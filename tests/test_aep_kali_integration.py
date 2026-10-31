"""
Integration and contract verification tests for Milestone ONT-31:
RE as SDD Kali MCP Offensive/Defensive Primitives & Native Antigravity Integration.

Verifies:
  - Gate 1: FastMCP 15-Tool Invariant (zero expansion).
  - Gate 2: Security Domain Schema in CONTROL_PLANE_SCHEMA.
  - Gate 3: aep_ctl firewall_status query contract.
  - Gate 4: aep_ctl nftables_inspect query contract.
  - Gate 5: aep_ctl threat_mitigate defense contract.
  - Gate 6: kernel_trace eBPF modes (network_sniff, security_audit, tcp_listeners + aliases).
  - Gate 7: Playbook tactical recipes (WF-10, WF-11) and quick reference mappings.
  - Gate 8: AEP Instructions and schema synchronization.
"""

import json

import pytest

import server
from engine.privilege import CONTROL_PLANE_SCHEMA, tactical_playbook


def test_gate1_exactly_15_fastmcp_tools():
    """AEP FastMCP server MUST preserve strictly 15 tools."""
    tools = server.mcp._tool_manager._tools
    assert len(tools) == 15, f"Expected 15 tools, found {len(tools)}: {list(tools.keys())}"
    expected_tools = {
        "topos_audit_dag",
        "discover",
        "artifact_catalog",
        "artifact_lint_and_build",
        "artifact_execute_in_ram",
        "process_inspect",
        "async_job_dispatch",
        "diagnose_system_crashes",
        "sandbox_run",
        "aep_ctl",
        "query_system_docs",
        "visual_inspect",
        "kernel_trace",
        "kanban_board",
        "playbook_run",
    }
    assert set(tools.keys()) == expected_tools


def test_gate2_security_domain_schema():
    """Security domain in CONTROL_PLANE_SCHEMA defines the new defensive actions."""
    sec_schema = CONTROL_PLANE_SCHEMA.get("security")
    assert sec_schema is not None
    actions = sec_schema.get("actions", [])
    expected_actions = {
        "status",
        "audit",
        "verify",
        "firewall_status",
        "nftables_inspect",
        "threat_mitigate",
    }
    assert expected_actions.issubset(set(actions)), f"Missing actions in {actions}"


@pytest.mark.anyio
async def test_gate3_aep_ctl_firewall_status():
    """aep_ctl security firewall_status returns active backend and status."""
    raw = await server.aep_ctl(domain="security", action="firewall_status")
    res = json.loads(raw)
    assert res.get("status") in ("OK", "DEGRADED")
    assert "backend" in res
    assert "active" in res
    assert "envelope" in res


@pytest.mark.anyio
async def test_gate4_aep_ctl_nftables_inspect():
    """aep_ctl security nftables_inspect inspects ruleset or reports degraded safely."""
    raw = await server.aep_ctl(domain="security", action="nftables_inspect")
    res = json.loads(raw)
    assert res.get("status") in ("OK", "DEGRADED")
    assert "envelope" in res


@pytest.mark.anyio
async def test_gate5_aep_ctl_threat_mitigate():
    """aep_ctl security threat_mitigate mitigates or simulates netfilter drop rule."""
    # Missing target
    raw_missing = await server.aep_ctl(domain="security", action="threat_mitigate")
    res_missing = json.loads(raw_missing)
    assert res_missing.get("status") == "ERROR"

    # Targeted IP
    raw_target = await server.aep_ctl(domain="security", action="threat_mitigate", name="192.168.1.55")
    res_target = json.loads(raw_target)
    assert res_target.get("status") in ("OK", "SIMULATED", "DEGRADED")
    assert "envelope" in res_target
    if res_target.get("status") == "SIMULATED":
        assert "nft add rule" in res_target.get("simulated_rule", "")
        assert "192.168.1.55" in res_target.get("simulated_rule", "")


@pytest.mark.anyio
async def test_gate6_kernel_trace_modes():
    """kernel_trace supports network_sniff, security_audit, tcp_listeners and aliases."""
    modes = server._BPFTRACE_MODES
    assert "network_sniff" in modes
    assert "security_audit" in modes
    assert "tcp_listeners" in modes

    aliases = server._BPFTRACE_MODE_ALIASES
    assert aliases.get("sniff") == "network_sniff"
    assert aliases.get("network") == "network_sniff"
    assert aliases.get("audit") == "security_audit"
    assert aliases.get("listeners") == "tcp_listeners"

    # Trace mode alias resolves without INVALID_MODE
    raw = await server.kernel_trace(mode="sniff", duration_sec=1)
    res = json.loads(raw)
    assert res.get("status") != "INVALID_MODE"


def test_gate7_tactical_playbook_wf10_wf11():
    """tactical_playbook includes WF-10, WF-11 and quick reference items."""
    pb = tactical_playbook()
    recipes = pb.get("workflow_recipes", [])
    recipe_ids = {r.get("id"): r for r in recipes}
    assert "WF-10" in recipe_ids
    assert "WF-11" in recipe_ids
    assert "Network Tactical Recon" in recipe_ids["WF-10"]["name"]
    assert "Incident Protocol Audit" in recipe_ids["WF-11"]["name"]

    qref = pb.get("quick_reference", {})
    assert "network_tactical_recon" in qref
    assert "incident_protocol_audit" in qref


def test_gate8_instructions_consistency():
    """server instructions document WF-10/WF-11, trace modes, and tactical security."""
    inst = server._INSTRUCTIONS
    assert "WF-1..WF-9" in inst and "WF-10" in inst and "WF-11" in inst
    assert "network_sniff" in inst
    assert "security_audit" in inst
    assert "tcp_listeners" in inst
    assert "WF-10" in inst
    assert "WF-11" in inst
