"""E3: supervision tree (one_for_one / rest_for_one) derived from the thread graph. AEP_DATA_HOME=tmp en los de heal."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import aep_lkg
from engine import threads_heal, threads_ops, threads_supervise
from engine.threads_model import Node, ThreadGraph

REPO = Path(__file__).resolve().parent.parent
BROKEN_FILE = "engine/threads_verify.py"
BENIGN_FILE = "engine/privilege.py"


# --------------------------------------------------------------------------- synthetic graphs


def _graph(fn_hash: dict[str, str]) -> Any:
    """Files: base.py <- mid.py <- top.py ; iso.py (solo lo consume server); leaf.py sin consumidores; ca.py <-> cb.py (ciclo estricto).

    Tools: t_top usa top.fn -> mid.fn -> base.fn ; t_iso usa iso.fn ; t_cyc usa ca.fn.
    """
    g = ThreadGraph()
    for mod in ("base", "mid", "top", "iso", "ca", "cb", "leaf"):
        g.add_node(Node("module", f"module:{mod}", f"m-{mod}", {"path": f"{mod}.py"}))
    for mod in ("base", "mid", "top", "iso", "ca", "cb", "leaf"):
        g.add_node(Node("function", f"fn:{mod}.fn", fn_hash.get(mod, f"h-{mod}"), {"module": mod}))
    g.add_node(Node("module", "module:server", "m-server", {"path": "server.py"}))
    for tool, target in (("t_top", "top"), ("t_iso", "iso"), ("t_cyc", "ca")):
        g.add_node(Node("function", f"fn:server.{tool}", f"h-{tool}", {"module": "server"}))
        g.add_node(Node("tool", f"tool:{tool}", f"h-{tool}", {"name": tool, "module": "server"}))
        g.add_edge(f"fn:server.{tool}", f"fn:{target}.fn", "consumes")
    for src, dst in (("top", "mid"), ("mid", "base"), ("ca", "cb"), ("cb", "ca")):
        g.add_edge(f"fn:{src}.fn", f"fn:{dst}.fn", "consumes")
        g.add_edge(f"module:{src}", f"module:{dst}", "consumes")
    return SimpleNamespace(graph=g)


LKG_SRC = {
    "base.py": "def fn(a, b):\n    return a\n",
    "mid.py": "from base import fn as bfn\n\ndef fn():\n    return bfn(1, 2)\n",
    "top.py": "from mid import fn as mfn\n\ndef fn():\n    return mfn()\n",
    "iso.py": "def fn():\n    return 1\n",
    "ca.py": "from cb import fn as cbf\n\ndef fn():\n    return cbf()\n",
    "cb.py": "from ca import fn as caf\n\ndef fn():\n    return caf()\n",
    "leaf.py": "def fn():\n    return 0\n",
    "server.py": "from top import fn as t\nfrom iso import fn as i\nfrom ca import fn as c\n\nt()\ni()\nc()\n",
}


def _plan(broken: list[str], changed: dict[str, str], repo_src: dict[str, str] | None = None) -> dict[str, Any]:
    repo = {**LKG_SRC, **(repo_src or {})}
    return threads_supervise.plan(
        _graph(changed),
        _graph({}),
        broken,
        lambda rel: True,
        lambda which, rel: (repo if which == "repo" else LKG_SRC).get(rel),
    )


def test_isolated_scc_is_one_for_one() -> None:
    res = _plan(["leaf.py"], {"leaf": "other"})
    assert res["strategy"] == "one_for_one" and res["files"] == ["leaf.py"]
    assert [u["role"] for u in res["units"]] == ["broken"]
    assert res["supervisor"] == [] and res["unaffected_tools"] == ["t_cyc", "t_iso", "t_top"]


def test_consumer_with_unrelated_edit_is_preserved() -> None:
    res = _plan(["iso.py"], {"iso": "other"}, {"server.py": LKG_SRC["server.py"] + "# my own edit\nx = 1\n"})
    assert res["strategy"] == "one_for_one" and res["files"] == ["iso.py"]
    assert [p["file"] for p in res["preserved"]] == ["server.py"] and res["preserved"][0]["reason"]
    assert res["supervisor"] == ["t_iso"] and res["unaffected_tools"] == ["t_cyc", "t_top"]


def test_consumer_using_the_changed_symbol_is_included() -> None:
    # server.py was adapted to a new signature of iso.fn(x); the restored (LKG) iso.fn() takes no args.
    res = _plan(["iso.py"], {"iso": "other"}, {"server.py": "from iso import fn as i\ni(1)\n"})
    assert res["strategy"] == "rest_for_one" and set(res["files"]) == {"iso.py", "server.py"}
    assert res["preserved"] == []


def test_consumer_using_symbol_absent_from_lkg_is_included() -> None:
    res = _plan(["iso.py"], {"iso": "other"}, {"server.py": "from iso import brand_new\nbrand_new()\n"})
    assert res["strategy"] == "rest_for_one" and "server.py" in res["files"]


def test_consumer_that_does_not_compile_is_included() -> None:
    res = _plan(["iso.py"], {"iso": "other"}, {"server.py": "def broken(:\n"})
    assert res["strategy"] == "rest_for_one" and "server.py" in res["files"]


def test_syntax_error_unit_compares_against_lkg_exports_not_vanished() -> None:
    # iso.py does not compile now (its nodes vanish), but every consumer still matches the LKG exports.
    res = _plan(["iso.py"], {"iso": "other"}, {"iso.py": "def fn(:\n"})
    assert res["strategy"] == "one_for_one" and res["files"] == ["iso.py"]
    assert [p["file"] for p in res["preserved"]] == ["server.py"]


def test_changed_contract_is_rest_for_one_in_topological_order() -> None:
    res = _plan(
        ["base.py"],
        {"base": "changed", "mid": "changed", "top": "changed"},
        {
            "mid.py": "from base import fn as bfn\n\ndef fn():\n    return bfn(1, 2, 3)\n",
            "top.py": "from mid import fn as mfn\n\ndef fn():\n    return mfn(9)\n",
            "server.py": "from top import fn as t\nt(1, 2)\n",
        },
    )
    assert res["strategy"] == "rest_for_one"
    assert set(res["files"]) == {"base.py", "mid.py", "top.py", "server.py"}
    order = [u["files"][0] for u in res["units"]]
    assert order.index("base.py") < order.index("mid.py") < order.index("top.py")
    assert [u["role"] for u in res["units"]][0] == "broken"
    assert "iso.py" not in res["files"] and "ca.py" not in res["files"]


def test_wave_stops_where_the_consumer_is_compatible() -> None:
    res = _plan(
        ["base.py"],
        {"base": "changed"},
        {"mid.py": "from base import fn as bfn\n\ndef fn():\n    return bfn(1, 2, 3)\n"},
    )
    assert res["strategy"] == "rest_for_one" and set(res["files"]) == {"base.py", "mid.py"}


def test_unaffected_tools_listed() -> None:
    res = _plan(["base.py"], {"base": "changed", "mid": "changed", "top": "changed"})
    assert res["supervisor"] == ["t_top"]
    assert res["unaffected_tools"] == ["t_cyc", "t_iso"]


def test_strict_cycle_fuses_into_one_unit() -> None:
    res = _plan(["ca.py"], {"ca": "changed"})
    assert any(u["files"] == ["ca.py", "cb.py"] for u in res["units"])
    assert res["supervisor"] == ["t_cyc"]


def test_restorable_filter_drops_identical_dependents() -> None:
    repo = {**LKG_SRC, "mid.py": "from base import fn as bfn\nbfn(1, 2, 3)\n"}
    res = threads_supervise.plan(
        _graph({"base": "x"}),
        _graph({}),
        ["base.py"],
        lambda rel: rel == "base.py",
        lambda which, rel: (repo if which == "repo" else LKG_SRC).get(rel),
    )
    assert res["files"] == ["base.py"]


def test_no_broken_files_is_empty_plan() -> None:
    res = _plan([], {})
    assert res["strategy"] == "none" and res["units"] == [] and res["files"] == []


def test_no_server_import_in_supervise() -> None:
    src = (REPO / "engine" / "threads_supervise.py").read_text()
    assert "import server" not in src and "from server" not in src and "aep_front" not in src.split('"""')[2]
    assert threads_supervise.file_units(ThreadGraph(), ThreadGraph()) == []


# --------------------------------------------------------------------------- heal integration


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("server.py", "aep_backend.py", "aep_front.py", "aep_lkg.py", "pyproject.toml"):
        shutil.copy2(REPO / name, repo / name)
    for sub in ("engine", "templates", "schemas", "scripts"):
        shutil.copytree(REPO / sub, repo / sub, ignore=shutil.ignore_patterns("__pycache__"))
    key = aep_lkg.save(repo, "g1", "fp", "schema", "head")["key"]
    return {"repo": repo, "key": key}


def _break(repo: Path) -> None:
    (repo / BROKEN_FILE).write_text((repo / BROKEN_FILE).read_text() + "\ndef broken(:\n    pass\n")
    (repo / BENIGN_FILE).write_text((repo / BENIGN_FILE).read_text() + "\n# local edit kept\n")


def test_heal_reports_plan_fields_and_isolates_tools(world: dict[str, Any]) -> None:
    repo = world["repo"]
    _break(repo)
    res = threads_heal.heal(repo)
    assert res["status"] == "BROKEN" and not res["applied"]
    assert res["strategy"] in ("one_for_one", "rest_for_one")
    unit_files = {f for u in res["units"] for f in u["files"]}
    assert BROKEN_FILE in unit_files and unit_files == set(res["files"])
    assert BENIGN_FILE not in unit_files
    assert "autoevol" in res["supervisor"]
    assert set(res["supervisor"]).isdisjoint(res["unaffected_tools"])
    assert res["unaffected_tools"], "tools whose subtree is untouched must be listed"
    assert "discover" in res["unaffected_tools"] or "kanban_board" in res["unaffected_tools"]


def test_apply_never_touches_files_outside_units(world: dict[str, Any]) -> None:
    repo = world["repo"]
    _break(repo)
    before = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    plan = threads_heal.heal(repo)
    allowed = set(plan["files"])
    seen: dict[str, Any] = {}

    def snapshot(files: list[str]) -> dict[str, Any]:
        seen["files"] = files
        return {"ok": True}

    res = threads_heal.heal(repo, apply=True, snapshot_fn=snapshot)
    assert res["applied"] and seen["files"] == sorted(allowed) and set(res["restored"]) <= allowed
    after = {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in repo.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed <= allowed and BROKEN_FILE in changed
    assert "# local edit kept" in (repo / BENIGN_FILE).read_text()


def test_tier_below_6_returns_plan_only(world: dict[str, Any]) -> None:
    repo = world["repo"]
    _break(repo)
    before = (repo / BROKEN_FILE).read_text()
    called: list[Any] = []
    res = threads_ops.run_heal(repo, apply=True, octal=5, snapshot_fn=called.append, terse=False)
    assert res["status"] == "PERMISSION_DENIED" and not res["applied"] and not called
    assert BROKEN_FILE in res["files"] and res["strategy"] != "none" and res["units"]
    assert (repo / BROKEN_FILE).read_text() == before


def test_terse_payload_within_400_tokens(world: dict[str, Any]) -> None:
    repo = world["repo"]
    _break(repo)
    res = threads_ops.run_heal(repo, apply=False, octal=4, snapshot_fn=None, terse=True)
    assert res["strategy"] != "none" and "supervisor" in res
    assert threads_ops.estimated_tokens(res) <= 400, json.dumps(res)


def test_real_consumer_with_local_edit_is_preserved_when_contract_module_breaks(world: dict[str, Any]) -> None:
    repo = world["repo"]
    fp = repo / "engine/fingerprint.py"
    fp.write_text(fp.read_text() + "\ndef broken(:\n    pass\n")
    priv = repo / "engine/privilege.py"
    priv.write_text(priv.read_text() + "\n# my own edit\n")
    res = threads_heal.heal(repo)
    assert "engine/privilege.py" not in res["files"]
    assert "engine/privilege.py" in [p["file"] for p in res["preserved"]]
    threads_heal.heal(repo, apply=True, snapshot_fn=lambda files: {"ok": True})
    assert "# my own edit" in priv.read_text()


def test_strategy_follows_planned_units_not_selected() -> None:
    """mid.py (dependiente) no es restaurable: no entra en el plan, luego la estrategia es one_for_one."""
    repo = {**LKG_SRC, "mid.py": "from base import fn as bfn\nbfn(1, 2, 3)\n"}
    res = threads_supervise.plan(
        _graph({"base": "x"}),
        _graph({}),
        ["base.py"],
        lambda rel: rel == "base.py",
        lambda which, rel: (repo if which == "repo" else LKG_SRC).get(rel),
    )
    assert res["strategy"] == "one_for_one"
    assert [u["role"] for u in res["units"]] == ["broken"]
    assert {"file": "mid.py", "reason": "fuera del LKG"} in res["skipped"]


def test_partial_unit_marks_skipped_files_of_half_restored_scc() -> None:
    res = threads_supervise.plan(
        _graph({"ca": "changed"}),
        _graph({}),
        ["ca.py"],
        lambda rel: rel != "cb.py",
        lambda which, rel: LKG_SRC.get(rel),
    )
    assert res["partial_unit"] is True
    assert res["skipped"] == [{"file": "cb.py", "reason": "fuera del LKG"}]
    assert any(u["files"] == ["ca.py"] for u in res["units"])


def test_identical_file_is_neither_skipped_nor_partial() -> None:
    res = threads_supervise.plan(
        _graph({"ca": "changed"}),
        _graph({}),
        ["ca.py"],
        lambda rel: "identical" if rel == "cb.py" else "restore",
        lambda which, rel: LKG_SRC.get(rel),
    )
    assert res["skipped"] == [] and res["partial_unit"] is False
    assert any(u["files"] == ["ca.py"] for u in res["units"])


def test_out_of_lkg_file_is_skipped_and_partial() -> None:
    res = threads_supervise.plan(
        _graph({"ca": "changed"}),
        _graph({}),
        ["ca.py"],
        lambda rel: "out_of_lkg" if rel == "cb.py" else "restore",
        lambda which, rel: LKG_SRC.get(rel),
    )
    assert res["skipped"] == [{"file": "cb.py", "reason": "fuera del LKG"}]
    assert res["partial_unit"] is True


def test_full_restore_is_not_partial_and_skips_nothing() -> None:
    res = _plan(["leaf.py"], {"leaf": "other"})
    assert res["partial_unit"] is False and res["skipped"] == []
    empty = _plan([], {})
    assert empty["skipped"] == [] and empty["partial_unit"] is False


# --------------------------------------------------------------------------- weak edges (ONT-51)


def _weak_cycle_graph(*, weak_back: bool) -> ThreadGraph:
    g = ThreadGraph()
    for mod in ("wa", "wb"):
        g.add_node(Node("module", f"module:{mod}", f"m-{mod}", {"path": f"{mod}.py"}))
        g.add_node(Node("function", f"fn:{mod}.fn", f"h-{mod}", {"module": mod}))
    g.add_edge("fn:wa.fn", "fn:wb.fn", "consumes")
    g.add_edge("fn:wb.fn", "fn:wa.fn", "consumes", weak=weak_back)
    return g


def test_weak_back_edge_does_not_fuse_files_into_one_unit() -> None:
    weak = _weak_cycle_graph(weak_back=True)
    assert sorted(threads_supervise.file_units(weak, weak)) == [["wa.py"], ["wb.py"]]
    strict = _weak_cycle_graph(weak_back=False)
    assert threads_supervise.file_units(strict, strict) == [["wa.py", "wb.py"]]


def test_weak_only_consumer_still_listed_as_dependent() -> None:
    lkg = ThreadGraph()
    repo = ThreadGraph()
    for g, h in ((lkg, "old"), (repo, "new")):
        for mod in ("wa", "wb"):
            g.add_node(Node("module", f"module:{mod}", f"m-{mod}", {"path": f"{mod}.py"}))
        g.add_node(Node("function", "fn:wa.fn", "h-wa", {"module": "wa"}))
        g.add_node(Node("function", "fn:wb.fn", h, {"module": "wb"}))
        g.add_edge("fn:wa.fn", "fn:wb.fn", "consumes", weak=True)
    edges = threads_supervise._union_edges((repo, lkg))
    assert ("fn:wa.fn", "fn:wb.fn", "consumes") in edges
    assert threads_supervise._union_edges((repo, lkg), include_weak=False) == []
    assert threads_supervise._changed_consumers({"wb.py"}, repo, lkg, edges) == {"wa.py"}
