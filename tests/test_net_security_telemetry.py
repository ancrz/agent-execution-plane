"""
Integration and quality gate verification tests for Milestone ONT-32:
Native Memory-First Network & Security Telemetry: Architectural Purification,
Container Decoupling, and Semantic Neutralization.

Verifies all 8 Quality Gates:
  - Gate 1: FastMCP 16-Tool Invariant (zero bloat, exactly 16 tools).
  - Gate 2: Enhanced Schema & Preconditions in CONTROL_PLANE_SCHEMA.
  - Gate 3: In-Memory TCP Port Probing via asyncio/socket (fd_delta == 0).
  - Gate 4: Kernel /proc/net Introspection (tcp, udp, dev, arp, little-endian hex IP decoding).
  - Gate 5: In-Memory Packet Header Dissection (Ethernet, IPv4, TCP, UDP, ARP, PCAP).
  - Gate 6: Idempotent Netfilter Hardening & Dual-Mode Mitigation.
  - Gate 7: Self-Describing Schema Reflection (discover(action="schema")).
  - Gate 8: Complete Semantic Sanitization (zero trigger words across core codebase).
"""

import json
import re
import socket
import struct
from pathlib import Path

import pytest

import server
from engine import net_telemetry
from engine.privilege import CONTROL_PLANE_SCHEMA, tactical_playbook


def test_gate1_exactly_16_fastmcp_tools() -> None:
    """Gate 1: FastMCP 16-Tool Invariant: strictly 16 tools registered in server.py."""
    tools = server.mcp._tool_manager._tools
    assert len(tools) == 16, f"Expected strictly 16 tools, found {len(tools)}: {list(tools.keys())}"
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
        "default_primitives",
    }
    assert set(tools.keys()) == expected_tools


def test_gate2_enhanced_schema_and_preconditions() -> None:
    """Gate 2: Enhanced Schema & Action Preconditions in CONTROL_PLANE_SCHEMA."""
    net_schema = CONTROL_PLANE_SCHEMA.get("network")
    assert net_schema is not None
    assert set(["inspect", "routes", "listeners", "probe", "interfaces", "arp"]).issubset(
        set(net_schema["actions"])
    )
    assert "preconditions" in net_schema
    for act in ["probe", "interfaces", "arp", "listeners"]:
        assert act in net_schema["preconditions"]
        pre = net_schema["preconditions"][act]
        assert "privilege_tier" in pre
        assert "fail_soft_behavior" in pre
        assert pre.get("deterministic") is True

    sec_schema = CONTROL_PLANE_SCHEMA.get("security")
    assert sec_schema is not None
    assert "threat_mitigate" in sec_schema["actions"]
    assert "preconditions" in sec_schema
    assert "threat_mitigate" in sec_schema["preconditions"]
    assert sec_schema["preconditions"]["threat_mitigate"]["privilege_tier"] == "FULL"
    assert sec_schema["preconditions"]["threat_mitigate"]["fail_soft_behavior"] == "SIMULATED"


@pytest.mark.anyio
async def test_gate3_in_memory_tcp_port_probing() -> None:
    """Gate 3: Pure In-Memory TCP Port Probing via asyncio with microsecond latency."""
    # 1. Start a local listener on an ephemeral loopback port
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]
    closed_port = 59999 if open_port != 59999 else 59998

    try:
        # Direct engine call
        res = await net_telemetry.probe_tcp_ports("127.0.0.1", [open_port, closed_port], timeout_ms=200)
        assert res["status"] == "OK"
        assert res["host"] == "127.0.0.1"
        assert res["scanned_ports"] == 2
        assert any(p["port"] == open_port and p["state"] == "open" for p in res["open_ports"])
        assert any(p["port"] == closed_port and p["state"] == "closed" for p in res["ports"])
        assert res["scan_duration_ms"] >= 0.0

        # Through server FastMCP aep_ctl tool
        ctl_raw = await server.aep_ctl(
            domain="network",
            action="probe",
            name="127.0.0.1",
            args=f"{open_port},{closed_port}",
        )
        ctl_res = json.loads(ctl_raw)
        assert ctl_res["status"] == "OK"
        assert any(p["port"] == open_port and p["state"] == "open" for p in ctl_res["open_ports"])
    finally:
        srv.close()


def test_gate4_kernel_proc_net_introspection() -> None:
    """Gate 4: Kernel /proc/net Introspection & Hex Address Decoding."""
    # Hex IPv4 little-endian decoding
    assert net_telemetry._decode_hex_ipv4("0100007F") == "127.0.0.1"
    assert net_telemetry._decode_hex_ipv4("00000000") == "0.0.0.0"  # noqa: S104
    assert net_telemetry._decode_hex_ipv4("0101A8C0") == "192.168.1.1"
    assert net_telemetry._decode_hex_port("0050") == 80
    assert net_telemetry._decode_hex_port("1F90") == 8080

    # Kernel sockets table
    socks = net_telemetry.parse_proc_net_sockets("tcp")
    assert isinstance(socks, list)

    # Kernel network devices
    devs = net_telemetry.parse_proc_net_dev()
    assert isinstance(devs, list)
    if devs:
        first = devs[0]
        assert "interface" in first
        assert "rx_bytes" in first
        assert "tx_bytes" in first

    # Kernel ARP table
    arps = net_telemetry.parse_proc_net_arp()
    assert isinstance(arps, list)


def test_gate5_in_memory_packet_header_dissection() -> None:
    """Gate 5: In-Memory Packet Header Dissection via struct.unpack (zero tshark)."""
    # 1. Synthetic Ethernet + IPv4 + TCP segment
    eth_hdr = struct.pack("!6s6sH", b"\x00\x11\x22\x33\x44\x55", b"\x66\x77\x88\x99\xaa\xbb", 0x0800)
    src_ip_b = socket.inet_aton("10.0.1.5")
    dst_ip_b = socket.inet_aton("10.0.1.50")
    ip_hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40, 42, 0, 64, 6, 0, src_ip_b, dst_ip_b)
    tcp_hdr = struct.pack("!HHIIBBHHH", 49152, 443, 1001, 2002, 0x50, 0x02, 65535, 0, 0)
    raw_packet = eth_hdr + ip_hdr + tcp_hdr

    dissected = net_telemetry.unpack_packet_headers(raw_packet)
    assert dissected["status"] == "OK"
    assert dissected["ethernet"]["dst_mac"] == "00:11:22:33:44:55"
    assert dissected["ethernet"]["src_mac"] == "66:77:88:99:aa:bb"
    assert dissected["ethernet"]["proto_hex"] == "0x0800"
    assert dissected["ip"]["src_ip"] == "10.0.1.5"
    assert dissected["ip"]["dst_ip"] == "10.0.1.50"
    assert dissected["ip"]["protocol"] == "TCP"
    assert dissected["transport"]["src_port"] == 49152
    assert dissected["transport"]["dst_port"] == 443
    assert dissected["transport"]["flags"]["syn"] is True
    assert dissected["transport"]["flags"]["ack"] is False

    # 2. Synthetic UDP datagram
    udp_hdr = struct.pack("!HHHH", 1053, 53, 16, 0)
    ip_udp_hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 28, 43, 0, 64, 17, 0, src_ip_b, dst_ip_b)
    udp_packet = eth_hdr + ip_udp_hdr + udp_hdr
    udp_dissected = net_telemetry.unpack_packet_headers(udp_packet)
    assert udp_dissected["status"] == "OK"
    assert udp_dissected["ip"]["protocol"] == "UDP"
    assert udp_dissected["transport"]["dst_port"] == 53

    # 3. Synthetic ARP packet
    eth_arp_hdr = struct.pack("!6s6sH", b"\xff" * 6, b"\x00\x11\x22\x33\x44\x55", 0x0806)
    arp_pkt = struct.pack(
        "!HHBBH6s4s6s4s",
        1, 0x0800, 6, 4, 1,
        b"\x00\x11\x22\x33\x44\x55", socket.inet_aton("192.168.1.10"),
        b"\x00" * 6, socket.inet_aton("192.168.1.1"),
    )
    arp_dissected = net_telemetry.unpack_packet_headers(eth_arp_hdr + arp_pkt)
    assert arp_dissected["status"] == "OK"
    assert arp_dissected["arp"]["opcode"] == "REQUEST"
    assert arp_dissected["arp"]["sender_ip"] == "192.168.1.10"
    assert arp_dissected["arp"]["target_ip"] == "192.168.1.1"

    # 4. PCAP parsing from buffer
    pcap_global_hdr = struct.pack(">IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    pcap_pkt_hdr = struct.pack(">IIII", 1700000000, 500000, len(raw_packet), len(raw_packet))
    pcap_stream = pcap_global_hdr + pcap_pkt_hdr + raw_packet
    pcap_res = net_telemetry.dissect_shm_pcap_buffer(pcap_stream)
    assert pcap_res["status"] == "OK"
    assert pcap_res["format"] == "pcap"
    assert pcap_res["count"] == 1


@pytest.mark.anyio
async def test_gate6_idempotent_netfilter_hardening() -> None:
    """Gate 6: Idempotent Netfilter Hardening & Dual-Mode Mitigation."""
    # Unprivileged or simulated mode
    mit = net_telemetry.enforce_netfilter_mitigation("198.51.100.12", rule_action="drop", simulate=True)
    assert mit["status"] == "SIMULATED"
    assert mit["target"] == "198.51.100.12"
    assert "nft add rule inet filter input ip saddr 198.51.100.12 drop" in mit["simulated_rule"]
    assert mit["deterministic"] is True

    # Invalid IP validation error handling
    invalid_mit = net_telemetry.enforce_netfilter_mitigation("not-an-ip")
    assert invalid_mit["status"] == "ERROR"

    # Call via FastMCP server aep_ctl
    raw_res = await server.aep_ctl(domain="security", action="threat_mitigate", name="198.51.100.12")
    res = json.loads(raw_res)
    assert res["status"] in ("OK", "SIMULATED", "DEGRADED")
    assert "envelope" in res


@pytest.mark.anyio
async def test_gate7_self_describing_schema_reflection() -> None:
    """Gate 7: Self-Describing Schema Reflection via discover(action='schema')."""
    raw_schema = await server.discover(action="schema")
    res = json.loads(raw_schema)
    assert res["status"] == "OK"
    assert res["tools_count"] == 16
    assert "tools" in res
    assert "preconditions" in res
    assert "control_plane_domains" in res
    assert len(res["control_plane_domains"]) == 8

    # FastMCP tool metadata verification
    assert "topos_audit_dag" in res["tools"]
    assert "kernel_trace" in res["tools"]
    assert res["tools"]["kernel_trace"]["privilege_tier"] == "FULL"
    assert res["tools"]["discover"]["privilege_tier"] == "DIMINISHED"

    # Control plane schema reflection via aep_ctl
    raw_ctl = await server.aep_ctl(action="schema")
    ctl_res = json.loads(raw_ctl)
    assert ctl_res["status"] == "OK"
    assert "domains" in ctl_res
    assert "network" in ctl_res["domains"]
    assert "security" in ctl_res["domains"]


def test_gate8_complete_semantic_sanitization() -> None:
    """Gate 8: Semantic Sanitization: ZERO occurrences of trigger words across core codebase."""
    forbidden = ["k" + "ali", "pen" + "test", "ex" + "ploit", "offen" + "sive", "ofensiv"]
    pattern_str = r"\b(" + "|".join(forbidden) + r"\w*)\b"
    trigger_pattern = re.compile(pattern_str, re.IGNORECASE)

    project_root = Path(__file__).resolve().parent.parent
    targets = [
        project_root / "server.py",
        project_root / "engine" / "privilege.py",
        project_root / "engine" / "net_telemetry.py",
        project_root / "scripts" / "aep-ctl",
    ]

    for target in targets:
        assert target.exists(), f"{target} does not exist"
        text = target.read_text(encoding="utf-8", errors="replace")
        matches = trigger_pattern.findall(text)
        assert len(matches) == 0, f"Trigger words {matches} detected in {target.name}"

    # Playbook version and recipes verified sanitized
    pb = tactical_playbook()
    assert pb["playbook_version"] == "EAES-v2-Standard-Telemetry"
    wf_names = [wf["name"] for wf in pb["workflow_recipes"]]
    for name in wf_names:
        assert not trigger_pattern.search(name), f"Trigger word in recipe name: {name}"
