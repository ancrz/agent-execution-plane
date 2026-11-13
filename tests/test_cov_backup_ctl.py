"""Cobertura conductual de `aep_ctl(domain="backup")` y `engine.backup` (BackupEngine, lock de concurrencia).

Todo el estado (DB, directorio de backups) vive en `tmp_path`: nunca toca la DB real de artefactos.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

import engine.backup as eb
import server
from engine.backup import BackupEngine, DatabasePoisonError, backup_concurrency_lock
from engine.privilege import BACKUP_MUTATING_ACTIONS, BACKUP_MUTATING_MIN_OCTAL, _PrivilegeCache


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """DB sqlite con una fila + defaults de engine.backup redirigidos a tmp (los usa la tool aep_ctl)."""
    db = tmp_path / "artifacts.db"
    bdir = tmp_path / "backups"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.execute("INSERT INTO t VALUES ('original')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(eb, "DB_DEFAULT_PATH", db)
    monkeypatch.setattr(eb, "BACKUPS_DEFAULT_DIR", bdir)
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    eb.clear_micro_snapshots()
    yield {"db": db, "bdir": bdir, "tmp": tmp_path}
    eb.clear_micro_snapshots()
    _PrivilegeCache.reset()


def _ctl(**kw: Any) -> dict[str, Any]:
    kw.setdefault("verbosity", "summary")
    return json.loads(asyncio.run(server.aep_ctl(**kw)))


def _rows(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT x FROM t ORDER BY rowid")]
    finally:
        conn.close()


def _mutate(db: Path, value: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute("UPDATE t SET x = ?", (value,))
    conn.commit()
    conn.close()


def _corrupt(db: Path) -> None:
    db.write_bytes(b"this is not a sqlite database" * 200)


# ---------------------------------------------------------------- aep_ctl: lecturas


@pytest.mark.parametrize("tier", ["4r--", "5r-x", "6rw-", "7rwx"])
def test_ctl_backup_status_read_at_every_tier(
    state: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()
    for res in (_ctl(domain="backup", action="status"), _ctl(domain="backup", action="backup_status")):
        assert res["status"] == "OK"
        assert res["backups_dir"] == str(state["bdir"])
        assert res["active_slots"] == 0
        assert res["max_slots"] == eb.MAX_BACKUP_SLOTS
        assert res["golden_snapshot"]["exists"] is False
        assert [s["exists"] for s in res["slots"]] == [False] * eb.MAX_BACKUP_SLOTS


_MUTATING = (
    "backup",
    "restore",
    "auto_recover",
    "verify_and_auto_recover",
    "restore_micro_snapshot",
    "golden",
    "restore_golden",
    "workspace_snapshot",
    "workspace_restore",
)


@pytest.mark.parametrize("tier", ["4r--", "5r-x"])
def test_ctl_backup_mutating_actions_denied_below_6rw(
    state: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    assert set(_MUTATING) <= set(BACKUP_MUTATING_ACTIONS)
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()
    before = eb.compute_file_sha256(state["db"])
    for action in _MUTATING:
        res = _ctl(domain="backup", action=action, name="1", target=str(state["tmp"]))
        assert res["status"] == "PERMISSION_DENIED", action
        assert res["tier"] == tier and "6rw-" in res["error"] and action in res["error"]
        assert res["next_action"]
    # cero mutacion: ni DB alterada ni backups creados
    assert eb.compute_file_sha256(state["db"]) == before
    assert not state["bdir"].exists() or not list(state["bdir"].glob("artifacts.db.*"))


@pytest.mark.parametrize("tier", ["6rw-", "7rwx"])
def test_ctl_backup_mutating_actions_allowed_at_6rw_and_above(
    state: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()
    assert _ctl(domain="backup", action="backup")["status"] == "SUCCESS"
    assert _ctl(domain="backup", action="golden")["status"] == "SUCCESS"
    assert (state["bdir"] / "artifacts.db.bak.1").exists()


@pytest.mark.parametrize("tier", ["4r--", "5r-x"])
def test_ctl_backup_read_actions_stay_open_below_6rw(
    state: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tier: str
) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    _PrivilegeCache.reset()
    assert _ctl(domain="backup", action="verify_integrity", name=str(state["db"]))["status"] == "OK"
    assert _ctl(domain="backup", action="quarantine_status")["status"] != "PERMISSION_DENIED"
    assert _ctl(domain="backup", action="list_micro_snapshots")["status"] != "PERMISSION_DENIED"
    assert _ctl(domain="backup", action="lkg_status")["status"] != "PERMISSION_DENIED"


def test_ctl_verify_integrity_never_writes_to_the_target(
    state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    _PrivilegeCache.reset()
    before = state["db"].read_bytes()
    res = _ctl(domain="backup", action="verify_integrity", name=str(state["db"]))
    assert res["status"] == "OK" and res["details"]["canary"] == "missing"  # sin canary: no se siembra
    assert state["db"].read_bytes() == before
    conn = sqlite3.connect(state["db"])
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert eb.CANARY_TABLE not in tables
    # una DB con canary alterado sigue siendo detectada
    conn = sqlite3.connect(state["db"])
    eb.ensure_canary(conn)
    conn.execute("UPDATE _aep_canary SET canary_token = 'forged'")
    conn.commit()
    conn.close()
    bad = _ctl(domain="backup", action="verify_integrity", name=str(state["db"]))
    assert bad["status"] == "INTEGRITY_FAILED" and bad["reason"] == "CANARY_CORRUPTED"


def test_ctl_schema_advertises_min_chmod_for_mutating_backup_actions() -> None:
    detail = _ctl(action="schema", verbosity="detail")["domains"]["backup"]["preconditions"]
    for act in BACKUP_MUTATING_ACTIONS:
        assert detail[act]["min_chmod_octal"] == 6
    for act in ("status", "backup_status", "verify_integrity", "lkg_status", "lkg_diff"):
        assert "min_chmod_octal" not in detail[act]


def test_ctl_unknown_backup_action_is_rejected_with_valid_list(state: dict[str, Any]) -> None:
    res = _ctl(domain="backup", action="nope")
    assert res["status"] == "ERROR"
    assert "backup" in res["error"]
    assert "backup" in res["valid"] and "verify_integrity" in res["valid"]


def test_ctl_verify_integrity_healthy_and_corrupted_copy(state: dict[str, Any]) -> None:
    ok = _ctl(domain="backup", action="verify_integrity", name=str(state["db"]))
    assert ok["status"] == "OK" and ok["valid"] is True and ok["reason"] == "HEALTHY"
    assert ok["details"]["user_tables"] == 1

    copy = state["tmp"] / "copy.db"
    _corrupt(copy)
    bad = _ctl(domain="backup", action="verify_integrity", name=str(copy))
    assert bad["status"] == "INTEGRITY_FAILED"
    assert bad["valid"] is False
    assert bad["reason"] != "HEALTHY"

    missing = _ctl(domain="backup", action="verify_integrity", name=str(state["tmp"] / "absent.db"))
    assert missing["status"] == "INTEGRITY_FAILED" and missing["reason"] == "FILE_NOT_FOUND"


# ---------------------------------------------------------------- aep_ctl: backup / restore


def test_ctl_backup_creates_slot_and_status_reflects_it(state: dict[str, Any]) -> None:
    res = _ctl(domain="backup", action="backup")
    assert res["status"] == "SUCCESS" and res["slot"] == 1
    slot_file = state["bdir"] / "artifacts.db.bak.1"
    assert slot_file.exists()
    assert res["sha256"] == eb.compute_file_sha256(slot_file)
    st = _ctl(domain="backup", action="status")
    assert st["active_slots"] == 1
    assert st["slots"][0]["exists"] is True and st["slots"][0]["sha256"] == res["sha256"]


def test_ctl_restore_roundtrip_recovers_original_content(state: dict[str, Any]) -> None:
    assert _ctl(domain="backup", action="backup")["status"] == "SUCCESS"
    _mutate(state["db"], "changed")
    assert _rows(state["db"]) == ["changed"]
    res = _ctl(domain="backup", action="restore", name="1")
    assert res["status"] == "SUCCESS" and res["integrity_verified"] is True
    assert _rows(state["db"]) == ["original"]


def test_ctl_restore_param_and_missing_slot_errors(state: dict[str, Any]) -> None:
    bad = _ctl(domain="backup", action="restore", name="abc")
    assert bad["status"] == "ERROR" and bad["valid"] == "1..5"
    assert _ctl(domain="backup", action="restore", name="9")["status"] == "INVALID_SLOT"
    assert _ctl(domain="backup", action="restore", name="3")["status"] == "BACKUP_NOT_FOUND"
    assert _rows(state["db"]) == ["original"]


# ---------------------------------------------------------------- aep_ctl: golden


def test_ctl_golden_then_restore_golden_roundtrip(state: dict[str, Any]) -> None:
    assert _ctl(domain="backup", action="restore_golden")["status"] == "GOLDEN_NOT_FOUND"
    gold = _ctl(domain="backup", action="golden")
    assert gold["status"] == "SUCCESS"
    assert gold["sha256"] == eb.compute_file_sha256(state["bdir"] / eb.GOLDEN_FILENAME)
    assert _ctl(domain="backup", action="status")["golden_snapshot"]["exists"] is True
    _mutate(state["db"], "changed")
    res = _ctl(domain="backup", action="restore_golden")
    assert res["status"] == "SUCCESS" and res["restored_from"] == eb.GOLDEN_FILENAME
    assert _rows(state["db"]) == ["original"]


def test_ctl_restore_golden_rejects_corrupted_golden(state: dict[str, Any]) -> None:
    _ctl(domain="backup", action="golden")
    _corrupt(state["bdir"] / eb.GOLDEN_FILENAME)
    _mutate(state["db"], "changed")
    res = _ctl(domain="backup", action="restore_golden")
    assert res["status"] == "CORRUPTED_GOLDEN"
    assert _rows(state["db"]) == ["changed"]  # el DB vivo no se sobrescribe con un golden corrupto


# ---------------------------------------------------------------- aep_ctl: auto-recover


def test_ctl_auto_recover_healthy_is_noop(state: dict[str, Any]) -> None:
    for res in (
        _ctl(domain="backup", action="auto_recover"),
        _ctl(domain="backup", action="verify_and_auto_recover"),
    ):
        assert res["status"] == "HEALTHY" and res["recovered"] is False
    assert _rows(state["db"]) == ["original"]


def test_ctl_auto_recover_restores_latest_valid_slot(state: dict[str, Any]) -> None:
    _ctl(domain="backup", action="backup")
    _corrupt(state["db"])
    res = _ctl(domain="backup", action="auto_recover")
    assert res["status"] == "AUTO_RECOVERED" and res["restored_from_slot"] == 1
    assert _rows(state["db"]) == ["original"]
    # la DB corrupta queda aislada en cuarentena, no borrada
    assert _ctl(domain="backup", action="quarantine_status")["count"] >= 1


def test_ctl_verify_and_auto_recover_alias_restores_from_slot(state: dict[str, Any]) -> None:
    _ctl(domain="backup", action="backup")
    _corrupt(state["db"])
    res = _ctl(domain="backup", action="verify_and_auto_recover")
    assert res["status"] == "AUTO_RECOVERED" and res["integrity_verified"] is True
    assert _rows(state["db"]) == ["original"]


def test_ctl_auto_recover_without_any_slot_fails_soft(state: dict[str, Any]) -> None:
    _corrupt(state["db"])
    res = _ctl(domain="backup", action="auto_recover")
    assert res["status"] == "AUTO_RECOVER_FAILED" and res["recovered"] is False


# ---------------------------------------------------------------- aep_ctl: micro snapshots


def test_ctl_restore_micro_snapshot_roundtrip_and_not_found(state: dict[str, Any]) -> None:
    miss = _ctl(domain="backup", action="restore_micro_snapshot", name="ghost")
    assert miss["status"] == "SNAPSHOT_NOT_FOUND"
    snap = _ctl(domain="backup", action="micro_snapshot", name="pre_edit")
    assert snap["status"] == "SUCCESS" and snap["in_ram"] is True
    _mutate(state["db"], "changed")
    res = _ctl(domain="backup", action="restore_micro_snapshot", name="pre_edit")
    assert res["status"] == "SUCCESS" and res["restored"] is True
    assert _rows(state["db"]) == ["original"]
    # el snapshot es volatil (RAM): no deja archivos nuevos en el directorio de backups
    assert not list(state["bdir"].glob("*pre_edit*"))


# ---------------------------------------------------------------- aep_ctl: workspace_restore / snapshot


def test_ctl_workspace_restore_blacklist_notfound_and_missing_snapshot(state: dict[str, Any]) -> None:
    denied = _ctl(domain="backup", action="workspace_restore", target="~/.ssh")
    assert denied["status"] == "PERMISSION_DENIED"
    gone = _ctl(domain="backup", action="workspace_restore", target=str(state["tmp"] / "nodir"))
    assert gone["status"] == "NOT_FOUND"
    res = _ctl(domain="backup", action="workspace_restore", target=str(state["tmp"]), name="cov-no-such-snapshot-x9")
    assert res["status"] == "SNAPSHOT_NOT_FOUND"
    assert "cov-no-such-snapshot-x9" in res["error"]


def test_ctl_workspace_snapshot_blacklist_denied(state: dict[str, Any]) -> None:
    assert _ctl(domain="backup", action="workspace_snapshot", target="~/.ssh")["status"] == "PERMISSION_DENIED"


# ---------------------------------------------------------------- engine.backup: BackupEngine


def _engine(state: dict[str, Any]) -> BackupEngine:
    return BackupEngine(db_path=state["db"], backups_dir=state["bdir"])


def _first_value(db: Path) -> str:
    conn = sqlite3.connect(db)
    try:
        return str(conn.execute("SELECT x FROM t").fetchone()[0])
    finally:
        conn.close()


def test_engine_create_backup_fifo_rotation_caps_at_max_slots(state: dict[str, Any]) -> None:
    engine = _engine(state)
    for i in range(eb.MAX_BACKUP_SLOTS + 2):
        _mutate(state["db"], f"v{i}")
        assert BackupEngine.create_backup(engine)["status"] == "SUCCESS"
    files = sorted(p.name for p in state["bdir"].glob("artifacts.db.bak.*"))
    # solo los 5 slots: ni staging ni sidecars -wal/-shm sobreviven
    assert files == [f"artifacts.db.bak.{i}" for i in range(1, eb.MAX_BACKUP_SLOTS + 1)]
    assert BackupEngine.get_backup_status(engine)["active_slots"] == eb.MAX_BACKUP_SLOTS
    # slot 1 = el mas reciente, slot 5 = el mas antiguo conservado (v2)
    assert _first_value(state["bdir"] / "artifacts.db.bak.1") == f"v{eb.MAX_BACKUP_SLOTS + 1}"
    assert _first_value(state["bdir"] / f"artifacts.db.bak.{eb.MAX_BACKUP_SLOTS}") == "v2"


def test_engine_create_backup_missing_source_and_poison(state: dict[str, Any]) -> None:
    engine = BackupEngine(db_path=state["tmp"] / "absent.db", backups_dir=state["bdir"])
    assert BackupEngine.create_backup(engine)["status"] == "SOURCE_NOT_FOUND"

    _corrupt(state["db"])
    soft = BackupEngine.create_backup(_engine(state), raise_on_poison=False)
    assert soft["status"] == "POISON_DETECTED" and soft["quarantined"] is True
    assert not (state["bdir"] / "artifacts.db.bak.1").exists()  # nada promovido
    _corrupt(state["db"])  # la cuarentena movio el original: se recrea corrupto
    with pytest.raises(DatabasePoisonError):
        BackupEngine.create_backup(_engine(state))


def test_engine_restore_backup_validates_slot_and_corruption(state: dict[str, Any]) -> None:
    engine = _engine(state)
    assert BackupEngine.restore_backup(engine, slot_number=0)["status"] == "INVALID_SLOT"
    assert BackupEngine.restore_backup(engine, slot_number=eb.MAX_BACKUP_SLOTS + 1)["status"] == "INVALID_SLOT"
    assert BackupEngine.restore_backup(engine, slot_number=2)["status"] == "BACKUP_NOT_FOUND"
    BackupEngine.create_backup(engine)
    _corrupt(state["bdir"] / "artifacts.db.bak.1")
    _mutate(state["db"], "changed")
    assert BackupEngine.restore_backup(engine, slot_number=1)["status"] == "CORRUPTED_BACKUP"
    assert _rows(state["db"]) == ["changed"]


def test_engine_restore_backup_purges_stale_wal_and_shm(state: dict[str, Any]) -> None:
    engine = _engine(state)
    BackupEngine.create_backup(engine)
    wal = state["db"].parent / f"{state['db'].name}-wal"
    shm = state["db"].parent / f"{state['db'].name}-shm"
    wal.write_bytes(b"stale")
    shm.write_bytes(b"stale")
    res = BackupEngine.restore_backup(engine, slot_number=1)
    assert res["status"] == "SUCCESS"
    assert not wal.exists() and not shm.exists()
    assert _rows(state["db"]) == ["original"]


def test_engine_golden_snapshot_create_and_restore(state: dict[str, Any]) -> None:
    engine = _engine(state)
    assert BackupEngine.restore_golden_snapshot(engine)["status"] == "GOLDEN_NOT_FOUND"
    created = BackupEngine.create_golden_snapshot(engine)
    assert created["status"] == "SUCCESS"
    assert BackupEngine.get_backup_status(engine)["golden_snapshot"]["details"]["sha256"] == created["sha256"]
    _mutate(state["db"], "changed")
    assert BackupEngine.restore_golden_snapshot(engine)["status"] == "SUCCESS"
    assert _rows(state["db"]) == ["original"]


def test_engine_golden_refuses_corrupted_source(state: dict[str, Any]) -> None:
    _corrupt(state["db"])
    with pytest.raises(DatabasePoisonError):
        BackupEngine.create_golden_snapshot(_engine(state))
    assert not (state["bdir"] / eb.GOLDEN_FILENAME).exists()


def test_engine_verify_and_auto_recover_missing_db_uses_slot(state: dict[str, Any]) -> None:
    engine = _engine(state)
    BackupEngine.create_backup(engine)
    state["db"].unlink()
    res = BackupEngine.verify_and_auto_recover(engine)
    assert res["status"] == "AUTO_RECOVERED" and res["integrity_verified"] is True
    assert _rows(state["db"]) == ["original"]


def test_engine_verify_and_auto_recover_skips_corrupted_slot(state: dict[str, Any]) -> None:
    engine = _engine(state)
    BackupEngine.create_backup(engine)  # -> slot 1 (original)
    _mutate(state["db"], "second")
    BackupEngine.create_backup(engine)  # -> slot 1 = second, slot 2 = original
    _corrupt(state["bdir"] / "artifacts.db.bak.1")
    _corrupt(state["db"])
    res = BackupEngine.verify_and_auto_recover(engine)
    assert res["status"] == "AUTO_RECOVERED" and res["restored_from_slot"] == 2
    assert _rows(state["db"]) == ["original"]


def test_engine_get_backup_status_counts_quarantine(state: dict[str, Any]) -> None:
    engine = _engine(state)
    assert BackupEngine.get_backup_status(engine)["quarantine"]["count"] == 0
    _corrupt(state["db"])
    BackupEngine.create_backup(engine, raise_on_poison=False)
    assert BackupEngine.get_backup_status(engine)["quarantine"]["count"] == 1


# ---------------------------------------------------------------- backup_concurrency_lock


def test_backup_concurrency_lock_blocks_second_backup_until_released(state: dict[str, Any]) -> None:
    engine = _engine(state)
    result: dict[str, Any] = {}
    done = threading.Event()

    def worker() -> None:
        result["res"] = BackupEngine.create_backup(engine)
        done.set()

    with backup_concurrency_lock(state["bdir"]):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        assert not done.wait(0.4), "create_backup no debe avanzar mientras otro proceso retiene el lock"
        assert not (state["bdir"] / "artifacts.db.bak.1").exists()
    assert done.wait(4.0)
    t.join(1.0)
    assert result["res"]["status"] == "SUCCESS"
    assert (state["bdir"] / "artifacts.db.bak.1").exists()


def test_backup_concurrency_lock_creates_dir_and_releases(state: dict[str, Any]) -> None:
    target = state["tmp"] / "fresh" / "dir"
    with backup_concurrency_lock(target):
        assert (target / eb.LOCK_FILENAME).exists()
    # reentrada tras liberar: no se bloquea
    with backup_concurrency_lock(target):
        pass


def test_ctl_schema_summary_folds_shared_backup_tier_exceptions_within_budget() -> None:
    """D-04: las 10 acciones mutantes comparten min_chmod_octal=6; en summary van plegadas una sola vez."""
    summary = _ctl(action="schema", verbosity="summary")
    backup = summary["domains"]["backup"]
    shared = backup.get("shared_exceptions") or []
    group = next(g for g in shared if g.get("min_chmod_octal") == BACKUP_MUTATING_MIN_OCTAL)
    assert set(group["actions"]) == set(BACKUP_MUTATING_ACTIONS)
    assert not any("min_chmod_octal" in v for v in (backup.get("exceptions") or {}).values())
    assert summary["t"]["tok"] < 1500
