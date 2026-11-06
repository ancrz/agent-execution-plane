"""Dokimos ONT-42a/ONT-41 findings. xfail(strict) tests document open defects; remove the marker when the fix lands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine import harness_reconnect as hr
from tests.test_ont42a_harness_reconnect import _mk_proc, _pts_nr

VERSIONED = "/home/u/.local/share/claude/versions/2.1.318"


def _versioned_tree(root: Path, exe: str = VERSIONED) -> Path:
    _mk_proc(root, 100, 1, exe, _pts_nr(3))
    _mk_proc(root, 200, 100, "/usr/bin/python3")
    _mk_proc(root, 300, 200, "/usr/bin/python3")
    return root


def test_l1_find_harness_recognises_versioned_claude_binary(tmp_path: Path) -> None:
    res = hr.find_harness(_versioned_tree(tmp_path), 300, os.getuid())
    assert res["found"] and res["pid"] == 100 and res["harness"] == "claude"


@pytest.mark.parametrize(
    "exe",
    [
        "/home/u/evil/versions/2.1.318",  # not under .../claude/versions/
        "/home/u/.local/share/claude/versions/latest",  # not a semver
        "/home/u/.local/share/claude/versions/2.1.318/../x",  # traversal-looking
        "/home/u/.local/share/claude/versions/2.1",  # incomplete semver
    ],
)
def test_l1_fix_must_stay_strict_about_versioned_paths(tmp_path: Path, exe: str) -> None:
    assert hr.find_harness(_versioned_tree(tmp_path, exe), 300, os.getuid())["found"] is False


def test_l2_plan_reports_ancestry_even_when_route_is_noop(tmp_path: Path) -> None:
    """Refutes the L2 hypothesis: build_plan already resolves harness/tty before the noop decision (only L1 hides them)."""
    _mk_proc(tmp_path, 100, 1, "/usr/bin/claude", _pts_nr(3))
    _mk_proc(tmp_path, 200, 100, "/usr/bin/python3")
    plan = hr.build_plan(front_stale=False, proc_root=tmp_path, start_pid=200, adapters=hr.dry_adapters())
    assert plan["recommended_route"] == "noop" and plan["harness"] == "claude" and plan["tty"] == "/dev/pts/3"


def test_l3_reaper_covers_lkg_tree_backends(tmp_path: Path) -> None:
    from tests.test_ont41_front import reap_backends_of

    repo = tmp_path / "repo"
    repo.mkdir()
    lkg_tree = tmp_path / "front_state" / "data" / "lkg" / "abc" / "tree"
    lkg_tree.mkdir(parents=True)
    (lkg_tree / "aep_backend.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(lkg_tree / "aep_backend.py")])  # noqa: S603
    try:
        assert (
            reap_backends_of(repo) == 1
        )  # the fixture only passes `root`; the LKG tree lives under tmp_path/front_state
    finally:
        proc.kill()
        proc.wait()
