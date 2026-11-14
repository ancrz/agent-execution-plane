"""ONT-48 T13 (G19): service map covers common LAN services; unlisted ports stay unknown."""

from __future__ import annotations

import asyncio
import socket

from engine import net_telemetry


def test_new_service_names() -> None:
    m = net_telemetry.COMMON_TCP_SERVICES
    expected = {111: "rpcbind", 139: "NetBIOS", 548: "AFP", 631: "IPP", 1900: "SSDP", 2049: "NFS"}
    expected |= {3702: "WS-Discovery", 5353: "mDNS", 5900: "VNC", 8006: "Proxmox", 9100: "JetDirect"}
    assert {p: m.get(p) for p in expected} == expected
    assert 8787 not in m and 4402 not in m


def test_probe_labels_open_port_with_mapped_service(monkeypatch) -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setitem(net_telemetry.COMMON_TCP_SERVICES, port, "IPP")
    try:
        res = asyncio.run(net_telemetry.probe_tcp_ports("127.0.0.1", [port], timeout_ms=300))
    finally:
        srv.close()
    assert "IPP" in str(res)
