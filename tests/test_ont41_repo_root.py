"""ONT-41 TC0: anclajes `__file__` (clase C, código) vs `AEP_REPO_ROOT` (clase D, datos)."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.fingerprint import REPO_ROOT_ENV, code_fingerprint, resolve_repo_root

ROOT = Path(__file__).resolve().parent.parent

# Sitios C: el ancla `__file__` es deliberada (el código en ejecución, p. ej. un snapshot LKG).
C_SITES: dict[str, set[str] | None] = {
    "server.py": {"PROJECT_DIR", "_read_git_head_commit"},
    "aep_backend.py": {"PROJECT_ROOT"},
    "aep_front.py": {"_fallback_code_fingerprint", "PROJECT_ROOT", "project_root", "<module>"},
    "aep_lkg.py": {"_own_source_hash", "_lkg_source", "<module>"},
    "scripts/aep-ctl": {"PROJECT_ROOT"},
    "engine/fingerprint.py": {"_resolve_repo_root"},
    "engine/catalog.py": None,  # ancla deliberada; el ámbito exacto no se fija
    "engine/hydrator.py": None,
    "engine/template_registry.py": {"REGISTRY_PATH"},
    "engine/threads_probes.py": {"PROJECT_DIR"},  # trusted: C a propósito (fail-closed bajo LKG)
    "engine/privilege.py": {"_CODE_ROOT"},
}
# Sitios D: ningún `__file__` crudo dentro de estos ámbitos.
D_SCOPES: dict[str, set[str]] = {
    "server.py": {"_is_front_stale", "REPO_ROOT", "autoevol"},
    "engine/privilege.py": {"detect_privilege_tier"},
    "aep_backend.py": {"BackendWorker", "handle_line", "REPO_ROOT"},
}


def _scopes_using_file(rel: str) -> set[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    found: set[str] = set()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Name) and child.id == "__file__":
                found.add(scope)
            nxt = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                nxt = child.name
            elif scope == "<module>" and isinstance(child, ast.Assign) and isinstance(child.targets[0], ast.Name):
                nxt = child.targets[0].id
            visit(child, nxt)

    visit(tree, "<module>")
    return found


def test_d_sites_never_use_raw_file() -> None:
    assert resolve_repo_root(ROOT).is_dir()  # anchor under test resolves to a real directory
    for rel, scopes in D_SCOPES.items():
        used = _scopes_using_file(rel)
        assert not (used & scopes), f"{rel}: D site uses raw __file__ in {used & scopes}"


def test_d_sites_resolve_through_repo_root() -> None:
    assert resolve_repo_root(ROOT).is_dir()  # anchor under test resolves to a real directory
    server_src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "REPO_ROOT: Path = resolve_repo_root(PROJECT_DIR)" in server_src
    assert 'front_path = REPO_ROOT / "aep_front.py"' in server_src
    assert "disk_fp = code_fingerprint(REPO_ROOT)" in server_src
    assert "if root else REPO_ROOT" in server_src
    assert "resolve_repo_root(_CODE_ROOT)" in (ROOT / "engine/privilege.py").read_text(encoding="utf-8")
    assert "code_fingerprint(REPO_ROOT)" in (ROOT / "aep_backend.py").read_text(encoding="utf-8")


def test_c_sites_regression_stay_on_file() -> None:
    """Los sitios C siguen anclados a `__file__` (solo los ámbitos nombrados), incl. el trusted de threads_probes."""
    assert resolve_repo_root(ROOT).is_dir()  # anchor under test resolves to a real directory
    for rel, allowed in C_SITES.items():
        used = _scopes_using_file(rel)
        assert used, f"{rel}: expected a deliberate __file__ anchor"
        if allowed is not None:
            assert used <= allowed, f"{rel}: unexpected __file__ scopes {used - allowed}"


def test_fingerprint_callers_pass_explicit_root() -> None:
    assert resolve_repo_root(ROOT).is_dir()  # anchor under test resolves to a real directory
    offenders: list[str] = []
    for rel in ("server.py", "aep_backend.py", "aep_front.py", "aep_lkg.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                if name in ("code_fingerprint", "_fallback_code_fingerprint") and not node.args and not node.keywords:
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def test_resolve_repo_root_without_env_is_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(REPO_ROOT_ENV, raising=False)
    assert resolve_repo_root(tmp_path) == tmp_path.resolve()
    monkeypatch.setenv(REPO_ROOT_ENV, str(ROOT))
    assert resolve_repo_root(tmp_path) == ROOT
    monkeypatch.setenv(REPO_ROOT_ENV, "   ")
    assert resolve_repo_root(tmp_path) == tmp_path.resolve()


def _probe(env_extra: dict[str, str], cwd: Path) -> list[str]:
    code = "import server, json; print(json.dumps([str(server.REPO_ROOT), str(server.PROJECT_DIR)]))"
    env = {k: v for k, v in os.environ.items() if k != REPO_ROOT_ENV}
    env.update(env_extra)
    env["PYTHONPATH"] = str(ROOT)
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert res.returncode == 0, res.stderr[-800:]
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_server_repo_root_env_and_default(tmp_path: Path) -> None:
    other = tmp_path / "repo"
    other.mkdir()
    default = _probe({}, tmp_path)
    assert default[0] == default[1] == str(ROOT)  # sin AEP_REPO_ROOT: idéntico
    overridden = _probe({REPO_ROOT_ENV: str(other)}, tmp_path)
    assert overridden == [str(other.resolve()), str(ROOT)]  # solo cambia el ancla D


def test_default_fingerprint_unchanged_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REPO_ROOT_ENV, raising=False)
    assert code_fingerprint(ROOT) == code_fingerprint(resolve_repo_root(ROOT))
