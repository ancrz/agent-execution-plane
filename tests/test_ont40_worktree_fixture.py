"""ONT-40 T0 (F7): fixture del worktree pre-L1 fuera del repo, con limpieza en finally."""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import pytest

from engine import threads_extractors as ex
from tests._threads_support import (
    PRE_L1_COMMIT,
    REPO_ROOT,
    commit_exists,
    detached_worktree,
    worktree_listed,
)

pytestmark = pytest.mark.skipif(not commit_exists(PRE_L1_COMMIT), reason="pre-L1 commit not in this clone")


def test_worktree_lives_outside_repo_and_is_pre_l1() -> None:
    with detached_worktree(PRE_L1_COMMIT) as wt:
        assert REPO_ROOT not in wt.resolve().parents, "fixture must live outside the repository"
        assert (wt / "server.py").is_file()
        assert "server.py" in ex.read_sources(wt).code
        # Pre-L1: sin presupuestos de tokens (L1 los añadió) y versión sin fuente única (D-12).
        assert not (wt / "tests" / "test_token_budgets.py").exists()
        assert 'version = "0.1.0"' in (wt / "pyproject.toml").read_text(encoding="utf-8")


def test_worktree_cleaned_after_normal_exit() -> None:
    with detached_worktree(PRE_L1_COMMIT) as wt:
        assert worktree_listed(wt)
        assert ex.read_sources(wt).texts
    assert not wt.exists()
    assert not worktree_listed(wt)


def test_worktree_cleaned_after_exception() -> None:
    captured: list[Path] = []
    with pytest.raises(RuntimeError, match="boom"), detached_worktree(PRE_L1_COMMIT) as wt:
        captured.append(wt)
        assert ex.read_sources(wt).code
        raise RuntimeError("boom")
    assert not captured[0].exists()
    assert not worktree_listed(captured[0])


def test_ast_dump_is_stable_and_py_version_is_recordable() -> None:
    """T0: `ast.dump` es determinista dentro de una versión de Python; la versión se registra por generación."""
    src = (REPO_ROOT / "engine" / "telemetry.py").read_text(encoding="utf-8")
    h1 = hashlib.sha256(ast.dump(ast.parse(src)).encode()).hexdigest()
    h2 = hashlib.sha256(ast.dump(ast.parse(src)).encode()).hexdigest()
    assert h1 == h2 and ex.module_name("engine/x.py") == "engine.x"
    assert sys.version_info[:2] >= (3, 14)
