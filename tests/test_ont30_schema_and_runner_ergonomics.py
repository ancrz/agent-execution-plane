"""
Tests for Milestone ONT-30: AEP Cross-Harness Schema Evolution & Multi-Runner Ergonomics Stabilization.

Verifies:
  - Gate 1: FastMCP strictly maintains exactly 15 tools (zero tool footprint expansion).
  - Gate 2: Schema evolution signaling (capabilities.tools.listChanged = True) & discover capabilities metadata (server_version, git_commit, schema_hash).
  - Gate 3: Multi-harness process observability (pid, process_start_time, uptime_seconds, and aep-sync.sh --audit).
  - Gate 4: topos_audit_dag resilient task-level resource hazard fallback (Directive OM-2).
  - Gate 5: sandbox_run brief mode trimming with parse (Directive OM-3 & input reflection suppression).
  - Gate 6: sandbox_run pytest failing test node IDs extraction (failures & failing_nodes).
  - Gate 7: sandbox_run composite runner chained output parsing (parse="auto" -> {"tool": "composite", "ruff": {...}, "pytest": {...}}).
  - Gate 8: Playbook tactical recipes discoverability (WF-7, WF-8, WF-9, quick_reference, and RoE).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import unittest.mock as mock

import server
from engine.topos_guard import ToposVerdict

# ==============================================================================
# Gate 1: FastMCP 15 Tools Invariant
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


# ==============================================================================
# Gate 2: Schema Evolution Signaling & Capabilities Metadata (GAP-DX-05)
# ==============================================================================


def test_gate2_schema_evolution_and_drift_detection() -> None:
    """FastMCP advertises tools.listChanged = True and exposes schema evolution metadata."""
    # 1. Initialization options advertise capabilities.tools.listChanged = True
    opts = server.mcp._mcp_server.create_initialization_options()
    assert opts.capabilities.tools is not None
    assert opts.capabilities.tools.listChanged is True

    # 2. discover(action="capabilities") exposes server_version, git_commit, schema_hash across all verbosities
    for v in ("detail", "summary", "brief", "terse"):
        raw = asyncio.run(server.discover(action="capabilities", verbosity=v, force_refresh=True))
        d = json.loads(raw)
        assert d.get("server_version") == "v0.2.8", f"Missing or invalid server_version in {v}"
        assert d.get("git_commit") is not None and len(d["git_commit"]) > 0, f"Missing git_commit in {v}"
        assert len(d.get("schema_hash", "")) == 64, f"schema_hash must be 64-char SHA256 in {v}"

    # 3. schema_hash is deterministic across calls
    hash1 = server._get_schema_hash()
    hash2 = server._get_schema_hash()
    assert hash1 == hash2
    assert re.match(r"^[0-9a-f]{64}$", hash1) is not None


# ==============================================================================
# Gate 3: Multi-Harness Process Observability (GAP-RT-03)
# ==============================================================================


def test_gate3_multi_harness_process_observability() -> None:
    """discover and process_inspect expose PID, process_start_time, and uptime; aep-sync.sh audits instances."""
    # 1. discover(action="capabilities") exposes pid, process_start_time, uptime_seconds
    raw = asyncio.run(server.discover(action="capabilities", verbosity="summary", force_refresh=True))
    d = json.loads(raw)
    assert d.get("pid") == os.getpid()
    assert "process_start_time" in d
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", d["process_start_time"]) is not None
    assert isinstance(d.get("uptime_seconds"), (int, float))
    assert d["uptime_seconds"] >= 0.0

    # 2. process_inspect(pid=0) self-inspection exposes process_start_time and uptime_seconds
    raw_insp = asyncio.run(server.process_inspect(pid=0, verbosity="summary"))
    d_insp = json.loads(raw_insp)
    assert d_insp.get("pid") == os.getpid()
    assert "process_start_time" in d_insp
    assert "uptime_seconds" in d_insp

    # 3. scripts/aep-sync.sh --audit executes without errors and exits 0 (Directive OM-4: warn-only, never kill)
    res_audit = subprocess.run(
        ["bash", "scripts/aep-sync.sh", "--audit"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_audit.returncode == 0
    assert (
        "Auditando instancias activas de AEP" in res_audit.stdout
        or "Auditando instancias activas de AEP" in res_audit.stderr
    )


# ==============================================================================
# Gate 4: topos_audit_dag Resilient Task-Level Resource Fallback (GAP-DX-05 / OM-2)
# ==============================================================================


def test_gate4_topos_audit_dag_resilient_resource_fallback() -> None:
    """topos_audit_dag extracts task writes/reads/contract when top-level resources is omitted."""
    # 1. Write-Write hazard without contract returns WARN
    tasks_hazard = [
        {"id": "t1", "writes": ["shared_state.json"]},
        {"id": "t2", "writes": ["shared_state.json"]},
    ]
    raw_w1 = asyncio.run(server.topos_audit_dag(tasks=tasks_hazard, dependencies={}))
    d_w1 = json.loads(raw_w1)
    assert d_w1["verdict"] == ToposVerdict.WARN
    assert "shared_state.json" in d_w1.get("resources", {})
    assert any("Shared write-set hazard" in line for line in d_w1.get("details", []))

    # 2. Write-Write hazard with declared contract returns APPROVED
    tasks_safe = [
        {"id": "t1", "writes": ["shared_state.json"], "contract": "rw_mutex"},
        {"id": "t2", "writes": ["shared_state.json"], "contract": "rw_mutex"},
    ]
    raw_w2 = asyncio.run(server.topos_audit_dag(tasks=tasks_safe, dependencies={}))
    d_w2 = json.loads(raw_w2)
    assert d_w2["verdict"] == ToposVerdict.APPROVED

    # 3. Mutual coupled writers without interface node returns BLOCKED
    tasks_coupled = [
        {"id": "t1", "writes": ["shared_state.json"]},
        {"id": "t2", "writes": ["shared_state.json"]},
    ]
    deps_coupled = {"t1": ["t2"], "t2": ["t1"]}
    raw_blocked = asyncio.run(server.topos_audit_dag(tasks=tasks_coupled, dependencies=deps_coupled))
    d_blocked = json.loads(raw_blocked)
    assert d_blocked["verdict"] == ToposVerdict.BLOCKED
    assert any("co-dependency detected" in line.lower() for line in d_blocked.get("details", []))


# ==============================================================================
# Gate 5: sandbox_run Brief Mode Trimming with Parse
# ==============================================================================


def test_gate5_sandbox_run_brief_trimming() -> None:
    """sandbox_run in brief mode with parse suppresses input reflection and empty output."""
    mock_proc = mock.Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = "= 42 passed in 1.15s ="
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc):
        raw = asyncio.run(server.sandbox_run(command="pytest -q", parse="pytest", verbosity="brief"))
        d = json.loads(raw)
        # Verify stripped fixed fields
        assert "ro_mounts" not in d
        assert "rw_mounts" not in d
        assert "agent_id" not in d
        assert "share_net" not in d
        assert "working_dir" not in d
        # Verify essential fields
        assert d["status"] == "SUCCESS"
        assert d["exit_code"] == 0
        assert d["parsed"]["passed"] == 42
        assert "t" in d


# ==============================================================================
# Gate 6: sandbox_run Pytest Failing Test Node IDs Extraction (OM-3)
# ==============================================================================


def test_gate6_sandbox_run_pytest_failing_node_ids() -> None:
    """_parse_runner_output extracts failing test node IDs into parsed['failures']."""
    raw_pytest_fail = """
=================================== FAILURES ===================================
__________________________________ test_auth ___________________________________
tests/test_auth.py:45: AssertionError
FAILED tests/test_auth.py::test_login_invalid_token - AssertionError: Expected 401
ERROR tests/test_db.py::test_migration - RuntimeError: Migration lock timeout
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_login_invalid_token
ERROR tests/test_db.py::test_migration
= 10 passed, 1 failed, 1 error in 2.34s =
"""
    res = server._parse_runner_output(raw_pytest_fail, "pytest", "pytest")
    assert res is not None
    assert res["failed"] == 1
    assert res["errors"] == 1
    assert "failures" in res
    assert "tests/test_auth.py::test_login_invalid_token" in res["failures"]
    assert "tests/test_db.py::test_migration" in res["failures"]

    # In sandbox_run brief with non-zero exit code: failures and stdout_tail are exposed
    mock_proc = mock.Mock()
    mock_proc.returncode = 1
    mock_proc.stdout = raw_pytest_fail
    mock_proc.stderr = ""

    with mock.patch("server.subprocess.run", return_value=mock_proc):
        raw_run = asyncio.run(server.sandbox_run(command="pytest", parse="pytest", verbosity="brief"))
        d_run = json.loads(raw_run)
        assert d_run["status"] == "EXEC_FAILED"
        assert d_run["exit_code"] == 1
        assert "failures" in d_run
        assert "tests/test_auth.py::test_login_invalid_token" in d_run["failures"]
        assert "stdout_tail" in d_run


# ==============================================================================
# Gate 7: sandbox_run Composite Runner Output Parsing (parse="auto")
# ==============================================================================


def test_gate7_sandbox_run_composite_runner_parsing() -> None:
    """_parse_runner_output(mode='auto') parses chained ruff && pytest output into composite dict."""
    combined_output = """
All checks passed!
============================= test session starts ==============================
= 25 passed in 0.85s =
"""
    res = server._parse_runner_output(combined_output, "ruff check . && pytest -q", "auto")
    assert res is not None
    assert res["tool"] == "composite"
    assert "ruff" in res and res["ruff"]["violations"] == 0
    assert "pytest" in res and res["pytest"]["passed"] == 25


# ==============================================================================
# Gate 8: Playbook Tactical Recipes Discoverability & Guidelines
# ==============================================================================


def test_gate8_playbook_tactical_recipes_discoverability() -> None:
    """discover(action='playbook') returns WF-7, WF-8, WF-9, quick_reference and RoE."""
    raw = asyncio.run(server.discover(action="playbook", verbosity="summary", force_refresh=True))
    d = json.loads(raw)
    recipes = d.get("workflow_recipes", [])
    recipe_ids = {r["id"]: r for r in recipes}

    # Verify recipes WF-7, WF-8, WF-9
    assert "WF-7" in recipe_ids
    assert "sandbox-linter-fix" in recipe_ids["WF-7"]["name"]
    assert "rw_paths" in str(recipe_ids["WF-7"]["steps"])

    assert "WF-8" in recipe_ids
    assert "untrusted-adversarial-probe" in recipe_ids["WF-8"]["name"]
    assert "scratch" in str(recipe_ids["WF-8"]["steps"])

    assert "WF-9" in recipe_ids
    assert "composite-verification-runner" in recipe_ids["WF-9"]["name"]
    assert 'parse="auto"' in str(recipe_ids["WF-9"]["steps"])

    # Verify quick_reference
    qref = d.get("quick_reference", {})
    assert "sandbox_linter_fix" in qref
    assert "untrusted_adversarial_probe" in qref
    assert "composite_verification" in qref

    # Verify Rules of Engagement
    roe = d.get("rules_of_engagement", [])
    assert any("TACTICAL SANDBOX RECIPES (ONT-30)" in rule for rule in roe)

    # Verify instructions reference WF-1..WF-9
    assert "WF-1..WF-9" in server._INSTRUCTIONS
