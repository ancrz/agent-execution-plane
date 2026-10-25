"""Comprehensive Engine & Security Test Suite for Agent Execution Plane (AEP).

Covers:
- engine/db.py: Connection pooling, read-only vs read-write, WAL mode, transaction_immediate.
- engine/backup.py: 5-slot FIFO rotation, hot streaming, SHA-256 verification, restore with sidecar cleanup, corruption auto-recovery.
- engine/privilege.py: CapabilityGuard, path blacklist enforcement (/etc/shadow, /root, ~/.ssh), 18 capabilities, multi-agent context.
- engine/security.py: record_audit_event, verify_audit_chain, mask_secrets, SHA-256 chained tamper-evident ledger.
- server.py: FastMCP 15 tools registration and capability manifest parity.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is in sys.path for server import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.backup import (  # noqa: E402
    MAX_BACKUP_SLOTS,
    compute_file_sha256,
    create_backup,
    get_backup_status,
    restore_backup,
    verify_and_auto_recover,
    verify_db_integrity,
)
from engine.db import (  # noqa: E402
    get_db_telemetry,
    get_ro_connection,
    get_rw_connection,
    transaction_immediate,
)
from engine.privilege import (  # noqa: E402
    CapabilityGuard,
    PermissionDenied,
    capability_manifest,
)
from engine.security import (  # noqa: E402
    mask_secrets,
    record_audit_event,
    verify_audit_chain,
)

# ==============================================================================
# 1. Database Engine Tests (engine/db.py)
# ==============================================================================

class TestDatabaseEngine:
    def test_ro_connection_is_read_only(self, tmp_path: Path):
        db_path = tmp_path / "test_ro.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO items (name) VALUES ('alpha')")
            conn.commit()

        ro_conn = get_ro_connection(str(db_path))
        try:
            cur = ro_conn.execute("SELECT name FROM items WHERE id = 1")
            assert cur.fetchone()[0] == "alpha"

            with pytest.raises(sqlite3.OperationalError):
                ro_conn.execute("INSERT INTO items (name) VALUES ('beta')")
        finally:
            ro_conn.close()

    def test_rw_connection_wal_mode(self, tmp_path: Path):
        db_path = tmp_path / "test_rw.db"
        rw_conn = get_rw_connection(str(db_path))
        try:
            cur = rw_conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0].lower()
            assert mode == "wal"

            cur = rw_conn.execute("PRAGMA busy_timeout")
            timeout = cur.fetchone()[0]
            assert timeout == 10000
        finally:
            rw_conn.close()

    def test_transaction_immediate_context(self, tmp_path: Path):
        db_path = tmp_path / "test_tx.db"
        rw_conn = get_rw_connection(str(db_path))
        try:
            rw_conn.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
            with transaction_immediate(rw_conn):
                rw_conn.execute("INSERT INTO kv (k, v) VALUES ('foo', 'bar')")

            cur = rw_conn.execute("SELECT v FROM kv WHERE k = 'foo'")
            assert cur.fetchone()[0] == "bar"
        finally:
            rw_conn.close()

    def test_db_telemetry(self, tmp_path: Path):
        db_path = tmp_path / "test_telemetry.db"
        rw_conn = get_rw_connection(str(db_path))
        try:
            telemetry = get_db_telemetry(rw_conn)
            assert telemetry["journal_mode"].lower() == "wal"
            assert telemetry["busy_timeout_ms"] == 10000
            assert telemetry["mmap_size_mb"] == 256
            assert telemetry["wal_autocheckpoint"] == 1000
        finally:
            rw_conn.close()


# ==============================================================================
# 2. Backup & Rotation Engine Tests (engine/backup.py)
# ==============================================================================

class TestBackupEngine:
    def test_backup_and_5_slot_rotation(self, tmp_path: Path):
        db_path = tmp_path / "artifacts.db"
        backups_dir = tmp_path / "backups"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO data (val) VALUES ('initial')")
            conn.commit()

        # Rotate up to 6 times to verify FIFO pool truncation
        for i in range(1, MAX_BACKUP_SLOTS + 2):
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("INSERT INTO data (val) VALUES (?)", (f"run_{i}",))
                conn.commit()
            meta = create_backup(db_path=db_path, backups_dir=backups_dir)
            assert meta["status"] == "SUCCESS"
            assert meta["slot"] == 1
            slot1_file = backups_dir / meta["filename"]
            assert slot1_file.exists()

        status = get_backup_status(backups_dir=backups_dir)
        assert status["status"] == "OK"
        assert status["active_slots"] == MAX_BACKUP_SLOTS

        # Verify slot 1 has latest data
        slot1_db = backups_dir / "artifacts.db.bak.1"
        with sqlite3.connect(str(slot1_db)) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM data")
            assert cur.fetchone()[0] == MAX_BACKUP_SLOTS + 2

        # Verify slot 6 does NOT exist (pool capped at 5)
        assert not (backups_dir / "artifacts.db.bak.6").exists()

    def test_backup_verification_checksum(self, tmp_path: Path):
        db_path = tmp_path / "test_verify.db"
        backups_dir = tmp_path / "backups"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE test (x INT)")
            conn.commit()

        meta = create_backup(db_path=db_path, backups_dir=backups_dir)
        bak_file = backups_dir / meta["filename"]

        # Genuine verification
        assert verify_db_integrity(bak_file) is True
        expected_sha = meta["sha256"]
        actual_sha = compute_file_sha256(bak_file)
        assert actual_sha == expected_sha

        # Tamper with file
        with open(bak_file, "ab") as f:
            f.write(b"tampered_bytes")

        tampered_sha = compute_file_sha256(bak_file)
        assert tampered_sha != expected_sha

    def test_restore_and_sidecar_cleanup(self, tmp_path: Path):
        db_path = tmp_path / "test_restore.db"
        backups_dir = tmp_path / "backups"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE items (id INT, txt TEXT)")
            conn.execute("INSERT INTO items VALUES (1, 'backup_content')")
            conn.commit()

        create_backup(db_path=db_path, backups_dir=backups_dir)

        # Mutate live DB and create sidecars
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("DELETE FROM items")
            conn.commit()

        wal_file = tmp_path / "test_restore.db-wal"
        shm_file = tmp_path / "test_restore.db-shm"
        wal_file.write_text("dummy wal")
        shm_file.write_text("dummy shm")

        # Restore from slot 1
        res = restore_backup(slot_number=1, db_path=db_path, backups_dir=backups_dir)
        assert res["status"] == "SUCCESS"
        assert res["integrity_verified"] is True
        assert not wal_file.exists()
        assert not shm_file.exists()

        # Check restored content
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute("SELECT txt FROM items WHERE id = 1")
            assert cur.fetchone()[0] == "backup_content"

    def test_auto_recovery_on_corrupt_database(self, tmp_path: Path):
        db_path = tmp_path / "test_auto_rec.db"
        backups_dir = tmp_path / "backups"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE status (msg TEXT)")
            conn.execute("INSERT INTO status VALUES ('healthy')")
            conn.commit()

        create_backup(db_path=db_path, backups_dir=backups_dir)

        # Corrupt DB file
        db_path.write_bytes(b"NOT A VALID SQLITE HEADER CORRUPTED FILE")

        res = verify_and_auto_recover(db_path=db_path, backups_dir=backups_dir)
        assert res["status"] == "AUTO_RECOVERED"
        assert res["recovered"] is True

        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute("SELECT msg FROM status")
            assert cur.fetchone()[0] == "healthy"


# ==============================================================================
# 3. Privilege & CapabilityGuard Tests (engine/privilege.py)
# ==============================================================================

class TestPrivilegeAndCapabilityGuard:
    def test_18_capabilities_manifest(self):
        manifest = capability_manifest()
        caps = manifest["capabilities"]
        assert len(caps) == 18
        assert "backup_admin" in caps
        assert "audit_read" in caps
        assert "ram_execution" in caps
        assert "ephemeral_sandbox" in caps

    def test_guard_blocks_blacklisted_paths(self):
        # /etc/shadow
        assert CapabilityGuard.is_path_blacklisted("/etc/shadow") is True
        with pytest.raises(PermissionDenied) as exc_info:
            CapabilityGuard.verify_action(
                agent_id="tester",
                capability="filesystem_mutation",
                action="write",
                target="/etc/shadow",
            )
        assert "restringida" in str(exc_info.value).lower()

        # /root
        assert CapabilityGuard.is_path_blacklisted("/root/secret") is True

        # ~/.ssh
        ssh_key = str(Path.home() / ".ssh" / "id_rsa")
        assert CapabilityGuard.is_path_blacklisted(ssh_key) is True

    def test_guard_allows_safe_workspace_paths(self, tmp_path: Path):
        safe_file = str(tmp_path / "safe.txt")
        assert CapabilityGuard.is_path_blacklisted(safe_file) is False
        check = CapabilityGuard.check_action(
            agent_id="tester",
            capability="filesystem_mutation",
            action="write",
            target=safe_file,
        )
        assert check["allowed"] is True

    def test_multi_agent_caller_audit(self):
        check = CapabilityGuard.check_action(
            agent_id="agent_gamma",
            capability="ram_execution",
            action="execute",
            target="socket-monitor",
        )
        assert check["status"] == "ALLOWED"
        assert check["agent_id"] == "agent_gamma"


# ==============================================================================
# 4. Security Audit Log Tests (engine/security.py)
# ==============================================================================

class TestSecurityAuditLog:
    def test_chained_tamper_evident_ledger(self, tmp_path: Path):
        db_path = tmp_path / "audit.db"
        with sqlite3.connect(str(db_path)) as conn:
            entry1 = record_audit_event(
                conn=conn,
                agent_id="agent_1",
                tool_name="artifact_execute_in_ram",
                action="execute_probe",
                capability_tier="DIMINISHED",
                status="SUCCESS",
                target="socket-monitor",
            )
            assert "entry_hash" in entry1
            assert "prev_hash" in entry1

            entry2 = record_audit_event(
                conn=conn,
                agent_id="agent_2",
                tool_name="aep_ctl",
                action="create_backup",
                capability_tier="DIMINISHED",
                status="SUCCESS",
                target="artifacts.db.bak.1",
            )
            assert entry2["prev_hash"] == entry1["entry_hash"]

            # Verify chain integrity
            v = verify_audit_chain(conn)
            assert v["valid"] is True
            assert v["total_verified"] == 2

    def test_chain_detects_tampering(self, tmp_path: Path):
        db_path = tmp_path / "audit_tamper.db"
        with sqlite3.connect(str(db_path)) as conn:
            record_audit_event(
                conn,
                agent_id="agent_1",
                tool_name="tool_a",
                action="act_a",
                capability_tier="DIMINISHED",
                status="SUCCESS",
            )
            record_audit_event(
                conn,
                agent_id="agent_2",
                tool_name="tool_b",
                action="act_b",
                capability_tier="DIMINISHED",
                status="SUCCESS",
            )

            # Tamper with row 1 in SQLite table
            conn.execute("UPDATE security_audit_log SET action = 'tampered' WHERE id = 1")
            conn.commit()

            v = verify_audit_chain(conn)
            assert v["valid"] is False
            assert "error" in v
            err = v["error"].lower()
            assert "manipulación" in err or "discrepancia" in err or "enlace roto" in err

    def test_mask_secrets(self):
        text = "Authorization: Bearer sk-1234567890abcdef1234567890abcdef and password=SuperSecretPassword!"
        masked = mask_secrets(text)
        assert "sk-1234567890abcdef1234567890abcdef" not in masked
        assert "SuperSecretPassword!" not in masked
        assert "[MASKED]" in masked


# ==============================================================================
# 5. FastMCP Server Parity Tests (server.py)
# ==============================================================================

class TestServerFastMCPParity:
    def test_15_tools_registered(self):
        import server
        tools = server.mcp._tool_manager.list_tools()
        tool_names = {t.name for t in tools}
        expected_15_tools = {
            "discover",
            "topos_audit_dag",
            "artifact_catalog",
            "artifact_lint_and_build",
            "artifact_execute_in_ram",
            "process_inspect",
            "sandbox_run",
            "async_job_dispatch",
            "diagnose_system_crashes",
            "kernel_trace",
            "aep_ctl",
            "query_system_docs",
            "visual_inspect",
            "kanban_board",
            "playbook_run",
        }
        assert expected_15_tools.issubset(tool_names)
        assert len(expected_15_tools) == 15

    def test_discover_capabilities_contract(self):
        import server
        res_str = asyncio.run(server.discover(action="capabilities"))
        res = json.loads(res_str)
        assert res["capability_tier"] in ("FULL", "DIMINISHED")
        assert "capabilities" in res
        assert len(res["capabilities"]) == 18
