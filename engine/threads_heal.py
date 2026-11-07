"""
Engine: threads_heal.py (ONT-41 TB2: thread-scoped healing against the Last-Known-Good tree)

`heal` statically compares the live repo against the LKG snapshot using `engine.threads.analyze`
(no code of either tree is executed), lists the broken threads (syntax errors and modules whose node
hash changed and that introduce new gaps), their reach, files and diff hunks, and optionally restores
ONLY those files from the LKG.

Supervision (E3): the restore set is the OTP-style plan of `engine.threads_supervise` (one_for_one or
rest_for_one over SCC units); `heal` never reverts the whole tree.

Safety contract (apply=True):
  1. `snapshot_fn` is mandatory and injected (Phase C wires `workspace_snapshot`); it is called with the
     list of files about to be touched BEFORE any write. A raising/falsy-failure snapshot aborts with
     SNAPSHOT_FAILED and nothing is written.
  2. Restore goes through `aep_lkg.restore_files` (dry-run rehearsal first, then real write), never a
     global rollback: files outside the broken-thread set are never touched.

Topos: depends on `aep_lkg` (stdlib leaf) and `engine.threads`; never imports `server`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aep_lkg
from engine import threads, threads_supervise

SCOPE_LIMIT = 50


def _snapshot_ok(result: Any) -> bool:
    """A snapshot failed when it returned False or an error-shaped dict; None means 'done'."""
    if result is False:
        return False
    return not (isinstance(result, dict) and (result.get("ok") is False or result.get("error")))


def _file_restorable(rel: str, manifest: dict[str, Any], root: Path) -> bool:
    """In the LKG set and different from it (missing counts as different)."""
    try:
        aep_lkg.safe_rel(rel)
    except aep_lkg.LkgError:
        return False
    if rel not in manifest["files"]:
        return False
    target = root / rel
    return not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != manifest["files"][rel]


def _broken_threads(repo: threads.Analysis, lkg: threads.Analysis, manifest: dict[str, Any], root: Path) -> list[dict]:
    lkg_gap_ids = {g.id for g in lkg.gaps}
    by_module: dict[str, list[threads.Gap]] = {}
    for gap in repo.gaps:
        if gap.id in lkg_gap_ids or gap.node not in repo.graph.nodes:
            continue
        mod = threads._module_of(gap.node, repo.graph)
        if mod:
            by_module.setdefault(f"module:{mod}", []).append(gap)
    broken: list[dict] = []
    for mod_id in sorted(by_module):
        node = repo.graph.nodes.get(mod_id)
        # Modules absent from the LKG (e.g. aep_front.py, outside the snapshot set) have no baseline to heal to.
        if node is None or mod_id not in lkg.node_hash or repo.node_hash.get(mod_id) == lkg.node_hash[mod_id]:
            continue
        rel = str(node.attrs.get("path", ""))
        gaps = sorted(by_module[mod_id], key=lambda g: g.id)
        entry: dict[str, Any] = {
            "module": mod_id,
            "file": rel,
            "kinds": sorted({g.kind for g in gaps}),
            "gaps": [g.id for g in gaps],
            "syntax_error": str(node.attrs.get("syntax_error", "")),
            "scope": sorted(threads.reverse_reach(repo.graph, mod_id))[:SCOPE_LIMIT],
            "restorable": False,
            "diff": {"hunks": []},
        }
        entry["restorable"] = _file_restorable(rel, manifest, root)
        broken.append(entry)
    return broken


def heal(
    repo_root: Path | str,
    key: str | None = None,
    apply: bool = False,
    snapshot_fn: Callable[[list[str]], Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    lkg_key = key or aep_lkg.latest()
    if not lkg_key:
        return {"status": "NO_LKG", "applied": False}
    verdict = aep_lkg.verify(lkg_key)
    if not verdict["ok"]:
        return {"status": "LKG_INVALID", "key": lkg_key, "errors": verdict["errors"], "applied": False}
    manifest = aep_lkg.read_manifest(lkg_key)
    repo_a = threads.analyze(root, use_cache=False)
    lkg_a = threads.analyze(aep_lkg.tree_path(lkg_key), use_cache=False)
    broken = _broken_threads(repo_a, lkg_a, manifest, root)
    broken_files = sorted({e["file"] for e in broken if e["restorable"]})
    sup = threads_supervise.plan(repo_a, lkg_a, broken_files, lambda rel: _file_restorable(rel, manifest, root))
    files = list(sup["files"])  # the restore set IS the supervision plan: nothing outside its units
    for entry in broken:
        if entry["restorable"]:
            entry["diff"] = aep_lkg.diff(lkg_key, entry["file"], root)
    report: dict[str, Any] = {
        "status": "BROKEN" if broken else "CLEAN",
        "key": lkg_key,
        "threads": broken,
        "files": files,
        "strategy": sup["strategy"],
        "units": sup["units"],
        "supervisor": sup["supervisor"],
        "unaffected_tools": sup["unaffected_tools"],
        "preserved": sup["preserved"],
        "applied": False,
        "restored": [],
    }
    if not apply or not files:
        return report
    if snapshot_fn is None:
        return {**report, "status": "SNAPSHOT_REQUIRED"}
    try:
        snap = snapshot_fn(list(files))
    except Exception as exc:  # noqa: BLE001 - any snapshot failure must abort without writing
        return {**report, "status": "SNAPSHOT_FAILED", "error": f"{type(exc).__name__}: {exc}"}
    if not _snapshot_ok(snap):
        return {**report, "status": "SNAPSHOT_FAILED", "error": "snapshot_fn reported failure"}
    try:
        restored = aep_lkg.restore_files(lkg_key, files, root, dry_run=False)
    except aep_lkg.LkgError as exc:
        return {**report, "status": "RESTORE_FAILED", "error": str(exc), "snapshot": snap}
    after = threads.analyze(root, use_cache=False)
    remaining = sorted(g.id for g in after.gaps if g.kind == "syntax_error")
    return {
        **report,
        "status": "HEALED" if not remaining else "PARTIAL",
        "applied": True,
        "restored": restored["restored"],
        "snapshot": snap,
        "remaining_syntax_errors": remaining,
    }
