"""The MCP aep_ctl tool must not depend on a system python3."""

import json
import subprocess
import sys
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parent.parent


def test_aep_ctl_tool_spawns_current_interpreter(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"status": "OK"}), stderr="")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    import asyncio

    asyncio.run(server.aep_ctl(domain="service", action="status"))
    ctl_calls = [c for c in seen if any(str(server.AEP_CTL) == part for part in c)]
    assert ctl_calls
    assert ctl_calls[0][0] == sys.executable
    assert '["python3", str(AEP_CTL)' not in (ROOT / "server.py").read_text()
