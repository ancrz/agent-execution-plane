# Context Compaction Guidance: AEP (ONT-66 VERIFIED tras dos ciclos; gaps 0; publicado en dev por Hermon)
Preserve: pipeline mode Short; base `main` = `dev` `69b1b76`; worktree `agent-a1f0db185df7df481`, HEAD `5c93d12`; Graphos no hizo commits.
Commits ONT-66: `7129048` (análisis caliente + engine/notices.py), `ce8210c` (aep_notice en todas las respuestas, notices/ack), `fa1d18c` (push MCP aep.notice), `c6508ee` (gaps_open, relay ask_user, WF-0), `5c93d12` (endurecimiento, caché analizada).
ONT-66 numbers: Dokimos VERIFIED en 2 ciclos (ciclo 1 DEFECTIVE LOGIC_ERROR: 1691 passed, 3 failed); 1700 passed, 0 failed (reportado por Dokimos); gaps 0; test_ont41_coverage 11 passed; `_INSTRUCTIONS` 9388 B.
Decisions taken by user: aviso ruidoso (2026-11-15); publicar en main a decisión del usuario; diseño delegado al orquestador.
Open: publicado en dev (Hermon, ff); push MCP requiere /mcp del usuario; residuales: ack por proceso backend, avisos fuera del ledger.
Lessons: (1) filtrar texto reenviado al usuario por clase de caracteres; (2) informes limitados a lo commiteado; (3) pruebas de regresión deben fallar en la base.
Next actions: (1) usuario: /mcp para activar el push; (2) decidir publicación en main.
Drop: salida de pytest, diffs intermedios, logs de subagentes, detalle de commits ya registrado, plan de ONT-66 ya ejecutado.
Recovery: leer `docs/pipeline/feature_20261115_ont66_noisy_notices.md` y `docs/pipeline/feature_rollup.md`; luego `git status` y `git log --oneline 69b1b76..HEAD` en el worktree.
