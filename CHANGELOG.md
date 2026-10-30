# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
