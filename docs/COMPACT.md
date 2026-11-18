# Compact: AEP ONT-69 publicado (dev = main, código 92ca91b)
Preserve: `main` = `dev` = `origin/*` (código ONT-69 `8502287`..`92ca91b`, docs posteriores); 1755 passed (serie), gaps 0, codep 0, hazards 0, cobertura none 8; backend en el head, `stale` false; modo de pipeline Short por defecto.
Preserve: reglas: push a `main` con autorización por track; `dev` solo ff tras VERIFIED; nunca force; tests nunca tocan la DB real (AEP_DATA_HOME tmp); sin sysctl/zram/KSM/THP en el host; avisos de AEP al usuario como "AEP reporta X, ¿quieres mejorarlo?"; `harness_reconnect force` solo con aprobación explícita; verificar literales de bytes con `od`.
Preserve: trabajo en worktree aislado (`git worktree add ../aep-ontNN`) para que el servidor vivo no recargue código a medio editar.
Open (opcional): 8 funciones "none" (privadas); rollup 66..70 se cierra con ONT-70; swap del host por otra sesión (no AEP).
Drop: salidas de pytest, logs de subagentes, planes superados, diffs ya commiteados.
Recovery: `docs/STATE.md`, `docs/pipeline/feature_rollup.md`, `docs/pipeline/feature_20261118_ont69_autoevol_findings.md`, `git log -1 main dev`.
Hint: las cifras de cobertura y hazards se confirman con `autoevol(action="graph", persist=false)`.
