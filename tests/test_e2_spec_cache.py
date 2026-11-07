"""E2: cache de `autoevol(spec)` por hilos (hit/miss, invalidacion, fail-open, stale_specs, paridad DDL)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from engine import threads as th
from engine import threads_spec as ts
from engine import threads_spec_cache as sc
from engine.threads_model import Gap
from tests.test_ont41_spec import _graph

ROOT = Path(__file__).resolve().parent.parent
GAP = Gap("omission:fn:pkg.mod.run_job:in:covers", "omission", "fn:pkg.mod.run_job", 0.3, "x")


def _analysis(hashes: dict[str, str] | None = None) -> SimpleNamespace:
    g = _graph()
    base = {nid: f"h-{nid}" for nid in g.nodes}
    base.update(hashes or {})
    return SimpleNamespace(gaps=[GAP], graph=g, node_hash=base)


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "c.db"
    sqlite3.connect(db).close()
    return db


def test_second_call_is_identical_hit(tmp_path: Path) -> None:
    db = _db(tmp_path)
    first = ts.cached_spec(_analysis(), GAP.id, db_path=db)
    second = ts.cached_spec(_analysis(), GAP.id, db_path=db)
    assert (first["cache"], second["cache"]) == ("miss", "hit")
    assert {k: v for k, v in second.items() if k != "cache"} == ts.build_spec(_analysis(), GAP.id)


def test_unrelated_thread_change_hits_scope_change_misses(tmp_path: Path) -> None:
    db = _db(tmp_path)
    ts.cached_spec(_analysis(), GAP.id, db_path=db)
    assert ts.cached_spec(_analysis({"fn:pkg.other.go": "changed"}), GAP.id, db_path=db)["cache"] == "hit"
    assert ts.cached_spec(_analysis({"module:pkg.mod": "changed"}), GAP.id, db_path=db)["cache"] == "miss"
    assert ts.cached_spec(_analysis({"fn:pkg.mod.run_job": "x2"}), GAP.id, db_path=db)["cache"] == "miss"


def test_missing_or_broken_db_is_miss_without_error(tmp_path: Path) -> None:
    out = ts.cached_spec(_analysis(), GAP.id, db_path=tmp_path / "nope" / "x.db")
    assert out["cache"] == "miss" and out["status"] == "OK"
    assert not (tmp_path / "nope").exists()
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite file" * 50)
    assert ts.cached_spec(_analysis(), GAP.id, db_path=bad)["cache"] == "miss"


def test_read_only_tier_does_not_persist(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert ts.cached_spec(_analysis(), GAP.id, db_path=db, write=False)["cache"] == "miss"
    assert ts.cached_spec(_analysis(), GAP.id, db_path=db)["cache"] == "miss"


def test_terse_budget_and_not_found_untagged(tmp_path: Path) -> None:
    db = _db(tmp_path)
    for _ in range(2):
        out = ts.cached_spec(_analysis(), GAP.id, terse=True, db_path=db)
        assert ts._estimated_tokens(out) <= ts.TERSE_MAX_TOKENS
    assert out["cache"] == "hit"
    assert "cache" not in ts.cached_spec(_analysis(), "no-such-gap", db_path=db)


def test_diff_lists_stale_specs(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    a = th.analyze(ROOT)
    th.persist_generation(a, db_path=db, tier_octal=6)
    nid = min(a.node_hash)
    sc._store(db, "g-stale", False, "k", {nid: "x"}, {"status": "OK"})
    sc._store(db, "g-fresh", False, "k", {"other:node": "x"}, {"status": "OK"})
    fields = {f: getattr(a, f) for f in type(a).__slots__}
    mutated = type(a)(**{**fields, "node_hash": {**a.node_hash, nid: "zz"}, "root_hash": "e" * 64})
    out = th.diff_generations("1", db_path=db, current=mutated)
    assert out["stale_specs"] == ["g-stale"] and out["stale_specs_total"] == 1
    assert th.diff_generations("1", db_path=db, current=a)["stale_specs"] == []
    assert sc.stale_specs(set(), db_path=db) == [] and sc.stale_specs({nid}, db_path=tmp_path / "none.db") == []


def test_ddl_parity_with_database_sql() -> None:
    sql = " ".join((ROOT / "schemas" / "database.sql").read_text(encoding="utf-8").split())
    assert " ".join(sc.DDL.split()) + ";" in sql
