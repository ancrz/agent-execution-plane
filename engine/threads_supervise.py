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
  - A consumer joins the plan ONLY if it is broken against the contract RESTORED from the LKG (AST check of its
    usage vs the LKG exports: a referenced symbol is absent, or a call no longer fits the LKG signature) or it
    does not compile itself. Unrelated local edits never pull a consumer in: it is listed in `preserved`.
    A syntax error in the broken module is compared against what the LKG exports, never "everything vanished".
  - `rest_for_one` iff at least one such consumer exists (plan = broken unit + those consumers and, wave-wise,
    their broken consumers, dependencies first). Otherwise `one_for_one`.
  Dependents are included only if `restorable(file)` (in the LKG set and different from it); identical files
  are never rewritten. No other file can enter the plan: the full tree is never reverted.
"""

from __future__ import annotations

import ast
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


# --------------------------------------------------------------------------- consumer compatibility (AST)


def _reader(repo: threads.Analysis, lkg: threads.Analysis) -> Callable[[str, str], str | None]:
    roots = {"repo": repo.root, "lkg": lkg.root}

    def read(which: str, rel: str) -> str | None:
        try:
            return (roots[which] / rel).read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return None

    return read


def _dotted(rel: str) -> str:
    return rel.removesuffix(".py").replace("/", ".")


def _sig(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    a = fn.args
    pos = [x.arg for x in (*a.posonlyargs, *a.args)]
    return {
        "pos": pos,
        "required": len(pos) - len(a.defaults),
        "varargs": a.vararg is not None,
        "kwonly": {x.arg for x in a.kwonlyargs},
        "kwonly_required": {x.arg for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=True) if d is None},
        "varkw": a.kwarg is not None,
    }


def _exports(tree: ast.Module) -> dict[str, dict[str, Any] | None]:
    """Module-level public-surface symbols: functions carry a signature, everything else is name-only."""
    out: dict[str, dict[str, Any] | None] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _sig(node)
        elif isinstance(node, ast.ClassDef):
            out[node.name] = None
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name):
                    out[t.id] = None
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                out[(al.asname or al.name).split(".")[0]] = None
    return out


def _call_fits(call: ast.Call, sig: dict[str, Any]) -> bool:
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return True  # dynamic arguments: cannot prove a mismatch
    npos = len(call.args)
    kws = {k.arg for k in call.keywords}
    if npos > len(sig["pos"]) and not sig["varargs"]:
        return False
    if not sig["varkw"] and not kws <= (set(sig["pos"][npos:]) | sig["kwonly"]):
        return False
    if any(name not in kws for name in sig["pos"][npos : sig["required"]]):
        return False
    return sig["kwonly_required"] <= kws


def _usages(tree: ast.Module, modules: set[str]) -> list[tuple[str, str, ast.Call | None]]:
    """(module, symbol, call-or-None) for every reference the consumer makes to the given modules."""
    name_of: dict[str, tuple[str, str]] = {}  # local name -> (module, symbol)
    mod_alias: dict[str, str] = {}  # local dotted name -> module
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for al in node.names:
                if node.module in modules:
                    name_of[al.asname or al.name] = (node.module, al.name)
                elif f"{node.module}.{al.name}" in modules:
                    mod_alias[al.asname or al.name] = f"{node.module}.{al.name}"
        elif isinstance(node, ast.Import):
            for al in node.names:
                if al.name in modules:
                    mod_alias[al.asname or al.name] = al.name
    calls = {id(n.func): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    out: list[tuple[str, str, ast.Call | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in name_of:
            out.append((*name_of[node.id], calls.get(id(node))))
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            base = ast.unparse(node.value)
            if base in mod_alias:
                out.append((mod_alias[base], node.attr, calls.get(id(node))))
    return out


def _broken_reason(consumer: str, unit_files: list[str], read: Callable[[str, str], str | None]) -> str:
    """Why `consumer` would break once `unit_files` are restored from the LKG; "" if it would not."""
    text = read("repo", consumer)
    if text is None:
        return ""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "consumer does not compile"
    exports: dict[str, dict[str, dict[str, Any] | None]] = {}
    for rel in unit_files:
        base = read("lkg", rel)
        try:
            exports[_dotted(rel)] = _exports(ast.parse(base)) if base is not None else {}
        except SyntaxError:
            exports[_dotted(rel)] = {}
    known = {m for m, syms in exports.items() if syms}  # an unreadable LKG file proves nothing
    for mod, sym, call in _usages(tree, known):
        if sym not in exports[mod]:
            return f"uses {mod}.{sym}, absent from the restored contract"
        sig = exports[mod][sym]
        if call is not None and sig is not None and not _call_fits(call, sig):
            return f"calls {mod}.{sym} with a signature the restored contract does not have"
    return ""


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
    source: Callable[[str, str], str | None] | None = None,
) -> dict[str, Any]:
    """Supervision plan for `broken_files`. `restorable` and `source(which, rel)` ("repo"|"lkg") are injectable."""
    rg, lg = repo.graph, lkg.graph
    graphs = (rg, lg)
    broken = sorted(set(broken_files))
    tools = sorted({n.id.removeprefix("tool:") for g in graphs for n in g.nodes_of("tool")})
    if not broken:
        return {
            "strategy": NO_STRATEGY,
            "units": [],
            "files": [],
            "supervisor": [],
            "unaffected_tools": [],
            "preserved": [],
        }

    edges = _union_edges(graphs)
    units = file_units(rg, lg)  # dependencies first
    unit_of = {f: i for i, comp in enumerate(units) for f in comp}
    for f in broken:  # a file with no dependency edges is its own unit
        if f not in unit_of:
            units.append([f])
            unit_of[f] = len(units) - 1
    broken_units = sorted({unit_of[f] for f in broken})
    read = source or _reader(repo, lkg)
    selected: dict[int, str] = dict.fromkeys(broken_units, "broken")
    preserved: dict[str, str] = {}
    frontier = list(broken_units)
    while frontier:  # the wave follows consumers that are actually broken against the restored (LKG) contract
        cur = frontier.pop()
        for f in sorted(_changed_consumers(set(units[cur]), rg, lg, edges)):
            nxt = unit_of.get(f)
            if nxt is None or nxt in selected:
                continue
            reason = _broken_reason(f, units[cur], read)
            if reason:
                selected[nxt] = "dependent"
                frontier.append(nxt)
            elif restorable(f):
                preserved[f] = "consumer is compatible with the restored contract (unrelated local edits kept)"
    for f in [f for f in preserved if unit_of.get(f) in selected]:
        del preserved[f]

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
    strategy = NO_STRATEGY if not planned else (REST_FOR_ONE if len(selected) > len(broken_units) else ONE_FOR_ONE)
    return {
        "strategy": strategy,
        "units": planned,
        "files": plan_files,
        "supervisor": affected,
        "unaffected_tools": [t for t in tools if t not in affected],
        "preserved": [{"file": f, "reason": r} for f, r in sorted(preserved.items())],
    }
