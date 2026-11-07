"""Dokimos D-EV-1b: la huella juzgada debe tomarse ANTES de correr los tests (no despues)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine import threads_verify as tv
from tests.test_ont41_ops import GAP, GREEN, _fix, trees  # noqa: F401  (fixture reutilizada)


def _fp(tree: Path | str) -> str:
    return hashlib.sha256((Path(tree) / "engine" / "m.py").read_bytes()).hexdigest()


@pytest.mark.xfail(strict=True, reason="D-EV-1b: tree_fingerprint se calcula tras judge(); una mutacion durante los tests queda bendecida")
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
