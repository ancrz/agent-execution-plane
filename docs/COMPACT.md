# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Short (ONT-22 Stage 2: Graphos G2 Record) -> Hermon (Stage 6).
- Active Intent / Milestone: ONT-22 (Spec OM-7 Omission Gap Remediation & Multi-Agent Cache Piping) — VERIFIED & PROMOTED ✅ (Task #130 Score: 0.9250 TRUST).
- Core Additions: `engine/ipc_pool.py` (smart projection, shared session cache), `engine/playbook.py` (signature inspect, whitelist), `server.py` (`failed_steps` retention, cache wiring), `aep_ctl(domain="ipc", action="cache")`, `tests/test_spec_om7_ipc_batch.py` (16 tests, 62 total).
- Multi-Agent Verification: 3-agent shared RAM handoff (`pragma` -> `dokimos` -> `graphos`) verified in `/dev/shm` session `ont-22-multi-agent`.
- Quality Gates: 62/62 pytest passed, 0 ruff errors, setup.sh --check HEALTHY (exit 0), 15 FastMCP tools invariant strictly preserved, zero FD leaks.
- Readiness & Next Actions: Ready for Hermon (Stage 6) atomic commit and sync.
Drop: raw AEP tool outputs, intermediate debug traces, superseded test execution logs.
