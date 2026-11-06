"""ONT-41 TC3: aep_ctl(backup, lkg_status|lkg_diff|lkg_restore) sobre un LKG sintetico en un data home aislado."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import aep_lkg
import server
from engine import lkg_ctl
from engine.privilege import CONTROL_PLANE_SCHEMA


@pytest.fixture
def lkg_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "home"))
    code = tmp_path / "code"
    (code / "engine").mkdir(parents=True)
    (code / "server.py").write_text("X = 1\n", encoding="utf-8")
    (code / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (code / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n", encoding="utf-8")
    aep_lkg.save(code, generation=1, code_fingerprint="fp", schema_hash="sh", git_head="h")
    key = aep_lkg.latest()
    assert key
    (code / "server.py").write_text("X = broken(\n", encoding="utf-8")
    return code, key


def test_schema_lists_lkg_actions_with_preconditions() -> None:
    spec = CONTROL_PLANE_SCHEMA["backup"]
    for act in lkg_ctl.ACTIONS:
        assert act in spec["actions"] and act in spec["preconditions"]


def test_status_diff_and_unknown(lkg_env: tuple[Path, str]) -> None:
    code, key = lkg_env
    st = lkg_ctl.lkg_ctl("lkg_status", None, repo_root=code, tier_octal=4)
    assert st["status"] == "OK" and st["key"] == key
    df = lkg_ctl.lkg_ctl("lkg_diff", "server.py", repo_root=code, tier_octal=4)
    assert df["diffs"][0]["identical"] is False
    assert lkg_ctl.lkg_ctl("lkg_diff", "../etc/passwd", repo_root=code, tier_octal=4)["status"] == "ERROR"
    assert lkg_ctl.lkg_ctl("lkg_diff", None, repo_root=code, tier_octal=4)["status"] == "ERROR"


def test_no_lkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "empty"))
    assert lkg_ctl.lkg_status()["status"] == "NO_LKG"
    assert lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=tmp_path, tier_octal=6)["status"] == "NO_LKG"


def test_restore_gates(lkg_env: tuple[Path, str]) -> None:
    code, _key = lkg_env
    snaps: list[list[str]] = []

    def snap(files: list[str]) -> dict[str, Any]:
        snaps.append(files)
        return {"status": "SUCCESS"}

    denied = lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=code, tier_octal=5, apply=True, snapshot_fn=snap)
    assert denied["status"] == "PERMISSION_DENIED" and not snaps
    dry = lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=code, tier_octal=6, snapshot_fn=snap)
    assert dry["status"] == "DRY_RUN" and not snaps and "broken" in (code / "server.py").read_text()
    need = lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=code, tier_octal=6, apply=True)
    assert need["status"] == "SNAPSHOT_REQUIRED"
    bad = lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=code, tier_octal=6, apply=True, snapshot_fn=lambda f: {"status": "ERROR"})
    assert bad["status"] == "SNAPSHOT_FAILED" and "broken" in (code / "server.py").read_text()
    ok = lkg_ctl.lkg_ctl("lkg_restore", "server.py", repo_root=code, tier_octal=6, apply=True, snapshot_fn=snap)
    assert ok["status"] == "RESTORED" and snaps == [["server.py"]]
    assert (code / "server.py").read_text() == "X = 1\n"


def test_server_backup_lkg_status_and_ipc_plane(lkg_env: tuple[Path, str]) -> None:
    res = json.loads(asyncio.run(server.aep_ctl(domain="backup", action="lkg_status", verbosity="summary")))
    assert res["status"] == "OK"
    ipc = json.loads(asyncio.run(server.aep_ctl(domain="ipc", action="status", verbosity="summary")))
    assert ipc["plane"]["serving_from"] in ("repo", "lkg")
