# Context Compaction Guidance: AEP (ONT-62 VERIFIED tras dos ciclos y publicado en dev; update real pendiente)
Preserve: pipeline mode Short (control de costos); ONT-62 base `dev` `a25d4a0`, HEAD `da05dd1` en worktree `agent-a00b767d80b587df1` (rama `worktree-agent-a00b767d80b587df1`); Graphos no hizo commits.
Commits ONT-62: `67896be` (T1 logs del front), `72750c8` (T2 hook G68, T3 pueue G69), `4eb222f` (T4 scope y RUNNING_UNMANAGED G70), `31690c2` (T5 venv G71), `9d3940f` y `da05dd1` (ciclo 2).
ONT-62 numbers: ciclo 1 DEFECTIVE LOGIC_ERROR (ruff reescribió la cabecera políglota de aep-ctl, 3 failed); ciclo 2 VERIFIED 1536 passed, 0 failed; DB real intacta (md5 205d8013… según registros previos).
Decisions taken by user: "continúa con los pendientes"; autorizó `setup.sh --update` completo asumiendo el blast radius; modo Short; commit y push de ONT-62 autorizados por el usuario para dev; main sigue user-gated.
Open items with routing: `setup.sh --update` real y `--check` con HOME real (orquestador); reconexión del front con `/mcp` (usuario, aplica T1). Publicado en dev (Hermon).
Next 3 actions: (1) ejecutar `setup.sh --update` real y confirmar rc 0 sin `uv venv` sobre el venv; (2) `setup.sh --check` con HOME real, hook en PASS; (3) ONT-62 ya publicado en dev por Hermon; no repetir la publicación.
Lesson: no pasar formateadores a archivos políglotas sin extensión (force-exclude); el update real es la prueba de los modos de instalador.
Drop: pytest output, diffs intermedios, logs de subagentes, detalle de commits ya registrado, plan_ont62 ya ejecutado.
Recovery: leer `docs/pipeline/feature_20261115_ont62_health_and_update.md` y este archivo; luego `git status` y `git log --oneline a25d4a0..HEAD` en el worktree.
