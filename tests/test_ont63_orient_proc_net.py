"""ONT-63 group (c): path-users, process_inspect detail extension, aep_ctl network probe explicit ports."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import server
from engine import net_telemetry
from engine.primitives_orient import process_detail


async def _run(name: str, params: dict) -> dict:
    return json.loads(await server.default_primitives(action="run", name=name, params=params, verbosity="detail"))


@pytest.fixture
def sleeper(tmp_path: Path):
    env = {**os.environ, "AEP_VISIBLE": "yes", "MY_SECRET_TOKEN": "s3cr3t-xyz", "API_KEY": "k-123"}
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(30)", "--token=abc123", "plain"],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    time.sleep(0.2)
    yield proc
    proc.kill()
    proc.wait()


@pytest.mark.anyio
async def test_path_users_finds_cwd_holder_and_empty_is_safe(tmp_path: Path, sleeper: subprocess.Popen) -> None:
    r = (await _run("path-users", {"path": str(tmp_path)}))["result"]
    assert any(p["pid"] == sleeper.pid and "cwd" in p["uses"] for p in r["processes"])
    assert f"process_inspect(pid={r['processes'][0]['pid']}" in r["next_action"]
    empty = tmp_path / "nobody"
    empty.mkdir()
    r2 = (await _run("path-users", {"path": str(empty)}))["result"]
    assert r2["count"] == 0 and "safe to modify/remove" in r2["next_action"]


@pytest.mark.anyio
async def test_path_users_vetoed_and_missing_param() -> None:
    assert (await _run("path-users", {"path": os.path.expanduser("~/.ssh")}))["status"] == "PARAM_ERROR"
    assert (await _run("path-users", {}))["status"] == "PARAM_ERROR"


def test_process_detail_never_leaks_env_values(sleeper: subprocess.Popen) -> None:
    d = process_detail(sleeper.pid, privileged=False)
    assert d["available"] and d["ppid"] == os.getpid()
    assert d["ancestors"] and d["start"].endswith("Z") and d["uptime_s"] >= 0
    assert "MY_SECRET_TOKEN" in d["env_names"] and "API_KEY" in d["env_names"]
    blob = json.dumps(d)
    assert "s3cr3t-xyz" not in blob and "k-123" not in blob and "abc123" not in blob
    assert d["env_allowed"].get("AEP_VISIBLE") == "yes"
    allow = {"PATH", "HOME", "LANG", "PWD", "USER", "SHELL", "VIRTUAL_ENV", "GOTOOLCHAIN", "GOROOT"}
    assert all(k in allow or k.startswith("AEP_") for k in d["env_allowed"])
    assert "plain" in d["cmdline"] and "--token=***" in d["cmdline"]


def test_process_detail_other_uid_withheld() -> None:
    d = process_detail(1, privileged=False)
    if d.get("uid") != os.getuid():
        assert d["full_access"] is False and "env_names" not in d and "cwd" not in d


@pytest.mark.anyio
async def test_process_inspect_detail_only_in_detail_verbosity(sleeper: subprocess.Popen) -> None:
    full = json.loads(await server.process_inspect(pid=sleeper.pid, verbosity="detail"))
    assert full["detail"]["env_names"] and "s3cr3t-xyz" not in json.dumps(full)
    brief = json.loads(await server.process_inspect(pid=sleeper.pid, verbosity="summary"))
    assert "detail" not in brief


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _probe(**kw) -> dict:
    return json.loads(await server.aep_ctl(domain="network", action="probe", verbosity="detail", **kw))


@pytest.mark.anyio
async def test_network_probe_honours_explicit_port_closed_and_open() -> None:
    closed = _closed_port()
    r = await _probe(params={"host": "127.0.0.1", "port": closed})
    assert r["scanned_ports"] == 1 and r["resolved"] == ["127.0.0.1"]
    assert r["ports"][0]["error_class"] == "refused" and r["open_count"] == 0
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        r2 = await _probe(params={"host": "127.0.0.1", "ports": [port, closed], "timeout_ms": 500})
        assert r2["scanned_ports"] == 2 and r2["open_count"] == 1 and r2["open_ports"][0]["port"] == port


@pytest.mark.anyio
async def test_network_probe_param_errors_and_defaults() -> None:
    assert (await _probe(params={"host": "127.0.0.1", "ports": list(range(1, 12))}))["status"] == "PARAM_ERROR"
    assert (await _probe(params={"host": "127.0.0.1", "port": 70000}))["status"] == "PARAM_ERROR"
    assert (await _probe(params={"host": "http://x y"}))["status"] == "PARAM_ERROR"
    legacy = await _probe(name="127.0.0.1")
    assert legacy["scanned_ports"] == 25  # no explicit port: historical behaviour


@pytest.mark.anyio
async def test_probe_dns_fail_class() -> None:
    res = await net_telemetry.probe_tcp_ports("no-such-host.invalid", [80], timeout_ms=200)
    assert res["status"] == "ERROR" and res["error_class"] == "dns_fail" and res["resolved"] == []


def test_parse_probe_ports() -> None:
    assert net_telemetry.parse_probe_ports(None) is None
    assert net_telemetry.parse_probe_ports(22) == [22]
    assert net_telemetry.parse_probe_ports("22, 80,22") == [22, 80]
    with pytest.raises(ValueError):
        net_telemetry.parse_probe_ports([0])
