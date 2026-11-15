# Context Compaction Guidance: AEP (ONT-65 VERIFIED tras dos ciclos; gaps 0; publicado en dev y main)
Preserve: pipeline mode Short; base `dev` `fa1c1b9`; worktree `agent-a528667b8d6f54be6`, HEAD `086dc02`; Graphos no hizo commits.
Commits ONT-65: `9bb7758` (read_mods: lecturas de .py por ruta literal como covers débiles), `7c29bfb` (GAPS_BASELINE 0), `535b4b0` (primer operando anclado a la raíz), `086dc02` (tests de spec con gaps sintéticos).
ONT-65 numbers: Dokimos VERIFIED en 2 ciclos (ciclo 1 LOGIC_ERROR: 3 tests con gaps[0], 75 aristas desde fixtures); 1666 passed, 0 failed; gaps == []; DB real intacta; enmascaramiento re-probado 0 gaps perdidos.
Decisions taken by user: push a main autorizado solo con 0 gaps (2026-11-15); diseño delegado al orquestador; regla NO DUPLICAR; ONT-66 encolado (aep_notice ruidoso).
Publicado: `fa1c1b9..086dc02` en dev (ff) y luego main (ff a dev), sin force (Hermon, modo Short). Evidencia registrada: rendimiento del análisis 1.62 s → 1.59 s (ciclo 1) y ~0.75 s tras el ciclo 2, dentro del criterio ≤5 %; `ruff check` y `ruff format --check` limpios (350 archivos, Dokimos ciclo 2).
Lessons: (1) cero gaps solo vale sin enmascarar; (2) tests no usan gaps reales como material; (3) no escribir en la DB real durante una verificación.
Next actions: (1) ONT-66 aep_notice (plan en `docs/pipeline/plan_ont66_noisy_notices.md`); (2) setup.sh --update real en el host (ONT-62).
Drop: salida de pytest, diffs intermedios, logs de subagentes, detalle de commits ya registrado, plan de ONT-65 ya ejecutado.
Recovery: leer `docs/pipeline/feature_20261115_ont65_zero_gaps.md` y `docs/pipeline/feature_rollup.md`; luego `git status` y `git log --oneline fa1c1b9..HEAD` en el worktree.
