"""
Engine: threads_events.py (ONT-41 TA5: estado y eventos de autoevol en /dev/shm)

Dos responsabilidades, ambas sobre un directorio privado (`/dev/shm/aep_autoevol`, 0700):

1. Primitivas de archivo seguras (`open_state_dir`, `create_file_exclusive`, `write_file_atomic`,
   `read_file`): todo se abre relativo a un dir_fd con `O_NOFOLLOW`, se exige `st_uid == euid`
   y los archivos nacen 0600. Las creaciones usan `O_EXCL`; las actualizaciones, temporal `O_EXCL` + `os.replace`.
2. `events_<uid>.jsonl`: registro append-only (`O_APPEND|O_NOFOLLOW`, 0600). Cada línea lleva `ts` y un `nonce`
   (`secrets.token_hex(4)`), de modo que el hash de línea es único. Rotación a 1 MB o 5000 líneas, conservando `.1`.
   `mirror_to_ledger(conn)` espeja las líneas a `security_audit_log`, idempotente por hash de línea. Lo invoca el
   servidor cuando el tier es >= 6rw-: un EXHAUSTED registrado en tier < 6 permanece en el JSONL hasta entonces.

Directorio base configurable con `AEP_AUTOEVOL_DIR` (tests). Topos: depende solo de `engine.security` (ledger);
NO importa `server` ni otros módulos `threads_*`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from engine.security import record_audit_event, sanitize_dict

ENV_DIR = "AEP_AUTOEVOL_DIR"
DEFAULT_DIR = "/dev/shm/aep_autoevol"
DIR_MODE = 0o700
FILE_MODE = 0o600
MAX_READ_BYTES = 2 * 1024 * 1024
EVENTS_MAX_BYTES = 1024 * 1024
EVENTS_MAX_LINES = 5000
MIRROR_MAX_LINES = 1000
LEDGER_ACTION = "autoevol_event"
_O_COMMON = os.O_NOFOLLOW | os.O_CLOEXEC


class StateFileError(OSError):
    """Violación de las reglas de archivo seguro (symlink, uid ajeno, tipo inesperado, tamaño)."""


def state_dir_path() -> Path:
    """Directorio de estado: `AEP_AUTOEVOL_DIR` si está definido; si no, `/dev/shm/aep_autoevol`."""
    return Path(os.environ.get(ENV_DIR) or DEFAULT_DIR)


def open_state_dir(path: Path | str | None = None) -> int:
    """Abre (creando 0700 si falta) el directorio y devuelve su fd. Rechaza symlinks y dueños ajenos."""
    target = Path(path) if path is not None else state_dir_path()
    os.makedirs(target, mode=DIR_MODE, exist_ok=True)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | _O_COMMON)
    except OSError as exc:
        raise StateFileError(f"cannot open state dir {target}: {exc.strerror}") from exc
    st = os.fstat(fd)
    if st.st_uid != os.geteuid():
        os.close(fd)
        raise StateFileError(f"state dir {target} is not owned by euid")
    if st.st_mode & 0o077:
        os.fchmod(fd, DIR_MODE)
    return fd


@contextlib.contextmanager
def state_dir(path: Path | str | None = None) -> Iterator[int]:
    """Context manager sobre `open_state_dir` que cierra el fd siempre."""
    fd = open_state_dir(path)
    try:
        yield fd
    finally:
        os.close(fd)


def _check_regular(fd: int, name: str) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise StateFileError(f"{name}: not a regular file")
    if st.st_uid != os.geteuid():
        raise StateFileError(f"{name}: not owned by euid")
    if st.st_mode & 0o077:
        os.fchmod(fd, FILE_MODE)
    return st


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def create_file_exclusive(dir_fd: int, name: str, data: bytes) -> bool:
    """Crea `name` (0600) con `O_EXCL|O_NOFOLLOW`. False si ya existía."""
    _validate_name(name)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_COMMON, FILE_MODE, dir_fd=dir_fd)
    except FileExistsError:
        return False
    try:
        _check_regular(fd, name)
        _write_all(fd, data)
    finally:
        os.close(fd)
    return True


def write_file_atomic(dir_fd: int, name: str, data: bytes) -> None:
    """Reemplazo atómico: temporal `O_EXCL|O_NOFOLLOW` 0600 + `os.replace` dentro del mismo directorio."""
    _validate_name(name)
    tmp = f".{name}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_COMMON, FILE_MODE, dir_fd=dir_fd)
    try:
        _check_regular(fd, tmp)
        _write_all(fd, data)
    except BaseException:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp, dir_fd=dir_fd)
        raise
    os.close(fd)
    try:
        os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp, dir_fd=dir_fd)
        raise


def read_file(dir_fd: int, name: str, *, max_bytes: int = MAX_READ_BYTES) -> bytes | None:
    """Lee `name` con `O_NOFOLLOW`. None si no existe. `StateFileError` si no es regular, ajeno o demasiado grande."""
    _validate_name(name)
    try:
        fd = os.open(name, os.O_RDONLY | _O_COMMON, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateFileError(f"{name}: {exc.strerror}") from exc
    try:
        st = _check_regular(fd, name)
        if st.st_size > max_bytes:
            raise StateFileError(f"{name}: larger than {max_bytes} bytes")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def remove_file(dir_fd: int, name: str) -> bool:
    """Borra `name` si existe. True si lo borró."""
    _validate_name(name)
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        return False
    return True


def list_names(dir_fd: int) -> list[str]:
    """Nombres del directorio (ordenados)."""
    return sorted(os.listdir(dir_fd))


def _validate_name(name: str) -> None:
    if not name or "/" in name or name in (".", "..") or "\x00" in name:
        raise StateFileError(f"invalid file name: {name!r}")


# ---------------------------------------------------------------------------
# events_<uid>.jsonl
# ---------------------------------------------------------------------------


def events_file_name(uid: int | None = None) -> str:
    return f"events_{os.geteuid() if uid is None else int(uid)}.jsonl"


def _rotate_if_needed(dir_fd: int, name: str) -> bool:
    raw = read_file(dir_fd, name, max_bytes=EVENTS_MAX_BYTES * 4)
    if raw is None:
        return False
    if len(raw) < EVENTS_MAX_BYTES and raw.count(b"\n") < EVENTS_MAX_LINES:
        return False
    os.replace(name, f"{name}.1", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    return True


def append_event(
    kind: str,
    data: dict[str, Any] | None = None,
    *,
    base_dir: Path | str | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Añade una línea JSON `{ts, nonce, kind, ...data}` al JSONL del uid. Fail-soft: nunca lanza al llamante."""
    event: dict[str, Any] = {**(data or {}), "kind": str(kind), "ts": round(clock(), 3), "nonce": secrets.token_hex(4)}
    line = (json.dumps(sanitize_dict(event), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with state_dir(base_dir) as dfd:
            name = events_file_name()
            rotated = _rotate_if_needed(dfd, name)
            fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_COMMON, FILE_MODE, dir_fd=dfd)
            try:
                _check_regular(fd, name)
                _write_all(fd, line)
            finally:
                os.close(fd)
    except OSError as exc:
        return {"appended": False, "error": str(exc)[:120]}
    return {"appended": True, "rotated": rotated, "line_sha": hashlib.sha256(line.rstrip(b"\n")).hexdigest()[:16]}


def read_events(*, base_dir: Path | str | None = None, include_rotated: bool = True) -> list[dict[str, Any]]:
    """Eventos válidos del JSONL (y de `.1` primero), en orden de escritura. Líneas corruptas se omiten."""
    out: list[dict[str, Any]] = []
    for _sha, parsed in _iter_lines(base_dir, include_rotated):
        if parsed is not None:
            out.append(parsed)
    return out


def _iter_lines(
    base_dir: Path | str | None, include_rotated: bool
) -> Iterator[tuple[str, dict[str, Any] | None]]:
    try:
        with state_dir(base_dir) as dfd:
            name = events_file_name()
            names = [f"{name}.1", name] if include_rotated else [name]
            blobs = [read_file(dfd, n, max_bytes=EVENTS_MAX_BYTES * 4) for n in names]
    except OSError:
        return
    for blob in blobs:
        for raw in (blob or b"").splitlines():
            if not raw.strip():
                continue
            digest = hashlib.sha256(raw).hexdigest()
            try:
                obj = json.loads(raw)
            except ValueError:
                yield digest, None
                continue
            yield digest, obj if isinstance(obj, dict) else None


def mirror_to_ledger(
    conn: sqlite3.Connection,
    *,
    base_dir: Path | str | None = None,
    tier_octal: int | None = None,
    tier_label: str = "6rw-",
    agent_id: str = "autoevol",
) -> dict[str, Any]:
    """Espeja las líneas del JSONL a `security_audit_log`. Idempotente: el `target` es el sha256 de la línea.

    Con `tier_octal < 6` no hace nada (las líneas esperan en el JSONL). Tope de `MIRROR_MAX_LINES` por llamada.
    """
    if tier_octal is not None and tier_octal < 6:
        return {"mirrored": 0, "skipped": 0, "invalid": 0, "reason": "tier < 6rw-"}
    mirrored = skipped = invalid = 0
    for digest, parsed in _iter_lines(base_dir, True):
        if parsed is None:
            invalid += 1
            continue
        if mirrored >= MIRROR_MAX_LINES:
            break
        target = digest[:32]
        try:
            seen = conn.execute(
                "SELECT 1 FROM security_audit_log WHERE action = ? AND target = ? LIMIT 1", (LEDGER_ACTION, target)
            ).fetchone()
        except sqlite3.OperationalError:
            seen = None  # la tabla aún no existe: record_audit_event la crea
        if seen:
            skipped += 1
            continue
        record_audit_event(
            conn,
            agent_id,
            "autoevol",
            LEDGER_ACTION,
            tier_label,
            "RECORDED",
            details=parsed,
            target=target,
        )
        mirrored += 1
    return {"mirrored": mirrored, "skipped": skipped, "invalid": invalid}
