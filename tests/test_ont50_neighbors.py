"""ONT-50 T1 (G21): aep_ctl network neighbors. No real network: sockets, ARP and routes are monkeypatched."""

import asyncio
import ipaddress
import json
from pathlib import Path

import pytest

from engine import net_telemetry as nt

REPO = Path(__file__).resolve().parent.parent


def _route(iface: str, dest: str, mask: str, flags: int = 1) -> dict:
    return {"iface": iface, "destination": dest, "gateway": "0.0.0.0", "flags": flags, "mask": mask}  # noqa: S104


def _arp(ip: str, mac: str, dev: str = "wlan0", flags: str = "0x2") -> dict:
    return {"ip": ip, "hw_type": "0x1", "flags": flags, "mac": mac, "mask": "*", "device": dev}


class _FakeSock:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    def setblocking(self, flag):
        assert flag is False

    def sendto(self, data, addr):
        _FakeSock.sent.append(addr)

    def close(self):
        pass


@pytest.fixture
def lan(monkeypatch):
    _FakeSock.sent = []
    monkeypatch.setattr(nt, "_new_udp_socket", _FakeSock)
    monkeypatch.setattr(nt, "parse_proc_net_route", lambda: [_route("wlan0", "192.168.1.0", "255.255.255.0")])
    arp = [
        _arp("192.168.1.20", "AA:BB:CC:00:00:20"),
        _arp("192.168.1.3", "aa:bb:cc:00:00:03"),
        _arp("192.168.1.9", "00:00:00:00:00:00"),  # incomplete
        _arp("192.168.1.10", "aa:bb:cc:00:00:10", flags="0x0"),  # incomplete
        _arp("172.17.0.2", "aa:bb:cc:00:00:99", dev="docker0"),  # ignored iface
    ]
    monkeypatch.setattr(nt, "parse_proc_net_arp", lambda: arp)
    return arp


def test_sweep_24_generates_hosts_and_sorts_neighbors(lan):
    res = asyncio.run(nt.discover_neighbors(None, sweep=True, timeout_ms=50, tier_octal=7))
    assert res["sweep"] is True and res["swept_hosts"] == 254
    assert len(_FakeSock.sent) == 254
    assert all(port == nt.NEIGHBOR_DISCARD_PORT for _, port in _FakeSock.sent)
    assert [n["ip"] for n in res["neighbors"]] == ["192.168.1.3", "192.168.1.20"]  # numeric order, no incomplete
    assert res["neighbors"][0]["oui"] == "AA:BB:CC"
    assert res["prefixes"] == ["192.168.1.0/24"] and res["arp_raw_count"] == 5
    assert res["limits"]


def test_tier4_never_sweeps(lan):
    res = asyncio.run(nt.discover_neighbors(None, sweep=True, tier_octal=4))
    assert res["sweep"] is False and res["reason"] == "tier < 6rw-"
    assert _FakeSock.sent == []
    assert res["count"] == 2  # passive ARP only


def test_nosweep_flag(lan):
    res = asyncio.run(nt.discover_neighbors(None, sweep=False, tier_octal=7))
    assert res["sweep"] is False and res["reason"] == "nosweep" and _FakeSock.sent == []


def test_wide_prefix_is_skipped(monkeypatch, lan):
    monkeypatch.setattr(nt, "parse_proc_net_route", lambda: [_route("wlan0", "10.1.0.0", "255.255.0.0")])
    res = asyncio.run(nt.discover_neighbors(None, sweep=True, tier_octal=7))
    assert res["prefixes"] == [] and res["sweep"] is False and _FakeSock.sent == []
    assert res["skipped_prefixes"][0]["prefix"] == "10.1.0.0/16"


def test_ignored_interfaces_unless_named(monkeypatch, lan):
    monkeypatch.setattr(nt, "parse_proc_net_route", lambda: [_route("docker0", "172.17.0.0", "255.255.255.0")])
    assert asyncio.run(nt.discover_neighbors(None, sweep=False))["prefixes"] == []
    named = asyncio.run(nt.discover_neighbors("docker0", sweep=False))
    assert named["prefixes"] == ["172.17.0.0/24"]
    assert [n["ip"] for n in named["neighbors"]] == ["172.17.0.2"]


def test_probe_is_limited_to_16(monkeypatch, lan):
    many = [_arp(f"192.168.1.{i}", f"aa:bb:cc:00:01:{i:02x}") for i in range(30, 50)]
    monkeypatch.setattr(nt, "parse_proc_net_arp", lambda: many)
    probed: list[str] = []

    async def fake_probe(host, ports=None, timeout_ms=300, concurrency=50):
        probed.append(host)
        return {"open_ports": [{"port": 22, "service": "SSH"}], "scan_duration_ms": 1.0}

    monkeypatch.setattr(nt, "probe_tcp_ports", fake_probe)
    res = asyncio.run(nt.discover_neighbors(None, sweep=False, probe=True))
    assert len(probed) == nt.NEIGHBOR_PROBE_MAX == 16
    assert res["probe_skipped"] == 4
    assert res["neighbors"][0]["probe"]["open_ports"] == [{"port": 22, "service": "SSH"}]
    assert "probe" not in res["neighbors"][-1]


def test_compact_view_drops_detail_keys(lan):
    res = asyncio.run(nt.discover_neighbors(None, sweep=False))
    compact = nt.compact_neighbors_result(res)
    assert set(compact["neighbors"][0]) == {"ip", "mac", "iface"}
    assert "arp_raw_count" not in compact and "arp_raw_count" in res


def test_parse_neighbor_args_tolerates_name_and_args():
    p = nt.parse_neighbor_args("nosweep", None, None)
    assert p["iface"] is None and p["sweep"] is False
    p = nt.parse_neighbor_args("wlan0", None, "probe,timeout=1500")
    assert p == {"iface": "wlan0", "sweep": True, "probe": True, "timeout_ms": 1500}
    assert nt.parse_neighbor_args(None, None, ["sweep", "probe"])["probe"] is True


def test_link_prefixes_skip_gateway_default_and_down():
    routes = [
        _route("wlan0", "0.0.0.0", "0.0.0.0"),  # noqa: S104
        _route("wlan0", "192.168.1.0", "255.255.255.0"),
        _route("eth0", "10.0.0.0", "255.255.255.0", flags=0),
        _route("eth1", "10.9.0.0", "255.255.255.0", flags=3),
    ]
    got = nt._link_prefixes(routes, None)
    assert [str(c["network"]) for c in got] == ["192.168.1.0/24"]
    assert isinstance(got[0]["network"], ipaddress.IPv4Network)


def test_schema_and_discover_routing():
    from engine.privilege import _CAP_TACTICAL, CHMOD_DEGRADATION_MATRIX, CONTROL_PLANE_SCHEMA

    net = CONTROL_PLANE_SCHEMA["network"]
    assert "neighbors" in net["actions"]
    pre = net["preconditions"]["neighbors"]
    assert pre["required_fs"] == ["/proc/net/arp", "/proc/net/route"]
    assert pre["privilege_tier"] == "DIMINISHED" and pre["fail_soft_behavior"] == "DEGRADED"
    assert "neighbors" in json.dumps(CHMOD_DEGRADATION_MATRIX["domains"]["network"])
    assert any("neighbors" in c for c in _CAP_TACTICAL["system_inspect"]["canonical_calls"])


def test_cli_neighbors_nosweep_runs_without_network(lan):
    """Real script logic (domain_network) with sockets/ARP/routes mocked, then relayed through the MCP tool."""
    import importlib.machinery
    import importlib.util

    import server

    loader = importlib.machinery.SourceFileLoader("aep_ctl_script_ont50", str(REPO / "scripts" / "aep-ctl"))
    spec = importlib.util.spec_from_loader("aep_ctl_script_ont50", loader)
    assert spec is not None
    ctl = importlib.util.module_from_spec(spec)
    loader.exec_module(ctl)
    out = ctl.domain_network("neighbors", "nosweep", None)
    assert out["status"] == "OK" and out["sweep"] is False and out["swept_hosts"] == 0
    assert [n["ip"] for n in out["neighbors"]] == ["192.168.1.3", "192.168.1.20"]
    assert _FakeSock.sent == []
    via_mcp = json.loads(asyncio.run(server.aep_ctl(domain="network", action="neighbors", args="nosweep")))
    assert via_mcp["count"] == out["count"]


def test_discover_routes_hosts_on_my_lan_to_neighbors():
    import asyncio

    import server

    out = json.loads(asyncio.run(server.discover(use_case="hosts on my LAN")))
    top = out["suggested_capability"][0]
    assert top["capability"] == "system_inspect"
    assert any("neighbors" in c for c in top["canonical_calls"])


def test_server_neighbors_paginates_with_cursor(lan):
    import server

    first = json.loads(
        asyncio.run(server.aep_ctl(domain="network", action="neighbors", args="nosweep", verbosity="detail", limit=1))
    )
    assert first["status"] == "OK" and first["total_count"] == 2 and len(first["neighbors"]) == 1
    assert first["truncated"] is True and first["cursor"] == "1"
    assert first["neighbors"][0]["ip"] == "192.168.1.3"
    second = json.loads(
        asyncio.run(
            server.aep_ctl(domain="network", action="neighbors", args="nosweep", verbosity="detail", limit=1, cursor=1)
        )
    )
    assert second["neighbors"][0]["ip"] == "192.168.1.20" and second["truncated"] is False
    compact = json.loads(
        asyncio.run(server.aep_ctl(domain="network", action="neighbors", args="nosweep", verbosity="summary"))
    )
    assert set(compact["neighbors"][0]) == {"ip", "mac", "iface"}


def test_neighbors_summary_token_budget(lan):
    import server

    res = asyncio.run(server.aep_ctl(domain="network", action="neighbors", args="nosweep", verbosity="summary"))
    tok = json.loads(res)["t"]["tok"]
    assert tok <= 450
