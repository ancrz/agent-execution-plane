"""ONT-58 T1/G55: reclassify restores the exact previous (state, score) when reverting."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engine.kanban import KanbanBoard


@pytest.fixture
def board(tmp_path: Path) -> KanbanBoard:
    return KanbanBoard(db_path=tmp_path / "kanban.db")


def _row(b: KanbanBoard, tid: int) -> sqlite3.Row:
    with b._conn_ro() as c:
        return c.execute("SELECT * FROM kanban_tasks WHERE id=?", (tid,)).fetchone()


def _set(b: KanbanBoard, tid: int, state: str, score: float) -> None:
    with b._conn_rw() as c:
        c.execute("UPDATE kanban_tasks SET state=?, promotion_score=? WHERE id=?", (state, score, tid))
        c.commit()


def test_work_done_roundtrip_returns_done(board: KanbanBoard) -> None:
    tid = board.create_task("w", kind="work")["task_id"]
    _set(board, tid, "DONE", 0.0)
    board.reclassify(kind="artifact", task_id=tid, apply=True)
    assert _row(board, tid)["state"] == "BACKLOG"
    dry = board.reclassify(kind="work", task_id=tid)
    assert dry["candidates"][0]["new_state"] == "DONE"
    assert dry["candidates"][0]["restores_previous"] is True
    board.reclassify(kind="work", task_id=tid, apply=True)
    r = _row(board, tid)
    assert (r["kind"], r["state"]) == ("work", "DONE")
    assert r["prev_kind"] is None


def test_promoted_score_restored(board: KanbanBoard) -> None:
    tid = board.create_task("a")["task_id"]
    _set(board, tid, "PROMOTED", 0.9)
    board.reclassify(kind="work", task_id=tid, apply=True)
    assert _row(board, tid)["state"] == "DONE"
    board.reclassify(kind="artifact", task_id=tid, apply=True)
    r = _row(board, tid)
    assert (r["kind"], r["state"], r["promotion_score"]) == ("artifact", "PROMOTED", 0.9)


def test_card_without_prev_uses_map(board: KanbanBoard) -> None:
    tid = board.create_task("a")["task_id"]
    _set(board, tid, "CANARY", 0.4)
    board.reclassify(kind="work", task_id=tid, apply=True)
    board.reclassify(kind="artifact", task_id=tid, apply=True)  # restores, clears prev
    assert _row(board, tid)["prev_kind"] is None
    board.reclassify(kind="work", task_id=tid, apply=True)  # no prev: map
    assert _row(board, tid)["state"] == "IN_PROGRESS"
    legacy = board.create_task("legacy")["task_id"]
    dry = board.reclassify(kind="work", task_id=legacy)
    assert "restores_previous" not in dry["candidates"][0]


def test_migration_on_old_db_and_board_intact(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE kanban_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, intent TEXT, "
        "category TEXT, artifact_name TEXT, state TEXT NOT NULL DEFAULT 'BACKLOG', "
        "lint_passed INTEGER NOT NULL DEFAULT 0, canary_passed INTEGER NOT NULL DEFAULT 0, "
        "attempts INTEGER NOT NULL DEFAULT 0, promotion_score REAL NOT NULL DEFAULT 0.0, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO kanban_tasks (title) VALUES ('legacy')")
    conn.commit()
    conn.close()
    KanbanBoard(db_path=db)
    b = KanbanBoard(db_path=db)  # idempotent second open
    with b._conn_ro() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(kanban_tasks)")}
    assert {"prev_kind", "prev_state", "prev_score"} <= cols
    lanes = b.board()
    assert "prev_kind" not in str(lanes)
    assert b.reclassify(kind="work", task_id=1, apply=True)["status"] == "RECLASSIFIED"
