"""ONT-67 T4: a cached Analysis must not keep the parsed AST of the whole tree alive."""

from __future__ import annotations

import ast
import gc
import textwrap
from pathlib import Path

from engine import threads


def _make_tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "server.py").write_text(
        textwrap.dedent(
            """
            import pkg.mod

            def helper(x):
                return pkg.mod.double(x)
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")
    return tmp_path


def _live_ast_nodes() -> int:
    return sum(1 for o in gc.get_objects() if isinstance(o, ast.AST))


def test_build_graph_releases_type_index(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    src = threads.ex.read_sources(root)
    _graph, info = threads.ex.build_graph(src)
    assert info.type_index is None
    assert isinstance(info.external_skipped, int)


def test_cached_analysis_does_not_retain_ast_nodes() -> None:
    threads.clear_cache()
    gc.collect()
    before = _live_ast_nodes()
    repo = Path(__file__).resolve().parent.parent
    analysis = threads.analyze(repo)
    del analysis
    gc.collect()
    held = _live_ast_nodes() - before
    assert len(threads._CACHE) >= 1
    # The repo parses to >1M nodes; the cache entry (graph, ranks, gaps) must hold none of them.
    assert held < 20_000, f"cache retains {held} AST nodes"
    threads.clear_cache()


def test_cache_hit_still_returns_same_graph(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    threads.clear_cache()
    first = threads.analyze(root)
    second = threads.analyze(root)
    assert second.cached is True and second.root_hash == first.root_hash
    threads.clear_cache()
