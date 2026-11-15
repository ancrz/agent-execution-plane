"""ONT-62/T2+T3: `setup.sh --check` hook path resolution and retrying pueue probe (stubbed, never the real daemon)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from unittest import mock

from engine.privilege import detect_chmod_tier

ROOT = Path(__file__).resolve().parent.parent
_FORCED_TIER = "6rw-"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "setup.sh", project / "scripts" / "setup.sh")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    return project


def _stub(directory: Path, name: str, body: str) -> None:
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _check(tmp_path: Path, project: Path, stubs: Path) -> str:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOME": str(home),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "AEP_FORCE_TIER": _FORCED_TIER,
        "AEP_DATA_HOME": str(tmp_path / "data"),
        "LANG": "C",
    }
    res = subprocess.run(
        ["bash", str(project / "scripts" / "setup.sh"), "--check"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
        check=False,
    )
    # setup.sh and the engine must agree on the forced tier (same AEP_FORCE_TIER contract)
    with mock.patch.dict(os.environ, {"AEP_FORCE_TIER": _FORCED_TIER}):
        engine_tier = detect_chmod_tier()["tier"]
    assert f"Detected Privilege Tier: {engine_tier}" in res.stdout
    return res.stdout


def _line(out: str, label: str) -> str:
    return next(ln for ln in out.splitlines() if label in ln)


def _hook_line(tmp_path: Path, hooks_path: str | None) -> str:
    project = _project(tmp_path)
    if hooks_path is not None:
        value = hooks_path.replace("{project}", str(project))
        subprocess.run(["git", "-C", str(project), "config", "core.hooksPath", value], check=True)
    return _line(_check(tmp_path, project, tmp_path / "stubs"), "Git Pre-commit Hook")


def test_hook_relative_path_passes(tmp_path):
    assert "[PASS]" in _hook_line(tmp_path, "scripts/hooks")


def test_hook_absolute_equivalent_path_passes(tmp_path):
    assert "[PASS]" in _hook_line(tmp_path, "{project}/scripts/../scripts/hooks")


def test_hook_elsewhere_warns(tmp_path):
    assert "[WARN]" in _hook_line(tmp_path, "/somewhere/else")


def test_hook_unset_warns(tmp_path):
    assert "[WARN]" in _hook_line(tmp_path, None)


def _pueue_line(tmp_path: Path, fail_first: int | None) -> tuple[str, int]:
    """fail_first=N: first N calls fail, then succeed; None: always fail. Returns (check line, call count)."""
    project = _project(tmp_path)
    stubs = tmp_path / "stubs"
    counter = tmp_path / "pueue_calls"
    cond = "true" if fail_first is None else f'[ "$n" -le {fail_first} ]'
    _stub(
        stubs,
        "pueue",
        f'echo x >> "{counter}"\nn=$(wc -l < "{counter}")\n'
        f'if {cond}; then echo "connection refused" >&2; exit 1; fi\nexit 0\n',
    )
    line = _line(_check(tmp_path, project, stubs), "Pueue Daemon")
    return line, len(counter.read_text().splitlines())


def test_pueue_recovers_on_third_attempt(tmp_path):
    line, calls = _pueue_line(tmp_path, fail_first=2)
    assert "[PASS]" in line and calls == 3


def test_pueue_fails_only_after_three_attempts(tmp_path):
    line, calls = _pueue_line(tmp_path, fail_first=None)
    assert "[FAIL]" in line and "connection refused" in line and calls == 3


def test_pueue_first_try_ok_single_call(tmp_path):
    line, calls = _pueue_line(tmp_path, fail_first=0)
    assert "[PASS]" in line and calls == 1
