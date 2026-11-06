"""ONT-42b B2 (AE-1): resolve_gap, orden id -> ref -> sufijo -> subcadena; ambigüedad; ciclo con id canónico."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import threads_ops as ops
from engine import threads_spec as spec
from engine import threads_verify as tv
from engine.threads import resolve_in
from engine.threads_model import Gap
from tests.test_ont41_spec import _fake, _graph


def _g(gid: str, ref: str = "", score: float = 0.0) -> Gap:
    return Gap(gid, "open_discrepancy" if ref else "omission", f"node:{gid}", 0.5, "x", ref=ref, score=score)


GAPS = [
    _g("drift:open:D-01b:test:tests/a.py::t1", "D-01b", 2.0),
    _g("drift:open:D-01b:test:tests/b.py::t2", "D-01b", 5.0),
    _g("drift:claim:README.md:x", "D-14"),
    _g("omission:fn:pkg.mod.run_job:in:covers"),
    _g("omission:fn:pkg.mod.run_jobs:in:covers"),
]


def test_exact_id_wins_over_everything() -> None:
    gap, extra = resolve_in(GAPS, "omission:fn:pkg.mod.run_job:in:covers")
    assert gap is GAPS[3] and extra == {}


def test_ref_is_case_insensitive_and_picks_highest_score_with_alternatives() -> None:
    gap, extra = resolve_in(GAPS, "d-01B")
    assert gap is GAPS[1]
    assert extra == {"alternatives": [GAPS[0].id]}


def test_unique_suffix_then_unique_substring() -> None:
    assert resolve_in(GAPS, "README.md:x")[0] is GAPS[2]
    assert resolve_in(GAPS, "run_jobs")[0] is GAPS[4]


def test_ambiguous_returns_none_with_similar() -> None:
    gap, extra = resolve_in(GAPS, "in:covers")
    assert gap is None
    assert sorted(extra["similar"]) == sorted([GAPS[3].id, GAPS[4].id])


def test_no_match_returns_none_and_close_matches() -> None:
    assert resolve_in(GAPS, "zzzzzz") == (None, {"similar": []})
    gap, extra = resolve_in(GAPS, "D-14b")
    assert gap is None and "drift:claim:README.md:x" in extra["similar"]
    assert resolve_in(GAPS, "") == (None, {"similar": []})


def test_resolve_target_uses_frozen_base_meta() -> None:
    base = {"gaps": [g.id for g in GAPS], "gap_meta": {g.id: [g.ref, g.score] for g in GAPS if g.ref}}
    assert ops.resolve_target(base, "D-01b") == (GAPS[1].id, None)
    assert ops.resolve_target(base, None) == (None, None)
    gid, missing = ops.resolve_target(base, "nope-nope")
    assert gid is None and missing is not None and missing["status"] == "NOT_FOUND"


def test_build_spec_by_ref_reports_alternatives() -> None:
    out = spec.build_spec(_fake(GAPS[:2], _graph()), "D-01b")
    assert out["gap"]["id"] == GAPS[1].id
    assert out["alternatives"] == [GAPS[0].id]


def test_open_cycle_stores_canonical_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = {"root": "r", "gaps": [g.id for g in GAPS], "gap_meta": {GAPS[1].id: ["D-01b", 5.0]}, "hashes": {}}
    monkeypatch.setattr(ops, "base_summary", lambda *a, **k: (base, "tree"))
    store = tv.CycleStore(base_dir=tmp_path / "shm")
    out = ops._open_cycle(store, tmp_path, "d-01b", None, True, ops.SUMMARY_BUDGET)
    assert out["status"] == "OK", out
    assert store.load(out["cycle"])["gap"] == GAPS[1].id
    miss = ops._open_cycle(store, tmp_path, "unknown-gap", None, True, ops.SUMMARY_BUDGET)
    assert miss["status"] == "NOT_FOUND"
