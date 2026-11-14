"""ONT-59 T1/K1: la evidencia y la promoción pertenecen a (source_hash, toolchain), no a un nombre."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import server
from engine import catalog as catalog_mod
from engine import go_toolchain
from engine.catalog import ArtifactCatalog
from engine.kanban import KanbanBoard
from engine.privilege import _PrivilegeCache

GO = shutil.which("go")
H1, H2 = "a" * 64, "b" * 64
TC1, TC2 = "go1.27.4", "go1.26.11"


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    return tmp_path / "artifacts.db"


def _promote_by_hand(board: KanbanBoard, task_id: int) -> None:
    with board._conn_rw() as conn:
        conn.execute("UPDATE kanban_tasks SET state='PROMOTED', canary_passed=1 WHERE id=?", (task_id,))


def _card(board: KanbanBoard, task_id: int) -> sqlite3.Row:
    with board._conn_ro() as conn:
        return conn.execute("SELECT * FROM kanban_tasks WHERE id=?", (task_id,)).fetchone()


# --------------------------------------------------------------------------- kanban
def test_new_card_is_generation_one(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    r = b.upsert_build_task("probe", H1, TC1, intent="i", category="c")
    assert (r["cached"], r["generation"], r["attempts"], r["state"]) == (False, 1, 1, "LINTED")
    row = _card(b, r["task_id"])
    assert (row["source_hash"], row["toolchain"], row["generation"]) == (H1, TC1, 1)


def test_same_inputs_is_cache_hit_and_state_is_untouched(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    tid = b.upsert_build_task("probe", H1, TC1)["task_id"]
    _promote_by_hand(b, tid)
    before = _card(b, tid)["attempts"]
    r = b.upsert_build_task("probe", H1, TC1)
    assert r["cached"] is True and r["task_id"] == tid
    assert r["state"] == "PROMOTED" and r["attempts"] == before and r["generation"] == 1
    assert "demoted_from" not in r
    row = _card(b, tid)
    assert (row["state"], row["canary_passed"], row["attempts"]) == ("PROMOTED", 1, before)


def test_new_source_over_promoted_starts_new_generation_without_inheriting(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    tid = b.upsert_build_task("probe", H1, TC1)["task_id"]
    _promote_by_hand(b, tid)
    r = b.upsert_build_task("probe", H2, TC1)
    assert r["cached"] is False and r["task_id"] == tid and r["generation"] == 2
    assert r["state"] == "LINTED" and r["demoted_from"] == "PROMOTED" and r["reason"] == "source_changed"
    row = _card(b, tid)
    assert (row["state"], row["canary_passed"], row["source_hash"], row["generation"]) == ("LINTED", 0, H2, 2)


def test_new_source_over_canary_reports_demoted_from_canary(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    tid = b.upsert_build_task("probe", H1, TC1)["task_id"]
    with b._conn_rw() as conn:
        conn.execute("UPDATE kanban_tasks SET state='CANARY', canary_passed=1 WHERE id=?", (tid,))
    r = b.upsert_build_task("probe", H2, TC1)
    assert r["demoted_from"] == "CANARY" and r["state"] == "LINTED"


def test_new_source_over_linted_has_no_demoted_from(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    b.upsert_build_task("probe", H1, TC1)
    r = b.upsert_build_task("probe", H2, TC1)
    assert r["generation"] == 2 and "demoted_from" not in r and r["attempts"] == 2


def test_toolchain_change_is_a_new_generation(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    tid = b.upsert_build_task("probe", H1, TC1)["task_id"]
    _promote_by_hand(b, tid)
    r = b.upsert_build_task("probe", H1, TC2)
    assert r["cached"] is False and r["generation"] == 2
    assert r["demoted_from"] == "PROMOTED" and r["reason"] == "toolchain_changed"
    assert _card(b, tid)["toolchain"] == TC2


def test_legacy_card_without_hash_is_not_trusted(db: Path) -> None:
    b = KanbanBoard(db_path=db)
    with b._conn_rw() as conn:
        conn.execute(
            "INSERT INTO kanban_tasks (title, artifact_name, state, lint_passed, canary_passed, attempts) "
            "VALUES ('build:old', 'old', 'PROMOTED', 1, 1, 3)"
        )
    r = b.upsert_build_task("old", H1, TC1)
    assert r["cached"] is False and r["demoted_from"] == "PROMOTED" and r["reason"] == "source_changed"
    assert r["generation"] == 1 and r["state"] == "LINTED"


def test_migration_is_idempotent_and_adds_columns(tmp_path: Path) -> None:
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE kanban_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, intent TEXT, "
        "category TEXT, artifact_name TEXT, state TEXT NOT NULL DEFAULT 'BACKLOG', "
        "lint_passed INTEGER NOT NULL DEFAULT 0, canary_passed INTEGER NOT NULL DEFAULT 0, "
        "attempts INTEGER NOT NULL DEFAULT 0, promotion_score REAL NOT NULL DEFAULT 0.0, "
        "archived INTEGER NOT NULL DEFAULT 0, agent_id TEXT NOT NULL DEFAULT 'default', note TEXT, "
        "description TEXT, refs TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)"
    )
    conn.execute("INSERT INTO kanban_tasks (title, state, attempts) VALUES ('legacy', 'LINTED', 2)")
    conn.commit()
    conn.close()
    KanbanBoard(db_path=old)
    KanbanBoard(db_path=old)
    conn = sqlite3.connect(old)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(kanban_tasks)")}
    assert {"source_hash", "toolchain", "generation"} <= cols
    assert conn.execute("SELECT title, state, attempts, source_hash, generation FROM kanban_tasks").fetchall() == [
        ("legacy", "LINTED", 2, None, 0)
    ]
    conn.close()


# --------------------------------------------------------------------------- catalog
def _reg(cat: ArtifactCatalog, src: str = "package main\n", blob: bytes = b"\x7fELF1", **kw: object) -> str:
    return cat.register_artifact(
        name="probe", intent="i", category="c", cue_contract="{}", go_source=src, binary_blob=blob, **kw
    )


def _art(cat: ArtifactCatalog) -> sqlite3.Row:
    with cat._get_ro_conn() as conn:
        return conn.execute("SELECT * FROM artifacts WHERE name='probe'").fetchone()


def test_register_unchanged_keeps_stats_and_updated_at(db: Path) -> None:
    cat = ArtifactCatalog(db_path=db)
    aid = _reg(cat, source_hash=H1, toolchain=TC1)
    cat.record_execution(aid, 0, 5.0)
    with cat._get_rw_conn() as conn:
        conn.execute("UPDATE artifacts SET updated_at='2020-01-01 00:00:00' WHERE name='probe'")
    _reg(cat, source_hash=H1, toolchain=TC1)
    row = _art(cat)
    assert row["execution_count"] == 1 and row["success_rate"] == 1.0
    assert row["updated_at"] == "2020-01-01 00:00:00" and row["previous_stats"] is None
    assert row["source_hash"] == H1 and row["toolchain"] == TC1


def test_register_changed_binary_archives_previous_stats_and_resets(db: Path) -> None:
    cat = ArtifactCatalog(db_path=db)
    aid = _reg(cat, source_hash=H1, toolchain=TC1)
    for code in (0, 1, 0, 0):
        cat.record_execution(aid, code, 5.0)
    assert _art(cat)["execution_count"] == 4
    _reg(cat, src="package main\n// v2\n", blob=b"\x7fELF2", source_hash=H2, toolchain=TC1)
    row = _art(cat)
    assert (row["execution_count"], row["success_rate"], row["promotion_score"]) == (0, 1.0, 0.0)
    prev = json.loads(row["previous_stats"])
    assert prev["source_hash"] == H1 and prev["execution_count"] == 4 and prev["success_rate"] == 0.75
    assert prev["updated_at"] and prev["toolchain"] == TC1
    assert row["source_hash"] == H2


def test_old_executions_do_not_resurrect_after_reset(db: Path) -> None:
    cat = ArtifactCatalog(db_path=db)
    aid = _reg(cat, source_hash=H1)
    for _ in range(3):
        cat.record_execution(aid, 1, 5.0)  # la generación vieja fallaba
    _reg(cat, blob=b"\x7fELF2", source_hash=H2)
    cat.record_execution(aid, 0, 5.0)
    row = _art(cat)
    assert (row["execution_count"], row["success_rate"]) == (1, 1.0)


def test_register_toolchain_change_resets(db: Path) -> None:
    cat = ArtifactCatalog(db_path=db)
    aid = _reg(cat, source_hash=H1, toolchain=TC1)
    cat.record_execution(aid, 0, 5.0)
    _reg(cat, source_hash=H1, toolchain=TC2)
    row = _art(cat)
    assert row["execution_count"] == 0 and json.loads(row["previous_stats"])["execution_count"] == 1


def test_register_without_blob_never_resets_binary_evidence(db: Path) -> None:
    """Re-seed sin binario (ONT-18 anti-cascada) con la misma fuente no es un cambio de código."""
    cat = ArtifactCatalog(db_path=db)
    aid = _reg(cat)
    cat.record_execution(aid, 0, 5.0)
    _reg(cat, blob=None)
    assert _art(cat)["execution_count"] == 1


def test_catalog_migration_adds_columns_idempotently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    p = tmp_path / "c.db"
    ArtifactCatalog(db_path=p)
    ArtifactCatalog(db_path=p)
    with sqlite3.connect(p) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(artifacts)")}
    assert {"source_hash", "toolchain", "previous_stats", "metrics_floor"} <= cols


# --------------------------------------------------------------------------- server (Go real)
@pytest.fixture
def build_env(db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=db))
    monkeypatch.setattr(server, "kanban", KanbanBoard(db_path=db))
    bin_dir = tmp_path / "bin_out"
    bin_dir.mkdir()
    monkeypatch.setattr(server, "TEMP_BIN_DIR", bin_dir)
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    go_toolchain.reset_cache()
    yield
    _PrivilegeCache.reset()


def _build(**kw: object) -> dict:
    kw.setdefault("verbosity", "detail")
    return json.loads(asyncio.run(server.artifact_lint_and_build(action="build", **kw)))


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
def test_build_twice_is_cached_then_source_change_is_new_generation(build_env: None) -> None:
    r1 = _build(template_name="mem-stat", name="t59_mem")
    assert r1["status"] == "SUCCESS" and r1["cached"] is False and r1["generation"] == 1
    assert len(r1["source_hash"]) == 64 and r1["toolchain"].startswith("go")
    tid = r1["kanban_task_id"]
    _promote_by_hand(server.kanban, tid)

    r2 = _build(template_name="mem-stat", name="t59_mem")
    assert r2["cached"] is True and r2["generation"] == 1 and r2["source_hash"] == r1["source_hash"]
    assert "demoted_from" not in r2
    card = _card(server.kanban, tid)
    assert (card["state"], card["canary_passed"], card["attempts"]) == ("PROMOTED", 1, 1)

    src = json.loads(asyncio.run(server.artifact_lint_and_build(action="hydrate", template_name="mem-stat")))[
        "go_source"
    ]
    r3 = _build(go_source=src + "\n// generation two\n", name="t59_mem", intent="mem", category="memory")
    assert r3["status"] == "SUCCESS" and r3["cached"] is False and r3["generation"] == 2
    assert r3["demoted_from"] == "PROMOTED" and r3["reason"] == "source_changed"
    assert r3["source_hash"] != r1["source_hash"]
    card = _card(server.kanban, tid)
    assert (card["state"], card["canary_passed"], card["generation"]) == ("LINTED", 0, 2)


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
def test_compact_build_shortens_source_hash(build_env: None) -> None:
    r = _build(template_name="mem-stat", name="t59_short", verbosity="summary")
    assert len(r["source_hash"]) == 12
