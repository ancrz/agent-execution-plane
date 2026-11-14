"""ONT-54 T1 (G43): pending crash alerts are grouped per crash file / executable and paginated."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import server
from engine.crash_router import CrashRouter

MTIMES = (1_700_000_000, 1_700_000_100, 1_700_000_200)


def _insert(router: CrashRouter, fp: str, exe: str, info: dict, source: str = "apport", sig: str = "SIGSEGV") -> None:
    with router._conn_rw() as conn:
        conn.execute(
            "INSERT INTO crash_events (fingerprint, pid, signal, executable, event_timestamp, coredump_info, source) "
            "VALUES (?, 1, ?, ?, 'ts', ?, ?)",
            (fp, sig, exe, json.dumps(info), source),
        )


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CrashRouter:
    r = CrashRouter(db_path=tmp_path / "crash.db")
    for sync in ("sync_coredumps", "sync_apport", "sync_plane_events"):
        monkeypatch.setattr(r, sync, lambda *a, **k: 0)
    return r


def _populate(router: CrashRouter, crash_dir: Path) -> None:
    crash_dir.mkdir(exist_ok=True)
    (crash_dir / "_opt_ag.1000.crash").write_text("x", encoding="utf-8")
    for m in MTIMES:
        _insert(router, f"apport:_opt_ag.1000.crash:{m}", "/opt/ag", {"file": "_opt_ag.1000.crash", "mtime": m})
    _insert(router, "apport:gone:1700000500", "/usr/bin/gone", {"file": "gone.crash", "mtime": 1_700_000_500})
    _insert(router, "apport:chrome:1700000300", "/opt/chrome", {"file": "chrome.crash", "mtime": 1_700_000_300})


def _call(**kw: object) -> str:
    return asyncio.run(server.diagnose_system_crashes(action="alerts", **kw))


def test_same_file_collapses_into_one_group(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    res = router.check(crash_dir=d)
    assert res["pending_count"] == 5 and res["pending_groups"] == 3
    grp = next(g for g in res["alerts"] if g["executable"] == "/opt/ag")
    assert grp["occurrences"] == 3 and sorted(grp["ids"]) == [1, 2, 3]
    assert grp["first_seen"].startswith("2023-11-14T22:13:20") and grp["last_seen"].startswith("2023-11-14T22:16:40")
    assert grp["file_present"] is True and "coredump_info" not in grp
    seen = [g["last_seen"] for g in res["alerts"]]
    assert seen == sorted(seen, reverse=True)


def test_missing_file_is_flagged(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    res = router.check(crash_dir=d)
    assert next(g for g in res["alerts"] if g["executable"] == "/usr/bin/gone")["file_present"] is False


def test_pagination_truncated_implies_cursor(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    p1 = router.check(limit=1, crash_dir=d)
    assert p1["truncated"] is True and p1["cursor"] == "1" and len(p1["alerts"]) == 1
    p2 = router.check(limit=5, cursor=int(p1["cursor"]), crash_dir=d)
    assert p2["truncated"] is False and p2["cursor"] is None and len(p2["alerts"]) == 2


def test_detail_includes_latest_coredump_info(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    res = router.check(detail=True, crash_dir=d)
    grp = next(g for g in res["alerts"] if g["executable"] == "/opt/ag")
    assert grp["coredump_info"]["mtime"] == MTIMES[-1]


def test_resolve_after_report_resolves_all_rows(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    router.check(resolve_after_report=True, limit=1, crash_dir=d)
    assert router.check(crash_dir=d)["pending_count"] == 0


def test_same_file_across_sources_is_one_group(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    d.mkdir()
    (d / "x.crash").write_text("x", encoding="utf-8")
    _insert(router, "legacy:1", "/opt/x", {"file": "x.crash", "mtime": 1_700_000_000}, source="coredump")
    _insert(router, "apport:x.crash:2", "/opt/x", {"file": "x.crash", "mtime": 1_700_000_100}, source="apport")
    res = router.check(crash_dir=d)
    assert res["pending_groups"] == 1
    grp = res["alerts"][0]
    assert grp["occurrences"] == 2 and grp["source"] == "apport" and grp["sources"] == ["apport", "coredump"]
    assert grp["file_present"] is True


def test_coredump_source_row_with_missing_file_is_flagged(router: CrashRouter, tmp_path: Path) -> None:
    d = tmp_path / "crash"
    d.mkdir()
    _insert(router, "legacy:2", "/usr/bin/gone", {"file": "gone.crash", "mtime": 1_700_000_000}, source="coredump")
    grp = router.check(crash_dir=d)["alerts"][0]
    assert grp["file_present"] is False and "sources" not in grp


def test_tool_next_action_and_hint(router: CrashRouter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "crash"
    _populate(router, d)
    real_check = router.check
    monkeypatch.setattr(router, "check", lambda *a, **k: real_check(*a, crash_dir=d, **k))
    monkeypatch.setattr(server, "crash_router", router)
    res = json.loads(_call(limit=1))
    assert res["truncated"] is True and res["cursor"] == "1"
    assert "resolve_after_report=True" in res["next_action"] and "cursor=1" in res["next_action"]
    full = json.loads(_call(limit=10))
    assert "file_present=false" in full["hint"]
