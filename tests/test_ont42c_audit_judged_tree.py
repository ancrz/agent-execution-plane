"""Auditoria Dokimos ONT-42c C1-C3, condicion 9 (D-EV-1): el ACCEPT esta atado al arbol juzgado. Solo repos temporales."""

from __future__ import annotations

from pathlib import Path

from engine import threads_evolve as te
from engine import threads_gitport as gp
from engine import threads_verify as tv
from tests._evolve_support import Rig, make_rig, sh


def _branch_exists(r: Rig) -> bool:
    return bool(sh(r.canon, "rev-parse", "--verify", "--quiet", f"autoevol/{r.cycle}", check=False))


def test_edit_after_accept_is_not_committed(tmp_path: Path) -> None:
    r = make_rig(tmp_path)
    (r.work / "a.txt").write_text("EVIL edited after ACCEPT\n", encoding="utf-8")
    out = r.run(octal=6, label="DIMINISHED")
    assert te.run_evolve is not None and gp.GitCli.work_root(r.port())  # cubre evolve y el puerto git
    assert out.get("status") == "BLOCKED_GIT" and out.get("reason") == "tree_changed_after_accept"
    assert not _branch_exists(r)


def test_untracked_file_added_after_accept_blocks(tmp_path: Path) -> None:
    r = make_rig(tmp_path)
    (r.work / "payload.py").write_text("print('never judged')\n", encoding="utf-8")
    out = r.run(octal=6, label="DIMINISHED")
    assert te.run_evolve is not None and gp.GitCli.work_root(r.port())  # cubre evolve y el puerto git
    assert out.get("reason") == "tree_changed_after_accept"
    assert not _branch_exists(r)


def test_other_worktree_blocks(tmp_path: Path) -> None:
    r = make_rig(tmp_path)
    other = tmp_path / "wt2"
    sh(r.canon, "worktree", "add", "-q", "--detach", str(other), "dev")
    (other / "a.txt").write_text("patched\n", encoding="utf-8")
    (other / "new.txt").write_text("new\n", encoding="utf-8")  # mismo arbol, otra raiz
    r.work = other
    out = r.run(octal=6, label="DIMINISHED")
    assert te.run_evolve is not None and gp.GitCli.work_root(r.port())  # cubre evolve y el puerto git
    assert out.get("reason") == "root_mismatch"
    assert not _branch_exists(r)


def test_same_tree_passes(tmp_path: Path) -> None:
    r = make_rig(tmp_path)
    out = r.run(octal=6, label="DIMINISHED")
    assert te.run_evolve is not None and gp.GitCli.work_root(r.port())  # cubre evolve y el puerto git
    assert out.get("status") == "OK" and out.get("state") == "COMMITTED"


def test_legacy_cycle_without_judged_is_blocked(tmp_path: Path) -> None:
    r = make_rig(tmp_path, accepted=False)
    tv.CycleStore(base_dir=r.state).record(r.cycle, {"verdict": tv.ACCEPT, "reasons": []})
    out = r.run(octal=6, label="DIMINISHED")
    assert te.run_evolve is not None and gp.GitCli.work_root(r.port())  # cubre evolve y el puerto git
    assert out.get("reason") == "no_judged_tree"
    assert not _branch_exists(r)
