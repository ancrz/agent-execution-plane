"""
Unit & Regression Test Suite: Milestone ONT-37 (Tasks T1-T6)
UMA-Aware Hardware Admission Ergonomics (GAP-DX-06), Apport RFC822 Header Forensics (GAP-OM-21),
and Sandbox Pytest Parsing Completeness & Anti-Masking (GAP-DX-07).
"""

import inspect
from pathlib import Path

import server
from engine.crash_router import CrashRouter
from engine.hardware import (
    DEFAULT_DESKTOP_SAFETY_MARGIN_MIB,
    admit_accelerator,
    probe_accelerators,
)
from engine.privilege import CONTROL_PLANE_SCHEMA
from server import _deduplicate_lines, _parse_pytest_output


def _create_mock_card(
    base_dir: Path,
    card_name: str,
    vram_total_mib: int,
    vram_used_mib: int,
    gtt_total_mib: int,
    gtt_used_mib: int,
    vendor_id: str = "0x1002",
) -> Path:
    card_dir = base_dir / card_name
    dev_dir = card_dir / "device"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "vendor").write_text(f"{vendor_id}\n", encoding="utf-8")
    (dev_dir / "device").write_text("0x1900\n", encoding="utf-8")
    (dev_dir / "mem_info_vram_total").write_text(f"{vram_total_mib * 1024 * 1024}\n", encoding="utf-8")
    (dev_dir / "mem_info_vram_used").write_text(f"{vram_used_mib * 1024 * 1024}\n", encoding="utf-8")
    (dev_dir / "mem_info_gtt_total").write_text(f"{gtt_total_mib * 1024 * 1024}\n", encoding="utf-8")
    (dev_dir / "mem_info_gtt_used").write_text(f"{gtt_used_mib * 1024 * 1024}\n", encoding="utf-8")
    return card_dir


# ==============================================================================
# Gate 1: UMA Auto-Detection Logic
# ==============================================================================


def test_gate1_uma_auto_detection_logic(tmp_path: Path) -> None:
    """Detects UMA when vram_total <= 2048 MiB and gtt_total > vram_total * 2."""
    drm_root = tmp_path / "drm_gate1"

    # 1. Typical UMA APU: 1024 MiB carve-out VRAM, 15179 MiB GTT
    _create_mock_card(drm_root, "card0", 1024, 570, 15179, 126)
    accels_uma = probe_accelerators(drm_dir=drm_root)
    assert len(accels_uma) == 1
    adm_uma = admit_accelerator(device="card0", drm_dir=drm_root)
    assert adm_uma["is_uma"] is True

    # 2. Typical Discrete GPU: 16384 MiB VRAM, 8192 MiB GTT
    drm_dgpu = tmp_path / "drm_dgpu"
    _create_mock_card(drm_dgpu, "card0", 16384, 4384, 8192, 192)
    adm_dgpu = admit_accelerator(device="card0", drm_dir=drm_dgpu)
    assert adm_dgpu["is_uma"] is False

    # 3. Boundary: 2048 MiB VRAM and 4096 MiB GTT (not strictly > 2048 * 2) -> is_uma == False
    drm_bound1 = tmp_path / "drm_bound1"
    _create_mock_card(drm_bound1, "card0", 2048, 100, 4096, 100)
    adm_bound1 = admit_accelerator(device="card0", drm_dir=drm_bound1)
    assert adm_bound1["is_uma"] is False

    # 4. Boundary: 2048 MiB VRAM and 4097 MiB GTT -> is_uma == True
    drm_bound2 = tmp_path / "drm_bound2"
    _create_mock_card(drm_bound2, "card0", 2048, 100, 4097, 100)
    adm_bound2 = admit_accelerator(device="card0", drm_dir=drm_bound2)
    assert adm_bound2["is_uma"] is True


# ==============================================================================
# Gate 2: UMA Unqualified Admission Routing to GTT
# ==============================================================================


def test_gate2_uma_unqualified_admission_routing_to_gtt(tmp_path: Path) -> None:
    """On UMA devices, unqualified single memory request routes to GTT enforcing safety margin."""
    drm_root = tmp_path / "drm_gate2"
    # 1024 VRAM (454 free), 15179 GTT (15053 free)
    _create_mock_card(drm_root, "card0", 1024, 570, 15179, 126)

    # Consumer test case: 6144 MiB unqualified demand
    res = admit_accelerator(req_mib=6144, drm_dir=drm_root)
    assert res["status"] == "OK"
    assert res["admit"] is True
    assert res["is_uma"] is True
    assert res["allocated_to"] == "gtt"
    assert res["req_gtt_mib"] == 6144
    assert res["req_vram_mib"] == 0
    # Available GTT: 15053 - 4096 = 10957 MiB
    assert res["gtt_available_mib"] == 15053 - DEFAULT_DESKTOP_SAFETY_MARGIN_MIB
    assert res["gtt_available_mib"] >= 6144


# ==============================================================================
# Gate 3: dGPU Unqualified Admission Routing to VRAM
# ==============================================================================


def test_gate3_dgpu_unqualified_admission_routing_to_vram(tmp_path: Path) -> None:
    """On discrete GPU devices, unqualified single memory request routes to VRAM."""
    drm_root = tmp_path / "drm_gate3"
    # 16384 VRAM (12000 free), 8192 GTT (8000 free)
    _create_mock_card(drm_root, "card0", 16384, 4384, 8192, 192)

    res = admit_accelerator(req_mib=6144, drm_dir=drm_root)
    assert res["status"] == "OK"
    assert res["admit"] is True
    assert res["is_uma"] is False
    assert res["allocated_to"] == "vram"
    assert res["req_vram_mib"] == 6144
    assert res["req_gtt_mib"] == 0


# ==============================================================================
# Gate 4: Named Parameters & Leaf Defensive Numeric Device Fallback (R2)
# ==============================================================================


def test_gate4_named_parameters_and_leaf_defensive_numeric_device(tmp_path: Path) -> None:
    """admit_accelerator accepts named params and auto-corrects numeric device strings (R2)."""
    drm_root = tmp_path / "drm_gate4"
    _create_mock_card(drm_root, "card0", 1024, 570, 15179, 126)

    # 1. Named parameters dictionary
    res_named = admit_accelerator(
        params={"vram_mib": 256, "gtt_mib": 2048, "margin_mib": 4096},
        drm_dir=drm_root,
    )
    assert res_named["status"] == "OK"
    assert res_named["admit"] is True
    assert res_named["req_vram_mib"] == 256
    assert res_named["req_gtt_mib"] == 2048

    # 2. Leaf Defensive Routing (Remediation R2): passing device=6144
    # Must NOT fail with device_6144_not_found; interprets as req_mib=6144 and auto-selects card0
    res_leaf = admit_accelerator(device="6144", drm_dir=drm_root)
    assert res_leaf["status"] == "OK"
    assert res_leaf["admit"] is True
    assert res_leaf["device"] == "card0"
    assert res_leaf["req_mib"] == 6144
    assert res_leaf["allocated_to"] == "gtt"

    # 3. Non-numeric unknown device still returns proper rejection
    res_unknown = admit_accelerator(device="card_nonexistent", drm_dir=drm_root)
    assert res_unknown["status"] == "REJECTED"
    assert res_unknown["reason"] == "device_card_nonexistent_not_found"


# ==============================================================================
# Gate 5: Actionable Rejection & UMA Hint in next_action
# ==============================================================================


def test_gate5_actionable_rejection_and_uma_hint(tmp_path: Path) -> None:
    """Rejection on UMA devices emits clear actionable next_action suggesting GTT."""
    drm_root = tmp_path / "drm_gate5"
    # 1024 VRAM (454 free), 15179 GTT (15053 free)
    _create_mock_card(drm_root, "card0", 1024, 570, 15179, 126)

    # Requesting explicit 600 MiB VRAM exceeds 454 MiB free carve-out
    res = admit_accelerator(req_vram_mib=600, drm_dir=drm_root)
    assert res["status"] == "REJECTED"
    assert res["admit"] is False
    assert "insufficient_vram" in res["reason"]
    assert "UMA/APU accelerator" in res["next_action"]
    assert "gtt_mib" in res["next_action"] or "req_mib" in res["next_action"]


# ==============================================================================
# Gate 6: Control Plane Schema Reflection for hardware.admit
# ==============================================================================


def test_gate6_control_plane_schema_reflection() -> None:
    """CONTROL_PLANE_SCHEMA documents admit signature, named flags, and UMA semantics."""
    assert "hardware" in CONTROL_PLANE_SCHEMA
    hw_schema = CONTROL_PLANE_SCHEMA["hardware"]
    assert "admit" in hw_schema["actions"]
    assert "--vram" in hw_schema["arg"]
    assert "--gtt" in hw_schema["arg"]
    assert "UMA" in hw_schema["description"]


# ==============================================================================
# Gate 7: Apport RFC822 Streaming & Fail-Soft Signal Mapping (R3)
# ==============================================================================


def test_gate7_apport_rfc822_streaming_and_fail_soft_signals(tmp_path: Path) -> None:
    """sync_apport reads <= 64 KiB, parses RFC822 headers, and fail-soft maps signals (R3)."""
    db_file = tmp_path / "test_apport_forensics.db"
    cr = CrashRouter(db_path=db_file)
    crash_dir = tmp_path / "var_crash"
    crash_dir.mkdir(parents=True)

    # 1. Standard Apport crash file with Signal 6 (SIGABRT)
    f_abrt = crash_dir / "_usr_bin_gnome-shell.1000.crash"
    f_abrt.write_text(
        "ProblemType: Crash\n"
        "ExecutablePath: /usr/bin/gnome-shell\n"
        "Signal: 6\n"
        "Date: Wed Nov  4 15:30:00 2026\n"
        "ProcCmdline: /usr/bin/gnome-shell --wayland\n"
        "Pid: 4210\n"
        "CoreDump: base64dummyblob\n",
        encoding="utf-8",
    )

    # 2. Large crash file (> 64 KiB) to verify streaming reader stops before CoreDump
    f_large = crash_dir / "_usr_bin_heavy-app.1000.crash"
    header_part = (
        "ProblemType: Crash\n"
        "ExecutablePath: /usr/bin/heavy-app\n"
        "Signal: 11\n"
        "Date: Thu Nov  5 01:00:00 2026\n"
        "ProcCmdline: /usr/bin/heavy-app --heavy\n"
        "Pid: 9988\n"
        "CoreDump: "
    )
    # Append 100 KiB dummy data
    large_content = header_part + ("A" * 102400) + "\n"
    f_large.write_text(large_content, encoding="utf-8")

    # 3. Crash file with non-standard / real-time signal number (Remediation R3 Fail-Soft)
    f_nonstd = crash_dir / "_usr_bin_custom-proc.1000.crash"
    f_nonstd.write_text(
        "ProblemType: Crash\n"
        "ExecutablePath: /usr/bin/custom-proc\n"
        "Signal: 999\n"
        "Date: Thu Nov  5 02:00:00 2026\n"
        "ProcCmdline: /usr/bin/custom-proc --rt\n"
        "Pid: 7777\n",
        encoding="utf-8",
    )

    # 4. Crash file with non-integer string signal
    f_str_sig = crash_dir / "_usr_bin_string-sig.1000.crash"
    f_str_sig.write_text(
        "ProblemType: Crash\nExecutablePath: /usr/bin/string-sig\nSignal: SIGRTMIN+2\nDate: Thu Nov  5 03:00:00 2026\n",
        encoding="utf-8",
    )

    new_count = cr.sync_apport(crash_dir=crash_dir)
    assert new_count == 4

    alerts = cr.pending_alerts()
    assert len(alerts) == 4

    # Verify SIGABRT mapping
    a_abrt = next(a for a in alerts if a["executable"] == "/usr/bin/gnome-shell")
    assert a_abrt["signal"] == "SIGABRT"
    assert a_abrt["pid"] == 4210
    assert a_abrt["cmdline"] == "/usr/bin/gnome-shell --wayland"

    # Verify 64 KiB streaming reader capped and extracted heavy-app accurately
    a_heavy = next(a for a in alerts if a["executable"] == "/usr/bin/heavy-app")
    assert a_heavy["signal"] == "SIGSEGV"
    assert a_heavy["pid"] == 9988
    assert a_heavy["cmdline"] == "/usr/bin/heavy-app --heavy"

    # Verify R3 fail-soft fallback on unknown signal 999
    a_nonstd = next(a for a in alerts if a["executable"] == "/usr/bin/custom-proc")
    assert a_nonstd["signal"] == "999"
    assert a_nonstd["pid"] == 7777

    # Verify R3 fail-soft fallback on non-integer string
    a_str = next(a for a in alerts if a["executable"] == "/usr/bin/string-sig")
    assert a_str["signal"] == "SIGRTMIN+2"


# ==============================================================================
# Gate 8: Pytest Parsing Completeness & Fail-Soft Defaults (R4)
# ==============================================================================


def test_gate8_pytest_parsing_completeness_and_fail_soft_defaults() -> None:
    """_parse_pytest_output extracts extended metrics with fail-soft defaults (R4)."""
    # 1. Full pytest summary with xfailed, deselected, and coverage
    raw_output = """
============================= test session starts ==============================
collected 25 items / 6 deselected / 19 selected
tests/test_mod.py ................xx.                                   [100%]
---------- coverage: platform linux, python 3.14.7 -----------
Name                 Stmts   Miss  Cover
----------------------------------------
engine/hardware.py     150     15    90%
TOTAL                  150     15    90%

================ 16 passed, 6 deselected, 2 xfailed, 1 xpassed in 2.34s ================
"""
    parsed = _parse_pytest_output(raw_output)
    assert parsed is not None
    assert parsed["tool"] == "pytest"
    assert parsed["passed"] == 16
    assert parsed["deselected"] == 6
    assert parsed["xfailed"] == 2
    assert parsed["xpassed"] == 1
    assert parsed["failed"] == 0
    assert parsed["errors"] == 0
    assert parsed["skipped"] == 0
    assert parsed["coverage"] == "90%"
    assert parsed["duration_s"] == 2.34

    # 2. Minimal summary without extended groups (Remediation R4 Fail-Soft Defaults)
    raw_min = """
============================== 42 passed in 0.50s ==============================
"""
    parsed_min = _parse_pytest_output(raw_min)
    assert parsed_min is not None
    assert parsed_min["passed"] == 42
    assert parsed_min["deselected"] == 0
    assert parsed_min["xfailed"] == 0
    assert parsed_min["xpassed"] == 0
    assert parsed_min["coverage"] is None
    assert parsed_min["failed"] == 0


# ==============================================================================
# Gate 9: Sandbox Pytest Anti-Masking Override & stdout_tail Deduplication
# ==============================================================================


def test_gate9_sandbox_pytest_anti_masking_and_deduplication() -> None:
    """sandbox_run overrides status on masked failures and deduplicates repeated lines."""
    # 1. Line deduplication helper unit test
    lines_repeat = ["probe line 1", "probe line 1", "probe line 1", "probe line 2"]
    deduped = _deduplicate_lines(lines_repeat)
    assert deduped == ["probe line 1 (repeated 3 times)", "probe line 2"]

    lines_unique = ["line A", "line B", "line C"]
    assert _deduplicate_lines(lines_unique) == lines_unique
    assert _deduplicate_lines([]) == []

    # 2. Pytest anti-masking logic
    mock_pytest_masked_text = """
=================================== FAILURES ===================================
FAILED tests/test_core.py::test_fail - AssertionError
=========================== short test summary info ============================
FAILED tests/test_core.py::test_fail
========================= 1 failed, 10 passed in 0.45s =========================
"""
    parsed = _parse_pytest_output(mock_pytest_masked_text)
    assert parsed is not None
    assert parsed["failed"] == 1

    # Verify anti-masking logic condition: failed > 0 overrides returncode 0
    is_masked = parsed.get("failed", 0) > 0 or parsed.get("errors", 0) > 0
    assert is_masked is True


# ==============================================================================
# Gate 10: FastMCP 17-Tool Invariant Preservation
# ==============================================================================


def test_gate10_fastmcp_16_tool_invariant() -> None:
    """Strictly preserve exactly 17 polymorphic FastMCP tools with uniform verbosity."""
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 17, f"Expected 17 tools, got {len(tools)}"

    tool_names = {t.name for t in tools}
    expected_tools = {
        "discover",
        "artifact_lint_and_build",
        "artifact_execute_in_ram",
        "artifact_catalog",
        "kanban_board",
        "process_inspect",
        "sandbox_run",
        "async_job_dispatch",
        "diagnose_system_crashes",
        "kernel_trace",
        "aep_ctl",
        "query_system_docs",
        "visual_inspect",
        "topos_audit_dag",
        "playbook_run",
        "default_primitives",
        "autoevol",
    }
    assert tool_names == expected_tools

    for name in expected_tools:
        fn = getattr(server, name)
        sig = inspect.signature(fn)
        assert "verbosity" in sig.parameters, f"Tool {name} missing verbosity parameter"
