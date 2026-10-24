# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case)` → reutilizar/sintetizar/automatizar (playbook_run) → gestionar/ponderar (kanban_board).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_board reversible;
   GC seguro (protect plantillas, cold-aging immunity en single-use exitosos; unlinking binarios;
   playbook_run prune inmune a recency); auto-canary en RAM (`LINTED`→`CANARY`); fail-soft; stdio; hot-reload
   Connect/JSON-RPC (Antigravity/Codex; Claude opt-in); 16 capacidades / 20 tools 100% mapeadas.
5. **Estado:** 20 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Fases 1–3 (semantic_memory: artifact_catalog,
   task_management: kanban_board, automation: playbook_run) VERIFICADAS; Kanban 101 PROMOTED (0.9979 TRUST).
6. **Pendientes:** Fase 4 (artifact_synthesis: 4 plantillas/síntesis tools -> artifact_lint_and_build, 20 -> 17 tools) siguiente objetivo.
   Fases 4–7 del Complete Tool Consolidation Roadmap (20 → 16 tools) encoladas.
7. **Decisiones firmes:** skill-swarm consumidor; JinjaX descartado; retrocompatibilidad de playbooks; no-recursión estricta en playbook_run.
8. **Fuentes:** `docs/STATE.md`, este archivo, y la memoria `aep-state-and-pendings`.

## DESCARTAR (ruido de proceso)
- Salidas largas de probes/semgrep/compilaciones ya resueltas (basta el veredicto).
- Diffs completos y hashes de commit intermedios (`git log` los tiene).
- Warnings de entorno repetidos (Node CVE, HF token, avisos del embedder).
- Iteraciones de depuración superadas; detalles de llamadas MCP individuales.

## Regla
Conserva **decisiones, invariantes y pendientes con su porqué**; descarta la **evidencia de ejecución**
una vez que el veredicto quedó registrado. Ante la duda, preserva el *porqué*, no el *cómo*.

---

### Foco listo para pegar en `/compact`
```
/compact Conserva estado AEP: premisa agents-for-agents (entregar artefacto, IA expande
eficiencia), 2 motores (ponder.py=confianza, matcher.py=relevancia), flujo discover→reutilizar/
sintetizar/automatizar→kanban_board→ponderar, invariantes (auto-index, telemetría, promoción↔degradación,
kanban_board reversible, GC seguro con cold-aging immunity, auto-canary en RAM LINTED→CANARY,
no-recursión en playbooks, fail-soft, stdio, hot-reload Connect-RPC/JSON-RPC Antigravity/Codex, Claude opt-in),
20 tools (16 capacidades 100% mapeadas), Fases 1-3 consolidadas (artifact_catalog, kanban_board, playbook_run),
en main (Semgrep 0), Tarea 101 PROMOTED (0.9979 TRUST), Fase 4 artifact_synthesis siguiente objetivo.
Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings.
```
