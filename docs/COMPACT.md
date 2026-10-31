# Context Compaction Guidance — AEP (Milestone ONT-32 Verified)

**Preserve**:
- Pipeline Mode: Full Pipeline (Dokimos Stage 5 VERIFIED ✅ -> Graphos G2 Baseline Refresh -> Hermon Stage 6 Release).
- Target Milestone: ONT-32 ("Native Memory-First Network & Security Telemetry") — VERIFIED & PROMOTED.
- Core Files: `engine/net_telemetry.py`, `server.py`, `engine/privilege.py`, `scripts/aep-ctl`, `tests/test_net_security_telemetry.py`, `README.md`, `docs/MILESTONES.md`.
- Quality Status: 109/109 tests passing repository-wide (100%), 0 failures, 0 regressions, 8/8 ONT-32 gates certified.
- Architectural Invariants: Exactly 15 FastMCP tools preserved; zero container/Docker dependencies; pure in-RAM operations; sanitized semantics.
- Next Actions: Hermon Stage 6 atomic release commit, version tag & push authorization.

**Drop**:
- Superseded intermediate test outputs, raw execution traces, superseded pipeline state.
