"""ONT-42c C1-C3: maquina de estados `evolve`, gating por tier, precondiciones del ff-merge. Solo repos temporales."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from engine import threads_evolve as te
from tests._evolve_support import Rig, make_rig, sh

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


def _branch(r: Rig) -> str:
    return te.branch_name(r.cycle)


def _remote_heads(r: Rig) -> set[str]:
    return {line.split()[1].removeprefix("refs/heads/") for line in sh(r.bare, "show-ref").splitlines()}


# --- C1: maquina de estados ------------------------------------------------------------------------


def test_full_flow_commit_merge_push(rig: Rig) -> None:
    out = rig.run()
    assert out["state"] == te.PUSHED and out["status"] == "OK", out
    br = _branch(rig)
    assert sh(rig.canon, "rev-parse", "dev") == sh(rig.canon, "rev-parse", br)  # ff: dev == rama
    assert sh(rig.bare, "rev-parse", "dev") == sh(rig.canon, "rev-parse", "dev")
    assert {"dev", br} <= _remote_heads(rig)
    assert (rig.canon / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert not rig.fence.exists()  # el fence se libera siempre
    assert rig.events() == ["cycle_terminal", "evolve.committed", "evolve.merged", "evolve.pushed"]


def test_reentrant_is_idempotent_and_creates_no_second_commit(rig: Rig) -> None:
    first = rig.run()
    head = sh(rig.canon, "rev-parse", "dev")
    again = rig.run()
    assert again["state"] == te.PUSHED and again["sha"] == first["sha"]
    assert sh(rig.canon, "rev-parse", "dev") == head
    assert sh(rig.canon, "rev-list", "--count", "dev") == "2"  # base + un unico commit de evolve


def test_without_cycle_or_unaccepted_cycle_only_plans(tmp_path: Path) -> None:
    r = make_rig(tmp_path, accepted=False)
    plan = r.run(cycle=None)
    assert plan["state"] == te.PLAN and plan["applied"] is False and plan["awaiting"] == "fix_test"
    waiting = r.run()
    assert waiting["state"] == te.PATCH_AWAITED and waiting["applied"] is False
    assert sh(r.canon, "branch", "--list", "autoevol/*") == ""


def test_unknown_cycle_is_not_found(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    assert rig.run(cycle="0" * 12)["status"] == "NOT_FOUND"


def test_dry_run_does_not_write(rig: Rig) -> None:
    out = rig.run(apply=False)
    assert out["state"] == te.JUDGED and out["applied"] is False and out["steps"]
    assert sh(rig.canon, "branch", "--list", "autoevol/*") == ""


def test_read_cycle_is_read_only_even_when_expired(rig: Rig) -> None:
    far = 10**10
    assert te.read_cycle(rig.cycle, base_dir=rig.state, now=far)["state"] == "EXPIRED"
    assert te.read_cycle(rig.cycle, base_dir=rig.state)["state"] == "ACCEPTED"  # no se borro


# --- C2: matriz de tiers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("octal", "label", "mode", "state", "branch", "merged", "pushed"),
    [
        (7, "FULL", "full", te.PUSHED, True, True, True),
        (6, "FULL", "local", te.COMMITTED, True, False, False),
        (6, "DIMINISHED", "local", te.COMMITTED, True, False, False),
        (7, "DIMINISHED", "local", te.COMMITTED, True, False, False),
        (5, "DIMINISHED", "plan", te.JUDGED, False, False, False),
        (4, "DIMINISHED", "plan", te.JUDGED, False, False, False),
    ],
)
def test_tier_matrix(
    tmp_path: Path, octal: int, label: str, mode: str, state: str, branch: bool, merged: bool, pushed: bool
) -> None:
    r = make_rig(tmp_path)
    assert te.gating(octal, label) == mode
    out = r.run(octal=octal, label=label)
    assert out["state"] == state, out
    assert bool(sh(r.canon, "branch", "--list", _branch(r))) is branch
    if branch:
        assert (sh(r.canon, "rev-parse", "dev") == sh(r.canon, "rev-parse", _branch(r))) is merged
    assert (_branch(r) in _remote_heads(r)) is pushed
    if not merged and branch:
        assert out["local_only"] is True
    assert sh(r.canon, "status", "--porcelain", "--untracked-files=no") == ""  # el canonico nunca se ensucia


# --- C3: precondiciones ----------------------------------------------------------------------------


def test_dev_ahead_blocks_without_rebase(rig: Rig) -> None:
    assert rig.run(octal=6)["state"] == te.COMMITTED
    (rig.canon / "b.txt").write_text("dev moved\n", encoding="utf-8")
    sh(rig.canon, "commit", "-q", "-am", "dev advanced")
    dev = sh(rig.canon, "rev-parse", "dev")
    out = rig.run()
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "dev_ahead"
    assert sh(rig.canon, "rev-parse", "dev") == dev and "evolve.blocked" in rig.events()


def test_dirty_tracked_file_touched_by_diff_blocks_but_untracked_is_ignored(rig: Rig) -> None:
    rig.run(octal=6)
    (rig.canon / "junk.txt").write_text("untracked\n", encoding="utf-8")
    (rig.canon / "a.txt").write_text("local edit\n", encoding="utf-8")  # a.txt esta en el diff del merge
    blocked = rig.run()
    assert blocked["reason"].startswith("dirty_tree")
    sh(rig.canon, "checkout", "--", "a.txt")
    ok = rig.run()
    assert ok["state"] == te.PUSHED  # el untracked no estorba


def test_remote_unreachable_blocks_before_merge(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    rig.run(octal=6)
    sh(rig.canon, "remote", "set-url", "origin", str(rig.root / "missing.git"))
    dev = sh(rig.canon, "rev-parse", "dev")
    out = rig.run()
    assert out["reason"] == "remote_unreachable"
    assert sh(rig.canon, "rev-parse", "dev") == dev


def test_fence_held_blocks_and_is_not_removed(rig: Rig) -> None:
    rig.run(octal=6)
    rig.fence.write_text("someone else", encoding="utf-8")
    out = rig.run()
    assert out["reason"] == "fence_held"
    assert rig.fence.exists()  # no se pisa ni se borra un fence ajeno
    rig.fence.unlink()
    assert rig.run()["state"] == te.PUSHED


def test_stale_or_unloaded_code_defers_push_until_reloaded(rig: Rig) -> None:
    rig.live.update(stale=True)
    out = rig.run()
    assert out["state"] == te.MERGED and out["awaiting"] == "reload"
    assert "evolve.pushed" not in rig.events() and te.branch_name(rig.cycle) not in _remote_heads(rig)
    rig.live.update(stale=False, loaded="f1", disk="f2")  # fingerprint cargado != disco
    assert rig.run()["awaiting"] == "reload"
    rig.live.update(disk="f1")
    assert rig.run()["state"] == te.PUSHED


def test_existing_branch_with_other_tree_is_blocked(rig: Rig) -> None:
    sh(rig.canon, "branch", _branch(rig), "dev")  # misma rama, arbol distinto al candidato
    out = rig.run(octal=6)
    assert out["status"] == "BLOCKED_GIT" and out["reason"] == "branch_other_tree"


def test_existing_branch_with_same_tree_is_idempotent(rig: Rig) -> None:
    tree = rig.port().candidate_tree()
    ok, sha = rig.port().commit_branch(_branch(rig), tree or "", "pre-existing")
    assert ok
    out = rig.run(octal=6)
    assert out["state"] == te.COMMITTED and out["sha"] == sha[:12]


def test_push_rejected_is_blocked_without_retry(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    other = rig.root / "other"
    sh(rig.root, "clone", "-q", str(rig.bare), str(other))
    sh(other, "checkout", "-q", "dev")
    (other / "z.txt").write_text("remote moved\n", encoding="utf-8")
    sh(other, "add", "-A")
    sh(other, "commit", "-q", "-m", "remote ahead")
    sh(other, "push", "-q", "origin", "dev")
    out = rig.run()
    assert out["status"] == "BLOCKED_GIT" and out["reason"].startswith("push_rejected")
    assert sh(rig.bare, "rev-parse", "dev") != sh(rig.canon, "rev-parse", "dev")  # no se forzo nada


def test_not_on_dev_blocks(rig: Rig) -> None:
    assert te.run_evolve  # cobertura directa del grafo
    rig.run(octal=6)
    sh(rig.canon, "checkout", "-q", "-b", "scratch")
    assert rig.run()["reason"] == "not_on_dev"


# --- Condiciones 2 y 12: acoplamiento y prohibiciones -----------------------------------------------


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_ops_and_verify_do_not_import_evolve() -> None:
    assert te.run_evolve  # cobertura directa del grafo
    for mod in ("threads_ops", "threads_verify", "threads"):
        assert not any("threads_evolve" in i or "threads_gitport" in i for i in _imports(ROOT / "engine" / f"{mod}.py"))


def test_engine_evolve_does_not_import_server_or_front() -> None:
    assert te.run_evolve  # cobertura directa del grafo
    for mod in ("threads_evolve", "threads_gitport"):
        imports = _imports(ROOT / "engine" / f"{mod}.py")
        assert not {i for i in imports if i.split(".")[0] in ("server", "aep_front")}


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_ids = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids
    ]


def test_git_prohibitions_in_port_and_machine() -> None:
    assert te.run_evolve  # cobertura directa del grafo
    forbidden = re.compile(
        r"(^|\s)(--force\S*|-f|--amend|rebase|reset|pull|main|master)(\s|$)|^\+|:\+|--force-with-lease"
    )
    for mod in ("threads_gitport", "threads_evolve"):
        path = ROOT / "engine" / f"{mod}.py"
        for const in _string_constants(path):
            assert not forbidden.search(const), (mod, const)
        src = path.read_text(encoding="utf-8")
        assert not re.search(r"--force|\brebase\b|--amend|\bpull\b|refs/heads/main|\"main\"|'main'", src), mod
        assert "--hard" not in src
