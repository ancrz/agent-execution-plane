"""ONT-40 T17 (SDD §6 corregido por DQ-1): aceptación sobre la realidad pre-L1 (b2afeb2) y sobre HEAD."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from engine import threads
from tests._threads_support import PRE_L1_COMMIT, commit_exists, detached_worktree

REPO = Path(__file__).resolve().parent.parent


def _refs(analysis: threads.Analysis) -> set[str]:
    return {g.ref for g in analysis.gaps if g.ref}


@pytest.mark.skipif(not commit_exists(PRE_L1_COMMIT), reason="pre-L1 commit not in this clone")
def test_pre_l1_static_gaps_d11_d12_d14() -> None:
    with detached_worktree(PRE_L1_COMMIT) as wt:
        analysis = threads.analyze(wt, use_cache=False)
        refs = _refs(analysis)
        assert {"D-11", "D-12", "D-14"} <= refs, refs
        assert analysis.scc.codependencies == []  # SCC_codep = vacío (también con imports perezosos)


@pytest.mark.skipif(not commit_exists(PRE_L1_COMMIT), reason="pre-L1 commit not in this clone")
def test_pre_l1_probes_find_d01_and_d08() -> None:
    from engine.threads_probes import run_probes

    with detached_worktree(PRE_L1_COMMIT) as wt:
        analysis = threads.analyze(wt, use_cache=False)
        probes = run_probes(wt, tier_octal=6)
        if probes["status"] != "OK":
            pytest.skip(f"probe could not run in this environment: {probes}")
        refs = _refs(threads.with_probes(analysis, probes))
        assert "D-01" in refs
        has_crash_dir = Path("/var/crash").is_dir()
        if has_crash_dir:  # D-08 solo es observable si el host tiene /var/crash y no hay coredumpctl
            obs = {o["probe"]: o for o in probes["observations"]}
            assert ("D-08" in refs) == (not obs["crash_forensics_ready"]["ok"])


def test_head_l3_and_closed_discrepancies_absent() -> None:
    analysis = threads.analyze(REPO, use_cache=False)
    refs = _refs(analysis)
    # L3 closed D-01..D-05 (strict xfails removed); earlier-closed ones stay absent.
    assert not {"D-01", "D-02", "D-03a", "D-03b", "D-04", "D-05", "D-08", "D-11", "D-12", "D-14"} & refs, refs
    assert analysis.scc.codependencies == []


def test_cold_extraction_under_two_seconds_and_stable_r() -> None:
    start = time.perf_counter()
    first = threads.analyze(REPO, use_cache=False)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, elapsed
    assert threads.analyze(REPO, use_cache=False).root_hash == first.root_hash


def test_r_changes_with_semantic_change_and_not_with_comment(tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "t"
    shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".claude"))
    base = threads.analyze(copy, use_cache=False).root_hash
    target = copy / "engine" / "ponder.py"
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n# comment only\n", encoding="utf-8")
    assert threads.analyze(copy, use_cache=False).root_hash == base
    target.write_text(original + "\ndef brand_new_fn():\n    return 1\n", encoding="utf-8")
    changed = threads.analyze(copy, use_cache=False)
    assert changed.root_hash != base
    assert any(g.id == "omission:fn:engine.ponder.brand_new_fn:in:covers" for g in changed.gaps)
    target.write_text("def broken(:\n", encoding="utf-8")
    broken = threads.analyze(copy, use_cache=False)
    assert any(g.kind == "syntax_error" for g in broken.gaps)
