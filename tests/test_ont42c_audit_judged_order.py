"""Dokimos D-EV-1b: la huella juzgada debe tomarse ANTES de correr los tests (no despues)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine import threads_verify as tv
from tests.test_ont41_ops import GAP, GREEN, _fix, isolated_home, trees  # noqa: F401  (fixtures reutilizadas)


def _fp(tree: Path | str) -> str:
    return hashlib.sha256((Path(tree) / "engine" / "m.py").read_bytes()).hexdigest()


def test_tree_mutated_during_judge_is_not_blessed(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, new, gap=GAP, snapshot=base, tree_fingerprint=_fp)["cycle"]
    before = _fp(new)

    def mutating_tests(tree: Path | str) -> dict[str, int]:
        (new / "engine" / "m.py").write_text("def _f():\n    return 1  # mutated by tests\n", encoding="utf-8")
        return GREEN

    _fix(store, new, cycle=cid, snapshot=base, run_tests=mutating_tests, tree_fingerprint=_fp)
    rec = store.load(cid) or {}
    judged = (rec.get("judged") or {}).get("tree")
    assert judged in (None, before), "ACCEPT atado a un arbol distinto del que se juzgo"
    assert rec["state"] != tv.ACCEPTED and rec["iteration"] == 1  # consume iteracion


def test_mutation_reason_is_degraded_reject(trees: tuple[Path, Path]) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    cid = _fix(store, new, gap=GAP, snapshot=base, tree_fingerprint=_fp)["cycle"]

    def mutating_tests(tree: Path | str) -> dict[str, int]:
        (new / "engine" / "m.py").write_text("def _f():\n    return 2\n", encoding="utf-8")
        return GREEN

    out = _fix(store, new, cycle=cid, snapshot=base, run_tests=mutating_tests, tree_fingerprint=_fp)
    assert out["verdict"] == tv.REJECT and tv.TREE_MUTATED_DURING_JUDGE in out["reasons"]
    assert out.get("consumed") is not False


def test_tree_edited_between_async_dispatch_and_poll_is_rejected(
    trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    monkeypatch.setattr(tv, "TESTS_PER_ITERATION", 0)
    cid = _fix(store, new, gap=GAP, snapshot=base, tree_fingerprint=_fp)["cycle"]
    pend = _fix(store, new, cycle=cid, snapshot=base, dispatch_job=lambda t: {"job": "9"}, tree_fingerprint=_fp)
    assert pend["awaiting"] == "job"
    (new / "engine" / "m.py").write_text("def _f():\n    return 3\n", encoding="utf-8")  # edicion entre dispatch y poll
    final = _fix(store, new, cycle=cid, snapshot=base, poll_job=lambda j: GREEN, tree_fingerprint=_fp)
    assert final["verdict"] == tv.REJECT and tv.TREE_MUTATED_DURING_JUDGE in final["reasons"]
    assert (store.load(cid) or {}).get("state") != tv.ACCEPTED


def test_async_unchanged_tree_is_accepted(trees: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    base, new = trees
    store = tv.CycleStore(base_dir=base.parent / "shm")
    monkeypatch.setattr(tv, "TESTS_PER_ITERATION", 0)
    cid = _fix(store, new, gap=GAP, snapshot=base, tree_fingerprint=_fp)["cycle"]
    _fix(store, new, cycle=cid, snapshot=base, dispatch_job=lambda t: {"job": "9"}, tree_fingerprint=_fp)
    final = _fix(store, new, cycle=cid, snapshot=base, poll_job=lambda j: GREEN, tree_fingerprint=_fp)
    assert final["state"] == tv.ACCEPTED and (store.load(cid) or {})["judged"]["tree"] == _fp(new)
