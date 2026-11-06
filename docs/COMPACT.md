# Context Compaction Guidance: AEP (L3 VERIFIED; ONT-42 pendiente; sin push)
**Preservar:**
- **Modo y baseline:** Short para L3. `dev` @ `e36a608`. Suite 576 passed, 0 xfail, ruff limpio. 17 tools, 19 capacidades.
- **Hechos:** ONT-39, ONT-39b, ONT-40, ONT-40b, ONT-41 VERIFIED (2 ciclos de fix); ONT-42a VERIFIED excluyendo T8 (1 ciclo de fix); L3 D-01..D-05 VERIFIED (0 ciclos de fix; commits `4af584d`, `5999cb1`, `9b2f11e`, `8068f8b`, `e36a608`).
- **Backlog ONT-42 (bloqueante para `autoevol evolve` y auto-commit):** D-01b LOW; AE-1 ref corta en spec; AE-2 spec sin apuntar al código; AE-3 `SANDBOX_UNAVAILABLE` sin `.venv` canónico; AE-4 `fix_test` atascado en `awaiting reload`; AE-5 ranking entierra `open_discrepancy`; AE-6 no predice tests de comportamiento viejo. Detalle: `docs/pipeline/feature_20261106_181608_l3_token_contract.md` §5.
- **Decisiones del usuario:** T8 (smoke en vivo `execute` de harness_reconnect, sudo + TIOCSTI) es user-gated. Push de `dev` solo tras autorización explícita.
- **Riesgos:** `sudo use_pty` puede sustituir stdin del helper (falla cerrado a manual), sin validar hasta T8; runners reales validados solo en clon; `autoevol` aún no es juez autónomo.
- **Fuentes:** `docs/pipeline/feature_20261106_181608_l3_token_contract.md`, `docs/pipeline/feature_20261106_172315_ont42a_harness_reconnect.md` §16, `docs/STATE.md`, `docs/MILESTONES.md`.
**Pendiente (próximas 3):**
1. Hermon: commit `docs(pipeline): record L3 VERIFIED and autoevol AE-1..AE-6 backlog`; sin push.
2. ONT-42: cerrar AE-1..AE-6 y D-01b antes de `autoevol evolve` y auto-commit.
3. Usuario: decidir consentimiento para T8 (user-gated).
**Descartar:** logs de pytest, trazas de subagentes, diffs intermedios, ciclos BLOCKED o DEFECTIVE ya cerrados, listados de pueue, detalle de F1 a F8 y L1 a L3 ya cerrados.
