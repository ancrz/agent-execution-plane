# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case)` → reutilizar/sintetizar (artifact_lint_and_build)/automatizar (playbook_run) → gestionar/ponderar (kanban_board).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_board reversible;
   GC seguro (protect plantillas, cold-aging immunity en single-use exitosos; unlinking binarios;
   playbook_run prune inmune a recency); atajo 1-paso síntesis en RAM; auto-canary en RAM (`LINTED`→`CANARY`);
   fail-soft; stdio; hot-reload Connect/JSON-RPC (Antigravity/Codex; Claude opt-in); 16 capacidades / 17 tools 100% mapeadas.
5. **Estado:** 17 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Fases 1–4 (semantic_memory: artifact_catalog,
   task_management: kanban_board, automation: playbook_run, artifact_synthesis: artifact_lint_and_build) VERIFICADAS; Kanban 102 PROMOTED (0.9964 TRUST).
6. **Pendientes:** Fase 5 (async_dispatch: 2 tools async_job_* -> polymorphic async_job_dispatch, 17 -> 16 tools) siguiente objetivo.
   Fases 5–7 del Complete Tool Consolidation Roadmap (17 → 16 tools) encoladas.
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
atajo 1-paso síntesis, no-recursión en playbooks, fail-soft, stdio, hot-reload Connect-RPC/JSON-RPC, Claude opt-in),
17 tools (16 capacidades 100% mapeadas), Fases 1-4 consolidadas (catalog, kanban, playbook, synthesis),
en main (Semgrep 0), Tarea 102 PROMOTED (0.9964 TRUST), Fase 5 async_dispatch siguiente objetivo.
Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings.
```
