"""ONT-42b B8: seleccion ordenada own -> covers -> pins -> transitivos(1), tope 24 sin apply, partial, split pin/validate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from engine import threads as th
from engine import threads_ops as ops
from engine import threads_spec as spec
from engine import threads_verify as tv
from engine.threads_model import Gap, Node, ThreadGraph


def _tid(i: int) -> str:
    return f"test:tests/t.py::test_{i:03d}"


def _world(tmp_path: Path, n_direct: int, n_trans: int, n_pins: int = 0) -> tuple[SimpleNamespace, dict]:
    """fn:m.target cubierta por n_direct tests; fn:m.user (consume target) cubierta por n_trans; n_pins por AST."""
    g = ThreadGraph()
    g.add_node(Node("function", "fn:m.target", "h", {"module": "m", "qual": "target_fn_unique", "public": True}))
    g.add_node(Node("function", "fn:m.user", "h", {"module": "m", "qual": "user", "public": True}))
    g.add_edge("fn:m.user", "fn:m.target", "consumes")
    body = []
    for i in range(n_direct):
        g.add_node(Node("test", _tid(i), "h", {}))
        g.add_edge(_tid(i), "fn:m.target", "covers")
        body.append(f"def test_{i:03d}():\n    pass\n")
    for i in range(n_direct, n_direct + n_trans):
        g.add_node(Node("test", _tid(i), "h", {}))
        g.add_edge(_tid(i), "fn:m.user", "covers")
        body.append(f"def test_{i:03d}():\n    pass\n")
    for i in range(n_direct + n_trans, n_direct + n_trans + n_pins):
        g.add_node(Node("test", _tid(i), "h", {}))
        body.append(f"def test_{i:03d}():\n    assert x == 'target_fn_unique'\n")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "t.py").write_text("\n".join(body), encoding="utf-8")
    cmp = {"changed": ["fn:m.target"], "changed_tests": []}
    return SimpleNamespace(graph=g), cmp


def test_order_is_own_then_direct_then_pins_then_transitive(tmp_path: Path) -> None:
    analysis, cmp = _world(tmp_path, 2, 2, 2)
    cmp["changed_tests"] = [_tid(5)]  # un pin que ademas es test propio: va primero y no se duplica
    sel, info = ops.select_tests(analysis, cmp, tmp_path)
    assert sel == [_tid(5), _tid(0), _tid(1), _tid(4), _tid(2), _tid(3)]
    assert info == {"direct": 3, "pins": 1, "transitive_dropped": 0}


def test_cap_24_without_apply_drops_transitive_and_reports_it(tmp_path: Path) -> None:
    analysis, cmp = _world(tmp_path, 10, 30, 2)
    sel, info = ops.select_tests(analysis, cmp, tmp_path)
    assert len(sel) == ops.SELECTION_CAP == 24
    assert info == {"direct": 10, "pins": 2, "transitive_dropped": 30 - 12}
    assert sel[:10] == [_tid(i) for i in range(10)]


def test_cap_never_applies_with_apply(tmp_path: Path) -> None:
    analysis, cmp = _world(tmp_path, 10, 30, 2)
    sel, info = ops.select_tests(analysis, cmp, tmp_path, apply=True)
    assert len(sel) == 42 and info["transitive_dropped"] == 0


def test_cap_biting_the_head_is_reported(tmp_path: Path) -> None:
    analysis, cmp = _world(tmp_path, 30, 0)
    _sel, info = ops.select_tests(analysis, cmp, tmp_path)
    assert info["direct"] == 24 and info["head_dropped"] == 6


def test_single_file_change_selects_at_most_20_on_the_real_repo() -> None:
    root = Path(__file__).resolve().parent.parent
    analysis = th.analyze(root, use_cache=False)
    fns = [i for i in analysis.graph.nodes if i.startswith("fn:engine.threads_verify.")]
    changed = [i for i in fns if i.endswith((".summarize", ".compare", ".plan_tests"))]
    cmp = {"changed": changed, "changed_tests": []}
    sel, _info = ops.select_tests(analysis, cmp, root)
    assert 0 < len(sel) <= 24
    one = {"changed": [next(i for i in fns if i.endswith(".plan_tests"))], "changed_tests": []}
    assert len(ops.select_tests(analysis, one, root)[0]) <= 20


def test_accept_with_dropped_transitive_is_partial(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    base = {"gaps": [], "hashes": {}, "public": [], "direct": [], "root": "a", "codep": []}
    analysis, cmp = _world(tmp_path, 1, 40)
    monkeypatch.setattr(th, "analyze", lambda *_a, **_k: analysis)
    monkeypatch.setattr(tv, "summarize", lambda _a: {**base, "hashes": {"fn:m.target": "x"}})
    monkeypatch.setattr(tv, "compare", lambda *_a: {**cmp, "fixed": ["g"], "introduced": [], "codep": [], "touches_public": False,
                                                    "uncovered_public": [], "uncovered_private": [], "gaps_base": 0, "gaps_new": 0,
                                                    "root_base": "", "root_new": ""})
    ran: list[int] = []

    def run(tests: list[str]) -> dict:
        ran.append(len(tests))
        return {"ran": len(tests), "passed": len(tests), "failed": 0, "errors": 0, "exit_code": 0}

    kw = {"gap": None, "barrier": None, "run_tests": run, "dispatch_job": lambda t: {"job": "1"}, "trusted": True}
    out = ops.judge(base, tmp_path, tests_result={"ran": 24, "passed": 24, "failed": 0, "errors": 0, "exit_code": 0}, **kw)
    assert out["selection"]["transitive_dropped"] == 17 and out["verdict"] == tv.ACCEPT and out["partial"] is True
    full = ops.judge(base, tmp_path, apply=True, tests_result={"ran": 41, "passed": 41, "failed": 0, "errors": 0, "exit_code": 0}, **kw)
    assert full["verdict"] == tv.ACCEPT and "partial" not in full and full["selection"]["transitive_dropped"] == 0


def test_spec_splits_pin_from_validate(tmp_path: Path) -> None:
    analysis, _cmp = _world(tmp_path, 1, 0, 2)
    analysis.root = tmp_path
    analysis.gaps = [Gap("omission:fn:m.target:in:covers", "omission", "fn:m.target", 0.3, "x")]
    out = spec.build_spec(analysis, analysis.gaps[0].id)
    assert out["validate"]["tests"] == [_tid(0)]
    assert out["validate"]["pin"] == [_tid(1), _tid(2)]
    terse = spec.build_spec(analysis, analysis.gaps[0].id, terse=True)
    assert terse["pin"] == [_tid(1), _tid(2)] and terse["tests"] == [_tid(0)]


def test_g1_batched_sandbox_runner_executes_over_20_without_async_reject() -> None:
    batches: list[int] = []

    def run(chunk: list[str]) -> dict:
        batches.append(len(chunk))
        return {"ran": len(chunk), "passed": len(chunk), "failed": 0, "errors": 0, "exit_code": 0}

    agg = tv.run_tests_batched([f"t{i:02d}" for i in range(24)], run, batch_size=20)
    assert batches == [20, 4] and agg["ran"] == 24 and agg["passed"] == 24 and agg["batches"] == 2
    base = {"gaps": ["g1"], "hashes": {"fn:a.f": "1"}, "public": ["fn:a.f"], "direct": ["fn:a.f"], "root": "r", "codep": []}
    new = {"gaps": [], "hashes": {"fn:a.f": "2"}, "public": ["fn:a.f"], "direct": ["fn:a.f"], "root": "r2", "codep": []}
    verdict = tv.verify_change(
        base,
        new,
        impacted_tests=[f"t{i:02d}" for i in range(24)],
        run_tests=run,
        dispatch_job=lambda _t: {"job": None, "available": False},
        trusted=False,
        batch_sync=True,
    )
    assert verdict["verdict"] == tv.ACCEPT and verdict["tests"]["mode"] == "batched" and verdict["tests"]["batches"] == 2


def test_g2_private_helper_inherits_caller_pins(tmp_path: Path) -> None:
    g = ThreadGraph()
    g.add_node(Node("function", "fn:m._helper", "h", {"module": "m", "qual": "_helper", "public": False}))
    g.add_node(Node("function", "fn:m.public_entry", "h", {"module": "m", "qual": "public_entry", "public": True}))
    g.add_edge("fn:m.public_entry", "fn:m._helper", "consumes")
    g.add_node(Node("test", _tid(0), "h", {}))
    g.add_edge(_tid(0), "fn:m._helper", "covers")
    g.add_node(Node("test", _tid(1), "h", {}))
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "t.py").write_text(
        "def test_000():\n    pass\n\ndef test_001():\n    assert res == 'public_entry'\n",
        encoding="utf-8",
    )
    sel, info = ops.select_tests(SimpleNamespace(graph=g), {"changed": ["fn:m._helper"], "changed_tests": []}, tmp_path)
    assert sel == [_tid(0), _tid(1)] and info["direct"] == 1 and info["pins"] == 1


def test_g4_open_cycle_reaps_orphan_open_cycle_for_same_gap(tmp_path: Path) -> None:
    store = tv.CycleStore(base_dir=tmp_path / "shm")
    c1 = store.open_cycle("gap:1", {"gaps": ["gap:1"]})["cycle_id"]
    assert store.load(c1) is not None
    c2 = store.open_cycle("gap:1", {"gaps": ["gap:1"]})["cycle_id"]
    assert c2 != c1 and store.load(c1) is None and store.load(c2) is not None
