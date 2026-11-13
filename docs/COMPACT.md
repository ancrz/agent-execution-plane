# Context Compaction Guidance: AEP (ONT-46 precision del extractor VERIFIED; publicado en dev)
Preserve: pipeline mode Short (default, cost control; Full only on user request or blast radius); ONT-46 VERIFIED en worktree ae5bdcba, HEAD 6aad7e0 + docs; publicado en dev.
ONT-46 numbers: 1147 passed / 0 failed; ruff limpio; extraccion en frio 1.50-1.72 s (tope 2.0 s); root_hash bb4094ddcf76; aristas 7194 (base 7264), weak 111; gaps 1 (test_gate8); co-dependencias 0; terse keys identicas a dev.
Baseline: branch `dev` base `99f80bb` (ONT-45 `92459e2`/`99f80bb`, ONT-44 `e0a9317`); worktree agent-ae5bdcba0132a8346 con commits Pragma `6b05f7b`..`6aad7e0`.
Files and why: `engine/threads_extractors.py`, `engine/threads_model.py`, `engine/threads.py` (tipado de receptor, Edge.weak, threads/2); `tests/test_ont46_extractor_precision.py` (nuevo); docs (feature ont46, SDD ont46, README badge 1147 y linea ONT-46, STATE, MILESTONES 13).
Decisions taken by the user: Short por defecto; commit (Hermon) y push user-gated; residuo de 1 gap (`test_gate8_semantic_sanitization`) visible, sin maquillar.
Open defects: none blocking. Backlog: `_TypeIndex.resolve` sin defaults Callable; `file_units` incluye weak; `_EXTERNAL_METHODS` depende de py_version; 20 nombres de metodo coinciden con la lista externa.
Next 3 pending actions: (1) comprobar en el plano vivo que `discover(capabilities)` da stale=false tras el hot-swap; (2) verificar margen de extraccion en frio (1.5-1.7 s vs 2.0 s) antes de nuevas aristas al grafo; (3) backlog ONT-46 (defaults Callable, file_units weak).
Drop: pytest output, intermediate diffs, subagent logs, superseded plans, resolved ciclo-1 detail (F1, F1b ya integradas), the perf profiling tables.
Recovery: tras un crash, leer `docs/pipeline/feature_20261113_ont46_extractor_precision.md` y este archivo, luego `git status` en el worktree.
