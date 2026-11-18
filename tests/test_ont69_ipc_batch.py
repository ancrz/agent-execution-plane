"""ONT-69 T1: the IPC `batch` path runs an async handler deterministically from the socket worker thread."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402
from engine.ipc_pool import UnixSocketMux, ipc_client_request  # noqa: E402


def _short_socket(tmp_path: Path) -> Path:
    # AF_UNIX paths are limited to ~108 bytes; tmp_path can exceed that, so use a short dir under it.
    d = tmp_path / "s"
    d.mkdir()
    return d / "m.sock"


def test_batch_end_to_end_over_socket(tmp_path: Path) -> None:
    mux = UnixSocketMux(_short_socket(tmp_path))
    mux.set_batch_handler(server._handle_ipc_batch)
    assert mux.start()
    try:
        resp = ipc_client_request(
            {
                "action": "batch",
                "name": "ont69-e2e",
                "steps": [{"id": "dag", "tool": "topos_audit_dag", "params": {"tasks": ["t1"], "dependencies": {}}}],
            },
            socket_path=mux.socket_path,
            timeout=30.0,
        )
    finally:
        mux.stop()
    assert resp["status"] == "OK", resp
    assert resp["all_ok"] is True
    assert resp["steps_run"] == 1
    assert resp["results"][0]["id"] == "dag"


def test_async_handler_runs_in_worker_thread_without_loop(tmp_path: Path) -> None:
    seen: dict[str, bool] = {}

    async def handler(req: dict) -> dict:
        await asyncio.sleep(0)
        seen["main"] = threading.current_thread() is threading.main_thread()
        return {"status": "OK", "echo": req["x"]}

    mux = UnixSocketMux(_short_socket(tmp_path))
    mux.set_batch_handler(handler)
    assert mux.start()
    try:
        resp = ipc_client_request({"action": "batch", "x": 7}, socket_path=mux.socket_path, timeout=10.0)
    finally:
        mux.stop()
    assert resp == {"status": "OK", "echo": 7}
    assert seen["main"] is False


def test_async_handler_with_running_loop_returns_error_not_deadlock(tmp_path: Path) -> None:
    async def handler(req: dict) -> dict:
        return {"status": "OK"}

    mux = UnixSocketMux(_short_socket(tmp_path))
    mux.set_batch_handler(handler)

    async def _inside_loop() -> dict:
        return mux._dispatch_message(b'{"action": "batch"}')

    res = asyncio.run(_inside_loop())
    assert res["status"] == "ERROR"
    assert "event loop" in res["error"]
