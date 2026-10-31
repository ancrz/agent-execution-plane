# Context Compaction Guidance — AEP (Milestone ONT-31 Verified)

**Preserve**:
- Pipeline Mode: Full Pipeline (Dokimos Stage 5 VERIFIED ✅ -> Graphos G2 Baseline Refresh -> Hermon Stage 6 Release).
- Target Milestone: ONT-31 ("RE as SDD: Kali MCP Offensive/Defensive Primitives & Native Antigravity Integration") — VERIFIED & PROMOTED.
- Core Files: `server.py`, `engine/privilege.py`, `scripts/aep-ctl`, `tests/test_aep_kali_integration.py`, `docs/sdd/sdd_kali_mcp_offensive_tactical_enhancements.md`, `README.md`, `docs/MILESTONES.md`.
- Quality Status: 109/109 AEP core + 7/7 Kali MCP = 116 tests passing (100%), 0 failures, 0 regressions, 0 open defects.
- Architectural Invariants: Exactly 15 FastMCP tools preserved; zero host attack tool pollution; hybrid dual-plane container isolation.
- Next Actions: Hermon Stage 6 atomic release commit, tag & push authorization.

**Drop**:
- Superseded intermediate test outputs, raw execution traces, superseded pipeline state.
