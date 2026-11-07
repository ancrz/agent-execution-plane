# Context Compaction Guidance: AEP (ONT-42c pendiente; auditoría agy cerrada; Short por defecto)
**Preservar:**
- **Modo:** Short por defecto (costos). Full sólo si el usuario lo pide o el blast radius lo exige.
- **Baseline:** `dev` @ `5bee5c1` (origin/dev @ `b605677`, sin push). 17 tools FastMCP, 19 capacidades, suite 659 passed, 0 xfail.
- **Cerrado y VERIFIED:** auditoría agy `1b983f1..b605677` (D-HR-1..6, D-AE-1, O3, D-02) con fixes `d0ff416..5bee5c1`; gaps 94 → 122 por visibilidad ipc/backup, own_gaps 0. Registro: `docs/pipeline/feature_20261107_011128_agy_audit.md`.
- **Decisiones del usuario:** AEP recarga sólo su propia sesión (ancestría estricta), nunca sesiones ajenas; Short por defecto.
- **Hallazgo abierto:** B9 ACCEPT de agy no reproducible (verify no discrimina D-01b); el fix sí pasa en pytest.
- **Pendientes ordenados:** (1) ONT-42c E1 juez no falsificable, (2) E2 specs incrementales, E3 OTP sobre SCC, E4 reconciliación acotada, (3) C1–C7; backlog bajo O-1, O-2, `select_fields`, `lkg_restore covers`.
**Descartar:** trazas de pytest, diffs intermedios, logs de subagentes, ciclos huérfanos ya cosechados y detalles de fixes ya verificados.
