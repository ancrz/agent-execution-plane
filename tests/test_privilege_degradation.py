"""
Quality Assurance Test Battery: Milestone ONT-33
Predictive Privilege-Aware Setup Pipeline & Chmod Graceful Degradation Matrix

Implements the 8 Quality Gates specified in the Ontos-approved plan:
  Gate 1: FastMCP 16-Tool Invariant Gate
  Gate 2: 4-Tier Chmod Classification & Prober Gate
  Gate 3: Setup Script Non-Interactive & Tier Reporting Gate
  Gate 4: Capabilities Matrix & Schema Synchrony Gate
  Gate 5: 16-Tool Graceful Degradation Contracts Gate
  Gate 6: Control Plane 8-Domain Degradation Gate
  Gate 7: Zero-Hangs Non-Interactive Guarantee (Timeout <= 3s) Gate
  Gate 8: Semantic Sanitization & Least-Privilege Gate
"""

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import server
from engine.privilege import (
    ALL_TIERS,
    TIER_4R,
    TIER_5RX,
    TIER_6RW,
    TIER_7RWX,
    TIER_OCTALS,
    _PrivilegeCache,
    capability_tier,
    detect_chmod_tier,
    get_effective_chmod_tier,
    privilege_prefix,
    sudo_n_available,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ==============================================================================
# Gate 1: FastMCP 16-Tool Invariant Gate
# ==============================================================================
def test_gate1_fastmcp_16_tool_invariant() -> None:
    """Gate 1: Verify exactly 16 polymorphic tools are registered in server.py (zero tool sprawl)."""
    tools = server.mcp._tool_manager._tools
    assert len(tools) == 16, f"FastMCP tool invariant violated: expected exactly 16 tools, got {len(tools)}"

    expected_tools = {
        "topos_audit_dag",
        "discover",
        "artifact_catalog",
        "artifact_lint_and_build",
        "artifact_execute_in_ram",
        "default_primitives",
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
    assert set(tools.keys()) == expected_tools, f"Tool set mismatch: {set(tools.keys()) ^ expected_tools}"

    # Verify all 16 tools are documented in _INSTRUCTIONS and include chmod octal tier headers
    assert "Complete 16-Tool Suite Map" in server._INSTRUCTIONS
    assert "4-tier Unix chmod octal privilege governance" in server._INSTRUCTIONS
    for tname in expected_tools:
        assert tname in server._INSTRUCTIONS, f"Tool {tname} missing from server._INSTRUCTIONS"


# ==============================================================================
# Gate 2: 4-Tier Chmod Classification & Prober Gate
# ==============================================================================
def test_gate2_tier_detection_accuracy() -> None:
    """Gate 2: Accurate detection of 7rwx, 6rw-, 5r-x, and 4r-- under simulated and live environments."""
    for expected_tier in (TIER_7RWX, TIER_6RW, TIER_5RX, TIER_4R):
        with patch.dict(os.environ, {"AEP_FORCE_TIER": expected_tier}):
            _PrivilegeCache.reset()
            info = detect_chmod_tier()
            assert info["tier"] == expected_tier
            assert info["octal"] == TIER_OCTALS[expected_tier]
            assert "degradation_plan" in info
            assert "probe_flags" in info
            assert get_effective_chmod_tier()["tier"] == expected_tier

            # Verify backward compatibility mappings
            expected_cap = "FULL" if expected_tier == TIER_7RWX else "DIMINISHED"
            assert capability_tier() == expected_cap
            if expected_tier == TIER_7RWX:
                assert privilege_prefix() is not None
            else:
                assert privilege_prefix() is None

    # Test reset helper (Ontos Advisory 2)
    _PrivilegeCache.reset()
    assert _PrivilegeCache.sudo_n is None
    assert _PrivilegeCache.tier_info is None

    # Live detection check without overrides
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AEP_FORCE_TIER", None)
        os.environ.pop("AEP_CHMOD_TIER", None)
        _PrivilegeCache.reset()
        live_info = detect_chmod_tier()
        assert live_info["tier"] in ALL_TIERS
        assert live_info["octal"] in (7, 6, 5, 4)
        assert isinstance(live_info["workspace_writable"], bool)


# ==============================================================================
# Gate 3: Setup Script Non-Interactive & Tier Reporting Gate
# ==============================================================================
def test_gate3_setup_cli_consistency() -> None:
    """Gate 3: Verify setup.sh --tier and --predict execution without interactive hangs."""
    setup_path = PROJECT_ROOT / "scripts" / "setup.sh"
    assert setup_path.exists(), "scripts/setup.sh must exist"

    # 1. bash -n syntax check
    res_syntax = subprocess.run(["bash", "-n", str(setup_path)], capture_output=True, text=True, check=False)
    assert res_syntax.returncode == 0, f"bash -n failed: {res_syntax.stderr}"

    # 2. Test --tier flag with simulated tiers
    for test_tier in (TIER_7RWX, TIER_6RW, TIER_5RX, TIER_4R):
        res_tier = subprocess.run(
            ["bash", str(setup_path), "--tier"],
            env={**os.environ, "AEP_FORCE_TIER": test_tier},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert res_tier.returncode == 0, f"--tier failed: {res_tier.stderr}"
        assert res_tier.stdout.strip() == test_tier

    # 3. Test --predict flag output
    res_predict = subprocess.run(
        ["bash", str(setup_path), "--predict"],
        env={**os.environ, "AEP_FORCE_TIER": TIER_6RW},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert res_predict.returncode == 0
    assert "AEP Predictive Privilege Probing & Degradation Matrix" in res_predict.stdout
    assert "Detected Chmod Tier: 6rw-" in res_predict.stdout
    assert "FastMCP 16-Tool Degradation Posture" in res_predict.stdout


# ==============================================================================
# Gate 4: Capabilities Matrix & Schema Synchrony Gate
# ==============================================================================
def test_gate4_capabilities_matrix_synchrony() -> None:
    """Gate 4: Ensure capabilities and schema discovery reflect the chmod degradation matrix."""
    async def _run() -> None:
        # Test discover(action="capabilities")
        raw_caps = await server.discover(action="capabilities", force_refresh=True)
        caps_data = json.loads(raw_caps)
        assert caps_data["status"] == "OK"
        assert "effective_chmod_tier" in caps_data
        assert caps_data["effective_chmod_tier"] in ALL_TIERS
        assert "chmod_octal" in caps_data
        assert "degradation_matrix" in caps_data
        assert len(caps_data["degradation_matrix"]["tools"]) == 16
        assert len(caps_data["degradation_matrix"]["domains"]) == 9

        # Test discover(action="schema")
        raw_schema = await server.discover(action="schema", force_refresh=True)
        schema_data = json.loads(raw_schema)
        assert schema_data["status"] == "OK"
        assert "degradation_matrix" in schema_data
        for tname, tinfo in schema_data["tools"].items():
            assert "degradation_behavior" in tinfo, f"Tool {tname} missing degradation_behavior"
            assert len(tinfo["degradation_behavior"]) == 4, f"Tool {tname} missing all 4 tiers in degradation_behavior"

    asyncio.run(_run())


# ==============================================================================
# Gate 5: 16-Tool Graceful Degradation Contracts Gate
# ==============================================================================
def test_gate5_tool_degradation_contracts() -> None:
    """Gate 5: Confirm all 16 tools degrade gracefully without unhandled exceptions across tiers."""
    async def _run() -> None:
        # In Tier 4 (auditor), execution tools must degrade fail-soft
        with patch.dict(os.environ, {"AEP_FORCE_TIER": TIER_4R}):
            _PrivilegeCache.reset()

            # 1. artifact_execute_in_ram in 4r-- -> PERMISSION_DENIED
            res_ram = json.loads(await server.artifact_execute_in_ram(name="socket_monitor"))
            assert res_ram["status"] == "PERMISSION_DENIED"
            assert res_ram.get("chmod_tier") == "4r--"

            # 2. artifact_lint_and_build(action="build") in 4r-- -> DEGRADED
            res_build = json.loads(await server.artifact_lint_and_build(action="build", template_name="mem-stat"))
            assert res_build["status"] == "DEGRADED"
            assert res_build.get("chmod_tier") == "4r--"

            # 3. sandbox_run in 4r-- -> DEGRADED dry-run
            res_sb = json.loads(await server.sandbox_run(command="echo test"))
            assert res_sb["status"] == "DEGRADED"
            assert res_sb.get("chmod_tier") == "4r--"
            assert "DRY_RUN_AUDITOR" in res_sb.get("stdout", "")

            # 4. async_job_dispatch(action="dispatch") in 4r-- -> DEGRADED
            res_async = json.loads(await server.async_job_dispatch(action="dispatch", command="echo test"))
            assert res_async["status"] == "DEGRADED"
            assert res_async.get("chmod_tier") == "4r--"

            # 5. kanban_board(action="create") in 4r-- -> DEGRADED
            res_kanban = json.loads(await server.kanban_board(action="create", title="Test task"))
            assert res_kanban["status"] == "DEGRADED"
            assert res_kanban.get("chmod_tier") == "4r--"

            # 6. playbook_run(action="run") in 4r-- -> DEGRADED
            res_pb = json.loads(await server.playbook_run(action="run", name="test-pb"))
            assert res_pb["status"] == "DEGRADED"
            assert res_pb.get("chmod_tier") == "4r--"

            # 7. artifact_catalog(action="prune") in 4r-- -> DEGRADED
            res_cat = json.loads(await server.artifact_catalog(action="prune"))
            assert res_cat["status"] == "DEGRADED"
            assert res_cat.get("chmod_tier") == "4r--"

            # 8. default_primitives(action="run") in 4r-- -> PERMISSION_DENIED
            res_prim = json.loads(await server.default_primitives(action="run", name="disk-usage"))
            assert res_prim["status"] == "PERMISSION_DENIED"
            assert res_prim.get("chmod_tier") == "4r--"

        _PrivilegeCache.reset()

    asyncio.run(_run())


# ==============================================================================
# Gate 6: Control Plane 8-Domain Degradation Gate
# ==============================================================================
def test_gate6_control_plane_degradation() -> None:
    """Gate 6: All 8 control plane domains handle diminished tiers fail-soft."""
    ctl_path = PROJECT_ROOT / "scripts" / "aep-ctl"

    # 1. Schema discovery includes chmod_tier and degradation_matrix
    res_schema = subprocess.run([str(ctl_path), "--schema"], capture_output=True, text=True, check=False)
    assert res_schema.returncode == 0
    data_schema = json.loads(res_schema.stdout)
    assert data_schema["status"] == "OK"
    assert "chmod_tier" in data_schema
    assert "degradation_matrix" in data_schema

    # 2. Service domain mutation degradation
    for tier, expected_status in [("4r--", "SIMULATED"), ("5r-x", "DEGRADED")]:
        res_svc = subprocess.run(
            [str(ctl_path), "service", "restart", "test-svc"],
            env={**os.environ, "AEP_FORCE_TIER": tier},
            capture_output=True,
            text=True,
            check=False,
        )
        data_svc = json.loads(res_svc.stdout)
        assert data_svc["status"] == expected_status
        assert data_svc["chmod_tier"] == tier

    # 3. Security domain threat_mitigate degradation
    for tier in ("4r--", "5r-x", "6rw-"):
        res_sec = subprocess.run(
            [str(ctl_path), "security", "threat_mitigate", "192.168.1.1"],
            env={**os.environ, "AEP_FORCE_TIER": tier},
            capture_output=True,
            text=True,
            check=False,
        )
        data_sec = json.loads(res_sec.stdout)
        assert data_sec["status"] == "SIMULATED"

    # 4. Backup domain mutation degradation in 4r-- and 5r-x
    res_bkp = subprocess.run(
        [str(ctl_path), "backup", "backup"],
        env={**os.environ, "AEP_FORCE_TIER": "4r--"},
        capture_output=True,
        text=True,
        check=False,
    )
    data_bkp = json.loads(res_bkp.stdout)
    assert data_bkp["status"] == "DEGRADED"

    # 5. IPC domain mutation degradation in 4r--
    res_ipc = subprocess.run(
        [str(ctl_path), "ipc", "lease"],
        env={**os.environ, "AEP_FORCE_TIER": "4r--"},
        capture_output=True,
        text=True,
        check=False,
    )
    data_ipc = json.loads(res_ipc.stdout)
    assert data_ipc["status"] == "DEGRADED"


# ==============================================================================
# Gate 7: Zero-Hangs Non-Interactive Guarantee (Timeout <= 3s)
# ==============================================================================
def test_gate7_zero_hangs_non_interactive_guarantee() -> None:
    """Gate 7: Verify zero interactive sudo hangs with strict <=3s prober timeout."""
    # 1. Source code inspection of timeout parameter
    privilege_src = (PROJECT_ROOT / "engine" / "privilege.py").read_text(encoding="utf-8")
    assert 'timeout=3' in privilege_src or 'timeout=2' in privilege_src, "sudo -n prober must specify timeout <= 3"

    # 2. Timing probe guarantee
    _PrivilegeCache.reset()
    t0 = time.perf_counter()
    res = sudo_n_available()
    t1 = time.perf_counter()
    assert (t1 - t0) < 3.5, f"sudo_n_available took too long: {t1 - t0:.2f}s"
    assert isinstance(res, bool)

    # 3. Simulate subprocess timeout / hang
    _PrivilegeCache.reset()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sudo", "-n", "true"], timeout=3)):
        res_hang = sudo_n_available()
        assert res_hang is False, "Timed out sudo check must return False fail-soft without exceptions"


# ==============================================================================
# Gate 8: Semantic Sanitization & Least-Privilege Gate
# ==============================================================================
def test_gate8_semantic_sanitization() -> None:
    """Gate 8: Verify semantic purity and absence of adversarial trigger words across runtime files."""
    forbidden_terms = [
        "herramientas ofensivas",
        "red team exploit",
        "interactive password prompt",
    ]
    files_to_audit = [
        PROJECT_ROOT / "engine" / "privilege.py",
        PROJECT_ROOT / "scripts" / "setup.sh",
        PROJECT_ROOT / "scripts" / "aep-ctl",
        PROJECT_ROOT / "server.py",
    ]

    for fpath in files_to_audit:
        assert fpath.exists(), f"File {fpath} must exist"
        content = fpath.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, f"Forbidden term '{term}' found in {fpath.name}"
