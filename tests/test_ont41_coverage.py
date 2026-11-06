"""ONT-41 TA0/TA1: el grafo cubre `aep_*.py` de nivel superior y la capa de cobertura no altera R ni gaps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import threads
from engine import threads_extractors as ex
from engine.threads_model import Node, ThreadGraph

REPO = Path(__file__).resolve().parent.parent
GAPS_BASELINE = 103


def _graph() -> ThreadGraph:
    g = ThreadGraph()
    g.add_node(Node("test", "test:t::test_a", "h"))
    for name, public in (("a", True), ("b", True), ("c", False), ("orphan", True)):
        g.add_node(Node("function", f"fn:m.{name}", "h", {"public": public, "module": "m"}))
    g.add_edge("test:t::test_a", "fn:m.a", "covers")
    g.add_edge("fn:m.a", "fn:m.b", "consumes")
    g.add_edge("fn:m.b", "fn:m.c", "consumes")
    return g


@pytest.fixture(scope="module")
def analysis() -> threads.Analysis:
    return threads.analyze(REPO)


def test_coverage_map_levels_direct_transitive_none() -> None:
    cmap = threads.coverage_map(_graph())
    assert cmap == {
        "fn:m.a": threads.COVERAGE_DIRECT,
        "fn:m.b": threads.COVERAGE_TRANSITIVE,
        "fn:m.c": threads.COVERAGE_TRANSITIVE,
        "fn:m.orphan": threads.COVERAGE_NONE,
    }


def test_coverage_summary_counts_public_without_coverage() -> None:
    assert threads.coverage_summary(_graph()) == {
        "functions": 4,
        "direct": 1,
        "transitive": 2,
        "none": 1,
        "public_none": 1,
    }


def test_node_coverage_function_action_alias_and_missing() -> None:
    g = _graph()
    assert threads.node_coverage(g, "fn:m.a") == threads.COVERAGE_DIRECT
    assert threads.node_coverage(g, "fn:m.orphan", threads.coverage_map(g)) == threads.COVERAGE_NONE
    assert threads.node_coverage(g, "fn:missing") == threads.COVERAGE_NONE
    g.add_node(Node("action", "action:t:canon", "h"))
    g.add_node(Node("action", "action:t:alias", "h"))
    g.add_edge("action:t:alias", "action:t:canon", "alias_of")
    assert threads.node_coverage(g, "action:t:canon") == threads.COVERAGE_NONE
    g.add_edge("test:t::test_a", "action:t:alias", "covers")
    assert threads.node_coverage(g, "action:t:canon") == threads.COVERAGE_DIRECT  # la canónica hereda de su alias


def test_coverage_layer_is_read_only() -> None:
    g = _graph()
    before = (g.edge_count(), len(g.nodes), threads.merkle_root(g)[0], len(threads.omission_gaps(g)))
    threads.coverage_map(g)
    threads.coverage_summary(g)
    threads.node_coverage(g, "fn:m.a")
    after = (g.edge_count(), len(g.nodes), threads.merkle_root(g)[0], len(threads.omission_gaps(g)))
    assert before == after


def test_real_graph_gaps_do_not_grow_and_own_gaps_zero(analysis: threads.Analysis) -> None:
    assert len(analysis.gaps) <= GAPS_BASELINE
    assert threads.own_gaps(analysis) == []


def test_graph_terse_stays_under_300_tokens_and_has_no_coverage(analysis: threads.Analysis) -> None:
    terse = threads.graph_payload(analysis, terse=True)
    assert "coverage" not in terse
    assert len(json.dumps(terse, separators=(",", ":"))) / 4 < 300


def test_graph_full_and_thread_expose_coverage(analysis: threads.Analysis) -> None:
    full = threads.graph_payload(analysis)
    assert set(full["coverage"]) == {"functions", "direct", "transitive", "none", "public_none"}
    fid = "fn:engine.threads_verify.decide"
    assert analysis.graph.nodes[fid]
    assert threads.thread_payload(analysis, fid)["coverage"] == threads.COVERAGE_DIRECT
    assert threads.thread_payload(analysis, "tool:autoevol")["coverage"] in {"direct", "none"}


def test_root_is_deterministic_and_unchanged_by_coverage_calls(analysis: threads.Analysis) -> None:
    again = threads.analyze(REPO, use_cache=False)
    threads.coverage_map(again.graph)
    assert again.root_hash == analysis.root_hash
    assert [g.id for g in again.gaps] == [g.id for g in analysis.gaps]


def test_ta0_top_level_aep_modules_are_read_deterministically(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("def f():\n    return 1\n")
    (tmp_path / "aep_zeta.py").write_text("def z():\n    return 1\n")
    (tmp_path / "aep_lkg.py").write_text("def lkg():\n    return 1\n")
    (tmp_path / "other.py").write_text("x = 1\n")
    first = list(ex.read_sources(tmp_path).code)
    assert first == ["aep_lkg.py", "aep_zeta.py", "server.py"]
    assert list(ex.read_sources(tmp_path).code) == first


def test_ta0_missing_aep_lkg_is_tolerated(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("def f():\n    return 1\n")
    assert list(ex.read_sources(tmp_path).code) == ["server.py"]
    assert "module:aep_lkg" not in threads.analyze(tmp_path, use_cache=False).graph.nodes


def test_ta0_aep_lkg_enters_graph_when_present(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text("def f():\n    return 1\n")
    (tmp_path / "aep_lkg.py").write_text("def snapshot():\n    return 1\n")
    graph = threads.analyze(tmp_path, use_cache=False).graph
    assert "module:aep_lkg" in graph.nodes
    assert "fn:aep_lkg.snapshot" in graph.nodes
