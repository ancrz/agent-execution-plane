"""ONT-69 T4: the extractor follows module-level dict registries (`RUNNERS[name](...)`) as weak consumes edges."""

from __future__ import annotations

from pathlib import Path

from engine import threads_extractors as ex
from engine.threads_model import ThreadGraph

FILES = {
    "engine/__init__.py": "",
    "engine/runners.py": (
        "def run_a():\n    return 1\n\n"
        "def run_b():\n    return 2\n\n"
        "def run_c():\n    return 3\n\n"
        "def build_other():\n    return 4\n\n"
        "BASE = {'a': run_a, 'b': lambda: run_b()}\n"
        "TABLE = {**BASE, 'c': run_c, 'd': build_other()}\n"
    ),
    "engine/dispatch.py": (
        "from engine.runners import TABLE\nfrom engine import runners\n\n"
        "def go(name):\n    return TABLE[name]()\n\n"
        "def go_attr(name):\n    return runners.TABLE[name]()\n\n"
        "def unrelated():\n    return 0\n"
    ),
}


def _build(root: Path) -> ThreadGraph:
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    graph, _ = ex.build_graph(ex.read_sources(root))
    return graph


def _consumes(g: ThreadGraph, src: str) -> dict[str, bool]:
    return {e.dst: e.weak for e in g.out_edges(f"fn:{src}", "consumes")}


def test_registry_members_become_weak_consumes_including_spread_and_lambda(tmp_path: Path) -> None:
    g = _build(tmp_path)
    expected = {"fn:engine.runners.run_a", "fn:engine.runners.run_b", "fn:engine.runners.run_c"}
    for caller in ("engine.dispatch.go", "engine.dispatch.go_attr"):
        edges = _consumes(g, caller)
        assert expected <= set(edges)
        assert all(edges[t] for t in expected)  # weak
        assert "fn:engine.runners.build_other" not in edges  # a call result is not a dispatch member
    assert not set(_consumes(g, "engine.dispatch.unrelated")) & expected
