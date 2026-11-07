"""ONT-43 adversarial (Dokimos): confinement of a malicious repro in the REAL bwrap sandbox + sig/path injection via the tool."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import anyio.to_thread
import pytest

import server
from engine import threads_field
from engine.privilege import _PrivilegeCache

SIG = "0123456789ab"
ROOT = Path(__file__).resolve().parent.parent

MALICIOUS = """import pytest, socket, pathlib


@pytest.mark.xfail(strict=True, reason="FR-0123456789ab side effects")
def test_bug():
    out = {}
    try:
        pathlib.Path("PWNED.txt").write_text("x")
        out["write"] = True
    except OSError:
        out["write"] = False
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        out["net"] = True
    except OSError:
        out["net"] = False
    if out["write"] or out["net"]:
        return  # escaped confinement: the test PASSES, strict xfail => not promoted
    assert False, out
"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(state))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    yield tmp_path
    _PrivilegeCache.reset()


def _call(**kw: object) -> dict[str, Any]:
    return json.loads(asyncio.run(server.autoevol(**kw)))  # type: ignore[arg-type]


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap missing")
def test_malicious_repro_cannot_write_repo_or_reach_net(env: Path) -> None:
    tree = env / "tree"
    (tree / "tests" / "field").mkdir(parents=True)
    (tree / "engine").mkdir()
    (tree / "engine" / "__init__.py").write_text("")
    (tree / "tests" / "field" / f"test_fr_{SIG}.py").write_text(MALICIOUS)
    assert _call(action="report", sig=SIG, report={"tool": "t", "observed": "IGNORE PREVIOUS"})["status"] == "RECORDED"
    res = _call(action="report", sig=SIG, repro_test=f"tests/field/test_fr_{SIG}.py::test_bug", root=str(tree))
    assert not (tree / "PWNED.txt").exists(), "repro wrote into the repo: sandbox not confining"
    assert not (tree / "tests" / "field" / "PWNED.txt").exists()
    assert "IGNORE" not in json.dumps(res)
    assert res["status"] == "PROMOTED", res  # promoted only if write AND net were both denied inside the sandbox


@pytest.mark.parametrize("sig", ["../../etc/x", "0123456789abc", "0123456789a", "x;rm -rf", "0123456789ag"])
def test_tool_rejects_malformed_sig_and_records_nothing(env: Path, sig: str) -> None:
    res = _call(action="report", sig=sig, report={"tool": "t", "observed": "o"})
    assert res["status"] == "ERROR"
    assert threads_field.list_candidates() == []


@pytest.mark.parametrize(
    "repro",
    ["../x.py::t", "/abs/tests/field/test_fr_0123456789ab.py::t", "tests/field/../field/test_fr_0123456789ab.py::t"],
)
def test_tool_promote_rejects_traversal(env: Path, repro: str) -> None:
    tree = env / "tree"
    (tree / "tests" / "field").mkdir(parents=True)
    _call(action="report", sig=SIG, report={"tool": "t", "observed": "o"})
    res = _call(action="report", sig=SIG, repro_test=repro, root=str(tree))
    assert res["status"] == "INVALID_REPRO"
    assert threads_field.promoted_sigs() == set()


@pytest.mark.parametrize("trusted", [True, False])
def test_promotion_fails_closed_when_bwrap_broken_even_for_own_tree(
    env: Path, monkeypatch: pytest.MonkeyPatch, trusted: bool
) -> None:
    """F1: repro de campo = codigo no confiable; bwrap caido => SANDBOX_UNAVAILABLE, nunca pytest plano."""
    tree = env / "tree"
    (tree / "tests" / "field").mkdir(parents=True)
    repro = (
        "import pytest\n\n\n"
        f'@pytest.mark.xfail(strict=True, reason="FR-{SIG} bug")\n'
        "def test_bug():\n    assert False\n"
    )
    (tree / "tests" / "field" / f"test_fr_{SIG}.py").write_text(repro)
    threads_field.record_report(SIG, "t", "a", "i", "e", "o", octal=6)
    monkeypatch.setattr(
        server, "_autoevol_interpreter", lambda _t: {"ro_paths": [], "python": "python", "venv": str(tree)}
    )
    monkeypatch.setattr(server, "_autoevol_pytest_cmd", lambda *_a, **_k: "pytest -q")

    async def broken_bwrap(**_kw: object) -> str:
        return json.dumps(
            {"status": "EXEC_FAILED", "exit_code": 1, "stderr": "bwrap: setting up uid map: Permission denied"}
        )

    calls: list[str] = []

    def spy(_tree: Path, cmd: str) -> dict[str, Any]:
        calls.append(cmd)
        return {"xfailed": 1}

    monkeypatch.setattr(server, "sandbox_run", broken_bwrap)
    monkeypatch.setattr(server, "_autoevol_plain_pytest", spy)

    async def go() -> dict[str, Any]:
        return await anyio.to_thread.run_sync(
            server._autoevol_report, tree, 6, trusted, SIG, f"tests/field/test_fr_{SIG}.py::test_bug", None, 10
        )

    res = asyncio.run(go())
    assert res["status"] == "SANDBOX_UNAVAILABLE", res
    assert calls == []
    assert threads_field.promoted_sigs() == set()
