"""
Tests for Milestone ONT-29: AEP External Consumption Gaps Remediation & Chrysalis Bridge Stabilization.

Verifies:
  - Gate 1: FastMCP strictly maintains exactly 15 tools (zero footprint expansion).
  - Gate 2: GAP-OM-19 FastMCP single-encoding (output_schema is None on all 15 tools).
  - Gate 3: GAP-OM-16 Envelope deduplication & stub telemetry in brief/terse; output_bytes(brief) < output_bytes(summary).
  - Gate 4: GAP-OM-17 Bernstein resource audit, 2-tuple return contract, WARN on hazard, BLOCKED on mutual co-dep.
  - Gate 5: GAP-CP-04 Workspace snapshot & byte-identical restore round-trip, 50MB cap, CapabilityGuard blacklist.
  - Gate 6: GAP-OM-18 Per-agent usage accounting ledger in audit domain.
  - Gate 7: GAP-DX-04 Structured pytest/ruff test parsing in sandbox_run and stdout suppression in brief.
  - Gate 8: GAP-DOC-02 Discoverability of RAM session caching (session_hint & Rules of Engagement).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest.mock as mock
from pathlib import Path

import server
from engine.backup import create_workspace_snapshot, restore_workspace_snapshot
from engine.playbook import PlaybookStore
from engine.privilege import CONTROL_PLANE_SCHEMA, tactical_playbook
from engine.security import _ensure_audit_table, get_agent_usage_summary, record_audit_event
from engine.telemetry import RequestTelemetry, attach_envelope
from engine.topos_guard import ToposGuard, ToposVerdict

# ==============================================================================
# Gate 1 & 2: FastMCP 15 Tools & Single-Encoding Invariant (GAP-OM-19)
# ==============================================================================

def test_gate1_exactly_15_fastmcp_tools() -> None:
    """The FastMCP server MUST strictly expose exactly 15 tools."""
    tools = server.mcp._tool_manager._tools
    assert len(tools) == 15, f"Expected exactly 15 tools, found {len(tools)}: {list(tools.keys())}"
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


def test_gate2_fastmcp_single_encoding_gap_om19() -> None:
    """All 15 tools must have output_schema is None (structured_output=False)."""
    tools = server.mcp._tool_manager._tools
    for tool_name, tool in tools.items():
        assert tool.output_schema is None, f"Tool {tool_name} has output_schema {tool.output_schema}; must be None"


# ==============================================================================
# Gate 3: Envelope Restructuring & Stub Telemetry (GAP-OM-16)
# ==============================================================================

def test_gate3_envelope_brief_terse_deduplication() -> None:
    """In brief/terse, nested payload['envelope'] is omitted; telemetry stub is emitted."""
    t = RequestTelemetry("test_probe", "probe_action")
    raw_brief = attach_envelope({"status": "OK", "data": "value"}, t, verbosity="brief")
    d_brief = json.loads(raw_brief)

    assert "envelope" not in d_brief, f"envelope found in brief response: {d_brief}"
    assert "telemetry" not in d_brief, f"telemetry found in brief response: {d_brief}"
    assert "t" in d_brief, f"telemetry stub 't' missing in brief response: {d_brief}"
    assert "ms" in d_brief["t"] and "tok" in d_brief["t"]
    assert d_brief["status"] == "OK"
    assert d_brief["severity"] == "INFO"
    assert "summary" in d_brief
    assert "next_action" in d_brief

    # Test explicit telemetry=False
    t_off = RequestTelemetry("test_probe", "probe_action")
    raw_off = attach_envelope({"status": "OK"}, t_off, verbosity="brief", telemetry=False)
    d_off = json.loads(raw_off)
    assert "t" not in d_off
    assert "telemetry" not in d_off

    # Test detail mode preserves nested envelope and full telemetry
    t_det = RequestTelemetry("test_probe", "probe_action")
    raw_det = attach_envelope({"status": "OK", "data": "value"}, t_det, verbosity="detail")
    d_det = json.loads(raw_det)
    assert "envelope" in d_det
    assert "telemetry" in d_det
    assert "request_id" in d_det["telemetry"]
    assert "rss_kb" in d_det["telemetry"]

    # Invariant: output_bytes(brief) < output_bytes(summary)
    t_sum = RequestTelemetry("test_probe", "probe_action")
    raw_sum = attach_envelope({"status": "OK", "data": "value"}, t_sum, verbosity="summary")
    assert len(raw_brief.encode("utf-8")) < len(raw_sum.encode("utf-8"))


# ==============================================================================
# Gate 4: Topos Shared-Write-Set Co-Dependency & Bernstein Hazard (GAP-OM-17)
# ==============================================================================

def test_gate4_topos_bernstein_resource_audit() -> None:
    """ToposGuard audits Bernstein write-write hazards (WARN) and mutual co-dependencies (BLOCKED)."""
    # 1. Critical Safeguard from Ontos: 2-tuple return contract preserved
    res_clean = ToposGuard.audit_task_dag(["T1", "T2"], {"T2": ["T1"]})
    assert isinstance(res_clean, tuple) and len(res_clean) == 2
    verdict, logs = res_clean
    assert verdict == ToposVerdict.APPROVED

    # PlaybookStore validate_and_order unpacks without TypeError
    steps = [{"id": "s1", "tool": "process_inspect"}, {"id": "s2", "tool": "aep_ctl", "depends_on": ["s1"]}]
    pb_order = PlaybookStore.validate_and_order(steps)
    assert pb_order["ok"] is True

    # 2. Bernstein Condition 1: 2 writers on a resource without contract -> WARN
    res_warn = ToposGuard.audit_task_dag(
        ["w1", "w2"],
        {},
        resources={"shared_state": {"writers": ["w1", "w2"]}},
    )
    assert res_warn[0] == ToposVerdict.WARN
    assert any("Shared write-set hazard" in line for line in res_warn[1])

    # With contract declared -> APPROVED
    res_contract = ToposGuard.audit_task_dag(
        ["w1", "w2"],
        {},
        resources={"shared_state": {"writers": ["w1", "w2"], "contract": "v1_mutex"}},
    )
    assert res_contract[0] == ToposVerdict.APPROVED

    # 3. Bernstein Condition 2: 2 writers mutually coupled without interface -> BLOCKED
    res_blocked = ToposGuard.audit_task_dag(
        ["w1", "w2"],
        {"w1": ["w2"], "w2": ["w1"]},
        resources={"shared_state": {"writers": ["w1", "w2"]}},
    )
    assert res_blocked[0] == ToposVerdict.BLOCKED
    assert any("Shared mutable state co-dependency" in line for line in res_blocked[1])

    # 4. server.py:topos_audit_dag accepts resources parameter and returns edges
    raw_server = asyncio.run(
        server.topos_audit_dag(
            tasks=["t1", "t2"],
            dependencies={"t2": ["t1"]},
            resources={"cache": {"writers": ["t1", "t2"]}},
            verbosity="summary",
        )
    )
    d_srv = json.loads(raw_server)
    assert d_srv["verdict"] == ToposVerdict.WARN
    assert "edges" in d_srv
    assert len(d_srv["edges"]) == 1
    assert d_srv["edges"][0]["type"] == "dependency"


# ==============================================================================
# Gate 5: Workspace Snapshot Round-Trip & Blacklist Guard (GAP-CP-04)
# ==============================================================================

def test_gate5_workspace_snapshot_and_restore_roundtrip() -> None:
    """Workspace snapshot captures directory tree and restores byte-identical state."""
    # 1. Schema check
    assert "workspace_snapshot" in CONTROL_PLANE_SCHEMA["backup"]["actions"]
    assert "workspace_restore" in CONTROL_PLANE_SCHEMA["backup"]["actions"]

    # 2. CapabilityGuard blacklist
    res_bl = create_workspace_snapshot("~/.ssh")
    assert res_bl["status"] == "PERMISSION_DENIED"

    # 3. Round-trip file restoration
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        f1 = td / "module.py"
        f1.write_text("def hello(): return 'world'\n", encoding="utf-8")
        sub = td / "subpkg"
        sub.mkdir()
        f2 = sub / "init.py"
        f2.write_text("# init\n", encoding="utf-8")

        # Snapshot
        snap_res = create_workspace_snapshot(td, name="test_snap_ont29")
        assert snap_res["status"] == "SUCCESS"
        assert Path(snap_res["archive_path"]).exists()

        # Mutate workspace (modify, delete, create extra)
        f1.unlink()
        f2.write_text("# corrupted\n", encoding="utf-8")
        (td / "rogue.tmp").write_text("untracked\n", encoding="utf-8")

        # Restore
        rest_res = restore_workspace_snapshot(td, name="test_snap_ont29")
        assert rest_res["status"] == "SUCCESS"
        assert rest_res["restored"] is True

        # Assert byte-identical restoration
        assert f1.exists() and f1.read_text(encoding="utf-8") == "def hello(): return 'world'\n"
        assert f2.exists() and f2.read_text(encoding="utf-8") == "# init\n"
        assert not (td / "rogue.tmp").exists()


# ==============================================================================
# Gate 6: Per-Agent Usage Accounting Ledger (GAP-OM-18)
# ==============================================================================

def test_gate6_per_agent_usage_accounting() -> None:
    """get_agent_usage_summary groups tool usage, bytes, tokens, and latency per agent."""
    # 1. Schema check
    assert "usage" in CONTROL_PLANE_SCHEMA["audit"]["actions"]

    # 2. In-memory ledger test
    conn = sqlite3.connect(":memory:")
    _ensure_audit_table(conn)

    record_audit_event(
        conn,
        agent_id="archon",
        tool_name="discover",
        action="capabilities",
        capability_tier="FULL",
        status="OK",
        details={"output_bytes": 1200, "estimated_tokens": 300, "latency_ms": 4.5},
    )
    record_audit_event(
        conn,
        agent_id="pragma",
        tool_name="sandbox_run",
        action="exec",
        capability_tier="FULL",
        status="SUCCESS",
        details={"output_bytes": 800, "estimated_tokens": 200, "latency_ms": 8.0},
    )
    record_audit_event(
        conn,
        agent_id="pragma",
        tool_name="sandbox_run",
        action="exec",
        capability_tier="FULL",
        status="SUCCESS",
        details={"output_bytes": 600, "estimated_tokens": 150, "latency_ms": 6.0},
    )
    record_audit_event(
        conn,
        agent_id="dokimos",
        tool_name="topos_audit_dag",
        action="audit",
        capability_tier="FULL",
        status="SUCCESS",
        details={"output_bytes": 400, "estimated_tokens": 100, "latency_ms": 1.5},
    )

    usage = get_agent_usage_summary(conn)
    assert usage["status"] == "OK"
    assert usage["total_calls"] == 4
    assert usage["agent_count"] == 3

    assert "archon" in usage["agents"]
    assert "pragma" in usage["agents"]
    assert "dokimos" in usage["agents"]

    p = usage["agents"]["pragma"]
    assert p["calls"] == 2
    assert p["bytes"] == 1400
    assert p["tokens"] == 350
    assert p["latency_ms"] == 14.0
    assert "sandbox_run" in p["tools"]
    assert p["tools"]["sandbox_run"]["calls"] == 2


# ==============================================================================
# Gate 7: Structured Test & Linter Parsing in sandbox_run (GAP-DX-04)
# ==============================================================================

def test_gate7_sandbox_run_structured_parsing() -> None:
    """sandbox_run parse='pytest'|'ruff'|'auto' extracts metrics and suppresses stdout in brief."""
    # 1. Unit parsing pytest
    out_pytest = "= 35 passed, 2 failed, 1 warning in 2.50s ="
    p_res = server._parse_runner_output(out_pytest, "pytest", "pytest")
    assert p_res is not None
    assert p_res["tool"] == "pytest"
    assert p_res["passed"] == 35
    assert p_res["failed"] == 2
    assert p_res["duration_s"] == 2.50
    assert p_res["total"] == 37

    # 2. Unit parsing ruff
    out_ruff = "Found 7 errors (3 fixable via --fix)."
    r_res = server._parse_runner_output(out_ruff, "ruff", "ruff")
    assert r_res is not None
    assert r_res["tool"] == "ruff"
    assert r_res["violations"] == 7
    assert r_res["fixable"] == 3

    # 3. Fail-soft on invalid output
    soft_res = server._parse_runner_output("unrelated log line without metrics", "cmd", "pytest")
    assert soft_res is None

    # 4. Mocked sandbox_run brief stdout suppression
    mock_proc = mock.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "= 50 passed in 1.23s ="
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc):
        raw_brief = asyncio.run(server.sandbox_run(command="pytest", parse="pytest", verbosity="brief"))
        d_brief = json.loads(raw_brief)
        assert "parsed" in d_brief
        assert d_brief["parsed"]["passed"] == 50
        assert d_brief["stdout"] == ""  # Suppressed in brief mode


# ==============================================================================
# Gate 8: RAM Session Caching Discoverability & RoE (GAP-DOC-02)
# ==============================================================================

def test_gate8_ram_session_caching_discoverability() -> None:
    """discover(capabilities) returns session_hint and documentation covers RAM caching."""
    # 1. session_hint in discover capabilities
    raw = asyncio.run(server.discover(action="capabilities", verbosity="summary"))
    d = json.loads(raw)
    assert "session_hint" in d
    assert "session_id" in d["session_hint"]
    assert "terse" in d["session_hint"]

    # 2. _INSTRUCTIONS RoE
    assert "Multi-Agent RAM Capability Caching" in server._INSTRUCTIONS

    # 3. tactical_playbook RoE and quick_reference
    pb = tactical_playbook()
    assert any("multi-agent ram capability caching" in r.lower() for r in pb["rules_of_engagement"])
    assert "terse_cached_capabilities" in pb["quick_reference"]
