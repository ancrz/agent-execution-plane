"""ONT-48 T6 (G13): aep-ctl service status reports NOT_FOUND for LoadState=not-found."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import server

ROOT = Path(__file__).resolve().parent.parent


def _load_ctl() -> ModuleType:
    path = str(ROOT / "scripts" / "aep-ctl")
    loader = importlib.machinery.SourceFileLoader("aep_ctl_script_ont48", path)
    spec = importlib.util.spec_from_loader("aep_ctl_script_ont48", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _status(monkeypatch, show_output: str) -> dict:
    """Run the real script logic (systemctl mocked), then relay it through the MCP aep_ctl tool."""
    ctl = _load_ctl()
    monkeypatch.setattr(ctl, "_need", lambda _b: "/usr/bin/systemctl")
    monkeypatch.setattr(ctl, "_run", lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout=show_output, stderr=""))
    script_payload = ctl.domain_service("status", "ssh")

    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(script_payload), stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    return json.loads(asyncio.run(server.aep_ctl(domain="service", action="status", name="ssh")))


def test_not_found_unit(monkeypatch) -> None:
    res = _status(monkeypatch, "ActiveState=inactive\nSubState=dead\nLoadState=not-found\nMainPID=0\n")
    assert res["status"] == "NOT_FOUND"
    assert res["severity"] == "WARN"
    assert 'domain="package"' in res["next_action"] and 'name="ssh"' in res["next_action"]
    assert res["properties"]["LoadState"] == "not-found"


def test_loaded_unit_stays_ok(monkeypatch) -> None:
    res = _status(monkeypatch, "ActiveState=active\nSubState=running\nLoadState=loaded\nMainPID=1\n")
    assert res["status"] == "OK"
    assert res["severity"] == "INFO"
