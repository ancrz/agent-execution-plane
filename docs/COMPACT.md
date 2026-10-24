# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full (Topos Integrity Protocol).
- Active Intent / Milestone: ONT-10 (Code Modernization, Ruff Linting, AnyIO & Hot SQLite Anti-Deadlock) VERIFIED; Task 111 PROMOTED (Score: 0.9250 TRUST).
- Files Changed & Why: `engine/db.py` (segregated RO/RW, PRAGMA wal_autocheckpoint=1000, transaction_immediate), `server.py` (AnyIO async thread offloading for 15 tools), `engine/*.py` (eliminated P0-P3 Ruff violations, singleton holder classes, atomic executemany), `pyproject.toml` (Ruff SAST rules).
- Open Defects: None (0 defects, 0 regressions, Ruff 0 errors, Semgrep 0 findings, 6/6 Dokimos gates passed).
- Architecture Decisions: Segregated RO/RW SQLite handles; `BEGIN IMMEDIATE` anti-deadlock transactions; reject fork with open WAL FDs; AnyIO stdio offloading; Contract Validation Triad; PLW1510 subprocess check=False with FD isolation.
- Next 3 Pending Actions:
  1. Hermon (Stage 6): Atomic Conventional Commit (`refactor: code modernization, ruff linting, anyio concurrency and hot sqlite anti-deadlock`).
  2. Hermon (Stage 6): Version release and branch push.
  3. Post-release status confirmation and milestone closeout.

Drop: Raw test outputs, intermediate linter logs, superseded plans, resolved dry-run findings.
