# Context Compaction Guidance: AEP (ONT-67 VERIFIED en un ciclo; publicado en dev)
Preserve: pipeline mode Short; base `dev` `2317d8d`; worktree `agent-a97a79376546e1bcf`, HEAD `e2f1e19`; Graphos no hizo commits.
Preserve ONT-67 commits: `47b1c14` (T2 memfd CLOEXEC/MFD_EXEC y sellos), `3c180ae` (T3 descarga del embedder y malloc_trim), `a023297` (T4 caché sin AST), `eb5b7ad` (T7 zstd en tmpfs), `e2f1e19` (T8 línea Memory y toolchain.env).
ONT-67 numbers: Dokimos VERIFIED 1740 passed, 0 failed, gaps 0, DB real intacta; reposo -41,6 % RSS; tras autoevol -43,2 %; recarga del embedder +136 ms una vez; sandbox grande +5,6 ms.
Decisions taken by user: aplicar solo lo que mejora la RAM medida; el instalador debe contemplarlo en fresh start; sin cambios de sysctl, zram, KSM ni THP en el host.
Open defects (no bloquean ONT-67): `server.py:2067/2079` magic ELF nunca coincide (routing: ONT futuro, Short); `test_ont40_acceptance` sensible a carga; `KEEP_EMBED_IDLE` muerta en `setup.sh` (eliminar o cablear).
Open: publicado en `dev` (Hermon, fast-forward, sin force); `main` solo por decisión del usuario.
Next 2 pending actions: (1) ONT futuro para el magic ELF y la caché binaria en disco; (2) decidir `KEEP_EMBED_IDLE` (eliminar o cablear a `AEP_EMBED_IDLE_S`).
Drop: salida de pytest, tablas de bench intermedias, logs de subagentes, plan de ONT-67 ya ejecutado (ver `plan_ont67_ram_efficiency.md`), detalle de commits ya registrado.
Recovery: leer `docs/pipeline/feature_20261116_ont67_ram_efficiency.md` y `docs/pipeline/feature_rollup.md`; luego `git status` y `git log --oneline 2317d8d..HEAD` en el worktree.
