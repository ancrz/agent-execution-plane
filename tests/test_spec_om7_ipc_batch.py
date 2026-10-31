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


# ==============================================================================
# 7. Milestone ONT-22: Spec OM-7 Omission Gap Remediation & Multi-Agent Tests
# ==============================================================================

class TestSpecOm7OmissionGapsAndMultiAgent:
    def test_gap_om22_1_smart_projection_fallbacks(self):
        async def _run():
            steps = [
                {"id": "s1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}},
            ]
            # 1. return_only="last" with select_fields
            res_last = json.loads(await server.playbook_run(
                action="batch",
                steps=steps,
                return_only="last",
                select_fields=["status", "pid"],
            ))
            assert res_last["status"] == "OK"
            assert "output" in res_last
            assert isinstance(res_last["output"]["pid"], int) and res_last["output"]["pid"] > 0
            assert res_last.get("pid") == res_last["output"]["pid"]
            assert "token_savings_estimate" in res_last
            assert res_last["token_savings_estimate"]["savings_pct"] >= 50.0

            # 2. return_only="all" with select_fields
            res_all = json.loads(await server.playbook_run(
                action="batch",
                steps=steps,
                return_only="all",
                select_fields=["status", "pid"],
            ))
            assert res_all["status"] == "OK"
            assert "results" in res_all
            assert len(res_all["results"]) == 1
            assert res_all["results"][0]["id"] == "s1"
            assert isinstance(res_all["results"][0]["pid"], int) and res_all["results"][0]["pid"] > 0
            assert "token_savings_estimate" in res_all

        asyncio.run(_run())

    def test_gap_om22_2_failed_steps_diagnostics_preservation(self):
        async def _run():
            steps = [
                {"id": "s1", "tool": "unknown_tool_for_test", "params": {}},
            ]
            # Verify field projection never swallows failed_steps
            res = json.loads(await server.playbook_run(
                action="batch",
                steps=steps,
                select_fields=["status"],
            ))
            assert res["status"] == "PARTIAL"
            assert "failed_steps" in res
            assert len(res["failed_steps"]) == 1
            assert res["failed_steps"][0]["id"] == "s1"
            assert res["failed_steps"][0]["status"] == "NOT_ALLOWED"

        asyncio.run(_run())

    def test_gap_om22_3_cross_agent_cache_piping(self):
        async def _run():
            sid = "test-cross-agent-session"
            # 1. Pragma produces output and stores as pragma_handoff
            steps_pragma = [
                {"id": "step1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}, "store_as": "pragma_handoff"},
            ]
            res_pragma = json.loads(await server.playbook_run(
                action="batch",
                steps=steps_pragma,
                vars={"session_id": sid},
                agent_id="pragma",
            ))
            assert res_pragma["status"] == "OK"

            # Verify cache via aep_ctl
            cache_info = json.loads(await server.aep_ctl(domain="ipc", action="cache", name=sid, agent_id="pragma"))
            assert cache_info["status"] == "OK"
            assert "pragma_handoff" in cache_info.get("keys", [])

            # 2. Dokimos reads the cached handoff via $cache.pragma_handoff.pid
            steps_dokimos = [
                {"id": "step2", "tool": "process_inspect", "params": {"pid": "$cache.pragma_handoff.pid", "limit": 1}},
            ]
            res_dokimos = json.loads(await server.playbook_run(
                action="batch",
                steps=steps_dokimos,
                vars={"session_id": sid},
                agent_id="dokimos",
            ))
            assert res_dokimos["status"] == "OK"
            assert res_dokimos["results"][0]["output"]["pid"] == res_pragma["results"][0]["output"]["pid"]

        asyncio.run(_run())

    def test_gap_om22_4_playbook_kwarg_filtering_and_kanban(self):
        async def _run():
            steps = [
                {
                    "id": "step_kb",
                    "tool": "kanban_board",
                    "params": {
                        "action": "board",
                        "limit": 2,
                        "extra_param_unknown_1": "abc",
                        "extra_param_unknown_2": [1, 2, 3],
                    },
                },
            ]
            res = json.loads(await server.playbook_run(action="batch", steps=steps))
            assert res["status"] == "OK"
            assert res["results"][0]["status"] == "OK"
            assert "lanes" in res["results"][0]["output"]

        asyncio.run(_run())


# ==============================================================================
# 8. Milestone ONT-23: Pico-Triad Multi-Agent Concurrency Isolation Tests
# ==============================================================================

class TestPicoTriadMultiAgentConcurrency:
    def test_concurrent_pico_jenkins_go_builds_no_collision(self):
        async def _run():
            # Clean up any existing tasks for concurrent_mem_stat
            with server.kanban._conn_rw() as conn:
                conn.execute(
                    "DELETE FROM kanban_tasks WHERE artifact_name = 'concurrent_mem_stat'"
                )

            agents = ["pragma", "dokimos", "archon", "ontos"]
            build_coros = [
                server.artifact_lint_and_build(
                    action="build",
                    template_name="mem-stat",
                    name="concurrent_mem_stat",
                    agent_id=agent,
                )
                for agent in agents
            ]
            raw_build_results = await asyncio.gather(*build_coros)

            for agent, raw in zip(agents, raw_build_results):
                data = json.loads(raw)
                assert data["status"] == "SUCCESS", f"Build failed for {agent}: {data}"
                assert data["name"] == "concurrent_mem_stat"
                assert "ipc_slot" in data
                assert data["ipc_slot"]["agent_id"] == agent
                bin_path = Path(data["binary_path"])
                assert bin_path.exists()
                assert bin_path.read_bytes()[:4] == b"\x7fELF"

            # Verify Kanban tasks immediately after 4 concurrent builds:
            # exactly 1 active task for concurrent_mem_stat with attempts == 4
            with server.kanban._conn_ro() as conn:
                tasks = conn.execute(
                    "SELECT * FROM kanban_tasks WHERE artifact_name = 'concurrent_mem_stat' AND archived = 0"
                ).fetchall()
                assert len(tasks) == 1
                assert tasks[0]["attempts"] == 4
                assert tasks[0]["state"] == "LINTED"

            # Execute in RAM concurrently across agents
            exec_coros = [
                server.artifact_execute_in_ram(name="concurrent_mem_stat", agent_id=agent)
                for agent in agents
            ]
            raw_exec_results = await asyncio.gather(*exec_coros)
            for agent, raw in zip(agents, raw_exec_results):
                ex_data = json.loads(raw)
                assert ex_data["status"] == "SUCCESS", f"Execution failed for {agent}: {ex_data}"
                assert ex_data.get("exit_code") == 0

            # Canary execution updates kanban task: attempts == 8, canary_passed == 1
            with server.kanban._conn_ro() as conn:
                tasks_after = conn.execute(
                    "SELECT * FROM kanban_tasks WHERE artifact_name = 'concurrent_mem_stat' AND archived = 0"
                ).fetchall()
                assert len(tasks_after) == 1
                assert tasks_after[0]["attempts"] == 8
                assert tasks_after[0]["canary_passed"] == 1

        asyncio.run(_run())

    def test_atomic_kanban_upsert_build_task_concurrency(self, tmp_path: Path):
        from engine.kanban import KanbanBoard

        k = KanbanBoard(db_path=tmp_path / "k.db")
        results = []
        errors = []
        lock = threading.Lock()

        def worker(idx: int):
            try:
                res = k.upsert_build_task(
                    artifact_name="shared_go_probe",
                    intent="concurrency test",
                    category="test",
                    lint_passed=True,
                    agent_id=f"agent_{idx}",
                    note=f"concurrent run {idx}",
                )
                with lock:
                    results.append(res)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent upsert: {errors}"
        assert len(results) == 8
        task_ids = {r["task_id"] for r in results}
        assert len(task_ids) == 1, f"Expected 1 unique task_id, got: {task_ids}"
        assert all(r["status"] == "OK" for r in results)
        assert all(r["state"] == "LINTED" for r in results)

        with k._conn_ro() as conn:
            rows = conn.execute("SELECT * FROM kanban_tasks WHERE artifact_name = 'shared_go_probe'").fetchall()
            assert len(rows) == 1
            assert rows[0]["attempts"] == 8
            assert rows[0]["id"] == list(task_ids)[0]

    def test_pico_ansible_saved_playbook_multi_agent_isolation_and_piping(self):
        async def _run():
            pb_name = "pb_multi_isolation"
            steps = [
                {"id": "s1", "tool": "process_inspect", "params": {"pid": 0}},
                {"id": "s2", "tool": "kanban_board", "params": {"action": "board", "limit": 2}},
            ]
            res_create = json.loads(
                await server.playbook_run(
                    action="create",
                    name=pb_name,
                    description="Multi agent isolation test",
                    steps=steps,
                )
            )
            assert res_create["status"] == "OK"

            agents = ["agent_alpha", "agent_beta", "agent_gamma", "agent_delta"]
            coros = [
                server.playbook_run(
                    action="run",
                    name=pb_name,
                    return_only="last",
                    select_fields=["status", "counts", "ipc_slot"],
                    agent_id=agent,
                )
                for agent in agents
            ]
            raw_results = await asyncio.gather(*coros)

            for agent, raw in zip(agents, raw_results):
                data = json.loads(raw)
                assert data["status"] == "OK", f"Playbook run failed for {agent}: {data}"
                assert "ipc_slot" in data
                assert data["ipc_slot"]["agent_id"] == agent
                assert "output" in data
                assert "token_savings_estimate" in data
                assert "counts" in data["output"] or "lanes" in data["output"] or "status" in data

        asyncio.run(_run())

    def test_catalog_register_artifact_precomputed_embedding_concurrency(self, tmp_path: Path):
        from engine.catalog import ArtifactCatalog

        cat = ArtifactCatalog(db_path=tmp_path / "cat.db")
        ids = []
        errors = []
        lock = threading.Lock()

        def worker(idx: int):
            try:
                aid = cat.register_artifact(
                    name="concurrent_vec_art",
                    intent=f"Concurrent embedding registration test {idx}",
                    category="test",
                    cue_contract="package schema",
                    go_source="package main\nfunc main() {}",
                    binary_blob=b"\x7fELFfaketest",
                )
                with lock:
                    ids.append(aid)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent register_artifact failed: {errors}"
        assert len(ids) == 4
        assert len(set(ids)) == 1

        with cat._get_ro_conn() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE name = 'concurrent_vec_art'").fetchone()
            assert row is not None
            assert row["version"] == 4


# ==============================================================================
# 9. Milestone ONT-24: Non-Pico Concurrency Protections (Audit & RAM Snapshots)
# ==============================================================================

class TestNonPicoSystemWideConcurrency:
    def test_concurrent_audit_ledger_recording_no_forks(self, tmp_path: Path):
        from engine.db import get_rw_connection
        from engine.security import record_audit_event, verify_audit_chain

        db_file = tmp_path / "audit_test.db"
        errors = []
        recorded_hashes = []
        lock = threading.Lock()

        # Pre-initialize database
        with get_rw_connection(db_file) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")

        def worker(idx: int):
            try:
                # Each thread gets its own rw connection to simulate distinct agent processes
                with get_rw_connection(db_file) as conn:
                    res = record_audit_event(
                        conn=conn,
                        agent_id=f"agent_{idx}",
                        tool_name="aep_ctl",
                        action="audit_test",
                        capability_tier="rwx",
                        status="OK",
                        details={"thread_index": idx, "spec": "OM-7"},
                        target=f"target_{idx}",
                    )
                    with lock:
                        recorded_hashes.append(res["entry_hash"])
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent audit recording: {errors}"
        assert len(recorded_hashes) == 8
        assert len(set(recorded_hashes)) == 8  # All hashes unique

        with get_rw_connection(db_file) as conn:
            chain_res = verify_audit_chain(conn)
            assert chain_res["valid"] is True, f"Audit chain verification failed: {chain_res}"
            assert chain_res["total_verified"] == 8
            assert chain_res.get("broken_at") is None

    def test_concurrent_in_memory_micro_snapshots_cross_thread(self, tmp_path: Path):
        from engine.backup import (
            clear_micro_snapshots,
            create_micro_snapshot,
            list_micro_snapshots,
            restore_micro_snapshot,
        )
        from engine.db import get_rw_connection

        db_file = tmp_path / "micro_test.db"
        with get_rw_connection(db_file) as conn:
            conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
            conn.execute("INSERT INTO kv VALUES ('initial', 'val_0')")

        clear_micro_snapshots()
        errors = []
        lock = threading.Lock()

        def snapshot_worker(idx: int):
            try:
                # Concurrent snapshot creation with different snapshot_ids (2 slots max in FIFO)
                snap_id = f"snap_{idx}"
                res = create_micro_snapshot(db_path=db_file, snapshot_id=snap_id)
                assert res["status"] == "SUCCESS"
                assert res["in_ram"] is True

                # Concurrent list
                l_res = list_micro_snapshots()
                assert l_res["status"] == "OK"

                # Concurrent restore to a clone db
                clone_db = tmp_path / f"clone_{idx}.db"
                with get_rw_connection(clone_db) as conn:
                    conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
                r_res = restore_micro_snapshot(db_path=clone_db, snapshot_id=snap_id)
                assert r_res["status"] == "SUCCESS"
                assert r_res["restored"] is True
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=snapshot_worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in concurrent micro snapshots: {errors}"

        # Test FIFO eviction with 3rd snapshot: exactly one of the previous snapshots is evicted
        res_3 = create_micro_snapshot(db_path=db_file, snapshot_id="snap_3")
        assert res_3["status"] == "SUCCESS"
        l_res_after = list_micro_snapshots()
        assert l_res_after["count"] == 2
        assert "snap_3" in l_res_after["active_snapshots"]
        assert ("snap_0" in l_res_after["active_snapshots"]) ^ ("snap_1" in l_res_after["active_snapshots"])

        clear_micro_snapshots()

    def test_docs_vectorizer_thread_safety(self):
        holders = []
        errors = []
        lock = threading.Lock()

        def get_holder():
            try:
                v = server._get_docs_vectorizer()
                with lock:
                    holders.append(v)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=get_holder) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in concurrent _get_docs_vectorizer: {errors}"
        assert len(holders) == 4
        # Should either all be the same instance or all None if sqlite-vec is not installed
        assert len(set(id(h) for h in holders)) == 1


# ==============================================================================
# 9. Omission Gaps Remediation Suite (ONT-25)
# ==============================================================================

class TestOmissionGapsRemediation:
    def test_gap_om01_artifact_lint_and_vet_actions(self):
        async def _run():
            src_valid = 'package main\nimport "fmt"\nfunc main() { fmt.Println("Lint Passed") }\n'
            # 1. lint action
            r1 = json.loads(await server.artifact_lint_and_build(action="lint", go_source=src_valid))
            assert r1["status"] == "OK"
            assert r1["lint_passed"] is True

            # 2. vet action (alias)
            r2 = json.loads(await server.artifact_lint_and_build(action="vet", go_source=src_valid))
            assert r2["status"] == "OK"
            assert r2["vet_passed"] is True

            # 3. lint error detection
            src_err = 'package main\nimport "fmt"\nfunc main() { fmt.Printf("%d", "str") }\n'
            r3 = json.loads(await server.artifact_lint_and_build(action="lint", go_source=src_err))
            assert r3["status"] == "LINT_ERROR"
            assert r3["lint_passed"] is False

        asyncio.run(_run())

    def test_gap_om02_process_inspect_name_and_filter(self):
        async def _run():
            r1 = json.loads(await server.process_inspect(name="python"))
            assert r1["status"] == "OK"
            assert r1["total_matches"] > 0
            assert "processes" in r1

            r2 = json.loads(await server.process_inspect(filter="non_existent_daemon_xyz_123"))
            assert r2["status"] == "NOT_FOUND"

        asyncio.run(_run())

    def test_gap_om03_artifact_execute_in_ram_env_and_stdin(self):
        async def _run():
            go_src = (
                'package main\n'
                'import ("bufio"; "fmt"; "os"; "strings")\n'
                'func main() {\n'
                '    flag := os.Getenv("AEP_TEST_FLAG")\n'
                '    reader := bufio.NewReader(os.Stdin)\n'
                '    line, _ := reader.ReadString(\'\\n\')\n'
                '    fmt.Printf("FLAG=%s|STDIN=%s", flag, strings.TrimSpace(line))\n'
                '}\n'
            )
            b = json.loads(await server.artifact_lint_and_build(
                action="build",
                name="env_stdin_test_tool",
                intent="Test env and stdin",
                category="test",
                go_source=go_src,
            ))
            assert b["status"] == "SUCCESS"

            r = json.loads(await server.artifact_execute_in_ram(
                name="env_stdin_test_tool",
                env={"AEP_TEST_FLAG": "PASSED_VALUE"},
                stdin="input_data\n",
            ))
            assert r["status"] == "SUCCESS"
            assert "FLAG=PASSED_VALUE|STDIN=input_data" in r.get("output", "")

        asyncio.run(_run())

    def test_gap_om04_sandbox_run_env_injection(self):
        async def _run():
            r = json.loads(await server.sandbox_run(
                command='echo "KEY=$TEST_ENV_KEY"',
                env={"TEST_ENV_KEY": "INSIDE_SANDBOX_OK"},
            ))
            assert r["status"] == "SUCCESS"
            assert "KEY=INSIDE_SANDBOX_OK" in r.get("stdout", "")

        asyncio.run(_run())

    def test_gap_om05_kanban_board_add_and_move_aliases(self):
        async def _run():
            # add alias
            r_add = json.loads(await server.kanban_board(action="add", title="Test Add Alias Task"))
            assert r_add["status"] == "OK"
            tid = r_add["task_id"]

            # move alias
            r_move = json.loads(await server.kanban_board(action="move", task_id=tid, to_state="SYNTHESIZED"))
            assert r_move["status"] == "OK"
            assert r_move["state"] == "SYNTHESIZED"

        asyncio.run(_run())

    def test_gap_om06_async_job_dispatch_compact_status_pagination(self):
        async def _run():
            r = json.loads(await server.async_job_dispatch(action="status", verbosity="summary"))
            assert r["status"] == "OK"
            assert r["count"] <= 5
            assert r.get("truncated") is True
            telem = r.get("telemetry", {})
            assert telem.get("output_bytes", 0) < 4000

        asyncio.run(_run())


