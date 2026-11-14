"""ONT-49: dogfooding round 3 (G27-G30)."""

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


def test_g28_archive_sweep_noop_and_no_null_hint(board: KanbanBoard) -> None:
    res = board.archive(title_like="%nothing%", apply=True)
    assert res["status"] == "NOOP" and res["applied"] is False and res["archived"] == 0
    assert "hint" not in res
    board.create_task("Test Add Alias Task")
    res = board.archive(title_like="%Alias%", apply=True)
    assert res["status"] == "ARCHIVED" and res["archived"] == 1 and res["applied"] is True
    assert "hint" not in res
    board.create_task("Test Add Alias Task")
    dry = board.archive(title_like="%Alias%")
    assert dry["status"] == "DRY_RUN" and "archived" not in dry and dry["hint"]


def test_g29_board_terse_limit_and_budget(board: KanbanBoard) -> None:
    for i in range(40):
        board.create_task(f"Card number {i} " + "x" * 80)
    res = _call(action="board", verbosity="terse", limit=1)
    assert set(res) >= {"status", "counts", "lane_totals", "archived_total", "threshold"}
    assert res["lane_totals"]["BACKLOG"] == 40
    ((tid, title),) = res["lanes"]["BACKLOG"]
    assert len(title) <= 60 and tid == 40
    assert res["truncated"] is True and res["cursor"] == "1"
    raw = asyncio.run(server.kanban_board(action="board", verbosity="terse", limit=1))
    assert len(raw) / 4 <= 400
    no_cards = _call(action="board", verbosity="terse", limit=0)
    assert "lanes" not in no_cards


def test_g30_db_scope_custom_in_kanban(board: KanbanBoard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    det = _call(action="board", verbosity="detail")
    assert det["db_scope"] == "custom" and det["db_path"] == str((tmp_path / "kanban.db").resolve())
    assert _call(action="board", verbosity="summary")["db_scope"] == "custom"
    monkeypatch.setattr("engine.kanban.DB_DEFAULT_PATH", tmp_path / "kanban.db")
    det = _call(action="board", verbosity="detail")
    assert det["db_scope"] == "real" and "db_path" not in det
    assert "db_scope" not in _call(action="board", verbosity="summary")


def test_g30_db_scope_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.catalog import ArtifactCatalog

    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=tmp_path / "cat.db"))
    det = json.loads(asyncio.run(server.artifact_catalog(action="browse", verbosity="detail")))
    assert det["db_scope"] == "custom" and det["db_path"].endswith("cat.db")
