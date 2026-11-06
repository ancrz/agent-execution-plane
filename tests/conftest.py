"""Fixtures compartidas. D-22: ningún test toca el fence real `PROJECT_ROOT/.aep_swap_fence`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_swap_fence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Apunta AEP_SWAP_FENCE_PATH a un tmp por test: los fronts lanzados y las comprobaciones en proceso lo heredan."""
    fence = tmp_path / "fence"
    monkeypatch.setenv("AEP_SWAP_FENCE_PATH", str(fence))
    return fence


@pytest.fixture(autouse=True)
def isolated_front_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """ONT-41: LKG store, front state file and plane_events spool live under tmp (never ~/.local or /dev/shm)."""
    base = tmp_path / "front_state"
    monkeypatch.setenv("AEP_DATA_HOME", str(base / "data"))
    monkeypatch.setenv("AEP_FRONT_STATE_DIR", str(base / "state"))
    monkeypatch.setenv("AEP_FRONT_SPOOL_DIR", str(base / "spool"))
    return base


# --- ONT-42a: harness_reconnect isolation -----------------------------------------------------------------------
_SYSCTL_TTY = "/proc/sys/dev/tty/legacy_tiocsti"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _read_tiocsti() -> str | None:
    try:
        with open(_SYSCTL_TTY) as fh:
            return fh.read().strip()
    except OSError:
        return None


@pytest.fixture(scope="session", autouse=True)
def tiocsti_sysctl_unchanged_guard():
    """Session guard (read-only): the real dev.tty.legacy_tiocsti must be identical before and after the suite."""
    before = _read_tiocsti()
    yield
    assert _read_tiocsti() == before, "dev.tty.legacy_tiocsti changed during the test session"


@pytest.fixture(autouse=True)
def isolated_harness_reconnect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may write /proc/sys/dev/tty/*, open /dev/pts/* or run the sudo TIOCSTI helper. Dry mode is forced."""
    import subprocess

    from engine import harness_reconnect as hr

    monkeypatch.setenv("AEP_HARNESS_RECONNECT_DRY", "1")
    real_open, real_os_open, real_popen_init = open, os.open, subprocess.Popen.__init__

    def _forbidden(path: object, write: bool) -> bool:
        p = os.fspath(path) if isinstance(path, (str, bytes, os.PathLike)) else ""
        p = p.decode() if isinstance(p, bytes) else p
        return p.startswith("/dev/pts/") or (write and p.startswith("/proc/sys/dev/tty"))

    def guard_open(file, mode="r", *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        if _forbidden(file, any(c in str(mode) for c in "wa+x")):
            raise AssertionError(f"test attempted forbidden open: {file!r} mode={mode!r}")
        return real_open(file, mode, *a, **k)

    def guard_os_open(path, flags, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        if _forbidden(path, bool(flags & _WRITE_FLAGS)):
            raise AssertionError(f"test attempted forbidden os.open: {path!r}")
        return real_os_open(path, flags, *a, **k)

    def guard_popen(self, args, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        if isinstance(args, (list, tuple)) and args and os.path.basename(str(args[0])) == "sudo" and hr.HELPER_SCRIPT in args:
            raise AssertionError("test attempted to run the sudo TIOCSTI helper")
        return real_popen_init(self, args, *a, **k)

    monkeypatch.setattr("builtins.open", guard_open)
    monkeypatch.setattr("io.open", guard_open)
    monkeypatch.setattr(os, "open", guard_os_open)
    monkeypatch.setattr(subprocess.Popen, "__init__", guard_popen)
