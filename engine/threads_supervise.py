"""
Engine: threads_supervise.py (E3: Erlang/OTP-style supervision tree derived from the thread graph)

Pure calculation: given the live analysis, the LKG analysis and the broken files, it decides WHAT to restart.
It never reads or writes files and never imports `server` or `aep_front`.

Supervision tree
  - Unit  = SCC of the FILE-level dependency graph (condensation of strict `consumes`/`contract` edges,
            over the union of the live and LKG graphs). A function-level cycle across files is therefore a
            single unit: its files restart together, never half of them.
  - Supervisor = a compact tool (`tool:*`). Its subtree is the dependency closure of `fn:server.<tool>`.
            A tool is AFFECTED when its subtree holds a changed node (content hash differs from the LKG or the
            node vanished) that lives in a planned file; every other tool is listed in `unaffected_tools`.

Strategy selection (deterministic, per broken unit)
  - `rest_for_one` iff the broken unit EXPORTS A CONTRACT whose hash changed: some node outside the unit
    consumes (`consumes`/`contract`) a function (or any `contract` target) living in the unit, and that node's
    content hash differs from the LKG or the node is missing from the live graph. Plan = broken unit + every unit
    that (transitively) consumes a changed contract, dependencies first (topological order). The wave stops at
    a unit whose own exports are unchanged (its consumers still see the same contract).
  - otherwise `one_for_one`: plan = the broken unit only.
  Dependents are included only if `restorable(file)` (in the LKG set and different from it); identical files
  are never rewritten. No other file can enter the plan: the full tree is never reverted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from engine import threads
from engine.threads_model import HASH_EDGE_KINDS, ThreadGraph

ONE_FOR_ONE = "one_for_one"
REST_FOR_ONE = "rest_for_one"
NO_STRATEGY = "none"

_TRACKED_TYPES = ("function", "tool")


def _file_of(node_id: str, graphs: tuple[ThreadGraph, ...]) -> str:
    for g in graphs:
        node = g.nodes.get(node_id)
        if node is None:
            continue
        if node.type == "module":
            return str(node.attrs.get("path", ""))
        mod = str(node.attrs.get("module", ""))
        if mod:
            for g2 in graphs:
                m = g2.nodes.get(f"module:{mod}")
                if m is not None and m.attrs.get("path"):
                    return str(m.attrs["path"])
    return ""


def _union_edges(graphs: tuple[ThreadGraph, ...], *, include_lazy: bool = True) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    for g in graphs:
        for e in g.edges(HASH_EDGE_KINDS):
            if include_lazy or not e.lazy:
                seen.add((e.src, e.dst, e.kind))
    return sorted(seen)


def _changed(node_id: str, repo: ThreadGraph, lkg: ThreadGraph) -> bool:
    base = lkg.nodes.get(node_id)
    if base is None:
        return False  # no baseline: nothing to compare with
    live = repo.nodes.get(node_id)
    return live is None or live.content_hash != base.content_hash


def file_units(repo: ThreadGraph, lkg: ThreadGraph) -> list[list[str]]:
    """File-level SCCs over STRICT (import-time) edges, dependencies first (sinks first, as `tarjan_scc` emits).

    Lazy-import cycles do not couple files at load time, so they do not fuse units; lazy edges still count as
    dependencies when collecting dependents.
    """
    graphs = (repo, lkg)
    files: set[str] = set()
    adj: dict[str, set[str]] = {}
    for src, dst, _kind in _union_edges(graphs, include_lazy=False):
        fs, fd = _file_of(src, graphs), _file_of(dst, graphs)
        files.update(f for f in (fs, fd) if f)
        if fs and fd and fs != fd:
            adj.setdefault(fs, set()).add(fd)
    comps = threads.tarjan_scc(sorted(files), {k: sorted(v) for k, v in sorted(adj.items())})
    return [sorted(c) for c in comps]


def _changed_consumers(
    unit: set[str], repo: ThreadGraph, lkg: ThreadGraph, edges: list[tuple[str, str, str]]
) -> set[str]:
    """Files outside `unit` that consume a contract of `unit` whose hash changed (or vanished) vs the LKG."""
    graphs = (repo, lkg)
    out: set[str] = set()
    for src, dst, kind in edges:
        fsrc = _file_of(src, graphs)
        if _file_of(dst, graphs) not in unit or fsrc in unit or not fsrc:
            continue
        node = lkg.nodes.get(dst) or repo.nodes.get(dst)
        if node is not None and (kind == "contract" or node.type == "function") and _changed(dst, repo, lkg):
            out.add(fsrc)
    return out


def _tool_subtree(tool: str, adj: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [f"fn:server.{tool}"]
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(adj.get(cur, []))
    return seen


def _changed_nodes(plan_files: set[str], repo: ThreadGraph, lkg: ThreadGraph) -> set[str]:
    graphs = (repo, lkg)
    out: set[str] = set()
    for nid in set(lkg.nodes) | set(repo.nodes):
        node = lkg.nodes.get(nid) or repo.nodes[nid]
        if node.type in _TRACKED_TYPES and _file_of(nid, graphs) in plan_files and _changed(nid, repo, lkg):
            out.add(nid)
    return out


def plan(
    repo: threads.Analysis,
    lkg: threads.Analysis,
    broken_files: Iterable[str],
    restorable: Callable[[str], bool],
) -> dict[str, Any]:
    """Supervision plan for `broken_files`. Pure: `restorable` is injected by the caller."""
    rg, lg = repo.graph, lkg.graph
    graphs = (rg, lg)
    broken = sorted(set(broken_files))
    tools = sorted({n.id.removeprefix("tool:") for g in graphs for n in g.nodes_of("tool")})
    if not broken:
        return {"strategy": NO_STRATEGY, "units": [], "files": [], "supervisor": [], "unaffected_tools": []}

    edges = _union_edges(graphs)
    units = file_units(rg, lg)  # dependencies first
    unit_of = {f: i for i, comp in enumerate(units) for f in comp}
    for f in broken:  # a file with no dependency edges is its own unit
        if f not in unit_of:
            units.append([f])
            unit_of[f] = len(units) - 1
    broken_units = sorted({unit_of[f] for f in broken})
    rest_units = [u for u in broken_units if _changed_consumers(set(units[u]), rg, lg, edges)]
    selected: dict[int, str] = dict.fromkeys(broken_units, "broken")
    frontier = list(rest_units)
    while frontier:  # propagate only along changed contracts: a unit whose exports are unchanged stops the wave
        cur = frontier.pop()
        for f in sorted(_changed_consumers(set(units[cur]), rg, lg, edges)):
            nxt = unit_of.get(f)
            if nxt is not None and nxt not in selected:
                selected[nxt] = "dependent"
                frontier.append(nxt)

    planned: list[dict[str, Any]] = []
    for u in sorted(selected):  # index order == dependencies first
        files = [f for f in units[u] if restorable(f)]
        if files:
            planned.append({"id": f"scc:{units[u][0]}", "role": selected[u], "files": files})
    plan_files = sorted({f for pu in planned for f in pu["files"]})

    fn_adj: dict[str, list[str]] = {}
    for src, dst, kind in edges:
        if kind == "consumes" and src.startswith("fn:") and dst.startswith("fn:"):
            fn_adj.setdefault(src, []).append(dst)
    changed = _changed_nodes(set(plan_files), rg, lg)
    affected = [t for t in tools if (_tool_subtree(t, fn_adj) | {f"tool:{t}"}) & changed]
    strategy = NO_STRATEGY if not planned else (REST_FOR_ONE if rest_units else ONE_FOR_ONE)
    return {
        "strategy": strategy,
        "units": planned,
        "files": plan_files,
        "supervisor": affected,
        "unaffected_tools": [t for t in tools if t not in affected],
    }
