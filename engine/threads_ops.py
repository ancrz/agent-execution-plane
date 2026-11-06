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

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine import threads as th
from engine import threads_events as ev
from engine import threads_heal
from engine import threads_verify as tv

MIN_VERIFY_OCTAL = 5
MIN_APPLY_OCTAL = 6
TERSE_BUDGET = 350
SUMMARY_BUDGET = 1500
ENVELOPE_RESERVE = 130
ENVIRONMENTAL: frozenset[str] = frozenset(
    {tv.SERVING_LKG, tv.RELOAD_PENDING, tv.BASE_UNAVAILABLE, tv.SANDBOX_UNAVAILABLE}
)
_SHRINK_ORDER = ("detail", "warnings", "diff", "threads", "files", "reasons")
HEAL_SUGGESTION = 'autoevol(action="heal")'
_HEAL_THREADS_TERSE = 3
_HEAL_THREADS_SUMMARY = 8
_HEAL_HUNKS = 2
_HEAL_HUNK_LINES = 20


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
) -> dict[str, Any]:
    """Una iteracion: analiza el arbol parcheado y decide contra la base congelada."""
    if base is None:
        return tv.decide(None, barrier=barrier, base_available=False)
    analysis = th.analyze(Path(tree), use_cache=False)
    new = tv.summarize(analysis)
    cmp = tv.compare(base, new)
    # F1: los nodos test: nuevos/cambiados forman parte de lo que debe ejecutarse (no solo covers^-1 del codigo).
    own_tests = [t for t in cmp["changed_tests"] if t in analysis.graph.nodes]
    impacted = test_node_args(sorted(set(th.impacted_tests(analysis.graph, cmp["changed"])) | set(own_tests)))
    if tests_result is not None:
        out = tv.decide(
            cmp, target_gap=gap, tests=tests_result, barrier=barrier, trusted=trusted, selected=len(impacted)
        )
        out["tests"] = {"mode": "async", "selected": len(impacted)}
        return out
    return tv.verify_change(
        base,
        new,
        impacted_tests=impacted,
        target_gap=gap,
        run_tests=run_tests,
        dispatch_job=dispatch_job,
        barrier=barrier,
        trusted=trusted,
    )


def _verdict_payload(decision: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "OK", "verdict": decision["verdict"], "reasons": decision["reasons"]}
    for key in ("fixed", "gaps", "tests", "job", "detail", "warnings"):
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
) -> dict[str, Any]:
    """`autoevol(verify)`: veredicto sin estado contra la base (snapshot o HEAD). Sin base: BASE_UNAVAILABLE."""
    base, source = base_summary(tree, snapshot)
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
    decision = judge(
        rec["base"],
        tree,
        gap=rec["gap"],
        barrier=barrier_state(barrier if trusted else None, serving_lkg and trusted),
        run_tests=run_tests,
        dispatch_job=dispatch_job,
        trusted=trusted,
        tests_result=tests_result,
    )
    binfo = barrier_info(barrier)
    reasons = set(decision["reasons"])
    if decision["verdict"] == tv.REJECT and reasons and reasons <= ENVIRONMENTAL:
        env = store.note_environmental(cycle, sorted(reasons))
        if env.get("exhausted"):
            out = _verdict_payload(
                {"verdict": tv.REJECT, "reasons": [tv.ENV_RETRIES_EXHAUSTED]},
                {"cycle": cycle, "state": tv.EXHAUSTED, "consumed": False, "env_retries": env["count"]},
            )
            return fit(out, budget)
        out = _verdict_payload(decision, {"cycle": cycle, "consumed": False, "awaiting": "reload"})
        out["env_retries"] = env.get("count", 0)
        out["iterations_left"] = max(0, rec["max_iterations"] - rec["iteration"])
        if binfo:
            out["barrier"] = binfo
        return fit(out, budget)
    recorded = store.record(cycle, decision)
    state = recorded.get("state", "")
    left = max(0, rec["max_iterations"] - int(recorded.get("iteration", rec["iteration"])))
    awaiting = {tv.OPEN: "patch", tv.CYCLE_PENDING: "job"}.get(state)
    extra: dict[str, Any] = {"cycle": cycle, "state": state, "iterations_left": left}
    if awaiting:
        extra["awaiting"] = awaiting
    if state == tv.EXHAUSTED:
        extra.update(suggest=HEAL_SUGGESTION, retry_after_s=recorded.get("retry_after_s", tv.LOCK_SECONDS))
    if binfo:
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
    opened = store.open_cycle(gap, base, restart=restart)
    if opened.get("status") != "OK":
        return opened
    out = {
        "status": "OK",
        "cycle": opened["cycle_id"],
        "state": tv.OPEN,
        "awaiting": "patch",
        "iterations_left": tv.MAX_ITERATIONS,
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
