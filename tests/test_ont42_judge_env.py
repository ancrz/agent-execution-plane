"""ONT-42b B5 (AE-3): cadena de interprete, ro_paths explicitos, centinela WRONG_TREE (condiciones 3, 4, 5 de Ontos)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import server
from engine import threads_ops as ops
from engine import threads_verify as tv
from tests.test_ont41_fixcycle1 import _b
from tests.test_ont41_ops import _run_in_worker

CANON_VENV = Path(sys.prefix)


def _capture(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake(**kw: Any) -> str:
        seen.update(kw)
        return json.dumps(payload)

    monkeypatch.setattr(server, "sandbox_run", fake)
    return seen


def test_worktree_without_venv_uses_canonical_and_mounts_explicit_ro_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ok = {"status": "SUCCESS", "exit_code": 0, "parsed": {"tool": "pytest", "passed": 1, "total": 1}}
    seen = _capture(monkeypatch, ok)
    out = _run_in_worker(server._autoevol_test_runner(tmp_path, True), ["t"])
    assert out["ran"] == 1
    ro = seen["ro_paths"]
    assert str(tmp_path.resolve()) in ro and str(CANON_VENV.resolve()) in ro and len(ro) == 3
    assert str(server.REPO_ROOT.resolve()) not in ro  # C3: nunca REPO_ROOT
    assert seen["command"].startswith(str(CANON_VENV.resolve() / "bin" / "python"))
    assert seen["env"]["PYTHONPATH"] == str(tmp_path.resolve())
    assert seen["working_dir"] == str(tmp_path)


def test_tree_venv_has_priority_over_canonical(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    interp = server._autoevol_interpreter(tmp_path)
    assert interp is not None and interp["python"] == str(venv.resolve() / "bin" / "python")


def test_no_interpreter_anywhere_is_sandbox_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(server, "_autoevol_canonical_venv", lambda: tmp_path / "nope")
    seen = _capture(monkeypatch, {"status": "SUCCESS", "exit_code": 0})
    result = _run_in_worker(server._autoevol_test_runner(tmp_path, True), ["t"])
    assert result == {"available": False} and not seen  # ni siquiera se invoca sandbox_run
    assert tv.decide(tv.compare(_b(), _b(gaps=[])), tests=result)["reasons"] == [tv.SANDBOX_UNAVAILABLE]
    assert server._autoevol_dispatcher(tmp_path, True)(["t"]) == {"job": None, "available": False}


def test_exit_97_maps_to_wrong_tree_before_env_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for payload in (
        {"status": "EXEC_FAILED", "exit_code": 97},
        {"status": "EXEC_FAILED", "exit_code": 97, "parsed": None, "stderr": "bwrap: x"},
    ):
        _capture(monkeypatch, payload)
        result = _run_in_worker(server._autoevol_test_runner(tmp_path, True), ["t"])
        assert result == {"wrong_tree": True}
        assert tv.decide(tv.compare(_b(), _b(gaps=[])), tests=result)["reasons"] == [tv.WRONG_TREE]


def test_wrong_tree_is_registered_and_environmental() -> None:
    assert tv.REJECT_REASONS.index(tv.WRONG_TREE) == tv.REJECT_REASONS.index(tv.SANDBOX_UNAVAILABLE) + 1
    assert tv.WRONG_TREE in ops.ENVIRONMENTAL


def test_second_consecutive_wrong_tree_exhausts_immediately(tmp_path: Path) -> None:
    store = tv.CycleStore(base_dir=tmp_path / "s")
    cid = store.open_cycle("g", _b())["cycle_id"]
    first = store.note_environmental(cid, [tv.WRONG_TREE])
    assert first == {"count": 1, "exhausted": False}
    second = store.note_environmental(cid, [tv.WRONG_TREE])
    assert second["exhausted"] is True and second["reasons"] == [tv.WRONG_TREE]
    assert store.load(cid)["state"] == tv.EXHAUSTED


def test_non_consecutive_wrong_tree_does_not_exhaust(tmp_path: Path) -> None:
    store = tv.CycleStore(base_dir=tmp_path / "s")
    cid = store.open_cycle("g", _b())["cycle_id"]
    store.note_environmental(cid, [tv.WRONG_TREE])
    store.note_environmental(cid, [tv.SANDBOX_UNAVAILABLE])  # rompe la racha
    assert store.note_environmental(cid, [tv.WRONG_TREE])["exhausted"] is False


def test_sentinel_in_same_command_cmd_shape(tmp_path: Path) -> None:
    cmd = server._autoevol_pytest_cmd(tmp_path, ["tests/a.py::t1", "tests/a.py::t2"])
    assert cmd.count("tests/a.py::t") == 2 and "-c" in cmd and "sys.exit(97)" in cmd and "pytest.main" in cmd


# --- sentinel real (sin bwrap): subproceso con el mismo script ----------------------------------------------
def _sentinel(tree: Path, pythonpath: Path, *, isolated: bool = False) -> int:
    argv = [sys.executable, *(["-I"] if isolated else []), "-c", server._AUTOEVOL_SENTINEL, str(tree), "-q", "--co"]
    proc = subprocess.run(  # noqa: S603 - argv literal, arboles temporales
        argv, cwd=tree, env={**os.environ, "PYTHONPATH": str(pythonpath)}, capture_output=True, text=True,
        check=False, timeout=60,
    )
    return proc.returncode


def test_tree_with_own_engine_passes_the_sentinel(tmp_path: Path) -> None:
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "__init__.py").write_text("")
    assert _sentinel(tmp_path, tmp_path) != server._AUTOEVOL_WRONG_TREE_EXIT


def test_tree_whose_engine_resolves_elsewhere_is_wrong_tree(tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / "engine").mkdir(parents=True)
    (other / "engine" / "__init__.py").write_text("")
    tree = tmp_path / "tree"
    tree.mkdir()  # sin engine/ propio: gana el engine ajeno via PYTHONPATH
    assert _sentinel(tree, other) == server._AUTOEVOL_WRONG_TREE_EXIT


def test_tree_without_engine_package_is_wrong_tree(tmp_path: Path) -> None:
    assert _sentinel(tmp_path, tmp_path, isolated=True) == server._AUTOEVOL_WRONG_TREE_EXIT


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_wrong_tree_in_real_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Arbol sin `engine/` propio: el centinela corre dentro del bwrap real y sale 97."""
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    interp = server._autoevol_interpreter(tree)
    assert interp is not None
    raw = asyncio.run(
        server.sandbox_run(
            command=server._autoevol_pytest_cmd(tree, ["x"], interp),
            parse="pytest",
            working_dir=str(tree),
            ro_paths=interp["ro_paths"],
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(tree)},
            timeout=60,
            verbosity="detail",
        )
    )
    res = json.loads(raw)
    if res.get("status") in ("DEGRADED", "PERMISSION_DENIED") or "bwrap:" in str(res.get("stderr", "")):
        pytest.skip("bwrap unavailable in this environment")
    assert res.get("exit_code") == server._AUTOEVOL_WRONG_TREE_EXIT, res
