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


def _plan(broken: list[str], changed: dict[str, str]) -> dict[str, Any]:
    return threads_supervise.plan(_graph(changed), _graph({}), broken, lambda rel: True)


def test_isolated_scc_is_one_for_one() -> None:
    res = _plan(["leaf.py"], {"leaf": "other"})
    assert res["strategy"] == "one_for_one" and res["files"] == ["leaf.py"]
    assert [u["role"] for u in res["units"]] == ["broken"]
    assert res["supervisor"] == [] and res["unaffected_tools"] == ["t_cyc", "t_iso", "t_top"]


def test_tool_consumed_function_with_changed_hash_restarts_its_consumers_only() -> None:
    res = _plan(["iso.py"], {"iso": "other"})
    assert res["strategy"] == "rest_for_one" and set(res["files"]) == {"iso.py", "server.py"}
    assert res["supervisor"] == ["t_iso"] and res["unaffected_tools"] == ["t_cyc", "t_top"]


def test_unchanged_contract_stays_one_for_one_even_with_consumers() -> None:
    # base.py esta rota pero su funcion exportada conserva el hash del LKG: no hay contrato que propagar.
    res = _plan(["base.py"], {})
    assert res["strategy"] == "one_for_one" and res["files"] == ["base.py"]


def test_changed_contract_is_rest_for_one_in_topological_order() -> None:
    res = _plan(["base.py"], {"base": "changed", "mid": "changed", "top": "changed"})
    assert res["strategy"] == "rest_for_one"
    assert set(res["files"]) == {"base.py", "mid.py", "top.py", "server.py"}
    order = [u["files"][0] for u in res["units"]]
    assert order.index("base.py") < order.index("mid.py") < order.index("top.py")
    assert [u["role"] for u in res["units"]][0] == "broken"
    assert "iso.py" not in res["files"] and "ca.py" not in res["files"]


def test_wave_stops_where_the_contract_is_unchanged() -> None:
    res = _plan(["base.py"], {"base": "changed"})
    assert res["strategy"] == "rest_for_one" and set(res["files"]) == {"base.py", "mid.py"}


def test_unaffected_tools_listed() -> None:
    res = _plan(["base.py"], {"base": "changed"})
    assert res["supervisor"] == ["t_top"]
    assert res["unaffected_tools"] == ["t_cyc", "t_iso"]


def test_strict_cycle_fuses_into_one_unit() -> None:
    res = _plan(["ca.py"], {"ca": "changed"})
    assert any(u["files"] == ["ca.py", "cb.py"] for u in res["units"])
    assert res["supervisor"] == ["t_cyc"]


def test_restorable_filter_drops_identical_dependents() -> None:
    res = threads_supervise.plan(_graph({"base": "x"}), _graph({}), ["base.py"], lambda rel: rel == "base.py")
    assert res["strategy"] == "rest_for_one" and res["files"] == ["base.py"]


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
