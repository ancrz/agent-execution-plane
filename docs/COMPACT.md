# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full / Short (ONT-24 Stage 6: Hermon Commit & Push).
- Active Intent / Milestone: ONT-24 (Non-Pico Concurrency Protections & Kali Semantic Polish) — VERIFIED & PROMOTED ✅ (Task #132 Score: 0.9500 TRUST).
- Core Additions: `engine/security.py` (`_AUDIT_LOCK` + `transaction_immediate` preventing SHA-256 forks), `engine/backup.py` (`_SNAPSHOT_LOCK` + `check_same_thread=False` `:memory:` micro-snapshots), `server.py` (`_DocsHolder.lock`, enriched `_INSTRUCTIONS`), `engine/privilege.py` (Rule #7, recipe `WF-6`), `tests/test_spec_om7_ipc_batch.py` (23 tests, 69 total).
- Concurrency & Schema Integrity: Tested with 8 concurrent threads on security audit log, 4 threads on RAM micro-snapshots, zero race conditions, zero FD leaks (`fd_delta == 0`), zero circular co-dependencies.
- Mermaid Integrity: 79 Mermaid diagrams across 52 markdown files linted and validated with 0 errors.
- Quality Gates: 69/69 pytest passed (100%), 0 ruff errors, setup.sh --check HEALTHY (exit 0), 15 FastMCP tools invariant strictly preserved.
- Readiness & Next Actions: Committed and synchronized with origin/dev and origin/main.
Drop: raw AEP tool outputs, intermediate debug traces, superseded test execution logs.
