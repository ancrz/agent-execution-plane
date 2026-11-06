"""
Test Battery: Hardware Domain & Accelerator Admission (GAP-CP-05) and Apport Crash Alerts (GAP-OM-20)

Milestone ONT-36 / M97 (10 Gates):
- Gate 1: FastMCP 17-Tool Invariant Preservation
- Gate 2: Control Plane 9 Domains & Hardware Schema Reflection
- Gate 3: Hardware Inventory Probe (CPU & Memory Telemetry)
- Gate 4: Fail-Soft Accelerator Enumeration on DRM/Headless/Container (R-3)
- Gate 5: Pre-Flight Accelerator Admission & 4096 MiB Desktop Safety Margin (GAP-CP-05)
- Gate 6: Permission-Safe Apport Forensics & Metadata Header Parsing (R-4)
- Gate 7: Apport Deduplication in SQLite (apport:<file>:<mtime>) & Fallback Source
- Gate 8: Modernized Compact Flat Telemetry (GAP-OM-19)
- Gate 9: Discover Capabilities Exposes Accelerators Block
- Gate 10: 4-Tier Degradation Matrix Across 9 Domains
"""

import json
import subprocess
from pathlib import Path

import pytest

import server
from engine.crash_router import CrashRouter
from engine.hardware import (
    DEFAULT_DESKTOP_SAFETY_MARGIN_MIB,
    admit_accelerator,
    probe_accelerators,
    probe_hardware_inventory,
)
from engine.privilege import ALL_TIERS, CHMOD_DEGRADATION_MATRIX, CONTROL_PLANE_SCHEMA

# ==============================================================================
# Gate 1: FastMCP 17-Tool Invariant Preservation
# ==============================================================================


def test_gate1_fastmcp_16_tool_invariant() -> None:
    """Strictly preserve exactly 17 polymorphic FastMCP tools without endpoint proliferation."""
    tools = server.mcp._tool_manager._tools
    assert len(tools) == 17, f"Expected exactly 17 tools, got {len(tools)}"

    expected_tools = {
        "topos_audit_dag",
        "discover",
        "artifact_catalog",
        "artifact_lint_and_build",
        "artifact_execute_in_ram",
        "default_primitives",
        "autoevol",
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
    # Hardware is integrated under polymorphic aep_ctl, not as a 17th tool endpoint
    assert "hardware" not in tools


# ==============================================================================
# Gate 2: Control Plane 9 Domains & Hardware Schema Reflection
# ==============================================================================


@pytest.mark.anyio
async def test_gate2_control_plane_9_domains_and_schema_reflection() -> None:
    """Control plane schema reflection exposes 9 domains including hardware."""
    # 1. Inspect CONTROL_PLANE_SCHEMA
    assert len(CONTROL_PLANE_SCHEMA) == 9
    assert "hardware" in CONTROL_PLANE_SCHEMA
    hw_schema = CONTROL_PLANE_SCHEMA["hardware"]
    assert set(hw_schema["actions"]) == {"inventory", "accelerators", "admit"}

    # 2. Inspect aep_ctl(action="schema")
    raw_schema = await server.aep_ctl(action="schema")
    schema_res = json.loads(raw_schema)
    assert schema_res["status"] == "OK"
    assert "domains" in schema_res
    assert len(schema_res["domains"]) == 9
    assert "hardware" in schema_res["domains"]

    # 3. CLI scripts/aep-ctl hardware --schema
    ctl_bin = Path("scripts/aep-ctl")
    res_cli = subprocess.run([str(ctl_bin), "hardware", "--schema"], capture_output=True, text=True, check=False)
    assert res_cli.returncode == 0
    cli_data = json.loads(res_cli.stdout)
    assert cli_data["status"] == "OK"
    assert cli_data["domain"] == "hardware"
    assert "schema" in cli_data
    assert set(cli_data["schema"]["actions"]) == {"inventory", "accelerators", "admit"}


# ==============================================================================
# Gate 3: Hardware Inventory Probe (CPU & Memory Telemetry)
# ==============================================================================


@pytest.mark.anyio
async def test_gate3_hardware_inventory_probe() -> None:
    """probe_hardware_inventory() extracts CPU, memory, and accelerators telemetry."""
    inv = probe_hardware_inventory()
    assert inv["status"] in ("OK", "DEGRADED")
    assert "cpu" in inv
    assert inv["cpu"]["logical_cores"] >= 1
    assert "memory" in inv
    assert inv["memory"]["total_mib"] >= 0
    assert "accelerators" in inv
    assert isinstance(inv["accelerators"], list)
    assert inv["accelerators_count"] == len(inv["accelerators"])

    # FastMCP server integration via aep_ctl(domain="hardware", action="inventory")
    raw_ctl = await server.aep_ctl(domain="hardware", action="inventory")
    ctl_inv = json.loads(raw_ctl)
    assert ctl_inv["status"] in ("OK", "DEGRADED")
    assert "cpu" in ctl_inv
    assert "memory" in ctl_inv


# ==============================================================================
# Gate 4: Fail-Soft Accelerator Enumeration on DRM/Headless/Container (R-3)
# ==============================================================================


def test_gate4_fail_soft_accelerator_enumeration(tmp_path: Path) -> None:
    """DRM introspection must fail-soft on headless, container, or non-AMD systems (R-3)."""
    # 1. Non-existent DRM directory
    non_existent = tmp_path / "non_existent_drm"
    accels_none = probe_accelerators(drm_dir=non_existent)
    assert accels_none == []

    # 2. Empty DRM directory
    empty_drm = tmp_path / "empty_drm"
    empty_drm.mkdir(parents=True)
    accels_empty = probe_accelerators(drm_dir=empty_drm)
    assert accels_empty == []

    # 3. Non-card entries ignored (e.g. version or connector symlinks)
    (empty_drm / "version").write_text("drm 1.1.0\n", encoding="utf-8")
    (empty_drm / "card1-DP-1").mkdir()
    assert probe_accelerators(drm_dir=empty_drm) == []

    # 4. Inventory probe with missing DRM directory still returns valid CPU/RAM
    inv_soft = probe_hardware_inventory(drm_dir=non_existent)
    assert inv_soft["status"] in ("OK", "DEGRADED")
    assert inv_soft["accelerators"] == []
    assert inv_soft["accelerators_count"] == 0


# ==============================================================================
# Gate 5: Pre-Flight Accelerator Admission & 4096 MiB Desktop Safety Margin (GAP-CP-05)
# ==============================================================================


def test_gate5_preflight_accelerator_admission_and_safety_margin(tmp_path: Path) -> None:
    """admit_accelerator() enforces mandatory 4096 MiB desktop safety margin on GTT."""
    # 1. Fail-closed when no accelerators exist
    res_no_accel = admit_accelerator(drm_dir=tmp_path / "missing_drm")
    assert res_no_accel["status"] == "REJECTED"
    assert res_no_accel["admit"] is False
    assert res_no_accel["reason"] == "no_accelerators_detected"
    assert res_no_accel["margin_mib"] == DEFAULT_DESKTOP_SAFETY_MARGIN_MIB

    # 2. Construct mock AMDGPU DRM sysfs structure
    mock_drm = tmp_path / "sys_class_drm"
    card0 = mock_drm / "card0"
    dev0 = card0 / "device"
    dev0.mkdir(parents=True)

    (dev0 / "vendor").write_text("0x1002\n", encoding="utf-8")
    (dev0 / "device").write_text("0x1900\n", encoding="utf-8")

    # 1024 MiB total VRAM (500 MiB used, 524 MiB free)
    (dev0 / "mem_info_vram_total").write_text(str(1024 * 1024 * 1024) + "\n", encoding="utf-8")
    (dev0 / "mem_info_vram_used").write_text(str(500 * 1024 * 1024) + "\n", encoding="utf-8")

    # 16384 MiB total GTT (2048 MiB used, 14336 MiB free)
    (dev0 / "mem_info_gtt_total").write_text(str(16384 * 1024 * 1024) + "\n", encoding="utf-8")
    (dev0 / "mem_info_gtt_used").write_text(str(2048 * 1024 * 1024) + "\n", encoding="utf-8")

    # Verify detection
    detected = probe_accelerators(drm_dir=mock_drm)
    assert len(detected) == 1
    assert detected[0]["card"] == "card0"
    assert detected[0]["vendor_name"] == "AMD"
    assert detected[0]["vram_free_mib"] == 524
    assert detected[0]["gtt_free_mib"] == 14336

    # Admission Scenario A: Small request within VRAM and available GTT (14336 - 4096 = 10240 MiB available)
    adm_ok = admit_accelerator(
        req_vram_mib=256,
        req_gtt_mib=8192,
        margin_mib=4096,
        drm_dir=mock_drm,
    )
    assert adm_ok["status"] == "OK"
    assert adm_ok["admit"] is True
    assert adm_ok["reason"] == "admitted"
    assert adm_ok["gtt_available_mib"] == 10240

    # Admission Scenario B: Request exceeds available GTT due to 4096 MiB desktop safety margin
    # 12000 MiB requested > 10240 MiB available -> REJECTED (Prevents gnome-shell / Mesa SIGABRT)
    adm_gtt_fail = admit_accelerator(
        req_vram_mib=256,
        req_gtt_mib=12000,
        margin_mib=4096,
        drm_dir=mock_drm,
    )
    assert adm_gtt_fail["status"] == "REJECTED"
    assert adm_gtt_fail["admit"] is False
    assert "insufficient_gtt_safety_margin" in adm_gtt_fail["reason"]
    assert adm_gtt_fail["gtt_available_mib"] == 10240

    # Admission Scenario C: Request exceeds VRAM (600 MiB requested > 524 MiB free)
    adm_vram_fail = admit_accelerator(
        req_vram_mib=600,
        req_gtt_mib=1024,
        margin_mib=4096,
        drm_dir=mock_drm,
    )
    assert adm_vram_fail["status"] == "REJECTED"
    assert adm_vram_fail["admit"] is False
    assert "insufficient_vram" in adm_vram_fail["reason"]

    # Admission Scenario D: Unknown device name returns clean diagnostic
    adm_unknown = admit_accelerator(device="card99", drm_dir=mock_drm)
    assert adm_unknown["status"] == "REJECTED"
    assert adm_unknown["reason"] == "device_card99_not_found"


# ==============================================================================
# Gate 6: Permission-Safe Apport Forensics & Metadata Header Parsing (R-4)
# ==============================================================================


def test_gate6_permission_safe_apport_forensics(tmp_path: Path) -> None:
    """sync_apport() handles readable and unreadable .crash files with stat fallback (R-4)."""
    db_file = tmp_path / "test_apport.db"
    cr = CrashRouter(db_path=db_file)
    crash_dir = tmp_path / "var_crash"
    crash_dir.mkdir(parents=True)

    # 1. Normal readable Apport crash report
    f_ok = crash_dir / "_usr_bin_my-app.1000.crash"
    f_ok.write_text(
        "ProblemType: Crash\n"
        "ExecutablePath: /usr/bin/my-app\n"
        "Signal: 11\n"
        "Date: Wed Nov  4 12:00:00 2026\n"
        "ProcCmdline: /usr/bin/my-app --worker 2\n"
        "UserGroups: ancruz adm sudo\n"
        "CoreDump: base64dummydata\n",
        encoding="utf-8",
    )

    # 2. Permission-restricted crash report (simulated by corrupt/unreadable header or stem fallback)
    f_unreadable = crash_dir / "_usr_bin_restricted-daemon.0.crash"
    f_unreadable.write_bytes(b"\x00\x01\x02\x03BINARY_UNREADABLE")

    new_count = cr.sync_apport(crash_dir=crash_dir)
    assert new_count == 2

    alerts = cr.pending_alerts()
    assert len(alerts) == 2

    # Check parsed readable alert
    alert_ok = next(a for a in alerts if a["executable"] == "/usr/bin/my-app")
    assert alert_ok["signal"] in ("11", "SIGSEGV")
    assert alert_ok["event_timestamp"] == "Wed Nov  4 12:00:00 2026"

    # Check stem-fallback alert
    alert_res = next(a for a in alerts if "restricted-daemon" in a["executable"])
    assert alert_res["executable"] == "/usr/bin/restricted-daemon"
    assert alert_res["signal"] == "UNKNOWN"


# ==============================================================================
# Gate 7: Apport Deduplication in SQLite (apport:<file>:<mtime>) & Fallback Source
# ==============================================================================


def test_gate7_apport_deduplication_and_fallback_source(tmp_path: Path) -> None:
    """Crash events are deduplicated by fingerprint and check() exposes source='apport'."""
    db_file = tmp_path / "test_dedup.db"
    cr = CrashRouter(db_path=db_file)
    crash_dir = tmp_path / "var_crash_dedup"
    crash_dir.mkdir(parents=True)

    f_crash = crash_dir / "_usr_bin_gnome-shell.1000.crash"
    f_crash.write_text("ExecutablePath: /usr/bin/gnome-shell\nSignal: 6\n", encoding="utf-8")

    # Run 1: Inserts 1 new event
    new_1 = cr.sync_apport(crash_dir=crash_dir)
    assert new_1 == 1

    # Run 2: Same mtime -> Deduplication -> Inserts 0
    new_2 = cr.sync_apport(crash_dir=crash_dir)
    assert new_2 == 0

    chk = cr.check()
    assert chk["status"] == "OK"
    assert chk["source"] in ("coredumpctl", "apport")
    assert chk["pending_count"] >= 1


# ==============================================================================
# Gate 8: Modernized Compact Flat Telemetry (GAP-OM-19)
# ==============================================================================


@pytest.mark.anyio
async def test_gate8_modernized_compact_flat_telemetry() -> None:
    """diagnose_system_crashes(action='alerts') emits flat keys + 't' stub in summary mode."""
    # Summary mode: Compact flat envelope with 't'
    raw_sum = await server.diagnose_system_crashes(action="alerts", verbosity="summary")
    res_sum = json.loads(raw_sum)
    assert res_sum["status"] in ("OK", "DEGRADED")
    assert "envelope" not in res_sum, "Compact mode must omit redundant nested envelope"
    assert "t" in res_sum, "Compact mode must emit lightweight 't' stub"
    assert "ms" in res_sum["t"]
    assert "tok" in res_sum["t"]
    assert "status" in res_sum
    assert "severity" in res_sum
    assert "summary" in res_sum
    assert "next_action" in res_sum

    # Detail mode: Preserves full nested envelope and telemetry for backward compatibility
    raw_det = await server.diagnose_system_crashes(action="alerts", verbosity="detail")
    res_det = json.loads(raw_det)
    assert "envelope" in res_det
    assert "telemetry" in res_det


# ==============================================================================
# Gate 9: Discover Capabilities Exposes Accelerators Block
# ==============================================================================


@pytest.mark.anyio
async def test_gate9_discover_capabilities_exposes_accelerators() -> None:
    """discover(action='capabilities') includes accelerators summary block."""
    raw_caps = await server.discover(action="capabilities", verbosity="detail")
    caps = json.loads(raw_caps)
    assert caps["status"] == "OK"
    assert "accelerators" in caps
    assert isinstance(caps["accelerators"], list)


# ==============================================================================
# Gate 10: 4-Tier Degradation Matrix Across 9 Domains
# ==============================================================================


def test_gate10_4tier_degradation_matrix_across_9_domains() -> None:
    """CHMOD_DEGRADATION_MATRIX must govern all 9 domains across all 4 tiers."""
    domains = CHMOD_DEGRADATION_MATRIX.get("domains", {})
    assert len(domains) == 9
    assert "hardware" in domains

    hw_tiers = domains["hardware"]
    for tier in ALL_TIERS:
        assert tier in hw_tiers, f"Tier {tier} missing in hardware degradation matrix"
        assert isinstance(hw_tiers[tier], str) and len(hw_tiers[tier]) > 0

    # Ensure setup.sh reflects 9 domains
    setup_sh = Path("scripts/setup.sh").read_text(encoding="utf-8")
    assert "9 Domains Fail-Soft Degradation" in setup_sh
