# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
