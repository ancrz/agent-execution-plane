"""ONT-60 T4/G61: the lint action reuses the module-mode pipeline and reports informative healing."""

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
from engine.kanban import KanbanBoard
from engine.privilege import _PrivilegeCache

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not installed")

GOOD = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}\n'
UNFORMATTED = 'package main\nimport "fmt"\nfunc main() {\nfmt.Println("hi")\n}\n'
VET_BAD = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Printf("%d\\n", "x")\n}\n'
SYNTAX_BAD = "package main\nfunc main( {\n"


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    db = tmp_path / "artifacts.db"
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=db))
    monkeypatch.setattr(server, "kanban", KanbanBoard(db_path=db))
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    go_toolchain.reset_cache()
    yield db
    _PrivilegeCache.reset()


def _lint(src: str) -> dict:
    return json.loads(
        asyncio.run(server.artifact_lint_and_build(action="lint", go_source=src, verbosity="detail")),
    )


def _cards(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM kanban_tasks").fetchone()[0]


def test_clean_source_reports_healing_without_touching_kanban(env: Path) -> None:
    out = _lint(GOOD)
    assert out["status"] == "OK" and out["vet_passed"] is True
    assert out["healing"] == {"gofmt_needed": False, "fix_lines": 0}
    assert _cards(env) == 0


def test_unformatted_source_flags_gofmt_needed_but_passes(env: Path) -> None:
    out = _lint(UNFORMATTED)
    assert out["status"] == "OK"
    assert out["healing"]["gofmt_needed"] is True


def test_vet_failure_is_reported_in_module_mode_without_kanban_card(env: Path) -> None:
    out = _lint(VET_BAD)
    assert out["status"] == "LINT_ERROR" and out["error_class"] == "vet"
    assert out["vet_passed"] is False and "healing" in out
    assert _cards(env) == 0


def test_syntax_error_is_fmt_class(env: Path) -> None:
    out = _lint(SYNTAX_BAD)
    assert out["status"] == "LINT_ERROR" and out["error_class"] == "fmt"
    assert _cards(env) == 0
