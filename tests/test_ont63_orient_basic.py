"""ONT-63 group (a): host-info, cpu-load, toolchain-probe (layer-0 orientation primitives)."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

import pytest

import server
from engine.primitives import execute_primitive
from engine.privilege import TIER_4R, TIER_6RW, _PrivilegeCache


async def _run(name: str, params: dict | None = None, verbosity: str = "detail") -> dict:
    return json.loads(
        await server.default_primitives(action="run", name=name, params=params or {}, verbosity=verbosity)
    )


@pytest.mark.anyio
async def test_host_info_fields_and_tier() -> None:
    data = await _run("host-info")
    assert data["status"] == "OK"
    r = data["result"]
    assert r["hostname"] and r["kernel"].startswith("Linux ") and r["arch"]
    assert r["ncpu"] >= 1 and r["uptime_s"] > 0
    assert r["virt"] in {"container", "vm", "bare", "unknown"}
    assert r["user"]["uid"] == os.getuid() and isinstance(r["user"]["groups"], list)
    assert r["tier"] in {"7rwx", "6rw-", "5r-x", "4r--"}
    assert "toolchain-probe" in data["next_action"]


@pytest.mark.anyio
async def test_cpu_load_sampling_and_clamp() -> None:
    t0 = time.perf_counter()
    r = (await _run("cpu-load", {"sample_ms": 50}))["result"]
    assert time.perf_counter() - t0 < 1.0
    assert len(r["loadavg"]) == 3 and r["ncpu"] >= 1
    assert r["usage_pct"] is None or 0.0 <= r["usage_pct"] <= 100.0
    clamped = (await _run("cpu-load", {"sample_ms": 99999}))["result"]
    assert clamped["sample_ms"] == 1000


@pytest.mark.anyio
async def test_toolchain_probe_defaults_and_aep_ready() -> None:
    r = (await _run("toolchain-probe"))["result"]
    names = {t["name"] for t in r["tools"]}
    assert {"python3", "go", "git", "bwrap", "sudo"} <= names
    py = next(t for t in r["tools"] if t["name"] == "python3")
    assert py["present"] and py["version"].lower().startswith("python")
    sudo = next(t for t in r["tools"] if t["name"] == "sudo")
    assert "version" not in sudo  # sudo is never executed
    for tool, cap in r["aep_ready"].items():
        assert next(t for t in r["tools"] if t["name"] == tool)["present"] and cap


@pytest.mark.anyio
async def test_toolchain_probe_names_validation() -> None:
    ok = (await _run("toolchain-probe", {"names": ["git", "definitely-not-a-binary-xyz"]}))["result"]
    assert ok["missing"] == ["definitely-not-a-binary-xyz"]
    for bad in (["--help"], ["a b"], ["x;ls"], [f"t{i}" for i in range(31)]):
        data = await _run("toolchain-probe", {"names": bad})
        assert data["status"] == "PARAM_ERROR", bad


@pytest.mark.anyio
async def test_orientation_primitives_run_in_auditor_tier() -> None:
    with patch.dict(os.environ, {"AEP_FORCE_TIER": TIER_4R}):
        _PrivilegeCache.reset()
        for name in ("host-info", "cpu-load", "toolchain-probe"):
            data = await _run(name)
            assert data["status"] == "OK", name
            assert data["chmod_tier"] == "4r--"
        denied = await _run("socket-monitor")
        assert denied["status"] == "PERMISSION_DENIED"
    _PrivilegeCache.reset()


def test_no_environment_values_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_TEST_SECRET_TOKEN", "s3cr3t-value-xyz")
    for name in ("host-info", "cpu-load", "toolchain-probe"):
        out = execute_primitive(name, {}, tier=TIER_6RW)
        assert out["status"] == "OK"
        assert "s3cr3t-value-xyz" not in json.dumps(out)


def test_probe_tools_direct_reports_budget_and_rows() -> None:
    from engine.primitives_orient import probe_tools

    rows, exceeded = probe_tools(["git", "no-such-binary-ont63"])
    assert exceeded is False
    assert [r["name"] for r in rows] == ["git", "no-such-binary-ont63"]
    assert rows[1]["present"] is False
