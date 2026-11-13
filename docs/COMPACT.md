# Context Compaction Guidance: AEP (ONT-45 residuo Topos VERIFIED, staged sin commit; gaps 1)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); ONT-45: VERIFIED (1121 passed, previo 1092; ruff check limpio; gaps 46 a 1 con trinquete GAPS_BASELINE=1; 17 tools / 19 capacidades; sin claim_drift; 0 co-dependencias); cambios staged, NO commit.
Baseline: branch `integ/ont45`, worktree `integ-ont45`, base `e1d661f`; ONT-43 y ONT-44 ya publicados (`d12e090`, `e0a9317`).
Files and why: `tests/test_token_budgets.py` (budgets de lectura de aep_ctl); `tests/test_cov_live_plane_core.py` (N2/N3 con guarda `_Fd1Guard`); diez archivos de tests con aserciones aditivas (N4); `README.md` (badge 1121, línea de gaps 1, tabla de contrato aep_ctl solo con líneas nuevas); docs (STATE, MILESTONES §12, rollup, SDD ONT-45).
Decisions taken by the user: Short by default; commit (Hermon) y push user-gated; residuo de 1 gap (`test_gate8_semantic_sanitization`) se deja visible, sin símbolo ficticio; budgets dependientes del host descartados.
Open defects: none blocking. Residuo: 1 gap; `test_d11` usa `server.mcp._tool_manager._tools` (privado, fragilidad leve).
Next 3 pending actions: (1) user authorizes commit (Hermon) of the staged tranche (ONT-44 + ONT-45); (2) user authorizes publication to `dev` (check `git log origin/dev` and reflog first); (3) ONT-46: precisión del extractor de threads (resolución por nombre de métodos; imports sólo top-level).
Drop: pytest output, intermediate diffs, subagent logs, superseded plans, resolved N1 to N4 detail, the rate-limit interruption trail.
Recovery: after a crash, read `docs/pipeline/feature_20261113_080406_ont45_topos_residue.md` and this file, then `git status` in the worktree.
