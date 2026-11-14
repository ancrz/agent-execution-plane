"""ONT-52 (ronda 6): firewall veraz (G36). Sin red real, sin DB real: subprocess/which monkeypatched."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import server
from engine import net_telemetry as nt
from engine.catalog import ArtifactCatalog
from engine.privilege import _PrivilegeCache

NFT_JSON = json.dumps(
    {
        "nftables": [
            {"metainfo": {"version": "1.1.1"}},
            {"table": {"family": "inet", "name": "windscribe", "handle": 1}},
            {"chain": {"family": "inet", "table": "windscribe", "name": "input", "handle": 1}},
            {"chain": {"family": "inet", "table": "windscribe", "name": "output", "handle": 2}},
            {"rule": {"family": "inet", "table": "windscribe", "chain": "output", "handle": 5}},
            {"table": {"family": "ip", "name": "empty", "handle": 2}},
        ]
    }
)


def _fake_env(monkeypatch: pytest.MonkeyPatch, ufw_out: str, nft_out: str | None, tools=("ufw", "nft")):
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "ufw" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=ufw_out, stderr="")
        if nft_out is None:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Operation not permitted")
        return subprocess.CompletedProcess(cmd, 0, stdout=nft_out, stderr="")

    monkeypatch.setattr(nt.shutil, "which", lambda b: f"/usr/sbin/{b}" if b in tools else None)
    monkeypatch.setattr(nt.subprocess, "run", fake_run)
    return calls


def test_firewall_ufw_active_via_sudo_and_nft_tables(monkeypatch):
    calls = _fake_env(monkeypatch, "Status: active\n22/tcp ALLOW", NFT_JSON)
    res = nt.firewall_status(["sudo", "-n"])
    assert res["status"] == "OK" and res["active"] is True and res["backend"] == "ufw"
    assert ["sudo", "-n", "ufw", "status"] in calls
    assert ["sudo", "-n", "nft", "-j", "list", "ruleset"] in calls
    assert {"family": "inet", "name": "windscribe", "chains": 2, "rules": 1} in res["nft_tables"]


def test_firewall_ufw_inactive_but_nft_rules_is_active(monkeypatch):
    _fake_env(monkeypatch, "Status: inactive", NFT_JSON)
    res = nt.firewall_status([])
    assert res["active"] is True and res["status"] == "OK"


def test_firewall_all_inactive_is_false(monkeypatch):
    empty = json.dumps({"nftables": [{"table": {"family": "ip", "name": "t"}}]})
    _fake_env(monkeypatch, "Status: inactive", empty)
    res = nt.firewall_status([])
    assert res["active"] is False and res["status"] == "OK"


def test_firewall_unprivileged_is_degraded_not_false_negative(monkeypatch):
    _fake_env(monkeypatch, "", None)  # `ufw status` without root prints nothing useful
    res = nt.firewall_status(None)
    assert res["status"] == "DEGRADED" and res["active"] is None
    assert "privilege" in res["reason"] and "nft_tables" not in res


def test_firewall_nft_denied_with_sudo_is_degraded(monkeypatch):
    _fake_env(monkeypatch, "Status: inactive", None)
    res = nt.firewall_status(["sudo", "-n"])
    assert res["status"] == "DEGRADED" and res["active"] is None and "nft ruleset unreadable" in res["reason"]


def test_firewall_no_tools(monkeypatch):
    _fake_env(monkeypatch, "", None, tools=())
    res = nt.firewall_status([])
    assert res["backend"] == "none" and res["active"] is False


def _ctl(**kw: Any) -> dict[str, Any]:
    kw.setdefault("verbosity", "summary")
    return json.loads(asyncio.run(server.aep_ctl(**kw)))


@pytest.fixture
def ctl_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=tmp_path / "t.db"))
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    _PrivilegeCache.reset()
    yield
    _PrivilegeCache.reset()


@pytest.mark.parametrize(("egress", "expected"), [(True, True), (False, False)])
def test_neighbors_egress_next_action_points_to_firewall_status(ctl_env, monkeypatch, egress, expected):
    async def fake_discover(*_a: Any, **_k: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"status": "OK", "neighbors": [], "count": 0, "limits": []}
        if egress:
            out["egress_blocked_suspected"] = True
        return out

    monkeypatch.setattr(nt, "discover_neighbors", fake_discover)
    res = _ctl(domain="network", action="neighbors")
    assert ("firewall_status" in res["next_action"]) is expected


# ---------------------------------------------------------------- T2 (G37): embedder sin telemetría onnxruntime


def test_embedder_disables_onnxruntime_telemetry_before_loading_model(monkeypatch):
    import sys
    import types

    from engine import embedder

    order: list[str] = []
    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.disable_telemetry_events = lambda: order.append("telemetry_off")
    fake_fe = types.ModuleType("fastembed")

    class _FakeModel:
        def __init__(self, model_name: str) -> None:
            order.append("model")

    fake_fe.TextEmbedding = _FakeModel
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)
    emb = embedder.LocalEmbedder()
    assert emb.is_available and order == ["telemetry_off", "model"]


def test_embedder_survives_missing_telemetry_api(monkeypatch):
    import sys
    import types

    from engine import embedder

    monkeypatch.setitem(sys.modules, "onnxruntime", types.ModuleType("onnxruntime"))  # sin disable_telemetry_events
    assert embedder._disable_ort_telemetry() is False


# ---------------------------------------------------------------- T3 (G38): one label for unreadable FDs


def test_unreadable_fd_label_is_unified():
    from engine import primitives
    from engine.telemetry import FD_UNREADABLE_LABEL

    assert FD_UNREADABLE_LABEL == "[unreadable]"
    assert primitives.FD_UNREADABLE_LABEL is FD_UNREADABLE_LABEL
    root = Path(server.__file__).resolve().parent
    for rel in ("server.py", "engine/primitives.py"):
        src = (root / rel).read_text()
        assert "<unreadable>" not in src and "[closed/unreachable]" not in src
