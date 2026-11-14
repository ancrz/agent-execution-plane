"""ONT-61 T4/G66: reclassify(task_ids) binds ONE JSON parameter (json_each) instead of N placeholders."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

from engine import kanban
from engine.kanban import KanbanBoard

_N_TASKS = 2000
_SQLITE_MAX_VARS_MODERN = 32766  # SQLITE_MAX_VARIABLE_NUMBER default since 3.32; 999 before


def _kind(b: KanbanBoard, tid: int) -> str:
    conn = sqlite3.connect(b.db_path)
    try:
        return conn.execute("SELECT kind FROM kanban_tasks WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()


def test_reclassify_2000_ids_and_beyond_the_sqlite_variable_limit(tmp_path: Path) -> None:
    board = KanbanBoard(db_path=tmp_path / "kanban.db")
    ids = [board.create_task(f"ONT-{i} legacy")["task_id"] for i in range(_N_TASKS)]
    # Pad with non-existent ids past the bound-variable limit: the old `IN (?,?,...)` form would raise OperationalError.
    padded = ids + list(range(10**6, 10**6 + _SQLITE_MAX_VARS_MODERN + 100))
    res = board.reclassify(task_ids=padded, kind="work", apply=True)
    assert res["status"] == "RECLASSIFIED" and res["reclassified"] == _N_TASKS
    assert _kind(board, ids[0]) == "work" and _kind(board, ids[-1]) == "work"
    back = board.reclassify(task_ids=ids, kind="artifact", apply=True)
    assert back["reclassified"] == _N_TASKS
    assert _kind(board, ids[1000]) == "artifact"


def test_reclassify_source_has_no_placeholder_fstring_sql() -> None:
    src = inspect.getsource(kanban.KanbanBoard.reclassify)
    assert "json_each(?)" in src
    assert 'join("?"' not in src and "noqa: S608" not in src
