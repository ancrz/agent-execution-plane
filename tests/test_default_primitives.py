"""
Quality Assurance Test Battery: Milestone ONT-34
FastMCP Tool #16 (default_primitives) & Factory Decoupling

Verifies:
  - Gate 1: Tool registration, signature ergonomics, and GAP-OM-19 single-encoding invariant (output_schema is None).
  - Gate 2: Action 'list' returns all 5 built-in diagnostic primitives with typed metadata.
  - Gate 3: Action 'info'/'get' returns contracts and handles missing/unknown names fail-soft.
  - Gate 4: Action 'run'/'exec' executes all 5 probes in-RAM under 7rwx, 6rw-, and 5r-x tiers.
  - Gate 5: 4-Tier chmod degradation: in 4r-- (auditor mode), execution returns status: PERMISSION_DENIED fail-soft.
  - Gate 6: Parameter aliases (args, params, verbosity='summary' token savings).
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

import server
from engine.privilege import TIER_4R, TIER_5RX, TIER_6RW, TIER_7RWX, _PrivilegeCache

EXPECTED_PRIMITIVES = {
    "socket-monitor",
    "fd-rescuer",
    "disk-usage",
    "mem-stat",
    "landlock-guard",
}


# ==============================================================================
# Gate 1: FastMCP Tool #16 & GAP-OM-19 Protocol Invariant
# ==============================================================================
def test_gate1_default_primitives_registration_and_gap_om19() -> None:
    """Tool #16 is registered and enforces output_schema is None (structured_output=False)."""
    tools = server.mcp._tool_manager._tools
    assert "default_primitives" in tools, "default_primitives must be registered in server.mcp"
    tool = tools["default_primitives"]
    assert tool.output_schema is None, f"GAP-OM-19 violation: output_schema must be None, got {tool.output_schema}"


# ==============================================================================
# Gate 2: Action 'list'
# ==============================================================================
@pytest.mark.anyio
async def test_gate2_action_list_returns_5_primitives() -> None:
    """Action 'list' returns all 5 default primitives with envelope and telemetry."""
    raw = await server.default_primitives(action="list", verbosity="detail")
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["count"] == 5
    prims = {p["name"] for p in data["primitives"]}
    assert prims == EXPECTED_PRIMITIVES
    assert "envelope" in data
    assert "telemetry" in data


# ==============================================================================
# Gate 3: Action 'info' / 'get'
# ==============================================================================
@pytest.mark.anyio
async def test_gate3_action_info_metadata_and_fail_soft() -> None:
    """Action 'info' returns schema metadata and degrades cleanly on missing/invalid name."""
    # 1. Missing name -> ERROR envelope with available_primitives
    raw_missing = await server.default_primitives(action="info", name=None)
    data_missing = json.loads(raw_missing)
    assert data_missing["status"] == "ERROR"
    assert "available_primitives" in data_missing

    # 2. Unknown name -> NOT_FOUND envelope
    raw_unknown = await server.default_primitives(action="info", name="nonexistent_probe")
    data_unknown = json.loads(raw_unknown)
    assert data_unknown["status"] == "NOT_FOUND"

    # 3. Valid names -> contract details
    for name in EXPECTED_PRIMITIVES:
        raw_valid = await server.default_primitives(action="info", name=name)
        data_valid = json.loads(raw_valid)
        assert data_valid["status"] == "OK"
        assert data_valid["primitive"]["name"] == name
        assert "description" in data_valid["primitive"]
        assert "params" in data_valid["primitive"]


# ==============================================================================
# Gate 4: Action 'run' Across Tiers (7rwx, 6rw-, 5r-x)
# ==============================================================================
@pytest.mark.anyio
async def test_gate4_action_run_all_5_primitives_in_ram() -> None:
    """All 5 probes execute in RAM returning structured diagnostics."""
    for tier in (TIER_7RWX, TIER_6RW, TIER_5RX):
        with patch.dict(os.environ, {"AEP_FORCE_TIER": tier}):
            _PrivilegeCache.reset()

            # 1. disk-usage
            raw_du = await server.default_primitives(action="run", name="disk-usage", params={"path": "/"})
            data_du = json.loads(raw_du)
            assert data_du["status"] == "OK"
            assert data_du["chmod_tier"] == tier
            res_du = data_du["result"]
            assert res_du["total_bytes"] > 0
            assert res_du["free_bytes"] > 0
            assert 0.0 <= res_du["percent_used"] <= 100.0

            # 2. mem-stat
            raw_mem = await server.default_primitives(action="run", name="mem-stat")
            data_mem = json.loads(raw_mem)
            assert data_mem["status"] == "OK"
            res_mem = data_mem["result"]
            assert res_mem["total_bytes"] > 0
            assert res_mem["available_bytes"] > 0

            # 3. socket-monitor
            raw_sm = await server.default_primitives(action="run", name="socket-monitor")
            data_sm = json.loads(raw_sm)
            assert data_sm["status"] == "OK"
            res_sm = data_sm["result"]
            assert "sockets" in res_sm
            assert isinstance(res_sm["count"], int)

            # 4. fd-rescuer
            raw_fd = await server.default_primitives(action="run", name="fd-rescuer", params={"pid": 0})
            data_fd = json.loads(raw_fd)
            assert data_fd["status"] == "OK"
            res_fd = data_fd["result"]
            assert res_fd["pid"] > 0
            assert "descriptors" in res_fd
            assert res_fd["fd_count"] >= 0

            # 5. landlock-guard
            raw_ll = await server.default_primitives(action="run", name="landlock-guard")
            data_ll = json.loads(raw_ll)
            assert data_ll["status"] == "OK"
            res_ll = data_ll["result"]
            assert "status" in res_ll
            assert "supported" in res_ll

    _PrivilegeCache.reset()


# ==============================================================================
# Gate 5: 4-Tier Degradation in 4r-- (Auditor Mode)
# ==============================================================================
@pytest.mark.anyio
async def test_gate5_chmod_4r_auditor_degradation_denies_execution() -> None:
    """In 4r-- (auditor mode), execution of all primitives returns PERMISSION_DENIED fail-soft."""
    with patch.dict(os.environ, {"AEP_FORCE_TIER": TIER_4R}):
        _PrivilegeCache.reset()

        # Metadata actions remain available in 4r--
        raw_list = await server.default_primitives(action="list")
        assert json.loads(raw_list)["status"] == "OK"

        raw_info = await server.default_primitives(action="info", name="mem-stat")
        assert json.loads(raw_info)["status"] == "OK"

        # Execution actions are disabled with PERMISSION_DENIED
        for name in EXPECTED_PRIMITIVES:
            raw_run = await server.default_primitives(action="run", name=name)
            data_run = json.loads(raw_run)
            assert data_run["status"] == "PERMISSION_DENIED"
            assert data_run["chmod_tier"] == "4r--"
            assert "summary" in data_run

    _PrivilegeCache.reset()


# ==============================================================================
# Gate 6: Parameter Ergonomics & Token Efficiency
# ==============================================================================
@pytest.mark.anyio
async def test_gate6_parameter_ergonomics_and_verbosity() -> None:
    """Supports args aliases, positional arguments, and verbosity token savings."""
    # 1. Positional args for disk-usage
    raw_args = await server.default_primitives(action="run", name="disk-usage", args=["/"])
    data_args = json.loads(raw_args)
    assert data_args["status"] == "OK"
    assert data_args["result"]["path"] == "/"

    # 2. Verbosity summary saves payload bytes
    raw_detail = await server.default_primitives(action="list", verbosity="detail")
    raw_summary = await server.default_primitives(action="list", verbosity="summary")
    data_detail = json.loads(raw_detail)
    data_summary = json.loads(raw_summary)
    assert data_summary["telemetry"]["output_bytes"] < data_detail["telemetry"]["output_bytes"]
