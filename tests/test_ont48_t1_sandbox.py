"""ONT-48 T1 (G24): sandbox_run keeps /dev writable with rw_paths and flags EXEC_SUSPECT."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

import pytest

import server


def _run(**kw) -> dict:
    return json.loads(asyncio.run(server.sandbox_run(**kw)))


def _capture_cmd(monkeypatch, **kw) -> list[str]:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_k):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.shutil, "which", lambda _n: "/usr/bin/bwrap")
    _run(command="true", **kw)
    return captured["cmd"]


def test_device_args_pure() -> None:
    assert server._bwrap_device_args() == ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/dev/shm"]


def test_dev_mount_after_all_binds_and_no_root_bind(monkeypatch, tmp_path) -> None:
    cmd = _capture_cmd(monkeypatch, rw_paths=[str(tmp_path)], ro_paths=["/"])
    triples = list(zip(cmd, cmd[1:], cmd[2:], strict=False))
    assert ("--ro-bind", "/", "/") not in triples
    assert ("--bind", "/", "/") not in triples
    dev_idx = cmd.index("--dev")
    user_binds = [i for i, a in enumerate(cmd) if a in ("--bind", "--ro-bind") and cmd[i + 1] == str(tmp_path)]
    assert user_binds and dev_idx > max(user_binds)


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_dev_null_writable_with_rw_paths(tmp_path) -> None:
    res = _run(command="sh -c 'echo ok > /dev/null && echo ok'", rw_paths=[str(tmp_path)])
    if res.get("status") == "EXEC_FAILED" and "bwrap:" in str(res.get("stderr", "")):
        pytest.skip("bwrap cannot create user namespaces here")
    assert res["status"] == "SUCCESS"
    assert res["stdout"].strip() == "ok"


def test_exec_suspect_on_traceback_with_exit_zero(monkeypatch) -> None:
    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Traceback (most recent call last):\nPermissionError: /dev/null\n", stderr=""
        )

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.shutil, "which", lambda _n: "/usr/bin/bwrap")
    res = _run(command="pytest | tail", parse="auto")
    assert res["status"] == "EXEC_SUSPECT"
    assert "hint" in res


def test_no_exec_suspect_without_auto(monkeypatch) -> None:
    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 0, stdout="Traceback (most recent call last)", stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server.shutil, "which", lambda _n: "/usr/bin/bwrap")
    assert _run(command="x")["status"] == "SUCCESS"
