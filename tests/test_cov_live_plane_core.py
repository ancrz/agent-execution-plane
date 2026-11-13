"""ONT-45 N2/N3: in-process coverage of the live-plane core (backend worker + front server + entry points).

`import aep_backend` runs `os.dup2(sys.stderr.fileno(), 1)` and rebinds `sys.stdout` at import time, which would
corrupt pytest's capture for the whole session. The module-scoped fixture below saves fd 1 / sys.stdout around
the import and restores both in `finally`. Sockets are socketpairs; nothing touches /dev/shm/aep.sock or the pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import sys
import types as pytypes
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

import aep_front
import server as server_mod


class _Fd1Guard:
    """Saves fd 1 / sys.stdout so the import-time redirect of `aep_backend` can be undone."""

    def __init__(self) -> None:
        self.fd = os.dup(1)
        self.stdout = sys.stdout
        self.getter = getattr(server_mod, "_BACKEND_META_GETTER", None)

    def restore(self) -> None:
        os.dup2(self.fd, 1)
        os.close(self.fd)
        sys.stdout = self.stdout
        server_mod._BACKEND_META_GETTER = self.getter


# Plain top-level statements (the covers extractor only resolves top-level imports): guard, import, restore.
_GUARD = _Fd1Guard()
try:
    import aep_backend as _loaded  # noqa: E402,F401
finally:
    _GUARD.restore()
import aep_backend  # noqa: E402,F811  (already loaded; no side effect, resolves symbols for the graph)

TIMEOUT_S = 5.0

_DEFAULT_META: dict[str, Any] = {
    "backend_generation": 1,
    "last_swap_at": None,
    "last_reload_error": None,
    "hotswap_mode": "auto",
    "failure_kind": None,
    "swap_attempts": 0,
    "swap_fenced": False,
    "swap_fence_orphan": False,
    "serving_from": None,
    "lkg_fingerprint": None,
    "last_reload_error_struct": None,
    "lkg_module_drift": False,
}


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _ident(st: os.stat_result) -> tuple[int, int]:
    return (st.st_dev, st.st_ino)


@pytest.fixture(scope="module", autouse=True)
def _fd1_guard() -> Iterator[Any]:
    guard = _Fd1Guard()
    try:
        yield aep_backend
    finally:
        guard.restore()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("AEP_STATE_DIR", str(tmp_path / "state"))
    for var in ("AEP_TEST_STDERR_FLOOD", "AEP_TEST_STDOUT_CORRUPT", "AEP_TEST_HEALTH_DELAY_S"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def meta_reset() -> Iterator[None]:
    yield
    aep_backend.BACKEND_META.update(_DEFAULT_META)


def test_fixture_protocol_restores_fd1_and_stdout() -> None:
    """Re-running the real import-time redirect of `aep_backend` under `_Fd1Guard` leaves fd 1 and sys.stdout as
    they were (this is the hazard Ontos E3 flagged: aep_backend.py dup2()s stderr onto fd 1 at import)."""
    import importlib

    stdout_before = sys.stdout
    stat_before = _ident(os.fstat(1))
    meta_before = dict(aep_backend.BACKEND_META)
    guard = _Fd1Guard()
    try:
        importlib.reload(aep_backend)  # executes the module-level os.dup2(stderr, 1) + sys.stdout reassignment again
        assert _ident(os.fstat(1)) != stat_before or sys.stdout is not stdout_before  # the hazard is real
    finally:
        guard.restore()
        aep_backend.BACKEND_META.clear()
        aep_backend.BACKEND_META.update(meta_before)
    assert sys.stdout is stdout_before
    assert _ident(os.fstat(1)) == stat_before
    assert aep_backend.get_backend_meta() == meta_before


# --------------------------------------------------------------------------------------------------------------
# N2(a): BackendWorker.handle_line
# --------------------------------------------------------------------------------------------------------------


async def _exchange(lines: list[str], expected: int) -> tuple[Any, list[dict[str, Any]]]:
    a, b = socket.socketpair()
    worker = aep_backend.BackendWorker(a)
    _, writer_w = await asyncio.open_connection(sock=a)
    reader_c, writer_c = await asyncio.open_connection(sock=b)
    responses: list[dict[str, Any]] = []
    try:
        for line in lines:
            await aep_backend.BackendWorker.handle_line(worker, line, writer_w)
        for _ in range(expected):
            raw = await asyncio.wait_for(reader_c.readline(), TIMEOUT_S)
            responses.append(json.loads(raw))
        await asyncio.gather(*worker.in_flight_tasks, return_exceptions=True)
        return worker, responses
    finally:
        for w in (writer_w, writer_c):
            w.close()
            with contextlib.suppress(Exception):
                await w.wait_closed()


def test_handle_line_health_ok(meta_reset: None) -> None:
    _, [resp] = asyncio.run(_exchange([json.dumps({"op": "health", "id": 7})], 1))
    assert resp["status"] == "OK"
    assert resp["id"] == 7
    assert resp["pid"] == os.getpid()
    assert resp["tools_count"] >= 1
    assert resp["schema_hash"] == server_mod._get_schema_hash()


def test_handle_line_list_returns_tools_and_hash(meta_reset: None) -> None:
    _, [resp] = asyncio.run(_exchange([json.dumps({"op": "list", "id": 1})], 1))
    assert resp["status"] == "OK"
    assert "discover" in {t["name"] for t in resp["tools"]}
    assert resp["schema_hash"] == server_mod._get_schema_hash()


def test_handle_line_call_unknown_tool_is_structured_error(meta_reset: None) -> None:
    line = json.dumps({"op": "call", "id": 3, "name": "no_such_tool", "args": {}})
    _, [resp] = asyncio.run(_exchange([line], 1))
    assert resp["status"] == "ERROR"
    assert resp["id"] == 3
    assert "no_such_tool" in resp["error"]
    assert "traceback" in resp


def test_handle_line_non_json_does_not_crash(meta_reset: None) -> None:
    worker, [resp] = asyncio.run(_exchange(["{not json"], 1))
    assert resp["status"] == "ERROR"
    assert resp["error"].startswith("Invalid JSON")
    assert worker.running is True


def test_handle_line_blank_and_unknown_op(meta_reset: None) -> None:
    _, [resp] = asyncio.run(_exchange(["   ", json.dumps({"op": "bogus", "id": 9})], 1))
    assert resp == {"status": "ERROR", "id": 9, "error": "Unknown op: bogus"}


def test_handle_line_set_meta_and_shutdown(meta_reset: None) -> None:
    lines = [
        json.dumps({"op": "set_meta", "id": 1, "meta": {"hotswap_mode": "watch", "not_a_key": 1}}),
        json.dumps({"op": "shutdown", "id": 2}),
    ]
    worker, responses = asyncio.run(_exchange(lines, 2))
    assert [r["status"] for r in responses] == ["OK", "OK"]
    assert aep_backend.BACKEND_META["hotswap_mode"] == "watch"
    assert "not_a_key" not in aep_backend.BACKEND_META
    assert worker.running is False


def test_valid_barrier_contract() -> None:
    assert aep_backend._valid_barrier({"state": "RELOAD_OK"}) is True
    assert aep_backend._valid_barrier({"state": "BOGUS"}) is False
    assert aep_backend._valid_barrier("RELOAD_OK") is False
    assert aep_backend._valid_barrier(None) is False


def test_handle_line_invalid_barrier_rejected_valid_forwarded(
    meta_reset: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_call_tool(name: str, args: dict[str, Any]) -> str:
        seen[json.dumps(args, sort_keys=True)] = server_mod._BARRIER_CTX.get()
        return "ok"

    monkeypatch.setattr(server_mod.mcp._tool_manager, "call_tool", fake_call_tool)
    lines = [
        json.dumps({"op": "call", "id": 1, "name": "t", "args": {"x": 1, "_barrier": {"state": "BOGUS"}}}),
        json.dumps({"op": "call", "id": 2, "name": "t", "args": {"_barrier": {"state": "RELOAD_OK"}}}),
    ]
    _, responses = asyncio.run(_exchange(lines, 2))
    assert {r["status"] for r in responses} == {"OK"}
    assert seen['{"x": 1}'] is None
    assert seen["{}"] == {"state": "RELOAD_OK"}


# --------------------------------------------------------------------------------------------------------------
# N2(b): aep_front.create_front_server
# --------------------------------------------------------------------------------------------------------------


class FakeManager:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.listed = 0
        self.cached_session: Any = None
        self.active_instructions = "fake-instructions"
        self.last_reload_error = None
        self.shut = False

    async def list_tools(self) -> list[Any]:
        self.listed += 1
        return [aep_front.types.Tool(name="alpha", description="d", inputSchema={"type": "object"})]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if self.fail:
            raise self.fail
        return "routed-result"

    async def get_or_start_backend(self) -> None:
        return None

    async def shutdown(self) -> None:
        self.shut = True


def _call_request(name: str, arguments: dict[str, Any]) -> Any:
    t = aep_front.types
    return t.CallToolRequest(method="tools/call", params=t.CallToolRequestParams(name=name, arguments=arguments))


def test_create_front_server_routes_list_and_call_to_manager() -> None:
    mgr = FakeManager()
    srv = aep_front.create_front_server(mgr, instructions="hello")  # type: ignore[arg-type]
    t = aep_front.types

    async def scenario() -> tuple[Any, Any]:
        listed = await srv.request_handlers[t.ListToolsRequest](t.ListToolsRequest(method="tools/list"))
        called = await srv.request_handlers[t.CallToolRequest](_call_request("alpha", {"k": 1}))
        return listed, called

    listed, called = asyncio.run(scenario())
    assert srv.instructions == "hello"
    assert [x.name for x in listed.root.tools] == ["alpha"]
    assert mgr.listed >= 1
    assert mgr.calls == [("alpha", {"k": 1})]
    assert called.root.isError is False
    assert called.root.content[0].text == "routed-result"


def test_create_front_server_error_envelope_when_backend_does_not_respond() -> None:
    mgr = FakeManager(fail=RuntimeError("backend did not respond"))
    srv = aep_front.create_front_server(mgr)  # type: ignore[arg-type]
    t = aep_front.types

    called = asyncio.run(srv.request_handlers[t.CallToolRequest](_call_request("alpha", {})))
    assert called.root.isError is True
    assert "backend did not respond" in called.root.content[0].text


# --------------------------------------------------------------------------------------------------------------
# N3: entry points
# --------------------------------------------------------------------------------------------------------------


def test_backend_worker_run_returns_on_eof_without_fd_leak() -> None:
    async def scenario() -> None:
        a, b = socket.socketpair()
        worker = aep_backend.BackendWorker(a)
        b.close()  # EOF for the worker
        await asyncio.wait_for(aep_backend.BackendWorker.run(worker), TIMEOUT_S)
        assert worker.running is False

    asyncio.run(scenario())  # warm-up: lazily opened interpreter-level fds settle
    before = _fd_count()
    asyncio.run(scenario())
    assert _fd_count() - before == 0


def test_backend_worker_run_serves_lines_then_exits_on_shutdown(meta_reset: None) -> None:
    async def scenario() -> list[dict[str, Any]]:
        a, b = socket.socketpair()
        worker = aep_backend.BackendWorker(a)
        reader_c, writer_c = await asyncio.open_connection(sock=b)
        task = asyncio.create_task(aep_backend.BackendWorker.run(worker))
        writer_c.write(b'{"op":"bogus","id":1}\n{"op":"shutdown","id":2}\n')
        await writer_c.drain()
        out = [json.loads(await asyncio.wait_for(reader_c.readline(), TIMEOUT_S)) for _ in range(2)]
        await asyncio.wait_for(task, TIMEOUT_S)
        writer_c.close()
        with contextlib.suppress(Exception):
            await writer_c.wait_closed()
        return out

    out = asyncio.run(scenario())
    assert out[0]["status"] == "ERROR"
    assert out[1] == {"status": "OK", "id": 2}


def test_backend_main_without_fd_or_socket_exits_1(meta_reset: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["aep_backend.py"])
    prev = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as exc:
        aep_backend.main()
    assert exc.value.code == 1
    assert signal.getsignal(signal.SIGTERM) is prev  # exits before installing signals


class _ExitCalledError(Exception):
    pass


def test_backend_main_good_path_installs_sigterm_and_hands_off(
    meta_reset: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = socket.socketpair()
    ran: list[Any] = []

    def fake_run(coro: Any) -> None:
        ran.append(coro)
        coro.close()

    def fake_exit(code: int) -> None:
        raise _ExitCalledError(code)

    monkeypatch.setattr(sys, "argv", ["aep_backend.py", "--fd", str(a.fileno()), "--generation", "3"])
    monkeypatch.setattr(aep_backend.asyncio, "run", fake_run)
    monkeypatch.setattr(aep_backend.os, "_exit", fake_exit)
    prev = signal.getsignal(signal.SIGTERM)
    try:
        with pytest.raises(_ExitCalledError) as exc:
            aep_backend.main()
        handler = signal.getsignal(signal.SIGTERM)
        assert exc.value.args == (0,)
        assert callable(handler)
        assert handler is not prev
        with pytest.raises(SystemExit) as sig_exit:
            handler(signal.SIGTERM, None)
        assert sig_exit.value.code == 0
        assert aep_backend.BACKEND_META["backend_generation"] == 3
    finally:
        signal.signal(signal.SIGTERM, prev)
        a.close()
        b.close()
    assert len(ran) == 1


class _FakeLowServer:
    def __init__(self, ran: list[bool]) -> None:
        self._ran = ran

    def create_initialization_options(self, *_a: Any, **_k: Any) -> str:
        return "init-options"

    async def run(self, *_a: Any, **_k: Any) -> None:
        self._ran.append(True)


def _patch_front_main(monkeypatch: pytest.MonkeyPatch, mgr: Any, spy: dict[str, Any], ran: list[bool]) -> None:
    def fake_create(m: Any, instructions: str | None = None) -> _FakeLowServer:
        spy["mgr"] = m
        spy["instructions"] = instructions
        return _FakeLowServer(ran)

    @contextlib.asynccontextmanager
    async def fake_stdio() -> AsyncIterator[tuple[object, object]]:
        yield object(), object()

    monkeypatch.setattr(aep_front, "manager", mgr)
    monkeypatch.setattr(aep_front, "server", aep_front.server)  # main rebinds the global; restored on teardown
    monkeypatch.setattr(aep_front, "create_front_server", fake_create)
    monkeypatch.setattr(aep_front.mcp.server.stdio, "stdio_server", fake_stdio)
    monkeypatch.setattr(aep_front, "NotificationOptions", lambda **_k: pytypes.SimpleNamespace())


def _run_front_main() -> None:
    prev = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        asyncio.run(asyncio.wait_for(aep_front.main(), TIMEOUT_S))
    finally:
        for s, h in prev.items():
            signal.signal(s, h)


def test_front_main_reaches_create_front_server_with_global_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = FakeManager()
    spy: dict[str, Any] = {}
    ran: list[bool] = []
    _patch_front_main(monkeypatch, mgr, spy, ran)
    _run_front_main()
    assert spy["mgr"] is mgr
    assert spy["instructions"] == "fake-instructions"
    assert ran == [True]
    assert mgr.shut is True


def test_front_main_degraded_instructions_when_backend_start_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing(FakeManager):
        async def get_or_start_backend(self) -> None:
            raise RuntimeError("gen1 boom")

    mgr = Failing()
    spy: dict[str, Any] = {}
    _patch_front_main(monkeypatch, mgr, spy, [])
    _run_front_main()
    assert "Degraded Mode" in spy["instructions"]
    assert "gen1 boom" in spy["instructions"]
    assert mgr.shut is True
