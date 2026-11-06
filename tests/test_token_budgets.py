"""
Tests for token budgets and contract regression assertions (Milestone ONT-38b-L1).

Verifies in-process FastMCP tool token budgets via `t.tok` or `telemetry.estimated_tokens`:
- Baseline assertions passing today:
  * discover(capabilities, terse, session_id) <= 400
  * default_primitives run mem-stat <= 250
  * topos_audit_dag brief <= 200
  * process_inspect brief limit=5 <= 300
- Known discrepancies failing today (marked @pytest.mark.xfail(strict=True, reason="D-0x")):
  * D-01: discover(schema, summary) < 3000
  * D-02: playbook_run(list) in summary without key "envelope"
  * D-03a: select_fields non-existent path -> key "unresolved_fields"
  * D-03b: indexed projection preserves list type
  * D-04: aep_ctl(schema, summary) < 1500
  * D-05: aep_ctl(ipc status, summary) without duplicated "mux.pool"
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import server


def _extract_tokens(payload: dict[str, Any]) -> int:
    """Extract token estimate from compact 't.tok' or legacy 'telemetry.estimated_tokens'."""
    t_field = payload.get("t")
    if isinstance(t_field, dict) and "tok" in t_field:
        return int(t_field["tok"])
    telem = payload.get("telemetry")
    if isinstance(telem, dict) and "estimated_tokens" in telem:
        return int(telem["estimated_tokens"])
    raise AssertionError(f"No token telemetry found in response keys: {list(payload.keys())}")


# ==============================================================================
# Passing Baseline Token Budgets (Today)
# ==============================================================================


def test_budget_discover_capabilities_terse() -> None:
    """discover(action='capabilities', verbosity='terse', session_id=...) <= 400 tokens."""
    res = asyncio.run(
        server.discover(
            action="capabilities",
            verbosity="terse",
            session_id="test-budget-token",
            force_refresh=True,
        )
    )
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok <= 400, f"Expected <= 400 tokens, got {tok}"


def test_budget_default_primitives_run_mem_stat() -> None:
    """default_primitives(action='run', name='mem-stat') <= 250 tokens."""
    res = asyncio.run(server.default_primitives(action="run", name="mem-stat"))
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok <= 250, f"Expected <= 250 tokens, got {tok}"


def test_budget_topos_audit_dag_brief() -> None:
    """topos_audit_dag(format='brief') <= 200 tokens."""
    res = asyncio.run(server.topos_audit_dag(tasks=["t1"], verbosity="brief"))
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok <= 200, f"Expected <= 200 tokens, got {tok}"


def test_budget_process_inspect_brief_limit_5() -> None:
    """process_inspect(verbosity='brief', limit=5) <= 300 tokens."""
    res = asyncio.run(server.process_inspect(verbosity="brief", limit=5))
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok <= 300, f"Expected <= 300 tokens, got {tok}"


# ==============================================================================
# Discrepancies Failing Today (strict=True xfail for D-01..D-05)
# ==============================================================================


def test_xfail_d01_discover_schema_summary_token_budget() -> None:
    """discover(action='schema', verbosity='summary') < 3000 tokens."""
    res = asyncio.run(server.discover(action="schema", verbosity="summary"))
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok < 3000, f"Expected < 3000 tokens, got {tok}"


@pytest.mark.xfail(strict=True, reason="D-02: playbook_run(list) in summary emits legacy envelope and telemetry")
def test_xfail_d02_playbook_run_list_summary_envelope() -> None:
    """playbook_run(action='list', verbosity='summary') must not contain 'envelope' key."""
    res = asyncio.run(server.playbook_run(action="list", verbosity="summary"))
    payload = json.loads(res)
    assert "envelope" not in payload, "Found legacy 'envelope' key in summary response"


@pytest.mark.xfail(strict=True, reason="D-03a: select_fields non-existent path must report unresolved_fields")
def test_xfail_d03a_select_fields_missing_key_unresolved_fields() -> None:
    """select_fields non-existent path should return unresolved_fields key."""
    res = asyncio.run(server.discover(action="playbook", select_fields=["nope"]))
    payload = json.loads(res)
    assert "unresolved_fields" in payload, "Missing 'unresolved_fields' key for invalid projection path"


@pytest.mark.xfail(strict=True, reason="D-03b: indexed projection converts list to dict instead of preserving list")
def test_xfail_d03b_indexed_projection_preserves_list() -> None:
    """Indexed select_fields path must preserve list type."""
    res = asyncio.run(
        server.discover(
            use_case="monitor open tcp sockets",
            select_fields=["suggested_capability.0.capability"],
        )
    )
    payload = json.loads(res)
    suggested = payload.get("suggested_capability")
    assert isinstance(suggested, list), f"Expected list for suggested_capability, got {type(suggested)}"


def test_xfail_d04_aep_ctl_schema_summary_token_budget() -> None:
    """aep_ctl(action='schema', verbosity='summary') < 1500 tokens."""
    res = asyncio.run(server.aep_ctl(action="schema", verbosity="summary"))
    payload = json.loads(res)
    tok = _extract_tokens(payload)
    assert tok < 1500, f"Expected < 1500 tokens, got {tok}"


def test_xfail_d05_aep_ctl_ipc_status_no_mux_pool() -> None:
    """aep_ctl(domain='ipc', action='status', verbosity='summary') must not include duplicated 'mux.pool'."""
    res = asyncio.run(server.aep_ctl(domain="ipc", action="status", verbosity="summary"))
    payload = json.loads(res)
    mux = payload.get("mux", {})
    assert "pool" not in mux, "Found duplicated 'pool' key inside 'mux' in summary response"
