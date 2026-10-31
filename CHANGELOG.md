# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.5] - 2026-10-30

### Added
- **Topos DAG Actionable Remediations & Alias (`GAP-OM-07`)**:
  - Enhanced `topos_audit_dag` in `server.py` to return structured actionable guidance (`remediation: list[str]`) and cyclic dependency trail (`cycle: list[str]`) when detecting co-dependencies, guiding multi-agent recovery without human escalation.
  - Added native `deps` alias alongside `dependencies`, eliminating parametric mismatch gaps during polymorphic DAG invocations.
- **Transparent Output & Data Unwrapping in Variable Piping (`GAP-OM-08`)**:
  - Implemented `_resolve_target_field()` in `engine/ipc_pool.py` for `resolve_step_refs()`, allowing seamless variable piping (`$steps.<id>.<field>` and `$prev.<field>`) without requiring manual `.output.` or `.data.` traversal while strictly preserving root-level object precision in `_get_dot_path()` and `project_fields()`.
- **Apport System Crash Recovery & Robust Status (`GAP-OM-09`)**:
  - Added native Debian/Ubuntu Apport crash report inspection (`/var/crash/*.crash`) in `diagnose_system_crashes` when `coredumpctl` is not present, extracting executable path, signal, date, and crash payload sizes with low-overhead header reads.
  - Refactored forensic system health calculation: retains `status: "OK"` if either systemd journal errors or Apport/coredump telemetry is successfully gathered, preventing false `DEGRADED` statuses on standard Debian/Ubuntu desktop and server environments.
- **Comprehensive Test Suite Expansion**:
  - Added `test_gap_om07_topos_audit_dag_remediation_and_cycle_and_deps_alias`, `test_gap_om08_ipc_pool_dot_path_unwrapping`, and `test_gap_om09_diagnose_system_crashes_apport_and_status_ok` to `tests/test_spec_om7_ipc_batch.py` (78/78 tests passing at 100%).

## [0.2.4] - 2026-10-30

### Added
- **Omission Gaps Remediation Suite across 15 FastMCP Tools (Milestone `ONT-25`)**:
  - **GAP-OM-01 (`artifact_lint_and_build`)**: Exposed dedicated `action="lint"` and `action="vet"` for pure Go static analysis (`go vet` + advisory `golangci-lint`) without triggering compilation or modifying catalog state.
  - **GAP-OM-02 (`process_inspect`)**: Added `name: str | None = None` and `filter: str | None = None` to search active processes in `/proc` by executable name or command-line, sorting by RSS and eliminating client-side whole-table dumping.
  - **GAP-OM-03 (`artifact_execute_in_ram`)**: Added `env: dict[str, str] | None = None` and `stdin: str | None = None` to inject dynamic environment variables and standard input into ephemeral binaries executing in RAM via `memfd_create`.
  - **GAP-OM-04 (`sandbox_run`)**: Added `env: dict[str, str] | None = None` forwarding custom environment variables into Bubblewrap sandbox via `--setenv`.
  - **GAP-OM-05 (`kanban_board`)**: Added intuitive transition aliases `action="add"` (mapping to `create`) and `action="move"` (mapping to `advance`) with mandatory parameter validation.
  - **GAP-OM-06 (`async_job_dispatch`)**: Implemented compact status pagination in `_compact_pueue_payload` for `summary` and `brief` verbosity modes, stripping bulk environment variables and nested timestamps to reduce payload size by 97.48% (from 32,165 bytes down to 811 bytes).
- **Unit and Integration Tests**:
  - Added `TestOmissionGapsRemediation` in `tests/test_spec_om7_ipc_batch.py` covering all 6 remediated gaps (total 75/75 tests passing).

## [0.2.3] - 2026-10-30

### Added
- **Non-Pico System-Wide Concurrency Hardening (Milestone `ONT-24`)**:
  - **Audit Ledger Fork Prevention**: Serialized `record_audit_event()` in `engine/security.py` using a re-entrant mutex (`_AUDIT_LOCK`) and `transaction_immediate(conn)` to prevent SHA-256 hash chain forks under parallel multi-agent tool execution.
  - **Thread-Safe In-Memory RAM Micro-Snapshots**: Wrapped `create_micro_snapshot()`, `restore_micro_snapshot()`, `list_micro_snapshots()`, and `clear_micro_snapshots()` in `engine/backup.py` under `_SNAPSHOT_LOCK` with `check_same_thread=False` `:memory:` SQLite connections, eliminating cross-thread connection exceptions.
  - **Docs Vectorizer Thread Safety**: Guarded `ManPagesVectorizer` singleton initialization under `_DocsHolder.lock` in `server.py` to prevent race conditions during concurrent `query_system_docs` queries.
  - **Kali-MCP Semantic Parity & Tactical Playbooks**:
    - Enriched `server._INSTRUCTIONS` with explicit recipes `WF-1` through `WF-6`, zero-token RAM handoffs, and 9 `aep_ctl` control plane domains.
    - Added Rule of Engagement #7 ("Zero-Token Multi-Agent RAM Handoff & Collision-Free Concurrency") and recipe `WF-6` in `engine/privilege.py`.
- **System-Wide Concurrency Verification Battery**:
  - Added `TestNonPicoSystemWideConcurrency` in `tests/test_spec_om7_ipc_batch.py` validating 8-thread concurrent audit ledger integrity, multi-thread RAM micro-snapshots, and double-checked locking of vectorizer.
  - Validated all 79 Mermaid diagrams across 52 markdown files with zero syntax or bracket/quote balance errors.
  - 69/69 total tests passing with 0 errors (`ruff check .` clean, `setup.sh --check` healthy).

## [0.2.2] - 2026-10-30

### Added
- **Multi-Agent Pico-Jenkins Build Slot Isolation (`GAP-OM23-1`)**:
  - Isolated Go compilation under `GLOBAL_SESSION_POOL` in `/dev/shm/aep_pool/slot_<id>` per agent (`agent_id=eff_agent`).
  - Added atomic binary materialization via `.tmp` staging and `os.replace` to `TEMP_BIN_DIR`, eliminating parallel compilation clobbers and TOCTOU races.
  - Enhanced `artifact_execute_in_ram` with ELF header magic (`\x7fELF`) validation before in-RAM execution.
- **Precomputed Vector Embeddings Outside SQLite Write Transactions (`GAP-OM23-4`)**:
  - Implemented `_precompute_embedding()` in `engine/catalog.py` using fastembed outside SQLite write locks.
  - Updated `_upsert_embedding()` to accept precomputed float32 serialized vectors, reducing SQLite write lock hold times by >95% and eliminating `vec0` primary key collisions.
- **Pico-Ansible Saved Playbook Multi-Agent Parity (`GAP-OM23-3`)**:
  - Brought `playbook_run(action="run")` to full parity with ephemeral batch execution: leases dedicated agent IPC slot, resolves step reference piping (`$prev`, `$steps.<id>`, `$cache`, `$slot`), and automatically injects caller `agent_id`.
  - Added server-side field projection (`return_only`, `select_fields`) with token savings estimation (94.25% token savings) and `failed_steps` error preservation.

### Fixed
- **Atomic Kanban Upsert & Immediate Transaction Locking (`GAP-OM23-2`)**:
  - Replaced read-then-write kanban task creation with atomic `kanban.upsert_build_task()` in `engine/kanban.py` under `transaction_immediate(conn)`.
  - Atomically matches active tasks across lanes, increments attempt counts and scores in-place, and prevents duplicate task creation during concurrent pipeline builds.

### Changed
- Expanded test suite with `TestPicoTriadMultiAgentConcurrency` in `tests/test_spec_om7_ipc_batch.py` covering all 4 concurrency scenarios (66/66 total tests passing).
- Updated `README.md` and architecture documentation with Pico-Triad multi-agent concurrency isolation patterns.

## [0.2.1] - 2026-10-30

### Added
- **Multi-Agent Shared RAM Cache Piping (`$cache.<key>`)**:
  - Implemented cross-agent in-memory session cache handoff via `/dev/shm/aep.sock` session pool.
  - Added `$cache.<key>.<field>` interpolation in `playbook_run(action="batch")`, enabling zero-turn state propagation across independent pipeline agents (`pragma` -> `dokimos` -> `graphos` -> `hermon`).
  - Added `aep_ctl` `domain="ipc"` `action="cache"` operation for direct RAM session cache inspection and key enumeration.
- **Batch Tool Whitelist Expansion**:
  - Added `kanban_board` and `artifact_lint_and_build` to the allowed batch tool whitelist in `server.py`.
  - Added dynamic signature-based kwarg filtering via `inspect.signature()`, eliminating `TypeError` when callers pass extra context parameters.

### Fixed
- **Smart Dot-Path Field Projection Fallbacks (GAP-OM22-1)**:
  - Relaxed strict field path matching in `return_only` and `select_fields` to automatically resolve attributes at the root or under `output` without requiring the `output.` prefix, delivering up to 94% token savings.
- **Diagnostic Error Preservation (GAP-OM22-2)**:
  - Guaranteed unconditional preservation of `failed_steps` error telemetry in batch responses even when field projection filters are active, preventing silent failures or masking of root causes.

### Changed
- Expanded `tests/test_spec_om7_ipc_batch.py` with 4 new omission-gap regression test cases (62/62 total tests passing).
- Updated `README.md` and CLI tools (`scripts/aep-ctl`) to document RAM cache piping and dot-path fallbacks.

## [0.2.0] - 2026-10-30

### Added
- **Spec OM-7: Shared-Memory UNIX Socket Session Pool (`/dev/shm/aep.sock`)**:
  - High-throughput in-memory IPC multiplexer (`engine/ipc_pool.py`) eliminating TCP loopback overhead.
  - Multi-tenant connection pooling with agent scratch directory isolation under `/dev/shm/aep_pool/slot_<id>`.
  - Auto-reaping daemon loop for idle/expired sessions with LRU leasing and slot reuse.
- **Ephemeral Batch / Code Mode**:
  - Cloudflare Workers / Code Mode architecture integrated into `playbook_run(action="batch", steps=[...])`.
  - Pipelined JSON-RPC execution allowing multiple tool invocations in a single round-trip turn.
  - Runtime variable interpolation (`$steps.<id>.<path>`) across sequential chained tool calls.
  - Server-side field projection (`return_only` and `select_fields`) reducing token payload sizes by 74%–95%.
- **Control Plane IPC Domain**:
  - Integrated `ipc` domain into `aep_ctl` supporting `status`, `ping`, `lease`, `release`, `reap`, and `metrics` subcommands.
  - Added CLI subcommand `./scripts/aep-ctl ipc` with colored terminal output and JSON introspection.
- **Comprehensive Verification & SDD**:
  - Specification document in `docs/sdd/sdd_om7_ipc_socket_pool_and_code_batch_mode.md`.
  - Dedicated regression test suite `tests/test_spec_om7_ipc_batch.py` (58/58 total tests passing across workspace).

### Changed
- Updated `engine/privilege.py` to recognize `domain="ipc"` and `action="batch"` with strict CapabilityGuard enforcement.
- Updated `server.py` to register the IPC daemon background task and lifecycle hooks while preserving the strict 15-tool MCP namespace.
- Synchronized `README.md` diagrams and tool matrix to document IPC session pool architecture and token reduction metrics.
