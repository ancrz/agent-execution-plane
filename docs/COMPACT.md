# Context Compaction Guidance: AEP (ONT-60 VERIFIED tras dos ciclos; docs publicados en dev)
Preserve: pipeline mode Short (control de costos); ONT-60 base `dev` `3a89423`, HEAD `e211140` en worktree `agent-a0368bc8d404d0b6c`; commits `cf2d8fb` (T3 G60), `8da28ad` (T1 G58), `b9b7f43` (T2 G59), `5f35ed7` (T5 G62), `5dad90d` (T4 G61), `e211140` (corrección de seguridad del ciclo 2).
ONT-60 numbers: Dokimos VERIFIED 1498 passed, 0 failed, 205 s; ruff 324 limpio; ciclo 1 DEFECTIVE LOGIC_ERROR de seguridad en T2 (raíces que contienen rutas vetadas), corregido con raíces ancestras de rutas vetadas, `auto_mounts_skipped`, nombres validados y tope 64.
Decisions taken by user/orchestrator: publicación solo en `dev` (main no); trailers Sonnet 5.5 de los commits de Pragma conservados; G67 se atiende en ONT-61 T0, no en ONT-60.
Open items with routing: G67 alta (`import server` migra la DB real; aislar con `AEP_DATA_HOME`) → ONT-61 T0; G63 flaky `test_criterion_6_zero_fd_leak`; G64 sandbox sin `/etc/alternatives`; G65 bloque `go` en `discover`; G66 `IN (?,...)` por `json_each`. Operativo: `setup.sh --update` pendiente de decisión del usuario (`go.channel` null).
Hecho operativo: la salida de `output_ref` vive en `<pool>/sandbox_out/` y la limpia el reaper de slots; expirada devuelve `PARAM_ERROR` (re-ejecutar).
Next actions: (1) commit `docs(ONT-60)` publicado en `dev` (completado); (2) ONT-61 T0 cuando el usuario lo pida; (3) decidir `setup.sh --update` en el host.
Drop: pytest output, diffs intermedios, logs de subagentes, plan_ont60 ya ejecutado, detalle de commits ya en el registro.
Recovery: tras un crash, leer `docs/pipeline/feature_20261114_ont60_sandbox_packages.md` y este archivo; luego `git status` y `git log --oneline 3a89423..HEAD` en el worktree.
