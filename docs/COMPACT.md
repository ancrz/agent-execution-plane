# Context Compaction Guidance: AEP (ONT-57 VERIFIED; publicado en dev)
Preserve: pipeline mode Short (control de costos); ONT-57 VERIFIED en un ciclo sobre base `dev` `3ff0c6f`, 4 commits Pragma `13238bc`..`53958b8` en worktree `agent-ad62494bd780c4685`; docs de G2 publicados en dev junto al código.
ONT-57 numbers: Dokimos 1386 passed + 1 failed (`test_cold_extraction`, flake de carga, G56), ruff 307 limpio; T3 ida y vuelta por task_ids sobre copia de la DB real, 503/504/505 intactas.
Open defects with routing: G55 (reverso work→artifact→work no restaura estado; decisión de diseño, no bloqueante). G56 (flake de carga, tercer episodio; candidato medir CPU time con justificación escrita, sin acción sin ella). Backlog ONT-46: solo `_TypeIndex.resolve` Callable → Pragma en tanda futura.
Decisions taken by user/orchestrator: Short; severidad INFO/WARN/ERROR por tabla explícita (UNPROVEN y BROKEN a WARN); DRY_RUN con candidatos sugiere apply; reclassify por task_ids; ajuste del orquestador antes de Dokimos (escáner de ramas de ternario).
Next actions: (1) ONT-57 publicado en dev (Hermon, ff autorizado por el usuario); (2) decidir G55 (reverso con estado original) si se pide; (3) aplicar reclassify sobre la base real solo con decisión del usuario.
Drop: pytest output, diffs intermedios, logs de subagentes, planes superseded (plan_ont56 ejecutado), detalle de commits ya integrado en el registro.
Recovery: tras un crash, leer docs/pipeline/feature_20261114_ont57_severity_table.md y este archivo; luego git status y git log --oneline 3ff0c6f..HEAD.
