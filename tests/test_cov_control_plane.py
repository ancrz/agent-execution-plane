"""Cobertura conductual de `aep_ctl` (network/package/service/ipc/storage/hardware).

Reglas: ninguna prueba muta el host. Las lecturas reales (interfaces, routes, mounts, paquete `bash`...) se
validan contra campos coherentes; las mutaciones (service start/stop/restart) se prueban solo por validacion de
parametros y por el gating del tier (4r-- SIMULATED / 5r-x DEGRADED), que ocurre antes de cualquier `systemctl`.
El pool IPC se aisla en un tmp (nunca /dev/shm/aep_pool).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

import server
from engine.ipc_pool import SessionPool
from engine.privilege import _PrivilegeCache


@pytest.fixture
def tier(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """Devuelve un setter de tier forzado; resetea la cache de privilegios al terminar."""

    def _set(value: str) -> None:
        monkeypatch.setenv("AEP_FORCE_TIER", value)
        _PrivilegeCache.reset()

    yield _set
    _PrivilegeCache.reset()


@pytest.fixture
def isolated_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionPool:
    pool = SessionPool(max_slots=4, base_dir=tmp_path / "pool")
    monkeypatch.setattr(server, "GLOBAL_SESSION_POOL", pool)
    return pool


def _j(coro: Awaitable[str]) -> dict[str, Any]:
    async def _await() -> str:
        return await coro

    data = json.loads(asyncio.run(_await()))
    assert isinstance(data, dict)
    return data


# --------------------------------------------------------------------------- network (lecturas reales)
def test_network_interfaces_reports_loopback_with_counters(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="network", action="interfaces", verbosity="detail"))
    assert res["status"] == "OK"
    assert res["count"] == len(res["interfaces"]) >= 1
    lo = next(i for i in res["interfaces"] if i["interface"] == "lo")
    assert lo["rx_bytes"] >= 0 and lo["tx_packets"] >= 0


def test_network_routes_have_destination_and_flags(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="network", action="routes", verbosity="detail"))
    assert res["status"] == "OK"
    assert res["total_count"] == len(res["routes"])
    for route in res["routes"]:
        assert route["dst"] and isinstance(route["dst"], str)
        assert isinstance(route.get("flags", []), list)


def test_network_listeners_summary_is_compact_and_paginated(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="network", action="listeners", verbosity="summary", limit=3))
    assert res["status"] == "OK"
    assert res["count"] <= 3
    assert res["total_count"] >= res["count"]
    for item in res["listeners"]:
        assert set(item) == {"proto", "local", "process", "pid"}  # proyeccion compacta del modo summary
        assert ":" in item["local"]
    # Regresion (bug real corregido en server.py): el fast-path in-process ignoraba summary/limit/cursor.
    assert res["truncated"] is (res["total_count"] > 3)
    assert res["cursor"] == ("3" if res["truncated"] else None)


def test_network_listeners_pagination_with_synthetic_sockets(tier, monkeypatch: pytest.MonkeyPatch) -> None:
    tier("4r--")
    from engine import net_telemetry

    rows = [
        {"proto": "tcp", "local": f"0.0.0.0:{9000 + i}", "process": f"p{i}", "pid": i, "extra": "x"} for i in range(60)
    ]
    monkeypatch.setattr(net_telemetry, "parse_proc_net_sockets", lambda protocol="tcp", **_kw: rows)

    first = _j(server.aep_ctl(domain="network", action="listeners", verbosity="summary", limit=3))
    assert first["count"] == 3 and first["total_count"] == 60
    assert first["truncated"] is True and first["cursor"] == "3"
    assert [i["pid"] for i in first["listeners"]] == [0, 1, 2]
    assert all("extra" not in i for i in first["listeners"])

    nxt = _j(server.aep_ctl(domain="network", action="listeners", verbosity="summary", limit=3, cursor=3))
    assert [i["pid"] for i in nxt["listeners"]] == [3, 4, 5]
    assert nxt["cursor"] == "6"
    assert not {i["pid"] for i in first["listeners"]} & {i["pid"] for i in nxt["listeners"]}

    detail = _j(server.aep_ctl(domain="network", action="listeners", verbosity="detail"))
    assert detail["count"] == 50 and detail["total_count"] == 60  # default limit caps detail
    assert detail["truncated"] is True and detail["cursor"] == "50"


def test_network_arp_entries_are_well_formed(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="network", action="arp", verbosity="detail"))
    assert res["status"] == "OK"
    assert res["count"] == len(res["arp"])
    for entry in res["arp"]:
        assert entry["ip"].count(".") == 3
        assert entry["mac"].count(":") == 5
        assert entry["device"]


def test_network_inspect_summary_projects_interface_addresses(tier) -> None:
    if not shutil.which("ip"):
        pytest.skip("iproute2 `ip` no disponible")
    tier("4r--")
    res = _j(server.aep_ctl(domain="network", action="inspect", verbosity="summary"))
    assert res["status"] == "OK"
    lo = next(i for i in res["interfaces"] if i["ifname"] == "lo")
    assert "127.0.0.1" in lo["addresses"]
    assert lo["mtu"] > 0


# --------------------------------------------------------------------------- package (lecturas reales)
needs_dpkg = pytest.mark.skipif(not shutil.which("dpkg-query"), reason="requiere dpkg (Debian/Ubuntu)")


@needs_dpkg
def test_package_info_and_check_for_known_package_bash(tier) -> None:
    tier("4r--")
    info = _j(server.aep_ctl(domain="package", action="info", name="bash"))
    assert info["status"] == "OK" and info["package"] == "bash"
    assert info["version"] and info["arch"]
    check = _j(server.aep_ctl(domain="package", action="check", name="bash"))
    assert check["installed"] is True
    missing = _j(server.aep_ctl(domain="package", action="check", name="aep-no-such-package-zz"))
    assert missing["installed"] is False  # no es un error: es una respuesta de lectura


@needs_dpkg
def test_package_installed_and_list_paginate(tier) -> None:
    tier("4r--")
    first = _j(server.aep_ctl(domain="package", action="installed", verbosity="summary", limit=5))
    assert first["status"] == "OK" and first["count"] == len(first["packages"]) <= 30
    assert first["total_count"] >= first["count"]
    for pkg in first["packages"]:
        assert pkg["name"] and pkg["version"]
    listed = _j(server.aep_ctl(domain="package", action="list", verbosity="summary"))
    assert listed["status"] == "OK"
    assert listed["total_count"] == first["total_count"]


def test_package_info_without_name_returns_remediation(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="package", action="info"))
    assert res["status"] == "ERROR"
    assert res["message"] and res["usage"]  # remediacion explicita


# --------------------------------------------------------------------------- service
needs_systemd = pytest.mark.skipif(not shutil.which("systemctl"), reason="requiere systemd")


@needs_systemd
def test_service_list_reads_running_units_without_mutation(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="service", action="list", verbosity="summary"))
    assert res["status"] == "OK"
    assert res["capability_tier"] == "DIMINISHED"
    assert res["count"] <= 25
    for svc in res["services"]:
        assert svc["unit"].endswith(".service") and svc["active"] == "active"


@needs_systemd
def test_service_mutations_require_a_name(tier) -> None:
    tier("6rw-")
    for res in (
        _j(server.aep_ctl(domain="service", action="start")),
        _j(server.aep_ctl(domain="service", action="stop")),
        _j(server.aep_ctl(domain="service", action="restart")),
    ):
        assert res["status"] == "ERROR"
        assert "name" in res["message"] and res["usage"].startswith("aep-ctl service")


@needs_systemd
def test_service_start_is_simulated_in_auditor_tier(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="service", action="start", name="aep-cov-nonexistent.service"))
    assert res["status"] == "SIMULATED" and res["simulated"] is True
    assert res["scope"] == "read-only" and res["chmod_tier"] == "4r--"
    assert res["service"] == "aep-cov-nonexistent.service"


@needs_systemd
def test_service_stop_and_restart_are_degraded_in_restricted_tier(tier) -> None:
    tier("5r-x")
    stop = _j(server.aep_ctl(domain="service", action="stop", name="aep-cov-nonexistent.service"))
    restart = _j(server.aep_ctl(domain="service", action="restart", name="aep-cov-nonexistent.service"))
    for res, act in ((stop, "stop"), (restart, "restart")):
        assert res["status"] == "DEGRADED" and res["action"] == act
        assert res["chmod_tier"] == "5r-x" and res["scope"] == "read-only"


# --------------------------------------------------------------------------- ipc (pool aislado en tmp)
def test_ipc_pool_reap_and_flush_operate_on_the_isolated_pool(tier, isolated_pool: SessionPool) -> None:
    tier("6rw-")
    isolated_pool.acquire(session_id="cov-session", agent_id="cov-agent")
    pool = _j(server.aep_ctl(domain="ipc", action="pool"))
    assert pool["status"] == "OK"
    assert pool["pool"]["max_slots"] == 4 and pool["pool"]["active_count"] == 1
    assert pool["pool"]["base_dir"] == str(isolated_pool.base_dir)

    reaped = _j(server.aep_ctl(domain="ipc", action="reap"))
    assert reaped["status"] == "OK"
    assert reaped["reaped_count"]["active_slots"] == 1  # la lease vigente NO se reapea

    flushed = _j(server.aep_ctl(domain="ipc", action="flush"))
    assert flushed["status"] == "OK"
    assert flushed["flushed_count"]["flushed_count"] >= 1
    assert isolated_pool.status()["active_count"] == 0  # el flush libero la lease


# --------------------------------------------------------------------------- storage
def test_storage_usage_reports_root_filesystem(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="storage", action="usage", verbosity="summary"))
    assert res["status"] == "OK"
    root = next(fs for fs in res["filesystems"] if fs["mount"] == "/")
    assert root["size"] >= root["used"] >= 0
    assert root["use_pct"].endswith("%")


@pytest.mark.skipif(not shutil.which("lsblk"), reason="requiere lsblk")
def test_storage_disks_summary_filters_loop_devices(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="storage", action="disks", verbosity="summary"))
    assert res["status"] == "OK"
    assert res["count"] == len(res["blockdevices"])
    assert all(bd["type"] != "loop" for bd in res["blockdevices"])
    assert res["filtered_loop_devices"] >= 0


def test_storage_mounts_summary_flattens_mount_table(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="storage", action="mounts", verbosity="summary"))
    assert res["status"] == "OK" and res["verbosity"] == "summary"
    assert res["total_mounts"] >= res["count"] == len(res["filesystems"]) >= 1
    assert all({"target", "source", "fstype"} <= set(m) for m in res["filesystems"])


# --------------------------------------------------------------------------- hardware
def test_hardware_accelerators_count_matches_list_and_fields(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="hardware", action="accelerators"))
    assert res["status"] == "OK"
    assert res["count"] == len(res["accelerators"])
    for acc in res["accelerators"]:
        assert acc["card"].startswith("card")
        assert acc["vram_total_mib"] >= acc["vram_free_mib"] >= 0


def test_hardware_admit_rejects_unknown_device_and_echoes_request(tier) -> None:
    tier("4r--")
    res = _j(
        server.aep_ctl(
            domain="hardware",
            action="admit",
            name="card-does-not-exist",
            params={"req_vram_mib": 128, "margin_mib": 512},
        )
    )
    assert res["status"] == "REJECTED" and res["admit"] is False
    assert res["req_vram_mib"] == 128 and res["margin_mib"] == 512
    assert res["reason"].startswith(("device_", "no_accelerators"))


def test_hardware_admit_rejects_request_larger_than_any_device(tier) -> None:
    tier("4r--")
    res = _j(server.aep_ctl(domain="hardware", action="admit", params={"req_mib": 10**9}))
    assert res["admit"] is False  # nunca cabe: sin GPU -> REJECTED; con GPU -> sin memoria libre
