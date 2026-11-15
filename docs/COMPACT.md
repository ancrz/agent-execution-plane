# Context Compaction Guidance: AEP (ONT-63 VERIFIED tras tres ciclos; publicado en dev)
Preserve: pipeline mode Short; base `dev` `df039ee`, HEAD `98efe5b` en worktree `agent-a66c3a57c6b314ef0` (rama `worktree-agent-a66c3a57c6b314ef0`); Graphos no hizo commits.
Commits ONT-63: `374f83d` (a), `506ec55` (b), `678f07e` (c), `c6fb6d6` (d), `5dc7426` (D1), `f1246a3` (D2), `8b99039` (R1-R5), `98efe5b` (D3).
ONT-63 numbers: ciclo 1 DEFECTIVE LOGIC_ERROR (D1, D2); ciclo 2 DEFECTIVE seguridad (D3 symlink ~/.docker); ciclo 3 VERIFIED 1637 passed, 0 failed; DB real intacta.
Decisions taken by user: diseño delegado al orquestador; regla NO DUPLICAR; escalera L0 -> L1 -> L2; net-reach y proc-detail descartados como primitivas.
Resueltos por orquestador: net_telemetry dentro de alcance (network probe grupo c); tests modificados sin aserciones relajadas; tiers verificados (ORIENT_REGISTRY + test_orientation_primitives_run_in_auditor_tier).
Open items with routing: publicado en dev (Hermon, ff sobre df039ee); cosmético `aep_python.path` recorta "Documents" (Pragma, opcional).
Next 3 actions: (1) decidir si el cosmético `aep_python.path` entra en un track posterior; (2) confirmar con el usuario el siguiente track; (3) ONT-65 es el quinto documento del rollup.
Lessons: (1) probar con frases naturales; (2) listas de vetos comparadas léxica y resueltamente, en un único sitio; (3) tests sin symlinks no reflejan hosts reales (Docker Desktop enlaza ~/.docker).
Drop: pytest output, diffs intermedios, logs de subagentes, detalle de commits ya registrado, plan_ont63 ya ejecutado.
Recovery: leer `docs/pipeline/feature_20261115_ont63_orientation_layer.md` y este archivo; luego `git status` y `git log --oneline df039ee..HEAD` en el worktree.
