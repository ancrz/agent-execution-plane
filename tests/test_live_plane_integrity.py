"""
Test Suite: test_live_plane_integrity.py (ONT-39 follow-ups D-18..D-21 + per-front logs)

D-18  sticky reload error: cleared by a successful swap (explicit None through set_meta).
D-19  retry storm: a broken fingerprint is attempted once (swap_attempts).
D-20  multi-file integrity: quiescence window + explicit .aep_swap_fence (+ orphan fence).
D-21  front self-contained fingerprint fallback, hash-identical to engine.fingerprint.
D-5   per-front backend log names and retention.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REAL_FENCE = PROJECT_ROOT / ".aep_swap_fence"
FENCE = REAL_FENCE  # rebound per test to an isolated tmp path by the autouse fixture (D-22)
DEBOUNCE_WAIT_S = 0.05  # debounce is 0 in these tests (AEP_HOTSWAP_DEBOUNCE_S)


@pytest.fixture(autouse=True)
def _bind_fence(isolated_swap_fence: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """D-22: FENCE apunta al fence aislado (conftest); el real PROJECT_ROOT/.aep_swap_fence no se toca."""
    monkeypatch.setattr(sys.modules[__name__], "FENCE", isolated_swap_fence)
    return isolated_swap_fence


@contextlib.asynccontextmanager
async def front_session(extra_env: dict[str, str] | None = None) -> AsyncIterator[ClientSession]:
    env = dict(os.environ)
    env.pop("AEP_HOTSWAP_MODE", None)
    env["AEP_HOTSWAP"] = "1"
    env.pop("AEP_LAST_RELOAD_ERROR", None)
    env["AEP_HOTSWAP_DEBOUNCE_S"] = "0"
    env["AEP_HOTSWAP_QUIESCE_MS"] = "20"
    if extra_env:
        env.update(extra_env)
    params = StdioServerParameters(command=sys.executable, args=[str(PROJECT_ROOT / "aep_front.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def caps(session: ClientSession) -> dict[str, Any]:
    res = await session.call_tool("discover", {"action": "capabilities", "verbosity": "terse"})
    data = json.loads(res.content[0].text)
    assert data.get("status") == "OK"
    return data


@contextlib.contextmanager
def mutated_matcher() -> Any:
    """Yield (path, original_code); always restores content and mtime."""
    target = PROJECT_ROOT / "engine" / "matcher.py"
    st = target.stat()
    original = target.read_text(encoding="utf-8")
    try:
        yield target, original
    finally:
        target.write_text(original, encoding="utf-8")
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_d18_reload_error_cleared_after_successful_swap() -> None:
    async def _run() -> None:
        with mutated_matcher() as (target, original):
            async with front_session() as session:
                d1 = await caps(session)
                assert d1["backend_generation"] == 1
                assert d1["last_reload_error"] is None

                await asyncio.sleep(DEBOUNCE_WAIT_S)
                target.write_text(original + "\n\ndef broken_syntax(:\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["backend_generation"] == 1
                assert "SyntaxError" in str(d2["last_reload_error"])
                assert d2["failure_kind"] == "deterministic"

                # Fix with a NEW mtime/content so the fingerprint differs from both prior states.
                await asyncio.sleep(DEBOUNCE_WAIT_S)
                target.write_text(original + "\n# d18 fixed\n", encoding="utf-8")
                d3 = await caps(session)
                assert d3["backend_generation"] == 2
                assert d3["last_reload_error"] is None
                assert "failure_kind" not in d3
                assert d3["stale"] is False
                assert d3.get("severity", "INFO") == "INFO"

    asyncio.run(_run())


def test_d18_reverting_to_running_code_clears_error() -> None:
    async def _run() -> None:
        with mutated_matcher() as (target, original):
            st = target.stat()
            async with front_session() as session:
                await caps(session)
                await asyncio.sleep(DEBOUNCE_WAIT_S)
                target.write_text(original + "\n\ndef broken_syntax(:\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["last_reload_error"] is not None

                await asyncio.sleep(DEBOUNCE_WAIT_S)
                target.write_text(original, encoding="utf-8")
                os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
                d3 = await caps(session)
                assert d3["backend_generation"] == 1
                assert d3["last_reload_error"] is None

    asyncio.run(_run())


def test_d18_set_backend_meta_accepts_explicit_none_and_server_prefers_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    import aep_backend
    import server

    saved = dict(aep_backend.BACKEND_META)
    try:
        aep_backend.set_backend_meta(last_reload_error="boom")
        assert aep_backend.BACKEND_META["last_reload_error"] == "boom"
        aep_backend.set_backend_meta(hotswap_mode="auto")  # key not sent -> untouched
        assert aep_backend.BACKEND_META["last_reload_error"] == "boom"
        aep_backend.set_backend_meta(last_reload_error=None)
        assert aep_backend.BACKEND_META["last_reload_error"] is None
        aep_backend.set_backend_meta(unknown_key="x")
        assert "unknown_key" not in aep_backend.BACKEND_META
    finally:
        aep_backend.BACKEND_META.clear()
        aep_backend.BACKEND_META.update(saved)

    monkeypatch.setenv("AEP_LAST_RELOAD_ERROR", "stale-from-env")
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {"last_reload_error": None})
    assert server._get_live_meta()["last_reload_error"] is None
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {})
    assert server._get_live_meta()["last_reload_error"] == "stale-from-env"


def test_d18_front_does_not_propagate_reload_error_env() -> None:
    async def _run() -> None:
        from aep_front import LivePlaneManager

        mgr = LivePlaneManager()
        mgr.last_reload_error = "old error"
        os.environ["AEP_LAST_RELOAD_ERROR"] = "ambient"
        try:
            cand = await mgr._spawn_backend(1)
            try:
                h = await cand.send_request({"op": "health"}, timeout=20.0)
                assert h["status"] == "OK"
                from_env = await cand.send_request(
                    {"op": "call", "name": "discover", "args": {"action": "capabilities", "verbosity": "terse"}},
                    timeout=30.0,
                )
                payload = json.loads(from_env["result"]) if isinstance(from_env["result"], str) else from_env["result"]
                assert "old error" not in json.dumps(payload)
                assert "ambient" not in json.dumps(payload)
            finally:
                await cand.terminate()
        finally:
            os.environ.pop("AEP_LAST_RELOAD_ERROR", None)

    asyncio.run(_run())


def test_d19_broken_code_single_spawn_attempt() -> None:
    async def _run() -> None:
        with mutated_matcher() as (target, original):
            async with front_session() as session:
                d1 = await caps(session)
                assert d1.get("swap_attempts", 0) == 0

                await asyncio.sleep(DEBOUNCE_WAIT_S)
                target.write_text(original + "\n\ndef broken_syntax(:\n", encoding="utf-8")
                last: dict[str, Any] = {}
                for _ in range(6):
                    last = await caps(session)
                    await asyncio.sleep(DEBOUNCE_WAIT_S)
                assert last["backend_generation"] == 1
                assert last["last_reload_error"] is not None
                assert last["swap_attempts"] == 1
                assert last["failure_kind"] == "deterministic"

    asyncio.run(_run())


def test_d20a_quiescence_blocks_swap_while_files_change(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import aep_front

        monkeypatch.setenv("AEP_HOTSWAP_QUIESCE_MS", "40")
        monkeypatch.delenv("AEP_HOTSWAP_MODE", raising=False)
        monkeypatch.setenv("AEP_HOTSWAP", "1")
        monkeypatch.setattr(aep_front, "swap_fence_state", lambda: (False, False))
        monkeypatch.setenv("AEP_HOTSWAP_DEBOUNCE_S", "0")

        spawns: list[int] = []

        async def fake_spawn(self: Any, generation: int) -> Any:
            spawns.append(generation)
            raise RuntimeError("stub: no real backend")

        monkeypatch.setattr(aep_front.LivePlaneManager, "_spawn_backend", fake_spawn)

        # Unstable: every read differs (a multi-file edit in progress) -> never swaps.
        counter = {"n": 0}

        def unstable_fp(_root: Any = None) -> str:
            counter["n"] += 1
            return f"fp-{counter['n']}"

        monkeypatch.setattr(aep_front, "code_fingerprint", unstable_fp)
        mgr = aep_front.LivePlaneManager()
        mgr.active_fingerprint = "baseline"
        await mgr.check_and_swap_if_needed()
        assert spawns == []
        assert mgr.last_check_time == 0.0  # re-evaluated on the very next call

        # Stable across the quiescence window -> swap attempted (stub fails; recorded once).
        monkeypatch.setattr(aep_front, "code_fingerprint", lambda _root=None: "stable-new")
        t0 = time.monotonic()
        await mgr.check_and_swap_if_needed()
        assert time.monotonic() - t0 >= 0.04
        assert spawns == [2]
        assert mgr.swap_attempts == 1
        # spawn exception is transient: not pinned, retried with backoff
        assert mgr.failed_fingerprint == ""
        assert mgr.failure_kind == "transient"

    asyncio.run(_run())


def test_d20b_fence_blocks_swap_and_reports() -> None:
    async def _run() -> None:
        probe = PROJECT_ROOT / "engine" / "_ont39_probe_d20b.py"
        try:
            async with front_session() as session:
                d1 = await caps(session)
                assert d1["backend_generation"] == 1
                assert d1.get("swap_fenced", False) is False

                await asyncio.sleep(DEBOUNCE_WAIT_S)
                FENCE.write_text("agent multi-file edit\n", encoding="utf-8")
                probe.write_text("# d20b probe\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["backend_generation"] == 1
                assert d2["swap_fenced"] is True
                assert d2["stale"] is True  # honest

                await asyncio.sleep(DEBOUNCE_WAIT_S)
                FENCE.unlink()
                d3 = await caps(session)
                assert d3["backend_generation"] == 2
                assert d3.get("swap_fenced", False) is False
                assert d3["stale"] is False
        finally:
            FENCE.unlink(missing_ok=True)
            probe.unlink(missing_ok=True)

    asyncio.run(_run())


def test_d20b_orphan_fence_is_ignored_and_reported() -> None:
    async def _run() -> None:
        probe = PROJECT_ROOT / "engine" / "_ont39_probe_d20b_orphan.py"
        try:
            async with front_session() as session:
                await caps(session)
                await asyncio.sleep(DEBOUNCE_WAIT_S)
                FENCE.write_text("forgotten\n", encoding="utf-8")
                old = time.time() - 700
                os.utime(FENCE, (old, old))
                probe.write_text("# d20b orphan probe\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["backend_generation"] == 2
                assert d2.get("swap_fenced", False) is False
                assert d2["swap_fence_orphan"] is True
        finally:
            FENCE.unlink(missing_ok=True)
            probe.unlink(missing_ok=True)

    asyncio.run(_run())


def test_swap_fence_state_semantics() -> None:
    import aep_front

    FENCE.unlink(missing_ok=True)
    try:
        assert aep_front.swap_fence_state() == (False, False)
        FENCE.write_text("x", encoding="utf-8")
        assert aep_front.swap_fence_state() == (True, False)
        old = time.time() - 601
        os.utime(FENCE, (old, old))
        assert aep_front.swap_fence_state() == (False, True)
    finally:
        FENCE.unlink(missing_ok=True)


def test_fence_is_gitignored() -> None:
    assert ".aep_swap_fence" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_d21_fallback_fingerprint_matches_engine_implementation() -> None:
    import aep_front
    from engine.fingerprint import code_fingerprint as engine_fp

    assert aep_front._fallback_code_fingerprint(PROJECT_ROOT) == engine_fp(PROJECT_ROOT)
    assert aep_front._fallback_code_fingerprint() == engine_fp(PROJECT_ROOT)


def test_d21_front_starts_when_engine_fingerprint_is_broken() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(PROJECT_ROOT)!r}); sys.modules['engine.fingerprint'] = None\n"
        "import aep_front\n"
        "assert aep_front.code_fingerprint is aep_front._fallback_code_fingerprint\n"
        "from importlib import import_module\n"
        "sys.modules.pop('engine.fingerprint')\n"
        "ref = import_module('engine.fingerprint').code_fingerprint(aep_front.PROJECT_ROOT)\n"
        "assert aep_front.code_fingerprint(aep_front.PROJECT_ROOT) == ref\n"
        "print('OK')\n"
    )
    env = dict(os.environ)
    env.pop("AEP_HOTSWAP", None)
    res = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env, check=False
    )
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout


def test_d5_per_front_log_retention_and_dead_front_cleanup(tmp_path: Path) -> None:
    import aep_front

    own = os.getpid()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    dead.wait()
    dead_pid = dead.pid
    now = time.time()

    def mk(name: str, age_s: float) -> Path:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        os.utime(p, (now - age_s, now - age_s))
        return p

    own_logs = [mk(f"aep_backend_{own}_gen{i}.log", 100 - i) for i in range(1, 9)]
    dead_old = mk(f"aep_backend_{dead_pid}_gen1.log", 2 * 86400)
    dead_fresh = mk(f"aep_backend_{dead_pid}_gen2.log", 60)
    legacy_old = mk("aep_backend_gen3.log", 3 * 86400)
    other = mk("unrelated.log", 5 * 86400)

    aep_front._prune_backend_logs(tmp_path, front_pid=own, max_generations=5)

    survivors = {p.name for p in tmp_path.iterdir()}
    assert {p.name for p in own_logs[3:]} <= survivors  # newest 5 of own front kept
    assert not any(p.name in survivors for p in own_logs[:3])
    assert dead_old.name not in survivors
    assert legacy_old.name not in survivors
    assert dead_fresh.name in survivors
    assert other.name in survivors


def test_d5_backend_log_name_includes_front_pid() -> None:
    import aep_front

    assert aep_front._backend_log_path(4242, 7).name == "aep_backend_4242_gen7.log"


def test_d20b_fence_appearing_during_quiescence_aborts_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import aep_front

        monkeypatch.setenv("AEP_HOTSWAP_QUIESCE_MS", "10")
        monkeypatch.setenv("AEP_HOTSWAP_DEBOUNCE_S", "0")
        monkeypatch.delenv("AEP_HOTSWAP_MODE", raising=False)
        monkeypatch.setenv("AEP_HOTSWAP", "1")
        monkeypatch.setattr(aep_front, "code_fingerprint", lambda _root=None: "new-fp")

        calls = {"n": 0}

        def fence_after_first_read() -> tuple[bool, bool]:
            calls["n"] += 1
            return (calls["n"] >= 2), False  # absent at the initial check, present after the quiescence sleep

        monkeypatch.setattr(aep_front, "swap_fence_state", fence_after_first_read)
        spawns: list[int] = []

        async def fake_spawn(self: Any, generation: int) -> Any:
            spawns.append(generation)
            raise RuntimeError("must not be reached")

        monkeypatch.setattr(aep_front.LivePlaneManager, "_spawn_backend", fake_spawn)
        mgr = aep_front.LivePlaneManager()
        mgr.active_fingerprint = "old-fp"
        await mgr.check_and_swap_if_needed()
        assert spawns == []
        assert mgr.swap_fenced is True
        assert mgr.swap_attempts == 0

    asyncio.run(_run())


def test_d20b_fence_appearing_before_promotion_terminates_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import aep_front

        monkeypatch.setenv("AEP_HOTSWAP_QUIESCE_MS", "0")
        monkeypatch.setenv("AEP_HOTSWAP_DEBOUNCE_S", "0")
        monkeypatch.delenv("AEP_HOTSWAP_MODE", raising=False)
        monkeypatch.setenv("AEP_HOTSWAP", "1")
        monkeypatch.setattr(aep_front, "code_fingerprint", lambda _root=None: "new-fp")

        calls = {"n": 0}

        def fence_before_promotion() -> tuple[bool, bool]:
            calls["n"] += 1
            return (calls["n"] >= 3), False  # initial, post-lock: absent; pre-promotion: present

        monkeypatch.setattr(aep_front, "swap_fence_state", fence_before_promotion)

        class FakeCandidate:
            terminated = False

            async def send_request(self, req: dict[str, Any], timeout: float = 0) -> dict[str, Any]:
                return {"status": "OK", "instructions": "", "tools": [], "schema_hash": "h"}

            async def terminate(self) -> None:
                FakeCandidate.terminated = True

        async def fake_spawn(self: Any, generation: int) -> Any:
            return FakeCandidate()

        monkeypatch.setattr(aep_front.LivePlaneManager, "_spawn_backend", fake_spawn)
        mgr = aep_front.LivePlaneManager()
        mgr.active_fingerprint = "old-fp"
        await mgr.check_and_swap_if_needed()
        assert FakeCandidate.terminated is True
        assert mgr.active_conn is None
        assert mgr.generation == 1
        assert mgr.active_fingerprint == "old-fp"
        assert mgr.swap_fenced is True
        assert mgr.failed_fingerprint == ""

    asyncio.run(_run())


def test_d19_transient_failure_does_not_pin_fingerprint_and_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import aep_front

        monkeypatch.setenv("AEP_HOTSWAP_QUIESCE_MS", "0")
        monkeypatch.setenv("AEP_HOTSWAP_DEBOUNCE_S", "0")
        monkeypatch.delenv("AEP_HOTSWAP_MODE", raising=False)
        monkeypatch.setenv("AEP_HOTSWAP", "1")
        monkeypatch.setattr(aep_front, "code_fingerprint", lambda _root=None: "new-fp")
        monkeypatch.setattr(aep_front, "swap_fence_state", lambda: (False, False))
        spawns: list[int] = []

        async def fake_spawn(self: Any, generation: int) -> Any:
            spawns.append(generation)
            raise OSError("transient spawn failure")

        monkeypatch.setattr(aep_front.LivePlaneManager, "_spawn_backend", fake_spawn)
        assert [aep_front.transient_backoff_seconds(n) for n in (1, 2, 3)] == [1.0, 2.0, 4.0]

        mgr = aep_front.LivePlaneManager()
        mgr.active_fingerprint = "old-fp"
        await mgr.check_and_swap_if_needed()
        assert len(spawns) == 1 and mgr.failed_fingerprint == "" and mgr.failure_kind == "transient"
        assert str(mgr.last_reload_error).startswith("[transient]")

        # Inside the backoff window: no new attempt.
        await mgr.check_and_swap_if_needed()
        assert len(spawns) == 1
        assert mgr.next_retry_at > time.monotonic()

        # Backoff elapsed: retry; after the 3rd transient failure the fingerprint is pinned.
        for expected in (2, 3):
            mgr.next_retry_at = 0.0
            await mgr.check_and_swap_if_needed()
            assert len(spawns) == expected
        assert mgr.failed_fingerprint == "new-fp"
        mgr.next_retry_at = 0.0
        await mgr.check_and_swap_if_needed()
        assert len(spawns) == 3  # capped

    asyncio.run(_run())


def test_d19_transient_health_timeout_e2e_retries_with_backoff() -> None:
    async def _run() -> None:
        probe = PROJECT_ROOT / "engine" / "_ont39_probe_transient.py"
        try:
            async with front_session(
                {"AEP_TEST_HEALTH_DELAY_S": "3", "AEP_HOTSWAP_HEALTH_TIMEOUT_S": "0.4"}
            ) as session:
                d1 = await caps(session)
                assert d1["backend_generation"] == 1
                probe.write_text("# transient probe\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["backend_generation"] == 1
                assert d2["failure_kind"] == "transient"
                assert d2["swap_attempts"] == 1
                # Immediately again: still inside the 1 s backoff window -> no new attempt.
                d3 = await caps(session)
                assert d3["swap_attempts"] == 1
                await asyncio.sleep(1.1)
                d4 = await caps(session)
                assert d4["swap_attempts"] == 2
                assert d4["failure_kind"] == "transient"
        finally:
            probe.unlink(missing_ok=True)

    asyncio.run(_run())


def test_spawn_failure_releases_fds_and_child(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import aep_front

        mgr = aep_front.LivePlaneManager()
        procs: list[subprocess.Popen[Any]] = []
        real_popen = subprocess.Popen

        def recording_popen(*a: Any, **kw: Any) -> Any:
            p = real_popen(*a, **kw)
            procs.append(p)
            return p

        async def failing_initialize(self: Any) -> None:
            raise RuntimeError("initialize failed")

        monkeypatch.setattr(aep_front.subprocess, "Popen", recording_popen)
        monkeypatch.setattr(aep_front.BackendConnection, "initialize", failing_initialize)
        before = set(os.listdir("/proc/self/fd"))
        with pytest.raises(RuntimeError, match="initialize failed"):
            await mgr._spawn_backend(1)
        assert procs and procs[0].poll() is not None
        # listdir itself opens a transient fd; compare the sets minus that one.
        after = set(os.listdir("/proc/self/fd"))
        assert len(after - before) <= 0

        def failing_popen(*a: Any, **kw: Any) -> Any:
            raise OSError("popen failed")

        monkeypatch.setattr(aep_front.subprocess, "Popen", failing_popen)
        with pytest.raises(OSError, match="popen failed"):
            await mgr._spawn_backend(1)
        assert len(set(os.listdir("/proc/self/fd")) - before) <= 0

    asyncio.run(_run())


def test_d22_real_fence_untouched_and_isolated_tests_unaffected(tmp_path: Path) -> None:
    """With a real fence present, an isolated front still swaps and the real fence is never modified."""
    import aep_front

    existed = REAL_FENCE.exists()
    if not existed:
        REAL_FENCE.write_text("d22 regression sentinel\n", encoding="utf-8")
    before = (REAL_FENCE.read_bytes(), REAL_FENCE.stat().st_mtime_ns)
    probe = PROJECT_ROOT / "engine" / "_ont39_probe_d22.py"
    try:
        # in-process semantics follow the isolated path, not the real fence
        assert aep_front.swap_fence_path() == FENCE
        assert aep_front.swap_fence_state() == (False, False)

        async def _run() -> None:
            async with front_session() as session:
                d1 = await caps(session)
                assert d1.get("swap_fenced", False) is False
                await asyncio.sleep(DEBOUNCE_WAIT_S)
                FENCE.write_text("isolated\n", encoding="utf-8")
                probe.write_text("# d22 probe\n", encoding="utf-8")
                d2 = await caps(session)
                assert d2["swap_fenced"] is True and d2["backend_generation"] == 1
                FENCE.unlink()
                d3 = await caps(session)
                assert d3["backend_generation"] == 2 and d3["stale"] is False

        asyncio.run(_run())
        assert (REAL_FENCE.read_bytes(), REAL_FENCE.stat().st_mtime_ns) == before
    finally:
        probe.unlink(missing_ok=True)
        if not existed:
            REAL_FENCE.unlink(missing_ok=True)


def test_d22_default_fence_path_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import aep_front

    monkeypatch.delenv("AEP_SWAP_FENCE_PATH", raising=False)
    assert aep_front.swap_fence_path() == REAL_FENCE
