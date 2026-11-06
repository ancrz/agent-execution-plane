# Context Compaction Guidance — AEP (ONT-41 EN PLAN Full, G1 tejido)
**Preserve**:
- Pipeline: Full. ONT-41 `autoevol` spec/verify/heal + LKG: EN PLAN, Ontos BLOCKED ciclo 1/3 (B1-B5), Ontos APPROVED ciclo 2 (condiciones C1, TA5 incorporadas en la §16), en implementación (Pragma). Doc: `docs/pipeline/feature_20261106_080856_ont41_autoevol_heal.md` (encadena a `feature_20261106_011249_ont40_autoevol.md`).
- Baseline: `dev` = `origin/dev` = `e3f7725`. ONT-40 VERIFIED; ONT-40b commiteado `a61b3f1`. ONT-41 sin código ni commit.
- Decisiones del usuario: DQ-1..DQ-9 del plan (LKG sha256, cycle_id, tiers, REJECT NO_DIRECT_COVERAGE); AP-1 auto-push solo en ONT-42; nunca `--force`, nunca `main`; no arreglar D-01..D-05 (xfail strict).
- Riesgos abiertos: viabilidad sandbox (T0 spike), front SPOF no hot-swapeable, SDD de ONT-41 no entregada.
- Siguientes 3 acciones: (1) Ontos audita el plan (BLOCKED -> G1 -> Archon; APPROVED -> Pragma); (2) T0 spike con `sandbox_run`; (3) reconexión `/mcp` y dogfooding de `autoevol` (TD1).
**Drop**:
- Salidas verbosas de pytest, trazas de subagentes, diffs intermedios, planes superados, detalle F1-F16 de ONT-40 (resuelto), errores ya resueltos.
