"""ONT-59 T2/K2: los fallos de build son datos de la tarjeta (errores como valores)."""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import server
from engine import catalog as catalog_mod
from engine import go_toolchain
from engine.catalog import ArtifactCatalog
from engine.kanban import FAILURE_PENALTY_CAP, KanbanBoard
from engine.privilege import _PrivilegeCache

GO = shutil.which("go")
H1, H2 = "a" * 64, "b" * 64
TC = "go1.27.4"


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


@pytest.fixture
def board(tmp_path: Path) -> KanbanBoard:
    return KanbanBoard(db_path=tmp_path / "k.db")


def _card(b: KanbanBoard, tid: int) -> sqlite3.Row:
    with b._conn_ro() as conn:
        return conn.execute("SELECT * FROM kanban_tasks WHERE id=?", (tid,)).fetchone()


def test_failure_without_card_creates_backlog_card(board: KanbanBoard) -> None:
    r = board.record_build_failure("probe", "vet", H1, TC, intent="i", category="c")
    assert r["created"] is True and r["state"] == "BACKLOG" and r["failures"] == 1
    row = _card(board, r["task_id"])
    assert (row["attempts"], row["lint_passed"], row["last_error_class"], row["source_hash"]) == (1, 0, "vet", H1)


def test_same_hash_failure_clears_lint_passed_and_counts(board: KanbanBoard) -> None:
    tid = board.upsert_build_task("probe", H1, TC)["task_id"]
    r = board.record_build_failure("probe", "build", H1, TC)
    assert r["task_id"] == tid and r["created"] is False and r["failures"] == 1
    row = _card(board, tid)
    assert (row["lint_passed"], row["attempts"], row["last_error_class"], row["state"]) == (0, 2, "build", "LINTED")
    assert board.record_build_failure("probe", "fmt", H1, TC)["failures"] == 2


def test_failure_of_other_source_keeps_lint_passed(board: KanbanBoard) -> None:
    tid = board.upsert_build_task("probe", H1, TC)["task_id"]
    board.record_build_failure("probe", "vet", H2, TC)
    assert _card(board, tid)["lint_passed"] == 1


def test_promoted_card_is_not_degraded_but_failure_is_recorded(board: KanbanBoard) -> None:
    tid = board.upsert_build_task("probe", H1, TC)["task_id"]
    with board._conn_rw() as conn:
        conn.execute("UPDATE kanban_tasks SET state='PROMOTED', canary_passed=1 WHERE id=?", (tid,))
    r = board.record_build_failure("probe", "build", H1, TC)
    row = _card(board, tid)
    assert r["state"] == "PROMOTED" and row["state"] == "PROMOTED"
    assert (row["lint_passed"], row["canary_passed"], row["failures"], row["last_error_class"]) == (1, 1, 1, "build")


def test_success_resets_failures(board: KanbanBoard) -> None:
    tid = board.upsert_build_task("probe", H1, TC)["task_id"]
    board.record_build_failure("probe", "vet", H1, TC)
    board.upsert_build_task("probe", H1, TC)
    row = _card(board, tid)
    assert (row["failures"], row["last_error_class"]) == (0, None)


def test_failure_penalty_is_bounded_and_monotonic(board: KanbanBoard) -> None:
    base = board._ponder(True, True, 1.0, 5, 0.0, 0)["effective"]
    scores = [board._ponder(True, True, 1.0, 5, 0.0, n)["effective"] for n in range(0, 12)]
    assert scores == sorted(scores, reverse=True) and scores[0] == base
    assert scores[FAILURE_PENALTY_CAP] == scores[11] < base  # acotada: más de CAP fallos no empeora
    assert board._ponder(True, True, 1.0, 5, 0.0, -3)["effective"] == base


def test_invalid_error_class(board: KanbanBoard) -> None:
    assert board.record_build_failure("probe", "nope")["status"] == "PARAM_ERROR"


def test_migration_adds_columns(tmp_path: Path) -> None:
    p = tmp_path / "k.db"
    KanbanBoard(db_path=p)
    KanbanBoard(db_path=p)
    with sqlite3.connect(p) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(kanban_tasks)")}
    assert {"last_error_class", "failures"} <= cols


@pytest.fixture
def build_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    db = tmp_path / "artifacts.db"
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=db))
    monkeypatch.setattr(server, "kanban", KanbanBoard(db_path=db))
    (tmp_path / "bin_out").mkdir()
    monkeypatch.setattr(server, "TEMP_BIN_DIR", tmp_path / "bin_out")
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    go_toolchain.reset_cache()
    yield
    _PrivilegeCache.reset()


def _build(**kw: object) -> dict:
    return json.loads(asyncio.run(server.artifact_lint_and_build(action="build", verbosity="detail", **kw)))


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
def test_vet_error_is_recorded_on_the_card(build_env: None) -> None:
    bad = 'package main\nimport "fmt"\nfunc main() { fmt.Printf("%d\\n", "x") }\n'
    r = _build(go_source=bad, name="t59_bad", intent="i", category="c")
    assert r["status"] == "LINT_ERROR" and isinstance(r["kanban_task_id"], int)
    with server.kanban._conn_ro() as conn:
        row = conn.execute("SELECT * FROM kanban_tasks WHERE id=?", (r["kanban_task_id"],)).fetchone()
    assert (row["state"], row["failures"], row["last_error_class"]) == ("BACKLOG", 1, "vet")


def test_hydrate_error_is_recorded(build_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> str:
        raise ValueError("bad params")

    monkeypatch.setattr(server.hydrator, "hydrate", boom)
    r = _build(template_name="mem-stat", name="t59_hyd")
    assert r["status"] == "HYDRATE_ERROR" and isinstance(r["kanban_task_id"], int)
    with server.kanban._conn_ro() as conn:
        row = conn.execute(
            "SELECT failures, last_error_class FROM kanban_tasks WHERE id=?", (r["kanban_task_id"],)
        ).fetchone()
    assert tuple(row) == (1, "hydrate")
