# Context Compaction Guidance — AEP (ONT-40 VERIFIED, Full, G2 registrado)
**Preserve**:
- Pipeline: Full. ONT-40 `autoevol` VERIFIED (Dokimos). Registro: `docs/pipeline/feature_20261106_011249_ont40_autoevol.md` §16.
- Commits `68e0af9..90886d9` en `dev`. ONT-40b commiteado y empujado a origin/dev (D-22, D-23, H1-H3, H5).
- Estado: 17 tools / 19 capacidades. Reportado: pytest 261 passed, 6 xfailed; ruff limpio; `aep-sync --check` OK.
- Milestones: ONT-40 M1-M4 ✅, M5 committed (Hermon). ONT-39 y ONT-39b VERIFIED.
- Decisiones del usuario: 17 tools; AP-1 auto-push solo en ONT-42 (tier ≥ `6rw-`, verify ACCEPT, tests verdes, nunca `--force`, nunca `main`); nunca revertir el working tree automáticamente.
- Riesgo aceptado: 37 % de funciones públicas con cobertura solo transitiva; refinar en ONT-41.
- Discrepancias abiertas: D-23 cita 23 alias, Dokimos 22 correctos; H4 ausente del registro.
- Pendientes de runtime: reconexión `/mcp` (aep_front.py cambió por D-22); `autoevol.json` de Antigravity tras `aep-sync` real.
- Siguientes acciones: (1) reconexión `/mcp` y prueba en vivo de `autoevol`; (2) abrir ONT-41 con L3 (D-01..D-05).

**Drop**:
- Salidas verbosas de pytest, trazas de subagentes, diffs intermedios, planes superados, errores ya resueltos, detalle F1-F16 (resuelto en §14-§15).
