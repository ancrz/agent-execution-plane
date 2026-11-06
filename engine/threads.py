"""
Engine: threads.py (ONT-40: `autoevol` Thread Graph core, read-only)

Grafo de hilos con integridad Merkle sobre la condensación SCC, detección de brechas por omisión
(`Req(t)`), drift declarado-vs-observado, ranking PageRank y selección de tests impactados.

Premisas (SDD ONT-40, P0/P1):
  - La extracción es ESTÁTICA (ast, re, hashlib): no ejecuta código del árbol destino. La capa de
    probes (DQ-2) es opt-in, vive en `threads_probes.py`, corre en un hijo aislado y sus observaciones
    quedan FUERA de R con su propio `obs_hash` (aristas `observes`).
  - Solo lectura sobre el árbol. Persistencia (`threads_gen`, ledger) solo con tier >= 6rw- (DQ-3).

Topos (dependencias de este módulo):
  threads -> threads_model, threads_extractors, threads_probes, db, security, privilege, fingerprint.
  PROHIBIDO: threads -> server (test AST en tests/test_ont40_threads_imports.py). `ToposGuard` se usa
  solo como oráculo de paridad en tests; el Tarjan y el Bernstein de aquí son propios.

Determinismo (F11): ninguna iteración depende del orden de hash ni de rutas absolutas; todo se ordena.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
import threading
import time
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine import threads_extractors as ex
from engine.db import get_db_connection, get_ro_connection, transaction_immediate
from engine.fingerprint import code_fingerprint
from engine.privilege import get_effective_chmod_tier
from engine.security import _AUDIT_LOCK, record_audit_event, sanitize_dict
from engine.threads_model import (
    COVERS_SEVERITY_BY_TYPE,
    HASH_EDGE_KINDS,
    OMISSION_SEVERITY,
    Gap,
    ThreadGraph,
    alias_members,
    copy_graph,
    is_alias,
    missing_edges,
)

logger = logging.getLogger("aep.threads")

GRAPH_SCHEMA_VERSION = "threads/1"

# Acciones previstas fuera de ONT-40 (spec/verify/heal/evolve): sin nodos, INVALID_ACTION en la tool.
_PLANNED_ACTIONS: tuple[str, ...] = ("spec", "verify", "heal", "evolve")

PAGERANK_DAMPING = 0.85
PAGERANK_ITERATIONS = 50
PAGERANK_DECIMALS = 6

# Umbral de octal mínimo (DQ-3 persistencia, F5 probes).
PERSIST_MIN_OCTAL = 6
PROBE_MIN_OCTAL = 5

# ---------------------------------------------------------------------------
# T2: Tarjan iterativo (SCC), clasificación Topos y Bernstein (traza horizontal)
# ---------------------------------------------------------------------------


def tarjan_scc(nodes: Iterable[str], adjacency: dict[str, list[str]]) -> list[list[str]]:
    """SCC por Tarjan iterativo, O(V+E). Devuelve componentes en orden topológico inverso (sumideros primero).

    Cada componente va ordenada; el recorrido usa nodos y vecinos ordenados, por lo que el resultado es
    determinista e independiente de PYTHONHASHSEED.
    """
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    for root in sorted(set(nodes)):
        if root in index_of:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, child_i = work.pop()
            if child_i == 0:
                index_of[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            neighbors = sorted(set(adjacency.get(v, [])))
            advanced = False
            for i in range(child_i, len(neighbors)):
                w = neighbors[i]
                if w not in index_of:
                    work.append((v, i + 1))
                    work.append((w, 0))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index_of[w])
            if advanced:
                continue
            if low[v] == index_of[v]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                components.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return components


def _module_of(node_id: str, graph: ThreadGraph) -> str:
    node = graph.nodes[node_id]
    if node.type == "module":
        return node_id.removeprefix("module:")
    return str(node.attrs.get("module", ""))


@dataclass(slots=True)
class SccReport:
    components: list[list[str]]  # todos los SCC (incluye tamaño 1)
    codependencies: list[list[str]]  # SCC de módulos/funciones que cruzan módulos sin contrato: BLOQUEAN
    interdependencies: list[list[str]]  # ciclos mediados por `contract`: válidos
    recursions: list[list[str]]  # ciclos dentro de un mismo módulo (recursión mutua): informativos
    lazy_only_codependencies: list[list[str]] = field(default_factory=list)  # desaparecen sin imports perezosos


def _dependency_adjacency(graph: ThreadGraph, *, include_lazy: bool) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {}
    for e in graph.edges(HASH_EDGE_KINDS):
        if not include_lazy and e.lazy:
            continue
        adj.setdefault(e.src, []).append(e.dst)
    return adj


def classify_sccs(graph: ThreadGraph) -> SccReport:
    """Clasificación Topos sobre `consumes` u `contract` (nunca `observes`, F6).

    - tamaño 1: dependencia (válida).
    - tamaño > 1 con una arista `contract` interna: interdependencia (válida).
    - tamaño > 1 todo dentro de un mismo módulo: recursión mutua (informativa).
    - tamaño > 1 cruzando módulos sin contrato: CO-DEPENDENCIA (bloquea).
    Los ciclos que solo existen por imports perezosos se anotan aparte (calibración T0).
    """
    adj = _dependency_adjacency(graph, include_lazy=True)
    comps = tarjan_scc(graph.nodes.keys(), adj)
    strict_adj = _dependency_adjacency(graph, include_lazy=False)
    strict_comps = {tuple(c) for c in tarjan_scc(graph.nodes.keys(), strict_adj) if len(c) > 1}

    codep: list[list[str]] = []
    inter: list[list[str]] = []
    recur: list[list[str]] = []
    lazy_only: list[list[str]] = []
    for comp in comps:
        if len(comp) < 2:
            continue
        members = set(comp)
        has_contract = any(
            e.kind == "contract" and e.src in members and e.dst in members for m in comp for e in graph.out_edges(m)
        )
        modules = {_module_of(m, graph) for m in comp}
        if has_contract:
            inter.append(comp)
        elif len(modules) == 1 and all(graph.nodes[m].type == "function" for m in comp):
            recur.append(comp)
        else:
            codep.append(comp)
            if tuple(comp) not in strict_comps:
                lazy_only.append(comp)
    return SccReport(comps, codep, inter, recur, lazy_only)


def bernstein_hazards(graph: ThreadGraph) -> list[dict[str, Any]]:
    """Traza horizontal (SDD §2.2): escritores de un mismo estado en módulos distintos sin `contract` común.

    W(a) ∩ (R(b) ∪ W(b)) ≠ ∅ entre funciones de distinto módulo, sin arista `contract` hacia el estado,
    produce un hazard (WARN, no bloquea ni cuenta como gap). Determinista y ordenado.
    """
    hazards: list[dict[str, Any]] = []
    for state in graph.nodes_of("state"):
        writers = sorted({e.src for e in graph.in_edges(state.id, "writes")})
        readers = sorted({e.src for e in graph.in_edges(state.id, "reads")} - set(writers))
        if graph.in_edges(state.id, "contract") or graph.out_edges(state.id, "contract"):
            continue
        writer_modules = sorted({_module_of(w, graph) for w in writers})
        if len(writer_modules) >= 2:
            hazards.append(
                {
                    "state": state.id,
                    "kind": "write-write",
                    "modules": writer_modules,
                    "writers": writers,
                }
            )
        elif writers and readers:
            reader_modules = sorted({_module_of(r, graph) for r in readers} - set(writer_modules))
            if reader_modules:
                hazards.append(
                    {
                        "state": state.id,
                        "kind": "write-read",
                        "modules": sorted(set(writer_modules) | set(reader_modules)),
                        "writers": writers,
                    }
                )
    return hazards


# ---------------------------------------------------------------------------
# T3: Merkle R sobre la condensación SCC
# ---------------------------------------------------------------------------


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def merkle_root(graph: ThreadGraph) -> tuple[str, dict[str, str]]:
    """Raíz Merkle R del grafo semántico y hash por nodo.

    h(n) = SHA256(tipo ‖ id ‖ hash_contenido ‖ sort(h(hijos por consumes/contract))). Los ciclos se
    condensan: todos los miembros de un SCC comparten el hash de la componente. R = SHA256 de los hashes
    de las componentes sin padres, ordenados. `observes` y el resto de aristas no entran (F6).
    """
    adj = _dependency_adjacency(graph, include_lazy=True)
    comps = tarjan_scc(graph.nodes.keys(), adj)  # sumideros primero: los hijos ya están hasheados
    comp_of: dict[str, int] = {}
    for i, comp in enumerate(comps):
        for m in comp:
            comp_of[m] = i

    comp_hash: dict[int, str] = {}
    has_parent: set[int] = set()
    child_comps: dict[int, list[int]] = {}
    for i, comp in enumerate(comps):
        kids = sorted({comp_of[d] for m in comp for d in adj.get(m, []) if comp_of[d] != i})
        child_comps[i] = kids
        has_parent.update(kids)

    node_hash: dict[str, str] = {}
    for i, comp in enumerate(comps):
        kid_hashes = sorted(comp_hash[k] for k in child_comps[i])
        if len(comp) == 1:
            n = graph.nodes[comp[0]]
            comp_hash[i] = _sha(n.type, n.id, n.content_hash, *kid_hashes)
        else:
            members = [graph.nodes[m] for m in comp]
            base = [f"{n.type}|{n.id}|{n.content_hash}" for n in members]
            comp_hash[i] = _sha("scc", *base, *kid_hashes)
        for m in comp:
            node_hash[m] = comp_hash[i]

    roots = sorted(comp_hash[i] for i in range(len(comps)) if i not in has_parent)
    return _sha(GRAPH_SCHEMA_VERSION, *roots), dict(sorted(node_hash.items()))


# ---------------------------------------------------------------------------
# T9: PageRank, alcance (blast radius) e impacted_tests
# ---------------------------------------------------------------------------


def pagerank(graph: ThreadGraph) -> dict[str, float]:
    """PageRank (0.85, 50 iteraciones) sobre `consumes`/`contract`. Redondeado a 6 decimales, determinista."""
    ids = sorted(graph.nodes)
    n = len(ids)
    if n == 0:
        return {}
    out: dict[str, list[str]] = {}
    for e in graph.edges(HASH_EDGE_KINDS):
        out.setdefault(e.src, []).append(e.dst)
    rank = dict.fromkeys(ids, 1.0 / n)
    for _ in range(PAGERANK_ITERATIONS):
        dangling = sum(rank[i] for i in ids if not out.get(i))
        base = (1.0 - PAGERANK_DAMPING) / n + PAGERANK_DAMPING * dangling / n
        new = dict.fromkeys(ids, base)
        for src in ids:
            targets = sorted(set(out.get(src, [])))
            if targets:
                share = PAGERANK_DAMPING * rank[src] / len(targets)
                for dst in targets:
                    new[dst] += share
        rank = new
    return {i: round(rank[i], PAGERANK_DECIMALS) for i in ids}


def _anchor(graph: ThreadGraph, node_id: str) -> str:
    """Hilo de implementación de un nodo: tools y acciones apuntan a su función; el resto, a sí mismos."""
    node = graph.nodes[node_id]
    if node.type in ("tool", "action"):
        impl = graph.out_edges(node_id, "implemented_by")
        if impl:
            return impl[0].dst
    return node_id


def reverse_reach(graph: ThreadGraph, start: str) -> set[str]:
    """Cierre transitivo inverso sobre consumes/contract (blast radius), incluyendo el propio nodo."""
    seen = {start}
    queue = [start]
    while queue:
        cur = queue.pop()
        for e in graph.in_edges(cur):
            if e.kind in HASH_EDGE_KINDS and e.src not in seen:
                seen.add(e.src)
                queue.append(e.src)
    return seen


def impacted_tests(graph: ThreadGraph, changed: Iterable[str]) -> list[str]:
    """impacted_tests(Δ) = covers⁻¹(alcance(nodos_cambiados)) (SDD §8). Ordenado y determinista."""
    functions_of: dict[str, list[str]] = {}
    for n in graph.nodes_of("function"):
        functions_of.setdefault(str(n.attrs.get("module", "")), []).append(n.id)
    affected: set[str] = set()
    for c in sorted(set(changed)):
        if c not in graph.nodes:
            continue
        affected |= reverse_reach(graph, c)
    expanded = set(affected)
    for nid in sorted(affected):
        node = graph.nodes[nid]
        if node.type == "module":
            expanded.update(functions_of.get(nid.removeprefix("module:"), []))
        for e in graph.in_edges(nid, "implemented_by"):
            expanded.add(e.src)
    tests: set[str] = set()
    for nid in expanded:
        for e in graph.in_edges(nid, "covers"):
            if graph.nodes[e.src].type == "test":
                tests.add(e.src)
    return sorted(tests)


# ---------------------------------------------------------------------------
# T8: Req(t) -> gaps, drift D = G_declarado △ G_observado
# ---------------------------------------------------------------------------

_DRIFT_KINDS = ("tool_count", "capability_count", "wf_range", "version")
_DRIFT_SEVERITY = 0.7
_OPEN_DISCREPANCY_SEVERITY = 0.8
# Umbral de probes derivado de la promesa del README (la compacidad de `verbosity`).
PROBE_SCHEMA_SUMMARY_MAX_TOKENS = 3000


def observed_metrics(src: ex.Sources, graph: ThreadGraph) -> dict[str, str]:
    """Realidad medida del árbol (AST/regex): lo que los claims declaran se compara contra esto."""
    metrics = {
        "tool_count": str(len(graph.nodes_of("tool"))),
        "capability_count": str(len(graph.nodes_of("capability"))),
    }
    priv = src.code.get("engine/privilege.py")
    if priv is not None:
        ids = set(re.findall(r'"id":\s*"WF-(\d+)"', priv.text))
        if ids:
            metrics["wf_range"] = str(max(int(i) for i in ids))
    pyproject = src.texts.get("pyproject.toml", "")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if m:
        metrics["version"] = m.group(1)
    return metrics


def _drift_ref(kind: str, file: str) -> str:
    if kind == "version":
        return "D-12"
    return "D-14" if file == "README.md" else "D-11"


def claim_drift(graph: ThreadGraph, observed: dict[str, str]) -> list[Gap]:
    """Claims vigentes (no históricos) cuyo valor declarado difiere del observado."""
    gaps: list[Gap] = []
    for claim in graph.nodes_of("claim"):
        kind = str(claim.attrs.get("kind", ""))
        if kind not in _DRIFT_KINDS or claim.attrs.get("hist") or kind not in observed:
            continue
        declared = str(claim.attrs.get("value", ""))
        if declared == observed[kind]:
            continue
        where = f"{claim.attrs.get('file')}:{claim.attrs.get('line')}"
        gaps.append(
            Gap(
                id=f"drift:claim:{claim.id}",
                kind="claim_drift",
                node=claim.id,
                severity=_DRIFT_SEVERITY,
                detail=f"{kind}: declared {declared}, observed {observed[kind]} ({where})",
                ref=_drift_ref(kind, str(claim.attrs.get("file", ""))),
            )
        )
    return gaps


def open_discrepancies(graph: ThreadGraph) -> list[Gap]:
    """Tests xfail estrictos con razón `D-xx`: discrepancias conocidas y abiertas (drift ya medido por el repo)."""
    return [
        Gap(
            id=f"drift:open:{t.attrs['xfail_ref']}:{t.id}",
            kind="open_discrepancy",
            node=t.id,
            severity=_OPEN_DISCREPANCY_SEVERITY,
            detail=f"xfail strict {t.attrs['xfail_ref']} in {t.attrs.get('file')}",
            ref=str(t.attrs["xfail_ref"]),
        )
        for t in graph.nodes_of("test")
        if t.attrs.get("xfail_ref")
    ]


def _weakly_covered(graph: ThreadGraph) -> set[str]:
    """Funciones alcanzadas por `consumes` desde un nodo con cobertura directa (cobertura débil).

    Req fuerte (cobertura directa) rige para tool/acción; para funciones basta la débil: un test que
    ejercita `analyze()` cubre transitivamente lo que `analyze()` consume. Una función que nadie
    referencia desde código cubierto sigue siendo un gap.
    """
    seeds = [nid for nid in graph.nodes if graph.in_edges(nid, "covers")]
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        cur = queue.pop()
        for e in graph.out_edges(cur, "consumes"):
            if e.dst not in seen:
                seen.add(e.dst)
                queue.append(e.dst)
        for e in graph.out_edges(cur, "implemented_by"):
            if e.dst not in seen:
                seen.add(e.dst)
                queue.append(e.dst)
    return {n for n in seen if graph.nodes[n].type == "function"}


def omission_gaps(graph: ThreadGraph) -> list[Gap]:
    """Gap(n) = Req(tipo(n)) \\ aristas(n). Funciones: solo públicas. Estado: solo tablas."""
    gaps: list[Gap] = []
    weak = _weakly_covered(graph)
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        if node.type == "function" and (not node.attrs.get("public") or nid in weak):
            continue
        if node.type == "state" and node.attrs.get("kind") != "table":
            continue
        if is_alias(graph, nid):
            continue  # D-23: un alias delega en su acción canónica
        inherited = alias_members(graph, nid)
        for direction, kind in missing_edges(graph, node):
            if direction == "in" and any(graph.in_edges(a, kind) for a in inherited):
                continue  # la canónica hereda covers/asserts/routes de sus alias
            sev = OMISSION_SEVERITY.get((direction, kind), 0.3)
            if (direction, kind) == ("in", "covers"):
                sev = COVERS_SEVERITY_BY_TYPE.get(node.type, sev)
            gaps.append(
                Gap(
                    id=f"omission:{nid}:{direction}:{kind}",
                    kind="omission",
                    node=nid,
                    severity=sev,
                    detail=f"{node.type} lacks {direction} '{kind}' edge",
                )
            )
    return gaps


def structural_gaps(graph: ThreadGraph, scc: SccReport) -> list[Gap]:
    """SyntaxError, co-dependencias y la arista prohibida `threads -> server`."""
    gaps: list[Gap] = []
    for mod in graph.nodes_of("module"):
        err = mod.attrs.get("syntax_error")
        if err:
            gaps.append(Gap(f"syntax_error:{mod.id}", "syntax_error", mod.id, 1.0, f"{mod.attrs.get('path')}: {err}"))
    for comp in scc.codependencies:
        suffix = " (only via lazy imports)" if comp in scc.lazy_only_codependencies else ""
        gaps.append(
            Gap(
                f"codep:{_sha(*comp)[:12]}",
                "codependency",
                comp[0],
                1.0,
                f"co-dependency among {len(comp)} nodes{suffix}: {' <-> '.join(comp[:4])}",
            )
        )
    for e in graph.edges({"consumes"}):
        if e.src.startswith("module:engine.threads") and e.dst == "module:server":
            gaps.append(Gap(f"forbidden_edge:{e.src}->{e.dst}", "forbidden_edge", e.src, 1.0, "threads must not import server"))
    return gaps


def probe_gaps(observations: list[dict[str, Any]]) -> list[Gap]:
    """Observaciones de probes que contradicen una promesa. Un timeout NO es un gap (O-8, fail-open)."""
    gaps: list[Gap] = []
    for obs in observations:
        if obs.get("ok", True):
            continue
        gaps.append(
            Gap(
                id=f"drift:probe:{obs['probe']}",
                kind="probe_drift",
                node=str(obs.get("node", "module:server")),
                severity=0.9,
                detail=str(obs.get("detail", "")),
                ref=str(obs.get("ref", "")),
            )
        )
    return gaps


# ---------------------------------------------------------------------------
# T10: analyze() y caché por hash de insumos + code_fingerprint
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Analysis:
    root: Path
    graph: ThreadGraph
    root_hash: str
    node_hash: dict[str, str]
    scc: SccReport
    hazards: list[dict[str, Any]]
    gaps: list[Gap]
    rank: dict[str, float]
    info: ex.ExtractionInfo
    inputs_hash: str
    code_fp: str
    elapsed_ms: float
    git_commit: str = "unknown"
    probes: dict[str, Any] | None = None
    obs_hash: str = ""
    cached: bool = False


_CACHE: dict[tuple[str, str, str, str], Analysis] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 4


def git_head(root: Path) -> str:
    """Commit corto de `root` (fail-soft)."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=2, check=False
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _score(graph: ThreadGraph, rank: dict[str, float], gaps: list[Gap]) -> None:
    n = max(len(graph.nodes), 1)
    reach_cache: dict[str, int] = {}
    for g in gaps:
        if g.node not in graph.nodes:
            continue
        anchor = _anchor(graph, g.node)
        if anchor not in reach_cache:
            reach_cache[anchor] = len(reverse_reach(graph, anchor))
        centrality = rank.get(anchor, 1.0 / n) * n
        g.reach = reach_cache[anchor]
        g.score = round(g.severity * centrality * g.reach, 6)


def sort_gaps(gaps: list[Gap]) -> list[Gap]:
    return sorted(gaps, key=lambda g: (-g.score, -g.severity, g.id))


def _analysis_fields(a: Analysis) -> dict[str, Any]:
    return {f: getattr(a, f) for f in Analysis.__slots__}


def analyze(root: Path | str, *, use_cache: bool = True) -> Analysis:
    """Extracción estática completa: grafo, R, SCC, hazards, gaps y ranking. Sin ejecutar código del árbol."""
    start = time.perf_counter()
    base = Path(root).resolve()
    src = ex.read_sources(base)
    inputs = src.inputs_hash()
    fp = code_fingerprint(base)
    key = (str(base), inputs, fp, sys.version.split()[0])
    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit is not None:
            return Analysis(**{**_analysis_fields(hit), "cached": True})
    graph, info = ex.build_graph(src)
    scc = classify_sccs(graph)
    root_hash, node_hash = merkle_root(graph)
    hazards = bernstein_hazards(graph)
    rank = pagerank(graph)
    observed = observed_metrics(src, graph)
    gaps = [
        *structural_gaps(graph, scc),
        *omission_gaps(graph),
        *claim_drift(graph, observed),
        *open_discrepancies(graph),
    ]
    _score(graph, rank, gaps)
    analysis = Analysis(
        root=base,
        graph=graph,
        root_hash=root_hash,
        node_hash=node_hash,
        scc=scc,
        hazards=hazards,
        gaps=sort_gaps(gaps),
        rank=rank,
        info=info,
        inputs_hash=inputs,
        code_fp=fp,
        elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
        git_commit=git_head(base),
    )
    if use_cache:
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = analysis
    return analysis


def clear_cache() -> None:
    """Vacía la caché de análisis (tests y recarga)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def with_probes(analysis: Analysis, probes: dict[str, Any]) -> Analysis:
    """Añade observaciones de probes SIN alterar R: aristas `observes` en una copia y su propio `obs_hash`."""
    observations = list(probes.get("observations", []))
    graph = copy_graph(analysis.graph)
    for obs in observations:
        graph.add_edge("module:server", str(obs.get("node", "")), "observes")
    extra = probe_gaps(observations)
    _score(graph, analysis.rank, extra)
    obs_hash = _sha(json.dumps(observations, sort_keys=True, default=str))
    existing = {g.id for g in analysis.gaps}
    merged = sort_gaps([*analysis.gaps, *(g for g in extra if g.id not in existing)])
    fields = _analysis_fields(analysis)
    fields.update(graph=graph, gaps=merged, probes=probes, obs_hash=obs_hash)
    return Analysis(**fields)


# ---------------------------------------------------------------------------
# F12: hilos propios de autoevol (la tool debe detectar sus propios gaps)
# ---------------------------------------------------------------------------

_OWN_PREFIXES = (
    "tool:autoevol",
    "action:autoevol:",
    "fn:server.autoevol",
    "fn:engine.threads",
    "module:engine.threads",
    "state:threads_gen",
    "budget:autoevol",
    "test:tests/test_ont40",
)


def own_gaps(analysis: Analysis) -> list[Gap]:
    """Gaps cuyo nodo pertenece a `autoevol` (tool, acciones, módulos threads*, su tabla y sus tests)."""
    return [g for g in analysis.gaps if g.node.startswith(_OWN_PREFIXES)]


# ---------------------------------------------------------------------------
# Payloads de lectura (graph / gaps / thread)
# ---------------------------------------------------------------------------


def graph_payload(analysis: Analysis, *, terse: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {
        "root": analysis.root_hash[:16] if terse else analysis.root_hash,
        "nodes": len(analysis.graph.nodes),
        "edges": analysis.graph.edge_count(),
        "gaps_open": len(analysis.gaps),
        "codep": len(analysis.scc.codependencies),
        "own_gaps": len(own_gaps(analysis)),
    }
    if terse:
        return base
    base.update(
        {
            "types": analysis.graph.type_counts(),
            "scc": {
                "codependencies": [c[:6] for c in analysis.scc.codependencies[:10]],
                "interdependencies": len(analysis.scc.interdependencies),
                "recursions": len(analysis.scc.recursions),
                "lazy_only_codependencies": len(analysis.scc.lazy_only_codependencies),
            },
            "hazards": len(analysis.hazards),
            "py_version": analysis.info.py_version,
            "git_commit": analysis.git_commit,
            "code_fingerprint": analysis.code_fp,
            "extraction_ms": analysis.elapsed_ms,
            "extraction_errors": analysis.info.errors[:10],
            "cached": analysis.cached,
            "limits": "static extraction; heuristic coverage is strong for tools/actions and weak for functions",
        }
    )
    if analysis.probes is not None:
        base["probes"] = {"status": analysis.probes.get("status"), "obs_hash": analysis.obs_hash}
    return base


def gaps_payload(analysis: Analysis, *, limit: int = 10, kind: str | None = None) -> dict[str, Any]:
    pool = [g for g in analysis.gaps if kind is None or g.kind == kind]
    by_kind: dict[str, int] = {}
    for g in analysis.gaps:
        by_kind[g.kind] = by_kind.get(g.kind, 0) + 1
    return {
        "gaps_open": len(analysis.gaps),
        "by_kind": dict(sorted(by_kind.items())),
        "refs": sorted({g.ref for g in analysis.gaps if g.ref}),
        "own_gaps": len(own_gaps(analysis)),
        "gaps": [
            {"id": g.id, "kind": g.kind, "node": g.node, "score": g.score, "reach": g.reach, "ref": g.ref, "detail": g.detail}
            for g in pool[: max(limit, 0)]
        ],
        "total_matching": len(pool),
    }


def thread_payload(analysis: Analysis, node_id: str, *, limit: int = 20) -> dict[str, Any]:
    """Inspección de un hilo: aristas, alcance, centralidad, hash e `impacted_tests` (solo lectura)."""
    node = analysis.graph.nodes.get(node_id)
    if node is None:
        near = sorted(n for n in analysis.graph.nodes if node_id and node_id in n)[:5]
        return {"status": "NOT_FOUND", "node": node_id, "similar": near}
    anchor = _anchor(analysis.graph, node_id)
    reach = reverse_reach(analysis.graph, anchor)
    n = max(len(analysis.graph.nodes), 1)
    tests = impacted_tests(analysis.graph, [node_id])
    return {
        "status": "OK",
        "node": node_id,
        "type": node.type,
        "hash": analysis.node_hash.get(node_id, ""),
        "content_hash": node.content_hash,
        "out": [{"kind": e.kind, "to": e.dst} for e in analysis.graph.out_edges(node_id)][:limit],
        "in": [{"kind": e.kind, "from": e.src} for e in analysis.graph.in_edges(node_id)][:limit],
        "reach": len(reach),
        "centrality": round(analysis.rank.get(anchor, 1.0 / n) * n, 6),
        "missing": [f"{d}:{k}" for d, k in missing_edges(analysis.graph, node)],
        "impacted_tests": tests[:limit],
        "impacted_tests_total": len(tests),
    }


# ---------------------------------------------------------------------------
# T11: persistencia `threads_gen` + ledger (tier >= 6rw-), log y diff
# ---------------------------------------------------------------------------

THREADS_GEN_DDL = """CREATE TABLE IF NOT EXISTS threads_gen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    git_commit TEXT NOT NULL DEFAULT '',
    code_fingerprint TEXT NOT NULL DEFAULT '',
    py_version TEXT NOT NULL DEFAULT '',
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    gaps_open INTEGER NOT NULL DEFAULT 0,
    codep_count INTEGER NOT NULL DEFAULT 0,
    snapshot_z BLOB
)"""


def default_db_path() -> Path:
    """Ruta de la BD de AEP, resuelta al llamar (respeta HOME en tests)."""
    return Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"


def _snapshot(analysis: Analysis) -> bytes:
    pairs = [[nid, analysis.node_hash[nid]] for nid in sorted(analysis.node_hash)]
    payload = {"n": pairs, "g": sorted(g.id for g in analysis.gaps)}
    return zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"), 6)


def _load_snapshot(blob: bytes | None) -> dict[str, Any]:
    if not blob:
        return {"n": [], "g": []}
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except (zlib.error, ValueError):
        return {"n": [], "g": []}


def persist_generation(
    analysis: Analysis,
    *,
    db_path: Path | str | None = None,
    tier_octal: int | None = None,
    agent_id: str = "autoevol",
) -> dict[str, Any]:
    """Persiste la generación (DQ-3: solo tier >= 6rw-). Idempotente por R.

    Orden de locks FIJO (F4, C6): `_AUDIT_LOCK` -> `transaction_immediate`. INSERT OR IGNORE sobre
    `root_hash UNIQUE`; el ledger se escribe SOLO si `rowcount == 1` (R nuevo). Las columnas propias pasan
    por `sanitize_dict` antes de escribirse.
    """
    eff = get_effective_chmod_tier()
    octal = int(eff["octal"]) if tier_octal is None else tier_octal
    tier_label = str(eff["tier"])
    if octal < PERSIST_MIN_OCTAL:
        return {"persisted": False, "reason": f"tier {octal} < {PERSIST_MIN_OCTAL} (6rw-)"}
    row = sanitize_dict(
        {
            "root_hash": analysis.root_hash,
            "created_at": datetime.now(UTC).isoformat(),
            "git_commit": analysis.git_commit,
            "code_fingerprint": analysis.code_fp,
            "py_version": analysis.info.py_version,
            "node_count": len(analysis.graph.nodes),
            "edge_count": analysis.graph.edge_count(),
            "gaps_open": len(analysis.gaps),
            "codep_count": len(analysis.scc.codependencies),
        }
    )
    path = Path(db_path) if db_path is not None else default_db_path()
    conn = get_db_connection(path)
    ledger: dict[str, Any] = {}
    try:
        with _AUDIT_LOCK, transaction_immediate(conn):
            conn.execute(THREADS_GEN_DDL)
            cur = conn.execute(
                "INSERT OR IGNORE INTO threads_gen (root_hash, created_at, git_commit, code_fingerprint, py_version, "
                "node_count, edge_count, gaps_open, codep_count, snapshot_z) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["root_hash"],
                    row["created_at"],
                    row["git_commit"],
                    row["code_fingerprint"],
                    row["py_version"],
                    row["node_count"],
                    row["edge_count"],
                    row["gaps_open"],
                    row["codep_count"],
                    _snapshot(analysis),
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                ledger = record_audit_event(
                    conn,
                    agent_id,
                    "autoevol",
                    "graph_generation",
                    tier_label,
                    "RECORDED",
                    details={
                        "root": analysis.root_hash,
                        "nodes": row["node_count"],
                        "edges": row["edge_count"],
                        "gaps_open": row["gaps_open"],
                        "commit": analysis.git_commit,
                    },
                    target=analysis.root_hash[:12],
                )
    finally:
        conn.close()
    return {"persisted": True, "inserted": inserted, "ledger_entry": str(ledger.get("entry_hash", ""))[:16]}


def _ro(db_path: Path | str | None) -> sqlite3.Connection | None:
    path = Path(db_path) if db_path is not None else default_db_path()
    if not path.exists():
        return None
    try:
        return get_ro_connection(path)
    except sqlite3.Error:
        return None


def list_generations(*, db_path: Path | str | None = None, limit: int = 10) -> dict[str, Any]:
    """Historial de generaciones (solo lectura). Tolera BD o tabla ausentes."""
    conn = _ro(db_path)
    if conn is None:
        return {"generations": [], "total": 0, "note": "no database"}
    try:
        rows = conn.execute(
            "SELECT id, root_hash, created_at, git_commit, node_count, edge_count, gaps_open, codep_count "
            "FROM threads_gen ORDER BY id DESC LIMIT ?",
            (max(limit, 1),),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM threads_gen").fetchone()[0]
    except sqlite3.OperationalError:
        return {"generations": [], "total": 0, "note": "threads_gen absent"}
    finally:
        conn.close()
    return {"generations": [dict(r) for r in rows], "total": int(total)}


def _find_generation(conn: sqlite3.Connection, ref: str) -> sqlite3.Row | None:
    if ref.isdigit():
        return conn.execute("SELECT * FROM threads_gen WHERE id = ?", (int(ref),)).fetchone()
    return conn.execute(
        "SELECT * FROM threads_gen WHERE root_hash LIKE ? ORDER BY id DESC LIMIT 1", (ref.replace("%", "") + "%",)
    ).fetchone()


def diff_generations(
    a: str,
    b: str | None = None,
    *,
    db_path: Path | str | None = None,
    current: Analysis | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Diff semántico entre dos R (ids de generación o prefijos). `b` omitido => análisis actual."""
    conn = _ro(db_path)
    if conn is None:
        return {"status": "NO_GENERATIONS", "note": "no database"}
    try:
        row_a = _find_generation(conn, a)
        row_b = _find_generation(conn, b) if b else None
        snap_a = _load_snapshot(row_a["snapshot_z"]) if row_a is not None else None
        snap_b = _load_snapshot(row_b["snapshot_z"]) if row_b is not None else None
    except sqlite3.OperationalError:
        return {"status": "NO_GENERATIONS", "note": "threads_gen absent"}
    finally:
        conn.close()
    if row_a is None or snap_a is None or (b and row_b is None):
        return {"status": "NOT_FOUND", "a": a, "b": b}
    if row_b is not None and snap_b is not None:
        root_b = str(row_b["root_hash"])
    elif current is not None:
        snap_b = {"n": [[k, v] for k, v in sorted(current.node_hash.items())], "g": sorted(g.id for g in current.gaps)}
        root_b = current.root_hash
    else:
        return {"status": "NOT_FOUND", "a": a, "b": b, "note": "no current analysis"}
    na = {k: v for k, v in snap_a["n"]}
    nb = {k: v for k, v in snap_b["n"]}
    added = sorted(set(nb) - set(na))
    removed = sorted(set(na) - set(nb))
    changed = sorted(k for k in set(na) & set(nb) if na[k] != nb[k])
    ga, gb = set(snap_a["g"]), set(snap_b["g"])
    impacted = impacted_tests(current.graph, [*added, *changed]) if current is not None else []
    return {
        "status": "OK",
        "a": row_a["root_hash"],
        "b": root_b,
        "identical": row_a["root_hash"] == root_b,
        "added": added[:limit],
        "removed": removed[:limit],
        "changed": changed[:limit],
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
        "gaps_new": sorted(gb - ga)[:limit],
        "gaps_resolved": sorted(ga - gb)[:limit],
        "impacted_tests": impacted[:limit],
        "impacted_tests_total": len(impacted),
    }
