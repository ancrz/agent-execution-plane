"""ONT-60 T5/G62: artifacts.stats_history keeps a bounded history of archived generations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import server
from engine import catalog as catalog_mod
from engine.catalog import STATS_HISTORY_MAX, ArtifactCatalog


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


@pytest.fixture
def cat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactCatalog:
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    return ArtifactCatalog(db_path=tmp_path / "artifacts.db")


def _reg(cat: ArtifactCatalog, n: int) -> str:
    return cat.register_artifact(
        name="probe",
        intent="i",
        category="c",
        cue_contract="{}",
        go_source=f"package main // v{n}\n",
        binary_blob=f"\x7fELF{n}".encode(),
        source_hash=f"{n:064x}",
        toolchain="go1.27.4",
    )


def _row(cat: ArtifactCatalog) -> sqlite3.Row:
    with cat._get_ro_conn() as conn:
        return conn.execute("SELECT * FROM artifacts WHERE name='probe'").fetchone()


def test_two_changes_without_execution_keep_both_generations(cat: ArtifactCatalog) -> None:
    assert server.catalog is not cat
    aid = _reg(cat, 1)
    cat.record_execution(aid, 0, 5.0)
    _reg(cat, 2)
    _reg(cat, 3)
    row = _row(cat)
    hist = json.loads(row["stats_history"])
    assert [h["source_hash"] for h in hist] == [f"{1:064x}", f"{2:064x}"]
    assert hist[0]["execution_count"] == 1 and hist[1]["execution_count"] == 0
    assert json.loads(row["previous_stats"]) == hist[-1]  # compat: previous_stats = última


def test_history_is_capped(cat: ArtifactCatalog) -> None:
    assert server.catalog is not cat
    for n in range(1, STATS_HISTORY_MAX + 5):
        _reg(cat, n)
    hist = json.loads(_row(cat)["stats_history"])
    assert len(hist) == STATS_HISTORY_MAX
    assert hist[-1]["source_hash"] == f"{STATS_HISTORY_MAX + 3:064x}"


def test_unchanged_register_does_not_touch_history(cat: ArtifactCatalog) -> None:
    assert server.catalog is not cat
    _reg(cat, 1)
    _reg(cat, 1)
    assert _row(cat)["stats_history"] is None


def test_pre_migration_previous_stats_seeds_history(cat: ArtifactCatalog) -> None:
    assert server.catalog is not cat
    _reg(cat, 1)
    legacy = json.dumps({"source_hash": "old", "toolchain": None, "success_rate": 0.5, "execution_count": 2})
    with cat._get_rw_conn() as conn:
        conn.execute("UPDATE artifacts SET previous_stats=? WHERE name='probe'", (legacy,))
    _reg(cat, 2)
    hist = json.loads(_row(cat)["stats_history"])
    assert [h["source_hash"] for h in hist] == ["old", f"{1:064x}"]


def test_migration_adds_column_idempotently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert server.catalog is not None
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    p = tmp_path / "c.db"
    ArtifactCatalog(db_path=p)
    ArtifactCatalog(db_path=p)
    with sqlite3.connect(p) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(artifacts)")}
    assert "stats_history" in cols
