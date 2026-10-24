# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case)` → reutilizar/sintetizar/automatizar → ponderar (promote/demote/prune).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_archive
   reversible; GC seguro (protect plantillas, cold-aging immunity en single-use exitosos; unlinking binarios;
   playbook_prune inmune a recency); auto-canary en RAM (`LINTED`→`CANARY`); fail-soft; stdio; hot-reload
   Connect/JSON-RPC (Antigravity/Codex; Claude opt-in); 16 capacidades / 30 tools 100% mapeadas.
5. **Estado:** 30 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Fase 1 consolidación (semantic_memory
   unificada en polymorphic artifact_catalog) VERIFICADA; Kanban 95 PROMOTED (0.8875 TRUST).
6. **Pendientes:** Fases 2–7 del Complete Tool Consolidation Roadmap (30 → 16 tools) encoladas.
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
sintetizar/automatizar→ponderar, invariantes (auto-index, telemetría, promoción↔degradación,
kanban_archive reversible, GC seguro con cold-aging immunity, auto-canary en RAM LINTED→CANARY,
fail-soft, stdio, hot-reload Connect-RPC/JSON-RPC Antigravity/Codex, Claude opt-in), 30 tools
(16 capacidades 100% mapeadas), Fase 1 consolidada (artifact_catalog polimórfico), en main
(Semgrep 0), Tarea 95 PROMOTED (0.8875 TRUST), Fases 2–7 encoladas.
Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings.
```
