"""ONT-42c E1: juez no falsificable. El ACCEPT exige tests que fallan en la BASE y pasan con el parche."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from engine import threads_ops as ops
from engine import threads_verify as tv

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}
_MOD_UNFIXED = "def run_op():\n    return 41\n"
_MOD_FIXED = "def run_op():\n    return 42\n"
_TEST_XFAIL = (
    "import pytest\nfrom engine import mod\n\n"
    "@pytest.mark.xfail(strict=True, reason='D-88')\n"
    "def test_op():\n    assert mod.run_op() == 42\n"
)
_TEST_PLAIN = "from engine import mod\n\n\ndef test_op():\n    assert mod.run_op() == 42\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **_GIT_ENV})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "engine").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "engine" / "mod.py").write_text(_MOD_UNFIXED, encoding="utf-8")
    (tmp_path / "tests" / "test_mod.py").write_text(_TEST_XFAIL, encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _runner_for(tree: Path) -> Callable[[list[str]], dict[str, Any]]:
    """Runner real de pytest sobre `tree` (sin bwrap): conteos y `failing` como el runner del servidor."""

    def run(tests: list[str]) -> dict[str, Any]:
        env = {**os.environ, "PYTHONPATH": str(tree), "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=tree, capture_output=True, text=True, env=env, timeout=120, check=False,
        )
        text = proc.stdout

        def n(word: str) -> int:
            m = re.search(rf"(\d+) {word}", text)
            return int(m.group(1)) if m else 0

        failing = re.findall(r"^FAILED (\S+)", text, re.MULTILINE)
        return {
            "ran": n("passed") + n("failed") + n("error") + n("xfailed") + n("xpassed"),
            "passed": n("passed"),
            "failed": n("failed"),
            "errors": n("error"),
            "exit_code": proc.returncode,
            "failing": failing,
        }

    return run


def _verify(repo: Path) -> dict[str, Any]:
    return ops.run_verify(
        repo, gap="D-88", snapshot=None, barrier=None, serving_lkg=False,
        run_tests=_runner_for(repo), dispatch_job=None, poll_job=None, job=None,
        trusted=True, terse=False, base_runner=_runner_for,
    )


def test_non_discriminating_is_registered_and_not_environmental() -> None:
    assert tv.NON_DISCRIMINATING in tv.REJECT_REASONS
    assert tv.NON_DISCRIMINATING not in ops.ENVIRONMENTAL
    order = tv.REJECT_REASONS
    assert order.index(tv.TESTS_FAIL) < order.index(tv.NON_DISCRIMINATING) < order.index(tv.BUDGET)


def test_d01b_case_fix_and_xfail_removed_accepts_with_discriminating(repo: Path) -> None:
    (repo / "engine" / "mod.py").write_text(_MOD_FIXED, encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(_TEST_PLAIN, encoding="utf-8")
    out = _verify(repo)
    assert out["verdict"] == tv.ACCEPT, out
    assert out["discriminating"] == ["tests/test_mod.py::test_op"]


def test_removing_xfail_without_fix_is_rejected(repo: Path) -> None:
    (repo / "tests" / "test_mod.py").write_text(_TEST_PLAIN, encoding="utf-8")
    out = _verify(repo)
    assert out["verdict"] == tv.REJECT
    assert tv.TESTS_FAIL in out["reasons"]


def test_patch_not_touching_the_test_is_not_accepted(repo: Path) -> None:
    (repo / "engine" / "mod.py").write_text(_MOD_FIXED, encoding="utf-8")
    out = _verify(repo)
    assert out["verdict"] == tv.REJECT
    assert out["reasons"] == [tv.NO_PROGRESS]
    assert out["tests"]["selected"] == 0 and "discriminating" not in out


def test_passing_on_base_too_is_non_discriminating(repo: Path) -> None:
    # La base ya cumple (fix commiteado, xfail puesto). Quitar el xfail no discrimina nada: el test pasa en base.
    (repo / "engine" / "mod.py").write_text(_MOD_FIXED, encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(_TEST_PLAIN, encoding="utf-8")
    _git(repo, "add", "engine/mod.py")
    _git(repo, "commit", "-q", "-m", "fix already in base")
    out = _verify(repo)
    assert out["verdict"] == tv.REJECT
    assert out["reasons"] == [tv.NON_DISCRIMINATING]


def test_base_runner_infrastructure_failure_is_environmental_reject(repo: Path) -> None:
    (repo / "engine" / "mod.py").write_text(_MOD_FIXED, encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(_TEST_PLAIN, encoding="utf-8")
    out = ops.run_verify(
        repo, gap="D-88", snapshot=None, barrier=None, serving_lkg=False,
        run_tests=_runner_for(repo), dispatch_job=None, poll_job=None, job=None,
        trusted=True, terse=False, base_runner=lambda _t: (lambda _tests: {"available": False}),
    )
    assert out["verdict"] == tv.REJECT and out["reasons"] == [tv.SANDBOX_UNAVAILABLE]


def test_snapshot_base_is_not_mutated(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    snap = tmp_path_factory.mktemp("snap")
    for rel in ("engine/__init__.py", "engine/mod.py", "tests/test_mod.py"):
        (snap / rel).parent.mkdir(parents=True, exist_ok=True)
        (snap / rel).write_text((repo / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "engine" / "mod.py").write_text(_MOD_FIXED, encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(_TEST_PLAIN, encoding="utf-8")
    out = ops.run_verify(
        repo, gap="D-88", snapshot=snap, barrier=None, serving_lkg=False,
        run_tests=_runner_for(repo), dispatch_job=None, poll_job=None, job=None,
        trusted=True, terse=False, base_runner=_runner_for,
    )
    assert out["verdict"] == tv.ACCEPT and out["discriminating"]
    assert (snap / "tests" / "test_mod.py").read_text(encoding="utf-8") == _TEST_XFAIL
