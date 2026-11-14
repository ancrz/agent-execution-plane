# Context Compaction Guidance: AEP (ONT-56 VERIFIED; publicado en dev)
Preserve: pipeline mode Short (default, control de costos); ONT-56 VERIFIED en un ciclo, publicado en dev por ff desde base `4fc7dc7`; 3 commits Pragma `f083a92` (G50 reclassify, dry-run por defecto), `ba327c5` (G51 next_action propio y NOOP terminal), `42dbb72` (backlog ONT-46, `_EXTERNAL_METHODS` literal 3.14.7).
ONT-56 numbers: Dokimos 1359 passed (187 s), ruff 303 limpio; reclassify sobre copia de la DB real: 17 candidatos, 17 reclasificadas, 2.a vez NOOP; grafo de hilos idéntico a 4fc7dc7 (7928 aristas, 1 gap).
Open defects with routing: ninguno bloqueante. Flake de carga `test_cold_extraction` (ONT-53 y ONT-56): vigilar, sin acción. Backlog ONT-46: solo `_TypeIndex.resolve` sin defaults Callable → Pragma en tanda futura.
Decisions taken by the user / orchestrator: Short; reclassify con dry-run por defecto; work→artifact a BACKLOG con score 0; snapshot de lista externa con SNAPSHOT_PY_VERSION 3.14.7, solo en detail del grafo.
Next actions: (1) decidir si se aplica reclassify sobre la base real (revertir con task_id, no title_like); (2) backlog ONT-46 `_TypeIndex.resolve` si se pide.
Drop: pytest output, diffs intermedios, logs de subagentes, mediciones de scratchpad, planes superseded (plan_ont55 ejecutado), detalle de T1-T3 ya integrado en el registro.
Recovery: tras un crash, leer docs/pipeline/feature_20261114_ont56_reclassify_snapshot.md y este archivo; luego git status y git log --oneline 4fc7dc7..HEAD en el repo principal (`dev`).
