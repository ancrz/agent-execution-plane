"""
Engine: threads_gitport.py (ONT-42c C2/C3: implementacion CLI del GitPort de `threads_evolve`)

Unico modulo de AEP que escribe en git por cuenta de `autoevol(evolve)`. No importa `server` ni `aep_front`: la ruta del
fence y los directorios los inyecta el llamante.

Prohibiciones (condicion 12, vigiladas por test AST/grep sobre este archivo y sobre `threads_evolve`):
  - solo se publica con refspec literal (`dev` y `autoevol/<ciclo>`), jamas con opciones de fuerza ni refspec con prefijo `+`;
  - sin reescritura de historia (ninguna rama existente se mueve ni se reemplaza);
  - sin traer cambios del remoto: la unica integracion es `merge --ff-only` de una rama local.

El commit se construye con fontaneria (indice temporal -> `write-tree` -> `commit-tree` -> `update-ref` con valor anterior
vacio): no toca el indice ni el HEAD del worktree del agente y no puede pisar una rama existente.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

DEV = "dev"
REMOTE = "origin"
BRANCH_RE = re.compile(r"^autoevol/[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
GIT_TIMEOUT_S = 60
NET_TIMEOUT_S = 30
EXCLUDE_PREFIXES: tuple[str, ...] = (".claude/", ".venv/", "__pycache__/", ".aep_swap_fence")
_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "aep-autoevol",
    "GIT_AUTHOR_EMAIL": "autoevol@localhost",
    "GIT_COMMITTER_NAME": "aep-autoevol",
    "GIT_COMMITTER_EMAIL": "autoevol@localhost",
}
GitResult = tuple[bool, str]


class GitCli:
    """GitPort sobre el binario `git`. `work` = worktree con el parche; `canonical` = checkout de `dev` (destino del merge)."""

    def __init__(self, work: Path | str, canonical: Path | str, fence: Path | str, *, git_bin: str = "git") -> None:
        self.work = Path(work)
        self.canonical = Path(canonical)
        self.fence = Path(fence)
        self._git = git_bin

    # -- primitivas -------------------------------------------------------------------------------
    def _run(
        self, repo: Path, *args: str, timeout: int = GIT_TIMEOUT_S, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        full_env = {**os.environ, **_ENV, **(env or {})}
        try:
            return subprocess.run(  # noqa: S603 - argv literal, sin shell
                [self._git, "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=full_env,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(args, 127, "", f"{type(exc).__name__}: {str(exc)[:80]}")

    def _out(self, repo: Path, *args: str) -> str | None:
        res = self._run(repo, *args)
        return res.stdout.strip() if res.returncode == 0 else None

    # -- lectura ----------------------------------------------------------------------------------
    def current_branch(self) -> str:
        return self._out(self.canonical, "rev-parse", "--abbrev-ref", "HEAD") or ""

    def rev_parse(self, ref: str) -> str | None:
        return self._out(self.canonical, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")

    def tree_of(self, ref: str) -> str | None:
        return self._out(self.canonical, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return self._run(self.canonical, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0

    def dirty_tracked(self, ref_a: str, ref_b: str) -> list[str]:
        """Archivos TRACKED con cambios locales entre los que toca el diff `ref_a..ref_b` (se ignoran los untracked)."""
        touched = self._out(self.canonical, "diff", "--name-only", f"{ref_a}..{ref_b}")
        if not touched:
            return []
        files = touched.splitlines()
        status = self._out(self.canonical, "status", "--porcelain", "--untracked-files=no", "--", *files)
        return [line[3:] for line in (status or "").splitlines() if line.strip()]

    def remote_reachable(self) -> bool:
        return self._run(self.canonical, "ls-remote", "--exit-code", REMOTE, DEV, timeout=NET_TIMEOUT_S).returncode in (0, 2)

    def remote_head(self, ref: str) -> str | None:
        out = self._out(self.canonical, "ls-remote", REMOTE, ref)
        return out.split()[0] if out else None

    def export_tree(self, ref: str, dest: Path | str) -> bool:
        """Extrae el arbol COMMITEADO de `ref` en `dest` (vacio) con `git archive`: no toca worktree, indice ni HEAD."""
        if ref != DEV and not BRANCH_RE.fullmatch(ref):
            return False
        try:
            proc = subprocess.run(  # noqa: S603 - argv literal, sin shell
                [self._git, "-C", str(self.canonical), "archive", "--format=tar", ref],
                capture_output=True,
                timeout=GIT_TIMEOUT_S,
                check=False,
                env={**os.environ, **_ENV},
            )
            if proc.returncode != 0:
                return False
            with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
                tar.extractall(Path(dest), filter="data")
        except (OSError, subprocess.SubprocessError, tarfile.TarError):
            return False
        return True

    # -- escritura local --------------------------------------------------------------------------
    def _candidate_paths(self) -> list[str]:
        changed = self._out(self.work, "diff", "--name-only", "HEAD") or ""
        fresh = self._out(self.work, "ls-files", "--others", "--exclude-standard") or ""
        return sorted(
            {p for p in (*changed.splitlines(), *fresh.splitlines()) if p and not p.startswith(EXCLUDE_PREFIXES)}
        )

    @contextlib.contextmanager
    def _temp_index(self) -> Iterator[dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix="aep_evolve_idx_") as tmp:
            yield {"GIT_INDEX_FILE": str(Path(tmp) / "index")}

    def work_root(self) -> str:
        return os.path.realpath(self.work)

    def candidate_tree(self) -> str | None:
        """Hash del arbol que resultaria de commitear el parche (HEAD + cambios), sin tocar el indice real."""
        paths = self._candidate_paths()
        if not paths:
            return None
        with self._temp_index() as env:
            if self._run(self.work, "read-tree", "HEAD", env=env).returncode != 0:
                return None
            if self._run(self.work, "add", "-A", "--", *paths, env=env).returncode != 0:
                return None
            res = self._run(self.work, "write-tree", env=env)
        return res.stdout.strip() if res.returncode == 0 else None

    def commit_branch(self, branch: str, tree: str, message: str) -> GitResult:
        """Crea `branch` (debe no existir) apuntando a un commit de `tree` cuyo padre es el HEAD del worktree."""
        if not BRANCH_RE.fullmatch(branch):
            return False, "bad_branch_name"
        parent = self._out(self.work, "rev-parse", "HEAD")
        if not parent:
            return False, "no_head"
        made = self._run(self.work, "commit-tree", tree, "-p", parent, "-m", message)
        if made.returncode != 0:
            return False, "commit_tree_failed"
        sha = made.stdout.strip()
        zero = "0" * 40
        ref = self._run(self.work, "update-ref", f"refs/heads/{branch}", sha, zero)
        return (True, sha) if ref.returncode == 0 else (False, "branch_exists")

    # -- integracion y publicacion ----------------------------------------------------------------
    def merge_ff(self, branch: str) -> GitResult:
        """`merge --ff-only` en el checkout canonico, envuelto por el fence (O_EXCL). El fence cubre solo el merge."""
        if not BRANCH_RE.fullmatch(branch):
            return False, "bad_branch_name"

        def _merge() -> GitResult:
            res = self._run(self.canonical, "merge", "--ff-only", branch)
            return (True, "merged") if res.returncode == 0 else (False, "ff_rejected")

        return self._fenced(_merge)

    def _fenced(self, action: Callable[[], GitResult]) -> GitResult:
        """Ejecuta `action` con el fence tomado por O_EXCL; se libera siempre en `finally` (condiciones 7 y 8)."""
        try:
            fd = os.open(self.fence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return False, "fence_held"
        except OSError:
            return False, "fence_unavailable"
        try:
            os.close(fd)
            return action()
        finally:
            with contextlib.suppress(OSError):
                self.fence.unlink()

    def revert(self, sha: str) -> GitResult:
        """C6 (condicion 15): `git revert` como commit NUEVO sobre `dev`, dentro del fence y sin push. Nunca reescribe historia."""
        if not SHA_RE.fullmatch(sha):
            return False, "bad_sha"

        def _revert() -> GitResult:
            res = self._run(self.canonical, "revert", "--no-edit", sha)
            if res.returncode == 0:
                return True, self._out(self.canonical, "rev-parse", "HEAD") or ""
            self._run(self.canonical, "revert", "--abort")  # deja el checkout como estaba
            return False, "revert_failed"

        return self._fenced(_revert)

    def push(self, ref: str) -> GitResult:
        """Publica `dev` o `autoevol/<ciclo>` con refspec literal. Un rechazo se devuelve tal cual (sin reintentos)."""
        if ref != DEV and not BRANCH_RE.fullmatch(ref):
            return False, "bad_ref"
        res = self._run(self.canonical, "push", REMOTE, ref, timeout=NET_TIMEOUT_S)
        return (True, "pushed") if res.returncode == 0 else (False, "push_rejected")
