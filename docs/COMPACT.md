# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Short (ONT-23 Stage 2: Graphos G2 Record) -> Hermon (Stage 6).
- Active Intent / Milestone: ONT-23 (Pico-Triad Multi-Agent Concurrency Isolation) — VERIFIED & PROMOTED ✅ (Task #131 Score: 0.9250 TRUST).
- Core Additions: `engine/kanban.py` (`upsert_build_task` under `transaction_immediate`), `engine/catalog.py` (precomputed embeddings outside write locks), `server.py` (`/dev/shm` slot Go builds + `os.replace`, `playbook_run(action="run")` slot/piping/projection parity), `tests/test_spec_om7_ipc_batch.py` (20 tests, 66 total).
- Concurrency Verification: 4 concurrent agents / 8 threads tested with zero TOCTOU races, zero build collisions, zero lock-upgrade deadlocks, and zero FD leaks.
- Quality Gates: 66/66 pytest passed (100%), 0 ruff errors, setup.sh --check HEALTHY (exit 0), 15 FastMCP tools invariant strictly preserved.
- Readiness & Next Actions: Ready for Hermon (Stage 6) atomic commit and sync.
Drop: raw AEP tool outputs, intermediate debug traces, superseded test execution logs.
