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
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Fast path: legacy mode override
if os.environ.get("AEP_HOTSWAP") == "0":
    project_root = Path(__file__).resolve().parent
    server_py = project_root / "server.py"
    os.execv(sys.executable, [sys.executable, str(server_py), *sys.argv[1:]])  # noqa: S606

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


def swap_fence_state() -> tuple[bool, bool]:
    """Return (fenced, orphan). A fence older than SWAP_FENCE_ORPHAN_AFTER_S is ignored (orphan)."""
    try:
        st = (PROJECT_ROOT / SWAP_FENCE_NAME).stat()
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


class LivePlaneManager:
    """Orchestrates hot-swapping, fail-safe promotion, and drainage of backends."""

    def __init__(self) -> None:
        self.active_conn: BackendConnection | None = None
        self.active_schema: list[dict[str, Any]] = []
        self.active_schema_hash: str = ""
        self.active_fingerprint: str = ""
        self.active_instructions: str = ""
        self.generation: int = 1
        self.last_swap_at: str | None = None
        self.last_reload_error: str | None = None
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

    def is_front_stale(self) -> bool:
        try:
            st = (PROJECT_ROOT / "aep_front.py").stat()
            return st.st_mtime_ns > FRONT_START_TIME_NS
        except OSError:
            return False

    async def _spawn_backend(self, generation: int) -> BackendConnection:
        backend_script = PROJECT_ROOT / "aep_backend.py"
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
                cwd=str(PROJECT_ROOT),
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

    async def get_or_start_backend(self) -> BackendConnection:
        if self.active_conn and self.active_conn.alive and self.active_conn.proc.poll() is None:
            return self.active_conn

        async with self.swap_lock:
            if self.active_conn and self.active_conn.alive and self.active_conn.proc.poll() is None:
                return self.active_conn

            conn = await self._spawn_backend(self.generation)
            try:
                health = await conn.send_request({"op": "health"}, timeout=20.0)
                if health.get("status") != "OK":
                    raise RuntimeError(health.get("error") or "Non-OK health status")
            except Exception as e:
                err_tail = _read_backend_log_tail(self.generation, max_bytes=4096)
                err_detail = err_tail or str(e)
                self.last_reload_error = f"Initial Gen {self.generation} health failed: {err_detail}"
                await conn.terminate()
                raise RuntimeError(self.last_reload_error) from e

            self.active_instructions = health.get("instructions", "")
            tools_resp = await conn.send_request({"op": "list"}, timeout=10.0)
            self.active_schema = tools_resp.get("tools", [])
            self.active_schema_hash = tools_resp.get("schema_hash", "")
            self.active_fingerprint = code_fingerprint(PROJECT_ROOT)
            self.active_conn = conn
            return conn

    def _live_meta(self, mode: str) -> dict[str, Any]:
        return {
            "last_reload_error": self.last_reload_error,
            "failure_kind": self.failure_kind,
            "hotswap_mode": mode,
            "swap_attempts": self.swap_attempts,
            "swap_fenced": self.swap_fenced,
            "swap_fence_orphan": self.swap_fence_orphan,
        }

    async def _push_meta(self, mode: str, extra: dict[str, Any] | None = None) -> None:
        """Send current front-side state to the ACTIVE backend (explicit None clears fields)."""
        if self.active_conn and self.active_conn.alive:
            meta = self._live_meta(mode)
            if extra:
                meta.update(extra)
            with contextlib.suppress(Exception):
                await self.active_conn.send_request({"op": "set_meta", "meta": meta}, timeout=5.0)

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

    async def _record_failed_swap(self, mode: str, disk_fp: str, error: str, kind: str) -> None:
        """Retain Gen N and surface the error (D-18). Deterministic failures pin the failing
        fingerprint (D-19). Transient ones retry with backoff, up to TRANSIENT_MAX_ATTEMPTS."""
        self.last_reload_error = f"[{kind}] {error}"
        self.failure_kind = kind
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
                self.next_retry_at = time.monotonic() + transient_backoff_seconds(self.transient_failures)
        await self._push_meta(mode)

    def _clear_failure_state(self) -> None:
        self.last_reload_error = None
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

        if disk_fp == self.active_fingerprint:
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
        if disk_fp == self.transient_fp and time.monotonic() < self.next_retry_at:
            return

        # D-20(a): quiescence window; only swap if the fingerprint is stable across two reads.
        await asyncio.sleep(_quiesce_seconds())
        if code_fingerprint(PROJECT_ROOT) != disk_fp:
            self.last_check_time = 0.0  # still being written: re-evaluate on the next call
            return

        # Auto-swap enabled (7rwx / 6rw- / 5r-x)
        async with self.swap_lock:
            # Re-check under lock (fingerprint and fence: a fence may appear during quiescence)
            disk_fp = code_fingerprint(PROJECT_ROOT)
            if disk_fp == self.active_fingerprint or disk_fp == self.failed_fingerprint:
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
                await self._record_failed_swap(mode, disk_fp, f"Reload Gen {next_gen} health failed: {err_detail}", kind)
                return

            new_instructions = health.get("instructions", "")
            # Health succeeded: fetch tool schema
            try:
                tools_resp = await candidate.send_request({"op": "list"}, timeout=10.0)
                new_schema = tools_resp.get("tools", [])
                new_schema_hash = tools_resp.get("schema_hash", "")
            except Exception as e:  # noqa: BLE001
                kind, _ = await self._classify_failure(candidate, next_gen)
                await candidate.terminate()
                await self._record_failed_swap(mode, disk_fp, f"Failed to list tools from Gen {next_gen}: {e}", kind)
                return

            # A fence created while the candidate was starting aborts the promotion.
            if await self._refresh_fence(mode):
                await candidate.terminate()
                return

            old_conn = self.active_conn
            old_schema_hash = self.active_schema_hash

            # Promote Gen N+1
            self.active_conn = candidate
            self.active_schema = new_schema
            self.active_schema_hash = new_schema_hash
            self.active_instructions = new_instructions
            self.active_fingerprint = disk_fp
            self.generation = next_gen
            self.last_swap_at = datetime.now(UTC).isoformat()
            self._clear_failure_state()
            if hasattr(server, "instructions") and new_instructions:
                server.instructions = new_instructions

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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
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
