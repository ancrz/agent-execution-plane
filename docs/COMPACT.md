# Context Compaction Guidance — AEP (Milestone ONT-36 VERIFIED)

**Preserve**:
- Pipeline State: Full Mode (Archon Stage 1 Rev2 ✅ -> Graphos G1 Rev2 Weave ✅ -> Ontos Stage 3 Approved ✅ -> Pragma Stage 4 Executed ✅ -> Dokimos Stage 5 Verified ✅ -> Graphos G2 Recorded ✅ -> Hermon Stage 6 Ready ⏳).
- Active Intent: ONT-36 / M97 ("Hardware Domain GAP-CP-05 & Apport Alerts GAP-OM-20") — VERIFIED ✅ (10/10 Gates Passed, 143/143 Full Suite Passed, 0 Ruff errors, 0 Semgrep blocking findings).
- Open Defects & Routing: 0 defects; all 5 Ontos remediations (R-1 through R-5) verified in tests/test_hardware_and_apport_alerts.py; routed to Hermon.
- Key Invariants: FastMCP 16 tools invariant (`len(_tools) == 16`); 4096 MiB desktop safety margin (`engine/hardware.py`); 4-tier chmod governance (9 domains); Apport crash header sync & permission-safe dedup; flat `t: {"ms": ..., "tok": ...}` stub in compact telemetry.
- Target Modules: `engine/hardware.py` (new), `engine/privilege.py`, `engine/crash_router.py`, `engine/telemetry.py`, `scripts/aep-ctl`, `server.py`, `tests/test_hardware_and_apport_alerts.py`, `tests/test_privilege_degradation.py`, `tests/test_net_security_telemetry.py`, `tests/test_agent_experience_evaluation.py`, `scripts/setup.sh`, `README.md`, `docs/MILESTONES.md`.
- Next 3 Pending Actions: (1) Hermon Stage 6 Atomic Release & Conventional Commit; (2) Git tag / push authorization; (3) Next milestone planning / idle.

**Drop**:
- Verbose test traces, intermediate diffs, superseded planning drafts, resolved audits.
