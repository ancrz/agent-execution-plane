"""ONT-56/G51: next_action propio del payload prevalece sobre el genérico del NOOP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import server
from engine.kanban import KanbanBoard
from engine.telemetry import RequestTelemetry, attach_envelope


@pytest.fixture
def board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KanbanBoard:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    monkeypatch.setattr(server, "kanban", b)
    return b


def _call(**kw) -> dict:
    return json.loads(asyncio.run(server.kanban_board(**kw)))


@pytest.mark.parametrize("verbosity", ["summary", "detail"])
def test_advance_done_noop_has_own_next_action(board: KanbanBoard, verbosity: str) -> None:
    tid = board.create_task("ONT-99 w", kind="work")["task_id"]
    board.advance(tid, "DONE")
    res = _call(action="advance", task_id=tid, verbosity=verbosity)
    assert res["status"] == "NOOP"
    assert res["next_action"] == "Card already in terminal state DONE; nothing to do."
    if verbosity == "detail":
        assert res["envelope"]["next_action"] == res["next_action"]


def test_attach_envelope_respects_payload_next_action_and_default_stays() -> None:
    tr = RequestTelemetry("t", "a")
    own = json.loads(attach_envelope({"status": "NOOP", "next_action": "custom"}, tr, verbosity="detail"))
    assert own["next_action"] == "custom" and own["envelope"]["next_action"] == "custom"
    gen = json.loads(attach_envelope({"status": "NOOP"}, RequestTelemetry("t", "a"), verbosity="detail"))
    assert gen["next_action"] == "Nothing to do; adjust filters or apply=true."
