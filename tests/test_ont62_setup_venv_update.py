"""ONT-62/T5 (G71): `setup.sh --update` must not run `uv venv` over an existing venv (stubbed uv, fake HOME and project)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from unittest import mock

from engine.privilege import detect_chmod_tier

ROOT = Path(__file__).resolve().parent.parent
_TIER = "6rw-"


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_update(tmp_path: Path, venv_version: str | None, env_extra: dict[str, str] | None = None):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "setup.sh", project / "scripts" / "setup.sh")
    if venv_version is not None:
        _exe(project / ".venv" / "bin" / "python", f'case "$1" in -c) echo {venv_version};; *) exit 1;; esac\n')
    stubs = tmp_path / "stubbin"
    log = tmp_path / "uv_calls"
    _exe(stubs / "uv", f'echo "$*" >> "{log}"\ncase "$1" in --version) echo "uv 0.0.0";; esac\nexit 0\n')
    _exe(stubs / "curl", "echo 'curl: (6) Could not resolve host' >&2\nexit 6\n")
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "PATH": f"{stubs}:/usr/bin:/bin",
        "AEP_FORCE_TIER": _TIER,
        "AEP_DATA_HOME": str(tmp_path / "data"),
        "LANG": "C",
        **(env_extra or {}),
    }
    with mock.patch.dict(os.environ, {"AEP_FORCE_TIER": _TIER}):
        assert detect_chmod_tier()["tier"] == _TIER
    res = subprocess.run(
        ["bash", str(project / "scripts" / "setup.sh"), "--update"],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=str(project),
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return res, [c for c in calls if c.startswith("venv")]


def test_existing_314_venv_is_reused(tmp_path):
    res, venv_calls = _run_update(tmp_path, "3.14")
    assert venv_calls == []
    assert "Reutilizando venv existente" in res.stdout


def test_missing_venv_is_created_without_clear(tmp_path):
    _, venv_calls = _run_update(tmp_path, None)
    assert len(venv_calls) == 1 and "--clear" not in venv_calls[0] and "3.14" in venv_calls[0]


def test_other_version_warns_and_is_left_alone(tmp_path):
    res, venv_calls = _run_update(tmp_path, "3.12")
    assert venv_calls == []
    assert "NO se recrea" in res.stdout


def test_other_version_recreated_only_with_explicit_variable(tmp_path):
    _, venv_calls = _run_update(tmp_path, "3.12", {"AEP_RECREATE_VENV": "1"})
    assert len(venv_calls) == 1 and "--clear" in venv_calls[0]
    assert "--system-site-packages" not in venv_calls[0]
