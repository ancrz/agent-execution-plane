"""
aep_backend.py (ONT-39: Live Plane Backend Worker)

Private worker process running server.mcp tool manager.
Communicates with aep_front.py via JSON-lines over AF_UNIX socket (socketpair).

Handles:
- op: health (checks server and tool registration)
- op: list (returns tool schemas and schema_hash)
- op: call (executes tool via server.mcp._tool_manager)
- op: set_meta (updates generation, reload errors, swap timestamps)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import traceback
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# F1: Defense in depth - redirect stdout to stderr before importing server to prevent protocol corruption
with contextlib.suppress(Exception):
    os.dup2(sys.stderr.fileno(), 1)
    sys.stdout = sys.stderr

import server  # noqa: E402
from engine.fingerprint import code_fingerprint, resolve_repo_root  # noqa: E402

# Class D anchor: the disk fingerprint always refers to the real repository (AEP_REPO_ROOT under LKG).
REPO_ROOT = resolve_repo_root(PROJECT_ROOT)

logger = logging.getLogger("aep.backend")

# Global backend metadata queried by server.py discover(capabilities)
BACKEND_META: dict[str, Any] = {
    "backend_generation": 1,
    "last_swap_at": None,
    "last_reload_error": None,
    "hotswap_mode": "auto",
    "failure_kind": None,
    "swap_attempts": 0,
    "swap_fenced": False,
    "swap_fence_orphan": False,
}


def get_backend_meta() -> dict[str, Any]:
    return dict(BACKEND_META)


def set_backend_meta(**kwargs: Any) -> None:
    """Update known meta keys. Only keys actually sent are touched; an explicit None
    is a valid value (D-18: clears a stale last_reload_error)."""
    for k, v in kwargs.items():
        if k in BACKEND_META:
            BACKEND_META[k] = v


# Register metadata hook in server module for discover(capabilities)
server._BACKEND_META_GETTER = get_backend_meta


BARRIER_STATES = frozenset({"RELOAD_OK", "RELOAD_PENDING", "RELOAD_FAILED", "SERVING_LKG"})


def _valid_barrier(barrier: Any) -> bool:
    return isinstance(barrier, dict) and barrier.get("state") in BARRIER_STATES


class BackendWorker:
    def __init__(self, sock: socket.socket, generation: int = 1) -> None:
        self.sock = sock
        self.generation = generation
        self.write_lock = asyncio.Lock()
        self.running = True
        self.in_flight_tasks: set[asyncio.Task[Any]] = set()

    async def handle_line(self, line: str, writer: asyncio.StreamWriter) -> None:
        line = line.strip()
        if not line:
            return

        try:
            req = json.loads(line)
        except Exception as e:  # noqa: BLE001
            await self._send_response(writer, {"status": "ERROR", "error": f"Invalid JSON: {e}"})
            return

        op = req.get("op")
        req_id = req.get("id")

        if op == "health":
            try:
                tm = getattr(server.mcp, "_tool_manager", None)
                tools_count = len(getattr(tm, "_tools", {})) if tm else 0
                schema_hash = server._get_schema_hash()
                fp = code_fingerprint(REPO_ROOT)
                # T-D19: test hook simulating a slow candidate (only for swap candidates, Gen >= 2)
                health_delay = float(os.environ.get("AEP_TEST_HEALTH_DELAY_S", "0") or 0)
                if health_delay > 0 and self.generation >= 2:
                    await asyncio.sleep(health_delay)
                instructions = getattr(server.mcp, "instructions", "") or ""
                await self._send_response(writer, {
                    "status": "OK",
                    "id": req_id,
                    "generation": self.generation,
                    "pid": os.getpid(),
                    "tools_count": tools_count,
                    "schema_hash": schema_hash,
                    "code_fingerprint": fp,
                    "instructions": instructions,
                })
            except Exception as e:  # noqa: BLE001
                await self._send_response(writer, {
                    "status": "ERROR",
                    "id": req_id,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        elif op == "list":
            try:
                tm = getattr(server.mcp, "_tool_manager", None)
                tools = []
                if tm:
                    for t in tm.list_tools():
                        tools.append({
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.parameters,
                        })
                schema_hash = server._get_schema_hash()
                await self._send_response(writer, {
                    "status": "OK",
                    "id": req_id,
                    "tools": tools,
                    "schema_hash": schema_hash,
                })
            except Exception as e:  # noqa: BLE001
                await self._send_response(writer, {
                    "status": "ERROR",
                    "id": req_id,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        elif op == "call":
            name = req.get("name")
            args = req.get("args") or {}
            task = asyncio.create_task(self._execute_tool(writer, req_id, name, args))
            self.in_flight_tasks.add(task)
            task.add_done_callback(self.in_flight_tasks.discard)

        elif op == "set_meta":
            meta = req.get("meta") or {}
            set_backend_meta(**meta)
            await self._send_response(writer, {"status": "OK", "id": req_id})

        elif op == "shutdown":
            await self._send_response(writer, {"status": "OK", "id": req_id})
            self.running = False

        else:
            await self._send_response(writer, {
                "status": "ERROR",
                "id": req_id,
                "error": f"Unknown op: {op}",
            })

    async def _execute_tool(
        self,
        writer: asyncio.StreamWriter,
        req_id: Any,
        name: str,
        args: dict[str, Any],
    ) -> None:
        try:
            # T-F1: test stdout corruption injection hook
            if os.environ.get("AEP_TEST_STDOUT_CORRUPT") == "1":
                with contextlib.suppress(Exception):
                    sys.stdout.write("CORRUPT_STDOUT_STREAM_INJECTION\n")
                    sys.stdout.flush()
                    os.write(1, b"CORRUPT_RAW_FD1_INJECTION\n")
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import os, sys; sys.stdout.write('grandchild stdout\\n'); os.write(1, b'grandchild raw fd1\\n')",
                        ],
                        check=False,
                    )

            # T-F2: test stderr flood hook (>256 KiB)
            if os.environ.get("AEP_TEST_STDERR_FLOOD") == "1":
                with contextlib.suppress(Exception):
                    sys.stderr.write("AEP_TEST_STDERR_FLOOD\n" + ("X" * (300 * 1024)) + "\n")
                    sys.stderr.flush()

            tm = getattr(server.mcp, "_tool_manager", None)
            if not tm:
                raise RuntimeError("server.mcp._tool_manager not available")
            # `_barrier` is front-owned (reload barrier): never a tool argument; exposed via server contextvar.
            args = dict(args)
            barrier = args.pop("_barrier", None)
            server._BARRIER_CTX.set(barrier if _valid_barrier(barrier) else None)
            res = await tm.call_tool(name, args)
            await self._send_response(writer, {
                "status": "OK",
                "id": req_id,
                "result": res,
            })
        except Exception as e:  # noqa: BLE001
            await self._send_response(writer, {
                "status": "ERROR",
                "id": req_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

    async def _send_response(self, writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
        payload = (json.dumps(data) + "\n").encode("utf-8")
        async with self.write_lock:
            try:
                writer.write(payload)
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                self.running = False

    async def run(self) -> None:
        reader, writer = await asyncio.open_connection(sock=self.sock)
        try:
            while self.running:
                line = await reader.readline()
                if not line:
                    break
                await self.handle_line(line.decode("utf-8", errors="replace"), writer)
        finally:
            self.running = False
            # Wait briefly for in-flight tasks if any
            if self.in_flight_tasks:
                await asyncio.gather(*self.in_flight_tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="AEP Live Plane Backend Worker")
    parser.add_argument("--fd", type=int, help="Inherited AF_UNIX socket file descriptor")
    parser.add_argument("--socket-path", type=str, help="AF_UNIX socket path to connect")
    parser.add_argument("--generation", type=int, default=1, help="Backend generation number")
    parser.add_argument("--last-swap-at", type=str, default="", help="Last swap ISO timestamp")
    parser.add_argument("--last-reload-error", type=str, default="", help="Last reload error message")
    parser.add_argument("--hotswap-mode", type=str, default="auto", help="Hotswap mode: auto|watch|legacy")
    args = parser.parse_args()

    BACKEND_META["backend_generation"] = args.generation
    if args.last_swap_at:
        BACKEND_META["last_swap_at"] = args.last_swap_at
    if args.last_reload_error:
        BACKEND_META["last_reload_error"] = args.last_reload_error
    # Candidates never inherit a reload error through env (D-18); only set_meta carries it.
    BACKEND_META["hotswap_mode"] = args.hotswap_mode

    # Setup socket
    if args.fd is not None:
        sock = socket.fromfd(args.fd, socket.AF_UNIX, socket.SOCK_STREAM)
    elif args.socket_path:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(args.socket_path)
    else:
        # Default: duplicate sys.stdin if socket or error
        sys.stderr.write("aep_backend.py: error: either --fd or --socket-path required\n")
        sys.exit(1)

    # Setup signal handlers for graceful drain
    def _sigterm_handler(signum: int, frame: Any) -> None:
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # T-F2: test stderr flood at startup (>256 KiB)
    if os.environ.get("AEP_TEST_STDERR_FLOOD") == "1":
        with contextlib.suppress(Exception):
            sys.stderr.write("AEP_TEST_STDERR_FLOOD_STARTUP\n" + ("X" * (300 * 1024)) + "\n")
            sys.stderr.flush()

    worker = BackendWorker(sock, generation=args.generation)
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
