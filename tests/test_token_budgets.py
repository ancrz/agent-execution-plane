"""
Tests for token budgets and contract regression assertions (Milestone ONT-38b-L1).

Verifies in-process FastMCP tool token budgets via `t.tok` or `telemetry.estimated_tokens`:
- Baseline assertions passing today:
  * discover(capabilities, terse, session_id) <= 400
  * default_primitives run mem-stat <= 250
  * topos_audit_dag brief <= 200
  * process_inspect brief limit=5 <= 300
- Former discrepancies D-01..D-05 closed in L3 (xfail markers removed):
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
import sqlite3
from pathlib import Path
from typing import Any

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


def test_xfail_d02_playbook_run_list_summary_envelope() -> None:
    """playbook_run(action='list', verbosity='summary') must not contain 'envelope' key."""
    res = asyncio.run(server.playbook_run(action="list", verbosity="summary"))
    payload = json.loads(res)
    assert "envelope" not in payload, "Found legacy 'envelope' key in summary response"


def test_xfail_d03a_select_fields_missing_key_unresolved_fields() -> None:
    """select_fields non-existent path should return unresolved_fields key."""
    res = asyncio.run(server.discover(action="playbook", select_fields=["nope"]))
    payload = json.loads(res)
    assert "unresolved_fields" in payload, "Missing 'unresolved_fields' key for invalid projection path"


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


# ==============================================================================
# Read-only aep_ctl action budgets (ONT-45 N1)
# Limits = tokens measured on the reference host x1.5, rounded up (all < 1500).
# Paginated listings pass a small literal ``limit`` so the output is host-independent.
# Host-sensitive, unpaginated actions (network.interfaces/inspect/arp, storage.disks)
# are intentionally not budgeted here. Mutating actions are never budgeted.
# ==============================================================================


def _aep_ctl_tokens(**kwargs: Any) -> int:
    res = asyncio.run(server.aep_ctl(verbosity="summary", **kwargs))
    return _extract_tokens(json.loads(res))


def test_budget_aep_ctl_backup_backup_status() -> None:
    """aep_ctl(domain='backup', action='backup_status', verbosity='summary') <= 881 tokens."""
    tok = _aep_ctl_tokens(domain="backup", action="backup_status")
    assert tok <= 881, f"Expected <= 881 tokens, got {tok}"


def test_budget_aep_ctl_backup_quarantine_status() -> None:
    """aep_ctl(domain='backup', action='quarantine_status', verbosity='summary') <= 126 tokens."""
    tok = _aep_ctl_tokens(domain="backup", action="quarantine_status")
    assert tok <= 126, f"Expected <= 126 tokens, got {tok}"


def test_budget_aep_ctl_backup_list_micro_snapshots() -> None:
    """aep_ctl(domain='backup', action='list_micro_snapshots', verbosity='summary') <= 101 tokens."""
    tok = _aep_ctl_tokens(domain="backup", action="list_micro_snapshots")
    assert tok <= 101, f"Expected <= 101 tokens, got {tok}"


def test_budget_aep_ctl_backup_verify_integrity(tmp_path: Path) -> None:
    """aep_ctl(domain='backup', action='verify_integrity', verbosity='summary') <= 165 tokens."""
    db = tmp_path / "budget.db"
    sqlite3.connect(db).close()
    tok = _aep_ctl_tokens(domain="backup", action="verify_integrity", name=str(db))
    assert tok <= 165, f"Expected <= 165 tokens, got {tok}"


def test_budget_aep_ctl_network_routes() -> None:
    """aep_ctl(domain='network', action='routes', verbosity='summary') <= 348 tokens."""
    tok = _aep_ctl_tokens(domain="network", action="routes", limit=5)
    assert tok <= 348, f"Expected <= 348 tokens, got {tok}"


def test_budget_aep_ctl_package_installed() -> None:
    """aep_ctl(domain='package', action='installed', verbosity='summary') <= 249 tokens."""
    tok = _aep_ctl_tokens(domain="package", action="installed", limit=5)
    assert tok <= 249, f"Expected <= 249 tokens, got {tok}"


def test_budget_aep_ctl_package_list() -> None:
    """aep_ctl(domain='package', action='list', verbosity='summary') <= 248 tokens."""
    tok = _aep_ctl_tokens(domain="package", action="list", limit=5)
    assert tok <= 248, f"Expected <= 248 tokens, got {tok}"


def test_budget_aep_ctl_package_check() -> None:
    """aep_ctl(domain='package', action='check', verbosity='summary') <= 96 tokens."""
    tok = _aep_ctl_tokens(domain="package", action="check", name="bash", limit=5)
    assert tok <= 96, f"Expected <= 96 tokens, got {tok}"


def test_budget_aep_ctl_package_info() -> None:
    """aep_ctl(domain='package', action='info', verbosity='summary') <= 107 tokens."""
    tok = _aep_ctl_tokens(domain="package", action="info", name="bash", limit=5)
    assert tok <= 107, f"Expected <= 107 tokens, got {tok}"


def test_budget_aep_ctl_security_landlock_status() -> None:
    """aep_ctl(domain='security', action='landlock_status', verbosity='summary') <= 138 tokens."""
    tok = _aep_ctl_tokens(domain="security", action="landlock_status")
    assert tok <= 138, f"Expected <= 138 tokens, got {tok}"


def test_budget_aep_ctl_service_list() -> None:
    """aep_ctl(domain='service', action='list', verbosity='summary') <= 446 tokens."""
    tok = _aep_ctl_tokens(domain="service", action="list", limit=5)
    assert tok <= 446, f"Expected <= 446 tokens, got {tok}"


def test_budget_aep_ctl_storage_mounts() -> None:
    """aep_ctl(domain='storage', action='mounts', verbosity='summary') <= 324 tokens."""
    tok = _aep_ctl_tokens(domain="storage", action="mounts", limit=5)
    assert tok <= 324, f"Expected <= 324 tokens, got {tok}"
