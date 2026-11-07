"""Backlog: cobertura de las acciones `aep_ctl(domain="backup", action=lkg_*)` via la tool (dry-run, AEP_DATA_HOME temporal)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import aep_lkg
import server
from engine.privilege import _PrivilegeCache


@pytest.fixture
def lkg_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    code = tmp_path / "code"
    (code / "engine").mkdir(parents=True)
    (code / "server.py").write_text("X = 1\n", encoding="utf-8")
    (code / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (code / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    aep_lkg.save(code, generation=1, code_fingerprint="fp", schema_hash="sh", git_head="h")
    (code / "server.py").write_text("X = broken(\n", encoding="utf-8")
    monkeypatch.setattr(server, "REPO_ROOT", code)
    yield code
    _PrivilegeCache.reset()


def _ctl(**kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(server.aep_ctl(**kw)))


def test_lkg_restore_dry_run_does_not_touch_files(lkg_code: Path) -> None:
    res = _ctl(domain="backup", action="lkg_restore", name="server.py", verbosity="summary")
    assert res["status"] == "DRY_RUN"
    assert "broken" in (lkg_code / "server.py").read_text(encoding="utf-8")


def test_lkg_restore_apply_blocked_when_snapshot_fails(lkg_code: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_lkg_snapshot_fn", lambda files: {"status": "ERROR"})
    res = _ctl(domain="backup", action="lkg_restore", name="server.py", params={"apply": True}, verbosity="summary")
    assert res["status"] == "SNAPSHOT_FAILED"
    assert "broken" in (lkg_code / "server.py").read_text(encoding="utf-8")


def test_lkg_status_and_diff_via_tool(lkg_code: Path) -> None:
    assert _ctl(domain="backup", action="lkg_status", verbosity="summary")["status"] == "OK"
    diff = _ctl(domain="backup", action="lkg_diff", name="server.py", verbosity="summary")
    assert diff["diffs"][0]["identical"] is False
