# Context Compaction Guidance — AEP (Milestone ONT-37 Verified)

**Preserve**:
- Pipeline State: Full Mode (Stage 5 Dokimos Complete ──► Stage 2 Graphos G2 Recorded ──► Stage 6 Hermon Pending).
- Active Intent: ONT-37 / M98 — UMA Admission (GAP-DX-06), Apport Forensics (GAP-OM-21), Pytest Anti-Masking (GAP-DX-07).
- Verdict: VERIFIED ✅ (10/10 Dedicated Gates, 153/153 Full Repo Suite Passed, 0 Regressions, 16 FastMCP Invariant Preserved).
- Remediations: R1 (Assertion sync), R2 (Leaf numeric routing), R3 (Fail-soft signals), R4 (Fail-soft pytest defaults) all verified.
- Files Changed: engine/hardware.py (UMA & leaf routing), engine/privilege.py (schema), scripts/aep-ctl (flags), engine/crash_router.py (RFC822 & POSIX signals), server.py (anti-masking & metrics), tests/ (10-gate suite & R1 sync).
- Next Actions: (1) Hermon Stage 6 Atomic Git Commit; (2) Conventional Commit Message; (3) Pipeline Completion Report.

**Drop**:
- Verbose test runner output, dry run traces, intermediate file edits, and resolved audit remediation logs.
