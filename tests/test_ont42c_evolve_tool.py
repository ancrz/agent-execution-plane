"""ONT-42c C2: accion `evolve` de la tool autoevol. REPO_ROOT se redirige a un repo temporal: nunca el real ni su origin."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import server
from engine.privilege import _PrivilegeCache
from tests._evolve_support import Rig, make_rig, sh


def _call(**kw: object) -> dict:
    return json.loads(asyncio.run(server.autoevol(**kw)))  # type: ignore[arg-type]


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    r = make_rig(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AEP_AUTOEVOL_DIR", str(r.state))
    monkeypatch.setenv("AEP_SWAP_FENCE_PATH", str(r.fence))
    monkeypatch.setattr(server, "REPO_ROOT", r.canon)
    yield r
    _PrivilegeCache.reset()


def _tier(monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()


def test_plan_without_cycle_is_available_in_every_tier(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    for tier in ("4r--", "5r-x", "6rw-", "7rwx"):
        _tier(monkeypatch, tier)
        res = _call(action="evolve", gap="D-88", root=str(rig.work))
        assert res["status"] == "OK" and res["state"] == "PLAN" and res["applied"] is False


@pytest.mark.parametrize("tier", ["4r--", "5r-x"])
def test_read_only_tiers_only_plan_even_with_apply(rig: Rig, monkeypatch: pytest.MonkeyPatch, tier: str) -> None:
    _tier(monkeypatch, tier)
    res = _call(action="evolve", cycle=rig.cycle, apply=True, root=str(rig.work))
    assert res["gating"] == "plan" and res["applied"] is False
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""


def test_6rw_commits_locally_without_merge_or_push(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _tier(monkeypatch, "6rw-")
    res = _call(action="evolve", cycle=rig.cycle, apply=True, root=str(rig.work))
    assert res["state"] == "COMMITTED" and res["local_only"] is True
    assert sh(rig.canon, "rev-parse", "dev") != sh(rig.canon, "rev-parse", f"autoevol/{rig.cycle}")
    assert f"autoevol/{rig.cycle}" not in sh(rig.bare, "show-ref")


def test_apply_on_canonical_root_is_refused(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    _tier(monkeypatch, "7rwx")
    res = _call(action="evolve", cycle=rig.cycle, apply=True, root=str(rig.canon))
    assert res["status"] == "ERROR" and "worktree" in res["error"]


def test_evolve_is_registered_as_action() -> None:
    assert "evolve" in server._AUTOEVOL_ACTIONS and "evolve" in server._TOOL_ACTIONS["autoevol"]
