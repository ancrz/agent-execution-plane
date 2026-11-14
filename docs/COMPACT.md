# Context Compaction Guidance: AEP (ONT-61 VERIFIED tras dos ciclos; documentación publicada en dev por Hermon)
Preserve: pipeline mode Short (control de costos); ONT-61 base `dev` `8d271f4`, HEAD `1120056` en worktree `agent-acf26c30de3644631` (rama `worktree-agent-acf26c30de3644631`).
Commits: `a369d22` (T0 G67 AEP_DATA_HOME), `ff28e2f` (T4 G66 json_each), `b527e77` (T3 G65 go en discover), `448307b` (T2 G64 sandbox /etc), `6f57a52` (T1 G63 FDs en subproceso), `e73d7d8` (aep-sync desechable), `1120056` (ciclo 2).
ONT-61 numbers: ciclo 1 DEFECTIVE LOGIC_ERROR en tests (om11, om12, om13 dependían de la DB real); ciclo 2 VERIFIED 1510 passed, 0 failed; DB real md5 205d8013… intacta.
Decisions taken by user/orchestrator: "Fix them." (G63–G66); G67 hallado en ONT-60 se atiende en ONT-61; modo Short; commits y push autorizados por el usuario; publicado en dev (modo Short).
Open items with routing: aep_front.py:63 BACKEND_LOG_DIR fuera de AEP_DATA_HOME (menor, front estable, solo logs); `setup.sh --update` pendiente de decisión del usuario.
Lesson: los tests siembran sus datos en un AEP_DATA_HOME temporal; nunca leen la DB real.
Next actions: (1) completado: commit de documentación ONT-61 publicado en dev por Hermon; (2) decidir BACKEND_LOG_DIR; (3) decidir `setup.sh --update` en el host.
Drop: pytest output, diffs intermedios, logs de subagentes, plan_ont61 ya ejecutado, detalle de commits ya en el registro.
Recovery: leer `docs/pipeline/feature_20261114_ont61_db_isolation.md` y este archivo; luego `git status` y `git log --oneline 8d271f4..HEAD` en el worktree.
