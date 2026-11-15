"""ONT-62/T1: aep_front.BACKEND_LOG_DIR follows AEP_DATA_HOME exactly like engine.paths.data_home() (parity)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from engine import paths

ROOT = Path(__file__).resolve().parent.parent
_PROBE = "import aep_front; print(aep_front.BACKEND_LOG_DIR)"


def _front_log_dir(env_home: str | None, tmp_path: Path) -> str:
    env = {"HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)}
    if env_home is not None:
        env["AEP_DATA_HOME"] = env_home
    res = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=ROOT, env=env, capture_output=True, text=True, check=True, timeout=60
    )
    return res.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("value", [None, "", "   ", "{tmp}/dh"])
def test_front_log_dir_matches_engine_data_home(value, tmp_path, monkeypatch):
    raw = value.format(tmp=tmp_path) if value else value
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    if raw is None:
        monkeypatch.delenv("AEP_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("AEP_DATA_HOME", raw)
    assert _front_log_dir(raw, tmp_path) == str(paths.data_home() / "logs")
