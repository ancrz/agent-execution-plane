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


def test_walk_is_memoised_per_analysis_without_touching_nodes():
    tree = ast.parse("def f(a):\n    return {'k': a + 1}\n")
    before = ast.dump(tree)
    token = ex._WALK_CACHE.set({})
    try:
        first = ex._walk(tree)
        assert ex._walk(tree) is first
        assert ex._type_index(tree) is ex._type_index(tree)
    finally:
        ex._WALK_CACHE.reset(token)
    assert ex._WALK_CACHE.get() is None
    assert ex._walk(tree) == first and ex._walk(tree) is not first  # sin cache activa se recalcula
    assert all(
        not k.startswith("_aep_walk") and not k.startswith("_aep_index") for n in ast.walk(tree) for k in n.__dict__
    )
    assert ast.dump(tree) == before
    assert ex._fast_dump(tree) == before


def test_build_graph_releases_cache_on_error():
    class Boom(Exception):
        pass

    orig = ex._build_graph
    ex._build_graph = lambda src: (_ for _ in ()).throw(Boom())  # type: ignore[assignment]
    try:
        try:
            ex.build_graph(None)  # type: ignore[arg-type]
        except Boom:
            pass
    finally:
        ex._build_graph = orig
    assert ex._WALK_CACHE.get() is None


def test_type_index_preserves_walk_order_per_type():
    for tree in _trees():
        walk = list(ast.walk(tree))
        for cached in (False, True):
            token = ex._WALK_CACHE.set({}) if cached else None
            try:
                index = ex._type_index(tree)
            finally:
                if token is not None:
                    ex._WALK_CACHE.reset(token)
            assert sum(len(v) for v in index.values()) == len(walk)
            for typ in (ast.Constant, ast.Dict):
                assert index.get(typ, []) == [n for n in walk if type(n) is typ]
