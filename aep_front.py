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
import json
import logging
import os
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

from engine.fingerprint import code_fingerprint  # noqa: E402

logger = logging.getLogger("aep.front")
PROJECT_ROOT = Path(__file__).resolve().parent
FRONT_START_TIME = time.time()


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
        self.generation: int = 1
        self.last_swap_at: str | None = None
        self.last_reload_error: str | None = None
        self.last_check_time: float = 0.0
        self.swap_lock = asyncio.Lock()
        self.cached_session: ServerSession | None = None

    def is_front_stale(self) -> bool:
        try:
            st = (PROJECT_ROOT / "aep_front.py").stat()
            return st.st_mtime > FRONT_START_TIME
        except OSError:
            return False

    async def _spawn_backend(self, generation: int) -> BackendConnection:
        backend_script = PROJECT_ROOT / "aep_backend.py"
        s_front, s_backend = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        s_backend.set_inheritable(True)

        mode = get_hotswap_mode()
        env = dict(os.environ)
        env["AEP_BACKEND_GENERATION"] = str(generation)
        env["AEP_HOTSWAP_MODE"] = mode
        if self.last_swap_at:
            env["AEP_LAST_SWAP_AT"] = self.last_swap_at
        if self.last_reload_error:
            env["AEP_LAST_RELOAD_ERROR"] = self.last_reload_error

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
            stderr=subprocess.PIPE,
        )
        s_backend.close()

        conn = BackendConnection(proc, s_front, generation)
        await conn.initialize()
        return conn

    async def get_or_start_backend(self) -> BackendConnection:
        if self.active_conn and self.active_conn.alive and self.active_conn.proc.poll() is None:
            return self.active_conn

        async with self.swap_lock:
            if self.active_conn and self.active_conn.alive and self.active_conn.proc.poll() is None:
                return self.active_conn

            conn = await self._spawn_backend(self.generation)
            health = await conn.send_request({"op": "health"}, timeout=20.0)
            if health.get("status") != "OK":
                await conn.terminate()
                raise RuntimeError(f"Initial backend health check failed: {health.get('error')}")

            tools_resp = await conn.send_request({"op": "list"}, timeout=10.0)
            self.active_schema = tools_resp.get("tools", [])
            self.active_schema_hash = tools_resp.get("schema_hash", "")
            self.active_fingerprint = code_fingerprint(PROJECT_ROOT)
            self.active_conn = conn
            return conn

    async def check_and_swap_if_needed(self) -> None:
        now = time.time()
        # Debounce of 1s
        if now - self.last_check_time < 1.0:
            return
        self.last_check_time = now

        mode = get_hotswap_mode()
        disk_fp = code_fingerprint(PROJECT_ROOT)

        if not self.active_fingerprint:
            self.active_fingerprint = disk_fp
            return

        if disk_fp == self.active_fingerprint:
            return

        # Code has changed!
        if mode == "watch":
            # In watch mode, do not swap. Report stale to active backend.
            if self.active_conn and self.active_conn.alive:
                with contextlib.suppress(Exception):
                    await self.active_conn.send_request({
                        "op": "set_meta",
                        "meta": {
                            "hotswap_mode": "watch",
                            "last_reload_error": self.last_reload_error,
                        },
                    }, timeout=2.0)
            return

        # Auto-swap enabled (7rwx / 6rw- / 5r-x)
        async with self.swap_lock:
            # Re-check under lock
            disk_fp = code_fingerprint(PROJECT_ROOT)
            if disk_fp == self.active_fingerprint:
                return

            next_gen = self.generation + 1
            try:
                candidate = await self._spawn_backend(generation=next_gen)
            except Exception as e:  # noqa: BLE001
                self.last_reload_error = f"Failed to spawn backend Gen {next_gen}: {e}"
                return

            # Wait for health with 20s timeout (fail-safe)
            try:
                health = await candidate.send_request({"op": "health"}, timeout=20.0)
                if health.get("status") != "OK":
                    raise RuntimeError(health.get("error") or "Non-OK health status")
            except Exception as e:  # noqa: BLE001
                # Retain Gen N! Un code roto nunca sustituye a uno sano.
                err_detail = str(e)
                if candidate.proc.poll() is not None and candidate.proc.stderr:
                    try:
                        err_bytes = candidate.proc.stderr.read()
                        if err_bytes:
                            lines = err_bytes.decode("utf-8", errors="replace").strip().splitlines()
                            err_detail = lines[-1] if lines else str(e)
                    except Exception:  # noqa: BLE001, S110
                        pass
                self.last_reload_error = f"Reload Gen {next_gen} health failed: {err_detail}"
                await candidate.terminate()
                if self.active_conn and self.active_conn.alive:
                    with contextlib.suppress(Exception):
                        await self.active_conn.send_request({
                            "op": "set_meta",
                            "meta": {
                                "last_reload_error": self.last_reload_error,
                                "hotswap_mode": mode,
                            },
                        }, timeout=2.0)
                return

            # Health succeeded: fetch tool schema
            try:
                tools_resp = await candidate.send_request({"op": "list"}, timeout=10.0)
                new_schema = tools_resp.get("tools", [])
                new_schema_hash = tools_resp.get("schema_hash", "")
            except Exception as e:  # noqa: BLE001
                self.last_reload_error = f"Failed to list tools from Gen {next_gen}: {e}"
                await candidate.terminate()
                return

            old_conn = self.active_conn
            old_schema_hash = self.active_schema_hash

            # Promote Gen N+1
            self.active_conn = candidate
            self.active_schema = new_schema
            self.active_schema_hash = new_schema_hash
            self.active_fingerprint = disk_fp
            self.generation = next_gen
            self.last_swap_at = datetime.now(UTC).isoformat()
            self.last_reload_error = None

            # Sync metadata to new worker
            with contextlib.suppress(Exception):
                await candidate.send_request({
                    "op": "set_meta",
                    "meta": {
                        "backend_generation": self.generation,
                        "last_swap_at": self.last_swap_at,
                        "last_reload_error": None,
                        "hotswap_mode": mode,
                    },
                }, timeout=5.0)

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


manager = LivePlaneManager()
server = Server("Agent-Execution-Plane")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    with contextlib.suppress(Exception):
        manager.cached_session = server.request_context.session
    return await manager.list_tools()


@server.call_tool(validate_input=False)
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    with contextlib.suppress(Exception):
        manager.cached_session = server.request_context.session
    result_text = await manager.call_tool(name, arguments)
    return [types.TextContent(type="text", text=result_text)]


async def main() -> None:
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _sig_handler() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _sig_handler)

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
