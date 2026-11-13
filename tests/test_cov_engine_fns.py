"""Cobertura conductual de funciones de engine/server/front/backend y de las tools kernel_trace / visual_inspect.

Sin mutar el host: bases en tmp, socket Unix en tmp, tier forzado para kernel_trace (nunca se ejecuta bpftrace)
y screenshot en tmp (SHM_DIR redirigido).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Awaitable, Iterator
from pathlib import Path
from typing import Any

import pytest

import aep_backend
import aep_front
import server
from engine import headless_display
from engine.catalog import ArtifactCatalog
from engine.crash_router import CrashRouter
from engine.db import create_in_memory_clone
from engine.docs_vectorizer import CURATED_COMMANDS, ManPagesVectorizer
from engine.ipc_pool import SessionPool, UnixSocketMux
from engine.playbook import PlaybookStore
from engine.privilege import _PrivilegeCache


def _j(coro: Awaitable[str]) -> dict[str, Any]:
    async def _await() -> str:
        return await coro

    data = json.loads(asyncio.run(_await()))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def forced_tier(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("AEP_FORCE_TIER", "5r-x")
    _PrivilegeCache.reset()
    yield "5r-x"
    _PrivilegeCache.reset()


# --------------------------------------------------------------------------- kernel_trace (sin bpftrace)
def test_kernel_trace_syscall_count_degrades_without_root(forced_tier: str) -> None:
    res = _j(server.kernel_trace(mode="syscall_count", duration_sec=1))
    assert res["status"] == "DEGRADED" and res["capability_tier"] == "DIMINISHED"
    assert "bpftrace" in res["message"]
    alias = _j(server.kernel_trace(mode="syscalls"))  # el alias resuelve al mismo modo
    assert alias["status"] == "DEGRADED"


def test_kernel_trace_rejects_unknown_mode_with_valid_list(forced_tier: str) -> None:
    res = _j(server.kernel_trace(mode="not_a_mode"))
    assert res["status"] == "INVALID_MODE"
    assert "syscall_count" in res["valid_modes"]
    assert set(res["valid_modes"]) == set(server._BPFTRACE_MODES)


# --------------------------------------------------------------------------- visual_inspect
def test_visual_inspect_renders_local_file_or_reports_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(headless_display, "SHM_DIR", tmp_path)
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>Cov Page</title></head><body><h1>hello aep</h1></body></html>")
    res = _j(server.visual_inspect(url=page.as_uri(), viewport_width=320, viewport_height=240, verbosity="detail"))
    if res["status"] == "DISPLAY_UNAVAILABLE":
        assert res["message"]  # envelope estructurado fail-soft cuando falta Chromium/Playwright
        return
    assert res["status"] == "SUCCESS"
    assert res["title"] == "Cov Page" and "hello aep" in res["text_excerpt"]
    shot = Path(res["screenshot_path"])
    assert shot.parent == tmp_path and shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert res["screenshot_bytes"] == shot.stat().st_size


# --------------------------------------------------------------------------- engine.catalog
def test_catalog_builtin_primitive_list_and_prune_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # prune(apply) borra bin bajo $HOME
    cat = ArtifactCatalog(db_path=tmp_path / "cat.db")
    assert ArtifactCatalog.is_builtin_primitive("socket-monitor") is True
    assert ArtifactCatalog.is_builtin_primitive("not-a-primitive") is False
    for nm in ("keep_me", "drop_me", "template_base"):
        cat.register_artifact(name=nm, intent=nm, category="cov", cue_contract="{}", go_source="package main")
    with cat._get_rw_conn() as conn:
        conn.execute("UPDATE artifacts SET reusable=0 WHERE name IN ('drop_me','template_base')")
    listed = ArtifactCatalog.list_artifacts(cat, category="cov")
    assert sorted(a["name"] for a in listed) == ["drop_me", "keep_me", "template_base"]
    assert all(a["artifact_type"] == "synthesized" for a in listed)

    dry = ArtifactCatalog.prune(cat, protect={"template_base"})
    assert dry["status"] == "DRY_RUN" and [c["name"] for c in dry["candidates"]] == ["drop_me"]
    done = ArtifactCatalog.prune(cat, protect={"template_base"}, apply=True)
    assert done["status"] == "PRUNED" and done["removed"] == ["drop_me"]
    assert sorted(a["name"] for a in ArtifactCatalog.list_artifacts(cat)) == ["keep_me", "template_base"]


# --------------------------------------------------------------------------- engine.playbook
def test_playbook_store_get_list_prune(tmp_path: Path) -> None:
    store = PlaybookStore(db_path=tmp_path / "pb.db")
    steps = [{"id": "a", "tool": "discover"}, {"id": "b", "tool": "process_inspect", "depends_on": ["a"]}]
    assert store.create("pb1", "first", steps)["order"] == ["a", "b"]
    assert PlaybookStore.get(store, "missing") is None
    got = PlaybookStore.get(store, "pb1")
    assert got is not None and [s["id"] for s in got["steps"]] == ["a", "b"] and got["steps"][1]["depends_on"] == ["a"]
    for _ in range(3):
        store.record_run("pb1", False)
    row = PlaybookStore.list(store)[0]
    assert row["name"] == "pb1" and row["n_steps"] == 2 and row["run_count"] == 3 and row["success_count"] == 0
    assert row["weighting"]["verdict"] != "TRUST"
    dry = PlaybookStore.prune(store)
    assert dry["status"] == "DRY_RUN" and dry["candidates"][0]["success_rate"] == 0.0
    assert PlaybookStore.prune(store, apply=True)["removed"] == ["pb1"]
    assert PlaybookStore.list(store) == []


# --------------------------------------------------------------------------- engine.ipc_pool
def test_session_pool_status_tracks_leases(tmp_path: Path) -> None:
    pool = SessionPool(max_slots=3, base_dir=tmp_path / "pool")
    idle = SessionPool.status(pool)
    assert idle["max_slots"] == 3 and idle["idle_count"] == 3 and idle["slots"] == []
    slot = pool.acquire(session_id="s1", agent_id="a1")
    busy = SessionPool.status(pool)
    assert busy["active_count"] == 1 and busy["idle_count"] == 2
    assert busy["slots"][0]["session_id"] == "s1" and busy["slots"][0]["slot_id"] == slot["slot_id"]


def test_unix_socket_mux_batch_handler_and_stop_removes_socket(tmp_path: Path) -> None:
    sock_path = tmp_path / "mux.sock"
    mux = UnixSocketMux(socket_path=sock_path)
    seen: list[dict[str, Any]] = []

    def handler(req: dict[str, Any]) -> dict[str, Any]:
        seen.append(req)
        return {"status": "OK"}

    UnixSocketMux.set_batch_handler(mux, handler)
    assert mux._batch_handler is handler
    assert mux.start() is True and sock_path.exists()
    UnixSocketMux.stop(mux)
    assert not sock_path.exists() and mux._server_sock is None and mux._thread is None
    UnixSocketMux.stop(mux)  # idempotente


# --------------------------------------------------------------------------- engine.docs_vectorizer
def test_docs_vectorizer_is_populated_and_ingest_curated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vec = ManPagesVectorizer(db_path=tmp_path / "docs.db")
    assert ManPagesVectorizer.is_populated(vec) is False
    with vec._conn_rw() as conn:
        conn.execute("INSERT INTO man_chunks (command, section, chunk_text) VALUES ('ls','NAME','ls - list')")
    assert ManPagesVectorizer.is_populated(vec) is True

    ingested: list[str] = []
    monkeypatch.setattr(vec, "ingest_command", lambda c: ingested.append(c) or {"status": "OK"})
    res = ManPagesVectorizer.ingest_curated(vec)
    assert res["status"] == "OK" and ingested == list(CURATED_COMMANDS)
    assert set(res["results"]) == set(CURATED_COMMANDS)


# --------------------------------------------------------------------------- engine.db
def test_create_in_memory_clone_copies_rows_and_is_detached(tmp_path: Path) -> None:
    src = sqlite3.connect(tmp_path / "src.db")
    src.execute("CREATE TABLE t (k TEXT, v INTEGER)")
    src.execute("INSERT INTO t VALUES ('a', 1), ('b', 2)")
    src.commit()
    clone = create_in_memory_clone(src)
    src.execute("INSERT INTO t VALUES ('c', 3)")
    src.commit()
    assert clone.execute("SELECT k, v FROM t ORDER BY k").fetchall() == [("a", 1), ("b", 2)]
    clone.execute("DELETE FROM t")  # mutar el clon no toca el origen
    assert src.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    src.close()
    clone.close()


# --------------------------------------------------------------------------- server compat forwarders
def test_aep_capabilities_forwards_to_discover_capabilities() -> None:
    res = _j(server.aep_capabilities())
    assert res["status"] == "OK" and "effective_chmod_tier" in res and "degradation_matrix" in res


def test_check_crash_alerts_reports_and_resolves_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    router = CrashRouter(db_path=tmp_path / "crash.db")
    for sync in ("sync_coredumps", "sync_apport", "sync_plane_events"):
        monkeypatch.setattr(router, sync, lambda *a, **k: 0)
    with router._conn_rw() as conn:
        conn.execute(
            "INSERT INTO crash_events (fingerprint, pid, signal, executable, event_timestamp, coredump_info) "
            "VALUES ('fp1', 42, 'SIGSEGV', '/usr/bin/cov', 'ts', '{\"cmdline\": \"cov --x\"}')"
        )
    monkeypatch.setattr(server, "crash_router", router)
    first = _j(server.check_crash_alerts())
    assert first["pending_count"] == 1 and first["alerts"][0]["executable"] == "/usr/bin/cov"
    assert first["alerts"][0]["cmdline"] == "cov --x"
    assert _j(server.check_crash_alerts(resolve_after_report=True))["pending_count"] == 1
    assert _j(server.check_crash_alerts())["pending_count"] == 0  # resuelto


# --------------------------------------------------------------------------- aep_front / aep_backend
def test_live_plane_manager_is_front_stale_tracks_source_mtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mgr = aep_front.LivePlaneManager()
    monkeypatch.setattr(aep_front, "FRONT_START_TIME_NS", 0)
    assert aep_front.LivePlaneManager.is_front_stale(mgr) is True  # fuente mas nueva que el arranque
    monkeypatch.setattr(aep_front, "FRONT_START_TIME_NS", time.time_ns() + 10**12)
    assert mgr.is_front_stale() is False
    monkeypatch.setattr(aep_front, "PROJECT_ROOT", tmp_path)  # sin aep_front.py -> OSError -> False
    monkeypatch.setattr(aep_front, "FRONT_START_TIME_NS", 0)
    assert mgr.is_front_stale() is False


def test_get_backend_meta_returns_a_defensive_copy() -> None:
    meta = aep_backend.get_backend_meta()
    assert meta == aep_backend.BACKEND_META
    meta["__probe__"] = 1
    assert "__probe__" not in aep_backend.get_backend_meta()
