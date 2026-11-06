# Context Compaction Guidance: AEP (ONT-41 fix ciclo 2 de 3, ONT-42a fix ciclo 1 de 3)
**Preservar:**
- **Modo y baseline:** Full. `dev` @ `52393aa`, push retenido hasta VERIFIED de ONT-41 y ONT-42a (AP-1). 17 tools, 19 capacidades. Suite 547 passed / 6 xfailed + tests Dokimos (3 xfail estrictos). ruff limpio.
- **Hechos:** ONT-39 Live Plane; ONT-40 autoevol; ONT-41 spec/verify/fix_test/heal + LKG; ONT-42a `aep_ctl ipc harness_reconnect` (plan/execute) implementado en worktree.
- **Defectos abiertos (LOGIC_ERROR → Pragma):**
  - ONT-41 ciclo 2 de 3: F7 (pytest ausente clasificado como fallo lógico) y F8 (poller async sin timeout ni estado pueue). F1 a F5 cerrados; F6 residual en L3. Detalle: feature §18.
  - ONT-42a ciclo 1 de 3: L1 bloqueante (binario `claude/versions/X.Y.Z` no reconocido por `find_harness`); L3 reaper incompleto (LKG tree y `_drain_and_terminate` sin await). L2 refutado. Detalle: feature §15.
- **Decisiones del usuario:** ONT-42a T8 (smoke en vivo) es user-gated. Push solo tras VERIFIED.
- **Riesgos:** runners reales validados solo en clon; huérfano `aep_backend.py` sobrevive a la muerte del front (sin causa raíz); playbook terse cerca del límite de 3000 bytes; subagentes agotan 50 turnos (commit por tarea).
- **Fuentes:** `docs/pipeline/feature_20261106_080856_ont41_autoevol_heal.md` (§17/§18), `docs/pipeline/feature_20261106_172315_ont42a_harness_reconnect.md` (§15), `docs/STATE.md`.
**Pendiente (próximas 3):**
1. Pragma: fix F7 y F8 de ONT-41; Dokimos re-testea (ciclo 3 de 3 si falla).
2. Pragma: fix L1 y L3 de ONT-42a en worktree; retirar xfail estrictos al corregir; Dokimos re-testea.
3. Tras VERIFIED de ambos: Graphos G2 (README, STATE, CHANGELOG de ONT-42a) y Hermon (push dev solo si se autoriza).
**Descartar:** logs de pytest, trazas de subagentes, diffs intermedios, ciclos BLOCKED ya resueltos, listados de pueue, detalle de F1 a F5 ya cerrados.
