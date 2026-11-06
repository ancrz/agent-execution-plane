"""
aep_front.py (ONT-39: Live Plane Low-Level MCP Front Server)

High-resilience, minimal MCP stdio frontend.
Decouples client connection from server implementation.
Proxies MCP JSON-RPC requests to an isolated aep_backend worker over AF_UNIX socketpair.

Capabilities:
- Low-level Server (no client-side argument schema caching/validation)
- Advertises tools.listChanged = True
- Hot-swap on code fingerprint change with 1s debounce
- Fail-safe swap protocol (Gen N retained on error, in-flight calls drained)
- Tier governance (7rwx/6rw-/5r-x auto-swap, 4r-- watch-only)
- Zero FD leak guarantee
- ONT-41: LKG (last-known-good) store integration: N0 structured reload error, N1 save after healthy
  promotions, N2 crash-window fallback to an LKG tree, reload barrier for autoevol(verify|fix_test),
  private plane-events spool and per-pid state file. The front never imports engine/threads* nor the
  heavy engine: the barrier contract is a plain JSON dict passed to the backend as `_barrier`.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Fast path: legacy mode override
if os.environ.get("AEP_HOTSWAP") == "0":
    project_root = Path(__file__).resolve().parent
    server_py = project_root / "server.py"
    os.execv(sys.executable, [sys.executable, str(server_py), *sys.argv[1:]])  # noqa: S606

try:  # ONT-41: a broken/missing aep_lkg must never stop the front (degrades to LKG_UNAVAILABLE)
    import aep_lkg  # noqa: E402
except Exception:  # noqa: BLE001
    aep_lkg = None  # type: ignore[assignment]

import mcp.server.stdio  # noqa: E402
import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.lowlevel.server import NotificationOptions  # noqa: E402
from mcp.server.session import ServerSession  # noqa: E402

logger = logging.getLogger("aep.front")
PROJECT_ROOT = Path(__file__).resolve().parent
FRONT_START_TIME_NS: int = time.time_ns()
BACKEND_LOG_DIR = Path.home() / ".local" / "share" / "agent-os" / "logs"
FRONT_PID: int = os.getpid()

SWAP_FENCE_NAME = ".aep_swap_fence"
SWAP_FENCE_PATH_ENV = "AEP_SWAP_FENCE_PATH"
SWAP_FENCE_ORPHAN_AFTER_S = 600.0
DEFAULT_QUIESCE_MS = 300
DEAD_FRONT_LOG_MAX_AGE_S = 86400.0
LOG_RETENTION_PER_FRONT = 5


def _fallback_code_fingerprint(root: Path | str | None = None) -> str:
    """Self-contained copy of engine.fingerprint.code_fingerprint (D-21).

    The front must start even when engine/fingerprint.py (a watched file) is broken.
    Must stay byte-for-byte equivalent in output; tests assert hash parity.
    """
    repo = Path(root).resolve() if root is not None else Path(__file__).resolve().parent
    files: list[Path] = []
    for name in ("server.py", "aep_backend.py"):
        p = repo / name
        if p.is_file():
            files.append(p)
    engine_dir = repo / "engine"
    if engine_dir.is_dir():
        for p in engine_dir.rglob("*.py"):
            if "__pycache__" not in p.parts and p.is_file():
                files.append(p)
    tpl = repo / "templates" / "registry.json"
    if tpl.is_file():
        files.append(tpl)
    schemas_dir = repo / "schemas"
    if schemas_dir.is_dir():
        for p in schemas_dir.iterdir():
            if p.is_file():
                files.append(p)
    files.sort(key=lambda f: f.relative_to(repo).as_posix())

    hasher = hashlib.sha256()
    for f in files:
        try:
            rel = f.relative_to(repo).as_posix()
            st = f.stat()
            hasher.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}\n".encode())
        except OSError:
            continue
    return hasher.hexdigest()


try:
    from engine.fingerprint import code_fingerprint  # noqa: E402
except Exception:  # noqa: BLE001
    code_fingerprint = _fallback_code_fingerprint


def _quiesce_seconds() -> float:
    raw = os.environ.get("AEP_HOTSWAP_QUIESCE_MS", str(DEFAULT_QUIESCE_MS))
    try:
        return max(0, int(raw)) / 1000.0
    except ValueError:
        return DEFAULT_QUIESCE_MS / 1000.0


def _debounce_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("AEP_HOTSWAP_DEBOUNCE_S", "1.0")))
    except ValueError:
        return 1.0


def _health_timeout_seconds() -> float:
    try:
        return max(0.1, float(os.environ.get("AEP_HOTSWAP_HEALTH_TIMEOUT_S", "20")))
    except ValueError:
        return 20.0


TRANSIENT_MAX_ATTEMPTS = 3  # backoff 1 s, 2 s, 4 s between attempts


def transient_backoff_seconds(failure_number: int) -> float:
    """Delay before the retry that follows the Nth consecutive transient failure (1 s, 2 s, 4 s)."""
    return float(2 ** (max(1, failure_number) - 1))


def swap_fence_path() -> Path:
    """Fence location: AEP_SWAP_FENCE_PATH if set (D-22, test isolation), else PROJECT_ROOT/.aep_swap_fence.

    Resolved at every call so every fence check (initial, under swap_lock, pre-promotion) agrees.
    """
    override = os.environ.get(SWAP_FENCE_PATH_ENV, "").strip()
    return Path(override) if override else PROJECT_ROOT / SWAP_FENCE_NAME


def swap_fence_state() -> tuple[bool, bool]:
    """Return (fenced, orphan). A fence older than SWAP_FENCE_ORPHAN_AFTER_S is ignored (orphan)."""
    try:
        st = swap_fence_path().stat()
    except OSError:
        return False, False
    if time.time() - st.st_mtime > SWAP_FENCE_ORPHAN_AFTER_S:
        return False, True
    return True, False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


_LOG_RE = re.compile(r"^aep_backend_(?:(\d+)_)?gen(\d+)\.log$")


def _backend_log_path(front_pid: int, generation: int) -> Path:
    return BACKEND_LOG_DIR / f"aep_backend_{front_pid}_gen{generation}.log"


def _prune_backend_logs(
    log_dir: Path,
    front_pid: int | None = None,
    max_generations: int = LOG_RETENTION_PER_FRONT,
) -> None:
    """Per-front retention of the last max_generations logs (by mtime), and removal of
    logs from dead fronts older than one day (legacy pid-less names count as dead)."""
    try:
        own = front_pid if front_pid is not None else FRONT_PID
        by_pid: dict[int | None, list[tuple[int, Path]]] = {}
        for p in log_dir.glob("aep_backend_*gen*.log"):
            m = _LOG_RE.match(p.name)
            if not m:
                continue
            pid = int(m.group(1)) if m.group(1) else None
            try:
                by_pid.setdefault(pid, []).append((p.stat().st_mtime_ns, p))
            except OSError:
                continue
        now_ns = time.time_ns()
        max_age_ns = int(DEAD_FRONT_LOG_MAX_AGE_S * 1e9)
        for pid, files in by_pid.items():
            files.sort(key=lambda x: x[0])
            if pid == own:
                while len(files) > max_generations:
                    _, old_p = files.pop(0)
                    with contextlib.suppress(Exception):
                        old_p.unlink()
            elif pid is None or not _pid_alive(pid):
                for mtime_ns, old_p in files:
                    if now_ns - mtime_ns > max_age_ns:
                        with contextlib.suppress(Exception):
                            old_p.unlink()
            else:
                # Live concurrent front: apply the same per-front retention to its logs.
                while len(files) > max_generations:
                    _, old_p = files.pop(0)
                    with contextlib.suppress(Exception):
                        old_p.unlink()
    except Exception as e:  # noqa: BLE001
        logger.debug("Failed pruning backend logs: %s", e)


def _read_backend_log_tail(generation: int, max_bytes: int = 4096) -> str:
    """Read tail of backend log file for last_reload_error on failure (F2)."""
    log_file = _backend_log_path(FRONT_PID, generation)
    try:
        if not log_file.exists():
            return ""
        size = log_file.stat().st_size
        with open(log_file, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def get_hotswap_mode() -> str:
    """Determine hotswap governance mode."""
    mode = os.environ.get("AEP_HOTSWAP_MODE")
    if mode in ("watch", "auto", "legacy"):
        return mode
    if os.environ.get("AEP_HOTSWAP") == "0":
        return "legacy"
    # Tier 4r--: Read-only filesystem
    if not os.access(PROJECT_ROOT, os.W_OK):
        return "watch"
    return "auto"


# ---------------------------------------------------------------------------
# ONT-41 TC1: private spool (plane_events JSONL) and per-pid state file
# ---------------------------------------------------------------------------

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_O_COMMON = os.O_NOFOLLOW | os.O_CLOEXEC
STATE_MAX_BYTES = 64 * 1024
SPOOL_MAX_BYTES = 1024 * 1024
SPOOL_MAX_LINES = 5000
SPOOL_MAX_LINE_BYTES = 4096
SPOOL_FIELD_MAX_CHARS = 512
DEFAULT_SPOOL_DIR = "/dev/shm/aep_autoevol"
DEFAULT_STATE_DIR = "/dev/shm"
CRASH_WINDOW_S = 60.0
CRASH_WINDOW_MAX = 3
DEFAULT_RELOAD_BARRIER_S = 15.0
BARRIER_POLL_S = 0.25
BARRIER_TOOL = "autoevol"
BARRIER_ACTIONS = frozenset({"verify", "fix_test"})
# Barrier contract (plain JSON dict, consumed by the backend as `_barrier`)
RELOAD_OK = "RELOAD_OK"
RELOAD_PENDING = "RELOAD_PENDING"
RELOAD_FAILED = "RELOAD_FAILED"
SERVING_LKG = "SERVING_LKG"
LKG_UNAVAILABLE = "LKG_UNAVAILABLE"


class FrontFileError(OSError):
    """Unsafe state/spool file (symlink, foreign owner, wrong type, oversize)."""


def spool_dir_path() -> Path:
    return Path(os.environ.get("AEP_FRONT_SPOOL_DIR") or os.environ.get("AEP_AUTOEVOL_DIR") or DEFAULT_SPOOL_DIR)


def state_dir_path() -> tuple[Path, bool]:
    """(directory, private). A custom dir is private (0700, owned by euid); the /dev/shm default is shared."""
    custom = os.environ.get("AEP_FRONT_STATE_DIR", "").strip()
    return (Path(custom), True) if custom else (Path(DEFAULT_STATE_DIR), False)


def state_file_name(pid: int | None = None) -> str:
    return f"aep_front_{pid if pid is not None else FRONT_PID}.json"


def _open_dir(path: Path, private: bool) -> int:
    if private:
        os.makedirs(path, mode=PRIVATE_DIR_MODE, exist_ok=True)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | _O_COMMON)
    except OSError as exc:
        raise FrontFileError(f"cannot open dir {path}: {exc.strerror}") from exc
    if private:
        st = os.fstat(fd)
        if st.st_uid != os.geteuid():
            os.close(fd)
            raise FrontFileError(f"dir {path} not owned by euid")
        if st.st_mode & 0o077:
            os.fchmod(fd, PRIVATE_DIR_MODE)
    return fd


def _check_regular(fd: int, name: str) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise FrontFileError(f"{name}: not a regular file")
    if st.st_uid != os.geteuid():
        raise FrontFileError(f"{name}: not owned by euid")
    if st.st_mode & 0o077:
        os.fchmod(fd, PRIVATE_FILE_MODE)
    return st


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def write_state_file(directory: Path, private: bool, name: str, data: dict[str, Any]) -> None:
    """Atomic replace: `O_EXCL|O_NOFOLLOW` 0600 temp inside the dir, then `os.replace` (dir_fd relative)."""
    payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    if len(payload) > STATE_MAX_BYTES:
        raise FrontFileError(f"{name}: state exceeds {STATE_MAX_BYTES} bytes")
    dir_fd = _open_dir(directory, private)
    tmp = f".{name}.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_COMMON, PRIVATE_FILE_MODE, dir_fd=dir_fd)
        try:
            _write_all(fd, payload)
        finally:
            os.close(fd)
        try:
            os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=dir_fd)
            raise
    finally:
        os.close(dir_fd)


def read_state_file(directory: Path, private: bool, name: str) -> dict[str, Any] | None:
    """Read with `O_NOFOLLOW`, `st_uid == euid`, regular file and size limit. None if missing."""
    dir_fd = _open_dir(directory, private=False)
    try:
        try:
            fd = os.open(name, os.O_RDONLY | _O_COMMON, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise FrontFileError(f"{name}: {exc.strerror}") from exc
        try:
            st = _check_regular(fd, name)
            if st.st_size > STATE_MAX_BYTES:
                raise FrontFileError(f"{name}: too large")
            raw = os.read(fd, STATE_MAX_BYTES + 1)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return data if isinstance(data, dict) else None


def remove_state_file(directory: Path, private: bool, name: str) -> None:
    dir_fd = _open_dir(directory, private)
    try:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


class PlaneEventSpool:
    """Append-only `plane_events_<uid>.jsonl` (O_APPEND|O_NOFOLLOW, 0600, private 0700 dir).

    Every line carries `ts`, `nonce` and `pid` so line hashes are unique; rotation at 1 MB / 5000 lines
    keeps one `.1` file; oversized lines are trimmed. Writers are best-effort (callers swallow errors).
    """

    def __init__(self, directory: Path | None = None, uid: int | None = None) -> None:
        self.directory = directory if directory is not None else spool_dir_path()
        self.name = f"plane_events_{uid if uid is not None else os.geteuid()}.jsonl"
        self._lines: int | None = None

    @staticmethod
    def _trim(fields: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in fields.items():
            out[str(k)[:64]] = v[:SPOOL_FIELD_MAX_CHARS] if isinstance(v, str) else v
        return out

    def append(self, kind: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="microseconds"), "nonce": secrets.token_hex(4),
                  "pid": FRONT_PID, "kind": kind, **self._trim(fields)}
        line = (json.dumps(record, sort_keys=True, default=str) + "\n").encode("utf-8")
        if len(line) > SPOOL_MAX_LINE_BYTES:
            line = (json.dumps({k: record[k] for k in ("ts", "nonce", "pid", "kind")}) + "\n").encode("utf-8")
        dir_fd = _open_dir(self.directory, private=True)
        try:
            fd = self._open_log(dir_fd)
            try:
                size = os.fstat(fd).st_size
                if self._lines is None:
                    self._lines = os.pread(fd, SPOOL_MAX_BYTES, 0).count(b"\n") if size else 0
                if size + len(line) > SPOOL_MAX_BYTES or self._lines >= SPOOL_MAX_LINES:
                    os.close(fd)
                    os.replace(self.name, self.name + ".1", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                    self._lines = 0
                    fd = self._open_log(dir_fd)
                _write_all(fd, line)
                self._lines += 1
            finally:
                os.close(fd)
        finally:
            os.close(dir_fd)

    def _open_log(self, dir_fd: int) -> int:
        flags = os.O_WRONLY | os.O_APPEND | _O_COMMON
        try:
            fd = os.open(self.name, flags | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE, dir_fd=dir_fd)
        except FileExistsError:
            try:
                fd = os.open(self.name, flags, dir_fd=dir_fd)
            except OSError as exc:
                raise FrontFileError(f"{self.name}: {exc.strerror}") from exc
        try:
            _check_regular(fd, self.name)
        except BaseException:
            os.close(fd)
            raise
        return fd


class BackendConnection:
    """Encapsulates a running backend worker and its socketpair connection."""

    def __init__(self, proc: subprocess.Popen, sock: socket.socket, generation: int) -> None:
        self.proc = proc
        self.sock = sock
        self.generation = generation
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.write_lock = asyncio.Lock()
        self.pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.in_flight_calls = 0
        self._read_task: asyncio.Task[None] | None = None
        self.alive = True

    async def initialize(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(sock=self.sock)
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            assert self.reader is not None  # noqa: S101
            while self.alive:
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode("utf-8", errors="replace"))
                    req_id = str(data.get("id"))
                    fut = self.pending_requests.pop(req_id, None)
                    if fut and not fut.done():
                        fut.set_result(data)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Error parsing backend response: %s", e)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self.alive = False
            # Cancel any remaining pending futures
            for fut in list(self.pending_requests.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("Backend connection closed unexpectedly"))
            self.pending_requests.clear()

    async def send_request(self, req: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        if not self.alive or not self.writer:
            raise RuntimeError("Backend connection is closed")

        req_id = str(req.get("id") or uuid.uuid4())
        req["id"] = req_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending_requests[req_id] = fut

        payload = (json.dumps(req) + "\n").encode("utf-8")
        async with self.write_lock:
            try:
                self.writer.write(payload)
                await self.writer.drain()
            except Exception as e:
                self.pending_requests.pop(req_id, None)
                self.alive = False
                raise RuntimeError(f"Failed to send request to backend: {e}") from e

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            self.pending_requests.pop(req_id, None)
            raise

    async def terminate(self) -> None:
        self.alive = False
        if self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None

        if self.writer:
            with contextlib.suppress(Exception):
                self.writer.close()
                await self.writer.wait_closed()
            self.writer = None

        with contextlib.suppress(Exception):
            self.sock.close()

        if self.proc.stderr:
            with contextlib.suppress(Exception):
                self.proc.stderr.close()

        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.to_thread(self.proc.wait, timeout=2.0)
            except Exception:  # noqa: BLE001
                self.proc.kill()
                await asyncio.to_thread(self.proc.wait)


class _StartFailure(Exception):
    """A backend (disk or LKG) failed to start/become healthy. `kind`: deterministic | transient."""

    def __init__(self, kind: str, detail: str, tail: str = "") -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.tail = tail


def _git_head_short(cwd: Path) -> str:
    """Fail-soft short HEAD for the LKG manifest (blocking: call through asyncio.to_thread)."""
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:  # noqa: BLE001, S110
        pass
    return "unknown"


def _barrier_timeout_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("AEP_RELOAD_BARRIER_S", str(DEFAULT_RELOAD_BARRIER_S))))
    except ValueError:
        return DEFAULT_RELOAD_BARRIER_S


class LivePlaneManager:
    """Orchestrates hot-swapping, fail-safe promotion, LKG fallback and drainage of backends.

    `clock` (monotonic seconds) and `sleep` are injectable so the N2 crash window and the reload barrier
    are testable with a fake clock.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        self.active_conn: BackendConnection | None = None
        self.active_schema: list[dict[str, Any]] = []
        self.active_schema_hash: str = ""
        self.active_fingerprint: str = ""
        self.active_instructions: str = ""
        self.generation: int = 1
        self.last_swap_at: str | None = None
        self.last_reload_error: str | None = None
        self.last_reload_error_struct: dict[str, Any] | None = None
        self.last_check_time: float = 0.0
        self.failed_fingerprint: str = ""
        self.failure_kind: str | None = None
        self.transient_failures: int = 0
        self.transient_fp: str = ""
        self.next_retry_at: float = 0.0
        self.swap_attempts: int = 0
        self.swap_fenced: bool = False
        self.swap_fence_orphan: bool = False
        self.swap_lock = asyncio.Lock()
        self.cached_session: ServerSession | None = None
        # ONT-41 (LKG)
        self.serving_lkg: bool = False
        self.lkg_key: str | None = None
        self.lkg_fingerprint: str | None = None
        self.lkg_module_drift: bool = False
        self.drops: list[float] = []
        self.spool = PlaneEventSpool()

    # -- telemetry (best-effort: never affects serving) -------------------------------------------

    def _event(self, kind: str, **fields: Any) -> None:
        try:
            self.spool.append(kind, generation=self.generation, **fields)
        except Exception as e:  # noqa: BLE001
            logger.debug("plane_events spool failed: %s", e)

    def _write_state(self) -> None:
        directory, private = state_dir_path()
        try:
            write_state_file(
                directory,
                private,
                state_file_name(),
                {
                    "pid": FRONT_PID,
                    "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                    "generation": self.generation,
                    "active_fingerprint": self.active_fingerprint,
                    "schema_hash": self.active_schema_hash,
                    "serving_from": "lkg" if self.serving_lkg else "disk",
                    "lkg_key": self.lkg_key,
                    "lkg_fingerprint": self.lkg_fingerprint,
                    "failure_kind": self._effective_failure_kind(),
                    "last_reload_error": self.last_reload_error,
                    "lkg_module_drift": self.lkg_module_drift,
                    "backend_pid": self.active_conn.proc.pid if self.active_conn else None,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("front state file failed: %s", e)

    def _remove_state(self) -> None:
        directory, private = state_dir_path()
        with contextlib.suppress(Exception):
            remove_state_file(directory, private, state_file_name())

    def is_front_stale(self) -> bool:
        try:
            st = (PROJECT_ROOT / "aep_front.py").stat()
            return st.st_mtime_ns > FRONT_START_TIME_NS
        except OSError:
            return False

    async def _spawn_backend(self, generation: int, lkg_tree: Path | None = None) -> BackendConnection:
        code_dir = lkg_tree if lkg_tree is not None else PROJECT_ROOT
        backend_script = code_dir / "aep_backend.py"
        s_front, s_backend = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        log_fd: Any = None
        proc: subprocess.Popen | None = None
        try:
            s_backend.set_inheritable(True)

            mode = get_hotswap_mode()
            env = dict(os.environ)
            env["AEP_BACKEND_GENERATION"] = str(generation)
            env["AEP_HOTSWAP_MODE"] = mode
            env["AEP_FRONT_START_TIME_NS"] = str(FRONT_START_TIME_NS)
            if self.last_swap_at:
                env["AEP_LAST_SWAP_AT"] = self.last_swap_at
            # D-18: a candidate never inherits a reload error. Drop any ambient value; the error is
            # delivered via set_meta only to the ACTIVE backend that keeps serving.
            env.pop("AEP_LAST_RELOAD_ERROR", None)
            if lkg_tree is not None:
                # N2: code from the snapshot, data (disk fingerprint, workspace) from the real repo.
                env["PYTHONPATH"] = str(lkg_tree)
                env["AEP_REPO_ROOT"] = str(PROJECT_ROOT)
                env["AEP_SERVING_FROM"] = "lkg"
                # The snapshot is hash-verified: byte-compiling into it would add stray files and fail verify().
                env["PYTHONDONTWRITEBYTECODE"] = "1"
            else:
                env.pop("AEP_SERVING_FROM", None)

            # F2/D-5: stderr -> aep_backend_<front_pid>_gen<N>.log (per-front names; retain last 5 per front)
            BACKEND_LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = _backend_log_path(FRONT_PID, generation)
            log_fd = open(log_path, "w", encoding="utf-8")
            _prune_backend_logs(BACKEND_LOG_DIR, front_pid=FRONT_PID, max_generations=LOG_RETENTION_PER_FRONT)

            # F1: Pass stdin/stdout DEVNULL to protect client MCP JSON-RPC protocol channel
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(backend_script),
                    "--fd",
                    str(s_backend.fileno()),
                    "--generation",
                    str(generation),
                    "--hotswap-mode",
                    mode,
                ],
                pass_fds=(s_backend.fileno(),),
                cwd=str(code_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_fd,
            )
            conn = BackendConnection(proc, s_front, generation)
            await conn.initialize()
            return conn
        except BaseException:
            # No leaks on a failed spawn: stop the child and release every descriptor we own.
            if proc is not None and proc.poll() is None:
                with contextlib.suppress(Exception):
                    proc.kill()
                    proc.wait(timeout=2.0)
            with contextlib.suppress(Exception):
                s_front.close()
            raise
        finally:
            if log_fd is not None:
                with contextlib.suppress(Exception):
                    log_fd.close()
            with contextlib.suppress(Exception):
                s_backend.close()

    # -- N1: LKG save ------------------------------------------------------------------------------

    async def _save_lkg(self, generation: int, fingerprint: str, schema_hash: str) -> None:
        """Snapshot the healthy disk tree. Only called after health+list OK; never while serving from LKG."""
        if aep_lkg is None or self.serving_lkg:
            return

        def _do() -> dict[str, Any]:
            return aep_lkg.save(PROJECT_ROOT, generation, fingerprint, schema_hash, _git_head_short(PROJECT_ROOT))

        try:
            manifest = await asyncio.to_thread(_do)
        except Exception as e:  # noqa: BLE001
            logger.warning("LKG save failed: %s", e)
            self._event("LKG_SAVE_FAILED", error=str(e))
            return
        self.lkg_key = str(manifest.get("key"))
        self.lkg_fingerprint = str(manifest.get("code_fingerprint") or "")
        self.lkg_module_drift = manifest.get("lkg_module_hash") != aep_lkg.LKG_MODULE_HASH
        self._event("LKG_SAVED", key=self.lkg_key, created=bool(manifest.get("created")))

    # -- backend start / recovery ------------------------------------------------------------------

    def _conn_ok(self) -> bool:
        return bool(self.active_conn and self.active_conn.alive and self.active_conn.proc.poll() is None)

    def _note_drop(self) -> int:
        """Record a backend drop; return how many fall inside the sliding window."""
        now = self.clock()
        self.drops = [t for t in self.drops if now - t <= CRASH_WINDOW_S] + [now]
        return len(self.drops)

    async def _health_and_list(self, conn: BackendConnection, generation: int, health_timeout: float) -> tuple[
        dict[str, Any], list[dict[str, Any]], str
    ]:
        try:
            health = await conn.send_request({"op": "health"}, timeout=health_timeout)
            if health.get("status") != "OK":
                raise RuntimeError(health.get("error") or "Non-OK health status")
            tools_resp = await conn.send_request({"op": "list"}, timeout=10.0)
        except Exception as e:  # noqa: BLE001
            kind, tail = await self._classify_failure(conn, generation)
            await conn.terminate()
            raise _StartFailure(kind, tail or str(e), tail) from e
        return health, tools_resp.get("tools", []), tools_resp.get("schema_hash", "")

    async def _start_disk_backend(self) -> tuple[BackendConnection, dict[str, Any], list[dict[str, Any]], str]:
        try:
            conn = await self._spawn_backend(self.generation)
        except Exception as e:  # noqa: BLE001
            raise _StartFailure("transient", f"spawn failed: {e}") from e
        health, tools, schema_hash = await self._health_and_list(conn, self.generation, 20.0)
        return conn, health, tools, schema_hash

    async def get_or_start_backend(self) -> BackendConnection:
        if self._conn_ok():
            assert self.active_conn is not None  # noqa: S101
            return self.active_conn

        async with self.swap_lock:
            if self._conn_ok():
                assert self.active_conn is not None  # noqa: S101
                return self.active_conn
            return await self._recover_locked()

    async def _recover_locked(self) -> BackendConnection:
        mode = get_hotswap_mode()
        dead = self.active_conn
        if dead is not None:
            self.active_conn = None
            with contextlib.suppress(Exception):
                await dead.terminate()

        if self.serving_lkg and dead is not None:
            # The LKG worker itself died: restart it. The disk is retried only when its fingerprint changes.
            conn = await self._serve_lkg(mode, reason="lkg_worker_died")
            if conn is not None:
                return conn
            raise RuntimeError(self.last_reload_error or "LKG worker could not be restarted")

        if dead is not None:
            n = self._note_drop()
            self._event("BACKEND_DROPPED", drops_in_window=n)
            if n >= CRASH_WINDOW_MAX:
                self.failed_fingerprint = code_fingerprint(PROJECT_ROOT)
                conn = await self._serve_lkg(mode, reason="crash_window")
                if conn is not None:
                    return conn
            else:
                await self.sleep(transient_backoff_seconds(n))

        while True:
            disk_fp = code_fingerprint(PROJECT_ROOT)
            try:
                conn, health, tools, schema_hash = await self._start_disk_backend()
                break
            except _StartFailure as f:
                n = self._note_drop()
                self._set_error(f.kind, f"Initial Gen {self.generation} health failed: {f.detail}", f.tail or f.detail)
                if f.kind == "deterministic":
                    self.failed_fingerprint = disk_fp
                if f.kind == "deterministic" or n >= CRASH_WINDOW_MAX:
                    self.failed_fingerprint = disk_fp
                    lkg_conn = await self._serve_lkg(mode, reason=f.kind)
                    if lkg_conn is not None:
                        return lkg_conn
                    raise RuntimeError(self.last_reload_error) from f
                await self.sleep(transient_backoff_seconds(n))

        self.active_instructions = health.get("instructions", "")
        self.active_schema = tools
        self.active_schema_hash = schema_hash
        self.active_fingerprint = code_fingerprint(PROJECT_ROOT)
        self.active_conn = conn
        await self._save_lkg(self.generation, self.active_fingerprint, schema_hash)
        await self._push_meta(mode)
        return conn

    async def _serve_lkg(self, mode: str, reason: str) -> BackendConnection | None:
        """N2: start a backend from the newest verified LKG tree. None when no usable LKG exists."""
        if aep_lkg is None:
            self._event("LKG_UNAVAILABLE", reason=reason)
            return None
        try:
            key = await asyncio.to_thread(aep_lkg.latest)
            if not key:
                self._event("LKG_UNAVAILABLE", reason="no_verified_lkg")
                return None
            manifest = await asyncio.to_thread(aep_lkg.read_manifest, key)
            tree = aep_lkg.tree_path(key)
        except Exception as e:  # noqa: BLE001
            self._event("LKG_UNAVAILABLE", reason=f"lkg_read_failed: {e}")
            return None
        conn: BackendConnection | None = None
        try:
            conn = await self._spawn_backend(self.generation, lkg_tree=tree)
            health, tools, schema_hash = await self._health_and_list(conn, self.generation, 20.0)
        except Exception as e:  # noqa: BLE001
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.terminate()
            self._event("LKG_START_FAILED", key=key, error=str(e))
            return None

        old_hash = self.active_schema_hash
        self.active_conn = conn
        self.active_instructions = health.get("instructions", "")
        self.active_schema = tools
        self.active_schema_hash = schema_hash
        self.active_fingerprint = str(manifest.get("code_fingerprint") or f"lkg:{key}")
        self.serving_lkg = True
        self.lkg_key = key
        self.lkg_fingerprint = self.active_fingerprint
        self.lkg_module_drift = manifest.get("lkg_module_hash") != aep_lkg.LKG_MODULE_HASH
        self._event("SERVING_LKG", key=key, reason=reason)
        await self._push_meta(mode)
        if old_hash and schema_hash != old_hash and self.cached_session:
            with contextlib.suppress(Exception):
                await self.cached_session.send_tool_list_changed()
        return conn

    # -- meta ----------------------------------------------------------------------------------------

    def _effective_failure_kind(self) -> str | None:
        if self.serving_lkg:
            return "SERVING_LKG"
        if self.failure_kind:
            return self.failure_kind
        return LKG_UNAVAILABLE if aep_lkg is None else None

    def _live_meta(self, mode: str) -> dict[str, Any]:
        return {
            "last_reload_error": self.last_reload_error,
            "last_reload_error_struct": self.last_reload_error_struct,
            "failure_kind": self._effective_failure_kind(),
            "hotswap_mode": mode,
            "swap_attempts": self.swap_attempts,
            "swap_fenced": self.swap_fenced,
            "swap_fence_orphan": self.swap_fence_orphan,
            "serving_from": "lkg" if self.serving_lkg else None,
            "lkg_fingerprint": self.lkg_fingerprint if self.serving_lkg else None,
            "lkg_module_drift": self.lkg_module_drift,
        }

    async def _push_meta(self, mode: str, extra: dict[str, Any] | None = None) -> None:
        """Send current front-side state to the ACTIVE backend (explicit None clears fields)."""
        self._write_state()
        if self.active_conn and self.active_conn.alive:
            meta = self._live_meta(mode)
            if extra:
                meta.update(extra)
            with contextlib.suppress(Exception):
                await self.active_conn.send_request({"op": "set_meta", "meta": meta}, timeout=5.0)

    def _set_error(self, kind: str, error: str, tail: str) -> None:
        """N0: free text is preserved; the structured form comes from aep_lkg.parse_error."""
        self.last_reload_error = f"[{kind}] {error}"
        self.failure_kind = kind
        struct = None
        if aep_lkg is not None:
            with contextlib.suppress(Exception):
                struct = aep_lkg.parse_error(tail or error)
        self.last_reload_error_struct = struct

    async def _refresh_fence(self, mode: str) -> bool:
        """Re-evaluate the swap fence, publish changes, and return True if swapping is fenced."""
        fenced, orphan = swap_fence_state()
        if (fenced, orphan) != (self.swap_fenced, self.swap_fence_orphan):
            self.swap_fenced, self.swap_fence_orphan = fenced, orphan
            await self._push_meta(mode)
        return fenced

    async def _classify_failure(self, candidate: BackendConnection | None, generation: int) -> tuple[str, str]:
        """deterministic: candidate exited with a traceback; transient: anything else (timeout,
        spawn exception, failed list with the process alive). Returns (kind, log_tail)."""
        exited = False
        if candidate is not None:
            try:
                await asyncio.to_thread(candidate.proc.wait, timeout=0.5)
                exited = True
            except Exception:  # noqa: BLE001
                exited = candidate.proc.poll() is not None
        tail = _read_backend_log_tail(generation=generation, max_bytes=4096) if candidate is not None else ""
        deterministic = exited and ("Traceback" in tail or "SyntaxError" in tail)
        return ("deterministic" if deterministic else "transient"), tail

    async def _record_failed_swap(self, mode: str, disk_fp: str, error: str, kind: str, tail: str = "") -> None:
        """Retain Gen N and surface the error (D-18). Deterministic failures pin the failing
        fingerprint (D-19). Transient ones retry with backoff, up to TRANSIENT_MAX_ATTEMPTS."""
        self._set_error(kind, error, tail)
        if kind == "deterministic":
            self.failed_fingerprint = disk_fp
        else:
            if disk_fp != self.transient_fp:
                self.transient_fp = disk_fp
                self.transient_failures = 0
            self.transient_failures += 1
            if self.transient_failures >= TRANSIENT_MAX_ATTEMPTS:
                self.failed_fingerprint = disk_fp  # give up; touching the file forces a new attempt
            else:
                self.next_retry_at = self.clock() + transient_backoff_seconds(self.transient_failures)
        self._event("SWAP_FAILED", failure_kind=kind, error=error)
        await self._push_meta(mode)

    def _clear_failure_state(self) -> None:
        self.last_reload_error = None
        self.last_reload_error_struct = None
        self.failure_kind = None
        self.failed_fingerprint = ""
        self.transient_failures = 0
        self.transient_fp = ""
        self.next_retry_at = 0.0

    async def check_and_swap_if_needed(self) -> None:
        now = time.time()
        # Debounce (default 1s, AEP_HOTSWAP_DEBOUNCE_S)
        if now - self.last_check_time < _debounce_seconds():
            return
        self.last_check_time = now

        mode = get_hotswap_mode()

        # D-20(b): explicit fence. Reported honestly; stale stays visible.
        fenced = await self._refresh_fence(mode)

        disk_fp = code_fingerprint(PROJECT_ROOT)

        if not self.active_fingerprint:
            self.active_fingerprint = disk_fp
            return

        # While serving from the LKG tree, "same fingerprint as the served code" does not mean the disk
        # is what runs: only a pinned (already failed) fingerprint is skipped.
        if disk_fp == self.active_fingerprint and not self.serving_lkg:
            # Code reverted to what is running: an old reload error no longer applies.
            if self.last_reload_error is not None or self.failed_fingerprint or self.failure_kind:
                self._clear_failure_state()
                await self._push_meta(mode)
            return

        # Code has changed!
        if mode == "watch":
            # In watch mode, do not swap. Report stale to active backend.
            await self._push_meta(mode)
            return

        if fenced:
            return

        # D-19: do not retry the same deterministically broken fingerprint.
        if disk_fp == self.failed_fingerprint:
            return
        # Transient failure backoff (1 s, 2 s, 4 s).
        if disk_fp == self.transient_fp and self.clock() < self.next_retry_at:
            return

        # D-20(a): quiescence window; only swap if the fingerprint is stable across two reads.
        await self.sleep(_quiesce_seconds())
        if code_fingerprint(PROJECT_ROOT) != disk_fp:
            self.last_check_time = 0.0  # still being written: re-evaluate on the next call
            return

        # Auto-swap enabled (7rwx / 6rw- / 5r-x)
        async with self.swap_lock:
            # Re-check under lock (fingerprint and fence: a fence may appear during quiescence)
            disk_fp = code_fingerprint(PROJECT_ROOT)
            if (disk_fp == self.active_fingerprint and not self.serving_lkg) or disk_fp == self.failed_fingerprint:
                return
            if await self._refresh_fence(mode):
                return

            next_gen = self.generation + 1
            self.swap_attempts += 1
            try:
                candidate = await self._spawn_backend(generation=next_gen)
            except Exception as e:  # noqa: BLE001
                await self._record_failed_swap(mode, disk_fp, f"Failed to spawn backend Gen {next_gen}: {e}", "transient")
                return

            # Wait for health (fail-safe)
            try:
                health = await candidate.send_request({"op": "health"}, timeout=_health_timeout_seconds())
                if health.get("status") != "OK":
                    raise RuntimeError(health.get("error") or "Non-OK health status")
            except Exception as e:  # noqa: BLE001
                # Retain Gen N! Un code roto nunca sustituye a uno sano.
                kind, err_tail = await self._classify_failure(candidate, next_gen)
                err_detail = err_tail or str(e)
                await candidate.terminate()
                await self._record_failed_swap(
                    mode, disk_fp, f"Reload Gen {next_gen} health failed: {err_detail}", kind, err_tail
                )
                return

            new_instructions = health.get("instructions", "")
            # Health succeeded: fetch tool schema
            try:
                tools_resp = await candidate.send_request({"op": "list"}, timeout=10.0)
                new_schema = tools_resp.get("tools", [])
                new_schema_hash = tools_resp.get("schema_hash", "")
            except Exception as e:  # noqa: BLE001
                kind, tail = await self._classify_failure(candidate, next_gen)
                await candidate.terminate()
                await self._record_failed_swap(mode, disk_fp, f"Failed to list tools from Gen {next_gen}: {e}", kind, tail)
                return

            # A fence created while the candidate was starting aborts the promotion.
            if await self._refresh_fence(mode):
                await candidate.terminate()
                return

            old_conn = self.active_conn
            old_schema_hash = self.active_schema_hash
            was_lkg = self.serving_lkg

            # Promote Gen N+1
            self.active_conn = candidate
            self.active_schema = new_schema
            self.active_schema_hash = new_schema_hash
            self.active_instructions = new_instructions
            self.active_fingerprint = disk_fp
            self.generation = next_gen
            self.last_swap_at = datetime.now(UTC).isoformat()
            self.serving_lkg = False
            self.drops = []  # N2: the crash counter restarts on every promotion
            self._clear_failure_state()
            self._event("PROMOTED", from_lkg=was_lkg, fingerprint=disk_fp)
            if hasattr(server, "instructions") and new_instructions:
                server.instructions = new_instructions

            # N1: snapshot the freshly promoted, healthy disk tree.
            await self._save_lkg(self.generation, disk_fp, new_schema_hash)

            # Sync metadata to new worker (explicit None clears any stale error)
            await self._push_meta(
                mode,
                {"backend_generation": self.generation, "last_swap_at": self.last_swap_at},
            )

            # Check if schema changed: notify client
            if old_schema_hash and new_schema_hash != old_schema_hash:
                if self.cached_session:
                    try:
                        await self.cached_session.send_tool_list_changed()
                    except Exception:  # noqa: BLE001, S110
                        pass

            # Drain calls on old connection in background (max 30s)
            if old_conn:
                asyncio.create_task(self._drain_and_terminate(old_conn, timeout=30.0))

    async def _drain_and_terminate(self, conn: BackendConnection, timeout: float = 30.0) -> None:
        start_t = time.time()
        while conn.in_flight_calls > 0 and time.time() - start_t < timeout:
            await asyncio.sleep(0.1)
        await conn.terminate()

    # -- reload barrier (autoevol verify | fix_test) ---------------------------------------------------

    def compute_barrier(self) -> dict[str, Any]:
        """Plain-JSON barrier state: {state, reason, retry_after_s, error, served_fingerprint,
        disk_fingerprint, from_lkg}. The backend consumes it as `_barrier`; no threads_verify import here."""
        disk_fp = code_fingerprint(PROJECT_ROOT)
        out: dict[str, Any] = {
            "state": RELOAD_PENDING,
            "reason": "swap_pending",
            "retry_after_s": None,
            "error": self.last_reload_error,
            "served_fingerprint": self.active_fingerprint,
            "disk_fingerprint": disk_fp,
            "from_lkg": self.serving_lkg,
        }
        if self.serving_lkg:
            out.update(state=SERVING_LKG, reason="serving_lkg")
        elif disk_fp == self.active_fingerprint:
            out.update(state=RELOAD_OK, reason="", error=None)
        elif disk_fp == self.failed_fingerprint:
            out.update(state=RELOAD_FAILED, reason=self.failure_kind or "failed")
        elif get_hotswap_mode() == "watch":
            out.update(reason="watch_mode")
        elif swap_fence_state()[0]:
            out.update(reason="fenced")
        elif disk_fp == self.transient_fp and self.clock() < self.next_retry_at:
            out.update(reason="backoff", retry_after_s=round(max(0.0, self.next_retry_at - self.clock()), 3))
        return out

    async def settle_barrier(self) -> dict[str, Any]:
        """Force a fingerprint check and wait (up to AEP_RELOAD_BARRIER_S) until the swap is no longer pending."""
        deadline = self.clock() + _barrier_timeout_seconds()
        while True:
            self.last_check_time = 0.0
            await self.check_and_swap_if_needed()
            state = self.compute_barrier()
            if state["state"] != RELOAD_PENDING or state["reason"] == "watch_mode" or self.clock() >= deadline:
                return state
            await self.sleep(BARRIER_POLL_S)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        # `_barrier` is front-owned: a client-supplied value is always discarded.
        arguments = {k: v for k, v in (arguments or {}).items() if k != "_barrier"}
        if name == BARRIER_TOOL and arguments.get("action") in BARRIER_ACTIONS:
            arguments["_barrier"] = await self.settle_barrier()
        else:
            await self.check_and_swap_if_needed()
        conn = await self.get_or_start_backend()

        conn.in_flight_calls += 1
        try:
            resp = await conn.send_request(
                {"op": "call", "name": name, "args": arguments},
                timeout=300.0,
            )
        finally:
            conn.in_flight_calls -= 1

        if resp.get("status") == "OK":
            res = resp.get("result")
            return res if isinstance(res, str) else json.dumps(res)
        raise RuntimeError(resp.get("error", "Tool execution error in backend"))

    async def list_tools(self) -> list[types.Tool]:
        await self.check_and_swap_if_needed()
        _ = await self.get_or_start_backend()
        tools_list: list[types.Tool] = []
        for t in self.active_schema:
            tools_list.append(
                types.Tool(
                    name=t["name"],
                    description=t.get("description", ""),
                    inputSchema=t.get("inputSchema", {"type": "object"}),
                )
            )
        return tools_list

    async def shutdown(self) -> None:
        if self.active_conn:
            await self.active_conn.terminate()
            self.active_conn = None
        self._remove_state()


def create_front_server(mgr: LivePlaneManager, instructions: str | None = None) -> Server:
    """Create Low-Level MCP Server instance with optional advertised instructions (F3)."""
    srv = Server("Agent-Execution-Plane", instructions=instructions)

    @srv.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        with contextlib.suppress(Exception):
            mgr.cached_session = srv.request_context.session
        return await mgr.list_tools()

    @srv.call_tool(validate_input=False)
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        with contextlib.suppress(Exception):
            mgr.cached_session = srv.request_context.session
        result_text = await mgr.call_tool(name, arguments)
        return [types.TextContent(type="text", text=result_text)]

    return srv


manager = LivePlaneManager()
server = create_front_server(manager)


async def main() -> None:
    global server  # noqa: PLW0603
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _sig_handler() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _sig_handler)

    # F3: Eagerly start Gen 1 before stdio_server to advertise backend instructions
    server_instructions: str | None = None
    try:
        await manager.get_or_start_backend()
        server_instructions = manager.active_instructions
    except Exception as e:  # noqa: BLE001
        logger.error("Gen 1 eager startup failed: %s", e)
        server_instructions = (
            f"Agent-Execution-Plane (Degraded Mode)\n"
            f"Backend Gen 1 startup failed: {manager.last_reload_error or e}"
        )

    server = create_front_server(manager, instructions=server_instructions)

    initialization_options = server.create_initialization_options(
        NotificationOptions(tools_changed=True)
    )

    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            server_task = asyncio.create_task(
                server.run(
                    read_stream,
                    write_stream,
                    initialization_options,
                    raise_exceptions=False,
                )
            )
            stop_task = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                [server_task, stop_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
