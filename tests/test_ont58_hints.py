"""ONT-58 T3/G57: DRY_RUN hints no longer duplicate next_action."""

from __future__ import annotations

from pathlib import Path

from engine.kanban import KanbanBoard


def test_archive_dry_run_hint_only_reversibility(tmp_path: Path) -> None:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    b.create_task("Alias card")
    dry = b.archive(title_like="%Alias%")
    assert dry["status"] == "DRY_RUN"
    assert dry["hint"] == "Reversible: kanban_board(action='unarchive', task_id=...)."


def test_reclassify_dry_run_has_no_duplicate_hint(tmp_path: Path) -> None:
    b = KanbanBoard(db_path=tmp_path / "kanban.db")
    b.create_task("Some card")
    dry = b.reclassify(kind="work", title_like="%Some card%")
    assert dry["status"] == "DRY_RUN" and "hint" not in dry
