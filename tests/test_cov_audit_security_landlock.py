"""Cobertura conductual de `aep_ctl(domain="audit"|"security")` y `engine.landlock.LandlockSandbox`.

El catalogo de auditoria se redirige a una DB temporal; el confinamiento Landlock irrevocable solo se aplica en
procesos hijo (fork), nunca en el proceso de pytest.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

import server
from engine import landlock
from engine.catalog import ArtifactCatalog
from engine.landlock import LandlockSandbox, get_landlock_status
from engine.privilege import _PrivilegeCache
from engine.security import record_audit_event

_SUPPORTED = bool(get_landlock_status().get("supported"))
needs_landlock = pytest.mark.skipif(not _SUPPORTED, reason="Landlock LSM no soportado por el kernel del host")


@pytest.fixture
def audit_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cat = ArtifactCatalog(db_path=tmp_path / "audit.db")
    monkeypatch.setattr(server, "catalog", cat)
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    _PrivilegeCache.reset()
    yield cat.db_path
    _PrivilegeCache.reset()


def _ctl(**kw: Any) -> dict[str, Any]:
    kw.setdefault("verbosity", "summary")
    return json.loads(asyncio.run(server.aep_ctl(**kw)))


def _seed(db: Path, n: int, session: str = "s1") -> list[str]:
    conn = sqlite3.connect(db)
    try:
        hashes = []
        for i in range(n):
            res = record_audit_event(
                conn,
                agent_id="agent-a" if i % 2 == 0 else "agent-b",
                tool_name="aep_ctl",
                action="backup.status",
                capability_tier="4r--",
                status="OK",
                details={"session_id": session, "output_bytes": 400, "latency_ms": 1.5},
            )
            hashes.append(res["entry_hash"])
        conn.commit()
        return hashes
    finally:
        conn.close()


# ---------------------------------------------------------------- audit


def test_ctl_verify_valid_chain_reports_blocks(audit_db: Path) -> None:
    _seed(audit_db, 3)
    for res in (_ctl(domain="audit", action="verify"), _ctl(domain="security", action="verify")):
        assert res["status"] == "OK" and res["valid"] is True
        assert res["total_verified"] >= 3  # la telemetria de la propia llamada puede anadir bloques
        assert res["latest_hash"]


def test_ctl_audit_verify_detects_tampering_with_broken_row(audit_db: Path) -> None:
    _seed(audit_db, 4)
    conn = sqlite3.connect(audit_db)
    victim = conn.execute("SELECT id FROM security_audit_log ORDER BY id LIMIT 1 OFFSET 1").fetchone()[0]
    conn.execute("UPDATE security_audit_log SET status = 'FORGED' WHERE id = ?", (victim,))
    conn.commit()
    conn.close()
    for res in (_ctl(domain="audit", action="verify"), _ctl(domain="security", action="verify")):
        assert res["status"] == "INTEGRITY_FAILED" and res["valid"] is False
        assert res["broken_row_id"] == victim
        assert "Manipulaci" in res["error"]


def test_ctl_audit_verify_detects_broken_link(audit_db: Path) -> None:
    _seed(audit_db, 3)
    conn = sqlite3.connect(audit_db)
    victim = conn.execute("SELECT id FROM security_audit_log ORDER BY id LIMIT 1 OFFSET 2").fetchone()[0]
    conn.execute("UPDATE security_audit_log SET prev_hash = 'deadbeef' WHERE id = ?", (victim,))
    conn.commit()
    conn.close()
    res = _ctl(domain="audit", action="verify")
    assert res["status"] == "INTEGRITY_FAILED" and res["broken_row_id"] == victim
    assert "Enlace roto" in res["error"]


def test_ctl_audit_usage_aggregates_by_agent_and_session(audit_db: Path) -> None:
    _seed(audit_db, 4, session="alpha")
    _seed(audit_db, 2, session="beta")
    scoped = _ctl(domain="audit", action="usage", name="alpha")
    assert scoped["status"] == "OK" and scoped["session_id"] == "alpha"
    assert scoped["total_calls"] == 4
    assert scoped["agents"]["agent-a"]["calls"] == 2 and scoped["agents"]["agent-b"]["calls"] == 2
    assert scoped["agents"]["agent-a"]["bytes"] == 800 and scoped["agents"]["agent-a"]["tokens"] == 200
    assert scoped["agents"]["agent-a"]["tools"]["aep_ctl"]["actions"] == {"backup.status": 2}
    unscoped = _ctl(domain="audit", action="usage")
    assert unscoped["session_id"] is None and unscoped["total_calls"] >= 6
    assert _ctl(domain="audit", action="usage", name="nobody")["total_calls"] == 0


def test_ctl_audit_rejects_unknown_action(audit_db: Path) -> None:
    res = _ctl(domain="audit", action="purge")
    assert res["status"] == "ERROR" and "purge" in res["error"]
    assert {"usage", "verify"} <= set(res["valid"])


# ---------------------------------------------------------------- security


def test_ctl_security_status_and_landlock_status_match_kernel(audit_db: Path) -> None:
    kernel = get_landlock_status()
    for res in (_ctl(domain="security", action="status"), _ctl(domain="security", action="landlock_status")):
        assert res["status"] == kernel["status"]
        assert res["supported"] is kernel["supported"]
        assert res["abi_version"] == kernel["abi_version"]
    if _SUPPORTED:
        assert res["features"]["v1_basic"] is True


def test_ctl_security_threat_mitigate_requires_target(audit_db: Path) -> None:
    res = _ctl(domain="security", action="threat_mitigate")
    assert res["status"] == "ERROR" and "target_ip" in res["error"]


def test_ctl_security_firewall_status_backends(audit_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert cmd == ["ufw", "status"]
        return subprocess.CompletedProcess(cmd, 0, stdout="Status: active\n22/tcp ALLOW", stderr="")

    monkeypatch.setattr(server.shutil, "which", lambda b: f"/usr/sbin/{b}" if b in ("ufw", "nft") else None)
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    ufw = _ctl(domain="security", action="firewall_status")
    assert ufw["backend"] == "ufw" and ufw["active"] is True and "22/tcp" in ufw["stdout"]

    monkeypatch.setattr(server.shutil, "which", lambda b: "/usr/sbin/nft" if b == "nft" else None)
    assert _ctl(domain="security", action="firewall_status")["backend"] == "nftables"

    monkeypatch.setattr(server.shutil, "which", lambda b: None)
    none = _ctl(domain="security", action="firewall_status")
    assert none["backend"] == "none" and none["active"] is False


def test_ctl_security_nftables_inspect_paths(audit_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.shutil, "which", lambda b: None)
    assert _ctl(domain="security", action="nftables_inspect")["status"] == "DEGRADED"

    calls: list[list[str]] = []
    out = "table inet filter {\n  chain input {\n  }\n}\n"

    def fake_ok(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(server.shutil, "which", lambda b: "/usr/sbin/nft")
    monkeypatch.setattr(server, "privilege_prefix", lambda: [])
    monkeypatch.setattr(server.subprocess, "run", fake_ok)
    ok = _ctl(domain="security", action="nftables_inspect")
    assert ok["status"] == "OK" and ok["rules_count"] == 4
    assert calls[-1] == ["nft", "list", "ruleset"]

    def fake_denied(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Operation not permitted")

    monkeypatch.setattr(server.subprocess, "run", fake_denied)
    denied = _ctl(domain="security", action="nftables_inspect")
    assert denied["status"] == "DEGRADED" and "not permitted" in denied["stderr"]


# ---------------------------------------------------------------- landlock: configuracion de rutas


def test_landlock_add_paths_resolves_and_deduplicates(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    sandbox = LandlockSandbox()
    sandbox.add_read_path(link)
    sandbox.add_read_path(real)  # mismo destino resuelto -> sin duplicado
    sandbox.add_write_path(str(real))
    sandbox.add_write_path(real)
    assert sandbox.allowed_read_paths == [real.resolve()]
    assert sandbox.allowed_write_paths == [real.resolve()]


def test_landlock_constructor_aliases_and_precedence(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    s = LandlockSandbox(allowed_read_paths=[a], read_paths=[b], write_paths=[b])
    assert s.allowed_read_paths == [a.resolve()]  # allowed_* gana sobre el alias
    assert s.allowed_write_paths == [b.resolve()]


def test_landlock_apply_unsupported_does_not_restrict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(landlock, "get_landlock_status", lambda: {"supported": False, "message": "nope"})
    res = LandlockSandbox(read_paths=["/"]).apply()
    assert res == {"status": "UNSUPPORTED", "applied": False, "error": "nope"}


# ---------------------------------------------------------------- landlock: confinamiento real (en hijo)


def _apply_in_child(sandbox: LandlockSandbox, target: Path) -> dict[str, Any]:
    """Aplica el sandbox en un hijo fork y devuelve resultado de apply() + intento de escritura en `target`."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        out: dict[str, Any] = {"apply": sandbox.apply()}
        try:
            target.write_text("x", encoding="utf-8")
            out["wrote"] = True
        except OSError as e:
            out["wrote"] = False
            out["errno"] = e.errno
        os.write(w, json.dumps(out).encode())
        os._exit(0)
    os.close(w)
    data = b""
    while chunk := os.read(r, 4096):
        data += chunk
    os.close(r)
    os.waitpid(pid, 0)
    return json.loads(data)


@needs_landlock
def test_landlock_apply_confines_writes_to_allowed_paths(tmp_path: Path) -> None:
    allowed, denied = tmp_path / "allowed", tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    ok = _apply_in_child(LandlockSandbox(read_paths=["/"], write_paths=[allowed]), allowed / "f.txt")
    assert ok["apply"]["status"] == "APPLIED" and ok["apply"]["applied"] is True
    assert ok["apply"]["rules_added"] >= 2
    assert ok["wrote"] is True and (allowed / "f.txt").read_text(encoding="utf-8") == "x"

    blocked = _apply_in_child(LandlockSandbox(read_paths=["/"], write_paths=[allowed]), denied / "f.txt")
    assert blocked["apply"]["applied"] is True
    assert blocked["wrote"] is False and blocked["errno"] == 13  # EACCES
    assert not (denied / "f.txt").exists()


@needs_landlock
def test_landlock_apply_skips_nonexistent_paths(tmp_path: Path) -> None:
    sandbox = LandlockSandbox(read_paths=["/", tmp_path / "ghost"], write_paths=[tmp_path / "ghost-w"])
    res = _apply_in_child(sandbox, tmp_path / "f.txt")
    assert res["apply"]["applied"] is True
    assert res["apply"]["rules_added"] == 1  # solo "/" existe


@needs_landlock
def test_landlock_add_write_path_enables_write_in_child(tmp_path: Path) -> None:
    target_dir = tmp_path / "later"
    target_dir.mkdir()
    sandbox = LandlockSandbox()
    sandbox.add_read_path("/")
    before = _apply_in_child(sandbox, target_dir / "f.txt")
    assert before["wrote"] is False
    sandbox.add_write_path(target_dir)
    after = _apply_in_child(sandbox, target_dir / "f.txt")
    assert after["wrote"] is True


@needs_landlock
def test_landlock_run_isolated_probe_reports_blocked_and_allowed(tmp_path: Path) -> None:
    allowed, denied = tmp_path / "allowed", tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    sandbox = LandlockSandbox(read_paths=["/"], write_paths=[allowed])
    blocked = LandlockSandbox.run_isolated_probe(sandbox, denied / "probe.txt")
    assert blocked["enforced"] is True and blocked["write_blocked"] is True
    assert blocked["apply_status"]["status"] == "APPLIED"
    assert not (denied / "probe.txt").exists()
    allowed_res = LandlockSandbox.run_isolated_probe(sandbox, allowed / "probe.txt")
    assert allowed_res["write_blocked"] is False and (allowed / "probe.txt").read_text(encoding="utf-8") == "probe_test"
    # el padre (pytest) NO quedo confinado
    (denied / "parent.txt").write_text("ok", encoding="utf-8")


def test_landlock_run_isolated_probe_unsupported_reports_not_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(landlock, "get_landlock_status", lambda: {"supported": False, "message": "off"})
    res = LandlockSandbox.run_isolated_probe(LandlockSandbox(read_paths=["/"]), tmp_path / "p.txt")
    assert res["enforced"] is False and res["supported"] is False
    assert res["apply_status"]["status"] == "UNSUPPORTED"
    assert res["write_blocked"] is False  # sin confinamiento la escritura prospera
    assert (tmp_path / "p.txt").read_text(encoding="utf-8") == "probe_test"
