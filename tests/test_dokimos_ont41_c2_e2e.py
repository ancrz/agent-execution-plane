"""Dokimos ONT-41 cycle 2: adversarial checks against the REAL sandbox runner (bwrap + pytest), no sandbox_run mocks."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest

import server
from engine import threads_verify as tv
from tests.test_ont41_ops import _run_in_worker


def _tree(root: Path, body: str) -> Path:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_x.py").write_text(body, encoding="utf-8")
    return root


def _decide(result: dict[str, Any], selected: int) -> dict[str, Any]:
    cmp = tv.compare(
        {"root": "r", "gaps": ["g"], "codep": [], "hashes": {}, "public": [], "direct": []},
        {"root": "r", "gaps": [], "codep": [], "hashes": {}, "public": [], "direct": []},
    )
    return tv.decide(cmp, tests=result, selected=selected)


def test_real_runner_executes_every_selected_test_beyond_20() -> None:
    """Real bwrap + repo .venv: 25 selected node ids -> ran == 25 (no truncation at 20)."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_ont42a_harness_reconnect.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    ids = [ln for ln in out.splitlines() if "::" in ln][:25]
    assert len(ids) == 25
    res = _run_in_worker(server._autoevol_test_runner(root, True), ids)
    if res.get("available") is False:
        pytest.skip("bwrap unavailable on this host")
    assert res["ran"] == 25 and res["exit_code"] == 0
    assert _decide(res, 25)["verdict"] == tv.ACCEPT
    assert _decide({**res, "ran": 20}, 25)["reasons"] == [tv.TESTS_FAIL]


@pytest.mark.xfail(
    strict=True,
    reason="F7: sandbox without pytest module exits 1 with zeros; classified TESTS_FAIL (consumes iteration)",
)
def test_real_runner_missing_pytest_module_is_environmental(tmp_path: Path) -> None:
    tree = _tree(tmp_path, "def test_ok():\n    assert True\n")
    res = _run_in_worker(server._autoevol_test_runner(tree, False), ["tests/test_x.py::test_ok"])
    assert res == {"available": False} or res.get("exit_code") is None


def test_real_runner_broken_venv_interpreter_is_environmental(tmp_path: Path) -> None:
    tree = _tree(tmp_path, "def test_ok():\n    assert True\n")
    py = tree / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    res = _run_in_worker(server._autoevol_test_runner(tree, False), ["tests/test_x.py::test_ok"])
    assert res == {"available": False}
    assert _decide(res, 1)["reasons"] == [tv.SANDBOX_UNAVAILABLE]


def test_untrusted_async_dispatch_never_reaches_pueue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def boom(**_kw: Any) -> str:
        raise AssertionError("untrusted tree must not be dispatched to pueue")

    monkeypatch.setattr(server, "async_job_dispatch", boom)
    assert _run_in_worker(server._autoevol_dispatcher(tmp_path, False), ["t"]) == {"job": None, "available": False}


def test_poller_job_without_summary_stays_pending_forever_documented(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known limitation (reported): a crashed async job (no pytest summary) is PENDING, never environmental."""
    import json

    async def fake(**_kw: Any) -> str:
        return json.dumps({"status": "OK", "output": "bash: .venv/bin/python: No such file or directory\\n"})

    monkeypatch.setattr(server, "async_job_dispatch", fake)
    assert _run_in_worker(server._autoevol_job_poller, "5") == {"status": "PENDING"}
