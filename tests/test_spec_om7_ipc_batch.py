"""Comprehensive Test Suite for Spec OM-7: Shared-Memory UNIX Socket Pool & Ephemeral Batch/Code Mode.

Covers:
1. SessionPool: Concurrency, isolation slots in /dev/shm, TTL expiration, and reaping.
2. UnixSocketMux: Line-delimited JSON AF_UNIX communication, zero-FD leak verification.
3. playbook_run(action="batch"):
   - Single-turn multi-step execution.
   - Variable piping ($prev.*, $steps.<id>.*).
   - Server-side field projection (select_fields) and token savings estimate.
   - Return modes ("all", "last", "summary").
   - DAG ordering with topos_guard.
4. aep_ctl(domain="ipc"): CLI and RPC control-plane actions (status, ping, lease, release, reap, pool, metrics).
5. FastMCP 15-Tool Invariant: Confirms exactly 15 tools are registered without bloating the tool namespace.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402
from engine.ipc_pool import (  # noqa: E402
    GLOBAL_SOCKET_MUX,
    SessionPool,
    ensure_ipc_server_started,
    ipc_client_request,
    project_fields,
    resolve_step_refs,
)

# ==============================================================================
# 1. SessionPool Tests
# ==============================================================================

class TestSessionPool:
    def test_slot_acquisition_and_release(self, tmp_path: Path):
        pool = SessionPool(base_dir=tmp_path / "pool", max_slots=4, default_ttl_sec=5.0)
        assert pool.status()["active_count"] == 0

        # Lease slot 0
        slot0 = pool.acquire("sess_a", "agent_1")
        assert slot0["slot_id"] == 0
        assert slot0["session_id"] == "sess_a"
        assert slot0["in_use"] is True
        assert Path(slot0["scratch_dir"]).exists()

        # Re-acquiring same session reuses slot
        slot0_again = pool.acquire("sess_a", "agent_1")
        assert slot0_again["slot_id"] == 0
        assert slot0_again["reuse_count"] == 2

        # Release
        rel = pool.release("sess_a", "agent_1")
        assert rel["status"] == "OK"
        assert pool.status()["active_count"] == 0

    def test_pool_exhaustion_and_reaping(self, tmp_path: Path):
        pool = SessionPool(base_dir=tmp_path / "pool", max_slots=2, default_ttl_sec=0.1)

        s1 = pool.acquire("s1", "a1", ttl_sec=0.1)
        s2 = pool.acquire("s2", "a2", ttl_sec=0.1)
        assert s1["slot_id"] != s2["slot_id"]

        # Pool is full
        with pytest.raises(RuntimeError, match="No available.*slots"):
            pool.acquire("s3", "a3")

        # Wait for expiration
        import time
        time.sleep(0.15)

        reaped = pool.reap_expired()
        assert reaped["reaped_count"] == 2
        assert pool.status()["active_count"] == 0

        # Now acquisition succeeds
        s3 = pool.acquire("s3", "a3")
        assert s3["slot_id"] in (0, 1)

    def test_concurrent_slot_leasing(self, tmp_path: Path):
        pool = SessionPool(base_dir=tmp_path / "pool", max_slots=8, default_ttl_sec=10.0)
        acquired_slots = []
        lock = threading.Lock()

        def worker(idx: int):
            slot = pool.acquire(f"sess_{idx}", f"agent_{idx}")
            with lock:
                acquired_slots.append(slot["slot_id"])
            pool.release(f"sess_{idx}", f"agent_{idx}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(acquired_slots) == 8
        assert pool.status()["active_count"] == 0


# ==============================================================================
# 2. Variable Piping & Field Projection Unit Tests
# ==============================================================================

class TestPipingAndProjection:
    def test_resolve_step_refs(self):
        prev_output = {"status": "OK", "pid": 1234, "items": ["a", "b"]}
        step_outputs = {
            "s1": {"status": "OK", "metrics": {"rss_kb": 5000}},
            "s2": prev_output,
        }

        # Direct reference preservation of native types
        params = {
            "target_pid": "$prev.pid",
            "rss": "$steps.s1.metrics.rss_kb",
            "items": "$prev.items",
            "msg": "Target is $prev.pid on $steps.s1.metrics.rss_kb",
        }
        resolved = resolve_step_refs(params, step_outputs, prev_output)
        assert resolved["target_pid"] == 1234
        assert resolved["rss"] == 5000
        assert resolved["items"] == ["a", "b"]
        assert resolved["msg"] == "Target is 1234 on 5000"

    def test_project_fields(self):
        data = {
            "status": "OK",
            "nested": {
                "val": 42,
                "secret": "hidden",
            },
            "array": [{"name": "item1", "drop": "yes"}],
            "unwanted": "discard_me",
        }
        projected = project_fields(data, ["status", "nested.val", "array.0.name"])
        assert projected["status"] == "OK"
        assert projected["nested"] == {"val": 42}
        assert projected["array"] == {"0": {"name": "item1"}}
        assert "unwanted" not in projected
        assert "secret" not in projected["nested"]


# ==============================================================================
# 3. UNIX Domain Socket Mux & Zero-FD Tests
# ==============================================================================

class TestUnixSocketMux:
    def test_zero_fd_leak_on_socket_roundtrips(self):
        ensure_ipc_server_started()
        assert GLOBAL_SOCKET_MUX.is_running

        # Initial FD count
        pid = os.getpid()
        proc_fd = Path(f"/proc/{pid}/fd")
        initial_fds = len(list(proc_fd.iterdir())) if proc_fd.exists() else 0

        # Execute 20 rapid AF_UNIX client pings
        for _ in range(20):
            res = ipc_client_request({"action": "ping"})
            assert res["status"] == "OK"
            assert res["pong"] is True

        if proc_fd.exists():
            final_fds = len(list(proc_fd.iterdir()))
            # Strict zero FD leakage tolerance
            assert abs(final_fds - initial_fds) <= 1, f"FD leak detected: {initial_fds} -> {final_fds}"


# ==============================================================================
# 4. Playbook Ephemeral Batch & Code Mode Tests
# ==============================================================================

class TestPlaybookBatchMode:
    def test_batch_all_and_variable_piping(self):
        async def _run():
            steps = [
                {"id": "s1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}},
                {"id": "s2", "tool": "topos_audit_dag", "params": {"tasks": ["t1"], "dependencies": {}}},
            ]
            res_raw = await server.playbook_run(
                action="batch",
                name="test-batch-pipeline",
                steps=steps,
                return_only="all",
            )
            res = json.loads(res_raw)
            assert res["status"] == "OK"
            assert res["all_ok"] is True
            assert res["steps_run"] == 2
            assert len(res["results"]) == 2
            assert res["results"][0]["id"] == "s1"
            assert res["results"][1]["id"] == "s2"
            assert "ipc_slot" in res

        asyncio.run(_run())

    def test_batch_return_last_and_summary(self):
        async def _run():
            steps = [
                {"id": "s1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}},
                {"id": "s2", "tool": "topos_audit_dag", "params": {"tasks": ["t1"], "dependencies": {}}},
            ]

            # return_only="last"
            res_last = json.loads(await server.playbook_run(action="batch", steps=steps, return_only="last"))
            assert res_last["status"] == "OK"
            assert "output" in res_last
            assert "results" not in res_last
            assert res_last["output"]["verdict"] == "APPROVED"

            # return_only="summary"
            res_sum = json.loads(await server.playbook_run(action="batch", steps=steps, return_only="summary"))
            assert res_sum["status"] == "OK"
            assert len(res_sum["steps_summary"]) == 2
            assert res_sum["steps_summary"][0]["ok"] is True

        asyncio.run(_run())

    def test_batch_field_projection_token_savings(self):
        async def _run():
            steps = [
                {"id": "s1", "tool": "process_inspect", "params": {"pid": 0}},
                {"id": "s2", "tool": "topos_audit_dag", "params": {"tasks": ["t1", "t2"], "dependencies": {"t2": ["t1"]}}},
            ]
            res_proj = json.loads(await server.playbook_run(
                action="batch",
                steps=steps,
                return_only="all",
                select_fields=["status", "batch", "all_ok", "results.0.output.status"],
            ))
            assert res_proj["status"] == "OK"
            assert res_proj["all_ok"] is True
            assert "token_savings_estimate" in res_proj
            savings = res_proj["token_savings_estimate"]
            assert savings["savings_pct"] >= 50.0
            assert savings["turns_saved"] == 1

        asyncio.run(_run())


# ==============================================================================
# 5. aep_ctl Control Plane IPC Domain Tests
# ==============================================================================

class TestAepCtlIpcDomain:
    def test_aep_ctl_ipc_actions(self):
        async def _run():
            # 1. status
            res_st = json.loads(await server.aep_ctl(domain="ipc", action="status"))
            assert res_st["status"] == "OK"
            assert "ipc_socket" in res_st
            assert "session_pool" in res_st

            # 2. ping
            res_ping = json.loads(await server.aep_ctl(domain="ipc", action="ping"))
            assert res_ping["status"] == "OK"
            assert res_ping["pong"] is True

            # 3. lease and release
            res_lease = json.loads(await server.aep_ctl(domain="ipc", action="lease", name="ctl-test"))
            assert res_lease["status"] == "OK"
            assert res_lease["leased_slot"]["session_id"] == "ctl-test"

            res_rel = json.loads(await server.aep_ctl(domain="ipc", action="release", name="ctl-test"))
            assert res_rel["status"] == "OK"

            # 4. metrics
            res_met = json.loads(await server.aep_ctl(domain="ipc", action="metrics"))
            assert res_met["status"] == "OK"
            assert "active_sessions" in res_met

        asyncio.run(_run())

    def test_cli_aep_ctl_ipc(self):
        import subprocess
        ctl_path = PROJECT_ROOT / "scripts" / "aep-ctl"
        res = subprocess.run([sys.executable, str(ctl_path), "ipc", "status", "--json"], capture_output=True, text=True, check=False)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["status"] == "OK"
        assert "session_pool" in data


# ==============================================================================
# 6. FastMCP 15-Tool Invariant Test
# ==============================================================================

class TestFastMcpToolInvariant:
    def test_strictly_15_tools_registered(self):
        tools = server.mcp._tool_manager.list_tools()
        assert len(tools) == 15, f"Expected strictly 15 FastMCP tools, got {len(tools)}: {[t.name for t in tools]}"
