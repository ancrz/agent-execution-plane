"""ONT-55: tarjetas de trabajo (kind='work') en el kanban y `advance` sin `to_state` (G48/G49)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import server
from engine.kanban import STATES, WORK_STATES, KanbanBoard


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KanbanBoard:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    monkeypatch.setattr(server, "kanban", b)
    return b


def _call(**kw) -> dict:
    return json.loads(asyncio.run(server.kanban_board(**kw)))


def test_migration_adds_kind_to_old_db(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE kanban_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, intent TEXT, "
        "category TEXT, artifact_name TEXT, state TEXT NOT NULL DEFAULT 'BACKLOG', "
        "lint_passed INTEGER NOT NULL DEFAULT 0, canary_passed INTEGER NOT NULL DEFAULT 0, "
        "attempts INTEGER NOT NULL DEFAULT 0, promotion_score REAL NOT NULL DEFAULT 0.0, "
        "archived INTEGER NOT NULL DEFAULT 0, agent_id TEXT NOT NULL DEFAULT 'default', note TEXT, "
        "description TEXT, refs TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)"
    )
    conn.execute("INSERT INTO kanban_tasks (title, state) VALUES ('legacy', 'LINTED')")
    conn.commit()
    conn.close()
    b = KanbanBoard(db_path=db)
    KanbanBoard(db_path=db)  # idempotente
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT kind FROM kanban_tasks").fetchall() == [("artifact",)]
    conn.close()
    res = b.board()
    assert res["counts"]["LINTED"] == 1 and "work_lanes" not in res


def test_work_card_lifecycle_and_noop(board: KanbanBoard) -> None:
    tid = board.create_task("ONT-99 trabajo", kind="work")["task_id"]
    assert board.create_task("x", kind="work")["kind"] == "work"
    r1 = board.advance(tid, "")
    assert r1 == {"status": "OK", "task_id": tid, "kind": "work", "state": "IN_PROGRESS", "from_state": "BACKLOG"}
    r2 = board.advance(tid, "")
    assert r2["state"] == "DONE" and r2["from_state"] == "IN_PROGRESS"
    r3 = board.advance(tid, "")
    assert r3["status"] == "NOOP" and r3["state"] == "DONE"
    blocked = board.advance(tid, "BLOCKED")
    assert blocked["status"] == "OK" and blocked["state"] == "BLOCKED"
    assert board.advance(tid, "")["state"] == "IN_PROGRESS"


def test_work_card_is_not_weighted(board: KanbanBoard) -> None:
    tid = board.create_task("trabajo", kind="work")["task_id"]
    res = board.advance(tid, "DONE")
    assert "promotion_score" not in res and "verdict" not in res and res["state"] == "DONE"
    conn = sqlite3.connect(board.db_path)
    score, attempts = conn.execute("SELECT promotion_score, attempts FROM kanban_tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    assert score == 0.0 and attempts == 1


def test_artifact_advance_without_to_state_and_canary_gate(board: KanbanBoard) -> None:
    tid = board.create_task("art")["task_id"]
    assert board.create_task("art2")["kind"] == "artifact"
    r = board.advance(tid, "")
    assert r["state"] == "SYNTHESIZED" and r["from_state"] == "BACKLOG" and r["kind"] == "artifact"
    assert "promotion_score" in r
    assert board.advance(tid, "")["state"] == "LINTED"
    assert board.advance(tid, "")["state"] == "CANARY"
    gate = board.advance(tid, "")
    assert gate["status"] == "PARAM_ERROR" and gate["next_action"] == f'kanban_board(action="promote", task_id={tid})'
    board.advance(tid, "REJECTED")
    assert board.advance(tid, "")["status"] == "NOOP"


def test_invalid_state_is_param_error_with_kind_states(board: KanbanBoard) -> None:
    art = board.create_task("art")["task_id"]
    work = board.create_task("w", kind="work")["task_id"]
    ra = board.advance(art, "DONE")
    assert ra["status"] == "PARAM_ERROR" and ra["valid_states"] == STATES and "DONE" in ra["error"]
    rw = board.advance(work, "PROMOTED")
    assert rw["status"] == "PARAM_ERROR" and rw["valid_states"] == WORK_STATES
    assert board.create_task("bad", kind="nope")["status"] == "PARAM_ERROR"
    assert board.create_task("bad", kind="nope")["valid_kinds"] == ["artifact", "work"]


def test_promote_demote_on_work_card_param_error(board: KanbanBoard) -> None:
    work = board.create_task("w", kind="work")["task_id"]
    assert board.promote(work)["status"] == "PARAM_ERROR"
    assert board.demote(task_id=work)["status"] == "PARAM_ERROR"
    assert board.advance(work, "")["state"] == "IN_PROGRESS"  # no mutada por demote


def test_board_work_lanes_only_when_present(board: KanbanBoard) -> None:
    board.create_task("art")
    before = board.board()
    assert "work_lanes" not in before and "work_counts" not in before
    wid = board.create_task("w", kind="work", description="d", refs=["abc"])["task_id"]
    board.advance(wid, "")
    after = board.board(with_extras=True)
    assert after["counts"] == before["counts"] and after["lanes"] == before["lanes"]
    assert after["work_counts"] == {"BACKLOG": 0, "IN_PROGRESS": 1, "BLOCKED": 0, "DONE": 0}
    (card,) = after["work_lanes"]["IN_PROGRESS"]
    assert card["title"] == "w" and card["description"] == "d" and card["refs"] == ["abc"] and card["attempts"] == 1
    slim = board.board()["work_lanes"]["IN_PROGRESS"][0]
    assert "description" not in slim


def test_reevaluate_and_canary_ignore_work(board: KanbanBoard) -> None:
    wid = board.create_task("w", kind="work", artifact_name="same_art")["task_id"]
    assert board.record_canary_by_artifact("same_art", True) is None
    conn = sqlite3.connect(board.db_path)
    conn.execute(
        "CREATE TABLE artifacts (name TEXT, success_rate REAL, execution_count INTEGER, updated_at TEXT, "
        "reusable INTEGER, promotion_score REAL)"
    )
    conn.commit()
    conn.close()
    assert board.reevaluate()["reevaluated"] == 0
    assert board.advance(wid, "")["from_state"] == "BACKLOG"


def test_archive_sweep_skips_done_work_unless_explicit(board: KanbanBoard) -> None:
    wid = board.create_task("w", kind="work")["task_id"]
    board.advance(wid, "DONE")
    sweep = board.archive(title_like="%w%", apply=True)
    assert sweep["status"] == "NOOP"
    explicit = board.archive(states=["DONE"], apply=True)
    assert explicit["status"] == "ARCHIVED" and explicit["archived"] == 1
    board.unarchive(wid)
    assert board.archive(task_id=wid)["status"] == "ARCHIVED"


def test_server_advance_without_to_state_work_flow(board: KanbanBoard) -> None:
    created = _call(action="create", title="ONT-77 tarea", kind="work")
    tid = created["task_id"]
    assert created["kind"] == "work" and created["next_action"] == f'kanban_board(action="advance", task_id={tid})'
    r1 = _call(action="advance", task_id=tid)
    assert r1["status"] == "OK" and r1["state"] == "IN_PROGRESS"
    assert r1["next_action"] == f'kanban_board(action="advance", task_id={tid})'
    r2 = _call(action="advance", task_id=tid)
    assert r2["state"] == "DONE"
    r3 = _call(action="advance", task_id=tid)
    assert r3["status"] == "NOOP"


def test_server_validation_paths(board: KanbanBoard) -> None:
    assert _call(action="advance")["status"] == "PARAM_ERROR"
    tid = _call(action="create", title="art")["task_id"]
    assert _call(action="advance", task_id=tid)["state"] == "SYNTHESIZED"
    bad = _call(action="advance", task_id=tid, to_state="DONE")
    assert bad["status"] == "PARAM_ERROR" and bad["valid_states"] == STATES
    assert _call(action="create", title="x", kind="zzz")["status"] == "PARAM_ERROR"
    for _ in range(2):
        _call(action="advance", task_id=tid)
    gate = _call(action="advance", task_id=tid)
    assert gate["status"] == "PARAM_ERROR" and "promote" in gate["next_action"]


def test_server_board_work_counts_in_terse_and_summary(board: KanbanBoard) -> None:
    assert "work_counts" not in _call(action="board", verbosity="terse")
    _call(action="create", title="w1", kind="work")
    terse = _call(action="board", verbosity="terse", limit=0)
    assert terse["work_counts"]["BACKLOG"] == 1
    summ = _call(action="board", verbosity="summary")
    assert summ["work_counts"]["BACKLOG"] == 1 and len(summ["work_lanes"]["BACKLOG"]) == 1
