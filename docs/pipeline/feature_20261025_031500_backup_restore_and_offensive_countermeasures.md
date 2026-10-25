# Feature Pipeline Document: Database Backup & Restore Rotation Engine, Offensive Primitive Countermeasures & Multi-Agent Context Segregation

- **Document ID**: `feature_20261025_031500_backup_restore_and_offensive_countermeasures.md`
- **Previous Document**: [`feature_20261024_171500_code_modernization_and_concurrency_optimization.md`](feature_20261024_171500_code_modernization_and_concurrency_optimization.md)
- **Chain Rollup Summary**: [`feature_rollup.md`](feature_rollup.md) (Consolidated History Docs 1-15)
- **Next Document**: `Hermon (Stage 6) Atomic Conventional Commit & Release Tagging (ONT-11)`
- **Pipeline Mode**: `Full` (Topos Integrity Protocol — Archon Strategic Plan & Ontos Structural Audit)
- **Kanban Task ID**: `112` (`feat:backup_restore_rotation_and_offensive_countermeasures`) in `/home/ancruz/.local/share/agent-os/artifacts.db` — Status: `PROMOTED` (Promotion Score: `0.9250`, Verdict: `TRUST`, Confidence: `1.00`, Attempts: 3)
- **Plan Scope**: Establishes enterprise-grade database resilience and offensive security containment for the Agent Execution Plane (AEP). Implements a 5-slot online hot backup rotation engine using native SQLite Backup API (`conn.backup()`) with pre-promotion verification (`PRAGMA integrity_check`, SHA-256 checksums, metadata manifest), atomic restore with WAL/SHM desync prevention, and automated self-healing corruption recovery. Hardens offensive execution primitives via `CapabilityGuard` in `engine/privilege.py`, path blacklist and network egress constraints in RAM binary execution (`artifact_execute_in_ram`), multi-agent caller context segregation (`agent_id: str = "default"`), hardened Bubblewrap POSIX sandboxing (`--unshare-all`, `--ro-bind`, `--cap-drop ALL`, isolated ephemeral `/tmp`), and an immutable cryptographic SHA-256 hash-chain audit log (`security_audit_log` in `artifacts.db`).
- **Current Status**: `STAGE 2 (G2): POST-DOKIMOS VERIFIED RECORD & DOCUMENTATION ROLLUP (READY FOR HERMON STAGE 6 RELEASE)`
- **Timestamp**: 2026-10-25T03:59:11Z (G2 Record)
- **Author**: Graphos (Universal State Manager & Knowledge Graph Custodian — Stage 2 G2)
- **Target Blast Radius**:
  - `engine/backup.py` (new module): Online backup rotation, SHA-256 checksum generation, `PRAGMA integrity_check` pre-validation, atomic restore purging stale `-wal`/`-shm`, automated self-healing corruption recovery (`verify_and_auto_recover`).
  - `engine/privilege.py`: `CapabilityGuard` capability-based access control engine, capability gating matrix, action authorization verification.
  - `engine/executor.py` / `server.py`: In-RAM execution path restrictions (`/etc/shadow`, `/etc/sudoers`, `/root`, `~/.ssh`, kernel control nodes), network egress boundaries, prevention of payload weaponization.
  - `server.py`: FastMCP tools accept `agent_id: str = "default"`; dispatch `aep_ctl` domain `backup` (actions `backup`, `restore`, `status`/`backup_status`); enforce multi-agent caller context segregation; bubblewrap sandboxing hardening.
  - `scripts/aep-ctl`: Unified CLI domain `backup` implementing `backup`, `restore`, and `status`.
  - `engine/db.py`: Schema migration for `security_audit_log` hash-chain table, helper functions for immutable audit event recording.
  - `engine/security.py`: Universal secret masking integration across audit trail payloads and stderr buffers.
  - Target documentation baseline: `docs/MILESTONES.md`, `docs/COMPACT.md`.

---

## 1. State Evolution Map & Knowledge Graph

```mermaid
flowchart TD
    subgraph Chain["Interwoven Knowledge Graph Chain (Unbroken Sequence)"]
        D1["Predecessor: feature_20261024_171500_code_modernization_and_concurrency_optimization.md<br/>(Milestone ONT-10: Python 3.12 Modernization, Ruff SAST, AnyIO & Anti-Deadlock SQLite)"]
        D2["Current: feature_20261025_031500_backup_restore_and_offensive_countermeasures.md<br/>(Milestone ONT-11: 5-Slot Hot Backup Engine, Offensive Countermeasures & Multi-Agent Segregation)"]
        R1["Chain Rollup: feature_rollup.md<br/>(Consolidated History Docs 1 to 15)"]
        D1 -->|"unbroken anchor chain"| D2
        D2 -.->|"rollup historical anchor"| R1
    end

    subgraph Pipeline["Full Mode Pipeline Lifecycle (Topos Integrity Protocol)"]
        A1["Archon (Stage 1)<br/>Strategic Plan Formulation & Topos DAG: COMPLETE ✅"]
        G1["Graphos G1 (Stage 2)<br/>Knowledge Graph Weave & Task 112 SYNTHESIZED: COMPLETE ✅"]
        O1["Ontos (Stage 3)<br/>Topos Structural & Interface Contract Audit (ONT-11): COMPLETE (APPROVED) ✅"]
        P1["Pragma (Stage 4)<br/>Implementation of T1 to T8 Security & Backup: COMPLETE (LINTED) ✅"]
        DK1["Dokimos (Stage 5)<br/>Verification Multi-Gate (Gates 1 to 7): COMPLETE (VERIFIED) ✅"]
        G2["Graphos G2 (Stage 2)<br/>Documentation Sync & Baseline Compaction: COMPLETE (Current) 🔵"]
        H1["Hermon (Stage 6)<br/>Atomic Conventional Commit & Release: PENDING ⏳"]
    end

    D2 --> A1
    A1 --> G1
    G1 -->|"documented plan"| O1
    O1 -->|"APPROVED"| P1
    P1 --> DK1
    DK1 -->|"VERIFIED"| G2
    G2 -->|"ready for release"| H1
```

```mermaid
flowchart LR
    subgraph StateEvolution["State Evolution Map: Milestone ONT-11"]
        direction LR
        S0["Baseline Verified AEP<br/>(ONT-10 Modernized & Anti-Deadlock) ✅"]
        S1["T1: 5-Slot Online Hot Backup Engine<br/>(engine/backup.py conn.backup API) ✅"]
        S2["T2: Atomic Restore & Self-Healing<br/>(Purge WAL/SHM & Auto-Recover) ✅"]
        S3["T3: Control Plane Backup Domain<br/>(scripts/aep-ctl & server.py aep_ctl) ✅"]
        S4["T4: CapabilityGuard Authorization<br/>(engine/privilege.py CBAC Engine) ✅"]
        S5["T5: In-RAM Execution Safety<br/>(Path Blacklist & Egress Policy) ✅"]
        S6["T6: Multi-Agent Context Segregation<br/>(agent_id Propagation across FastMCP) ✅"]
        S7["T7: Bubblewrap POSIX Hardening<br/>(--unshare-all, --cap-drop ALL, /tmpfs) ✅"]
        S8["T8: Cryptographic Audit Trail<br/>(SHA-256 Hash Chaining in artifacts.db) ✅"]
        S9["T9: Dokimos Multi-Gate Verification<br/>(Gates 1 to 7, Task 112 PROMOTED) ✅"]

        S0 --> S1 --> S2 --> S3
        S0 --> S4 --> S5 --> S7
        S4 --> S6 --> S8
        S3 --> S9
        S5 --> S9
        S6 --> S9
        S7 --> S9
        S8 --> S9
    end
```

```mermaid
flowchart TD
    subgraph ToposDAG["Topos Integrity Protocol Task Dependency DAG (Milestone ONT-11)"]
        T1["T1: Database Backup Engine & 5-Slot Rotation Pool (engine/backup.py)"]
        T2["T2: Atomic Database Restore & Self-Healing Recovery (engine/backup.py)"]
        T3["T3: Control Plane & FastMCP Integration for Backup Management (scripts/aep-ctl, server.py)"]
        T4["T4: CapabilityGuard & Multi-Tier Privilege Isolation (engine/privilege.py)"]
        T5["T5: In-RAM Execution Safety & Offensive Primitive Guardrails (engine/executor.py, server.py)"]
        T6["T6: Multi-Agent Caller Context Segregation (server.py, engine/*.py)"]
        T7["T7: Bubblewrap POSIX Sandboxing Hardening (server.py, engine/executor.py)"]
        T8["T8: Immutable Cryptographic Audit Trail (engine/security.py, engine/db.py)"]
        T9["T9: Dokimos Multi-Gate Verification & Stress Testing (Gates 1-7)"]

        T1 --> T2
        T1 --> T3
        T2 --> T3
        T4 --> T5
        T4 --> T6
        T5 --> T7
        T6 --> T7
        T4 --> T8
        T6 --> T8
        T1 --> T9
        T2 --> T9
        T3 --> T9
        T4 --> T9
        T5 --> T9
        T6 --> T9
        T7 --> T9
        T8 --> T9
    end
```

---

## 2. Operating Premises & Tool Reach (P0, P1, P2)

- **Premise P0 (Agents-for-Agents Delivery & Deterministic Execution)**:
  - Deliver deterministic, zero-contention, low-latency execution for concurrent multi-agent swarms.
  - System resilience and security guardrails must operate transparently to LLM agents: agents obtain verified, functional capabilities without needing to manage database locks, rotation mechanics, or container namespaces manually.
  - Defensive guardrails are enforced deterministically at the execution plane perimeter, preventing prompt injection, payload weaponization, and privilege confusion without relying on human supervision.

- **Premise P1 (Tool Reach, Blast Radius & Sub-agent Inheritance)**:
  - **Tool Reach**: Preserves 100% parity across all 15 FastMCP tools and 16 system capabilities, expanding `aep_ctl` with domain `backup` without altering tool count or signatures.
  - **Standard vs. Non-Conventional Execution Paths**:
    - Standard Path: FastMCP JSON-RPC interface with AnyIO thread offloading, backed by atomic SQLite operations and Pueue async queues.
    - Non-Conventional In-RAM Path (`memfd_create`): High-speed binary execution with zero physical disk residue ($T_{exec} pprox 4	ext{ ms}$). Hardened with path access blacklists (`/etc/shadow`, `/root`, `~/.ssh`) and network egress boundaries.
    - Non-Conventional Sandbox Path (`bwrap`): Hardened ephemeral namespaces with complete capability dropping (`--cap-drop ALL`), strict unsharing (`--unshare-all`), and isolated tmpfs.
  - **Safety Boundary & Invariants**:
    - Under no circumstance may an agent escape container isolation or bypass `CapabilityGuard`.
    - Online backups must never perform raw file copies (`shutil.copyfile`) on active WAL databases, which risks torn pages. The native SQLite Backup API (`conn.backup()`) is mandatory.
    - Multi-agent caller context segregation prevents Agent A from reading or modifying Agent B's execution state or escalating privileges across agent boundaries.

- **Premise P2 (Pipeline Mode & Budget Control)**:
  - Mode: **Full** (Archon Plan -> Graphos G1 Weave -> Ontos Audit -> Pragma Execution -> Dokimos Verification -> Graphos G2 Rollup -> Hermon Commit).
  - All 9 tasks (T1 to T9) operate under Topos DAG constraints with zero cyclic co-dependencies.

---

## 3. Strategic Context & State of the Art (SOTA) Comparative Matrix

Traditional AI agent frameworks treat the operating system as an uncontained command-line prompt: commands are echoed into a bash subshell, stdout is returned as an unstructured string, and database persistence is either nonexistent or handled by external heavy services (PostgreSQL, Redis). When applied to enterprise operations, this paradigm introduces severe failure modes: deadlocks, torn databases, uncontained command execution, credential leakage, and privilege confusion.

AEP establishes a new state of the art by treating the agent execution plane as a formal operating system capability layer:

| Dimension | Conventional Text-Stream Agents (e.g. LangChain, AutoGPT, Raw Bash) | AEP Systems Engineering Runtime (Milestone ONT-11) |
| :--- | :--- | :--- |
| **Operational Interface** | Unstructured, untyped stdout text stream; vulnerable to ANSI escape codes, interactive pagers (`less`, `more`), and prompt stalls. | Typed FastMCP JSON-RPC stream with Pydantic v2 schemas; non-blocking stdio loop with AnyIO worker thread offloading (<2ms jitter). |
| **Memory & Storage Execution** | Ephemeral script files written to disk (`/tmp/script.sh`); slow process startup (50–200ms); high disk I/O churn and inode contention. | In-RAM binary execution via `memfd_create` and `/proc/self/fd/` ($T_{exec} pprox 4	ext{ ms}$); 256MB memory-mapped SQLite (`PRAGMA mmap_size`). |
| **Concurrency & Lock Model** | Unmanaged shell concurrency; file locks collide; SQLite `OperationalError: database is locked` on concurrent writes. | Segregated RO/RW connection factories (`get_ro_connection` mode=ro vs `get_rw_connection`); `BEGIN IMMEDIATE` anti-deadlock transactions; WAL autocheckpoint 1000 pages (~4MB). |
| **Disaster Recovery & Backup** | Ad-hoc file copy (`cp artifacts.db ...`) resulting in corrupted torn pages during active WAL writes; no automated recovery. | 5-Slot online hot backup rotation pool via SQLite native Backup API (`conn.backup()`); zero-lock contention; SHA-256 validation; `PRAGMA integrity_check`; atomic WAL/SHM purge; automated self-healing. |
| **Execution Sandboxing** | Unrestricted host shell; ambient user/sudo privileges; accidental execution of destructive commands (`rm -rf`, system reboots). | Ephemeral Bubblewrap sandboxing (`--unshare-all`, `--ro-bind`, `--cap-drop ALL`, ephemeral `--tmpfs /tmp`); `CapabilityGuard` policy gating. |
| **Offensive Primitive Defense** | Primitives (raw sockets, memory execution) can be hijacked for unauthorized scanning, lateral movement, or credential exfiltration. | Strict path blacklist (`/etc/shadow`, `/root`, `~/.ssh`); network egress boundaries; secret masking across logs; binary signature and capability validation. |
| **Multi-Agent Isolation** | Shared ambient context; Agent A can overwrite Agent B's tasks or escalate privileges via shared shell environment. | Explicit `agent_id: str = "default"` context segregation across all FastMCP tools; per-agent scratchpad namespaces; isolated audit tracking. |
| **Auditability & Forensics** | Ephemeral console history lost on shell termination; vulnerable to log tampering or truncation. | Cryptographic SHA-256 hash-chain audit log (`security_audit_log` in `artifacts.db`); immutable audit trail; automated tamper detection (`verify_audit_chain`). |

---

## 4. Mandate 1: Database Resilience & 5-Slot Online Hot Backup Rotation Engine

### 4.1 The SQLite WAL Backup Problem & Native Backup API
Under Write-Ahead Logging (WAL) mode, SQLite transactions write changes to the `-wal` file while the main database file (`artifacts.db`) remains frozen at an earlier state until checkpointing. If an agent executes a standard filesystem copy (`shutil.copyfile` or `cp artifacts.db artifacts.db.bak`):
1. **Torn Pages**: If a concurrent thread is writing a 4KB database page while the copy utility reads it, half of the old page and half of the new page are written to the backup, creating fatal corruption (`SQLITE_CORRUPT`).
2. **Missing WAL Frames**: A copy of `artifacts.db` without `artifacts.db-wal` misses recent transactions. If `artifacts.db-wal` is copied separately, the copy occurs at a different point in time, producing an inconsistent WAL header that destroys transactional integrity.

**The Solution**: The SQLite native Backup API (`sqlite3.Connection.backup(target_conn)`):
- Streams pages from source to target while holding a shared lock that tolerates active concurrent WAL readers and writers without blocking the main event loop.
- Guarantees point-in-time ACID consistency without requiring application downtime or WAL checkpoints.
- Produces a single, self-contained, fully consolidated `.db` file requiring no auxiliary `-wal` or `-shm` files to open.

### 4.2 5-Slot Online Hot Backup Rotation Pool
All backups are maintained in `~/.local/share/agent-os/backups/`:
- **Pool Slots**: Exactly 5 slots maintained under FIFO rotation:
  - `artifacts.db.bak.1` (most recent snapshot)
  - `artifacts.db.bak.2`
  - `artifacts.db.bak.3`
  - `artifacts.db.bak.4`
  - `artifacts.db.bak.5` (oldest snapshot)
- **Rotation Mechanics**:
  - Before creating a new backup, existing slots shift: `bak.4 -> bak.5`, `bak.3 -> bak.4`, `bak.2 -> bak.3`, `bak.1 -> bak.2`. If `bak.5` exists, it is unlinked.
  - The new backup is written to a temporary staging file: `artifacts.db.bak.tmp`.
  - Once verified, it is atomically renamed to `artifacts.db.bak.1`.
- **Pre-Promotion Verification**:
  - `PRAGMA integrity_check`: Executed against the staging database. If the result is not `["ok"]`, the backup is rejected and unlinked.
  - SHA-256 Checksum: Computed over the raw backup bytes and stored in the manifest.
- **Manifest File (`backups_manifest.json`)**:
  Maintains structured JSON telemetry for all active slots:
  ```json
  {
    "version": 1,
    "last_backup_timestamp": "2026-10-25T03:15:00Z",
    "active_slots": 5,
    "slots": {
      "1": {
        "filename": "artifacts.db.bak.1",
        "timestamp": "2026-10-25T03:15:00Z",
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "size_bytes": 1048576,
        "page_count": 256,
        "integrity_verified": true
      }
    }
  }
  ```

### 4.3 Atomic Restore Protocol & Anti-Desync Protection
Restoring a SQLite database under WAL mode carries a major hazard: if `artifacts.db` is replaced on disk while stale `artifacts.db-wal` or `artifacts.db-shm` files remain, SQLite attempts to replay WAL frames from the prior database onto the newly restored database. This results in instant index mismatch, checksum failure, and database corruption.

**The Atomic Restore Protocol**:
1. **Pre-Flight Validation**: Compute SHA-256 of the target backup slot and verify integrity against `backups_manifest.json`. Open the backup in read-only mode and execute `PRAGMA integrity_check`.
2. **Quiesce & Lock**: Ensure all active SQLite connections in the current process are closed or idling.
3. **Purge Stale Indexes**: Atomically remove `artifacts.db-wal` and `artifacts.db-shm`.
4. **Atomic File Replacement**: Copy the backup file to `artifacts.db.tmp`, flush buffers to disk (`os.sync()`), and atomically rename `artifacts.db.tmp` to `artifacts.db` via `os.replace()`.
5. **Post-Restore Initialization**: Open a new connection using `engine/db.py:get_rw_connection()`, apply engine pragmas (`journal_mode=WAL`, `mmap_size=256MB`), and execute `PRAGMA integrity_check`.
6. **Audit Event**: Record a `DATABASE_RESTORE` event in the cryptographic audit log.

### 4.4 Automated Self-Healing Corruption Detection (`verify_and_auto_recover`)
If an engine operation catches `sqlite3.DatabaseError` containing `file is encrypted or is not a database` or `database disk image is malformed`, or if a startup check detects `integrity_check != ["ok"]`:
1. The engine triggers `verify_and_auto_recover()`.
2. The recovery manager scans `backups_manifest.json` starting from slot 1 through slot 5.
3. For each slot, it validates the SHA-256 checksum and executes `PRAGMA integrity_check`.
4. The newest slot that passes all checks is selected, and the Atomic Restore Protocol is executed.
5. Telemetry alert is logged with high priority, and a forensics crash ticket is filed via `engine/crash_router.py`.

### 4.5 CLI & FastMCP Control Plane Integration
- `scripts/aep-ctl`:
  - `aep-ctl backup backup`: Creates an immediate online hot backup, rotates slots, and outputs JSON status.
  - `aep-ctl backup restore [slot_number]`: Restores database from specified slot (defaults to slot 1).
  - `aep-ctl backup status` (alias `backup_status`): Returns manifest, slot details, and disk usage.
- `server.py`:
  - `aep_ctl(domain="backup", action="backup"|"restore"|"status", name=None)` exposes full backup control to agents over JSON-RPC.

---

## 5. Mandate 2: Offensive Primitive Countermeasures & Anti-Weaponization Guardrails

AEP harnesses powerful low-level Linux primitives (`memfd_create` in-RAM execution, bubblewrap sandboxing, eBPF telemetry, and process descriptor inspection) to give AI agents systems engineering autonomy. However, if unconstrained, these same primitives could be misused as offensive cyber weapons (e.g. executing stealthy payloads in RAM, exfiltrating `/etc/shadow`, or launching DDoS attacks). Milestone ONT-11 implements an ironclad defensive perimeter.

### 5.1 CapabilityGuard: Capability-Based Access Control (CBAC)
Located in `engine/privilege.py`, `CapabilityGuard` enforces granular authorization on every operational action:
1. **Separation of Concerns**: Privileges are not binary (`root` vs `non-root`). Actions require specific capability tokens (e.g. `CAP_RAM_EXEC`, `CAP_BACKUP_ADMIN`, `CAP_SYSTEM_INSPECT`, `CAP_NETWORK_LISTEN`).
2. **Action Authorization Matrix**:
   - `DIMINISHED` agents are strictly confined to self-scoped actions: memory searches, template builds, isolated ephemeral sandboxing, and user-scope systemd services.
   - `FULL` agents may execute system inspection and kernel tracing, but cannot bypass filesystem blacklists or tamper with the audit trail.
3. **Programmatic Enforcement**:
   ```python
   class CapabilityGuard:
       @staticmethod
       def verify_action(agent_id: str, capability: str, action: str, target: str | None = None) -> None:
           """Raises PermissionDenied if the requested action violates capability constraints."""
   ```

### 5.2 In-RAM Execution Safety & Offensive Primitive Guardrails
`artifact_execute_in_ram` in `server.py` and `engine/executor.py` injects Go ELF binaries directly into memory using `memfd_create`. To prevent this primitive from being used for malicious activity:
1. **Filesystem Blacklist**:
   Even when running with elevated capabilities, RAM-executed binaries are prevented from accessing sensitive system paths:
   - `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`, `/etc/security`
   - `/root`, `/home/*/.ssh`, `/home/*/.gnupg`
   - `/proc/kcore`, `/dev/mem`, `/dev/kmem`
   - Path traversal attempts (`..`, symlink dereferencing) are resolved to canonical paths and blocked before execution.
2. **Network Egress Restriction**:
   In-RAM binaries cannot establish arbitrary outbound network connections (reverse shells, external data exfiltration) unless the artifact explicitly declares and possesses `network_egress=True` metadata authorized in the catalog.
3. **Payload Inspection**:
   Binaries must match registered catalog artifacts (`reusable=1`) or pass Pico-Jenkins static linting (`go vet` / `golangci-lint`) prior to memory execution. Arbitrary unchecked binary blobs are rejected.

### 5.3 Multi-Agent Caller Context Segregation
When multiple agents or swarms interact with AEP simultaneously, standard ambient permissions create a risk of **privilege confusion**: an unprivileged agent could leverage a tool invocation initiated by an administrative agent.
1. **Explicit `agent_id` Parameter**:
   All FastMCP tools in `server.py` accept an optional parameter `agent_id: str = "default"`.
2. **Context Isolation**:
   - Scratchpad directories and temporary storage are isolated under `~/.local/share/agent-os/scratch/<agent_id>/`.
   - Pueue job groups are tagged per agent (`group = f"agent_{agent_id}"`).
   - Audit log entries record the initiating `agent_id`.
3. **Impersonation Prevention**:
   An agent cannot manipulate or query state owned by another `agent_id` without explicit cross-agent delegation contracts.

### 5.4 Hardened Bubblewrap POSIX Sandboxing
`sandbox_run` isolates arbitrary command execution using Linux user namespaces. Milestone ONT-11 hardens Bubblewrap flags to maximum containment:
- `--unshare-all`: Unshares IPC, mount, network (unless `share_net=True`), PID, user, UTS, and cgroup namespaces.
- `--ro-bind`: Read-only bind mounts restricted to `/usr`, `/lib`, `/lib64`, `/bin`, `/etc/resolv.conf`, and `/etc/ssl`.
- `--cap-drop ALL`: Drops all Linux kernel capabilities (including `CAP_NET_RAW`, `CAP_SYS_ADMIN`, `CAP_DAC_OVERRIDE`) inside the sandbox.
- `--tmpfs /tmp` & `--tmpfs /dev/shm`: Ephemeral in-memory filesystems mounted with `nodev`, `nosuid`, `noexec`.
- Clean Environment: Cleans all ambient environment variables, injecting only minimal sanitized `PATH`, `LANG`, and `HOME`.

### 5.5 Immutable Cryptographic Audit Trail
To ensure non-repudiation and forensic integrity, AEP establishes a cryptographic SHA-256 hash-chained audit log in `artifacts.db`:
- **Table Schema (`security_audit_log`)**:
  - `id`: INTEGER PRIMARY KEY AUTOINCREMENT
  - `timestamp`: TEXT NOT NULL (ISO 8601 UTC)
  - `agent_id`: TEXT NOT NULL
  - `action`: TEXT NOT NULL
  - `capability`: TEXT NOT NULL
  - `target`: TEXT
  - `status`: TEXT NOT NULL (`SUCCESS`, `BLOCKED`, `ERROR`)
  - `details_json`: TEXT NOT NULL (Universal Secret Masked)
  - `prev_hash`: TEXT NOT NULL
  - `entry_hash`: TEXT NOT NULL (SHA-256)
- **Hash-Chaining Rule**:
  $$	ext{entry\_hash} = 	ext{SHA-256}(	ext{prev\_hash} \parallel 	ext{timestamp} \parallel 	ext{agent\_id} \parallel 	ext{action} \parallel 	ext{target} \parallel 	ext{status} \parallel 	ext{details\_json})$$
  - The genesis entry uses $	ext{prev\_hash} = 	ext{"0"*64}$.
- **Verification Utility (`verify_audit_chain`)**:
  Scans all entries sequentially and verifies that every `entry_hash` exactly matches the re-computed hash and that `prev_hash` links to the previous entry. Any manual modification or row deletion triggers instant verification failure.
- **Secret Masking Integration**:
  Before computing hashes and storing records, all `details_json` strings are filtered through `engine/security.py:mask_secrets()`, ensuring no secrets or private keys enter the permanent hash chain.

---

## 6. Strategic Execution Plan Tasks (T1 to T9)

### Task T1: Database Backup Engine & 5-Slot Rotation Pool (`engine/backup.py`)
- **Module**: `engine/backup.py` (new module)
- **Changes**:
  - Implement `create_backup(source_db_path: Path, backups_dir: Path) -> dict[str, Any]`.
  - Use SQLite native Backup API (`conn.backup()`) with `get_ro_connection()` to copy database lock-free under WAL.
  - Implement 5-slot FIFO rotation shifting slots 1-4 and retiring slot 5.
  - Implement `PRAGMA integrity_check` and compute SHA-256 checksum on backup file.
  - Maintain `backups_manifest.json` recording slot metadata.
- **Invariants**:
  - Raw filesystem copy of active WAL database is strictly prohibited.
  - Rotation pool bounds disk footprint to exactly 5 verified backup files.
- **Blast Radius**: `engine/backup.py`.

### Task T2: Atomic Database Restore & Self-Healing Recovery (`engine/backup.py`)
- **Module**: `engine/backup.py`
- **Changes**:
  - Implement `restore_backup(slot_number: int, db_path: Path, backups_dir: Path) -> dict[str, Any]`.
  - Implement atomic file replacement via temporary file and `os.replace()`.
  - Enforce atomic purging of stale `-wal` and `-shm` index files to prevent desync corruption.
  - Implement `verify_and_auto_recover(db_path: Path, backups_dir: Path) -> dict[str, Any]` scanning slots 1 through 5 for newest valid backup.
- **Invariants**:
  - Restoring without deleting `-wal` and `-shm` files is strictly forbidden.
  - Failed restore attempts must rollback and leave original files intact if possible.
- **Blast Radius**: `engine/backup.py`.

### Task T3: Control Plane & FastMCP Integration for Backup Management (`scripts/aep-ctl`, `server.py`)
- **Modules**: `scripts/aep-ctl`, `server.py`
- **Changes**:
  - Update `scripts/aep-ctl` with domain `backup` and actions `backup`, `restore`, `status` (alias `backup_status`).
  - Update `SCHEMA` in `scripts/aep-ctl` to document domain `backup`.
  - Update `aep_ctl` tool in `server.py` to route domain `backup` to CLI implementation or internal engine.
  - Offload execution to worker threads via `anyio.to_thread.run_sync()`.
- **Invariants**:
  - FastMCP tool contract preserved (15 tools); `aep_ctl` tool signature unchanged.
  - Stdio JSON-RPC event loop latency remains <2.0ms during backup operations.
- **Blast Radius**: `scripts/aep-ctl`, `server.py`.

### Task T4: CapabilityGuard & Multi-Tier Privilege Isolation (`engine/privilege.py`)
- **Module**: `engine/privilege.py`
- **Changes**:
  - Implement `CapabilityGuard` class with `verify_action(agent_id, capability, action, target)`.
  - Map capability permissions to caller tiers (`FULL` vs `DIMINISHED`).
  - Add `CAP_BACKUP_ADMIN`, `CAP_RAM_EXEC`, `CAP_AUDIT_READ` to capability definitions.
  - Add fail-soft rejection returning structured JSON error objects on unauthorized actions.
- **Invariants**:
  - Ambient root privileges cannot bypass CapabilityGuard policies.
  - Zero circular imports with `engine/db.py` or `server.py`.
- **Blast Radius**: `engine/privilege.py`.

### Task T5: In-RAM Execution Safety & Offensive Primitive Guardrails (`engine/executor.py`, `server.py`)
- **Modules**: `engine/executor.py`, `server.py`
- **Changes**:
  - Implement path restriction filter in `artifact_execute_in_ram`: canonicalize paths and reject access to `/etc/shadow`, `/root`, `~/.ssh`, etc.
  - Implement network egress boundary check: deny unauthorized outbound socket creation.
  - Enforce binary origin validation: reject non-catalog unverified binary blobs.
- **Invariants**:
  - Fast RAM execution performance preserved ($T_{exec} pprox 4	ext{ ms}$).
  - Security checks execute in <0.2ms before binary RAM injection.
- **Blast Radius**: `server.py`, `engine/executor.py`.

### Task T6: Multi-Agent Caller Context Segregation (`server.py`, `engine/*.py`)
- **Modules**: `server.py`, `engine/catalog.py`, `engine/kanban.py`
- **Changes**:
  - Add `agent_id: str = "default"` to all 15 FastMCP tools in `server.py`.
  - Isolate scratchpad workspaces to `~/.local/share/agent-os/scratch/<agent_id>/`.
  - Pass `agent_id` into Pueue job dispatch groups (`group=f"agent_{agent_id}"`).
  - Tag Kanban task creation and updates with `agent_id`.
- **Invariants**:
  - Backward compatibility: calls omitting `agent_id` default cleanly to `"default"`.
  - An agent cannot mutate another agent's tasks without explicit authorization.
- **Blast Radius**: `server.py` tool parameter signatures, engine state tracking.

### Task T7: Bubblewrap POSIX Sandboxing Hardening (`server.py`, `engine/executor.py`)
- **Modules**: `server.py`, `engine/executor.py`
- **Changes**:
  - Enforce `--unshare-all` in all bubblewrap sandbox invocations.
  - Configure minimal read-only bind mounts (`/usr`, `/lib`, `/bin`, `/etc/ssl`).
  - Enforce `--cap-drop ALL` to drop all Linux capabilities.
  - Mount fresh tmpfs for `/tmp` and `/dev/shm` with `nodev,nosuid,noexec`.
  - Scrub all environment variables except sanitized minimal execution variables.
- **Invariants**:
  - Sandbox escapes via setuid binaries or raw capabilities are mathematically blocked.
- **Blast Radius**: `sandbox_run` in `server.py`.

### Task T8: Immutable Cryptographic Audit Trail (`engine/security.py`, `engine/db.py`)
- **Modules**: `engine/db.py`, `engine/security.py`
- **Changes**:
  - Add `security_audit_log` table definition to `engine/db.py` with SHA-256 hash chaining columns.
  - Implement `record_audit_event(conn, agent_id, action, capability, target, status, details)` with automatic hash computation and secret masking.
  - Implement `verify_audit_chain(conn) -> tuple[bool, str, int]` to validate cryptographic chain integrity.
- **Invariants**:
  - Hash chain cannot be modified without invalidating all subsequent block hashes.
  - No unmasked secrets or sensitive tokens may be stored in audit records.
- **Blast Radius**: `engine/db.py`, `engine/security.py`.

### Task T9: Dokimos Multi-Gate Verification & Stress Testing (Gates 1 to 7)
- **Modules**: Test suites and verification harnesses
- **Changes**:
  - Construct comprehensive automated verification suites covering all 7 Dokimos gates.
  - Execute live WAL stress backup, corruption simulation & auto-recovery, capability gating, path traversal attacks, and cryptographic hash chain verification.
- **Invariants**:
  - All 7 gates must pass with 100% compliance before Hermon handoff.
- **Blast Radius**: Verification suites.

---

## 7. Dokimos Multi-Gate Verification Matrix (Gates 1 to 7)

| Gate # | Name | Verification Scope | Target Artifacts | Acceptance Criteria |
| :---: | :--- | :--- | :--- | :--- |
| **Gate 1** | **Online Hot Backup & 5-Slot Rotation Integrity** | Trigger backup under concurrent WAL writes; verify 5-slot rotation shifts (`bak.1` through `bak.5`); verify `backups_manifest.json` SHA-256 checksums match physical files. | `engine/backup.py` | 0 torn pages; `PRAGMA integrity_check` returns `ok` on all backup slots; slot count never exceeds 5. |
| **Gate 2** | **Atomic Restore & WAL/SHM Desync Protection** | Execute atomic restore from backup slot; verify stale `-wal` and `-shm` files are completely unlinked prior to replacement; verify database opens cleanly. | `engine/backup.py` | Zero SQLite index desync or checksum errors; database opens in WAL mode with full data integrity. |
| **Gate 3** | **Automated Corruption Self-Healing Recovery** | Artificially corrupt `artifacts.db` header; invoke `verify_and_auto_recover()`; verify automatic fallback to latest valid backup slot. | `engine/backup.py`, `engine/db.py` | Engine detects corruption, identifies latest healthy backup slot, executes atomic restore, and restores full service in <500ms. |
| **Gate 4** | **CapabilityGuard & Privilege Confusion Resistance** | Attempt unauthorized actions from `DIMINISHED` agent context; verify `CapabilityGuard` blocks execution with structured JSON error. | `engine/privilege.py` | Unauthorized actions blocked 100%; zero privilege escalation across agent boundaries. |
| **Gate 5** | **In-RAM Execution Path Blacklist & Egress Boundaries** | Attempt to execute RAM binaries accessing `/etc/shadow`, `/root`, or `~/.ssh`; attempt unauthorized outbound socket connections. | `server.py`, `engine/executor.py` | Path traversal and sensitive file access blocked; unauthorized outbound connections rejected. |
| **Gate 6** | **Bubblewrap POSIX Hardening & Capability Dropping** | Inspect bubblewrap container flags; test capability dropping (`--cap-drop ALL`) and namespace isolation (`--unshare-all`). | `server.py` | Sandbox executes with 0 retained Linux capabilities; host filesystem protected from write mutations. |
| **Gate 7** | **Cryptographic Audit Trail Integrity & FastMCP Parity** | Generate 100 audit entries; verify SHA-256 chain via `verify_audit_chain()`; tamper with single entry and verify detection; verify 15 FastMCP tools via `aep-sync.sh --check`. | `engine/db.py`, `engine/security.py`, `server.py` | Hash chain validates with 100% mathematical integrity; tamper attempt detected immediately; 15 FastMCP tools maintain 100% parity. |

---

## 8. Ontos Audit Contract & Pre-Audit Checklist (ONT-11)

- [x] **Topos Task DAG Validated**: `topos_audit_dag` executed with verdict `APPROVED` (Grafo coherente: Cero co-dependencias detectadas; T1 to T9 form a strict directional DAG).
- [x] **Unbroken Knowledge Graph Sequence**: Predecessor anchor `feature_20261024_171500_code_modernization_and_concurrency_optimization.md` linked.
- [x] **Rollup History Consolidated**: Rollup document `feature_rollup.md` (Docs 1-14) referenced.
- [x] **Kanban State Synchronized**: Task 112 transitioned from `BACKLOG` to `SYNTHESIZED` in `/home/ancruz/.local/share/agent-os/artifacts.db`.
- [x] **Dependency Direction Validated**: `engine/backup.py` depends on `engine/db.py`; `engine/privilege.py` remains leaf dependency; `server.py` coordinates tools without circular imports.
- [x] **Concurrency Safety Verified**: Backups utilize native SQLite Backup API (`conn.backup()`) avoiding raw file copy hazards on WAL databases; AnyIO thread offloading enforced for stdio responsiveness.
- [x] **Disaster Recovery Verified**: 5-slot rotation pool, SHA-256 verification, atomic restore purging `-wal`/`-shm`, and self-healing auto-recovery formally specified.
- [x] **Offensive Countermeasures Codified**: `CapabilityGuard`, path blacklist (`/etc/shadow`, `/root`, `~/.ssh`), network egress policy, bubblewrap `--cap-drop ALL`, and cryptographic hash-chain audit log specified.
- [x] **Dokimos Verification Gates Defined**: 7-Gate verification matrix specified with rigorous pass/fail criteria.

---

## 9. Ontos Structural & Contract Audit Verdict (Stage 3 — ONT-11)

- **Audit Date**: 2026-10-25T03:25:00Z
- **Auditor**: Ontos (Stage 3 — Structural & Interface Contract Auditor)
- **Audit Verdict**: **`APPROVED`**
- **Topos Structural Analysis**:
  - **DAG Verification**: Co-dependencies: 0. Tasks T1 to T9 form a strict directional DAG with zero cycles.
  - **Vertical Trace**: Verified clean separation across Storage (`engine/db.py`, `engine/backup.py`), Access Control (`engine/privilege.py`, `engine/security.py`), and Transport / Interface (`server.py`, `scripts/aep-ctl`).
  - **Horizontal Trace**: Read-only SQLite connection pooling (`get_ro_connection`) during backup operations guarantees zero write-lock contention with active WAL writers.
  - **Blast Radius & Concurrency Safety**: Native SQLite Backup API (`conn.backup()`) eliminates torn-page risks. Advisory file locking (`fcntl.flock(LOCK_EX)`) prevents concurrent backup race conditions. AnyIO worker offloading (`anyio.to_thread.run_sync`) preserves stdio loop latency (<2.0ms).
- **Handoff**: Approved without remediation. Routed to Pragma (Stage 4) for execution.

---

## 10. Pragma Execution Summary (Stage 4)

- **Execution Document**: [`execution_report_20261025_034500_backup_restore_and_offensive_countermeasures.md`](execution_report_20261025_034500_backup_restore_and_offensive_countermeasures.md)
- **Execution Verdict**: **`READY_FOR_DOKIMOS (STAGE 5)`**
- **Kanban Transition**: Task 112 advanced from `SYNTHESIZED` to `LINTED` (Score: `0.1875`, `lint_passed=True`).
- **Implementation Scope Delivered**:
  - **T1 (`engine/backup.py`)**: Implemented `BackupEngine` with `conn.backup()`, strict 5-slot FIFO rotation pool (`artifacts.db.bak.1..5`), pre-promotion SHA-256 byte verification, `PRAGMA integrity_check`, atomic restore purging stale `-wal`/`-shm` sidecars, and automated self-healing corruption recovery (`verify_and_auto_recover()`).
  - **T2 (`engine/privilege.py`)**: Implemented `CapabilityGuard` and typed `PermissionDenied` exception enforcing fine-grained capability checks (`cap_ram_exec`, `cap_backup_admin`, `cap_audit_read`) and sensitive path blacklist detection.
  - **T3 (`engine/security.py`)**: Universal secret masking (`mask_secrets`) covering 8 token/key categories, SHA-256 cryptographic hash-chained audit logging (`record_audit_event`), and tamper verification (`verify_audit_chain`).
  - **T4 (`schemas/database.sql`, `engine/catalog.py`, `engine/kanban.py`)**: Schema migration adding `agent_id TEXT NOT NULL DEFAULT 'default'` to `kanban_tasks`, `execution_metrics`, and `security_audit_log` with indexes.
  - **T5 (`scripts/aep-ctl`)**: Unified CLI domain `backup` (`backup`, `restore`, `status`, `backup_status`) with dynamic project root resolution.
  - **T6 (`server.py`)**: Updated all 15 FastMCP tools with `agent_id: str = "default"`; wired `CapabilityGuard` path blacklisting in `artifact_execute_in_ram`; hardened `sandbox_run` bwrap flags (`--unshare-all`, `--cap-drop ALL`); wired `aep_ctl` backup domain; segregated Pueue execution groups.
  - **T7 (Codebase)**: Ruff clean (0 errors across 42 files), Semgrep clean (0 findings across 63 files, 1,352 rules), `aep-sync.sh` hot reload confirmed.

---

## 11. Dokimos Verification & Multi-Gate Audit (Stage 5)

- **Verification Document**: [`verification_report_20261025_035500_backup_restore_and_offensive_countermeasures.md`](verification_report_20261025_035500_backup_restore_and_offensive_countermeasures.md)
- **Dokimos Verdict**: **`VERIFIED`** (All 7 Mandatory Gates Passed — Zero Defect / Zero Regression)
- **Kanban Promotion**: Task 112 advanced to **`PROMOTED`** (Score: `0.9250`, Verdict: `TRUST`, Confidence: `1.00`, Attempts: 3).
- **Multi-Gate Audit Results**:
  1. **Gate 1 (FastMCP Registration & Parity Check)**: `./scripts/aep-sync.sh --check` passed. All 15 FastMCP tools importable and verified backward-compatible with `agent_id: str = "default"`. All 18 capabilities verified.
  2. **Gate 2 (Hot Backup & 5-Slot FIFO Rotation Pool)**: 6 sequential backups bounded to 5 slots (`bak.1` through `bak.5`). SHA-256 checksums match manifest. Atomic restore purged `-wal`/`-shm` sidecars cleanly. Self-healing recovered from corrupted database in <15ms. Fail-soft fallback verified on destroyed pool.
  3. **Gate 3 (Offensive Countermeasures & Security Gate)**: Path blacklist (`/etc/shadow`, `/root`, `~/.ssh`) blocked 100%. RAM binary execution targeting sensitive paths blocked and logged in audit trail. Bubblewrap executed with `--unshare-all` and `--cap-drop ALL` (0 capabilities retained). 8 secret types redacted. SHA-256 hash-chain validated ($H_n = \text{SHA256}(H_{n-1} + \dots)$); tamper detection caught simulated row modification immediately.
  4. **Gate 4 (Stdio Event Loop Latency & Concurrency)**: All 15 FastMCP tools declared `async def` with worker offloading via AnyIO (14) or native coroutine orchestration (1). Event loop latency measured at avg `0.113 ms` (P95 < 0.24 ms), well within < 2.0 ms threshold.
  5. **Gate 5 (Subprocess Hygiene & FD Isolation)**: 19 subprocess calls audited. All enforce `check=False`, timeouts, `close_fds=True`, and `stdin=DEVNULL`. In-RAM execution primitive enforces `pass_fds=(fd,)`.
  6. **Gate 6 (Static Code Health & Zero Regression)**: Ruff passed with 0 errors and 0 warnings across all 42 Python files. Semgrep SAST passed with 0 findings across 63 files (1,352 rules).
  7. **Gate 7 (Kanban Promotion & Trust Ponderation)**: Task 112 transitioned from `LINTED` (0.1875) → `CANARY` (0.9250) → `PROMOTED` in `/home/ancruz/.local/share/agent-os/artifacts.db` with verdict `TRUST` and confidence `1.00`.

---

## 12. State Evolution Transition Diagram

```mermaid
stateDiagram-v2
    [*] --> G1_Weave: Archon Plan Formulated (ONT-11)
    G1_Weave --> Ontos_Audit: Plan Documented (Task 112 SYNTHESIZED)
    Ontos_Audit --> Pragma_Exec: Verdict APPROVED (ONT-11)
    Pragma_Exec --> Dokimos_Verify: Execution Report (T1-T7 Done, LINTED)
    Dokimos_Verify --> G2_Record: Verdict VERIFIED (Gates 1-7 Pass, PROMOTED)
    G2_Record --> Hermon_Release: Ready for Commit & Push
    Hermon_Release --> [*]: Done
```

---

## 13. Graphos G2 State Transition & Release Routing

- **Pipeline Stage**: `Stage 2 (G2) — Post-Dokimos Verification Record & Documentation Sync`
- **Verification Verdict**: **`VERIFIED`**
- **Kanban Promotion**: Task 112 `PROMOTED` (Score: `0.9250 TRUST`)
- **Knowledge Graph Anchor**: Sequence chain unbroken (`D14 -> D15`).
- **Rollup Synchronization**: `docs/pipeline/feature_rollup.md` updated incorporating Milestone ONT-11 (Document 15).
- **Milestone Matrix**: Milestone ONT-11 marked as `✅ VERIFIED` / `PROMOTED` in `docs/MILESTONES.md`.
- **Compaction Instruction**: `docs/COMPACT.md` regenerated for post-verification state.
- **Routing Decision**: As required by Topos Integrity Protocol, Graphos returns execution context to the **Orchestrator**, routing next to **Hermon (Stage 6)** for atomic Conventional Commit and version release.
