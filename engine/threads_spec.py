"""
Engine: threads_spec.py (ONT-41 TA2: mini-SDD determinista por gap)

`autoevol(spec)` convierte un gap abierto en una mini-SDD (RE as SDD: Specify -> Plan -> Tasks -> Validate) SIN
razonar: es una plantilla por tipo de gap más datos del grafo (alcance, tests impactados, nombre canónico).
El agente llamante escribe el parche; `verify` lo juzga.

Presupuestos de salida (tokens ~ bytes/4, igual que la telemetría): terse <= 400, summary <= 1500.
Topos: depende de `engine.threads` y `engine.matcher`; NO importa `server`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pathlib import Path

from engine import matcher, threads_pins, threads_spec_cache
from engine import threads as th

TERSE_MAX_TOKENS = 400
SUMMARY_MAX_TOKENS = 1500
_TERSE_TASKS = 3
_TERSE_TESTS = 3
_TERSE_PIN = 2
_SUMMARY_PIN = 10
_SIMILAR = 3
_SUMMARY_NODES = 8
_SUMMARY_FILES = 6

# Plantillas por arista faltante (dirección, tipo) de un gap de omisión: (qué, tarea).
_OMISSION: dict[tuple[str, str], tuple[str, str]] = {
    ("in", "covers"): (
        "A test must reference the thread directly (call it or invoke the action).",
        "Add a test that exercises {node} directly and asserts its observable contract.",
    ),
    ("in", "routes"): (
        "The thread must be discoverable through a capability or playbook route.",
        "Route {node} from a capability in engine/privilege.py (_CAPABILITIES) or a playbook.",
    ),
    ("in", "asserts"): (
        "The thread must be documented by at least one claim (README or docstring).",
        "Document {node} in README.md or in its docstring with the contract it honours.",
    ),
    ("out", "implemented_by"): (
        "The declared tool/action must have an implementing function.",
        "Implement the handler for {node} and wire it in the dispatch table.",
    ),
    ("out", "privileged_by"): (
        "The tool/action must declare its minimum tier.",
        "Declare the tier of {node} in the privilege tables.",
    ),
    ("out", "routes"): (
        "The capability must route to at least one tool/action.",
        "Map capability {node} to the tool or action that realises it.",
    ),
    ("out", "covers"): (
        "The test must exercise at least one project function, action or tool.",
        "Make {node} call the code it is meant to verify.",
    ),
    ("out", "asserts"): (
        "The budget must assert a tool/action.",
        "Attach budget {node} to a measured tool call.",
    ),
    ("in", "writes"): (
        "The table must have a writer.",
        "Write {node} from a function, or remove the unused table.",
    ),
}

# Plantillas por tipo de gap no-omisión: (qué, tarea).
_BY_KIND: dict[str, tuple[str, str]] = {
    "claim_drift": (
        "The declared value must equal the observed one.",
        "Align the declared claim {node} with the measured value ({detail}).",
    ),
    "open_discrepancy": (
        "The known discrepancy must be fixed and its strict xfail removed.",
        "Fix the root cause behind {ref} and drop the xfail marker of {node}.",
    ),
    "syntax_error": ("The module must parse.", "Fix the syntax error reported for {node} ({detail})."),
    "codependency": (
        "The cycle must become dependency or interdependency.",
        "Extract the shared logic of {node} into a third module or an interface.",
    ),
    "forbidden_edge": ("The forbidden import must disappear.", "Remove the import behind {node}; inject the callable."),
    "probe_drift": (
        "The runtime behaviour must honour its promise.",
        "Make the observed behaviour of {node} match the promise ({detail}).",
    ),
}

_PLAN_COMMON = (
    "Re-run autoevol(graph) on the patched tree and confirm the gap id is gone.",
    "Run only the impacted tests, then autoevol(verify).",
)


def _estimated_tokens(payload: dict[str, Any]) -> int:
    return max(1, round(len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")) / 4))


def _omission_parts(gap: th.Gap) -> tuple[str, str]:
    """(dirección, tipo de arista) desde `omission:<nodo>:<dir>:<kind>`; el nodo puede contener ':'."""
    body = gap.id.removeprefix("omission:")
    node_and_dir, _, kind = body.rpartition(":")
    _, _, direction = node_and_dir.rpartition(":")
    return direction, kind


def _files_for(analysis: th.Analysis, node_id: str) -> list[str]:
    graph = analysis.graph
    node = graph.nodes.get(node_id)
    if node is None:
        return []
    attrs = node.attrs
    if node.type == "function":
        mod = graph.nodes.get(f"module:{attrs.get('module', '')}")
        path = mod.attrs.get("path") if mod is not None else None
        return [str(path or str(attrs.get("module", "")).replace(".", "/") + ".py")]
    if node.type == "module":
        return [str(attrs.get("path", ""))]
    if node.type == "test":
        return [str(attrs.get("file", ""))]
    if node.type == "claim":
        return [str(attrs.get("file", ""))]
    if node.type in ("tool", "action"):
        impl = graph.out_edges(node_id, "implemented_by")
        if impl:
            return _files_for(analysis, impl[0].dst) or ["server.py"]
        return ["server.py"]
    if node.type == "state":
        return ["schemas/database.sql"]
    return []


def _change_targets(analysis: th.Analysis, gap: th.Gap) -> dict[str, list[str]]:
    """AE-2: dónde se edita realmente. Para open_discrepancy: test xfail -> covers -> implemented_by -> fn/archivos.

    Para el resto de gaps el objetivo es el propio nodo. El split pin/validate de los tests está en `build_spec` (B8).
    """
    graph = analysis.graph
    if gap.kind != "open_discrepancy":
        seeds = [gap.node]
    else:
        seeds = []
        for edge in graph.out_edges(gap.node, "covers"):
            dst = graph.nodes.get(edge.dst)
            if dst is None:
                continue
            impl = [e.dst for e in graph.out_edges(edge.dst, "implemented_by")] if dst.type in ("tool", "action") else []
            seeds.extend(impl or [edge.dst])
        seeds = seeds or [gap.node]
    nodes = list(dict.fromkeys(seeds))
    files = list(dict.fromkeys(f for n in nodes for f in _files_for(analysis, n) if f))
    return {"nodes": nodes, "files": files}


def canonical_name(analysis: th.Analysis, node_id: str) -> dict[str, Any]:
    """Nombre canónico coherente con el vocabulario del grafo, ordenando vecinos con el matcher compartido.

    Para funciones sin test propone `test_<modulo>_<función>`; evita colisiones con tests existentes.
    """
    graph = analysis.graph
    node = graph.nodes.get(node_id)
    leaf = node_id.rsplit(".", 1)[-1] if node is not None and node.type == "function" else node_id.split(":")[-1]
    words = re.findall(r"[a-z0-9]+", leaf.lower())
    docs = [
        {"key": n.id, "name": " ".join(re.findall(r"[a-z0-9]+", n.id.rsplit(".", 1)[-1].lower()))}
        for n in graph.nodes_of("function")
        if n.id != node_id
    ]
    neighbors = [r["key"] for r in matcher.rank(" ".join(words), docs, limit=_SIMILAR)]
    if node is not None and node.type == "function":
        mod = str(node.attrs.get("module", "")).rsplit(".", 1)[-1]
        base = f"test_{mod}_{'_'.join(words)}"
    else:
        base = "_".join(words) or "unnamed"
    taken = {n.attrs.get("name", "") for n in graph.nodes_of("test")}
    name = base
    suffix = 1
    while name in taken:
        suffix += 1
        name = f"{base}_{suffix}"
    return {"name": name, "neighbors": neighbors}


def _template(gap: th.Gap) -> tuple[str, str]:
    if gap.kind == "omission":
        what, task = _OMISSION.get(_omission_parts(gap), ("Close the missing edge.", "Connect {node} to the graph."))
    else:
        what, task = _BY_KIND.get(gap.kind, ("Resolve the gap.", "Resolve {node}."))
    fmt = {"node": gap.node, "detail": gap.detail, "ref": gap.ref or gap.id}
    return what.format(**fmt), task.format(**fmt)


def _fit(payload: dict[str, Any], budget: int, shrinkable: tuple[str, ...]) -> dict[str, Any]:
    """Recorta listas (de la última clave a la primera) hasta cumplir el presupuesto; marca `truncated`."""
    out = dict(payload)
    while _estimated_tokens(out) > budget and isinstance(out.get("validate"), dict) and out["validate"].get("tests"):
        out["validate"] = {**out["validate"], "tests": out["validate"]["tests"][: len(out["validate"]["tests"]) // 2]}
        out["truncated"] = True
    for key in shrinkable:
        while _estimated_tokens(out) > budget and isinstance(out.get(key), list) and out[key]:
            out[key] = out[key][: len(out[key]) // 2]
            out["truncated"] = True
    if _estimated_tokens(out) > budget:
        for key in ("neighbors", "plan"):
            out.pop(key, None)
        out["truncated"] = True
    change = out.get("change")
    while _estimated_tokens(out) > budget and isinstance(change, dict) and any(len(v) > 1 for v in change.values()):
        change = {k: v[: max(1, len(v) // 2)] for k, v in change.items()}
        out["change"] = change
    return out


def _tag_cache(spec: dict[str, Any], state: str, terse: bool) -> dict[str, Any]:
    out = {**spec, "cache": state}
    if terse and _estimated_tokens(out) > TERSE_MAX_TOKENS:
        out = _fit(out, TERSE_MAX_TOKENS, ("pin", "tests", "files"))
    return out


def cached_spec(
    analysis: th.Analysis, gap_id: str, *, terse: bool = False, db_path: Path | str | None = None, write: bool = True
) -> dict[str, Any]:
    """E2: `build_spec` con cache por hilos (ver `threads_spec_cache`). `write=False` consulta sin persistir.

    Fail-open: cualquier fallo del cache degrada a recalcular; el contenido de la spec es el mismo.
    """
    gap, _found = th.resolve_gap(analysis, gap_id)
    if gap is None:
        return build_spec(analysis, gap_id, terse=terse)
    try:
        db = Path(db_path) if db_path is not None else th.default_db_path()
        change = _change_targets(analysis, gap)
        deps = threads_spec_cache.thread_hashes(analysis, gap, change["nodes"])
        key = threads_spec_cache.cache_key(gap, terse, deps)
    except Exception:  # noqa: BLE001 - el cache jamas rompe `spec`
        return _tag_cache(build_spec(analysis, gap_id, terse=terse), "miss", terse)
    hit = threads_spec_cache._lookup(db, gap.id, terse, key)
    if hit is not None:
        return _tag_cache(hit, "hit", terse)
    spec = build_spec(analysis, gap_id, terse=terse)
    if write and spec.get("status") == "OK":
        threads_spec_cache._store(db, gap.id, terse, key, deps, spec)
    return _tag_cache(spec, "miss", terse)


def build_spec(analysis: th.Analysis, gap_id: str, *, terse: bool = False) -> dict[str, Any]:
    """Mini-SDD del gap `gap_id`: specify, plan, tasks, validate, alcance, tests impactados y nombre canónico."""
    gap, found = th.resolve_gap(analysis, gap_id)
    if gap is None:
        return {"status": "NOT_FOUND", "gap": gap_id, "similar": found.get("similar", [])}
    what, task = _template(gap)
    files = [f for f in _files_for(analysis, gap.node) if f]
    tests = th.impacted_tests(analysis.graph, [gap.node])
    name = canonical_name(analysis, gap.node)
    change = _change_targets(analysis, gap)
    # B8: `pin` = tests que fijan el comportamiento viejo del nodo a editar (B7); `validate.tests` = cobertura directa.
    covered = set(tests)
    pin = [
        t
        for t in threads_pins.pinning_tests(analysis.graph, change["nodes"] or [gap.node], getattr(analysis, "root", None))
        if t not in covered
    ]
    validate = {
        "gap_must_close": gap.id,
        "no_new_gaps": True,
        "codep": 0,
        "tests": tests,
        "next": "autoevol(verify)",
    }
    if terse:
        payload: dict[str, Any] = {
            "status": "OK",
            "gap": gap.id,
            "kind": gap.kind,
            "node": gap.node,
            "change": {"nodes": change["nodes"][:_TERSE_TASKS], "files": change["files"][:_TERSE_TASKS]},
            "tasks": [task],
            "name": name["name"],
            "tests": tests[:_TERSE_TESTS],
            "tests_total": len(tests),
        }
        if pin:
            payload["pin"] = pin[:_TERSE_PIN]
        if found:
            payload["alternatives"] = found["alternatives"]
        return _fit(payload, TERSE_MAX_TOKENS, ("pin", "tests", "files"))
    payload = {
        "status": "OK",
        "gap": {"id": gap.id, "kind": gap.kind, "node": gap.node, "ref": gap.ref, "score": gap.score, "reach": gap.reach},
        "specify": {"what": what, "detail": gap.detail},
        "plan": [f"Edit {', '.join(files) or 'the owning file'}.", *_PLAN_COMMON],
        "tasks": [task, "Keep every public change covered by a direct test."],
        "validate": validate,
        "scope": {"files": files, "reach": gap.reach},
        "change": {"nodes": change["nodes"][:_SUMMARY_NODES], "files": change["files"][:_SUMMARY_FILES]},
        "name": name,
    }
    payload["validate"] = {**validate, "tests": tests[:20], "tests_total": len(tests)}
    if pin:
        payload["validate"]["pin"] = pin[:_SUMMARY_PIN]
    if found:
        payload["alternatives"] = found["alternatives"]
    return _fit(payload, SUMMARY_MAX_TOKENS, ("plan", "tasks"))
