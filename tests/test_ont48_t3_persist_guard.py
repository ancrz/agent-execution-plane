"""ONT-48 T3 (G16/G26): persist_generation refuses foreign roots, unknown commits and node-count collapses."""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

from engine import threads

REPO = Path(__file__).resolve().parent.parent


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "mod_a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return root


def test_foreign_root_not_persisted(tmp_path: Path) -> None:
    analysis = threads.analyze(_tree(tmp_path))
    db = tmp_path / "t.db"
    res = threads.persist_generation(analysis, db_path=db, tier_octal=6, server_root=REPO)
    assert res == {"persisted": False, "reason": "foreign_root"}
    assert not db.exists()


def test_unknown_commit_not_persisted(tmp_path: Path) -> None:
    analysis = dataclasses.replace(threads.analyze(_tree(tmp_path)), git_commit="unknown")
    db = tmp_path / "t.db"
    res = threads.persist_generation(analysis, db_path=db, tier_octal=6)
    assert res == {"persisted": False, "reason": "unknown_commit"}
    assert not db.exists()


def test_node_count_drop_not_persisted_and_root_path_recorded(tmp_path: Path) -> None:
    analysis = dataclasses.replace(threads.analyze(_tree(tmp_path)), git_commit="abc1234")
    db = tmp_path / "t.db"
    first = threads.persist_generation(analysis, db_path=db, tier_octal=6)
    assert first["persisted"] is True
    conn = sqlite3.connect(db)
    root_path = conn.execute("SELECT root_path FROM threads_gen").fetchone()[0]
    assert root_path == str(analysis.root.resolve())
    conn.execute("UPDATE threads_gen SET node_count = 100000")
    conn.commit()
    conn.close()
    drifted = dataclasses.replace(analysis, root_hash="f" * 64)
    res = threads.persist_generation(drifted, db_path=db, tier_octal=6)
    assert res == {"persisted": False, "reason": "node_count_drop"}
    assert threads.list_generations(db_path=db)["generations"][0]["root_path"] == root_path


def test_legacy_table_gets_root_path_column(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    legacy_ddl = threads.THREADS_GEN_DDL.replace(",\n    root_path TEXT NOT NULL DEFAULT ''", "")
    conn.execute(legacy_ddl)
    conn.commit()
    conn.close()
    analysis = dataclasses.replace(threads.analyze(_tree(tmp_path)), git_commit="abc1234")
    assert threads.persist_generation(analysis, db_path=db, tier_octal=6)["persisted"] is True
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(threads_gen)")]
    conn.close()
    assert "root_path" in cols
    # second call is idempotent (no duplicate ALTER)
    assert threads.persist_generation(analysis, db_path=db, tier_octal=6)["persisted"] is True
