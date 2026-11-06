"""ONT-41 TA2: mini-SDD determinista por tipo de gap, alcance, tests impactados, nombre canónico y presupuestos."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import threads
from engine import threads_spec as spec
from engine.threads_model import Gap, Node, ThreadGraph

REPO = Path(__file__).resolve().parent.parent


def _tokens(payload: dict) -> int:
    return round(len(json.dumps(payload, separators=(",", ":")).encode()) / 4)


def _fake(gaps: list[Gap], graph: ThreadGraph | None = None) -> SimpleNamespace:
    g = graph or ThreadGraph()
    return SimpleNamespace(gaps=gaps, graph=g)


def _graph() -> ThreadGraph:
    g = ThreadGraph()
    g.add_node(Node("module", "module:pkg.mod", "h", {"path": "pkg/mod.py"}))
    g.add_node(Node("function", "fn:pkg.mod.run_job", "h", {"module": "pkg.mod", "public": True}))
    g.add_node(Node("function", "fn:pkg.mod.run_jobs", "h", {"module": "pkg.mod", "public": True}))
    g.add_node(Node("function", "fn:pkg.other.go", "h", {"module": "pkg.other", "public": True}))
    g.add_node(Node("test", "test:tests/t.py::test_mod_run_job", "h", {"file": "tests/t.py", "name": "test_mod_run_job"}))
    g.add_node(Node("tool", "tool:tl", "h"))
    g.add_node(Node("action", "action:tl:act", "h"))
    g.add_node(Node("state", "state:tbl", "h"))
    g.add_node(Node("claim", "claim:README.md:x", "h", {"file": "README.md"}))
    g.add_node(Node("capability", "capability:cap", "h"))
    g.add_edge("tool:tl", "fn:pkg.mod.run_job", "implemented_by")
    g.add_edge("action:tl:act", "fn:pkg.mod.run_job", "implemented_by")
    g.add_edge("test:tests/t.py::test_mod_run_job", "fn:pkg.mod.run_job", "covers")
    return g


@pytest.fixture(scope="module")
def real() -> threads.Analysis:
    return threads.analyze(REPO)


@pytest.mark.parametrize(
    ("edge", "needle"),
    [
        ("in:covers", "test"),
        ("in:routes", "capability"),
        ("in:asserts", "Document"),
        ("out:implemented_by", "Implement"),
        ("out:privileged_by", "tier"),
        ("out:routes", "Map capability"),
        ("out:covers", "call"),
        ("out:asserts", "budget"),
        ("in:writes", "Write"),
    ],
)
def test_omission_template_per_missing_edge(edge: str, needle: str) -> None:
    gap = Gap(f"omission:tool:tl:{edge}", "omission", "tool:tl", 0.5, "x")
    out = spec.build_spec(_fake([gap], _graph()), gap.id)
    assert out["status"] == "OK"
    text = json.dumps(out)
    assert needle.lower() in text.lower()
    assert out["gap"]["id"] == gap.id


@pytest.mark.parametrize(
    ("kind", "node", "needle"),
    [
        ("claim_drift", "claim:README.md:x", "Align"),
        ("open_discrepancy", "test:tests/t.py::test_mod_run_job", "xfail"),
        ("syntax_error", "module:pkg.mod", "syntax"),
        ("codependency", "module:pkg.mod", "Extract"),
        ("forbidden_edge", "module:pkg.mod", "import"),
        ("probe_drift", "module:pkg.mod", "promise"),
        ("unknown_kind", "module:pkg.mod", "Resolve"),
    ],
)
def test_non_omission_templates(kind: str, node: str, needle: str) -> None:
    gap = Gap(f"{kind}:1", kind, node, 0.9, "detail", ref="D-99")
    out = spec.build_spec(_fake([gap], _graph()), gap.id)
    assert needle.lower() in json.dumps(out).lower()


def test_unknown_omission_edge_falls_back_to_generic_template() -> None:
    gap = Gap("omission:tool:tl:in:weird", "omission", "tool:tl", 0.5, "x")
    assert "Connect" in json.dumps(spec.build_spec(_fake([gap], _graph()), gap.id))


def test_not_found_returns_similar() -> None:
    gap = Gap("omission:fn:a:in:covers", "omission", "fn:a", 0.3, "x")
    out = spec.build_spec(_fake([gap]), "omission:fn:a:on:covers")  # AE-1: 'covers' ya resuelve por sufijo único; ahora NOT_FOUND usa coincidencia aproximada
    assert out == {"status": "NOT_FOUND", "gap": "omission:fn:a:on:covers", "similar": ["omission:fn:a:in:covers"]}


def test_scope_files_per_node_type() -> None:
    a = _fake([], _graph())
    files = spec._files_for
    assert files(a, "fn:pkg.mod.run_job") == ["pkg/mod.py"]
    assert files(a, "fn:pkg.other.go") == ["pkg/other.py"]
    assert files(a, "module:pkg.mod") == ["pkg/mod.py"]
    assert files(a, "test:tests/t.py::test_mod_run_job") == ["tests/t.py"]
    assert files(a, "claim:README.md:x") == ["README.md"]
    assert files(a, "tool:tl") == ["pkg/mod.py"]
    assert files(a, "state:tbl") == ["schemas/database.sql"]
    assert files(a, "capability:cap") == []
    assert files(a, "missing") == []
    bare = _graph()
    bare.add_node(Node("action", "action:tl:orphan", "h"))
    assert files(_fake([], bare), "action:tl:orphan") == ["server.py"]


def test_impacted_tests_are_part_of_validate() -> None:
    gap = Gap("omission:fn:pkg.mod.run_job:in:covers", "omission", "fn:pkg.mod.run_job", 0.3, "x")
    out = spec.build_spec(_fake([gap], _graph()), gap.id)
    assert out["validate"]["tests"] == ["test:tests/t.py::test_mod_run_job"]
    assert out["validate"]["no_new_gaps"] is True
    terse = spec.build_spec(_fake([gap], _graph()), gap.id, terse=True)
    assert terse["tests"] == ["test:tests/t.py::test_mod_run_job"]


def test_canonical_name_uses_matcher_and_avoids_collision() -> None:
    g = _graph()
    name = spec.canonical_name(_fake([], g), "fn:pkg.mod.run_job")
    assert name["name"] == "test_mod_run_job_2"  # test_mod_run_job ya existe
    assert name["neighbors"][0] == "fn:pkg.mod.run_jobs"
    plain = spec.canonical_name(_fake([], g), "tool:tl")
    assert plain["name"] == "tl"
    assert spec.canonical_name(_fake([], g), "fn:pkg.other.go")["name"] == "test_other_go"
    assert spec.canonical_name(_fake([], g), "")["name"] == "unnamed"


def test_fit_truncates_lists_then_drops_optional_keys() -> None:
    big = {"plan": ["x" * 400] * 10, "tasks": ["y" * 400] * 10, "neighbors": ["z" * 400] * 10}
    out = spec._fit(big, 300, ("plan", "tasks"))
    assert out["truncated"] is True
    assert _tokens(out) <= 300
    nested = {"validate": {"tests": ["t" * 100] * 40}}
    assert _tokens(spec._fit(nested, 200, ())) <= 200


def test_real_gaps_respect_token_budgets(real: threads.Analysis) -> None:
    ids = [g.id for g in real.gaps[:25]]
    assert ids
    for gid in ids:
        terse = spec.build_spec(real, gid, terse=True)
        full = spec.build_spec(real, gid)
        assert terse["status"] == full["status"] == "OK"
        assert _tokens(terse) <= spec.TERSE_MAX_TOKENS
        assert _tokens(full) <= spec.SUMMARY_MAX_TOKENS


def test_spec_is_deterministic(real: threads.Analysis) -> None:
    gid = real.gaps[0].id
    assert spec.build_spec(real, gid) == spec.build_spec(real, gid)


def test_huge_test_list_is_truncated_within_budget() -> None:
    g = _graph()
    for i in range(300):
        tid = f"test:tests/t.py::test_long_name_for_budget_{i}_{'x' * 40}"
        g.add_node(Node("test", tid, "h", {"file": "tests/t.py", "name": f"n{i}"}))
        g.add_edge(tid, "fn:pkg.mod.run_job", "covers")
    gap = Gap("omission:fn:pkg.mod.run_job:in:asserts", "omission", "fn:pkg.mod.run_job", 0.3, "x")
    out = spec.build_spec(_fake([gap], g), gap.id)
    assert _tokens(out) <= spec.SUMMARY_MAX_TOKENS
    assert out["validate"]["tests_total"] == 301
    assert len(out["validate"]["tests"]) <= 20
