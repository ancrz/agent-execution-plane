# Context Compaction Guidance: AEP (ONT-64 VERIFIED en un ciclo; publicado en dev)
Preserve: pipeline mode Short; base `dev` `fe59411`; worktree `agent-a1a8de650a0c35de8` (rama `worktree-agent-a1a8de650a0c35de8`), HEAD `140a165`; Graphos no hizo commits.
Commits ONT-64: `4848735` (_trim_path por componente, bytes UTF-8), `4535d83` (README sin claim de conteo), `140a165` (pre-commit ejecuta test_ont41_coverage).
ONT-64 numbers: Dokimos VERIFIED en 1 ciclo, 1657 passed, 0 failed; gaps = 1 (gate8, baseline); fuzz 300 000 rutas <= 60 B y UTF-8 válido; DB real intacta.
Decisions taken by user: continuar con el cosmético de aep_python.path (2026-11-15); diseño delegado al orquestador; regla NO DUPLICAR; escalera L0 -> L1 -> L2.
Open items with routing: publicado en dev por Hermon (ff `fe59411`..`dev`, autorizado por AP-1 tier 7rwx); observación sin impacto: último componente de 58-60 B cortado con `…` (Pragma, opcional).
Lessons: (1) los commits de docs posteriores a la verificación también rompen gates, porque el grafo lee *.md; el hook lo impide ahora; (2) RCA: la causa fue la documentación, no el código.
Next actions: (1) confirmar con el usuario el siguiente track; (2) ONT-65 es el quinto documento y hace rollup (feature_rollup.md).
Drop: salida de pytest, diffs intermedios, logs de subagentes, detalle de commits ya registrado, plan de ONT-64 ya ejecutado.
Recovery: leer `docs/pipeline/feature_20261115_ont64_path_trim_and_doc_gate.md` y este archivo; luego `git status` y `git log --oneline fe59411..HEAD` en el worktree.
