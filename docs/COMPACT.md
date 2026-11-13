# Context Compaction Guidance: AEP (ONT-44 cobertura MCP VERIFIED, staged sin commit; gaps 46)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); ONT-44: VERIFIED (1092 passed, previo 987; ruff check y format limpios; gaps 120 a 46 con trinquete GAPS_BASELINE=46; 17 tools / 19 capacidades; sin claim_drift); cambios staged, NO commit.
Baseline: branch `integ/coverage`, worktree `integ-cov`, base `e0a9317`; ONT-43 y endurecimiento ya publicados (`d12e090`, `e0a9317`).
Files and why: `engine/backup.py`, `engine/catalog.py`, `engine/privilege.py`, `server.py` (correcciones P1 a P5); `tests/test_cov_*.py` (5 archivos nuevos, cobertura de superficie); `tests/test_ont41_coverage.py` (trinquete 46); `tests/test_l3_contract_compaction.py` (schema D-04); docs (STATE, MILESTONES §11, rollup, SDD ONT-44, README).
Decisions taken by the user: Short by default; commit (Hermon) and push user-gated; `micro_snapshot` sin gate en servidor aceptado como diferencia conocida con el CLI.
Open defects: none blocking. Residuo: 15 tests sin referencia a código; gaps tipo `asserts`; sin covers en `aep_front.main`, `aep_front.create_front_server`, `aep_backend.main`, `BackendWorker`.
Next 3 pending actions: (1) user authorizes commit (Hermon) of the staged tranche; (2) user authorizes publication to `dev` (check `git log origin/dev` and reflog first); (3) next batch: residuo `asserts` before lowering GAPS_BASELINE.
Drop: pytest output, intermediate diffs, subagent logs, superseded plans, resolved P1 to P5 detail.
Recovery: after a crash, read `docs/pipeline/feature_20261113_004026_mcp_coverage_reinforcement.md` and this file, then `git status` in the worktree.
