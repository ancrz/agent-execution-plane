# Context Compaction Guidance — AEP (ONT-39 Live Plane verificado + ONT-39b hardening)

**Preserve**:
- Pipeline: ONT-39 Live Plane hot-swap cerrado. ONT-39b (D-18..D-21) VERIFIED en modo Short, commiteado en dev. Baseline 16 tools, SSoT `0.2.8`.
- Verificación: pytest 198 passed / 6 xfailed (50.8 s), ruff limpio, `aep-sync.sh --check` OK. En vivo: hot-swap Gen1→Gen2 sin reconexión, fail-safe ante SyntaxError (se conservó Gen2), recuperación a Gen3.
- Reconexión: el front de Claude Code requiere `/mcp` (cambió `aep_front.py`). Los backends hot-swap no.
- Sin commit: `aep_front.py`, `aep_backend.py`, `server.py`, `engine/privilege.py`, `tests/test_live_plane_fixes.py`, `docs/sdd/sdd_ont39_*.md`, `.gitignore`. Sin seguimiento: `docs/sdd/sdd_ont40_autoevol_thread_graph.md`, `tests/test_live_plane_integrity.py`.
- Siguiente: ONT-40 `autoevol` read-only (`engine/threads.py` + tool 17); después L3/L4 (D-01..D-07) como primer uso real.
- Política self-healing: nunca revertir el working tree automáticamente; solo restauración por hilo con snapshot previo.
- Política de ramas: auto-commit solo en `autoevol/*`, fast-forward a `dev` solo tras ACCEPT; push gateado por el usuario.

**Drop**:
- Salidas verbosas de pytest, trazas de subagentes, diffs intermedios, planes superados y errores ya resueltos.
