# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full (ONT-21 Stage 2: Graphos G2 Record) -> Hermon (Stage 6).
- Active Intent / Milestone: ONT-21 (Spec OM-7 IPC Socket Pool & Ephemeral Batch/Code Mode) — VERIFIED & PROMOTED ✅ (Task #129 Score: 1.0 TRUST).
- Core Deliverables: `engine/ipc_pool.py`, `/dev/shm/aep.sock` (0.52ms warm IPC), `playbook_run(action="batch")` with server-side field projection (74.6%–96.98% token savings), `aep_ctl(domain="ipc")`, `docs/sdd/spec_om7_ipc_socket_pool_and_code_mode.md`.
- Verification Status: 58/58 pytest passed (100%), 0 ruff errors, setup.sh --check HEALTHY (exit 0), 15 FastMCP tools invariant strictly preserved, zero FD leaks (`fd_delta: 0`).
- Readiness & Next Actions: Ready for Hermon (Stage 6) atomic Conventional Commit and version control sync.
Drop: raw AEP tool outputs, intermediate debug traces, superseded test execution logs.
