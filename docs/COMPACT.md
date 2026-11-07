# Context Compaction Guidance: AEP (ONT-42c: E1 y C1–C3 en dev; D-EV-1 abierto)
**Preservar:**
- **Modo:** Short por defecto (costos). Full sólo si el usuario lo pide o el blast radius lo exige.
- **Baseline:** `dev` @ `00cbadb` (origin/dev @ `be78115`, sin push). Suite 697 passed; xfail strict de D-EV-1 en `00cbadb`.
- **Cerrado (OK):** E1 juez no falsificable `f8b92c8` (D-01b en 4 variantes); C1–C3 `4a7b61f` (tiers, fence, ff-only, prohibiciones, stale antes de push). Registro: `docs/pipeline/feature_20261106_182001_ont42_judge_evolve.md` §16.
- **Defecto abierto:** D-EV-1 DEFECTIVE (LOGIC_ERROR): ACCEPT no atado al tree hash → Pragma fix ciclo 1/3 → re-Dokimos.
- **Menores (documentar):** M-1 E1 solo drift/código público; M-2 discriminación entre seleccionados, señal débil; M-3 docstring de `evolve` desfasado.
- **Decisiones del usuario:** AEP recarga sólo su propia sesión (ancestría estricta); Short por defecto.
- **Pendientes ordenados:** (1) fix D-EV-1; (2) C4 gate final con `run_tests_batched`, C5 ledger/idempotencia, C6 rollback `git revert`, C7 Merkle `R_before`/`R_after` + SDD §9; (3) E2 specs incrementales, E3 OTP sobre SCC, E4 reconciliación; backlog O-1, O-2, `select_fields`, `lkg_restore covers`.
- **Commit:** lo hace Hermon junto con el fix de D-EV-1, no Graphos.
- **Recuperación:** tras caída, worktree vacío con ref corrupta eliminado; `git fsck` limpio.
**Descartar:** trazas de pytest, diffs intermedios, logs de subagentes, worktrees de agentes ya cosechados y detalles de E1/C1–C3 ya verificados.
