"""ONT-57 T2/G52: a DRY_RUN with candidates must not say 'Nothing to do'."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import server
from engine.kanban import KanbanBoard
from engine.telemetry import RequestTelemetry, attach_envelope

REVIEW = "Review candidates; repeat with apply=True to execute."


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KanbanBoard:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    monkeypatch.setattr(server, "kanban", b)
    return b


def _call(**kw) -> dict:
    return json.loads(asyncio.run(server.kanban_board(**kw)))


def _env(payload: dict) -> dict:
    return json.loads(attach_envelope(payload, RequestTelemetry("t", "a"), verbosity="detail"))


def test_reclassify_dry_run_with_candidates(board: KanbanBoard) -> None:
    board.create_task("ONT-1 a")
    res = _call(action="reclassify", title_like="ONT-%", kind="work")
    assert res["status"] == "DRY_RUN" and res["candidate_count"] == 1
    assert res["next_action"] == REVIEW


def test_archive_dry_run_with_candidates(board: KanbanBoard) -> None:
    tid = board.create_task("ONT-2 stale")["task_id"]
    conn = sqlite3.connect(board.db_path)
    conn.execute("UPDATE kanban_tasks SET state='REJECTED' WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    res = _call(action="archive", title_like="ONT-%")
    assert res["status"] == "DRY_RUN" and res["candidate_count"] >= 1
    assert res["next_action"] == REVIEW


def test_dry_run_without_candidates_keeps_nothing_to_do(board: KanbanBoard) -> None:
    res = _call(action="reclassify", title_like="NOPE-%", kind="work")
    assert res["status"] == "DRY_RUN" and res["candidate_count"] == 0
    assert res["next_action"].startswith("Nothing to do")


@pytest.mark.parametrize(
    "payload",
    [{"candidate_count": 3}, {"total_candidates": 2}, {"candidates": [{"id": 1}]}],
)
def test_candidate_shapes(payload: dict) -> None:
    assert _env({"status": "DRY_RUN", **payload})["next_action"] == REVIEW


def test_own_next_action_still_wins() -> None:
    assert _env({"status": "DRY_RUN", "candidate_count": 4, "next_action": "mine"})["next_action"] == "mine"
