"""ONT-53 (G40): `_bfs`/`_walk`/`_type_index` son equivalentes a `ast.walk` (mismos nodos, mismo orden)."""

from __future__ import annotations

import ast
from pathlib import Path

from engine import threads_extractors as ex

ROOT = Path(__file__).resolve().parent.parent
_FILES = ["server.py", "engine/threads_extractors.py", "engine/privilege.py", "tests/test_ont53_walk_index.py"]


def _trees() -> list[ast.Module]:
    return [ast.parse((ROOT / rel).read_text(encoding="utf-8")) for rel in _FILES]


def test_bfs_matches_ast_walk_order():
    for tree in _trees():
        assert ex._bfs(tree) == list(ast.walk(tree))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))][:50]:
            assert ex._bfs(fn) == list(ast.walk(fn))


def test_walk_is_memoised_and_does_not_alter_dump():
    tree = ast.parse("def f(a):\n    return {'k': a + 1}\n")
    before = ast.dump(tree)
    first = ex._walk(tree)
    assert ex._walk(tree) is first
    assert ast.dump(tree) == before
    assert ex._fast_dump(tree) == before


def test_type_index_preserves_walk_order_per_type():
    for tree in _trees():
        index = ex._type_index(tree)
        walk = list(ast.walk(tree))
        assert sum(len(v) for v in index.values()) == len(walk)
        for typ in (ast.Constant, ast.Dict):
            assert index.get(typ, []) == [n for n in walk if type(n) is typ]
