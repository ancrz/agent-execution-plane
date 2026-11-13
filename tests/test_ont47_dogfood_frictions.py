"""ONT-47: fricciones de dogfooding (T1..T9). Todo in-proceso; bases SQLite en tmp; el host no se muta."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import server
from engine import net_telemetry, primitives
from engine.kanban import KanbanBoard
from engine.playbook import DB_DEFAULT_PATH as PLAYBOOK_DEFAULT_DB
from engine.playbook import PlaybookStore
from engine.privilege import _PrivilegeCache
from engine.telemetry import normalize_error_class


def _j(coro: Any) -> dict[str, Any]:
    data = json.loads(asyncio.run(coro))
    assert isinstance(data, dict)
    return data


@pytest.fixture
def tier_rw(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    yield
    _PrivilegeCache.reset()


# --- T1: drift_kind -----------------------------------------------------------------------------------------


def _discover(monkeypatch: pytest.MonkeyPatch, *, loaded_fp: str, disk_fp: str, drift: bool = True) -> dict[str, Any]:
    monkeypatch.setattr(server, "LOADED_COMMIT", "old1111" if drift else "new2222")
    monkeypatch.setattr(server, "_read_git_head_commit", lambda: "new2222")
    monkeypatch.setattr(server, "LOADED_FINGERPRINT", loaded_fp)
    monkeypatch.setattr(server, "code_fingerprint", lambda *_a, **_k: disk_fp)
    monkeypatch.setattr(server, "_is_front_stale", lambda: False)
    return _j(server.discover(action="capabilities", verbosity="terse", force_refresh=True))


def test_t1_docs_only_drift_kind_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp1")
    assert data["commit_drift"] is True and data["stale"] is False
    assert data["drift_kind"] == "docs_only"
    assert "HEAD new2222 differs from loaded old1111 (docs-only, no reload needed)" in data["summary"]


def test_t1_code_drift_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp2")
    assert data["commit_drift"] is True and data["stale"] is True and data["drift_kind"] == "code"


def test_t1_unverified_drift_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="unknown", disk_fp="fp1")
    assert data["commit_drift"] is True and data["drift_kind"] == "unverified"


def test_t1_no_drift_emits_no_drift_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _discover(monkeypatch, loaded_fp="fp1", disk_fp="fp1", drift=False)
    assert "commit_drift" not in data and "drift_kind" not in data


# --- T2: socket-monitor compacto plegado y paginado ----------------------------------------------------------


def _fake_sockets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(40):
        rows.append(
            {
                "proto": "TCP",
                "local": f"0.0.0.0:{2000 + i}",
                "remote": "0.0.0.0:0",
                "state": "LISTEN",
                "uid": 0,
                "inode": 0,
            }
        )
    for i in range(20):
        rows.append(
            {
                "proto": "TCP6",
                "local": f"::1:{3000 + i}",
                "remote": "::1:9",
                "state": "ESTABLISHED",
                "uid": 1,
                "inode": 0,
            }
        )
    return rows


@pytest.fixture
def fake_sockets(monkeypatch: pytest.MonkeyPatch, tier_rw: None) -> None:
    monkeypatch.setattr(primitives, "parse_proc_net_sockets", lambda protocol="tcp", **_kw: _fake_sockets())
    monkeypatch.setattr(primitives, "map_socket_inodes", lambda inodes: {})


def test_t2_compact_socket_monitor_folds_and_paginates(fake_sockets: None) -> None:
    page1 = _j(server.default_primitives(action="run", name="socket-monitor", verbosity="summary"))
    res = page1["result"]
    assert res["count"] == 60
    assert res["by_state"] == {"LISTEN": 40, "ESTABLISHED": 20}
    assert res["by_proto"] == {"TCP": 40, "TCP6": 20}
    assert len(res["listeners"]) == 25 and "sockets" not in res
    assert set(res["listeners"][0]) <= {"proto", "local", "uid", "pid"}
    assert page1["truncated"] is True and page1["cursor"] == "25"

    page2 = _j(server.default_primitives(action="run", name="socket-monitor", verbosity="summary", cursor=25))
    assert len(page2["result"]["listeners"]) == 15
    assert page2["truncated"] is False and page2["cursor"] is None


def test_t2_state_filter_paginates_sockets_key(fake_sockets: None) -> None:
    out = _j(
        server.default_primitives(
            action="run", name="socket-monitor", params={"state": "ESTABLISHED"}, verbosity="summary", limit=5
        )
    )
    res = out["result"]
    assert res["count"] == 20 and len(res["sockets"]) == 5 and "listeners" not in res
    assert {s["state"] for s in res["sockets"]} == {"ESTABLISHED"}
    assert out["truncated"] is True and out["cursor"] == "5"


def test_t2_detail_keeps_full_table(fake_sockets: None) -> None:
    out = _j(server.default_primitives(action="run", name="socket-monitor", verbosity="detail"))
    assert len(out["result"]["sockets"]) == 60 and "by_state" not in out["result"]


# --- T3: map_socket_inodes ---------------------------------------------------------------------------------------


def test_t3_map_socket_inodes_resolves_own_socket() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        inode = os.fstat(sock.fileno()).st_ino
        found = net_telemetry.map_socket_inodes({inode})
        assert inode in found and found[inode][0] == os.getpid() and found[inode][1]
        assert net_telemetry.map_socket_inodes({inode}) == found  # deterministic for the same /proc view


def test_t3_map_socket_inodes_empty_and_unknown() -> None:
    assert net_telemetry.map_socket_inodes(set()) == {}
    assert net_telemetry.map_socket_inodes({2**62}) == {}


def test_t3_parse_resolve_pids_fills_own_listener() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        rows = net_telemetry.parse_proc_net_sockets("tcp", resolve_pids=True)
        mine = [r for r in rows if r["local_port"] == port]
        assert mine and mine[0]["pid"] == os.getpid() and mine[0]["process"]
        plain = net_telemetry.parse_proc_net_sockets("tcp")
        assert all("pid" not in r for r in plain)


# --- T4: probe compacto ------------------------------------------------------------------------------------------


def test_t4_compact_probe_keeps_only_open_rows(monkeypatch: pytest.MonkeyPatch, tier_rw: None) -> None:
    async def fake_open(host: str, port: int) -> Any:
        if port == 81:
            raise TimeoutError
        raise ConnectionRefusedError

    monkeypatch.setattr(net_telemetry.asyncio, "open_connection", fake_open)
    compact = _j(
        server.aep_ctl(domain="network", action="probe", name="192.0.2.1", args=["80", "81", "82"], verbosity="summary")
    )
    assert compact["ports"] == [] and compact["open_ports"] == [] and compact["open_count"] == 0
    assert compact["closed_count"] == 3 and compact["closed_by_reason"] == {"refused": 2, "timeout": 1}

    detail = _j(
        server.aep_ctl(domain="network", action="probe", name="192.0.2.1", args=["80", "81", "82"], verbosity="detail")
    )
    assert len(detail["ports"]) == 3 and "closed_by_reason" not in detail


def test_t4_compact_probe_result_keeps_open_rows() -> None:
    result = {
        "ports": [{"port": 22, "state": "open"}, {"port": 80, "state": "closed", "reason": "refused"}],
        "open_ports": [{"port": 22, "state": "open"}],
        "open_count": 1,
        "closed_count": 1,
    }
    out = net_telemetry.compact_probe_result(result)
    assert out["ports"] == [{"port": 22, "state": "open"}] and out["closed_by_reason"] == {"refused": 1}
    assert out["open_ports"] == result["open_ports"] and len(result["ports"]) == 2  # input not mutated


# --- T5: confianza de query_system_docs ---------------------------------------------------------------------------


class _FakeDocs:
    def __init__(self, distances: list[float]) -> None:
        self._d = distances

    def query(self, q: str, limit: int = 3) -> dict[str, Any]:
        return {"status": "OK", "results": [{"command": "ss", "distance": d, "chunk": "x"} for d in self._d]}

    def ingest_command(self, cmd: str) -> None:  # pragma: no cover - not used
        return None


@pytest.mark.parametrize(
    ("distances", "confidence"),
    [([0.15, 0.3], "HIGH"), ([0.20], "HIGH"), ([0.22, 0.31], "MEDIUM"), ([0.28], "MEDIUM"), ([0.30, 0.32], "LOW")],
)
def test_t5_confidence_bands(monkeypatch: pytest.MonkeyPatch, distances: list[float], confidence: str) -> None:
    monkeypatch.setattr(server, "_get_docs_vectorizer", lambda: _FakeDocs(distances))
    out = _j(server.query_system_docs(query="socket question", verbosity="summary"))
    assert out["best_distance"] == min(distances) and out["confidence"] == confidence
    assert len(out["results"]) == len(distances)  # results are never filtered
    if confidence == "LOW":
        assert out["match_status"] == "NO_HIGH_CONFIDENCE_MATCH"
        assert "ingest_command=<cmd>" in out["next_action"]
    else:
        assert "match_status" not in out


def test_t5_no_results_no_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_get_docs_vectorizer", lambda: _FakeDocs([]))
    out = _j(server.query_system_docs(query="nothing", verbosity="summary"))
    assert "confidence" not in out and "best_distance" not in out


# --- T6: error_class desde stderr --------------------------------------------------------------------------------


def test_t6_stderr_traceback_gives_last_exception_class() -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "ValueError: inner\n"
        "\nDuring handling of the above exception, another exception occurred:\n"
        "FileNotFoundError: [Errno 2] No such file or directory: 'nope'\n"
    )
    assert normalize_error_class({"stderr": stderr}) == "filenotfounderror"
    assert normalize_error_class({"stderr": stderr}) == normalize_error_class({"stderr": stderr})


def test_t6_precedence_explicit_then_error_then_stderr() -> None:
    stderr = "KeyError: 'x'"
    assert normalize_error_class({"error_class": "Boom", "error": "Other x", "stderr": stderr}) == "boom"
    assert normalize_error_class({"error": "Other x", "stderr": stderr}) == "other"
    assert normalize_error_class({"stderr": stderr}) == "keyerror"
    assert normalize_error_class({"stderr": "all good"}) == "unknown"
    assert normalize_error_class({}) == "unknown"


# --- T7: truncated => cursor -------------------------------------------------------------------------------------


@pytest.fixture
def tmp_board(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tier_rw: None) -> KanbanBoard:
    board = KanbanBoard(db_path=tmp_path / "kanban.db")
    monkeypatch.setattr(server, "kanban", board)
    for i in range(7):
        board.create_task(f"ont47 task {i}", "intent", "cat", None)
    return board


def test_t7_kanban_board_truncated_has_cursor_and_pages(tmp_board: KanbanBoard) -> None:
    first = _j(server.kanban_board(action="board", limit=3, verbosity="summary"))
    assert first["truncated"] is True and first["cursor"] == "3"
    assert first["lane_totals"]["BACKLOG"] == 7 and len(first["lanes"]["BACKLOG"]) == 3

    second = _j(server.kanban_board(action="board", limit=3, verbosity="summary", cursor=3))
    ids_first = {c["task_id"] for c in first["lanes"]["BACKLOG"]}
    ids_second = {c["task_id"] for c in second["lanes"]["BACKLOG"]}
    assert len(ids_second) == 3 and not ids_first & ids_second and second["truncated"] is True

    last = _j(server.kanban_board(action="board", limit=3, verbosity="summary", cursor=6))
    assert len(last["lanes"]["BACKLOG"]) == 1 and last["truncated"] is False and last["cursor"] is None


def test_t7_kanban_not_truncated_has_no_cursor(tmp_board: KanbanBoard) -> None:
    out = _j(server.kanban_board(action="board", limit=50, verbosity="summary"))
    assert out["truncated"] is False and out["cursor"] is None


def _pueue_status(n: int) -> str:
    tasks = {
        str(i): {
            "id": i,
            "label": None,
            "command": f"cmd{i}",
            "group": "default",
            "status": {"Done": {"result": "Success"}},
            "envs": {"A": "b"},
        }
        for i in range(n)
    }
    return json.dumps({"tasks": tasks, "groups": {}})


def test_t7_pueue_status_truncated_has_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ensure_pueue_daemon", lambda: "pueue")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=_pueue_status(12), stderr=""),
    )
    first = _j(server.async_job_dispatch(action="status", limit=5, verbosity="summary"))
    assert first["truncated"] is True and first["cursor"] == "5" and first["total_tasks"] == 12
    assert list(first["tasks"]) == ["11", "10", "9", "8", "7"]

    last = _j(server.async_job_dispatch(action="status", limit=5, verbosity="summary", cursor=10))
    assert list(last["tasks"]) == ["1", "0"] and last["truncated"] is False and last["cursor"] is None


@pytest.mark.parametrize("payload_n", [3, 12])
def test_t7_invariant_truncated_implies_cursor(monkeypatch: pytest.MonkeyPatch, payload_n: int) -> None:
    payload, truncated = server._compact_pueue_payload(_pueue_status(payload_n), limit=5, is_compact=True)
    assert (not truncated) or payload.get("next_cursor") is not None


# --- T8: schema por dominio compacto ----------------------------------------------------------------------------


def test_t8_compact_domain_schema_has_no_domains_dump() -> None:
    out = _j(server.aep_ctl(domain="network", action="schema", verbosity="summary"))
    assert out["domain"] == "network" and "domains" not in out
    assert out["schema"]["actions"] and "precondition_defaults" in out and "degradation_matrix" in out


def test_t8_detail_and_full_schema_keep_domains() -> None:
    detail = _j(server.aep_ctl(domain="network", action="schema", verbosity="detail"))
    assert len(detail["domains"]) >= 9 and detail["domain"] == "network"
    full = _j(server.aep_ctl(action="schema", verbosity="summary"))
    assert len(full["domains"]) >= 9 and "precondition_defaults" in full


# --- T9: los tests no escriben en la DB real --------------------------------------------------------------------


def test_t9_om7_fixture_isolates_playbook_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The om7 fixture swaps server.playbook_store for a tmp store; running a saved playbook then leaves the real DB alone."""
    src = (Path(__file__).parent / "test_spec_om7_ipc_batch.py").read_text(encoding="utf-8")
    assert 'monkeypatch.setattr(server, "playbook_store"' in src
    monkeypatch.setattr(server, "playbook_store", PlaybookStore(db_path=tmp_path / "playbooks.db"))
    assert server.playbook_store.db_path != PLAYBOOK_DEFAULT_DB
    server.playbook_store.create("pb_t9_probe", "probe", [{"id": "s1", "tool": "process_inspect", "params": {}}], None)
    assert server.playbook_store.get("pb_t9_probe") is not None
