"""
Engine: net_telemetry.py — Native in-memory network & security telemetry.

Pure Python stdlib implementation (asyncio, socket, struct, ipaddress, time, pathlib).
Zero external binary dependencies (no nmap, no tshark, no docker).
"""

import asyncio
import ipaddress
import logging
import os
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.net_telemetry")

# Common TCP services mapping for standard network telemetry
COMMON_TCP_SERVICES: dict[int, str] = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    445: "SMB",
    993: "IMAPS",
    995: "POP3S",
    1433: "MSSQL",
    1521: "Oracle",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    6379: "Redis",
    8000: "HTTP-Alt",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt",
    9000: "SonarQube/PHP",
    9090: "Prometheus",
    9200: "Elasticsearch",
    27017: "MongoDB",
}

TCP_STATE_MAP: dict[str, str] = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
    "0C": "NEW_SYN_RECV",
}


async def probe_tcp_ports(
    host: str = "127.0.0.1",
    ports: list[int] | None = None,
    timeout_ms: int = 300,
    concurrency: int = 50,
) -> dict[str, Any]:
    """
    Asynchronous TCP port prober executing purely in memory via asyncio.
    Strictly closes writers in try...finally to ensure zero file descriptor leaks (fd_delta == 0).
    """
    target_host = host.strip() if host and host.strip() else "127.0.0.1"
    effective_ports = ports or [
        21,
        22,
        23,
        25,
        53,
        80,
        110,
        143,
        443,
        445,
        993,
        995,
        1433,
        1521,
        3306,
        3389,
        5432,
        6379,
        8000,
        8080,
        8443,
        9000,
        9090,
        9200,
        27017,
    ]
    clamped_timeout_ms = max(20, min(int(timeout_ms or 300), 5000))
    timeout_sec = clamped_timeout_ms / 1000.0
    clamped_concurrency = max(1, min(int(concurrency or 50), 200))
    sem = asyncio.Semaphore(clamped_concurrency)

    async def _probe_single(port: int) -> dict[str, Any]:
        async with sem:
            t0 = time.perf_counter()
            writer = None
            try:
                conn_coro = asyncio.open_connection(target_host, port)
                reader, writer = await asyncio.wait_for(conn_coro, timeout=timeout_sec)
                lat_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "port": port,
                    "state": "open",
                    "service": COMMON_TCP_SERVICES.get(port, "unknown"),
                    "latency_ms": round(lat_ms, 2),
                }
            except TimeoutError:
                return {
                    "port": port,
                    "state": "closed",
                    "reason": "timeout",
                    "service": COMMON_TCP_SERVICES.get(port, "unknown"),
                }
            except ConnectionRefusedError, OSError:
                return {
                    "port": port,
                    "state": "closed",
                    "reason": "refused",
                    "service": COMMON_TCP_SERVICES.get(port, "unknown"),
                }
            except (RuntimeError, ValueError) as e:
                return {
                    "port": port,
                    "state": "closed",
                    "reason": str(e),
                    "service": COMMON_TCP_SERVICES.get(port, "unknown"),
                }
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except OSError:
                        pass

    t_start = time.perf_counter()
    results = await asyncio.gather(*(_probe_single(p) for p in effective_ports))
    total_ms = (time.perf_counter() - t_start) * 1000.0

    open_ports = [r for r in results if r.get("state") == "open"]
    closed_ports = [r for r in results if r.get("state") != "open"]

    return {
        "status": "OK",
        "host": target_host,
        "scanned_ports": len(effective_ports),
        "open_ports": open_ports,
        "open_count": len(open_ports),
        "closed_count": len(closed_ports),
        "scan_duration_ms": round(total_ms, 2),
        "ports": results,
    }


def compact_probe_result(result: dict[str, Any]) -> dict[str, Any]:
    """
    ONT-47 T4: compact view of a probe_tcp_ports result. `ports` keeps only the open rows and the closed rows are
    folded into `closed_by_reason` ({timeout: n, refused: n, ...}). Counters and `open_ports` are unchanged.
    """
    compact = dict(result)
    rows = result.get("ports") or []
    closed_by_reason: dict[str, int] = {}
    for row in rows:
        if row.get("state") != "open":
            reason = str(row.get("reason") or "closed")
            closed_by_reason[reason] = closed_by_reason.get(reason, 0) + 1
    compact["ports"] = [row for row in rows if row.get("state") == "open"]
    compact["closed_by_reason"] = closed_by_reason
    return compact


def _decode_hex_ipv4(hex_str: str) -> str:
    """Decode Linux /proc/net little-endian hex IPv4 string to dotted-decimal notation."""
    try:
        val = int(hex_str, 16)
        return socket.inet_ntoa(struct.pack("<L", val))
    except ValueError, struct.error, OSError:
        return hex_str


def _decode_hex_ipv6(hex_str: str) -> str:
    """Decode Linux /proc/net hex IPv6 string (32 hex digits = 4 little-endian 32-bit words)."""
    if len(hex_str) != 32:
        return hex_str
    try:
        words = [int(hex_str[i : i + 8], 16) for i in range(0, 32, 8)]
        packed = b"".join(struct.pack("<I", w) for w in words)
        return socket.inet_ntop(socket.AF_INET6, packed)
    except ValueError, struct.error, OSError:
        return hex_str


def _decode_hex_port(hex_str: str) -> int:
    """Decode hex port to integer."""
    try:
        return int(hex_str, 16)
    except ValueError:
        return 0


_SOCKET_LINK_PREFIX = "socket:["


def map_socket_inodes(inodes: set[int]) -> dict[int, tuple[int, str]]:
    """
    Map socket inodes to (pid, comm) by a single bounded pass over /proc/[0-9]*/fd (ONT-47 T3).

    Deterministic for a given /proc view (PIDs visited in ascending order; the lowest PID owning an inode wins).
    Processes that vanish or deny access (PermissionError, FileNotFoundError, ProcessLookupError) are skipped,
    so unprivileged callers only see their own processes. Stops early once every requested inode is resolved.
    """
    wanted = set(inodes)
    found: dict[int, tuple[int, str]] = {}
    if not wanted:
        return found
    try:
        pids = sorted(int(name) for name in os.listdir("/proc") if name.isdigit())
    except OSError:
        return found
    for pid in pids:
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:  # PermissionError / FileNotFoundError / ProcessLookupError are OSError subclasses
            continue
        comm: str | None = None
        for fd in fds:
            try:
                target = os.readlink(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if not target.startswith(_SOCKET_LINK_PREFIX) or not target.endswith("]"):
                continue
            try:
                ino = int(target[len(_SOCKET_LINK_PREFIX) : -1])
            except ValueError:
                continue
            if ino not in wanted or ino in found:
                continue
            if comm is None:
                try:
                    with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as fh:
                        comm = fh.read().strip()
                except OSError:
                    comm = ""
            found[ino] = (pid, comm)
        if len(found) == len(wanted):
            break
    return found


def parse_proc_net_sockets(protocol: str = "tcp", *, resolve_pids: bool = False) -> list[dict[str, Any]]:
    """
    Parse Linux kernel /proc/net/{tcp,tcp6,udp,udp6} tables directly in memory.
    Decodes little-endian hex IPv4/IPv6 addresses, hex ports, and kernel socket states.
    With resolve_pids=True each row also gets `pid` and `process` (None when the owner cannot be resolved).
    """
    proto_norm = (protocol or "tcp").strip().lower()
    targets: list[tuple[str, str, bool]] = []
    if proto_norm in ("tcp", "all"):
        targets.append(("/proc/net/tcp", "TCP", False))
        targets.append(("/proc/net/tcp6", "TCP6", True))
    elif proto_norm == "tcp6":
        targets.append(("/proc/net/tcp6", "TCP6", True))
    if proto_norm in ("udp", "all"):
        targets.append(("/proc/net/udp", "UDP", False))
        targets.append(("/proc/net/udp6", "UDP6", True))
    elif proto_norm == "udp6":
        targets.append(("/proc/net/udp6", "UDP6", True))

    sockets: list[dict[str, Any]] = []
    for filepath, proto_label, is_ipv6 in targets:
        path = Path(filepath)
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Failed reading %s: %s", filepath, e)
            continue

        lines = content.splitlines()
        if len(lines) <= 1:
            continue

        # Skip header: sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode
        for ln in lines[1:]:
            parts = ln.split()
            if len(parts) < 10:
                continue
            local_raw = parts[1]
            rem_raw = parts[2]
            st_raw = parts[3]
            uid_raw = parts[7]
            inode_raw = parts[9]

            if ":" not in local_raw or ":" not in rem_raw:
                continue

            loc_ip_hex, loc_port_hex = local_raw.split(":", 1)
            rem_ip_hex, rem_port_hex = rem_raw.split(":", 1)

            loc_ip = _decode_hex_ipv6(loc_ip_hex) if is_ipv6 else _decode_hex_ipv4(loc_ip_hex)
            rem_ip = _decode_hex_ipv6(rem_ip_hex) if is_ipv6 else _decode_hex_ipv4(rem_ip_hex)
            loc_port = _decode_hex_port(loc_port_hex)
            rem_port = _decode_hex_port(rem_port_hex)

            state_str = TCP_STATE_MAP.get(st_raw.upper(), st_raw)
            try:
                uid = int(uid_raw)
            except ValueError:
                uid = None
            try:
                inode = int(inode_raw)
            except ValueError:
                inode = None

            sockets.append(
                {
                    "proto": proto_label,
                    "local_ip": loc_ip,
                    "local_port": loc_port,
                    "local": f"{loc_ip}:{loc_port}",
                    "remote_ip": rem_ip,
                    "remote_port": rem_port,
                    "remote": f"{rem_ip}:{rem_port}",
                    "state": state_str,
                    "state_hex": st_raw,
                    "uid": uid,
                    "inode": inode,
                }
            )
    if resolve_pids:
        owners = map_socket_inodes({s["inode"] for s in sockets if s.get("inode")})
        for sock in sockets:
            owner = owners.get(sock.get("inode") or 0)
            sock["pid"] = owner[0] if owner else None
            sock["process"] = (owner[1] or None) if owner else None
    return sockets


def parse_proc_net_dev() -> list[dict[str, Any]]:
    """
    Parse Linux kernel /proc/net/dev to obtain real-time network interface statistics.
    """
    path = Path("/proc/net/dev")
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Failed reading /proc/net/dev: %s", e)
        return []

    lines = content.splitlines()
    if len(lines) <= 2:
        return []

    interfaces: list[dict[str, Any]] = []
    for ln in lines[2:]:
        if ":" not in ln:
            continue
        iface_part, stats_part = ln.split(":", 1)
        iface = iface_part.strip()
        nums = stats_part.split()
        if len(nums) < 16:
            continue
        try:
            interfaces.append(
                {
                    "interface": iface,
                    "rx_bytes": int(nums[0]),
                    "rx_packets": int(nums[1]),
                    "rx_errs": int(nums[2]),
                    "rx_drop": int(nums[3]),
                    "rx_fifo": int(nums[4]),
                    "rx_frame": int(nums[5]),
                    "rx_compressed": int(nums[6]),
                    "rx_multicast": int(nums[7]),
                    "tx_bytes": int(nums[8]),
                    "tx_packets": int(nums[9]),
                    "tx_errs": int(nums[10]),
                    "tx_drop": int(nums[11]),
                    "tx_fifo": int(nums[12]),
                    "tx_colls": int(nums[13]),
                    "tx_carrier": int(nums[14]),
                    "tx_compressed": int(nums[15]),
                }
            )
        except ValueError:
            continue
    return interfaces


def parse_proc_net_arp() -> list[dict[str, Any]]:
    """
    Parse Linux kernel /proc/net/arp table to inspect local neighbor hardware mappings.
    """
    path = Path("/proc/net/arp")
    if not path.exists():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.debug("Failed reading /proc/net/arp: %s", e)
        return []

    lines = content.splitlines()
    if len(lines) <= 1:
        return []

    arp_entries: list[dict[str, Any]] = []
    # Header: IP address HW type Flags HW address Mask Device
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) >= 6:
            arp_entries.append(
                {
                    "ip": parts[0],
                    "hw_type": parts[1],
                    "flags": parts[2],
                    "mac": parts[3],
                    "mask": parts[4],
                    "device": parts[5],
                }
            )
    return arp_entries


def unpack_packet_headers(raw_bytes: bytes) -> dict[str, Any]:
    """
    Dissect packet byte headers entirely in memory using standard struct.unpack with big-endian network byte order.
    Unpacks Ethernet frame, IPv4 header, TCP/UDP transport headers, and ARP packets.
    """
    if len(raw_bytes) < 14:
        return {
            "status": "INVALID",
            "error": f"Packet truncated: length {len(raw_bytes)} < 14 bytes Ethernet minimum",
            "raw_len": len(raw_bytes),
        }

    # 1. Ethernet Header (14 bytes)
    dst_mac_raw, src_mac_raw, eth_proto = struct.unpack("!6s6sH", raw_bytes[:14])
    dst_mac = ":".join(f"{b:02x}" for b in dst_mac_raw)
    src_mac = ":".join(f"{b:02x}" for b in src_mac_raw)
    eth_dict: dict[str, Any] = {
        "dst_mac": dst_mac,
        "src_mac": src_mac,
        "proto": eth_proto,
        "proto_hex": f"0x{eth_proto:04x}",
    }

    result: dict[str, Any] = {
        "status": "OK",
        "ethernet": eth_dict,
        "raw_len": len(raw_bytes),
    }

    # 2. IPv4 Header (eth_proto == 0x0800)
    if eth_proto == 0x0800 and len(raw_bytes) >= 34:
        v_ihl, tos, total_len, ident, flags_frag, ttl, proto_num, checksum, src_ip_raw, dst_ip_raw = struct.unpack(
            "!BBHHHBBH4s4s", raw_bytes[14:34]
        )
        version = v_ihl >> 4
        ihl = (v_ihl & 0x0F) * 4
        src_ip = socket.inet_ntoa(src_ip_raw)
        dst_ip = socket.inet_ntoa(dst_ip_raw)
        proto_name = {6: "TCP", 17: "UDP", 1: "ICMP"}.get(proto_num, f"UNKNOWN_{proto_num}")

        result["ip"] = {
            "version": version,
            "ihl": ihl,
            "tos": tos,
            "total_len": total_len,
            "id": ident,
            "ttl": ttl,
            "protocol": proto_name,
            "protocol_num": proto_num,
            "checksum": checksum,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
        }

        transport_offset = 14 + ihl
        # TCP Segment
        if proto_num == 6 and len(raw_bytes) >= transport_offset + 20:
            src_port, dst_port, seq, ack, offset_res, flags, window, chksum, urg_ptr = struct.unpack(
                "!HHIIBBHHH", raw_bytes[transport_offset : transport_offset + 20]
            )
            data_offset = (offset_res >> 4) * 4
            tcp_flags = {
                "fin": bool(flags & 0x01),
                "syn": bool(flags & 0x02),
                "rst": bool(flags & 0x04),
                "psh": bool(flags & 0x08),
                "ack": bool(flags & 0x10),
                "urg": bool(flags & 0x20),
            }
            result["transport"] = {
                "proto": "TCP",
                "src_port": src_port,
                "dst_port": dst_port,
                "seq": seq,
                "ack": ack,
                "data_offset": data_offset,
                "flags": tcp_flags,
                "flags_raw": flags,
                "window": window,
                "checksum": chksum,
            }
        # UDP Datagram
        elif proto_num == 17 and len(raw_bytes) >= transport_offset + 8:
            src_port, dst_port, udp_len, udp_chksum = struct.unpack(
                "!HHHH", raw_bytes[transport_offset : transport_offset + 8]
            )
            result["transport"] = {
                "proto": "UDP",
                "src_port": src_port,
                "dst_port": dst_port,
                "length": udp_len,
                "checksum": udp_chksum,
            }

    # 3. ARP Packet (eth_proto == 0x0806)
    elif eth_proto == 0x0806 and len(raw_bytes) >= 42:
        (
            hw_type,
            proto_type,
            hw_size,
            proto_size,
            opcode,
            sender_mac_raw,
            sender_ip_raw,
            target_mac_raw,
            target_ip_raw,
        ) = struct.unpack("!HHBBH6s4s6s4s", raw_bytes[14:42])
        sender_mac = ":".join(f"{b:02x}" for b in sender_mac_raw)
        target_mac = ":".join(f"{b:02x}" for b in target_mac_raw)
        sender_ip = socket.inet_ntoa(sender_ip_raw)
        target_ip = socket.inet_ntoa(target_ip_raw)
        opcode_name = {1: "REQUEST", 2: "REPLY"}.get(opcode, f"OP_{opcode}")

        result["arp"] = {
            "hw_type": hw_type,
            "proto_type": proto_type,
            "opcode": opcode_name,
            "opcode_num": opcode,
            "sender_mac": sender_mac,
            "sender_ip": sender_ip,
            "target_mac": target_mac,
            "target_ip": target_ip,
        }

    return result


def dissect_shm_pcap_buffer(buffer_or_path: bytes | str | Path, limit: int = 50) -> dict[str, Any]:
    """
    Parse standard PCAP files or raw packet buffers in RAM (/dev/shm) without executing tshark.
    Supports standard big-endian and little-endian PCAP headers.
    """
    if isinstance(buffer_or_path, (str, Path)):
        p = Path(buffer_or_path)
        if not p.exists():
            return {"status": "EMPTY", "count": 0, "packets": [], "message": f"Path {p} does not exist."}
        try:
            raw = p.read_bytes()
        except OSError as e:
            return {"status": "ERROR", "count": 0, "packets": [], "error": str(e)}
    else:
        raw = bytes(buffer_or_path)

    if len(raw) < 14:
        return {"status": "EMPTY", "count": 0, "packets": []}

    # Check for PCAP Global Header magic (24 bytes)
    if len(raw) >= 24:
        magic = struct.unpack("!I", raw[:4])[0]
        if magic in (0xA1B2C3D4, 0xA1B23C4D):
            endian = ">"
        elif magic in (0xD4C3B2A1, 0x4D3CB2A1):
            endian = "<"
        else:
            endian = None

        if endian is not None:
            # Valid PCAP header: magic(4), v_maj(2), v_min(2), tz(4), sigfigs(4), snaplen(4), net(4)
            offset = 24
            packets: list[dict[str, Any]] = []
            while offset + 16 <= len(raw) and len(packets) < limit:
                ts_sec, ts_usec, incl_len, orig_len = struct.unpack(f"{endian}IIII", raw[offset : offset + 16])
                offset += 16
                if offset + incl_len > len(raw):
                    break
                pkt_data = raw[offset : offset + incl_len]
                offset += incl_len

                parsed = unpack_packet_headers(pkt_data)
                parsed["timestamp"] = ts_sec + (ts_usec / 1_000_000.0)
                parsed["orig_len"] = orig_len
                packets.append(parsed)

            return {
                "status": "OK",
                "format": "pcap",
                "count": len(packets),
                "packets": packets,
            }

    # Fallback: treat as raw Ethernet frame
    single_pkt = unpack_packet_headers(raw)
    return {
        "status": "OK",
        "format": "raw_frame",
        "count": 1 if single_pkt.get("status") == "OK" else 0,
        "packets": [single_pkt] if single_pkt.get("status") == "OK" else [],
    }


def enforce_netfilter_mitigation(
    target_ip: str,
    rule_action: str = "drop",
    simulate: bool = False,
) -> dict[str, Any]:
    """
    Deterministic, idempotent netfilter drop rule management.
    Fails soft with SIMULATED status when executed in unprivileged (DIMINISHED) tier.
    """
    from engine.privilege import capability_tier, privilege_prefix

    eff_ip = (target_ip or "").strip()
    try:
        ipaddress.ip_address(eff_ip)
    except ValueError:
        return {"status": "ERROR", "error": f"Invalid IP address: '{eff_ip}'", "deterministic": True}

    action_norm = (rule_action or "drop").strip().lower()
    tier = capability_tier()
    prefix = privilege_prefix()

    simulated_cmd = f"nft add rule inet filter input ip saddr {eff_ip} {action_norm}"

    # Fail-soft unprivileged simulation or explicit simulation flag
    if simulate or prefix is None:
        return {
            "status": "SIMULATED",
            "target": eff_ip,
            "action": action_norm,
            "capability_tier": tier,
            "simulated_rule": simulated_cmd,
            "message": "Tier is DIMINISHED. Netfilter rule simulated.",
            "deterministic": True,
        }

    nft_bin = shutil.which("nft")
    if not nft_bin:
        return {
            "status": "DEGRADED",
            "target": eff_ip,
            "message": "nft binary not found on host.",
            "simulated_rule": simulated_cmd,
            "deterministic": True,
        }

    # Idempotency check: inspect current ruleset
    try:
        check_proc = subprocess.run(
            prefix + ["nft", "list", "ruleset"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if (
            check_proc.returncode == 0
            and f"ip saddr {eff_ip}" in check_proc.stdout
            and action_norm in check_proc.stdout
        ):
            return {
                "status": "OK",
                "target": eff_ip,
                "action": action_norm,
                "mitigated": True,
                "idempotent_noop": True,
                "rule": f"{action_norm} ip saddr {eff_ip}",
                "deterministic": True,
            }
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("nft list ruleset check error: %s", e)

    # Apply rule
    try:
        add_proc = subprocess.run(
            prefix + ["nft", "add", "rule", "inet", "filter", "input", "ip", "saddr", eff_ip, action_norm],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if add_proc.returncode == 0:
            return {
                "status": "OK",
                "target": eff_ip,
                "action": action_norm,
                "mitigated": True,
                "rule": f"{action_norm} ip saddr {eff_ip}",
                "deterministic": True,
            }
        return {
            "status": "DEGRADED",
            "target": eff_ip,
            "message": add_proc.stderr.strip()[:200] or "Failed adding nft rule",
            "deterministic": True,
        }
    except (subprocess.SubprocessError, OSError) as e:
        return {
            "status": "DEGRADED",
            "target": eff_ip,
            "message": str(e),
            "deterministic": True,
        }
