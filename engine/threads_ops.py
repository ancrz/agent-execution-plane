"""
Engine: threads_ops.py (ONT-41 TC5: orquestacion de autoevol spec | verify | fix_test | heal)

Une los nucleos puros (`threads_spec`, `threads_verify`, `threads_heal`) con los efectos que inyecta `server.py`
(`run_tests`, `dispatch_job`, `poll_job`, `snapshot_fn`). Este modulo NO importa `server` (arista prohibida).

Reglas de diseno:
  - La barrera (`_barrier` del front, via `server.get_reload_barrier()`) se traduce a `BarrierState`; SERVING_LKG
    rechaza, RELOAD_PENDING/RELOAD_FAILED llevan datos estructurados (`retry_after_s`, `reason`).
  - Los motivos ambientales (SERVING_LKG, RELOAD_PENDING, BASE_UNAVAILABLE, SANDBOX_UNAVAILABLE) NO consumen una
    iteracion del ciclo: no son culpa del parche.
  - `fix_test` es re-entrante: cada llamada devuelve `awaiting` ("patch" | "job" | "reload") y las iteraciones
    restantes. La 3.a iteracion fallida es EXHAUSTED con la sugerencia de `heal`; NUNCA revierte por su cuenta.
  - Un EXHAUSTED/ACCEPTED registrado con tier < 6rw- permanece en el JSONL de eventos hasta que una llamada con
    tier >= 6rw- lo espeja al ledger (`mirror_events`).
  - Presupuestos terse (tokens ~ bytes/4, sobre el payload; el envoltorio los reserva en `ENVELOPE_RESERVE`):
    spec <= 400, verify/heal/fix_test <= 350; summary <= 1500.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from engine import threads as th
from engine import threads_events as ev
from engine import threads_heal, threads_pins
from engine import threads_verify as tv

SELECTION_CAP = 24  # B8: tope de tests por verify en ejecuciones no `apply` (la suite completa es del gate C4)
PIN_CALLER_CAP = 10  # G2: tope de pins heredados de callers publicos cuando se edita un helper privado (paridad con spec)
MIN_VERIFY_OCTAL = 5
MIN_APPLY_OCTAL = 6
TERSE_BUDGET = 350
SUMMARY_BUDGET = 1500
ENVELOPE_RESERVE = 130
ENVIRONMENTAL: frozenset[str] = frozenset(
    {tv.SERVING_LKG, tv.RELOAD_PENDING, tv.BASE_UNAVAILABLE, tv.SANDBOX_UNAVAILABLE, tv.WRONG_TREE}
)
_SHRINK_ORDER = ("detail", "warnings", "diff", "threads", "files", "reasons")
_AWAITING_BY_CAUSE: tuple[tuple[str, frozenset[str]], ...] = (
    ("base", frozenset({tv.BASE_UNAVAILABLE})),
    ("reload", frozenset({tv.RELOAD_PENDING, tv.SERVING_LKG, tv.RELOAD_BLOCKED})),
    ("env", frozenset({tv.SANDBOX_UNAVAILABLE, tv.WRONG_TREE})),
)
BARRIER_NA = "n/a"  # root no confiable/externo: la barrera de recarga del plano vivo no aplica (plano estatico)
HEAL_SUGGESTION = 'autoevol(action="heal")'
_HEAL_THREADS_TERSE = 3
_HEAL_THREADS_SUMMARY = 8
_HEAL_HUNKS = 2
_HEAL_HUNK_LINES = 20


def awaiting_for(reasons: set[str] | list[str]) -> str:
    """Que espera un rechazo ambiental, derivado de su causa: base | reload | env."""
    present = set(reasons)
    for name, causes in _AWAITING_BY_CAUSE:
        if present & causes:
            return name
    return "env"


def estimated_tokens(payload: dict[str, Any]) -> int:
    return max(1, round(len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")) / 4))


def fit(payload: dict[str, Any], budget: int) -> dict[str, Any]:
    """Recorta el payload (claves opcionales, luego listas) hasta caber en `budget - ENVELOPE_RESERVE` tokens."""
    limit = max(60, budget - ENVELOPE_RESERVE)
    out = dict(payload)
    for key in _SHRINK_ORDER:
        if estimated_tokens(out) <= limit:
            break
        val = out.get(key)
        if isinstance(val, list) and len(val) > 1:
            while estimated_tokens(out) > limit and len(out[key]) > 1:
                out[key] = out[key][: max(1, len(out[key]) // 2)]
            out["truncated"] = True
        elif val is not None:
            out.pop(key)
            out["truncated"] = True
    return out


def barrier_state(barrier: dict[str, Any] | None, serving_lkg: bool = False) -> tv.BarrierState | None:
    """Traduce el dict `_barrier` del front. `None` y sin LKG = analisis puramente estatico."""
    state = str((barrier or {}).get("state", ""))
    if serving_lkg or state == tv.SERVING_LKG:
        return tv.BarrierState(serving_lkg=True)
    if barrier is None:
        return None
    if state == "RELOAD_PENDING":
        return tv.BarrierState(generation_advanced=False)
    if state == "RELOAD_FAILED":
        err = str(barrier.get("error") or barrier.get("reason") or "failed")[:200]
        return tv.BarrierState(reload_error=err, reload_error_deterministic=True)
    return tv.BarrierState()


def barrier_info(barrier: dict[str, Any] | None) -> dict[str, Any]:
    """Subconjunto estructurado de la barrera para la respuesta (vacio si esta sana)."""
    if not barrier or barrier.get("state") in (None, "RELOAD_OK"):
        return {}
    keys = ("state", "reason", "retry_after_s", "error")
    return {k: barrier[k] for k in keys if barrier.get(k) not in (None, "")}


def test_node_args(test_ids: list[str]) -> list[str]:
    """`test:tests/x.py::t` -> `tests/x.py::t` (argumentos de pytest)."""
    return [t.removeprefix("test:") for t in test_ids]


def base_summary(
    tree: Path | str, snapshot: Path | str | None = None, *, allow_tree: bool = False
) -> tuple[dict[str, Any] | None, str]:
    """(resumen, origen). Origen: snapshot | head | tree. Sin base y sin `allow_tree` -> (None, '')."""
    with tv.base_tree(tree, snapshot=snapshot) as base_dir:
        if base_dir is not None:
            return tv.summarize(th.analyze(base_dir, use_cache=False)), ("snapshot" if snapshot else "head")
    if allow_tree:
        # m3: la base de la iteracion 0 es el propio arbol antes del parche; nunca se inventa.
        return tv.summarize(th.analyze(Path(tree), use_cache=False)), "tree"
    return None, ""


def resolve_target(base: dict[str, Any] | None, ref: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """AE-1: resuelve `ref` (id, ref `D-xx`, sufijo o subcadena) contra los gaps de la base congelada.

    Devuelve `(id_canónico, None)` o `(None, payload NOT_FOUND)`. Sin `ref` o sin base no resuelve nada.
    """
    if not ref or base is None:
        return ref, None
    meta = base.get("gap_meta", {})
    pool = [
        th.Gap(gid, "", "", 0.0, "", ref=str(meta.get(gid, ["", 0.0])[0]), score=float(meta.get(gid, ["", 0.0])[1]))
        for gid in base.get("gaps", [])
    ]
    gap, found = th.resolve_in(pool, ref)
    if gap is None:
        return None, {"status": "NOT_FOUND", "gap": ref[:80], "similar": found.get("similar", [])}
    return gap.id, None


def _direct_cover_tests(graph: Any, changed: list[str]) -> list[str]:
    """Tests con arista `covers` directa a un nodo cambiado o a lo que lo implementa."""
    found: set[str] = set()
    for cid in changed:
        if cid not in graph.nodes:
            continue
        targets = [cid, *(e.src for e in graph.in_edges(cid, "implemented_by"))]
        for tgt in targets:
            found.update(e.src for e in graph.in_edges(tgt, "covers") if graph.nodes[e.src].type == "test")
    return sorted(found)


def _transitive_depth1(graph: Any, changed: list[str]) -> list[str]:
    """Tests que cubren a los consumidores inmediatos (profundidad 1) de los nodos cambiados."""
    found: set[str] = set()
    for cid in changed:
        if cid not in graph.nodes:
            continue
        for e in graph.in_edges(cid):
            if e.kind not in th.HASH_EDGE_KINDS:
                continue
            for tgt in (e.src, *(i.src for i in graph.in_edges(e.src, "implemented_by"))):
                found.update(c.src for c in graph.in_edges(tgt, "covers") if graph.nodes[c.src].type == "test")
    return sorted(found)


def _pin_tests(graph: Any, changed: list[str], tree: Path | str, direct: list[str]) -> list[str]:
    """G2: pins directos de `changed` + hasta `PIN_CALLER_CAP` pins de callers del mismo modulo si `changed` es privado."""
    covered = set(direct)
    own_pins = [t for t in threads_pins.pinning_tests(graph, changed, tree) if t not in covered]
    priv_callers: list[str] = []
    for cid in changed:
        node = graph.nodes.get(cid)
        if node is None or node.type != "function" or node.attrs.get("public", True):
            continue
        mod = node.attrs.get("module")
        for e in graph.in_edges(cid, "consumes"):
            src = graph.nodes.get(e.src)
            if src is not None and src.type == "function" and src.attrs.get("module") == mod:
                priv_callers.append(e.src)
    if not priv_callers:
        return own_pins
    seen = covered | set(own_pins)
    trans_set = set(_transitive_depth1(graph, changed))
    raw_caller_pins = [t for t in threads_pins.pinning_tests(graph, priv_callers, tree) if t not in seen]
    caller_pins = sorted(raw_caller_pins, key=lambda t: (t not in trans_set, t))[:PIN_CALLER_CAP]
    return own_pins + caller_pins


def select_tests(
    analysis: th.Analysis, cmp: dict[str, Any], tree: Path | str, *, apply: bool = False
) -> tuple[list[str], dict[str, Any]]:
    """B8: own_tests -> covers directos -> pins (B7) -> transitivos prof. 1. Tope SELECTION_CAP salvo `apply`.

    Devuelve (ids `test:...` ordenados por prioridad y deduplicados, `selection`). `selection.partial` = el tope
    dejo tests fuera: el veredicto ACCEPT lo marca `partial:true` (nunca se aplica el tope con `apply`).
    """
    graph = analysis.graph
    changed = list(cmp["changed"])
    own = sorted(t for t in cmp["changed_tests"] if t in graph.nodes)
    direct = own + [t for t in _direct_cover_tests(graph, changed) if t not in own]
    tiers = [
        direct,
        _pin_tests(graph, changed, tree, direct),
        _transitive_depth1(graph, changed),
    ]
    ordered: list[str] = []
    seen: set[str] = set()
    sizes: list[int] = []
    for tier in tiers:
        fresh = [t for t in tier if t not in seen]
        seen.update(fresh)
        ordered.extend(fresh)
        sizes.append(len(fresh))
    direct_n, pins_n, trans_n = sizes
    kept = ordered if apply else ordered[:SELECTION_CAP]
    k_direct = min(direct_n, len(kept))
    k_pins = min(pins_n, max(0, len(kept) - direct_n))
    k_trans = max(0, len(kept) - direct_n - pins_n)
    selection: dict[str, Any] = {"direct": k_direct, "pins": k_pins, "transitive_dropped": trans_n - k_trans}
    head_dropped = (direct_n - k_direct) + (pins_n - k_pins)
    if head_dropped:
        selection["head_dropped"] = head_dropped  # el tope mordio tests directos/pins: es mas grave que descartar transitivos
    return kept, selection


_COPY_IGNORE = shutil.ignore_patterns(".git", ".venv", "__pycache__", "node_modules", ".pytest_cache")
_UNLISTED = "(unlisted)"
BaseRunner = Callable[[Path], Callable[[list[str]], dict[str, Any]]]


@contextlib.contextmanager
def base_with_patched_tests(
    tree: Path | str, snapshot: Path | str | None, test_args: list[str]
) -> Iterator[Path | None]:
    """E1: arbol BASE (snapshot o HEAD) con los directorios de test del arbol PARCHEADO superpuestos.

    Es el mismo codigo que la base pero con los tests (nuevos/modificados) del parche, para saber si fallan sin el fix.
    El snapshot nunca se muta (se copia). None -> BASE_UNAVAILABLE.
    """
    with tv.base_tree(tree, snapshot=snapshot) as base_dir:
        if base_dir is None:
            yield None
            return
        work = Path(tempfile.mkdtemp(prefix="aep_autoevol_e1_"))
        try:
            dest = work / "tree"
            if snapshot is not None:
                shutil.copytree(base_dir, dest, ignore=_COPY_IGNORE, symlinks=False)
            else:
                dest = base_dir
            patched = Path(tree)
            for top in sorted({a.split("::", 1)[0].split("/", 1)[0] for a in test_args if "/" in a}):
                src = patched / top
                if not src.is_dir():
                    continue
                shutil.rmtree(dest / top, ignore_errors=True)
                shutil.copytree(src, dest / top, ignore=_COPY_IGNORE, symlinks=False)
            for a in test_args:  # tests en la raiz (sin directorio)
                f = a.split("::", 1)[0]
                if "/" not in f and (patched / f).is_file():
                    shutil.copy2(patched / f, dest / f)
            yield dest
        finally:
            shutil.rmtree(work, ignore_errors=True)


def discriminate(
    base_runner: BaseRunner, tree: Path | str, snapshot: Path | str | None, impacted: list[str]
) -> dict[str, Any]:
    """Corre los tests seleccionados contra la BASE (con los tests del parche). `ids` = fallan en base (y pasan parcheados).

    Mismo runner por lotes y mismo tope que el verify (solo los seleccionados). Fallo de infraestructura -> `env`.
    """
    with base_with_patched_tests(tree, snapshot, impacted) as dest:
        if dest is None:
            return {"env": tv.BASE_UNAVAILABLE}
        res = tv.run_tests_batched(impacted, base_runner(dest))
    if res.get("wrong_tree"):
        return {"env": tv.WRONG_TREE}
    infra = res.get("available") is False or res.get("timeout") or res.get("no_summary")
    if infra or str(res.get("status", "")).upper() == tv.PENDING:
        return {"env": tv.SANDBOX_UNAVAILABLE}
    failing = {str(f) for f in res.get("failing", [])}
    ids = [a for a in impacted if a in failing or any(f.endswith(a) or a.endswith(f) for f in failing)]
    if not ids and int(res.get("failed", 0) or 0) + int(res.get("errors", 0) or 0) > 0:
        ids = [_UNLISTED]  # el runner no listo los nodos: hubo fallos en base, pero no se pueden nombrar
    return {"ids": ids}


def _discrimination_required(gap: str | None, cmp: dict[str, Any]) -> bool:
    """Drift/open_discrepancy como objetivo (o algun drift arreglado), o parche que toca codigo publico."""
    fixed_drift = any(str(g).startswith("drift:") for g in cmp.get("fixed", []))
    return bool(str(gap or "").startswith("drift:") or (not gap and fixed_drift) or cmp.get("touches_public"))


def judge(
    base: dict[str, Any] | None,
    tree: Path | str,
    *,
    gap: str | None,
    barrier: tv.BarrierState | None,
    run_tests: Callable[[list[str]], dict[str, Any]] | None,
    dispatch_job: Callable[[list[str]], dict[str, Any]] | None,
    trusted: bool,
    tests_result: dict[str, Any] | None = None,
    apply: bool = False,
    base_runner: BaseRunner | None = None,
    snapshot: Path | str | None = None,
) -> dict[str, Any]:
    """Una iteracion: analiza el arbol parcheado y decide contra la base congelada."""
    if base is None:
        return tv.decide(None, barrier=barrier, base_available=False)
    analysis = th.analyze(Path(tree), use_cache=False)
    new = tv.summarize(analysis)
    cmp = tv.compare(base, new)
    # F1: los nodos test: nuevos/cambiados forman parte de lo que debe ejecutarse (no solo covers^-1 del codigo).
    selected, selection = select_tests(analysis, cmp, tree, apply=apply)
    impacted = test_node_args(selected)
    if tests_result is not None:
        out = tv.decide(
            cmp, target_gap=gap, tests=tests_result, barrier=barrier, trusted=trusted, selected=len(impacted)
        )
        out["tests"] = {"mode": "async", "selected": len(impacted)}
    else:
        out = tv.verify_change(
            base,
            new,
            impacted_tests=impacted,
            target_gap=gap,
            run_tests=run_tests,
            dispatch_job=dispatch_job,
            barrier=barrier,
            trusted=trusted,
            batch_sync=True,
        )
    out["selection"] = selection
    if out.get("verdict") == tv.ACCEPT and _discrimination_required(gap, cmp):
        if base_runner is None:
            out.setdefault("warnings", []).append("discrimination unchecked")
        elif not impacted:
            tv.add_reasons(out, tv.NON_DISCRIMINATING)
        else:
            disc = discriminate(base_runner, tree, snapshot, impacted)
            if "env" in disc:
                tv.add_reasons(out, disc["env"])
            elif not disc["ids"]:
                tv.add_reasons(out, tv.NON_DISCRIMINATING)
            else:
                out["discriminating"] = disc["ids"][:SELECTION_CAP]
    if out.get("verdict") == tv.ACCEPT and (selection["transitive_dropped"] or selection.get("head_dropped")):
        out["partial"] = True  # el tope oculto tests: un ACCEPT no equivale a suite completa
    return out


def _verdict_payload(decision: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "OK", "verdict": decision["verdict"], "reasons": decision["reasons"]}
    for key in ("fixed", "gaps", "tests", "selection", "discriminating", "partial", "job", "detail", "warnings"):
        if key in decision:
            out[key] = decision[key]
    out.update(extra or {})
    return out


def run_verify(
    tree: Path | str,
    *,
    gap: str | None,
    snapshot: Path | str | None,
    barrier: dict[str, Any] | None,
    serving_lkg: bool,
    run_tests: Callable[[list[str]], dict[str, Any]] | None,
    dispatch_job: Callable[[list[str]], dict[str, Any]] | None,
    poll_job: Callable[[str], dict[str, Any]] | None,
    job: str | None,
    trusted: bool,
    terse: bool,
    apply: bool = False,
    base_runner: BaseRunner | None = None,
) -> dict[str, Any]:
    """`autoevol(verify)`: veredicto sin estado contra la base (snapshot o HEAD). Sin base: BASE_UNAVAILABLE."""
    base, source = base_summary(tree, snapshot)
    gap, missing = resolve_target(base, gap)
    if missing is not None:
        return missing
    state = barrier_state(barrier if trusted else None, serving_lkg and trusted)
    tests_result = poll_job(job) if (job and poll_job is not None) else None
    decision = judge(
        base,
        tree,
        gap=gap,
        barrier=state,
        run_tests=run_tests,
        dispatch_job=dispatch_job,
        trusted=trusted,
        tests_result=tests_result,
        apply=apply,
        base_runner=base_runner,
        snapshot=snapshot,
    )
    extra: dict[str, Any] = {"base": source} if source else {}
    binfo = barrier_info(barrier)
    if binfo:
        extra["barrier"] = binfo
    return fit(_verdict_payload(decision, extra), TERSE_BUDGET if terse else SUMMARY_BUDGET)


def run_fix_test(
    store: tv.CycleStore,
    tree: Path | str,
    *,
    gap: str | None,
    cycle: str | None,
    snapshot: Path | str | None,
    restart: bool,
    barrier: dict[str, Any] | None,
    serving_lkg: bool,
    run_tests: Callable[[list[str]], dict[str, Any]] | None,
    dispatch_job: Callable[[list[str]], dict[str, Any]] | None,
    poll_job: Callable[[str], dict[str, Any]] | None,
    job: str | None,
    trusted: bool,
    terse: bool,
    apply: bool = False,
    base_runner: BaseRunner | None = None,
    tree_fingerprint: Callable[[Path | str], str | None] | None = None,
) -> dict[str, Any]:
    """`autoevol(fix_test)` re-entrante. Sin `cycle` abre uno (base congelada); con `cycle` evalua el parche."""
    budget = TERSE_BUDGET if terse else SUMMARY_BUDGET
    if not cycle:
        return _open_cycle(store, tree, gap, snapshot, restart, budget)
    rec = store.load(cycle)
    if rec is None:
        return {"status": "NOT_FOUND", "cycle": str(cycle)[:16]}
    if rec["state"] == tv.EXPIRED:
        return {"status": tv.EXPIRED, "cycle": cycle, "next": "autoevol(fix_test, gap=..., restart=True)"}
    if rec["state"] in tv.TERMINAL_STATES:
        return {"status": "CLOSED", "state": rec["state"], "cycle": cycle}
    pending_job = job or rec.get("job")
    tests_result = poll_job(str(pending_job)) if (pending_job and poll_job is not None) else None
    # D-EV-1b: huella ANTES de juzgar (o la guardada al despachar, en la ruta async) y recomputada despues.
    fp_before = tree_fingerprint(tree) if tree_fingerprint is not None else None
    expected_fp = (rec.get("pending_fp") or fp_before) if tests_result is not None else fp_before
    decision = judge(
        rec["base"],
        tree,
        gap=rec["gap"],
        barrier=barrier_state(barrier if trusted else None, serving_lkg and trusted),
        run_tests=run_tests,
        dispatch_job=dispatch_job,
        trusted=trusted,
        tests_result=tests_result,
        apply=apply,
        base_runner=base_runner,
        snapshot=snapshot,
    )
    fp_after = tree_fingerprint(tree) if tree_fingerprint is not None else None
    if tree_fingerprint is not None and decision["verdict"] == tv.ACCEPT and fp_after != expected_fp:
        tv.add_reasons(decision, tv.TREE_MUTATED_DURING_JUDGE)  # no ambiental: consume iteracion
    if decision["verdict"] == tv.PENDING and fp_before:
        decision["pending_fp"] = rec.get("pending_fp") or fp_before
    binfo = barrier_info(barrier)
    reasons = set(decision["reasons"])
    if decision["verdict"] == tv.REJECT and reasons and reasons <= ENVIRONMENTAL:
        env = store.note_environmental(cycle, sorted(reasons))
        if env.get("exhausted"):
            out = _verdict_payload(
                {"verdict": tv.REJECT, "reasons": env.get("reasons") or [tv.ENV_RETRIES_EXHAUSTED]},
                {"cycle": cycle, "state": tv.EXHAUSTED, "consumed": False, "env_retries": env["count"]},
            )
            return fit(out, budget)
        out = _verdict_payload(decision, {"cycle": cycle, "consumed": False, "awaiting": awaiting_for(reasons)})
        out["env_retries"] = env.get("count", 0)
        out["iterations_left"] = max(0, rec["max_iterations"] - rec["iteration"])
        out["env_left"] = max(0, tv.MAX_ENV_RETRIES - out["env_retries"])
        if not trusted:
            out["barrier"] = BARRIER_NA
        elif binfo:
            out["barrier"] = binfo
        return fit(out, budget)
    to_record = decision
    if decision["verdict"] == tv.ACCEPT and tree_fingerprint is not None:
        # D-EV-1: el ACCEPT queda atado al arbol juzgado (huella inyectada) y a su raiz real.
        to_record = {**decision, "judged": {"tree": fp_before or "", "root": os.path.realpath(tree)}}
    recorded = store.record(cycle, to_record)
    state = recorded.get("state", "")
    left = max(0, rec["max_iterations"] - int(recorded.get("iteration", rec["iteration"])))
    awaiting = {tv.OPEN: "patch", tv.CYCLE_PENDING: "job"}.get(state)
    extra: dict[str, Any] = {
        "cycle": cycle,
        "state": state,
        "iterations_left": left,
        "env_left": max(0, tv.MAX_ENV_RETRIES - int(rec.get("env_retries", 0))),
    }
    if awaiting:
        extra["awaiting"] = awaiting
    if state == tv.EXHAUSTED:
        extra.update(suggest=HEAL_SUGGESTION, retry_after_s=recorded.get("retry_after_s", tv.LOCK_SECONDS))
    if not trusted:
        extra["barrier"] = BARRIER_NA
    elif binfo:
        extra["barrier"] = binfo
    return fit(_verdict_payload(decision, extra), budget)


def _open_cycle(
    store: tv.CycleStore, tree: Path | str, gap: str | None, snapshot: Path | str | None, restart: bool, budget: int
) -> dict[str, Any]:
    if not gap:
        return {"status": "ERROR", "error": "El parametro 'gap' es obligatorio para abrir un ciclo fix_test."}
    base, source = base_summary(tree, snapshot, allow_tree=True)
    if base is None:
        return {"status": "ERROR", "verdict": tv.REJECT, "reasons": [tv.BASE_UNAVAILABLE]}
    gap, missing = resolve_target(base, gap)
    if missing is not None or gap is None:
        return missing or {"status": "NOT_FOUND", "gap": ""}
    opened = store.open_cycle(gap, base, restart=restart)
    if opened.get("status") != "OK":
        return opened
    out = {
        "status": "OK",
        "cycle": opened["cycle_id"],
        "state": tv.OPEN,
        "awaiting": "patch",
        "iterations_left": tv.MAX_ITERATIONS,
        "env_left": tv.MAX_ENV_RETRIES,
        "base": source,
        "next": "apply the patch, then autoevol(fix_test, cycle=<cycle>)",
    }
    return fit(out, budget)


def _heal_thread(entry: dict[str, Any], terse: bool) -> dict[str, Any]:
    out: dict[str, Any] = {k: entry[k] for k in ("module", "file", "kinds", "restorable") if k in entry}
    if not terse:
        hunks = entry.get("diff", {}).get("hunks", [])[:_HEAL_HUNKS]
        out["diff"] = [{**h, "lines": h["lines"][:_HEAL_HUNK_LINES]} for h in hunks]
        if entry.get("syntax_error"):
            out["syntax_error"] = str(entry["syntax_error"])[:160]
    return out


def run_heal(
    tree: Path | str,
    *,
    apply: bool,
    octal: int,
    snapshot_fn: Callable[[list[str]], Any] | None,
    terse: bool,
    key: str | None = None,
) -> dict[str, Any]:
    """`autoevol(heal)`: lectura/dry-run por defecto (tier >= 4r--); `apply` exige tier >= 6rw- y snapshot previo."""
    if apply and octal < MIN_APPLY_OCTAL:
        return {"status": "PERMISSION_DENIED", "error": "heal con apply=True requiere tier >= 6rw-.", "applied": False}
    report = threads_heal.heal(tree, key=key, apply=apply, snapshot_fn=snapshot_fn)
    cap = _HEAL_THREADS_TERSE if terse else _HEAL_THREADS_SUMMARY
    out: dict[str, Any] = {
        "status": report["status"],
        "applied": bool(report.get("applied")),
        "files": report.get("files", [])[:cap],
        "threads": [_heal_thread(e, terse) for e in report.get("threads", [])[:cap]],
        "total_threads": len(report.get("threads", [])),
    }
    for passthrough in ("key", "restored", "remaining_syntax_errors", "error"):
        if report.get(passthrough):
            out[passthrough] = report[passthrough]
    return fit(out, TERSE_BUDGET if terse else SUMMARY_BUDGET)


def mirror_events(octal: int, tier_label: str, agent_id: str, db_path: Path | str | None = None) -> dict[str, Any]:
    """Espeja el JSONL de eventos al ledger con tier >= 6rw-. Fail-soft: nunca rompe la accion."""
    if octal < MIN_APPLY_OCTAL:
        return {"mirrored": 0, "reason": "tier < 6rw-"}
    from engine.db import get_rw_connection

    path = Path(db_path) if db_path is not None else th.default_db_path()
    try:
        conn = get_rw_connection(path, row_factory=False, load_vec=False)
        try:
            res = ev.mirror_to_ledger(conn, tier_octal=octal, tier_label=tier_label, agent_id=agent_id)
            conn.commit()
            return res
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - el espejo es best-effort
        return {"mirrored": 0, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
