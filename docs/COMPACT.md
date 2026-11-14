# Context Compaction Guidance: AEP (ONT-59 VERIFIED en un ciclo; publicado en dev y main)
Preserve: pipeline mode Short (control de costos); ONT-59 base `dev` `da22d5d`, HEAD `9ee5d8c` en worktree `agent-a136904026e74a4af`; commits `fa64ad7` (T4), `ad20bcb` (T1 K1), `23dd2d5` (T2 K2), `37095cb` (T3 K3), `9ee5d8c` (T5 canal stable).
ONT-59 numbers: Dokimos 1462 passed, 0 failed; ruff 318 limpio; migraciones sobre copia de la DB real (322 tarjetas, 95 artefactos) idempotentes; K1 de punta a punta con go1.27.4.
Decisions taken by user/orchestrator: kanban con filosofía Go (K1 contenido, K2 errores como valores, K3 curación mecánica, T4 toolchain soportado); Go `stable` por defecto en el montaje (`AEP_GO_CHANNEL=pinned` para fijar; pin de caída go1.27.4); host Go 1.22.5 → 1.27.4 (rollback `/mnt/apps/tools/go1.22.5`); reinicio deja stats a cero y tarjetas legadas sin source_hash se democionan al recompilar (aceptado).
Open items with routing: G61 acción `lint` sin build_env (server.py ~1510) y G62 previous_stats de una generación → ONT-59 menor (Pragma si el usuario lo pide); G58–G60 → ONT-60 (cuando el usuario lo pida).
Hecho operativo: 40 tarjetas vivas con source_hash NULL bajan a LINTED al recompilar y recuperan promoción al pasar canary.
Next actions: (1) Hermon commit `docs(ONT-59)` con los documentos de este G2, publicado en dev y main con autorización explícita del usuario (2026-11-14); (2) ONT-60 cuando el usuario lo pida.
Drop: pytest output, diffs intermedios, logs de subagentes, plan_ont59 ya ejecutado, detalle de commits ya en el registro.
Recovery: tras un crash, leer docs/pipeline/feature_20261114_ont59_go_philosophy_kanban.md y este archivo; luego `git status` y `git log --oneline da22d5d..HEAD` en el worktree.
