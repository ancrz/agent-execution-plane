"""ONT-57 T3/G54: reclassify reverses by explicit task_ids and never touches native cards."""

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


def _kind(b: KanbanBoard, tid: int) -> str:
    import sqlite3

    conn = sqlite3.connect(b.db_path)
    try:
        return conn.execute("SELECT kind FROM kanban_tasks WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()


def test_revert_by_task_ids_leaves_native_work_cards(board: KanbanBoard) -> None:
    legacy = [board.create_task(f"ONT-{i} legacy")["task_id"] for i in range(3)]
    native = board.create_task("ONT-503 native", kind="work")["task_id"]

    res = _call(action="reclassify", title_like="ONT-%", kind="work", apply=True, verbosity="detail")
    assert res["status"] == "RECLASSIFIED"
    assert res["reclassified_ids"] == legacy
    assert f"task_ids={legacy}" in res["hint"] and "title_like" not in res["hint"]

    back = _call(action="reclassify", task_ids=res["reclassified_ids"], kind="artifact", apply=True)
    assert back["status"] == "RECLASSIFIED" and back["reclassified"] == 3
    assert all(_kind(board, t) == "artifact" for t in legacy)
    assert _kind(board, native) == "work"


def test_task_ids_apply_directly_without_apply_flag(board: KanbanBoard) -> None:
    a = board.create_task("ONT-1 x")["task_id"]
    res = board.reclassify("work", task_ids=[a])
    assert res["status"] == "RECLASSIFIED" and res["reclassified_ids"] == [a]


def test_invalid_task_ids(board: KanbanBoard) -> None:
    assert board.reclassify("work", task_ids=["x"])["status"] == "PARAM_ERROR"  # type: ignore[list-item]


def test_hint_over_50_ids_gives_count_not_list(board: KanbanBoard) -> None:
    for i in range(55):
        board.create_task(f"ONT-{i} bulk")
    res = board.reclassify("work", title_like="ONT-%", apply=True)
    assert res["reclassified"] == 55 and len(res["reclassified_ids"]) == 55
    assert "55 cards" in res["hint"] and "task_ids=[" not in res["hint"]


def test_reclassified_ids_paginated_in_tool(board: KanbanBoard) -> None:
    for i in range(8):
        board.create_task(f"ONT-{i} p")
    res = _call(action="reclassify", title_like="ONT-%", kind="work", apply=True, limit=3)
    assert len(res["reclassified_ids"]) == 3 and res["total_reclassified_ids"] == 8
