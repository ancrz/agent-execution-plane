"""ONT-41 TC5: autoevol spec | verify | fix_test | heal (barrera, ciclo re-entrante, tiers, runners, heal, espejo)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import anyio
import pytest

import aep_lkg
import server
from engine import threads
from engine import threads_events as ev
from engine import threads_ops as ops
from engine import threads_verify as tv
from engine.privilege import _PrivilegeCache, get_effective_chmod_tier

REPO = Path(__file__).resolve().parent.parent
GAP = "syntax_error:module:engine.m"


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    yield tmp_path
    _PrivilegeCache.reset()

GREEN = {"ran": 1, "passed": 1, "failed": 0, "errors": 0}
RED = {"ran": 1, "passed": 0, "failed": 1, "errors": 0}


def _call(**kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(server.autoevol(**kw)))


def _mini(root: Path, *, fixed: bool) -> Path:
    (root / "engine").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "engine" / "m.py").write_text("def _f():\n    return 1\n" if fixed else "def _f(:\n", encoding="utf-8")
    (root / "tests" / "test_m.py").write_text("from engine import m\n\n\ndef test_f():\n    assert m._f() == 1\n", encoding="utf-8")
    return root


@pytest.fixture
def trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> tuple[Path, Path]:
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(tmp_path / "shm"))
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    get_effective_chmod_tier(force_refresh=True)
    return _mini(tmp_path / "base", fixed=False), _mini(tmp_path / "new", fixed=True)


def _verify(new: Path, base: Path | None, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "gap": GAP, "snapshot": base, "barrier": None, "serving_lkg": False, "run_tests": lambda t: GREEN,
        "dispatch_job": None, "poll_job": None, "job": None, "trusted": True, "terse": True,
    }
    args.update(kw)
    return ops.run_verify(new, **args)


# --- spec -------------------------------------------------------------------------------------------------
def test_spec_terse_and_summary_budgets(isolated_home: Path) -> None:
    gap_id = threads.analyze(REPO).gaps[0].id
    terse = _call(action="spec", gap=gap_id, verbosity="terse")
    assert terse["status"] == "OK" and terse["t"]["tok"] <= 400, terse["t"]
    full = _call(action="spec", gap=gap_id)
    assert full["t"]["tok"] <= 1500, full["t"]
    assert _call(action="spec")["status"] == "ERROR"
    assert _call(action="spec", gap="nope:nope")["status"] == "NOT_FOUND"


# --- verify -----------------------------------------------------------------------------------------------
def test_verify_accepts_fixed_gap_and_runs_impacted_tests(trees: tuple[Path, Path]) -> None:
    base, new = trees
    seen: list[list[str]] = []

    def runner(tests: list[str]) -> dict[str, Any]:
        seen.append(tests)
        return GREEN

    res = _verify(new, base, run_tests=runner)
    assert res["verdict"] == tv.ACCEPT and res["base"] == "snapshot", res
    assert seen == [["tests/test_m.py::test_f"]]


def test_verify_rejects_failing_tests_and_missing_base(trees: tuple[Path, Path]) -> None:
    base, new = trees
    assert _verify(new, base, run_tests=lambda t: RED)["reasons"] == [tv.TESTS_FAIL]
    no_base = _verify(new, None)  # tmp no es repo git: nunca se inventa una base
    assert no_base["verdict"] == tv.REJECT and no_base["reasons"] == [tv.BASE_UNAVAILABLE]
    unsandboxed = _verify(new, base, run_tests=lambda t: {**GREEN, "unsandboxed": True}, trusted=False)
    assert unsandboxed["reasons"] == [tv.SANDBOX_UNAVAILABLE]


def test_verify_barrier_states_are_structured(trees: tuple[Path, Path]) -> None:
    base, new = trees
    lkg = _verify(new, base, barrier={"state": "SERVING_LKG", "reason": "serving_lkg"})
    assert tv.SERVING_LKG in lkg["reasons"] and lkg["verdict"] == tv.REJECT
    pend = _verify(new, base, barrier={"state": "RELOAD_PENDING", "reason": "backoff", "retry_after_s": 4.0})
    assert tv.RELOAD_PENDING in pend["reasons"] and pend["barrier"]["retry_after_s"] == 4.0
    failed = _verify(new, base, barrier={"state": "RELOAD_FAILED", "error": "SyntaxError"})
    assert tv.RELOAD_BLOCKED in failed["reasons"] and failed["barrier"]["error"] == "SyntaxError"
    assert tv.SERVING_LKG in _verify(new, base, serving_lkg=True)["reasons"]
    assert tv.SERVING_LKG not in _verify(new, base, barrier={"state": "SERVING_LKG"}, trusted=False)["reasons"]
    assert _verify(new, base, barrier={"state": "RELOAD_OK"})["verdict"] == tv.ACCEPT


def test_verify_async_job_pending_then_polled(trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    base, new = trees
    monkeypatch.setattr(tv, "TESTS_PER_ITERATION", 0)
    pending = _verify(new, base, dispatch_job=lambda t: {"job": "7"})
    assert pending["verdict"] == tv.PENDING and pending["job"] == "7"
    done = _verify(new, base, job="7", poll_job=lambda j: GREEN)
    assert done["verdict"] == tv.ACCEPT
    still = _verify(new, base, job="7", poll_job=lambda j: {"status": "PENDING"})
    assert still["verdict"] == tv.PENDING
    unavailable = _verify(new, base, dispatch_job=lambda t: {"job": None, "available": False})
    assert unavailable["reasons"] == [tv.SANDBOX_UNAVAILABLE]


def test_verify_tool_tier_gates_and_invalid_base(trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    base, new = trees
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    get_effective_chmod_tier(force_refresh=True)
    assert _call(action="verify", root=str(new), base=str(base))["status"] == "PERMISSION_DENIED"
    assert _call(action="fix_test", root=str(new), gap=GAP)["status"] == "PERMISSION_DENIED"
    monkeypatch.setenv("AEP_FORCE_TIER", "5r-x")
    get_effective_chmod_tier(force_refresh=True)
    assert _call(action="verify", root=str(new), base="/nonexistent/zzz")["status"] == "ERROR"
    monkeypatch.setattr(server, "_autoevol_test_runner", lambda tree, trusted: (lambda tests: GREEN))
    res = _call(action="verify", root=str(new), base=str(base), gap=GAP, verbosity="terse")
    assert res["verdict"] == tv.ACCEPT and res["t"]["tok"] <= 350, res["t"]


# --- fix_test ---------------------------------------------------------------------------------------------
def _fix(store: tv.CycleStore, new: Path, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "gap": None, "cycle": None, "snapshot": None, "restart": False, "barrier": None, "serving_lkg": False,
        "run_tests": lambda t: GREEN, "dispatch_job": None, "poll_job": None, "job": None, "trusted": True, "terse": True,
    }
    args.update(kw)
    return ops.run_fix_test(store, new, **args)


def test_fix_test_exhausts_on_third_failure_without_reverting(trees: tuple[Path, Path]) -> None:
    base, _new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    opened = _fix(store, base, gap=GAP)
    assert opened["awaiting"] == "patch" and opened["iterations_left"] == 3 and opened["base"] == "tree"
    cid = opened["cycle"]
    assert tv.valid_cycle_id(cid)
    broken = (base / "engine" / "m.py").read_text(encoding="utf-8")
    first = _fix(store, base, cycle=cid)
    assert first["verdict"] == tv.REJECT and first["awaiting"] == "patch" and first["iterations_left"] == 2
    assert _fix(store, base, cycle=cid)["iterations_left"] == 1
    last = _fix(store, base, cycle=cid)
    assert last["state"] == tv.EXHAUSTED and last["suggest"] == ops.HEAL_SUGGESTION and last["retry_after_s"] == tv.LOCK_SECONDS
    assert (base / "engine" / "m.py").read_text(encoding="utf-8") == broken  # nunca revierte
    assert _fix(store, base, cycle=cid)["status"] == "CLOSED"
    assert _fix(store, base, gap=GAP)["status"] == "LOCKED"
    assert _fix(store, base, gap=GAP, restart=True)["status"] == "OK"
    kinds = [e["kind"] for e in ev.read_events(base_dir=base.parent / "shm")]
    assert "cycle_terminal" in kinds


def test_fix_test_accepts_patch_and_environmental_reasons_do_not_consume(trees: tuple[Path, Path]) -> None:
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, base, gap=GAP)["cycle"]
    waiting = _fix(store, new, cycle=cid, barrier={"state": "RELOAD_PENDING", "retry_after_s": 2.0})
    assert waiting["consumed"] is False and waiting["iterations_left"] == 3 and waiting["awaiting"] == "reload"
    assert waiting["env_left"] == tv.MAX_ENV_RETRIES - 1 and waiting["barrier"] != ops.BARRIER_NA  # B6: causa=reload
    lkg = _fix(store, new, cycle=cid, serving_lkg=True)
    assert lkg["consumed"] is False and tv.SERVING_LKG in lkg["reasons"]
    done = _fix(store, new, cycle=cid)
    assert done["verdict"] == tv.ACCEPT and done["state"] == tv.ACCEPTED


def test_fix_test_errors_and_async_cycle(trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    assert _fix(store, base)["status"] == "ERROR"
    assert _fix(store, base, cycle="0123456789ab")["status"] == "NOT_FOUND"
    assert _fix(store, base, cycle="../../x")["status"] == "NOT_FOUND"
    monkeypatch.setattr(tv, "TESTS_PER_ITERATION", 0)
    cid = _fix(store, base, gap=GAP)["cycle"]
    pend = _fix(store, new, cycle=cid, dispatch_job=lambda t: {"job": "9"})
    assert pend["awaiting"] == "job" and pend["job"] == "9" and pend["iterations_left"] == 3
    final = _fix(store, new, cycle=cid, poll_job=lambda j: GREEN)  # el job guardado se sondea solo
    assert final["state"] == tv.ACCEPTED


# --- heal -------------------------------------------------------------------------------------------------
@pytest.fixture
def lkg_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "home"))
    code = tmp_path / "code"
    (code / "engine").mkdir(parents=True)
    (code / "server.py").write_text("X = 1\n", encoding="utf-8")
    (code / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (code / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    aep_lkg.save(code, generation=1, code_fingerprint="fp", schema_hash="sh", git_head="h")
    (code / "server.py").write_text("X = broken(\n", encoding="utf-8")
    return code


def test_heal_dry_run_apply_and_tier(lkg_code: Path, isolated_home: Path) -> None:
    snaps: list[list[str]] = []
    dry = ops.run_heal(lkg_code, apply=False, octal=4, snapshot_fn=None, terse=True)
    assert dry["status"] == "BROKEN" and dry["files"] == ["server.py"] and dry["applied"] is False
    denied = ops.run_heal(lkg_code, apply=True, octal=5, snapshot_fn=None, terse=False)
    assert denied["status"] == "PERMISSION_DENIED"
    need = ops.run_heal(lkg_code, apply=True, octal=6, snapshot_fn=None, terse=False)
    assert need["status"] == "SNAPSHOT_REQUIRED" and "broken" in (lkg_code / "server.py").read_text()
    done = ops.run_heal(lkg_code, apply=True, octal=6, snapshot_fn=lambda f: snaps.append(f) or {"status": "SUCCESS"}, terse=False)
    assert done["status"] == "HEALED" and snaps == [["server.py"]]
    assert (lkg_code / "server.py").read_text() == "X = 1\n"


def test_heal_tool_dry_run_budget_and_apply_gate(lkg_code: Path, monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", "5r-x")
    get_effective_chmod_tier(force_refresh=True)
    res = _call(action="heal", root=str(lkg_code), verbosity="terse")
    assert res["status"] == "BROKEN" and res["t"]["tok"] <= 350, res["t"]
    assert _call(action="heal", root=str(lkg_code), apply=True)["applied"] is False
    assert "broken" in (lkg_code / "server.py").read_text()


# --- espejo, presupuestos y runners -----------------------------------------------------------------------
def test_mirror_events_needs_tier_6_and_is_idempotent(tmp_path: Path, isolated_home: Path) -> None:
    ev.append_event("cycle_terminal", {"gap": "g", "state": "EXHAUSTED"}, base_dir=tmp_path / "shm")
    db = tmp_path / "ledger.db"
    assert ops.mirror_events(5, "5r-x", "t", db_path=db)["mirrored"] == 0
    import os

    os.environ["AEP_AUTOEVOL_DIR"] = str(tmp_path / "shm")
    try:
        first = ops.mirror_events(6, "6rw-", "t", db_path=db)
        again = ops.mirror_events(6, "6rw-", "t", db_path=db)
    finally:
        del os.environ["AEP_AUTOEVOL_DIR"]
    assert first["mirrored"] == 1 and again["mirrored"] == 0


def test_fit_shrinks_and_barrier_helpers() -> None:
    big = {"status": "OK", "detail": {"x": "y" * 4000}, "files": ["a"] * 400}
    out = ops.fit(big, 350)
    assert ops.estimated_tokens(out) <= 350 and out["truncated"] is True
    assert ops.barrier_state(None) is None and ops.barrier_state(None, serving_lkg=True).serving_lkg
    assert ops.barrier_info({"state": "RELOAD_OK"}) == {} and ops.barrier_info(None) == {}
    assert ops.test_node_args(["test:tests/a.py::t"]) == ["tests/a.py::t"]


def _fake_sandbox(payload: dict[str, Any]) -> Any:
    async def fake(**_kw: Any) -> str:
        return json.dumps(payload)

    return fake


def _run_in_worker(fn: Any, *args: Any) -> Any:
    async def main() -> Any:
        return await anyio.to_thread.run_sync(fn, *args)

    return anyio.run(main)


def test_test_runner_wraps_sandbox_run_parse_pytest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parsed = {"tool": "pytest", "passed": 2, "failed": 1, "errors": 0, "total": 3}
    monkeypatch.setattr(server, "sandbox_run", _fake_sandbox({"status": "EXEC_FAILED", "parsed": parsed}))
    run = server._autoevol_test_runner(tmp_path, True)
    assert _run_in_worker(run, ["tests/a.py::t"]) == {"ran": 3, "passed": 2, "failed": 1, "errors": 0}
    monkeypatch.setattr(server, "sandbox_run", _fake_sandbox({"status": "ERROR", "error": "Command timed out after 120 seconds"}))
    assert _run_in_worker(run, ["t"])["timeout"] is True
    bwrap_down = {"status": "EXEC_FAILED", "exit_code": 1, "stderr": "bwrap: No permissions to create new namespace"}
    monkeypatch.setattr(server, "sandbox_run", _fake_sandbox(bwrap_down))
    monkeypatch.setattr(server, "_autoevol_plain_pytest", lambda tree, cmd: {**GREEN, "unsandboxed": True})
    assert _run_in_worker(run, ["t"])["unsandboxed"] is True
    assert _run_in_worker(server._autoevol_test_runner(tmp_path, False), ["t"]) == {"available": False}
    monkeypatch.setattr(server, "sandbox_run", _fake_sandbox({"status": "DEGRADED"}))
    assert _run_in_worker(run, ["t"]) == {"available": False}
    assert server._autoevol_pytest_cmd(tmp_path, [f"t{i}" for i in range(33)]).count(" t") == 33  # F2: sin truncar


def test_dispatcher_and_poller_use_async_job_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "async_job_dispatch", _fake_sandbox({"status": "queued", "task_id": 5}))
    assert _run_in_worker(server._autoevol_dispatcher(tmp_path, True), ["t"]) == {"job": "5"}
    monkeypatch.setattr(server, "async_job_dispatch", _fake_sandbox({"status": "PUEUE_ERROR"}))
    assert _run_in_worker(server._autoevol_dispatcher(tmp_path, True), ["t"])["available"] is False
    assert server._autoevol_job_poller("abc") == {"available": False}
    log = {"status": "OK", "output": "...\\n2 passed in 1.2s\\n"}
    monkeypatch.setattr(server, "async_job_dispatch", _fake_sandbox(log))
    assert _run_in_worker(server._autoevol_job_poller, "5")["passed"] == 2
    monkeypatch.setattr(server, "async_job_dispatch", _fake_sandbox({"status": "OK", "output": "running"}))
    assert _run_in_worker(server._autoevol_job_poller, "5") == {"status": "PENDING"}


def test_every_new_action_is_directly_invoked_and_registered(trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Cobertura directa (action literal) de spec | verify | fix_test | heal: el grafo no debe dejarlas huerfanas."""
    base, new = trees
    monkeypatch.setattr(server, "_autoevol_test_runner", lambda tree, trusted: (lambda tests: GREEN))
    spec = json.loads(asyncio.run(server.autoevol(action="spec", gap=GAP, root=str(base), verbosity="terse")))
    assert spec["status"] == "OK"
    verify = json.loads(asyncio.run(server.autoevol(action="verify", root=str(new), base=str(base), gap=GAP)))
    assert verify["verdict"] == tv.ACCEPT
    opened = json.loads(asyncio.run(server.autoevol(action="fix_test", root=str(base), gap=GAP)))
    assert opened["awaiting"] == "patch"
    heal = json.loads(asyncio.run(server.autoevol(action="heal", root=str(new))))
    assert heal["status"] in ("NO_LKG", "CLEAN", "BROKEN", "LKG_INVALID")
    assert {"spec", "verify", "fix_test", "heal"} <= set(server._AUTOEVOL_ACTIONS)
    assert "evolve" not in server._AUTOEVOL_ACTIONS


def test_docs_and_playbook_carry_the_self_heal_rule() -> None:
    assert "SELF-HEAL (ONT-41" in server._INSTRUCTIONS and "lkg_restore" in server._INSTRUCTIONS
    recipe = json.loads(asyncio.run(server.discover(action="playbook", verbosity="summary")))["quick_reference"]["self_heal"]
    assert 'autoevol(action="heal")' in recipe and len(recipe.encode()) < 3000
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "Self-Healing N0-N3" in readme and '"fix_test"' in readme and "17_Tools" in readme


def test_async_job_dispatch_log_degrades_without_pueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """F8: el poller depende de la accion `log`; sin demonio pueue degrada (no cuelga)."""
    import asyncio

    monkeypatch.setattr(server, "_ensure_pueue_daemon", lambda: None)
    out = json.loads(asyncio.run(server.async_job_dispatch(action="log", task_id=5, verbosity="summary")))
    assert out["status"] == "DEGRADED"
