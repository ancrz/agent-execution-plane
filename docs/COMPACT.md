# Context Compaction Guidance — AEP (Milestone ONT-34 Verified)

**Preserve**:
- Pipeline State: Full Mode (Archon ✅ -> Graphos G1 ✅ -> Ontos ✅ -> Pragma Stage 4 ✅ -> Dokimos Stage 5 VERIFIED ✅ -> Graphos G2 Record ✅ -> Hermon Stage 6 Release ⏳).
- Active Milestone: ONT-34 / M95 ("FastMCP Tool #16 default_primitives & Factory Decoupling") — VERIFIED ✅ (123/123 tests passing, 100%, 0 errors Ruff).
- Verified Invariants: Exactly 16 FastMCP tools (`len(_tools) == 16`), 19 capabilities (`len(_CAPABILITIES) == 19`), 4-tier chmod octal matrix (`7rwx`/`6rw-`/`5r-x`/`4r--`), `output_schema is None` (GAP-OM-19), zero sudo prompt hangs (`sudo -n true`).
- Verified Artifacts: `docs/pipeline/feature_20261104_105500_ont34_default_primitives_and_factory_decoupling.md`, `execution_report_20261104_114000_ont34_default_primitives_and_factory_decoupling.md`, `verification_report_20261104_121500_ont34_default_primitives_and_factory_decoupling.md`.
- Files Changed: 17 modified (`server.py`, `engine/privilege.py`, `templates/registry.json`, `engine/catalog.py`, `scripts/setup.sh`, `scripts/aep-sync.sh`, 7 test files, docs), 2 code created (`engine/primitives.py`, `tests/test_default_primitives.py`).
- Next Actions: (1) Hermon Stage 6 Atomic Release & Conventional Commit (`feat(mcp): ont-34 ...`); (2) Git Tag / Release Notes; (3) Final repo synchronization.

**Drop**:
- Verbose test run outputs, intermediate stack traces, superseded planning drafts.
