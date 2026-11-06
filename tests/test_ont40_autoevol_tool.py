"""ONT-40 T14/T15 (F2, F9, F10, C4, C7): tool 17 `autoevol`, gate de tier, budget terse e imports."""

from __future__ import annotations

import ast
import asyncio
import json
import re
import sqlite3
from pathlib import Path

import pytest

import server
from engine import threads
from engine.privilege import _PrivilegeCache, get_effective_chmod_tier
from tests.test_live_plane_ont39 import test_criterion_4_list_changed_notification

REPO = Path(__file__).resolve().parent.parent


def _call(**kw: object) -> dict:
    return json.loads(asyncio.run(server.autoevol(**kw)))  # type: ignore[arg-type]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """HOME temporal: nunca se toca la BD ni el ledger reales."""
    monkeypatch.setenv("HOME", str(tmp_path))
    yield tmp_path
    _PrivilegeCache.reset()


def test_tool_registered_without_output_schema() -> None:
    tool = server.mcp._tool_manager.list_tools()
    names = {t.name: t for t in tool}
    assert "autoevol" in names and names["autoevol"].output_schema is None


@pytest.mark.parametrize("act", ["spec", "verify", "heal", "evolve", "bogus"])
def test_planned_and_unknown_actions_invalid(act: str) -> None:
    res = _call(action=act)
    assert res["status"] == "INVALID_ACTION" and "graph" in res["valid_actions"]


def test_graph_terse_budget_under_300_tokens(isolated_home: Path) -> None:
    """F10: graph en modo terse cuesta menos de 300 tokens."""
    res = _call(action="graph", verbosity="terse", persist=False)
    assert res["t"]["tok"] < 300, res["t"]
    assert res["nodes"] > 100 and len(res["root"]) == 16


@pytest.mark.parametrize(("tier", "persists"), [("7rwx", True), ("6rw-", True), ("5r-x", False), ("4r--", False)])
def test_persistence_gate_by_tier(tier: str, persists: bool, isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4: AEP_FORCE_TIER + get_effective_chmod_tier(force_refresh=True)."""
    monkeypatch.setenv("AEP_FORCE_TIER", tier)
    assert get_effective_chmod_tier(force_refresh=True)["tier"] == tier
    res = _call(action="graph", verbosity="terse")
    assert res["persisted"] is persists
    db = isolated_home / ".local" / "share" / "agent-os" / "artifacts.db"
    assert db.exists() is persists
    log = _call(action="log")
    assert log["total"] == (1 if persists else 0)


def test_log_and_diff_tolerate_missing_table(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    get_effective_chmod_tier(force_refresh=True)
    assert _call(action="log")["total"] == 0
    assert _call(action="diff", a="1")["status"] == "NO_GENERATIONS"
    db = isolated_home / ".local" / "share" / "agent-os"
    db.mkdir(parents=True)
    sqlite3.connect(db / "artifacts.db").close()  # BD sin threads_gen
    assert _call(action="log")["total"] == 0
    assert _call(action="diff", a="1")["status"] == "NO_GENERATIONS"


def test_probe_skipped_at_4r(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_FORCE_TIER", "4r--")
    get_effective_chmod_tier(force_refresh=True)
    res = _call(action="graph", probe=True, persist=False)
    assert res["probe"] == "SKIPPED"


def test_thread_and_gaps_actions() -> None:
    thread = json.loads(asyncio.run(server.autoevol(action="thread", node="tool:autoevol")))
    assert thread["status"] == "OK"
    gaps = json.loads(asyncio.run(server.autoevol(action="gaps", limit=3)))
    assert len(gaps["gaps"]) == 3
    projected = json.loads(asyncio.run(server.autoevol(action="gaps", select_fields=["gaps_open"])))
    assert "gaps_open" in projected


def test_own_gaps_are_zero_for_the_right_reasons() -> None:
    """F12/criterio 7: `autoevol` no tiene gaps propios (tool, acciones, módulos threads*, tests ONT-40)."""
    analysis = threads.analyze(REPO)
    assert [g.id for g in threads.own_gaps(analysis)] == []
    assert json.loads(asyncio.run(server.autoevol(action="gaps", limit=1)))["own_gaps"] == 0


def test_log_diff_actions_literal(isolated_home: Path) -> None:
    log = json.loads(asyncio.run(server.autoevol(action="log")))
    diff = json.loads(asyncio.run(server.autoevol(action="diff", a="1")))
    assert log["total"] == 0 and diff["status"] == "NO_GENERATIONS"


def test_playbook_dispatch_whitelists_autoevol() -> None:
    assert "autoevol" in server._playbook_dispatch()


def test_schema_hash_covers_autoevol_and_notifies_on_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """C7: el schema_hash cambia sin `autoevol` (=> send_tool_list_changed); reutiliza criterion_4."""
    full = server._get_schema_hash()
    manager = server.mcp._tool_manager
    reduced = {k: v for k, v in manager._tools.items() if k != "autoevol"}
    monkeypatch.setattr(manager, "_tools", reduced)
    assert server._get_schema_hash() != full
    monkeypatch.undo()
    test_criterion_4_list_changed_notification()


def test_instructions_declare_17_tools() -> None:
    assert "17 typed JSON-RPC tools" in server._INSTRUCTIONS
    assert "Complete 17-Tool Suite Map" in server._INSTRUCTIONS
    assert "autoevol(" in server._INSTRUCTIONS


def test_threads_never_imports_server() -> None:
    """F7/F6: ningún módulo threads* importa `server` (ni lazy)."""
    assert threads.GRAPH_SCHEMA_VERSION.startswith("threads/")
    for path in sorted((REPO / "engine").glob("threads*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "server" for a in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "server", path


def test_threads_gen_ddl_parity_with_database_sql() -> None:
    sql = (REPO / "schemas" / "database.sql").read_text(encoding="utf-8")
    m = re.search(r"CREATE TABLE IF NOT EXISTS threads_gen \(.*?\n\);", sql, re.DOTALL)
    assert m
    norm = lambda s: " ".join(re.sub(r"--[^\n]*", "", s).replace(";", "").split())  # noqa: E731
    assert norm(m.group(0)) == norm(threads.THREADS_GEN_DDL)
