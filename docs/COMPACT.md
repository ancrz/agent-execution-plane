# Context Compaction Guidance — AEP

Preserve:
- Pipeline Mode: Full (Topos Integrity Protocol).
- Active Intent / Milestone: ONT-11 (5-Slot Hot Backup Engine, Offensive Countermeasures & Multi-Agent Context Segregation) — Stage 2 G2 (Dokimos VERIFIED; Task 112 PROMOTED 0.9250 TRUST).
- Files Changed & Why: `engine/backup.py` (5-slot hot backup, atomic restore, self-healing), `engine/privilege.py` (CapabilityGuard), `engine/security.py` (secret masking, hash chain), `schemas/database.sql` (agent_id, audit log), `scripts/aep-ctl` (backup CLI), `server.py` (FastMCP agent_id, bwrap hardening, memfd blacklist).
- Open Defects: None (0 defects; 7/7 Dokimos gates passed; Ruff 0 errors; Semgrep 0 findings).
- Decisions Taken: Native SQLite Backup API (`conn.backup()`); 5-slot FIFO pool; atomic WAL/SHM purge; CapabilityGuard CBAC; memfd path blacklist; Bubblewrap `--cap-drop ALL` & `--unshare-all`; SHA-256 hash chain; agent_id default segregation.
- Next 3 Pending Actions:
  1. Hermon (Stage 6): Atomic Conventional Commit and release tagging.
  2. Orchestrator: Verify clean git status and release report delivery.
  3. Orchestrator / User: Milestone ONT-11 closure and next intent intake.

Drop: Tool outputs already summarized, intermediate test logs, superseded plans, resolved errors.
