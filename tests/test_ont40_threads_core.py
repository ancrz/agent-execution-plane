"""ONT-40 T1-T3, T9-T11: modelo, Tarjan/Bernstein, Merkle, ranking y persistencia (BD temporal)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from engine import threads
from engine.security import verify_audit_chain
from engine.threads_model import Node, ThreadGraph, missing_edges, required_edges
from engine.topos_guard import ToposGuard, ToposVerdict

REPO = Path(__file__).resolve().parent.parent


def _g(nodes: list[str], edges: list[tuple[str, str, str]]) -> ThreadGraph:
    g = ThreadGraph()
    for n in nodes:
        g.add_node(Node("module", f"module:{n}", n))
    for a, b, k in edges:
        g.add_edge(f"module:{a}", f"module:{b}", k)
    return g


def test_model_req_and_missing_edges() -> None:
    assert ("in", "covers") in required_edges("function")
    g = ThreadGraph()
    g.add_node(Node("function", "fn:a.f", "h"))
    assert missing_edges(g, g.nodes["fn:a.f"]) == [("in", "covers")]
    with pytest.raises(ValueError):
        g.add_node(Node("bogus", "x", "h"))
    assert g.add_edge("fn:a.f", "nope", "consumes") is False


def test_tarjan_matches_toposguard_oracle() -> None:
    cases = [
        (["a", "b", "c"], [("a", "b", "consumes"), ("b", "c", "consumes")]),
        (["a", "b"], [("a", "b", "consumes"), ("b", "a", "consumes")]),
        (["a", "b", "c"], [("a", "b", "consumes"), ("b", "c", "consumes"), ("c", "a", "consumes")]),
    ]
    for nodes, edges in cases:
        g = _g(nodes, edges)
        rep = threads.classify_sccs(g)
        deps: dict[str, list[str]] = {n: [] for n in nodes}
        for a, b, _ in edges:
            deps[a].append(b)
        verdict, _ = ToposGuard.audit_task_dag(nodes, deps)
        assert (verdict == ToposVerdict.BLOCKED) == bool(rep.codependencies)


def test_contract_mediated_cycle_is_interdependency_and_observes_ignored() -> None:
    g = _g(["a", "b"], [("a", "b", "consumes"), ("b", "a", "contract")])
    rep = threads.classify_sccs(g)
    assert rep.interdependencies and not rep.codependencies
    h = _g(["a", "b"], [("a", "b", "consumes"), ("b", "a", "observes")])
    assert not threads.classify_sccs(h).components or all(len(c) == 1 for c in threads.classify_sccs(h).components)
    r1, _ = threads.merkle_root(_g(["a", "b"], [("a", "b", "consumes")]))
    r2, _ = threads.merkle_root(h)
    assert r1 == r2, "observes edges must not enter R"


def test_merkle_changes_with_content_and_is_stable() -> None:
    g1 = _g(["a", "b"], [("a", "b", "consumes")])
    g2 = _g(["a", "b"], [("a", "b", "consumes")])
    assert threads.merkle_root(g1)[0] == threads.merkle_root(g2)[0]
    g2.nodes["module:b"].content_hash = "changed"
    assert threads.merkle_root(g1)[0] != threads.merkle_root(g2)[0]


def test_pagerank_deterministic_and_reach() -> None:
    g = _g(["a", "b", "c"], [("a", "c", "consumes"), ("b", "c", "consumes")])
    assert threads.pagerank(g) == threads.pagerank(g)
    assert threads.pagerank(g)["module:c"] > threads.pagerank(g)["module:a"]
    assert threads.reverse_reach(g, "module:c") == {"module:a", "module:b", "module:c"}
    assert threads.impacted_tests(g, ["module:c"]) == []


def test_bernstein_write_write_hazard() -> None:
    g = ThreadGraph()
    g.add_node(Node("state", "state:t", "h", {"kind": "table"}))
    for m in ("x", "y"):
        g.add_node(Node("function", f"fn:{m}.f", "h", {"module": m}))
        g.add_edge(f"fn:{m}.f", "state:t", "writes")
    assert threads.bernstein_hazards(g)[0]["kind"] == "write-write"


def test_analyze_repo_deterministic_and_no_codep() -> None:
    threads.clear_cache()
    a = threads.analyze(REPO, use_cache=False)
    b = threads.analyze(REPO, use_cache=False)
    assert a.root_hash == b.root_hash
    assert a.scc.codependencies == []
    assert threads.analyze(REPO).cached is False and threads.analyze(REPO).cached is True
    assert threads.graph_payload(a, terse=True)["nodes"] > 100
    assert threads.gaps_payload(a, limit=3)["gaps"]
    assert threads.thread_payload(a, "tool:discover")["status"] == "OK"
    assert threads.thread_payload(a, "nope")["status"] == "NOT_FOUND"


def test_persist_gate_idempotent_and_ledger(tmp_path: Path) -> None:
    a = threads.analyze(REPO)
    db = tmp_path / "t.db"
    assert threads.persist_generation(a, db_path=db, tier_octal=4)["persisted"] is False
    assert not db.exists()
    first = threads.persist_generation(a, db_path=db, tier_octal=6)
    again = threads.persist_generation(a, db_path=db, tier_octal=6)
    assert first["inserted"] is True and first["ledger_entry"]
    assert again["inserted"] is False and again["ledger_entry"] == ""
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM security_audit_log WHERE tool_name='autoevol'").fetchone()[0] == 1
    assert threads.list_generations(db_path=db)["total"] == 1
    d = threads.diff_generations("1", db_path=db, current=a)
    assert d["status"] == "OK" and d["identical"] is True
    assert threads.list_generations(db_path=tmp_path / "none.db")["total"] == 0
    conn.close()


def test_persist_lock_order_and_chain_integrity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C6: _AUDIT_LOCK debe adquirirse ANTES de BEGIN IMMEDIATE; la cadena no se bifurca con 2 hilos."""
    a1 = threads.analyze(REPO)
    a2 = threads.analyze(REPO)
    a2 = type(a2)(**{**{f: getattr(a2, f) for f in type(a2).__slots__}, "root_hash": "f" * 64})
    events: list[tuple[str, int]] = []

    class Proxy:
        def __init__(self, inner: object) -> None:
            self.inner = inner

        def __enter__(self) -> object:
            self.inner.acquire()  # type: ignore[attr-defined]
            events.append(("lock", threading.get_ident()))
            return self

        def __exit__(self, *exc: object) -> None:
            self.inner.release()  # type: ignore[attr-defined]

    orig_tx = threads.transaction_immediate
    import contextlib

    @contextlib.contextmanager
    def tx(conn):  # noqa: ANN001, ANN202
        events.append(("tx", threading.get_ident()))
        with orig_tx(conn) as c:
            yield c

    monkeypatch.setattr(threads, "_AUDIT_LOCK", Proxy(threads._AUDIT_LOCK))
    monkeypatch.setattr(threads, "transaction_immediate", tx)
    db = tmp_path / "c.db"
    ts = [
        threading.Thread(target=threads.persist_generation, args=(x,), kwargs={"db_path": db, "tier_octal": 6})
        for x in (a1, a2)
    ]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    for tid in {t for _, t in events}:
        seq = [k for k, t in events if t == tid]
        assert seq[:2] == ["lock", "tx"], f"lock order inverted: {seq}"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    assert verify_audit_chain(conn)["valid"] is True
    assert conn.execute("SELECT COUNT(*) FROM security_audit_log").fetchone()[0] == 2
    conn.close()
