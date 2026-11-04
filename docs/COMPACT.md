# Context Compaction Guidance — AEP (Milestone ONT-35 Verified)

**Preserve**:
- Pipeline State: Short Mode (Pragma Stage 4 ✅ -> Dokimos Stage 5 VERIFIED ✅ -> Graphos G2 Record ✅ -> Hermon Stage 6 Release ⏳).
- Active Milestone: ONT-35 / M96 ("Version Stamp Integrity GAP-RT-04, Multi-Harness Sync GAP-RT-03 & Sandbox Ergonomics") — VERIFIED ✅ (133/133 tests passing, 100%, 0 Ruff SAST errors).
- Verified Invariants: `LOADED_COMMIT` + source hash freeze at import, call-time `repo_head` & `stale` calculation with `WARN`/restart hint; non-destructive `aep-sync.sh --audit` multi-harness inspection; structured Ruff parser (`check`/`format`); `sandbox_run` brief stdout truncation cap (20 lines); uv auto-mount.
- Verified Artifacts: `docs/pipeline/feature_20261104_133000_ont35_version_stamp_integrity_and_sync.md`, `verification_report_20261104_133500_ont35_version_stamp_integrity_and_sync.md`, `reports/2026-11-04_aep_ont30_34_consumer_verification.md`.
- Files Changed: 3 modified (`server.py`, `engine/telemetry.py`, `scripts/aep-sync.sh`), 1 test created (`tests/test_version_integrity.py`), +493/-68 lines, 0 scope creep.
- Next Actions: (1) Hermon Stage 6 Atomic Release & Conventional Commit (`fix(runtime): ont-35 version stamp integrity, multi-harness sync & sandbox ergonomics`); (2) Git Tag / Release Notes; (3) Multi-harness status report.

**Drop**:
- Verbose test run outputs, intermediate stack traces, superseded planning drafts.
