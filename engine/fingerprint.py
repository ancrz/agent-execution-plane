"""
Engine: fingerprint.py (ONT-39: Live Plane Code Fingerprint Engine)

Calculates deterministic, low-overhead (<2ms) code fingerprint over server files
to detect uncommitted working tree changes and trigger zero-downtime hot swaps.

Zero external dependencies; pure stdlib.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def _resolve_repo_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root).resolve()
    # Resolve relative to this file: engine/ -> repo_root
    return Path(__file__).resolve().parent.parent


def get_watched_files(root: Path | str | None = None) -> list[Path]:
    """Return sorted list of files monitored for code fingerprinting."""
    repo = _resolve_repo_root(root)
    files: list[Path] = []

    # Explicit top-level files
    for name in ("server.py", "aep_backend.py"):
        p = repo / name
        if p.is_file():
            files.append(p)

    # engine/**/*.py
    engine_dir = repo / "engine"
    if engine_dir.is_dir():
        for p in engine_dir.rglob("*.py"):
            # Exclude __pycache__ or temporary files
            if "__pycache__" not in p.parts and p.is_file():
                files.append(p)

    # templates/registry.json
    tpl = repo / "templates" / "registry.json"
    if tpl.is_file():
        files.append(tpl)

    # schemas/*
    schemas_dir = repo / "schemas"
    if schemas_dir.is_dir():
        for p in schemas_dir.iterdir():
            if p.is_file():
                files.append(p)

    # Return sorted by relative path for determinism
    return sorted(files, key=lambda f: f.relative_to(repo).as_posix())


def code_fingerprint(root: Path | str | None = None) -> str:
    """
    Compute a SHA-256 fingerprint from (rel_path, mtime_ns, size) of tracked files.
    Takes ~1-2 ms for ~40 files.
    """
    repo = _resolve_repo_root(root)
    files = get_watched_files(repo)

    hasher = hashlib.sha256()
    for f in files:
        try:
            rel = f.relative_to(repo).as_posix()
            st = f.stat()
            line = f"{rel}:{st.st_mtime_ns}:{st.st_size}\n"
            hasher.update(line.encode("utf-8"))
        except OSError:
            continue

    return hasher.hexdigest()
