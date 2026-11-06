# Context Compaction Guidance: AEP (ONT-41 implementado, Dokimos pendiente)

**Preservar:**
- **Baseline:** `dev` en `e8f13b8` (18 commits por delante de `origin/dev` = `e3f7725`; el push está retenido hasta el VERIFIED de Dokimos, según AP-1). 17 tools, 19 capacidades. Suite: 477 passed, 6 xfailed (D-01..D-05). ruff limpio. autoevol: 103 gaps, own_gaps=0, codep=0.
- **Hechos:**
  - ONT-39 Live Plane (front estable con backend hot-swap y fence `AEP_SWAP_FENCE_PATH`).
  - ONT-40 `autoevol` (grafo de hilos con Merkle R).
  - ONT-41: `spec/verify/fix_test/heal`, `aep_lkg.py` (LKG content-addressed en `~/.local/share/agent-os/lkg`), front N0-N2 con barrera `_barrier`, `aep_ctl backup lkg_*`, `crash_events.source` y spool, y `--audit` D-24.
- **Pendiente:**
  1. Dokimos ONT-41 (cortado por el límite de la API; reanudar).
  2. Graphos G2 y Hermon: push de dev.
  3. Reconexión `/mcp` para activar el front de C1. Rollback: `git checkout pre-ont41-front -- aep_front.py`.
  4. Dogfooding de `fix_test` real.
  5. L3: D-01..D-05 como primer ciclo de autoevol.
  6. ONT-42 `evolve` con auto-commit y auto-push (AP-1).
- **Riesgos:**
  - El playbook en summary está en 2990/3000 bytes.
  - Los runners reales (sandbox/pueue) de verify/fix_test solo se probaron con dobles.
  - Los subagentes agotan sus 50 turnos: hay que commitear por tarea.
- **Fuentes de verdad:** `docs/STATE.md`, `docs/pipeline/feature_20261106_080856_ont41_autoevol_heal.md` (§15/§16), `docs/sdd/sdd_ont40_autoevol_thread_graph.md` (§7/§8), `docs/sdd/sdd_ont39_live_plane_hot_swap.md` (§9), `docs/reports/2026-11-05_aep_mcp_live_audit_and_agy_harness.md`.

**Descartar:** logs de pytest, trazas de subagentes, diffs intermedios, ciclos BLOCKED ya resueltos.
