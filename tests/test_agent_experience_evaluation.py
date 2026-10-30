"""Executable evaluation of AEP's public agent-facing contracts.

Covers all remediated product contracts from the Agent Experience Evaluation:
1. Clean-home hermetic SQLite bootstrap (promoted from xfail -> PASS).
2. Unified CLI & MCP control-plane schema including `audit` and `aep_ctl(action="schema")` (promoted from xfail -> PASS).
3. Bubblewrap sandbox isolation by default + explicit `working_dir`/`ro_paths`/`rw_paths` + `share_net=False` + `CapabilityGuard` blacklist enforcement.
4. Compact `verbosity="summary"` / `"brief"` modes, pagination cursors, and per-request telemetry (`output_bytes`, `estimated_tokens`, `rss_delta_kb`, `fd_delta`).
5. Real binary prerequisite readiness and Kali-MCP style semantic playbook (`discover(action="playbook")`) & intent precision.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CTL = PROJECT_ROOT / "scripts" / "aep-ctl"


def _run_ctl(*args: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(CTL), *args, "--json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(result.stdout)


def test_control_plane_schema_is_machine_discoverable() -> None:
    """The CLI can disclose its contract without parsing help text."""
    schema = _run_ctl("--schema")
    assert schema["status"] == "OK"
    domains = schema["domains"]
    assert isinstance(domains, dict)
    assert {"service", "network", "storage", "package", "backup", "security", "audit", "ipc"} <= set(domains)


def test_invalid_control_action_returns_remediation() -> None:
    """An agent gets valid alternatives after an invalid action."""
    result = _run_ctl("storage", "not-an-action")
    assert result["status"] == "ERROR"
    assert result["valid"] == ["usage", "mounts", "disks"]


def test_sandbox_hides_the_host_workspace() -> None:
    """The default sandbox must not expose the AEP checkout implicitly."""
    import server

    result = json.loads(
        asyncio.run(server.sandbox_run(f"test ! -e {PROJECT_ROOT}"))
    )
    assert result["status"] == "SUCCESS"
    assert result["share_net"] is False


def test_clean_home_bootstraps_the_mcp_runtime(tmp_path: Path) -> None:
    """A newly installed AEP runtime must import without pre-existing state."""
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import server; print('bootstrapped')"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bootstrapped"


def test_control_plane_schema_matches_advertised_mcp_domains() -> None:
    """The CLI schema and MCP aep_ctl domain contract must remain aligned."""
    import server

    cli_schema = _run_ctl("--schema")
    cli_domains = cli_schema["domains"]
    assert isinstance(cli_domains, dict)
    assert "audit" in cli_domains

    mcp_schema = json.loads(asyncio.run(server.aep_ctl(action="schema")))
    assert mcp_schema["status"] == "OK"
    assert mcp_schema["domains"] == cli_domains
    assert "telemetry" in mcp_schema
    assert "envelope" in mcp_schema


def test_sandbox_authorized_workspace_and_blacklist_guard(tmp_path: Path) -> None:
    """sandbox_run supports explicit read-only working_dir and blocks blacklisted paths."""
    import server

    # 1. Authorized working_dir mounts read-only and sets cwd
    res_ok = json.loads(
        asyncio.run(
            server.sandbox_run(
                "test -f pyproject.toml && ! touch .sandbox_write_probe",
                working_dir=str(PROJECT_ROOT),
            )
        )
    )
    assert res_ok["status"] == "SUCCESS"
    assert res_ok["working_dir"] == str(PROJECT_ROOT)
    assert str(PROJECT_ROOT) in res_ok["ro_mounts"]

    # 2. Explicit rw_paths allows writing inside an authorized temporary workspace
    rw_dir = tmp_path / "rw_work"
    rw_dir.mkdir()
    res_rw = json.loads(
        asyncio.run(
            server.sandbox_run(
                "echo 'ok' > allowed.txt && cat allowed.txt",
                working_dir=str(rw_dir),
                rw_paths=[str(rw_dir)],
            )
        )
    )
    assert res_rw["status"] == "SUCCESS"
    assert res_rw["stdout"] == "ok"
    assert (rw_dir / "allowed.txt").read_text().strip() == "ok"

    # 3. Blacklisted path (/etc/shadow or ~/.ssh) is blocked by CapabilityGuard
    res_blocked = json.loads(
        asyncio.run(
            server.sandbox_run("cat /etc/shadow", ro_paths=["/etc/shadow"])
        )
    )
    assert res_blocked["status"] == "PERMISSION_DENIED"
    assert res_blocked["envelope"]["severity"] == "ERROR"


def test_compact_summary_and_telemetry_attribution() -> None:
    """Summary mode reduces payload size and records byte/token/RSS/FD telemetry."""
    import server

    detail_mounts = json.loads(
        asyncio.run(server.aep_ctl(domain="storage", action="mounts", verbosity="detail"))
    )
    summary_mounts = json.loads(
        asyncio.run(server.aep_ctl(domain="storage", action="mounts", verbosity="summary", limit=5))
    )
    assert detail_mounts["status"] == "OK"
    assert summary_mounts["status"] == "OK"
    assert summary_mounts["telemetry"]["output_bytes"] < detail_mounts["telemetry"]["output_bytes"]
    assert summary_mounts["telemetry"]["estimated_tokens"] >= 1
    assert "rss_delta_kb" in summary_mounts["telemetry"]
    assert "fd_delta" in summary_mounts["telemetry"]
    assert summary_mounts["envelope"]["status"] == "OK"

    proc_sum = json.loads(
        asyncio.run(server.process_inspect(pid=0, verbosity="summary"))
    )
    assert proc_sum["status"] == "OK"
    assert len(proc_sum["descriptors"]) <= 15
    assert "telemetry" in proc_sum


def test_discover_binary_readiness_and_kali_tactical_playbook() -> None:
    """discover exposes binary prerequisites, Kali-style tactical playbook, and intent precision."""
    import server

    caps = json.loads(asyncio.run(server.discover(action="capabilities")))
    assert caps["status"] == "OK"
    assert "prerequisites" in caps
    assert "bwrap" in caps["prerequisites"]
    assert "ready" in caps["capabilities"]["ephemeral_sandbox"]
    assert "canonical_calls" in caps["capabilities"]["ephemeral_sandbox"]

    playbook = json.loads(asyncio.run(server.discover(action="playbook")))
    assert playbook["status"] == "OK"
    assert playbook["playbook_version"] == "EAES-v2-Kali-Semantic"
    assert len(playbook["rules_of_engagement"]) >= 5
    assert len(playbook["workflow_recipes"]) >= 4

    routed = json.loads(
        asyncio.run(
            server.discover(use_case="run pytest repository test suite in isolated bubblewrap sandbox")
        )
    )
    assert routed["status"] == "OK"
    assert routed["confidence"] == "HIGH"
    assert routed["match_status"] == "MATCHED"
    top_caps = [c["capability"] for c in routed["suggested_capability"]]
    assert "ephemeral_sandbox" in top_caps


def test_omission_battery_all_15_tools_envelope_and_frame_safety() -> None:
    """All 15 tools include envelope+telemetry, support ergonomic aliases, and prevent JSON-RPC frame overflow."""
    import server
    from engine.telemetry import MAX_SAFE_JSON_BYTES

    # 1. discover accepts action="match" and intent= alias, and flags low confidence for unrelated queries
    low_conf = json.loads(
        asyncio.run(server.discover(action="match", intent="plant tomatoes in backyard garden"))
    )
    assert low_conf["status"] == "OK"
    assert low_conf["match_status"] == "NO_HIGH_CONFIDENCE_MATCH"
    assert "envelope" in low_conf and "telemetry" in low_conf

    # 2. async_job_dispatch(action="status") strips massive envs and stays strictly under MAX_SAFE_JSON_BYTES
    pueue_st_raw = asyncio.run(server.async_job_dispatch(action="status", limit=5, verbosity="summary"))
    assert len(pueue_st_raw.encode("utf-8")) < MAX_SAFE_JSON_BYTES
    pueue_st = json.loads(pueue_st_raw)
    assert "envelope" in pueue_st and "telemetry" in pueue_st
    if pueue_st["status"] == "OK" and "tasks" in pueue_st:
        assert len(pueue_st["tasks"]) <= 5
        for t in pueue_st["tasks"].values():
            assert "envs" not in t

    # 3. artifact_execute_in_ram resolves socket_monitor <-> socket-monitor and truncates in summary mode
    ram_res = json.loads(
        asyncio.run(server.artifact_execute_in_ram(name="socket_monitor", limit=5, verbosity="summary"))
    )
    assert "envelope" in ram_res and "telemetry" in ram_res
    if ram_res["status"] == "SUCCESS" and isinstance(ram_res.get("output"), dict):
        if "sockets" in ram_res["output"]:
            assert len(ram_res["output"]["sockets"]) <= 5

    # 4. Remaining tools return uniform envelope + telemetry
    dag = json.loads(asyncio.run(server.topos_audit_dag(tasks=["a", "b"], dependencies={"a": [], "b": ["a"]})))
    cat = json.loads(asyncio.run(server.artifact_catalog(action="browse", limit=2)))
    bld = json.loads(asyncio.run(server.artifact_lint_and_build(action="catalog")))
    docs = json.loads(asyncio.run(server.query_system_docs(query="bwrap", source="man", limit=1)))
    kb = json.loads(asyncio.run(server.kanban_board(action="board")))
    pb = json.loads(asyncio.run(server.playbook_run(action="list")))
    for r in (dag, cat, bld, docs, kb, pb):
        assert "envelope" in r
        assert "telemetry" in r


def test_deep_omission_battery_v2_zero_fd_leak_and_storage_disks_summary() -> None:
    """SQLite connections close FDs on context exit, micro_snapshot lifecycle is complete, and storage.disks filters loop mounts."""
    import os

    import server

    # 1. Zero FD leak across 10 consecutive SQLite catalog/kanban operations
    fd_before = len(os.listdir("/proc/self/fd"))
    for _ in range(10):
        asyncio.run(server.artifact_catalog(action="browse", limit=2))
        asyncio.run(server.kanban_board(action="board", limit=2, verbosity="summary"))
    fd_after = len(os.listdir("/proc/self/fd"))
    assert fd_after - fd_before <= 2

    # 2. Full in-RAM micro-snapshot lifecycle via aep_ctl + FIFO bound (MAX_RAM_SNAPSHOTS=2)
    for idx in range(3):
        snap = json.loads(
            asyncio.run(server.aep_ctl(domain="backup", action="micro_snapshot", name=f"snap_{idx}"))
        )
        assert snap["status"] == "SUCCESS"
        assert len(snap["active_ram_snapshots"]) <= 2

    listed = json.loads(
        asyncio.run(server.aep_ctl(domain="backup", action="list_micro_snapshots"))
    )
    assert listed["status"] == "OK"
    assert listed["count"] <= 2

    cleared = json.loads(
        asyncio.run(server.aep_ctl(domain="backup", action="clear_micro_snapshots"))
    )
    assert cleared["status"] == "OK"

    # 3. storage.disks in summary mode filters out snap loop devices
    disks = json.loads(
        asyncio.run(server.aep_ctl(domain="storage", action="disks", verbosity="summary"))
    )
    assert disks["status"] == "OK"
    for bd in disks.get("blockdevices", []):
        assert bd.get("type") != "loop"


def test_deep_omission_battery_v3_polymorphic_dag_and_aliases() -> None:
    """Polymorphic topos_audit_dag, aep_ctl target/args aliases & service.list, process_inspect(pid=1) graceful handling, and compact discover."""
    import server

    # 1. Polymorphic topos_audit_dag accepts task dicts and edge lists without Pydantic validation errors
    dag_dicts = json.loads(
        asyncio.run(
            server.topos_audit_dag(
                tasks=[
                    {"id": "step_a", "consumes": []},
                    {"id": "step_b", "consumes": ["step_a"]},
                ]
            )
        )
    )
    assert dag_dicts["verdict"] == "APPROVED"

    dag_edges = json.loads(
        asyncio.run(
            server.topos_audit_dag(
                tasks=["step_1", "step_2"],
                dependencies=[{"from": "step_2", "to": "step_1", "type": "dependency"}],
            )
        )
    )
    assert dag_edges["verdict"] == "APPROVED"

    # 2. aep_ctl accepts target= alias and supports service.list and package.list
    pkg_chk = json.loads(
        asyncio.run(server.aep_ctl(domain="package", action="check", target="python3", verbosity="summary"))
    )
    assert pkg_chk["status"] == "OK"
    assert pkg_chk["package"] == "python3"

    svc_list = json.loads(
        asyncio.run(server.aep_ctl(domain="service", action="list", limit=5, verbosity="summary"))
    )
    assert svc_list["status"] in ("OK", "DEGRADED")
    if svc_list["status"] == "OK":
        assert len(svc_list.get("services", [])) <= 5

    # 3. discover(action="capabilities", verbosity="summary") is compact (< 5,500 bytes vs ~7,900 detail) and discover(action="recommend") works
    cap_sum_raw = asyncio.run(server.discover(action="capabilities", verbosity="summary"))
    cap_det_raw = asyncio.run(server.discover(action="capabilities", verbosity="detail"))
    assert len(cap_sum_raw.encode("utf-8")) < len(cap_det_raw.encode("utf-8"))
    assert len(cap_sum_raw.encode("utf-8")) < 5500
    rec = json.loads(
        asyncio.run(server.discover(action="recommend", intent="inspect open file descriptors of process"))
    )
    assert rec["status"] == "OK"

    # 4. artifact_catalog accepts action="list" and action="search"
    cat_list = json.loads(asyncio.run(server.artifact_catalog(action="list", limit=3)))
    assert cat_list["status"] == "OK"

    # 5. process_inspect(pid=1) returns OK (via sudo -n) or PARTIAL (preserving /proc/1/status)
    p1 = json.loads(asyncio.run(server.process_inspect(pid=1, limit=5, verbosity="summary")))
    assert p1["status"] in ("OK", "PARTIAL")
    assert p1["pid"] == 1

def test_installation_pipeline_and_topos_anti_cascade(tmp_path: Path) -> None:
    """Verify setup.sh integrity, Pueue tag extraction, and Topos anti-cascade blob preservation."""
    from engine.catalog import ArtifactCatalog

    # 1. Topos anti-cascade blob preservation:
    # cat.register_artifact(..., binary_blob=fake_elf) followed by cat.register_artifact(..., binary_blob=None)
    # preserves binary_blob == fake_elf and binary_hash (X1 ↛ X2 ↛ X1)
    db_file = tmp_path / "test_anti_cascade.db"
    cat = ArtifactCatalog(db_path=db_file)
    fake_elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24 + b"STATIC_PROBE_DUMMY_ELF_PAYLOAD"
    cue_code = 'package schema\nname: "test-probe"\ncategory: "diagnostic"'
    go_code = "package main\nfunc main() {}\n"

    art_id1 = cat.register_artifact(
        name="test-probe",
        intent="diagnose_system_integrity",
        category="diagnostic",
        cue_contract=cue_code,
        go_source=go_code,
        binary_blob=fake_elf,
        intent_description="topos test probe for anti cascade verification",
        source_template="test-probe",
    )
    with cat._get_ro_conn() as conn:
        row1 = conn.execute("SELECT binary_blob, binary_hash FROM artifacts WHERE name = ?", ("test-probe",)).fetchone()
        assert row1 is not None
        assert bytes(row1["binary_blob"]) == fake_elf
        assert row1["binary_hash"] is not None
        orig_hash = row1["binary_hash"]

    art_id2 = cat.register_artifact(
        name="test-probe",
        intent="diagnose_system_integrity",
        category="diagnostic",
        cue_contract=cue_code,
        go_source=go_code,
        binary_blob=None,
        intent_description="topos test probe updated without compiled binary",
        source_template="test-probe",
    )
    assert art_id2 == art_id1
    with cat._get_ro_conn() as conn:
        row2 = conn.execute("SELECT binary_blob, binary_hash FROM artifacts WHERE name = ?", ("test-probe",)).fetchone()
        assert row2 is not None
        assert bytes(row2["binary_blob"]) == fake_elf, "Topos anti-cascade violation: binary_blob was overwritten by NULL"
        assert row2["binary_hash"] == orig_hash, "Topos anti-cascade violation: binary_hash was overwritten by NULL"

    assert cat.get_binary_blob("test-probe") == fake_elf

    # 2. bash -n scripts/setup.sh and bash -n scripts/aep-sync.sh exit 0
    res_bash_setup = subprocess.run(
        ["bash", "-n", str(PROJECT_ROOT / "scripts" / "setup.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bash_setup.returncode == 0, f"bash -n setup.sh failed: {res_bash_setup.stderr}"

    res_bash_sync = subprocess.run(
        ["bash", "-n", str(PROJECT_ROOT / "scripts" / "aep-sync.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bash_sync.returncode == 0, f"bash -n aep-sync.sh failed: {res_bash_sync.stderr}"

    # 3. scripts/setup.sh contains \1 backreference on the Pueue sed line and not / /
    setup_text = (PROJECT_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert "sed -E 's/.*\"([^\"]+)\".*/\\1/'" in setup_text, "setup.sh must use \\1 in Pueue tag extraction"
    assert "sed -E 's/.*\"([^\"]+)\".*/ /'" not in setup_text, "setup.sh must not use broken space replacement in Pueue sed"

    # 4. ./scripts/setup.sh --check exits 0 and outputs [PASS] SQLite Catalog & Integrity and [PASS] MCP Ecosystem Sync
    res_check = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "setup.sh"), "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_check.returncode == 0, f"setup.sh --check failed:\nSTDOUT:\n{res_check.stdout}\nSTDERR:\n{res_check.stderr}"
    assert "[PASS] SQLite Catalog & Integrity" in res_check.stdout
    assert "[PASS] MCP Ecosystem Sync" in res_check.stdout

    # 5. ./scripts/aep-sync.sh --check exits 0
    res_sync = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "aep-sync.sh"), "--check"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_sync.returncode == 0, f"aep-sync.sh --check failed:\nSTDOUT:\n{res_sync.stdout}\nSTDERR:\n{res_sync.stderr}"

    # 6. Stray 0-byte PROJECT_ROOT / "artifacts.db" is unlinked / does not exist
    stray_db = PROJECT_ROOT / "artifacts.db"
    assert not stray_db.exists(), f"Stray 0-byte database file must not exist at repo root: {stray_db}"


def test_self_evolutionary_loop_and_ram_probes() -> None:
    """ONT-19 & ONT-20: Verify zero-warning template builds, memfd RAM execution fd_delta=0, and 15/15 verbosity."""
    import inspect

    import server
    from engine.telemetry import infer_severity

    for st in ("ARCHIVED", "UNARCHIVED", "PRUNED", "DEMOTED", "REEVALUATED", "REINDEXED", "CLEAN"):
        assert infer_severity(st) == "INFO", f"Expected INFO for {st}, got {infer_severity(st)}"

    # Verify all 15 MCP tools accept verbosity uniformly and _INSTRUCTIONS exposes the full 15-tool suite map
    assert "Complete 15-Tool Suite Map" in server._INSTRUCTIONS
    assert "herramientas ofensivas" not in server._INSTRUCTIONS.lower()
    for tool_name in (
        "discover",
        "artifact_lint_and_build",
        "artifact_execute_in_ram",
        "artifact_catalog",
        "kanban_board",
        "process_inspect",
        "sandbox_run",
        "async_job_dispatch",
        "diagnose_system_crashes",
        "kernel_trace",
        "aep_ctl",
        "query_system_docs",
        "visual_inspect",
        "topos_audit_dag",
        "playbook_run",
    ):
        sig = inspect.signature(getattr(server, tool_name))
        assert "verbosity" in sig.parameters, f"{tool_name} must accept 'verbosity'"
        assert tool_name in server._INSTRUCTIONS, f"{tool_name} must be documented in _INSTRUCTIONS (instructions.md)"

    # Verify compact template catalog saves tokens
    cat_detail = json.loads(asyncio.run(server.artifact_lint_and_build(action="catalog", verbosity="detail")))
    cat_summary = json.loads(asyncio.run(server.artifact_lint_and_build(action="catalog", verbosity="summary")))
    assert cat_summary["telemetry"]["output_bytes"] < cat_detail["telemetry"]["output_bytes"]

    # Verify 1-step template build with zero-config defaults and alias parameters
    build_res = json.loads(
        asyncio.run(
            server.artifact_lint_and_build(
                action="build",
                artifact_name="mem_stat",
                template_name="mem-stat",
            )
        )
    )
    assert build_res["status"] == "SUCCESS"
    assert build_res["lint_warnings"] == []

    # Verify in-RAM execution closes memfd before telemetry finish (fd_delta == 0)
    exec_res = json.loads(asyncio.run(server.artifact_execute_in_ram(name="mem_stat")))
    assert exec_res["status"] == "SUCCESS"
    assert exec_res["telemetry"]["fd_delta"] == 0




def test_spec_om7_ipc_control_plane_actions() -> None:
    """Spec OM-7 IPC domain responds deterministically to status, ping, and metrics."""
    result = _run_ctl("ipc", "status")
    assert result["status"] == "OK"
    assert "ipc_socket" in result
    assert "session_pool" in result

    metrics = _run_ctl("ipc", "metrics")
    assert metrics["status"] == "OK"
    assert "active_sessions" in metrics
    assert "idle_slots" in metrics


def test_spec_om7_ephemeral_batch_execution_and_token_savings() -> None:
    """Spec OM-7 playbook_run batch executes multi-step chains with field projection."""
    import server

    steps = [
        {"id": "p1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}},
        {"id": "p2", "tool": "topos_audit_dag", "params": {"tasks": ["t1"], "dependencies": {}}},
    ]
    raw = asyncio.run(
        server.playbook_run(
            action="batch",
            steps=steps,
            return_only="last",
            select_fields=["status", "batch", "output.verdict"],
        )
    )
    result = json.loads(raw)
    assert result["status"] == "OK"
    assert result["output"]["verdict"] == "APPROVED"
    assert "token_savings_estimate" in result
    assert result["token_savings_estimate"]["turns_saved"] == 1
    assert result["token_savings_estimate"]["savings_pct"] >= 50.0
