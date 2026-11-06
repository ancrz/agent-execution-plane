"""
Soporte de tests ONT-40 (T0, F7): fixture de worktree desechable fuera del repo.

`detached_worktree(commit)` crea `git worktree add --detach <tmp>/wt <commit>` en un directorio
temporal FUERA del repositorio y lo limpia SIEMPRE en `finally`: `git worktree remove --force`,
`git worktree prune` y borrado del tmpdir. Nunca toca el árbol de trabajo del repo.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Commit pre-L1 usado como realidad de referencia de la aceptación (SDD §6, plan T17).
PRE_L1_COMMIT = "b2afeb2"


def _git(*args: str, cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60, check=check
    )


def commit_exists(commit: str) -> bool:
    """True si el commit existe en el repositorio (clones superficiales pueden no tenerlo)."""
    try:
        return _git("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@contextlib.contextmanager
def detached_worktree(commit: str) -> Iterator[Path]:
    """Worktree detached de `commit` en un tmpdir fuera del repo; limpieza garantizada en finally."""
    tmp = Path(tempfile.mkdtemp(prefix="aep_threads_wt_"))
    wt = tmp / "wt"
    try:
        _git("worktree", "add", "--detach", str(wt), commit)
        yield wt
    finally:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _git("worktree", "remove", "--force", str(wt), check=False)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _git("worktree", "prune", check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def worktree_listed(path: Path) -> bool:
    """True si git aún registra `path` como worktree."""
    out = _git("worktree", "list", "--porcelain").stdout
    return any(line == f"worktree {path}" for line in out.splitlines())
