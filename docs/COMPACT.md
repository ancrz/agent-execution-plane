# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case)` → reutilizar/sintetizar/automatizar → gestionar/ponderar (kanban_board).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_board reversible;
   GC seguro (protect plantillas, cold-aging immunity en single-use exitosos; unlinking binarios;
   playbook_prune inmune a recency); auto-canary en RAM (`LINTED`→`CANARY`); fail-soft; stdio; hot-reload
   Connect/JSON-RPC (Antigravity/Codex; Claude opt-in); 16 capacidades / 23 tools 100% mapeadas.
5. **Estado:** 23 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Fase 1 (semantic_memory: artifact_catalog)
   y Fase 2 (task_management: kanban_board polimórfico) VERIFICADAS; Kanban 97 PROMOTED (0.925 TRUST).
6. **Pendientes:** Fase 3 (automation: 4 playbook_* tools -> playbook_run, 23 -> 20 tools) siguiente objetivo.
   Fases 3–7 del Complete Tool Consolidation Roadmap (23 → 16 tools) encoladas.
7. **Decisiones firmes:** skill-swarm consumidor; JinjaX descartado; retrocompatibilidad de playbooks vía alias lambda.
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
fail-soft, stdio, hot-reload Connect-RPC/JSON-RPC Antigravity/Codex, Claude opt-in), 23 tools
(16 capacidades 100% mapeadas), Fases 1-2 consolidadas (artifact_catalog y kanban_board polimórficos),
en main (Semgrep 0), Tarea 97 PROMOTED (0.925 TRUST), Fase 3 automation siguiente objetivo.
Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings.
```
