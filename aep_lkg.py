"""
aep_lkg.py (ONT-41 TB1): Last-Known-Good (LKG) store for the AEP code tree.

Top-level, stdlib-only leaf module (no `engine` import, so it can run when the engine is broken).
It is copied INSIDE every LKG snapshot (`tree/aep_lkg.py`), so a backend started from an LKG tree
imports its own copy and never depends on the (possibly broken) repo to heal itself.

Layout (under `lkg_home()`, resolved from the data home, never from `__file__` or the code root):

    lkg/<key>/tree/...        self-contained copy of the watched set
    lkg/<key>/manifest.json   {files:{rel:sha256}, code_fingerprint, generation, git_head, ts,
                               schema_hash, lkg_module_hash, manifest_sha}

`<key>` = sha256 of the sorted (rel, sha256) content listing, first 16 hex chars.
Saves are written to a temp directory and published with one atomic rename, so a crash mid-save
never leaves a partial LKG (only ignorable `.tmp-*` directories).
"""

from __future__ import annotations

import difflib
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RETENTION = 3
KEY_RE = re.compile(r"^[0-9a-f]{16}$")
DIR_MODE = 0o700
_TOP_FILES = ("server.py", "aep_backend.py", "scripts/aep-ctl", "pyproject.toml", "aep_lkg.py")
_TMP_PREFIX = ".tmp-"


class LkgError(Exception):
    """Raised for unsafe or inconsistent LKG operations; `code` is machine-readable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _own_source_hash() -> str:
    return _sha_bytes(Path(__file__).read_bytes())


LKG_MODULE_HASH = _own_source_hash()


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def lkg_home() -> Path:
    """`$AEP_DATA_HOME` or `~/.local/share/agent-os`, plus `/lkg`; created with mode 0700."""
    env = os.environ.get("AEP_DATA_HOME", "").strip()
    base = Path(env) if env else Path.home() / ".local" / "share" / "agent-os"
    home = base / "lkg"
    home.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    os.chmod(home, DIR_MODE)
    return home


def key_dir(key: str) -> Path:
    if not KEY_RE.match(key):
        raise LkgError("BAD_KEY", key)
    return lkg_home() / key


def tree_path(key: str) -> Path:
    return key_dir(key) / "tree"


# ---------------------------------------------------------------------------
# Watched set
# ---------------------------------------------------------------------------


def in_set(rel: str) -> bool:
    """Allowlist predicate for a normalized posix relative path."""
    if rel in _TOP_FILES:
        return True
    if rel.startswith("engine/"):
        return rel.endswith(".py") and "__pycache__" not in rel.split("/")
    if rel.startswith("templates/"):
        return "__pycache__" not in rel.split("/")
    if rel.startswith("schemas/"):
        return rel.count("/") == 1
    return False


def safe_rel(rel: str) -> str:
    """Return `rel` if it is a normalized, relative, traversal-free member of the set; else raise."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel:
        raise LkgError("BAD_PATH", repr(rel))
    p = Path(rel)
    if p.is_absolute() or rel.startswith("/") or ".." in p.parts or p.as_posix() != rel or "." in p.parts:
        raise LkgError("BAD_PATH", rel)
    if not in_set(rel):
        raise LkgError("NOT_IN_SET", rel)
    return rel


def _lkg_source(code_root: Path) -> Path:
    own = code_root / "aep_lkg.py"
    return own if own.is_file() else Path(__file__)


def collect_set(code_root: Path | str) -> dict[str, Path]:
    """Map rel -> source file for the watched set under `code_root` (symlinks are refused)."""
    root = Path(code_root).resolve()
    found: dict[str, Path] = {}
    candidates: list[Path] = [root / n for n in _TOP_FILES if n != "aep_lkg.py"]
    for sub in ("engine", "templates", "schemas"):
        d = root / sub
        if d.is_dir():
            candidates.extend(sorted(p for p in d.rglob("*") if not p.is_dir()))
    for p in candidates:
        if not (p.is_file() or p.is_symlink()):
            continue
        rel = p.relative_to(root).as_posix()
        if not in_set(rel):
            continue
        if p.is_symlink():
            raise LkgError("SYMLINK_IN_SOURCE", rel)
        found[rel] = p
    found["aep_lkg.py"] = _lkg_source(root)
    return dict(sorted(found.items()))


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_digest(manifest: dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha"}
    return _sha_bytes(_canonical(body))


def content_key(files: dict[str, str]) -> str:
    listing = "".join(f"{rel}:{files[rel]}\n" for rel in sorted(files))
    return _sha_bytes(listing.encode("utf-8"))[:16]


def read_manifest(key: str) -> dict[str, Any]:
    path = key_dir(key) / "manifest.json"
    try:
        data = json.loads(_read_nofollow(path).decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise LkgError("MANIFEST_UNREADABLE", f"{key}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise LkgError("MANIFEST_MALFORMED", key)
    return data


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _write_file(dest: Path, data: bytes, executable: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(dest, 0o755 if executable else 0o644)


def _sweep_tmp(home: Path) -> None:
    for p in home.glob(f"{_TMP_PREFIX}*"):
        shutil.rmtree(p, ignore_errors=True)


def save(
    code_root: Path | str,
    generation: str | int,
    code_fingerprint: str,
    schema_hash: str,
    git_head: str,
) -> dict[str, Any]:
    """Snapshot the watched set; idempotent per content. Returns the manifest plus `key` and `created`."""
    sources = collect_set(code_root)
    blobs = {rel: p.read_bytes() for rel, p in sources.items()}
    files = {rel: _sha_bytes(b) for rel, b in blobs.items()}
    key = content_key(files)
    home = lkg_home()
    _sweep_tmp(home)
    final = home / key
    if final.exists():
        if verify(key)["ok"]:
            return {**read_manifest(key), "key": key, "created": False}
        shutil.rmtree(final)
    tmp = Path(tempfile.mkdtemp(prefix=f"{_TMP_PREFIX}{key}-", dir=home))
    try:
        os.chmod(tmp, DIR_MODE)
        for rel, data in blobs.items():
            executable = bool(os.stat(sources[rel]).st_mode & stat.S_IXUSR)
            _write_file(tmp / "tree" / rel, data, executable)
        manifest: dict[str, Any] = {
            "files": files,
            "code_fingerprint": code_fingerprint,
            "generation": generation,
            "git_head": git_head,
            "ts": datetime.now(UTC).isoformat(timespec="microseconds"),
            "schema_hash": schema_hash,
            "lkg_module_hash": LKG_MODULE_HASH,
        }
        manifest["manifest_sha"] = manifest_digest(manifest)
        _write_file(tmp / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"), False)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _prune(keep=key)
    return {**manifest, "key": key, "created": True}


def _prune(keep: str) -> None:
    entries = list_keys()
    for entry in entries[RETENTION:]:
        if entry["key"] != keep:
            shutil.rmtree(lkg_home() / entry["key"], ignore_errors=True)


# ---------------------------------------------------------------------------
# Query / verify
# ---------------------------------------------------------------------------


def list_keys() -> list[dict[str, Any]]:
    """Published LKGs (valid directory name + parseable manifest), newest first. No hash verification."""
    out: list[dict[str, Any]] = []
    home = lkg_home()
    for p in home.iterdir():
        if not KEY_RE.match(p.name) or not p.is_dir():
            continue
        try:
            m = read_manifest(p.name)
        except LkgError:
            continue
        out.append(
            {
                "key": p.name,
                "ts": str(m.get("ts", "")),
                "generation": m.get("generation"),
                "git_head": m.get("git_head"),
                "code_fingerprint": m.get("code_fingerprint"),
                "files": len(m["files"]),
            }
        )
    return sorted(out, key=lambda e: (e["ts"], e["key"]), reverse=True)


def latest() -> str | None:
    """Newest key that passes full verification, else None."""
    for entry in list_keys():
        if verify(entry["key"])["ok"]:
            return str(entry["key"])
    return None


def verify(key: str) -> dict[str, Any]:
    """Check manifest_sha, content key, per-file sha, symlinks and stray files. Never raises."""
    errors: list[str] = []
    try:
        manifest = read_manifest(key)
        tree = tree_path(key)
    except LkgError as exc:
        return {"ok": False, "errors": [str(exc)]}
    if manifest.get("manifest_sha") != manifest_digest(manifest):
        errors.append("MANIFEST_SHA_MISMATCH")
    files: dict[str, Any] = manifest["files"]
    declared: dict[str, str] = {}
    for rel, sha in files.items():
        try:
            safe_rel(rel)
        except LkgError as exc:
            errors.append(f"MANIFEST_PATH: {exc}")
            continue
        if not isinstance(sha, str):
            errors.append(f"MANIFEST_SHA_TYPE: {rel}")
            continue
        declared[rel] = sha
    if declared and content_key(declared) != key and not errors:
        errors.append("KEY_MISMATCH")
    present: set[str] = set()
    if tree.is_symlink() or not tree.is_dir():
        errors.append("TREE_MISSING")
    else:
        for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
            for name in [*dirnames, *filenames]:
                p = Path(dirpath) / name
                if p.is_symlink():
                    errors.append(f"SYMLINK_IN_TREE: {p.relative_to(tree).as_posix()}")
                elif p.is_file():
                    present.add(p.relative_to(tree).as_posix())
    for rel, sha in declared.items():
        if rel not in present:
            errors.append(f"MISSING: {rel}")
            continue
        try:
            data = _read_nofollow(tree / rel)
        except OSError as exc:
            errors.append(f"UNREADABLE: {rel}: {exc}")
            continue
        if _sha_bytes(data) != sha:
            errors.append(f"SHA_MISMATCH: {rel}")
    for rel in sorted(present - set(files)):
        errors.append(f"EXTRA_FILE: {rel}")
    return {"ok": not errors, "errors": errors}


def _read_nofollow(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Restore / diff
# ---------------------------------------------------------------------------


def _target_for(repo: Path, rel: str) -> Path:
    target = repo / rel
    if target.is_symlink():
        raise LkgError("SYMLINK_TARGET", rel)
    resolved = (repo / rel).resolve()
    if not resolved.is_relative_to(repo):
        raise LkgError("ESCAPES_REPO", rel)
    return target


def _load_member(key: str, manifest: dict[str, Any], rel: str) -> bytes:
    if rel not in manifest["files"]:
        raise LkgError("NOT_IN_MANIFEST", rel)
    src = tree_path(key) / rel
    if src.is_symlink():
        raise LkgError("SYMLINK_IN_TREE", rel)
    try:
        data = _read_nofollow(src)
    except OSError as exc:
        code = "SYMLINK_IN_TREE" if exc.errno == errno.ELOOP else "UNREADABLE"
        raise LkgError(code, f"{rel}: {exc}") from exc
    if _sha_bytes(data) != manifest["files"][rel]:
        raise LkgError("SHA_MISMATCH", rel)
    return data


def restore_files(key: str, rel_paths: list[str], repo_root: Path | str, dry_run: bool = True) -> dict[str, Any]:
    """Restore only `rel_paths` from the LKG into `repo_root`.

    Everything is validated first and rehearsed in a temp directory; the real tree is touched only if
    `dry_run=False` and the rehearsal matched byte for byte. Raises LkgError before any write.
    """
    repo = Path(repo_root).resolve()
    manifest = read_manifest(key)
    if manifest.get("manifest_sha") != manifest_digest(manifest):
        raise LkgError("MANIFEST_SHA_MISMATCH", key)
    plan: list[tuple[str, Path, bytes]] = []
    for rel in sorted(set(rel_paths)):
        safe_rel(rel)
        plan.append((rel, _target_for(repo, rel), _load_member(key, manifest, rel)))
    # Rehearsal: always, into a throwaway directory, compared against the manifest hashes.
    with tempfile.TemporaryDirectory(prefix="aep-lkg-dry-") as stage:
        for rel, _target, data in plan:
            staged = Path(stage) / rel
            _write_file(staged, data, False)
            if _sha_bytes(staged.read_bytes()) != manifest["files"][rel]:
                raise LkgError("DRY_RUN_MISMATCH", rel)
    changes = []
    for rel, target, data in plan:
        changed = not target.is_file() or _sha_bytes(target.read_bytes()) != _sha_bytes(data)
        changes.append({"file": rel, "would_change": changed})
    result: dict[str, Any] = {"key": key, "dry_run": dry_run, "files": changes, "restored": []}
    if dry_run:
        return result
    for rel, target, data in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.resolve().is_relative_to(repo):
            raise LkgError("ESCAPES_REPO", rel)
        tmp = target.parent / f".{target.name}.lkg-{secrets.token_hex(4)}"
        executable = bool(manifest_exec(key, rel))
        try:
            _write_file(tmp, data, executable)
            if _sha_bytes(tmp.read_bytes()) != manifest["files"][rel]:
                raise LkgError("SHA_MISMATCH", rel)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        result["restored"].append(rel)
    return result


def manifest_exec(key: str, rel: str) -> bool:
    """True if the snapshot copy of `rel` carries the owner-exec bit (e.g. scripts/aep-ctl)."""
    try:
        return bool(os.lstat(tree_path(key) / rel).st_mode & stat.S_IXUSR)
    except OSError:
        return False


def diff(key: str, rel_path: str, repo_root: Path | str) -> dict[str, Any]:
    """Unified diff hunks, current repo file (a) -> LKG file (b)."""
    repo = Path(repo_root).resolve()
    manifest = read_manifest(key)
    safe_rel(rel_path)
    new = _load_member(key, manifest, rel_path).decode("utf-8", errors="replace").splitlines(keepends=True)
    target = repo / rel_path
    old: list[str] = []
    if target.is_file() and not target.is_symlink():
        old = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    hunks: list[dict[str, Any]] = []
    for line in difflib.unified_diff(old, new, fromfile=f"repo/{rel_path}", tofile=f"lkg/{rel_path}", n=2):
        text = line.rstrip("\n")
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", text)
        if m:
            hunks.append(
                {
                    "old_start": int(m.group(1)),
                    "old_lines": int(m.group(2) or 1),
                    "new_start": int(m.group(3)),
                    "new_lines": int(m.group(4) or 1),
                    "lines": [],
                }
            )
        elif hunks:
            hunks[-1]["lines"].append(text)
    return {"file": rel_path, "identical": not hunks, "hunks": hunks}


# ---------------------------------------------------------------------------
# Traceback parsing
# ---------------------------------------------------------------------------

_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
_EXC_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)):\s*(.*)$", re.MULTILINE)


def parse_error(tail: str) -> dict[str, Any] | None:
    """Extract {type,file,line,msg,fingerprint} from a Python traceback / SyntaxError tail."""
    if not isinstance(tail, str) or not tail:
        return None
    frames = _FRAME_RE.findall(tail)
    excs = _EXC_RE.findall(tail)
    if not excs and not frames:
        return None
    etype, msg = excs[-1] if excs else ("", "")
    file, line = (frames[-1][0], int(frames[-1][1])) if frames else ("", 0)
    etype = etype.rsplit(".", 1)[-1]
    basis = "|".join((etype, os.path.basename(file), msg.strip()))
    return {
        "type": etype,
        "file": file,
        "line": line,
        "msg": msg.strip(),
        "fingerprint": _sha_bytes(basis.encode("utf-8"))[:16],
    }


# `list` is part of the specified API surface; bound last so it never shadows the builtin above.
list = list_keys
