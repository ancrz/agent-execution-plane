"""ONT-41 TC4: crash_events.source, migracion idempotente e ingesta del spool plane_events_<uid>.jsonl."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from engine import crash_router as cr

REPO = Path(__file__).resolve().parent.parent
OLD_DDL = """CREATE TABLE crash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL UNIQUE, pid INTEGER, signal TEXT,
    executable TEXT, event_timestamp TEXT, coredump_info TEXT, resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""
OLD_INSERT = (
    "INSERT OR IGNORE INTO crash_events (fingerprint, pid, signal, executable, event_timestamp, coredump_info) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)


def _cols(db: Path) -> list[str]:
    with sqlite3.connect(db) as conn:
        return [r[1] for r in conn.execute("PRAGMA table_info(crash_events)")]


def _spool(tmp_path: Path, lines: list[object]) -> Path:
    d = tmp_path / "spool"
    d.mkdir(mode=0o700, exist_ok=True)
    f = d / f"plane_events_{os.geteuid()}.jsonl"
    f.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    f.chmod(0o600)
    return d


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cr.CrashRouter:
    monkeypatch.setattr(cr.shutil, "which", lambda _n: None)
    return cr.CrashRouter(db_path=tmp_path / "a.db")


def test_authoritative_schema_and_ddl_declare_source() -> None:
    assert "source TEXT DEFAULT 'coredump'" in (REPO / "schemas" / "database.sql").read_text(encoding="utf-8")
    assert "source TEXT DEFAULT 'coredump'" in cr._CRASH_DDL


def test_migration_adds_column_to_legacy_db_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(OLD_DDL)
        conn.execute(OLD_INSERT, ("fp1", 1, "SIGSEGV", "/bin/x", "t", "{}"))
    assert "source" not in _cols(db)
    cr.CrashRouter(db_path=db)
    cr.CrashRouter(db_path=db)  # idempotente
    assert _cols(db).count("source") == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT source FROM crash_events").fetchone()[0] == "coredump"


def test_old_code_still_inserts_against_new_db(router: cr.CrashRouter) -> None:
    with sqlite3.connect(router.db_path) as conn:
        conn.execute(OLD_INSERT, ("fp-old", 2, "SIGABRT", "/bin/y", "t", "{}"))
        assert conn.execute("SELECT source FROM crash_events WHERE fingerprint='fp-old'").fetchone()[0] == "coredump"
    assert router.pending_alerts()[0].get("source") is None


def test_ingest_whitelist_limits_dedup_and_enum(router: cr.CrashRouter, tmp_path: Path) -> None:
    long_err = "x" * 5000
    spool = _spool(
        tmp_path,
        [
            {"kind": "BACKEND_DROPPED", "pid": 11, "ts": "t1", "nonce": "a", "drops_in_window": 3},
            {"kind": "SWAP_FAILED", "pid": 12, "ts": "t2", "nonce": "b", "error": long_err, "evil": "'; DROP TABLE crash_events;--"},
            {"kind": "LKG_UNAVAILABLE", "pid": 13, "ts": "t3", "nonce": "c", "reason": "no_verified_lkg"},
            {"kind": "LKG_SAVED", "pid": 14, "ts": "t4", "nonce": "d"},  # fuera de la whitelist
            {"kind": "BACKEND_DROPPED", "source": "coredump", "pid": "NaN", "nonce": "e"},  # source del cliente se ignora
            "not json",
            "[1, 2]",
        ],
    )
    assert router.sync_plane_events(str(spool)) == 4
    assert router.sync_plane_events(str(spool)) == 0  # dedup por fingerprint
    with sqlite3.connect(router.db_path) as conn:
        rows = conn.execute("SELECT source, signal, coredump_info FROM crash_events ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["aep_backend", "aep_backend", "aep_front", "aep_backend"]
    assert all(r[0] in cr.CRASH_SOURCES for r in rows)
    info = json.loads(rows[1][2])
    assert len(info["error"]) == cr.PLANE_FIELD_MAX_CHARS and "evil" not in info
    alerts = router.pending_alerts()
    assert {a["source"] for a in alerts} == {"aep_backend", "aep_front"}


def test_ingest_failsoft_and_line_cap(router: cr.CrashRouter, tmp_path: Path) -> None:
    assert router.sync_plane_events(str(tmp_path / "missing_parent" / "nope")) == 0
    lines = [{"kind": "SWAP_FAILED", "pid": 1, "nonce": str(i)} for i in range(cr.PLANE_EVENT_MAX_LINES + 50)]
    assert router.sync_plane_events(str(_spool(tmp_path, lines))) == cr.PLANE_EVENT_MAX_LINES


def test_symlinked_spool_is_refused(router: cr.CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "spool"
    d.mkdir(mode=0o700)
    target = tmp_path / "real.jsonl"
    target.write_text(json.dumps({"kind": "SWAP_FAILED", "pid": 1}) + "\n", encoding="utf-8")
    (d / f"plane_events_{os.geteuid()}.jsonl").symlink_to(target)
    assert router.sync_plane_events(str(d)) == 0


def test_check_includes_plane_events(router: cr.CrashRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_FRONT_SPOOL_DIR", str(_spool(tmp_path, [{"kind": "SWAP_FAILED", "pid": 5, "nonce": "z"}])))
    res = router.check()
    assert res["new_since_last_check"] >= 1 and res["alerts"][0]["source"] == "aep_backend"
