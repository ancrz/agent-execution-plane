"""ONT-59 T3/K3: curación mecánica (gofmt, go fix) antes del juicio (go vet), build en modo módulo reproducible."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import server
from engine import catalog as catalog_mod
from engine import go_toolchain
from engine.catalog import ArtifactCatalog
from engine.kanban import KanbanBoard
from engine.privilege import _PrivilegeCache

GO = shutil.which("go")
needs_go = pytest.mark.skipif(GO is None, reason="go toolchain not installed")

MESSY = 'package main\nimport "fmt"\nfunc main(){\nvar x   interface{} = 1\nfmt.Println( x )\n}\n'
NEAT = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tvar x interface{} = 1\n\tfmt.Println(x)\n}\n'


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


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


def _build(src: str, name: str = "t59_heal", **kw: object) -> dict:
    kw.setdefault("verbosity", "detail")
    return json.loads(
        asyncio.run(
            server.artifact_lint_and_build(action="build", go_source=src, name=name, intent="i", category="c", **kw)
        )
    )


def _catalog_source(name: str) -> str:
    with server.catalog._get_ro_conn() as conn:
        return conn.execute("SELECT go_source FROM artifacts WHERE name=?", (name,)).fetchone()["go_source"]


def test_build_env_is_reproducible() -> None:
    env = go_toolchain.build_env({"PATH": "/x"})
    assert env["GOTOOLCHAIN"] == "local" and env["GOFLAGS"] == "-mod=mod" and env["CGO_ENABLED"] == "0"
    assert env["PATH"] == "/x"


def test_go_mod_has_module_and_toolchain_major_minor(tmp_path: Path) -> None:
    path = go_toolchain.write_go_mod(tmp_path, "my art!", "go1.27.4")
    assert path.read_text(encoding="utf-8") == "module aep.local/my_art_\n\ngo 1.27\n"


def test_go_fix_unavailable_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(go_toolchain, "go_bin", lambda: None)
    assert go_toolchain.go_fix(tmp_path, apply=True) == {"available": False, "lines": 0, "diff": "", "applied": False}


@needs_go
def test_gofmt_source_formats_and_reports_syntax_errors() -> None:
    ok, out, _ = go_toolchain.gofmt_source(MESSY)
    assert ok and out == NEAT
    ok, same, err = go_toolchain.gofmt_source("package main\nfunc {")
    assert not ok and same == "package main\nfunc {" and err


@needs_go
def test_gofmt_is_applied_and_catalog_keeps_curated_source(build_env: None) -> None:
    r = _build(MESSY)
    assert r["status"] == "SUCCESS" and r["healing"]["gofmt_applied"] is True
    assert _catalog_source("t59_heal") == NEAT
    assert r["healing"]["fix_applied"] is False and r["healing"]["fix_lines"] > 0  # interface{} -> any, informado
    assert "any" in r["healing"]["fix_diff"]


@needs_go
def test_format_only_difference_is_the_same_source_hash(build_env: None) -> None:
    r1 = _build(MESSY)
    r2 = _build(NEAT)
    assert r1["source_hash"] == r2["source_hash"]
    assert r2["cached"] is True and r2["generation"] == 1 and r2["healing"]["gofmt_applied"] is False


@needs_go
def test_go_fix_is_applied_only_with_autofix(build_env: None) -> None:
    r_off = _build(NEAT, name="t59_nofix")
    assert r_off["healing"]["fix_applied"] is False and "interface{}" in _catalog_source("t59_nofix")
    r_on = _build(NEAT, name="t59_fix", autofix=True)
    assert r_on["status"] == "SUCCESS" and r_on["healing"]["fix_applied"] is True
    src = _catalog_source("t59_fix")
    assert "interface{}" not in src and " any" in src
    assert r_on["source_hash"] != r_off["source_hash"]  # el código curado es otro contenido


@needs_go
def test_syntax_error_is_a_fmt_failure_recorded_on_the_card(build_env: None) -> None:
    r = _build("package main\nfunc {", name="t59_syntax")
    assert r["status"] == "LINT_ERROR" and r["error_class"] == "fmt"
    with server.kanban._conn_ro() as conn:
        row = conn.execute(
            "SELECT state, failures, last_error_class FROM kanban_tasks WHERE id=?", (r["kanban_task_id"],)
        ).fetchone()
    assert tuple(row) == ("BACKLOG", 1, "fmt")


@needs_go
def test_vet_runs_in_module_mode_and_blocks(build_env: None) -> None:
    bad = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Printf("%d\\n", "x")\n}\n'
    r = _build(bad, name="t59_vet")
    assert r["status"] == "LINT_ERROR" and r["error_class"] == "vet" and "healing" in r


@needs_go
def test_compact_build_drops_fix_diff(build_env: None) -> None:
    r = _build(MESSY, name="t59_compact", verbosity="summary")
    assert "fix_diff" not in r["healing"] and r["healing"]["fix_lines"] > 0
