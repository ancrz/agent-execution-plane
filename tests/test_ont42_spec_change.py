"""ONT-42b B3 (AE-2): `change:{nodes, files}` apunta a donde se edita; terse <= 400 tokens, files <= 3."""

from __future__ import annotations

import json
from pathlib import Path

from engine import threads as th
from engine import threads_spec as spec
from engine.threads_model import Gap, Node, ThreadGraph
from tests.test_ont41_spec import _fake, _graph

REPO = Path(__file__).resolve().parent.parent


def _tokens(payload: dict) -> int:
    return round(len(json.dumps(payload, separators=(",", ":")).encode()) / 4)


def _xfail_graph() -> ThreadGraph:
    g = _graph()
    g.add_node(Node("test", "test:tests/x.py::test_d", "h", {"file": "tests/x.py", "name": "test_d", "xfail_ref": "D-77"}))
    g.add_edge("test:tests/x.py::test_d", "action:tl:act", "covers")
    g.add_edge("test:tests/x.py::test_d", "fn:pkg.other.go", "covers")
    return g


def _gap() -> Gap:
    return Gap("drift:open:D-77:test:tests/x.py::test_d", "open_discrepancy", "test:tests/x.py::test_d", 0.5, "x", ref="D-77")


def test_open_discrepancy_change_follows_covers_then_implemented_by() -> None:
    out = spec.build_spec(_fake([_gap()], _xfail_graph()), "D-77")
    change = out["change"]
    assert change["nodes"] == ["fn:pkg.mod.run_job", "fn:pkg.other.go"]
    assert change["files"] == ["pkg/mod.py", "pkg/other.py"]
    assert "tests/x.py" not in change["files"]  # el test xfail no es el objetivo de edición
    assert "pin" not in out["validate"]  # sin tests en disco no hay pins (B8: split pin/validate)


def test_non_discrepancy_change_is_the_node_itself() -> None:
    gap = Gap("omission:fn:pkg.mod.run_job:in:covers", "omission", "fn:pkg.mod.run_job", 0.3, "x")
    out = spec.build_spec(_fake([gap], _graph()), gap.id)
    assert out["change"] == {"nodes": ["fn:pkg.mod.run_job"], "files": ["pkg/mod.py"]}


def test_terse_change_caps_files_and_fits_budget() -> None:
    g = _xfail_graph()
    for i in range(10):
        fid = f"fn:pkg.m{i}.f{i}"
        g.add_node(Node("module", f"module:pkg.m{i}", "h", {"path": f"pkg/m{i}.py"}))
        g.add_node(Node("function", fid, "h", {"module": f"pkg.m{i}"}))
        g.add_edge("test:tests/x.py::test_d", fid, "covers")
    terse = spec.build_spec(_fake([_gap()], g), "D-77", terse=True)
    assert len(terse["change"]["files"]) <= 3
    assert _tokens(terse) <= spec.TERSE_MAX_TOKENS


def test_real_repo_open_discrepancy_resolves_to_implementation() -> None:
    analysis = th.analyze(REPO)
    opens = [g for g in analysis.gaps if g.kind == "open_discrepancy"]
    assert opens, "D-01b debe estar abierto (B1)"
    for gap in opens:
        out = spec.build_spec(analysis, gap.id, terse=True)
        assert _tokens(out) <= spec.TERSE_MAX_TOKENS
        assert out["change"]["files"]
