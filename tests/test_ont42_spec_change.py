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


def test_real_repo_open_discrepancy_resolves_to_implementation(tmp_path: Path) -> None:
    # G3: fixture sintetico con open_discrepancy real extraido por AST + invariante sobre REPO si hubiera abiertos
    (tmp_path / "engine").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "engine" / "mod.py").write_text("def run_op():\n    return 42\n", encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(
        "import pytest\nfrom engine import mod\n\n"
        "@pytest.mark.xfail(strict=True, reason='D-88')\n"
        "def test_op():\n    assert mod.run_op() == 42\n",
        encoding="utf-8",
    )
    syn = th.analyze(tmp_path, use_cache=False)
    opens = [g for g in syn.gaps if g.kind == "open_discrepancy"]
    assert len(opens) == 1 and opens[0].ref == "D-88"
    out = spec.build_spec(syn, opens[0].id, terse=True)
    assert _tokens(out) <= spec.TERSE_MAX_TOKENS
    assert out["change"]["files"] == ["engine/mod.py"]

    repo_analysis = th.analyze(REPO)
    for gap in (g for g in repo_analysis.gaps if g.kind == "open_discrepancy"):
        repo_out = spec.build_spec(repo_analysis, gap.id, terse=True)
        assert _tokens(repo_out) <= spec.TERSE_MAX_TOKENS
        assert repo_out["change"]["files"]
