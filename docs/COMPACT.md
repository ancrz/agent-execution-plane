# Context Compaction Guidance: AEP (ONT-41 y ONT-42a VERIFIED; push retenido)
**Preservar:**
- **Modo y baseline:** Full. `dev` @ `c52861c`, 36 commits por delante de `origin/dev` (`e3f7725`). Suite 562 passed / 6 xfailed, ruff limpio, 0 huérfanos. 17 tools, 19 capacidades.
- **Hechos:** ONT-39, ONT-39b, ONT-40, ONT-40b y ONT-41 VERIFIED (2 ciclos de fix); ONT-42a VERIFIED excluyendo T8 (1 ciclo de fix).
- **Backlog (no bloqueante):** o1 ONT-42a (anclar `_VERSIONED_CLAUDE_RE` a `$HOME/.local/share/claude/versions`); o2 ONT-41 (`os._exit` omite `atexit` de `GLOBAL_SOCKET_MUX.stop`, benigno, autocura); o3 ONT-41 (job exitoso sin resumen tratado como ambiental, conservador).
- **Decisiones del usuario:** T8 (smoke en vivo `execute` de harness_reconnect, sudo + TIOCSTI) es user-gated, pendiente de consentimiento. Push de `dev` solo tras autorización explícita.
- **Riesgos:** `sudo use_pty` puede sustituir stdin del helper (falla cerrado a manual), sin validar hasta T8; runners reales validados solo en clon; playbook terse cerca del límite de 3000 bytes.
- **Fuentes:** `docs/pipeline/feature_20261106_080856_ont41_autoevol_heal.md` §19, `docs/pipeline/feature_20261106_172315_ont42a_harness_reconnect.md` §16, `docs/STATE.md`, `docs/MILESTONES.md`.
**Pendiente (próximas 3):**
1. Hermon: commit `docs(pipeline): record VERIFIED for ONT-41 and ONT-42a`; push a `dev` solo si el usuario lo autoriza.
2. Usuario: decidir consentimiento para T8; si se autoriza, ejecutar y registrar el resultado en ONT-42a §16.
3. L3 = D-01..D-05 (primer ciclo autoevol en vivo); después ONT-42 (`autoevol evolve`, única acción fuera de alcance).
**Descartar:** logs de pytest, trazas de subagentes, diffs intermedios, ciclos BLOCKED o DEFECTIVE ya cerrados, listados de pueue, detalle de F1 a F8 y L1 a L3 ya cerrados.
