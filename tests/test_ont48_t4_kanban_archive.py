"""ONT-48 T4 (G22): kanban archive by task_id (any lane except PROMOTED) and title_like sweeps."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import server
from engine.kanban import KanbanBoard


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KanbanBoard:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    monkeypatch.setattr(server, "kanban", b)
    return b


def _call(**kw) -> dict:
    return json.loads(asyncio.run(server.kanban_board(**kw)))


def test_archive_task_id_backlog_and_unarchive(board: KanbanBoard) -> None:
    tid = board.create_task("Test Add Alias Task")["task_id"]
    res = board.archive(task_id=tid)
    assert res["status"] == "ARCHIVED" and res["applied"] is True
    assert board.board()["counts"]["BACKLOG"] == 0
    assert board.unarchive(tid)["archived"] is False
    assert board.board()["counts"]["BACKLOG"] == 1


def test_archive_task_id_promoted_is_protected(board: KanbanBoard) -> None:
    tid = board.create_task("p")["task_id"]
    with board._conn_rw() as conn:
        conn.execute("UPDATE kanban_tasks SET state='PROMOTED' WHERE id=?", (tid,))
        conn.commit()
    res = board.archive(task_id=tid)
    assert res["status"] == "PROTECTED" and res["applied"] is False
    assert board.board()["counts"]["PROMOTED"] == 1


def test_archive_unknown_task(board: KanbanBoard) -> None:
    assert board.archive(task_id=9999)["status"] == "ERROR"


def test_task_id_wins_over_states(board: KanbanBoard) -> None:
    tid = board.create_task("x")["task_id"]
    res = board.archive(states=["LINTED"], task_id=tid)
    assert res["applied"] is True and res["states_ignored"] == ["LINTED"]


def test_title_like_sweep_dry_run_then_apply(board: KanbanBoard) -> None:
    for _ in range(3):
        board.create_task("Test Add Alias Task")
    keep = board.create_task("Real work")["task_id"]
    dry = board.archive(title_like="Test Add Alias%")
    assert dry["status"] == "DRY_RUN" and dry["candidate_count"] == 3
    assert "BACKLOG" in dry["states_scanned"] and dry["title_like"] == "Test Add Alias%"
    assert keep not in [c["task_id"] for c in dry["candidates"]]
    done = board.archive(title_like="Test Add Alias%", apply=True)
    assert done["status"] == "ARCHIVED"
    assert board.board()["counts"]["BACKLOG"] == 1


def test_server_archive_with_task_id(board: KanbanBoard) -> None:
    tid = board.create_task("srv")["task_id"]
    res = _call(action="archive", task_id=tid)
    assert res["status"] == "ARCHIVED" and res["applied"] is True


def test_t5_description_and_refs_only_in_detail(board: KanbanBoard) -> None:
    res = _call(action="create", title="with ctx", description="plan link", refs=["abc1234", "docs/plan.md"])
    assert res["status"] == "OK"
    detail = _call(action="board", verbosity="detail")
    card = detail["lanes"]["BACKLOG"][0]
    assert card["description"] == "plan link" and card["refs"] == ["abc1234", "docs/plan.md"]
    summary = _call(action="board", verbosity="summary")
    assert "description" not in summary["lanes"]["BACKLOG"][0]
    assert "refs" not in summary["lanes"]["BACKLOG"][0]


def test_t5_legacy_table_migrates(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE kanban_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, intent TEXT, "
        "category TEXT, artifact_name TEXT, state TEXT NOT NULL DEFAULT 'BACKLOG', lint_passed INTEGER NOT NULL "
        "DEFAULT 0, canary_passed INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, promotion_score "
        "REAL NOT NULL DEFAULT 0.0, archived INTEGER NOT NULL DEFAULT 0, agent_id TEXT NOT NULL DEFAULT 'default', "
        "note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    b = KanbanBoard(db_path=db)
    KanbanBoard(db_path=db)  # idempotent
    tid = b.create_task("t", description="d", refs=["r"])["task_id"]
    assert b.board(with_extras=True)["lanes"]["BACKLOG"][0]["refs"] == ["r"] and tid
