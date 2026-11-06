"""Fixtures compartidas. D-22: ningún test toca el fence real `PROJECT_ROOT/.aep_swap_fence`."""

from __future__ import annotations

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
