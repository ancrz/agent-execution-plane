"""ONT-67 T2: sealed, CLOEXEC, MFD_EXEC memfd for in-RAM execution + kernel-policy fallbacks."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import server
from engine import memfd

# not coreutils/uutils: those are multi-call binaries that dispatch on argv[0] and reject /proc/self/fd/N
SHELL = shutil.which("dash") or shutil.which("sh") or "/bin/sh"


def _echo_bytes() -> bytes:
    return Path(SHELL).resolve().read_bytes()


def test_memfd_is_sealed_cloexec_and_runs() -> None:
    fd = memfd.create_sealed_exec_memfd("anon_t2", _echo_bytes())
    try:
        assert memfd.seals(fd) & memfd.SEALS == memfd.SEALS
        assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        with pytest.raises(OSError) as err:
            os.write(fd, b"x")  # F_SEAL_WRITE: content can no longer change
        assert err.value.errno == errno.EPERM
        res = subprocess.run(
            [f"/proc/self/fd/{fd}", "-c", "echo sealed"], pass_fds=(fd,), capture_output=True, text=True, check=False
        )  # noqa: S603
        assert res.stdout.strip() == "sealed"
    finally:
        os.close(fd)


def test_mfd_exec_flag_requested_and_einval_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    real = os.memfd_create

    def fake(name: str, flags: int = 0) -> int:
        seen.append(flags)
        if flags & memfd.MFD_EXEC:
            raise OSError(errno.EINVAL, "kernel < 6.3")
        return real(name, flags)

    monkeypatch.setattr(os, "memfd_create", fake)
    fd = memfd.create_sealed_exec_memfd("anon_old", _echo_bytes())
    os.close(fd)
    assert len(seen) == 2 and seen[0] & memfd.MFD_EXEC and not seen[1] & memfd.MFD_EXEC
    assert seen[1] & os.MFD_CLOEXEC and seen[1] & os.MFD_ALLOW_SEALING


def test_noexec_policy_2_raises_without_creating_fd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memfd, "noexec_policy", lambda: 2)
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises(memfd.MemfdNoexecEnforced):
        memfd.create_sealed_exec_memfd("anon_x", b"data")
    assert len(os.listdir("/proc/self/fd")) == before


def test_create_eacces_maps_to_noexec_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(name: str, flags: int = 0) -> int:
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(os, "memfd_create", deny)
    with pytest.raises(memfd.MemfdNoexecEnforced):
        memfd.create_sealed_exec_memfd("anon_y", b"data")


def test_noexec_policy_reads_sysctl_value() -> None:
    val = memfd.noexec_policy()
    on_disk = Path(memfd.NOEXEC_SYSCTL)
    assert val == (int(on_disk.read_text().strip()) if on_disk.exists() else None)


def _register_echo(name: str) -> None:
    server.catalog.register_artifact(
        name=name,
        intent="echo for memfd test",
        category="test",
        cue_contract="{}",
        go_source="// test",
        binary_blob=_echo_bytes(),
    )


@pytest.mark.anyio
async def test_execute_in_ram_runs_sealed_binary_with_fd_delta_zero() -> None:
    _register_echo("ont67_echo")
    res = json.loads(
        await server.artifact_execute_in_ram(name="ont67_echo", args=["-c", "echo hi"], verbosity="detail")
    )
    assert res["status"] == "SUCCESS", res
    assert res["output"] == "hi"
    assert res["telemetry"]["fd_delta"] == 0


@pytest.mark.anyio
async def test_execute_in_ram_reports_memfd_noexec_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_echo("ont67_echo2")
    monkeypatch.setattr(memfd, "noexec_policy", lambda: 2)
    res = json.loads(await server.artifact_execute_in_ram(name="ont67_echo2", verbosity="detail"))
    assert res["status"] == "ERROR" and res["error_class"] == "memfd_noexec_enforced"
    assert res["memfd_noexec"] == 2
    assert res["next_action"].startswith("sandbox_run(") and "ont67_echo2" in res["next_action"]
    assert res["telemetry"]["fd_delta"] == 0


@pytest.mark.anyio
async def test_execute_in_ram_exec_denied_is_reported_as_noexec(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_echo("ont67_echo3")

    def deny(*_a: object, **_k: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(server.subprocess, "run", deny)
    res = json.loads(await server.artifact_execute_in_ram(name="ont67_echo3", verbosity="detail"))
    assert res["error_class"] == "memfd_noexec_enforced"
    assert res["telemetry"]["fd_delta"] == 0
