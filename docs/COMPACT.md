# Context Compaction Guidance — AEP (ONT-40 EN PLAN, Full, G1 completo)
**Preserve**:
- Pipeline: Full. ONT-40 `autoevol` EN PLAN. Plan tejido por Graphos G1: `docs/pipeline/feature_20261106_011249_ont40_autoevol.md` (T0..T17). Siguiente: auditoría de Ontos (O-1..O-8 abiertas).
- Baseline: HEAD `3515a22` en `dev` (ONT-39b VERIFIED: pytest 198 passed / 6 xfailed). 16 tools; ONT-40 propone 17 (decisión del usuario). Capacidades: 19.
- Decisiones: DQ-1..DQ-5 (SDD §7). AP-1: auto-push autorizado por el usuario solo en ONT-42, con condiciones (tier ≥ `6rw-`, verify ACCEPT, tests verdes, nunca `--force`, nunca `main`).
- SDD `docs/sdd/sdd_ont40_autoevol_thread_graph.md`: rastreado desde `6a0601d`; §7 y §8 SIN commit (Hermon, antes de Fase B).
- Riesgos de Ontos: T6 requiere T7 (condensación SCC); premisa «sin ejecutar código» vs probes DQ-2; tests de T14 sin enumerar; `threads → privilege` inferido.
- Fase B bajo `.aep_swap_fence` (T13 edita `server.py` con hot-swap activo).
- Política self-healing: nunca revertir el working tree automáticamente; restauración solo por hilo con snapshot previo.
- Siguiente tres acciones: (1) Orquestador invoca Ontos con el plan y O-1..O-8; (2) si APPROVED, T0 calibración en worktree `b2afeb2`; (3) Hermon confirma commit de §7/§8 del SDD.

**Drop**:
- Salidas verbosas de pytest, trazas de subagentes, diffs intermedios, planes superados, errores ya resueltos, contenido de los rollups históricos.
</content>
