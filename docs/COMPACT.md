# Context Compaction Guidance: AEP (ONT-42b B9 PLAN_GAP; re-plan Archon pendiente; sin push)
**Preservar:**
- **Modo y baseline:** Full. `dev` @ `a34b5ac`. Suite 632 passed, 1 xfail (D-01b). 17 tools, 19 capacidades.
- **Hechos:** ONT-39, ONT-40, ONT-41 VERIFIED. ONT-42a VERIFIED completo: T8 en vivo (`harness_reconnect` execute confirm=true; inyectado 86 ms, sysctl 0→0, ledger ok, front pid 753000→921894, front_stale=false). ONT-42b B1–B8 integrados (`6490533..a34b5ac`).
- **Defecto abierto:** B9 DEFECTIVE (PLAN_GAP) → Archon re-plan. RC1: `SELECTION_CAP` 24 (`threads_ops.py:32`) > `TESTS_PER_ITERATION` 20 (`threads_verify.py:80`) → modo async → dispatcher fail-closed F3 → SANDBOX_UNAVAILABLE perpetuo. Además `pins=0` con 10 pins en spec (sin diagnosticar).
- **Commit no integrado:** `5a3c98b` en rama `worktree-agent-a783d592846aab250`. Vuelve vacuos `test_ont42_spec_change` y `test_ont42_gap_priority`: reescribir con fixtures sintéticos, no integrar relajados.
- **Recomendación del orquestador:** opción 2 (lotes sync re-entrantes ≤20 en sandbox), mismo mecanismo que condición 10 de Ontos para el gate C4.
- **Decisiones del usuario:** push de `dev` solo con autorización explícita. R7 (tier de push) pendiente si no se confirmó.
- **Riesgos:** ciclo `72871021d7de` abierto (`env_left` 8). `sudo use_pty` sin validar. Runners reales validados solo en clon.
- **Fuentes:** `docs/pipeline/feature_20261106_182001_ont42_judge_evolve.md` §13; `docs/pipeline/ont42_ontos_audit.md`; reporte B9 en el scratchpad de la sesión.
**Pendiente (próximas 3):**
1. Archon: re-plan de B9 (opción 2, diagnóstico de `pins=0`, tests con fixtures sintéticos). Ontos audita el re-plan.
2. Pragma: aplicar re-plan, B9 con ACCEPT real (`ran ≥ selected`, sin `unsandboxed`), luego C1–C3.
3. Usuario: decidir si se reescribe o descarta `5a3c98b`.
**Descartar:** logs de pytest, trazas de subagentes, llamadas intermedias de B9 ya resumidas en §13.3, ciclos cerrados (fix cycles de L3, BLOCKED de Ontos), detalle de T8 más allá de la línea de evidencia.
