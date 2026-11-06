"""ONT-42b B7 (AE-6): `pinning_tests` escanea el cuerpo completo del test, cachea por mtime y filtra genericos."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine import threads as th
from engine import threads_pins as pins
from engine.threads_model import Node, ThreadGraph

TEST_SRC = '''
EXPECTED_SHAPE = {"keys": ["alpha_marker", "beta"]}


def _helper_shape():
    return {"wanted": "wiring_sentinel"}


def test_golden_in_variable():
    expected = {"summary": "frobnicate_widget result"}
    got = run()
    assert got == expected


def test_uses_module_constant():
    got = run()
    assert sorted(got) == EXPECTED_SHAPE["keys"]


def test_uses_helper():
    assert run() == _helper_shape()


def test_generic_only():
    status = get()
    assert status == "summary"


def test_attribute_call():
    assert mod.compute_totals(1) == 2


@pytest.mark.parametrize("arg", ["decorated_literal"])
def test_decorator_literal(arg):
    assert arg


class TestGroup:
    def test_method(self):
        assert helper.other_unrelated() == 1
'''


def _graph(*fn_names: str, extra: tuple[Node, ...] = ()) -> ThreadGraph:
    g = ThreadGraph()
    for n in fn_names:
        g.add_node(Node("function", f"fn:mod.{n}", "h", {"module": "mod", "qual": n, "public": True}))
    for q in (
        "test_golden_in_variable", "test_uses_module_constant", "test_uses_helper", "test_generic_only",
        "test_attribute_call", "test_decorator_literal", "TestGroup::test_method",
    ):  # fmt: skip
        g.add_node(Node("test", f"test:tests/t.py::{q}", "h", {"file": "tests/t.py", "name": q}))
    for n in extra:
        g.add_node(n)
    return g


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    pins.clear_cache()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(TEST_SRC, encoding="utf-8")
    return tmp_path


def _ids(found: list[str]) -> list[str]:
    return [t.split("::", 1)[1] for t in found]


def test_golden_value_in_a_variable_is_found_not_only_asserts(tree: Path) -> None:
    g = _graph("frobnicate_widget")
    assert _ids(pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)) == ["test_golden_in_variable"]


def test_module_constant_and_helper_referenced_by_the_test_are_followed(tree: Path) -> None:
    assert _ids(pins.pinning_tests(_graph("alpha_marker"), ["fn:mod.alpha_marker"], tree)) == ["test_uses_module_constant"]
    assert _ids(pins.pinning_tests(_graph("wiring_sentinel"), ["fn:mod.wiring_sentinel"], tree)) == ["test_uses_helper"]


def test_attribute_and_decorator_references(tree: Path) -> None:
    assert _ids(pins.pinning_tests(_graph("compute_totals"), ["fn:mod.compute_totals"], tree)) == ["test_attribute_call"]
    assert _ids(pins.pinning_tests(_graph("decorated_literal"), ["fn:mod.decorated_literal"], tree)) == ["test_decorator_literal"]


def test_generic_names_and_short_identifiers_select_nothing(tree: Path) -> None:
    g = _graph("summary", "status", "get", "run", "abc")
    assert pins.pinning_tests(g, [f"fn:mod.{n}" for n in ("summary", "status", "get", "run", "abc")], tree) == []


def test_short_name_needs_module_qualification(tree: Path) -> None:
    g = _graph("compute")  # >= 5: simple
    assert pins.pinning_tests(g, ["fn:mod.compute"], tree) == []  # `compute_totals` != `compute`
    g2 = _graph("get")
    (tree / "tests" / "t.py").write_text(TEST_SRC + "\ndef test_q():\n    assert mod.get() == 1\n", encoding="utf-8")
    g2.add_node(Node("test", "test:tests/t.py::test_q", "h", {}))
    assert _ids(pins.pinning_tests(g2, ["fn:mod.get"], tree)) == ["test_q"]


def test_tests_absent_from_the_graph_are_never_returned(tree: Path) -> None:
    g = _graph("frobnicate_widget")
    del g.nodes["test:tests/t.py::test_golden_in_variable"]
    assert pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree) == []


def test_cache_by_path_mtime_size_is_reused_and_invalidated(tree: Path) -> None:
    g = _graph("frobnicate_widget")
    pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)
    first = pins.cache_stats()
    assert first["parsed"] == 1
    pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)
    assert pins.cache_stats()["parsed"] == 1 and pins.cache_stats()["hits"] == 1
    path = tree / "tests" / "t.py"
    path.write_text(TEST_SRC + "\n# edit\n", encoding="utf-8")
    pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)
    assert pins.cache_stats()["parsed"] == 2
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5))
    pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)
    assert pins.cache_stats()["parsed"] == 3


def test_syntax_error_file_and_missing_root_are_fail_open(tree: Path) -> None:
    (tree / "tests" / "broken.py").write_text("def (:\n", encoding="utf-8")
    g = _graph("frobnicate_widget")
    assert len(pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)) == 1
    assert pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], None) == []
    assert pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree / "nope") == []


def test_pins_are_not_stored_in_the_graph_and_do_not_move_the_root(tree: Path) -> None:
    g = _graph("frobnicate_widget")
    before = (len(g.nodes), len(g.edges()))
    pins.pinning_tests(g, ["fn:mod.frobnicate_widget"], tree)
    assert (len(g.nodes), len(g.edges())) == before


def test_real_repo_finds_the_old_contract_pin_for_summary_shape() -> None:
    """AE-6 sobre el repo real: cambiar `tv.summarize` selecciona tests que fijan su forma sin llamarlo por covers."""
    root = Path(__file__).resolve().parent.parent
    analysis = th.analyze(root, use_cache=False)
    fid = next(i for i in analysis.graph.nodes if i.endswith(".summarize") and i.startswith("fn:engine.threads_verify"))
    found = pins.pinning_tests(analysis.graph, [fid], root)
    assert found and all(t in analysis.graph.nodes for t in found)
