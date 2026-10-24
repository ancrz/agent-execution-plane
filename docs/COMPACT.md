# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case)` → reutilizar/sintetizar/despachar/automatizar → gestionar/ponderar (kanban_board).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_board reversible;
   GC seguro (protect plantillas, cold-aging immunity; unlinking binarios); atajo 1-paso síntesis en RAM;
   auto-canary en RAM (`LINTED`→`CANARY`); fail-soft; stdio; hot-reload Connect/JSON-RPC (Antigravity/Codex; Claude opt-in);
   aislamiento subprocess/FD (`pass_fds=(fd,)`, `timeout=30`, daemons detached con `DEVNULL` stdio y `start_new_session=True`);
   16 capacidades / 16 tools 100% mapeadas.
5. **Estado:** 16 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Fases 1–5 (catalog, kanban, playbook, synthesis, async) VERIFICADAS; Kanban 105 PROMOTED (0.9955 TRUST).
6. **Pendientes:** Fase 6 (crash_forensics: 2 tools -> 1 polymorphic diagnose_system_crashes, 16 -> 15 tools) siguiente objetivo; luego Fase 7 (paridad 1:1, 16 tools).
7. **Decisiones firmes:** daemons jamás por artifact_execute_in_ram; retrocompatibilidad de playbooks; no-recursión estricta en playbook_run.
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
sintetizar/despachar/automatizar→kanban_board→ponderar, invariantes (auto-index, telemetría, promoción↔degradación,
kanban_board reversible, GC seguro con cold-aging immunity, auto-canary en RAM, atajo 1-paso síntesis,
blindaje subprocess/FD pass_fds+DEVNULL daemons, fail-soft, stdio, hot-reload Connect-RPC/JSON-RPC, Claude opt-in),
16 tools (16 capacidades 100% mapeadas), Fases 1-5 consolidadas (catalog, kanban, playbook, synthesis, async),
en main (Semgrep 0), Tarea 105 PROMOTED (0.9955 TRUST), Fase 6 crash_forensics siguiente objetivo.
Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings.
```
