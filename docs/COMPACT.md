# Context Compaction Guidance — AEP (Milestone ONT-33 Verified)

**Preserve**:
- Pipeline State: Full Pipeline (Archon ✅ -> Graphos G1 ✅ -> Ontos ✅ -> Pragma ✅ -> Dokimos ✅ -> Graphos G2 ✅ -> Hermon Stage 6 ⏳).
- Active Milestone: ONT-33 ("Predictive Privilege-Aware Setup Pipeline & Chmod Graceful Degradation Matrix") — VERIFIED & PROMOTED ✅.
- Quality Status: 117/117 tests passed (100%), 0 regressions, 8/8 gates passed, Ruff SAST 0 errors.
- Invariants: FastMCP 15 tools strictly preserved (len(_tools) == 15); 4 chmod tiers (7rwx, 6rw-, 5r-x, 4r--); zero sudo prompt hangs.
- Modified Files: engine/privilege.py, scripts/setup.sh, scripts/aep-ctl, server.py, tests/test_privilege_degradation.py, README.md, docs/MILESTONES.md.
- Next Actions: Hermon (Stage 6) atomic commit on dev branch & handoff.

**Drop**:
- Intermediate shell traces, verbose test run outputs, superseded pipeline drafts.
