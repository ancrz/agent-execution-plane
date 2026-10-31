# Context Compaction Guidance — AEP (Milestone ONT-30)

**Preserve**:
- Pipeline Mode: Full Pipeline (Stage 2 Graphos G2 Final Record -> Routing to Hermon Stage 6).
- Completed Milestone: ONT-30 ("AEP Cross-Harness Schema Evolution & Multi-Runner Ergonomics") — VERIFIED ✅ (99/99 tests passed, 100% gates, 0 Ruff errors).
- Key Changes: FastMCP listChanged=True, drift metadata (schema_hash, server_version, pid, uptime), topos_audit_dag task-level resource fallback, aep-sync.sh --audit, sandbox_run brief trimming / composite parse="auto", playbook recipes WF-7 to WF-9.
- Open Defects: None (Gate 4 LOGIC_ERROR resolved via ceiling update < 6000 bytes).
- Next Actions: (1) Hermon Stage 6 atomic git commit; (2) Pre-commit hook validation; (3) Remote push to origin/dev.

**Drop**:
- Verbose test runs, raw stdout/stderr logs, intermediate defect traces, and superseded planning drafts.
