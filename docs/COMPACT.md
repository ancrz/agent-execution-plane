# Context Compaction Guidance: AEP (ONT-68 VERIFIED tras dos ciclos; sin commit, Hermon commitea a dev)
Preserve: pipeline mode Short; base `dev` `c4345e8`; cambios ONT-68 sin commit en `server.py`, `engine/catalog.py`, `scripts/setup.sh`, `tests/test_ont40_acceptance.py`, `tests/test_ont67_setup_memory.py` y `tests/test_ont68_elf_cache.py` (nuevo); Graphos no hizo commits.
Preserve ONT-68 numbers: Dokimos VERIFIED 1751 passed, 0 failed (serie), gaps 0, md5 de la DB real sin cambios; ciclo 1 LOGIC_ERROR solo en tests (3 tests sin `covers` de bordes, 3 gaps, 7 fallos).
Preserve corrections: el magic ELF de ONT-67 era falso positivo (byte 0x7f en bruto, verificado con `od`); `KEEP_EMBED_IDLE` era un bug real y queda reaplicado tras reescribir `toolchain.env`.
Decisions taken by user: corregir los tres hallazgos reportados como AEP; publicar con Hermon en `dev` y luego fast-forward de `dev` a `main` con ONT-66, ONT-67 y ONT-68 ("procesa lo que falta"); sin force.
Open (no bloquean ONT-68): carrera benigna en la caché ELF entre el reemplazo del archivo y `register_artifact`; `test_ont40_acceptance` mitigado, sensible a carga.
Next 3 pending actions: (1) Hermon commit en `dev` de los cambios ONT-68; (2) fast-forward `dev` a `main` (ONT-66 a ONT-68); (3) definir el intent ONT-69 (no definido) y cerrar el rollup 66..70 con ONT-70.
Drop: salida de pytest, tablas de bench intermedias, logs de subagentes, detalle de hallazgos ya registrado en `feature_20261116_ont68_aep_findings.md`.
Recovery: leer `docs/pipeline/feature_20261116_ont68_aep_findings.md` y `docs/pipeline/feature_rollup.md`; luego `git status` y `git log --oneline -5` en el repo principal.
