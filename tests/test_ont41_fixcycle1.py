"""ONT-41 fix cycle 1 (Dokimos F1-F5 + presupuesto del playbook terse): regresiones."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import server
from engine import threads_verify as tv
from tests.test_ont41_ops import GAP, GREEN, _run_in_worker, _verify, isolated_home, trees  # noqa: F401  (fixtures)


def _b(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"root": "r", "gaps": ["g1"], "codep": [], "hashes": {}, "public": [], "direct": []}
    base.update(kw)
    return base


# --- F1: tests nuevos/cambiados se ejecutan; sin tests ejecutados no hay ACCEPT -----------------------------
def test_new_failing_test_is_selected_and_rejects(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    (new / "tests" / "test_extra.py").write_text(
        "from engine import m\n\n\ndef test_boom():\n    assert m._f() == 2\n", encoding="utf-8"
    )
    seen: list[list[str]] = []

    def run(tests: list[str]) -> dict[str, Any]:
        seen.append(tests)
        return {"ran": len(tests), "passed": 0, "failed": 1, "errors": 0}

    out = _verify(new, base, run_tests=run)
    assert seen, out
    assert any("tests/test_extra.py::test_boom" in t for t in seen[0])
    assert out["verdict"] == tv.REJECT and tv.TESTS_FAIL in out["reasons"]


def test_no_impacted_tests_but_tests_touched_is_no_tests_executed() -> None:
    base = _b(hashes={"fn:a.f": "h"}, public=["fn:a.f"], direct=["fn:a.f"])
    new = {**base, "gaps": [], "hashes": {"fn:a.f": "h", "test:tests/t.py::test_x": "n"}}
    out = tv.verify_change(base, new, impacted_tests=[])
    assert out["verdict"] == tv.REJECT and out["reasons"] == [tv.NO_TESTS_EXECUTED]
    pub = {**new, "hashes": {"fn:a.f": "CHANGED"}}
    assert tv.verify_change(base, pub, impacted_tests=[])["reasons"] == [tv.NO_TESTS_EXECUTED]
    private_only = {**base, "gaps": [], "public": [], "hashes": {"fn:a.f": "CHANGED"}}
    assert tv.verify_change(base, private_only, impacted_tests=[])["verdict"] == tv.ACCEPT


# --- F2: 33 seleccionados -> 33 ejecutados ---------------------------------------------------------------
def test_33_selected_means_33_in_the_command_and_ran_must_cover_them(tmp_path: Path) -> None:
    tests = [f"tests/t.py::t{i}" for i in range(33)]
    assert server._autoevol_pytest_cmd(tmp_path, tests).count("tests/t.py::t") == 33
    new = _b(gaps=[])
    full = tv.verify_change(_b(), new, impacted_tests=tests, dispatch_job=lambda t: {"job": "7"})
    assert full["verdict"] == tv.PENDING and full["tests"]["selected"] == 33
    cmp = tv.compare(_b(), new)
    truncated = {"ran": 20, "passed": 20, "failed": 0, "errors": 0}
    assert tv.decide(cmp, tests=truncated, selected=33)["reasons"] == [tv.TESTS_FAIL]
    assert tv.decide(cmp, tests={**truncated, "ran": 33, "passed": 33}, selected=33)["verdict"] == tv.ACCEPT


# --- F3: async no trusted rechazado ----------------------------------------------------------------------
def test_untrusted_async_dispatch_is_refused_without_queueing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def boom(**_kw: Any) -> str:
        raise AssertionError("must not dispatch")

    monkeypatch.setattr(server, "async_job_dispatch", boom)
    dispatcher = server._autoevol_dispatcher(tmp_path, False)
    assert _run_in_worker(dispatcher, ["t"]) == {"job": None, "available": False}
    out = tv.verify_change(
        _b(), _b(gaps=[]), impacted_tests=[f"t{i}" for i in range(21)], dispatch_job=dispatcher, trusted=False
    )
    assert out["verdict"] == tv.REJECT and out["reasons"] == [tv.SANDBOX_UNAVAILABLE]


# --- F4: fallos de infraestructura = ambientales -----------------------------------------------------------
def _fake(payload: dict[str, Any]) -> Any:
    async def fake(**_kw: Any) -> str:
        return json.dumps(payload)

    return fake


_ZERO = {"tool": "pytest", "passed": 0, "failed": 0, "errors": 0, "total": 0}


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "EXEC_FAILED", "exit_code": 127, "stderr": ".venv/bin/python: not found"},
        {"status": "EXEC_FAILED", "exit_code": 126},
        {"status": "EXEC_FAILED", "exit_code": 1, "parsed": None},
        {"status": "EXEC_FAILED", "exit_code": 127, "parsed": _ZERO},
    ],
)
def test_infra_failures_are_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: dict[str, Any]
) -> None:
    monkeypatch.setattr(server, "sandbox_run", _fake(payload))
    result = _run_in_worker(server._autoevol_test_runner(tmp_path, True), ["t"])
    assert result == {"available": False}
    assert tv.decide(tv.compare(_b(), _b(gaps=[])), tests=result)["reasons"] == [tv.SANDBOX_UNAVAILABLE]


def test_exit_127_does_not_consume_iteration_and_env_retries_are_bounded(
    trees: tuple[Path, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base, new = trees
    monkeypatch.setattr(server, "sandbox_run", _fake({"status": "EXEC_FAILED", "exit_code": 127}))
    opened = json.loads(asyncio.run(server.autoevol(action="fix_test", root=str(base), gap=GAP)))
    cycle = opened["cycle"]
    for i in range(tv.MAX_ENV_RETRIES):
        out = json.loads(
            asyncio.run(server.autoevol(action="fix_test", root=str(new), cycle=cycle, verbosity="summary"))
        )
        assert out["reasons"] == [tv.SANDBOX_UNAVAILABLE], out
        assert out["consumed"] is False and out["iterations_left"] == tv.MAX_ITERATIONS
        assert out["env_retries"] == i + 1 and out["env_left"] == tv.MAX_ENV_RETRIES - (i + 1)
        assert out["awaiting"] == "env"  # B6: SANDBOX_UNAVAILABLE no espera una recarga
    final = json.loads(asyncio.run(server.autoevol(action="fix_test", root=str(new), cycle=cycle, verbosity="summary")))
    assert final["reasons"] == [tv.ENV_RETRIES_EXHAUSTED] and final["state"] == tv.EXHAUSTED
    again = json.loads(asyncio.run(server.autoevol(action="fix_test", root=str(new), cycle=cycle)))
    assert again["status"] == "CLOSED"


def test_note_environmental_closes_cycle_store(tmp_path: Path) -> None:
    store = tv.CycleStore(base_dir=tmp_path / "s")
    cid = store.open_cycle("g", _b())["cycle_id"]
    for i in range(tv.MAX_ENV_RETRIES):
        assert store.note_environmental(cid, [tv.SANDBOX_UNAVAILABLE]) == {"count": i + 1, "exhausted": False}
    assert store.note_environmental(cid, [tv.SANDBOX_UNAVAILABLE])["exhausted"] is True
    rec = store.load(cid)
    assert rec is not None and rec["state"] == tv.EXHAUSTED and rec["iteration"] == 0


# --- F5: ran == 0 no es verde -----------------------------------------------------------------------------
def test_zero_ran_is_not_green_and_exit_code_counts() -> None:
    cmp = tv.compare(_b(), _b(gaps=[]))
    zero = {"ran": 0, "passed": 0, "failed": 0, "errors": 0}
    assert tv.decide(cmp, tests=zero, selected=2)["reasons"] == [tv.TESTS_FAIL]
    assert tv.decide(cmp, tests={**GREEN, "ran": 1}, selected=2)["reasons"] == [tv.TESTS_FAIL]
    assert tv.decide(cmp, tests={**GREEN, "exit_code": 5})["reasons"] == [tv.TESTS_FAIL]
    assert tv.decide(cmp, tests={**GREEN, "exit_code": 0}, selected=1)["verdict"] == tv.ACCEPT
    out = tv.verify_change(_b(), _b(gaps=[]), impacted_tests=["t1"], run_tests=lambda t: zero)
    assert out["verdict"] == tv.REJECT and out["reasons"] == [tv.TESTS_FAIL]


def test_runner_reports_pytest_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    parsed = {"tool": "pytest", "passed": 1, "failed": 0, "errors": 0, "total": 1}
    monkeypatch.setattr(server, "sandbox_run", _fake({"status": "SUCCESS", "exit_code": 0, "parsed": parsed}))
    assert _run_in_worker(server._autoevol_test_runner(tmp_path, True), ["t"])["exit_code"] == 0


# --- Presupuesto del playbook terse -------------------------------------------------------------------------
@pytest.mark.parametrize("agent_id", ["dokimos", "an-unusually-long-agent-identifier-" + "x" * 40])
def test_terse_playbook_stays_under_3000_bytes(agent_id: str) -> None:
    raw = asyncio.run(server.discover(action="playbook", verbosity="terse", agent_id=agent_id))
    assert len(raw.encode("utf-8")) < 3000, len(raw.encode("utf-8"))
