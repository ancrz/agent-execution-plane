"""ONT-41 TC1: front (N0 structured error, N1 LKG save, N2 crash window + LKG fallback, reload barrier,
plane_events spool and per-pid state file).

Tests run against a COPY of the code tree (`PROJECT_ROOT` patched / front launched from the copy), with
AEP_SWAP_FENCE_PATH / AEP_DATA_HOME / AEP_FRONT_STATE_DIR / AEP_FRONT_SPOOL_DIR isolated by conftest, and a
fake clock for the N2 window and barrier timeouts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import aep_front
import aep_lkg

REPO = Path(__file__).resolve().parent.parent
BROKEN = "\n\ndef broken_syntax(:\n"


def make_tree(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", ".git", ".venv", "tests", "docs", ".claude", "*.pyc")
    dest.mkdir(parents=True)
    for name in ("aep_front.py", "aep_backend.py", "aep_lkg.py", "server.py", "pyproject.toml"):
        shutil.copy2(REPO / name, dest / name)
    for sub in ("engine", "schemas", "templates", "scripts", "config"):
        if (REPO / sub).is_dir():
            shutil.copytree(REPO / sub, dest / sub, ignore=ignore)
    return dest


class FakeClock:
    """Monotonic fake: `sleep` records the request and advances time instantly."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def reap_backends_of(root: Path) -> int:
    """F6/L3: termina los `aep_backend.py` cuyo script cuelga de el directorio padre de `root` (el tmp_path del test; incluye arboles LKG).

    SIGTERM, y SIGKILL tras 2 s: los huerfanos ignoran SIGTERM.
    """
    prefix = str(root.parent)
    me = os.getpid()
    victims: list[int] = []
    reaped = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if not any(a.startswith(prefix.encode()) and a.endswith(b"/aep_backend.py") for a in argv):
            continue
        with contextlib.suppress(OSError):
            os.kill(int(entry.name), signal.SIGTERM)
            victims.append(int(entry.name))
            reaped += 1
    deadline = time.monotonic() + 2.0
    while victims and time.monotonic() < deadline:
        victims = [p for p in victims if Path(f"/proc/{p}").exists() and not _is_zombie(p)]
        if victims:
            time.sleep(0.05)
    for pid in victims:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    return reaped


def _is_zombie(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
    except (OSError, IndexError):
        return True


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = make_tree(tmp_path / "repo")
    monkeypatch.setattr(aep_front, "PROJECT_ROOT", root)
    monkeypatch.setenv("AEP_HOTSWAP_DEBOUNCE_S", "0")
    monkeypatch.setenv("AEP_HOTSWAP_QUIESCE_MS", "0")
    monkeypatch.delenv("AEP_HOTSWAP_MODE", raising=False)
    try:
        yield root
    finally:
        reap_backends_of(root)


def new_mgr(clock: FakeClock | None = None) -> aep_front.LivePlaneManager:
    clock = clock or FakeClock()
    return aep_front.LivePlaneManager(clock=clock, sleep=clock.sleep)


def kill_backend(mgr: aep_front.LivePlaneManager) -> None:
    assert mgr.active_conn is not None
    os.kill(mgr.active_conn.proc.pid, signal.SIGKILL)
    mgr.active_conn.proc.wait()


def break_disk(root: Path) -> Path:
    target = root / "engine" / "matcher.py"
    target.write_text(target.read_text(encoding="utf-8") + BROKEN, encoding="utf-8")
    return target


def read_state() -> dict[str, Any]:
    directory, private = aep_front.state_dir_path()
    files = sorted(directory.glob("aep_front_*.json"))
    assert files, "front state file missing"
    data = aep_front.read_state_file(directory, private, files[-1].name)
    assert data is not None
    return data


async def tool_ok(mgr: aep_front.LivePlaneManager) -> dict[str, Any]:
    raw = await mgr.call_tool("topos_audit_dag", {"tasks": ["a", "b"]})
    return json.loads(raw)


# ---------------------------------------------------------------------------
# N1: LKG saved after healthy Gen-1 and after each promotion
# ---------------------------------------------------------------------------


def test_n1_lkg_saved_after_gen1_health_and_after_promotion(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            keys1 = [e["key"] for e in aep_lkg.list_keys()]
            assert len(keys1) == 1 and mgr.lkg_key == keys1[0]
            assert aep_lkg.verify(keys1[0])["ok"]
            (tree / "engine" / "_probe_n1.py").write_text("X = 1\n", encoding="utf-8")
            await mgr.check_and_swap_if_needed()
            assert mgr.generation == 2 and not mgr.serving_lkg
            keys2 = [e["key"] for e in aep_lkg.list_keys()]
            assert len(keys2) == 2 and mgr.lkg_key == aep_lkg.latest()
            assert state_serving_from() == "disk"
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def state_serving_from() -> str:
    return str(read_state()["serving_from"])


def test_n1_failed_swap_does_not_save_lkg(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            before = [e["key"] for e in aep_lkg.list_keys()]
            break_disk(tree)
            await mgr.check_and_swap_if_needed()
            assert mgr.generation == 1 and mgr.failure_kind == "deterministic"
            assert [e["key"] for e in aep_lkg.list_keys()] == before
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# N0: structured reload error (free text is preserved)
# ---------------------------------------------------------------------------


def test_n0_structured_reload_error_keeps_free_text(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            target = break_disk(tree)
            await mgr.check_and_swap_if_needed()
            assert "SyntaxError" in str(mgr.last_reload_error)
            struct = mgr.last_reload_error_struct
            assert struct is not None and struct["type"] == "SyntaxError"
            assert struct["file"].endswith("matcher.py") and struct["line"] > 0
            assert struct == aep_lkg.parse_error(aep_front._read_backend_log_tail(2))
            meta = mgr._live_meta("auto")
            assert meta["last_reload_error_struct"] == struct and meta["last_reload_error"]
            # Revert: both forms clear together.
            target.write_text(target.read_text(encoding="utf-8").replace(BROKEN, ""), encoding="utf-8")
            await mgr.check_and_swap_if_needed()
            assert mgr.last_reload_error is None and mgr.last_reload_error_struct is None
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# N2: crash window, backoff, LKG fallback, recovery
# ---------------------------------------------------------------------------


def test_n2_three_drops_in_window_serve_lkg_with_backoff_1_2(tree: Path) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        try:
            await mgr.get_or_start_backend()
            lkg = mgr.lkg_key
            for _ in range(3):
                kill_backend(mgr)
                clock.t += 5.0
                await mgr.get_or_start_backend()
            assert mgr.serving_lkg and mgr.lkg_key == lkg
            assert clock.sleeps == [1.0, 2.0]
            assert mgr._live_meta("auto")["serving_from"] == "lkg"
            assert mgr._live_meta("auto")["failure_kind"] == "SERVING_LKG"
            assert "verdict" in await tool_ok(mgr)
            st = read_state()
            assert st["serving_from"] == "lkg" and st["lkg_key"] == lkg
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_n2_drops_outside_window_never_reach_lkg(tree: Path) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        try:
            await mgr.get_or_start_backend()
            for _ in range(4):
                kill_backend(mgr)
                clock.t += 61.0
                await mgr.get_or_start_backend()
            assert not mgr.serving_lkg
            assert clock.sleeps == [1.0, 1.0, 1.0, 1.0]
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_n2_lkg_then_fixed_disk_promotes_and_clears_serving_from(tree: Path) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        try:
            await mgr.get_or_start_backend()
            for _ in range(3):
                kill_backend(mgr)
                await mgr.get_or_start_backend()
            assert mgr.serving_lkg
            pinned = mgr.failed_fingerprint
            assert pinned
            # Same (pinned) disk: no promotion attempt.
            await mgr.check_and_swap_if_needed()
            assert mgr.serving_lkg and mgr.swap_attempts == 0
            # Disk changes: candidate from disk is promoted, counter restarts.
            (tree / "engine" / "_probe_fix.py").write_text("X = 2\n", encoding="utf-8")
            await mgr.check_and_swap_if_needed()
            assert not mgr.serving_lkg and mgr.drops == []
            meta = mgr._live_meta("auto")
            assert meta["serving_from"] is None and meta["failure_kind"] is None
            assert read_state()["serving_from"] == "disk"
            assert "verdict" in await tool_ok(mgr)
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_n2_cold_broken_disk_serves_lkg_then_recovers(tree: Path) -> None:
    async def _run() -> None:
        first = new_mgr()
        try:
            await first.get_or_start_backend()
        finally:
            await first.shutdown()
        target = break_disk(tree)
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            assert mgr.serving_lkg and mgr.failure_kind == "deterministic"
            assert aep_lkg.verify(str(mgr.lkg_key))["ok"]  # serving must not dirty the hash-verified snapshot
            assert mgr.last_reload_error_struct and mgr.last_reload_error_struct["type"] == "SyntaxError"
            assert "verdict" in await tool_ok(mgr)
            # Still broken: pinned, no retry loop.
            await mgr.check_and_swap_if_needed()
            assert mgr.swap_attempts == 0 and mgr.serving_lkg
            target.write_text(target.read_text(encoding="utf-8").replace(BROKEN, ""), encoding="utf-8")
            await mgr.check_and_swap_if_needed()
            assert not mgr.serving_lkg and mgr.last_reload_error is None
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_n2_no_lkg_available_raises_like_before(tree: Path) -> None:
    async def _run() -> None:
        break_disk(tree)
        mgr = new_mgr()
        with pytest.raises(RuntimeError, match="health failed"):
            await mgr.get_or_start_backend()
        assert not mgr.serving_lkg and mgr.failure_kind == "deterministic"

    asyncio.run(_run())


def test_n2_schema_hash_change_sends_list_changed(tree: Path) -> None:
    async def _run() -> None:
        notified = asyncio.Event()

        class Session:
            async def send_tool_list_changed(self) -> None:
                notified.set()

        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            mgr.cached_session = Session()  # type: ignore[assignment]
            for _ in range(2):
                kill_backend(mgr)
                await mgr.get_or_start_backend()
            mgr.active_schema_hash = "an-older-schema-hash"  # what the clients last saw
            kill_backend(mgr)
            await mgr.get_or_start_backend()
            assert mgr.serving_lkg and notified.is_set()
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_lkg_module_drift_reported_in_meta(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            assert mgr._live_meta("auto")["lkg_module_drift"] is False
            monkeypatch.setattr(aep_lkg, "LKG_MODULE_HASH", "0" * 64)
            for _ in range(3):
                kill_backend(mgr)
                await mgr.get_or_start_backend()
            assert mgr.serving_lkg and mgr._live_meta("auto")["lkg_module_drift"] is True
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_aep_lkg_import_failure_degrades_to_lkg_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as m:
        m.setattr(aep_front, "aep_lkg", None)
        probe = new_mgr()
        assert probe._effective_failure_kind() == "LKG_UNAVAILABLE"
        assert probe._live_meta("auto")["lkg_module_drift"] is False
    code = (
        "import sys, json, asyncio\n"
        "sys.modules['aep_lkg'] = None\n"
        "import aep_front\n"
        "assert aep_front.aep_lkg is None\n"
        "async def go():\n"
        "    m = aep_front.LivePlaneManager()\n"
        "    try:\n"
        "        await m.get_or_start_backend()\n"
        "        raw = await m.call_tool('topos_audit_dag', {'tasks': ['a']})\n"
        "        print(json.dumps({'kind': m._live_meta('auto')['failure_kind'], 'ok': 'verdict' in raw,\n"
        "                          'lkg': m.lkg_key}))\n"
        "    finally:\n"
        "        await m.shutdown()\n"
        "asyncio.run(go())\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert res.returncode == 0, res.stderr[-1500:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out == {"kind": "LKG_UNAVAILABLE", "ok": True, "lkg": None}
    assert not list(Path(os.environ["AEP_DATA_HOME"]).glob("lkg/*/manifest.json"))


# ---------------------------------------------------------------------------
# Reload barrier: one test per branch
# ---------------------------------------------------------------------------


def test_barrier_ok_when_disk_equals_served(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_OK" and b["from_lkg"] is False and b["error"] is None
            assert b["served_fingerprint"] == b["disk_fingerprint"]
            assert set(b) == {"state", "reason", "retry_after_s", "error", "served_fingerprint", "disk_fingerprint", "from_lkg"}
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_forces_check_and_swaps_before_verdict(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            (tree / "engine" / "_probe_barrier.py").write_text("X = 3\n", encoding="utf-8")
            mgr.last_check_time = 10**12  # a recent check must not suppress the forced one
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_OK" and mgr.generation == 2
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_pending_when_fenced_until_timeout(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        monkeypatch.setenv("AEP_RELOAD_BARRIER_S", "3")
        try:
            await mgr.get_or_start_backend()
            (tree / "engine" / "_probe_fence.py").write_text("X = 4\n", encoding="utf-8")
            Path(os.environ["AEP_SWAP_FENCE_PATH"]).write_text("", encoding="utf-8")
            t0 = clock.t
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_PENDING" and b["reason"] == "fenced"
            assert clock.t - t0 >= 3.0 and mgr.generation == 1
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_pending_backoff_reports_retry_after(tree: Path) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        try:
            await mgr.get_or_start_backend()
            (tree / "engine" / "_probe_backoff.py").write_text("X = 5\n", encoding="utf-8")
            mgr.transient_fp = aep_front.code_fingerprint(tree)
            mgr.next_retry_at = clock.t + 4.0
            state = mgr.compute_barrier()
            assert state["state"] == "RELOAD_PENDING" and state["reason"] == "backoff"
            assert state["retry_after_s"] == pytest.approx(4.0)
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_pending_resolves_when_backoff_elapses(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        monkeypatch.setenv("AEP_RELOAD_BARRIER_S", "15")
        try:
            await mgr.get_or_start_backend()
            (tree / "engine" / "_probe_backoff2.py").write_text("X = 6\n", encoding="utf-8")
            mgr.transient_fp = aep_front.code_fingerprint(tree)
            mgr.next_retry_at = clock.t + 2.0
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_OK" and mgr.generation == 2
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_failed_on_pinned_deterministic_error(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            break_disk(tree)
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_FAILED" and b["reason"] == "deterministic"
            assert "SyntaxError" in str(b["error"]) and b["from_lkg"] is False
            assert b["served_fingerprint"] != b["disk_fingerprint"]
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_serving_lkg(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            for _ in range(3):
                kill_backend(mgr)
                await mgr.get_or_start_backend()
            b = await mgr.settle_barrier()
            assert b["state"] == "SERVING_LKG" and b["from_lkg"] is True
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_watch_mode_is_pending_without_waiting(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        clock = FakeClock()
        mgr = new_mgr(clock)
        try:
            await mgr.get_or_start_backend()
            monkeypatch.setenv("AEP_HOTSWAP_MODE", "watch")
            (tree / "engine" / "_probe_watch.py").write_text("X = 7\n", encoding="utf-8")
            t0 = clock.t
            b = await mgr.settle_barrier()
            assert b["state"] == "RELOAD_PENDING" and b["reason"] == "watch_mode"
            assert clock.t == t0
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_barrier_injected_only_for_autoevol_verify_and_client_value_is_discarded(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            conn = await mgr.get_or_start_backend()
            seen: list[dict[str, Any]] = []
            real = conn.send_request

            async def spy(req: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
                if req.get("op") == "call":
                    seen.append(dict(req["args"]))
                return await real(req, timeout=timeout)

            conn.send_request = spy  # type: ignore[method-assign]
            await mgr.call_tool("autoevol", {"action": "verify", "_barrier": {"state": "RELOAD_OK", "spoof": True}})
            await mgr.call_tool("autoevol", {"action": "graph"})
            await mgr.call_tool("discover", {"action": "capabilities", "verbosity": "terse", "_barrier": {"x": 1}})
            assert seen[0]["_barrier"]["state"] == "RELOAD_OK" and "spoof" not in seen[0]["_barrier"]
            assert seen[0]["_barrier"]["disk_fingerprint"]
            assert "_barrier" not in seen[1] and "_barrier" not in seen[2]
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


def test_backend_strips_barrier_and_exposes_it_via_contextvar(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            conn = await mgr.get_or_start_backend()
            barrier = {"state": "RELOAD_OK", "reason": ""}
            resp = await conn.send_request(
                {"op": "call", "name": "topos_audit_dag", "args": {"tasks": ["a"], "_barrier": barrier}}, timeout=30.0
            )
            assert resp["status"] == "OK"  # `_barrier` never reaches the tool signature
            import server

            assert server.get_reload_barrier() is None  # nothing leaks into the front process
            token = server._BARRIER_CTX.set(barrier)
            try:
                assert server.get_reload_barrier() == barrier
            finally:
                server._BARRIER_CTX.reset(token)
            bad = await conn.send_request(
                {"op": "call", "name": "topos_audit_dag", "args": {"tasks": ["a"], "_barrier": {"state": "BOGUS"}}},
                timeout=30.0,
            )
            assert bad["status"] == "OK"
        finally:
            await mgr.shutdown()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Spool + state file: permissions and limits
# ---------------------------------------------------------------------------


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_spool_permissions_and_events(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            (tree / "engine" / "_probe_spool.py").write_text("X = 8\n", encoding="utf-8")
            await mgr.check_and_swap_if_needed()
        finally:
            await mgr.shutdown()

    asyncio.run(_run())
    spool_dir = aep_front.spool_dir_path()
    log = spool_dir / f"plane_events_{os.geteuid()}.jsonl"
    assert mode_of(spool_dir) == 0o700 and mode_of(log) == 0o600
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    kinds = [x["kind"] for x in lines]
    assert "LKG_SAVED" in kinds and "PROMOTED" in kinds
    assert all(x["nonce"] and x["ts"] and x["pid"] == os.getpid() for x in lines)
    assert len({x["nonce"] for x in lines}) == len(lines)


def test_state_file_permissions_atomicity_and_removal_on_shutdown(tree: Path) -> None:
    async def _run() -> None:
        mgr = new_mgr()
        await mgr.get_or_start_backend()
        directory, _private = aep_front.state_dir_path()
        path = directory / aep_front.state_file_name()
        assert mode_of(directory) == 0o700 and mode_of(path) == 0o600
        assert not list(directory.glob(".*.tmp"))
        st = read_state()
        assert st["pid"] == os.getpid() and st["serving_from"] == "disk" and st["generation"] == 1
        await mgr.shutdown()
        assert not path.exists()

    asyncio.run(_run())


def test_state_default_dir_is_dev_shm_with_0600(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEP_FRONT_STATE_DIR", raising=False)
    directory, private = aep_front.state_dir_path()
    assert directory == Path("/dev/shm") and private is False
    name = f"aep_front_test_{os.getpid()}.json"
    try:
        aep_front.write_state_file(directory, private, name, {"pid": 1})
        assert mode_of(directory / name) == 0o600
        assert aep_front.read_state_file(directory, private, name) == {"pid": 1}
    finally:
        aep_front.remove_state_file(directory, private, name)
    assert not (directory / name).exists()


def test_state_and_spool_refuse_symlinks_and_oversize(tmp_path: Path) -> None:
    d = tmp_path / "st"
    d.mkdir(mode=0o700)
    secret = tmp_path / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    (d / "aep_front_1.json").symlink_to(secret)
    with pytest.raises(aep_front.FrontFileError):
        aep_front.read_state_file(d, True, "aep_front_1.json")
    (d / "big.json").write_text("{" + " " * (aep_front.STATE_MAX_BYTES + 10) + "}", encoding="utf-8")
    with pytest.raises(aep_front.FrontFileError):
        aep_front.read_state_file(d, True, "big.json")
    with pytest.raises(aep_front.FrontFileError):
        aep_front.write_state_file(d, True, "x.json", {"k": "v" * (aep_front.STATE_MAX_BYTES + 1)})
    # Spool: a planted symlink at the log name is never followed.
    sp = tmp_path / "spool"
    sp.mkdir(mode=0o700)
    spool = aep_front.PlaneEventSpool(sp, uid=os.geteuid())
    (sp / spool.name).symlink_to(secret)
    with pytest.raises(aep_front.FrontFileError):
        spool.append("X")
    assert secret.read_text(encoding="utf-8") == "{}"
    # A loose directory mode is tightened.
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    aep_front.PlaneEventSpool(loose, uid=1).append("X")
    assert mode_of(loose) == 0o700


def test_spool_rotation_and_line_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aep_front, "SPOOL_MAX_LINES", 5)
    spool = aep_front.PlaneEventSpool(tmp_path / "sp", uid=7)
    for i in range(7):
        spool.append("E", i=i)
    main = tmp_path / "sp" / spool.name
    rotated = tmp_path / "sp" / (spool.name + ".1")
    assert rotated.is_file() and len(main.read_text().splitlines()) == 2
    assert mode_of(main) == 0o600 and mode_of(rotated) == 0o600
    big = aep_front.PlaneEventSpool(tmp_path / "sp2", uid=7)
    big.append("E", blob="x" * 100_000)
    line = (tmp_path / "sp2" / big.name).read_text().splitlines()[0]
    assert len(line) <= aep_front.SPOOL_MAX_LINE_BYTES and len(json.loads(line).get("blob", "")) <= 512


# ---------------------------------------------------------------------------
# Real front process (stdio): cold broken disk -> LKG, tools work, fix -> disk
# ---------------------------------------------------------------------------


def _front_params(root: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env.update({"AEP_HOTSWAP_DEBOUNCE_S": "0", "AEP_HOTSWAP_QUIESCE_MS": "0"})
    env.pop("AEP_HOTSWAP", None)
    env.pop("AEP_HOTSWAP_MODE", None)
    return StdioServerParameters(command=sys.executable, args=[str(root / "aep_front.py")], env=env)


def test_front_process_cold_broken_disk_serves_lkg_and_recovers(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "repo")

    async def _session(check: Any) -> Any:
        async with stdio_client(_front_params(root)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await check(session)

    async def _first(session: ClientSession) -> None:
        res = await session.call_tool("topos_audit_dag", {"tasks": ["a"]})
        assert "verdict" in res.content[0].text

    asyncio.run(_session(_first))
    assert aep_lkg.latest() is not None
    target = break_disk(root)

    async def _second(session: ClientSession) -> None:
        res = await session.call_tool("topos_audit_dag", {"tasks": ["a", "b"]})
        assert "verdict" in res.content[0].text
        st = read_state()
        assert st["serving_from"] == "lkg" and st["failure_kind"] == "SERVING_LKG"
        assert st["lkg_key"] == aep_lkg.latest()
        target.write_text(target.read_text(encoding="utf-8").replace(BROKEN, ""), encoding="utf-8")
        res = await session.call_tool("topos_audit_dag", {"tasks": ["a"]})
        assert "verdict" in res.content[0].text
        assert read_state()["serving_from"] == "disk"

    asyncio.run(_session(_second))


def test_reap_backends_of_terminates_only_backends_of_its_own_tree(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """F6: el teardown mata el backend huerfano de su arbol y no toca procesos ajenos."""
    assert aep_front.state_dir_path()  # ancla el test al grafo de hilos (covers)
    own = tmp_path / "repo"
    own.mkdir()
    (own / "aep_backend.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    other = tmp_path_factory.mktemp("foreign_tree")  # fuera del tmp_path de este test: el reaper cubre todo tmp_path
    (other / "aep_backend.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    mine = subprocess.Popen([sys.executable, str(own / "aep_backend.py")])  # noqa: S603
    foreign = subprocess.Popen([sys.executable, str(other / "aep_backend.py")])  # noqa: S603
    try:
        assert reap_backends_of(own) == 1
        assert mine.wait(timeout=10) == -signal.SIGTERM
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait()
        if mine.poll() is None:
            mine.kill()
            mine.wait()
