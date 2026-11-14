"""ONT-48 T11 (G14): crash diagnosis carries ts_iso next to the original time fields."""

from __future__ import annotations

import asyncio
import json
import subprocess

import server


def test_epoch_to_iso_units() -> None:
    assert server._epoch_to_iso(1_700_000_000) == "2023-11-14T22:13:20+00:00"
    assert server._epoch_to_iso("1700000000000000") == "2023-11-14T22:13:20+00:00"
    assert server._epoch_to_iso(None) is None
    assert server._epoch_to_iso("garbage") is None


def _fake_run(cmd, **_k):
    if "coredumpctl" in cmd:
        out = json.dumps([{"pid": 1, "uid": 0, "sig": 11, "time": 1_700_000_000_000_000, "exe": "/bin/x"}])
    else:
        line = json.dumps({"__REALTIME_TIMESTAMP": "1700000000000000", "MESSAGE": "boom", "_SYSTEMD_UNIT": "u.service"})
        out = line + "\n"
    return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def _diagnose(monkeypatch, verbosity: str) -> dict:
    monkeypatch.setattr(server.subprocess, "run", _fake_run)
    monkeypatch.setattr(server.shutil, "which", lambda b: f"/usr/bin/{b}")
    return json.loads(asyncio.run(server.diagnose_system_crashes(action="diagnose", verbosity=verbosity)))


def test_ts_iso_present_in_compact_and_detail(monkeypatch) -> None:
    for mode in ("summary", "detail"):
        res = _diagnose(monkeypatch, mode)
        cd = res["recent_coredumps"][0]
        err = res["recent_systemd_errors"][0]
        assert cd["ts_iso"] == "2023-11-14T22:13:20+00:00" and cd["time"] == 1_700_000_000_000_000
        assert err["ts_iso"] == "2023-11-14T22:13:20+00:00"
        assert err.get("timestamp", err.get("__REALTIME_TIMESTAMP")) == "1700000000000000"
