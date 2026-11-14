"""ONT-56/G50: kanban_board(action="reclassify") sobre tarjetas legadas (DB en tmp_path)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
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


def _card(b: KanbanBoard, title: str, state: str, *, artifact: str | None = None, archived: int = 0) -> int:
    tid = b.create_task(title)["task_id"]
    conn = sqlite3.connect(b.db_path)
    conn.execute(
        "UPDATE kanban_tasks SET state=?, artifact_name=?, archived=?, promotion_score=0.9, attempts=2 WHERE id=?",
        (state, artifact, archived, tid),
    )
    conn.commit()
    conn.close()
    return tid


def _row(b: KanbanBoard, tid: int) -> sqlite3.Row:
    conn = sqlite3.connect(b.db_path)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM kanban_tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    return r


def test_dry_run_does_not_write_and_maps_states(board: KanbanBoard) -> None:
    ids = {
        s: _card(board, f"ONT-1 {s}", s) for s in ("BACKLOG", "SYNTHESIZED", "LINTED", "CANARY", "PROMOTED", "REJECTED")
    }
    res = board.reclassify("work", title_like="ONT-%")
    assert res["status"] == "DRY_RUN" and res["applied"] is False
    got = {c["state"]: c["new_state"] for c in res["candidates"]}
    assert got == {
        "BACKLOG": "BACKLOG",
        "SYNTHESIZED": "IN_PROGRESS",
        "LINTED": "IN_PROGRESS",
        "CANARY": "IN_PROGRESS",
        "PROMOTED": "DONE",
        "REJECTED": "BLOCKED",
    }
    assert all(_row(board, t)["kind"] == "artifact" for t in ids.values())


def test_apply_idempotent_and_preserves_fields(board: KanbanBoard) -> None:
    tid = _card(board, "ONT-2 x", "PROMOTED")
    res = board.reclassify("work", title_like="ONT-%", apply=True)
    assert res["status"] == "RECLASSIFIED" and res["reclassified"] == 1
    r = _row(board, tid)
    assert (r["kind"], r["state"], r["attempts"], r["archived"]) == ("work", "DONE", 2, 0)
    again = board.reclassify("work", title_like="ONT-%", apply=True)
    assert again["status"] == "NOOP" and again["skipped"] == [{"task_id": tid, "reason": "already work"}]


def test_artifact_name_is_skipped(board: KanbanBoard) -> None:
    tid = _card(board, "ONT-3 real", "LINTED", artifact="my_art")
    res = board.reclassify("work", title_like="ONT-%", apply=True)
    assert res["status"] == "NOOP"
    assert res["skipped"] == [{"task_id": tid, "reason": "has artifact"}]
    assert _row(board, tid)["kind"] == "artifact"


def test_archived_only_with_include_archived(board: KanbanBoard) -> None:
    tid = _card(board, "ONT-4 arch", "BACKLOG", archived=1)
    assert board.reclassify("work", title_like="ONT-%")["candidate_count"] == 0
    res = board.reclassify("work", title_like="ONT-%", include_archived=True)
    assert res["candidate_count"] == 1 and res["candidates"][0]["archived"] is True
    board.reclassify("work", title_like="ONT-%", include_archived=True, apply=True)
    assert _row(board, tid)["archived"] == 1


def test_task_id_direct_and_reverse(board: KanbanBoard) -> None:
    tid = _card(board, "ONT-5 y", "CANARY")
    res = board.reclassify("work", task_id=tid)
    assert res["status"] == "RECLASSIFIED" and res["applied"] is True
    assert _row(board, tid)["state"] == "IN_PROGRESS"
    back = board.reclassify("artifact", task_id=tid)
    assert back["status"] == "RECLASSIFIED"
    r = _row(board, tid)
    # ONT-58/G55: the reverse restores the exact previous state (CANARY, score 0.9), not the BACKLOG/0.0 reset.
    assert (r["kind"], r["state"], r["promotion_score"]) == ("artifact", "CANARY", 0.9)
    assert board.reclassify("work", task_id=9999)["status"] == "ERROR"


def test_param_errors(board: KanbanBoard) -> None:
    assert board.reclassify("bogus", task_id=1)["status"] == "PARAM_ERROR"
    assert board.reclassify("work")["status"] == "PARAM_ERROR"


def test_board_moves_card_to_work_lanes(board: KanbanBoard) -> None:
    tid = _card(board, "ONT-6 z", "PROMOTED")
    _call(action="reclassify", title_like="ONT-%", kind="work", apply=True, verbosity="detail")
    res = _call(action="board", verbosity="detail")
    assert res["counts"]["PROMOTED"] == 0
    assert [c["task_id"] for c in res["work_lanes"]["DONE"]] == [tid]


def test_tool_dry_run_pagination(board: KanbanBoard) -> None:
    for i in range(4):
        _card(board, f"ONT-7 {i}", "BACKLOG")
    res = _call(action="reclassify", title_like="ONT-%", kind="work", limit=2)
    assert res["status"] == "DRY_RUN" and res["truncated"] is True and res["cursor"] == "2"
    assert len(res["candidates"]) == 2 and res["total_candidates"] == 4
    res2 = _call(action="reclassify", title_like="ONT-%", kind="work", limit=2, cursor=2)
    assert res2["truncated"] is False and len(res2["candidates"]) == 2
