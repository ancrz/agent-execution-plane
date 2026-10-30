# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Short (Self-Evolutionary Loop with Live AEP MCP Hot-Reload).
- Active Intent / Milestone: ONT-15 (Self-Evolutionary Agent Experience Suite & Kali-Style Semantic Ergonomics) — VERIFIED & PROMOTED ✅.
- Files Changed:
  - `engine/catalog.py` & `engine/kanban.py`: Clean-home SQLite bootstrap (`if cols:` guard before `ALTER TABLE` in `_migrate`).
  - `engine/telemetry.py`: Per-request latency, byte count, estimated tokens, RSS/FD delta attribution, and normalized `agent-brief` envelope (`status`, `severity`, `summary`, `next_action`, `truncated`, `cursor`, `telemetry`).
  - `engine/privilege.py`: Shared `CONTROL_PLANE_SCHEMA`, `check_binary_prerequisites()` real binary readiness (`bwrap`, `pueue`, `go`, `coredumpctl`, `bpftrace`, etc.), and `tactical_playbook()` (`EAES-v2-Kali-Semantic`) with canonical 1-liners, workflow recipes, and token-efficiency Rules of Engagement.
  - `scripts/aep-ctl`: Unified schema imported from `engine.privilege`, added `audit` domain (`verify`) and `auto_recover`.
  - `server.py`: `aep_ctl(action="schema")` without dummy domain, `verbosity="summary"|"detail"|"brief"` & pagination cursors, `sandbox_run` with `share_net=False` default, `working_dir`/`ro_paths`/`rw_paths`, automatic `.venv` interpreter symlink mount, and `CapabilityGuard` blacklist enforcement.
  - `scripts/aep-sync.sh`: Added `timeout 3` around Codex socket reload so hot-reload completes non-blockingly.
  - `tests/test_agent_experience_evaluation.py`: Promoted both strict `xfail` tests to `PASS` and added contract tests for workspace sandboxing, telemetry attribution, compact summaries, and Kali tactical playbook.
- Verification Status: `ruff check .` (0 errors); `pytest` (39/39 passed, 0 xfailed); `sandbox_run` & `async_job_dispatch` live-verified via hot-reloaded AEP MCP.
- Next Actions: Sync `dev` and `main` branches and push to `origin`.
Drop: raw AEP outputs, intermediate debug traces, superseded pre-ONT-15 failure logs.
