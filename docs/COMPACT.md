# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo. En Claude Code se usa
pegando el foco en `/compact <instrucciones>` (ver el bloque listo abajo). El objetivo: conservar
el ESTADO y las DECISIONES; descartar el ruido de proceso.

## PRESERVAR (imprescindible)
1. **Identidad del proyecto:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu;
   premisa = entregar el artefacto al usuario y que la IA expanda su trabajo hacia eficiencia;
   transparente al usuario.
2. **Dos motores compartidos:** `engine/ponder.py` (CONFIANZA, multidimensional+veto+bandas) y
   `engine/matcher.py` (RELEVANCIA, BM25F multi-señal RE de skill-swarm).
3. **Flujo del agente:** `discover(use_case)` → reutilizar(artifact_catalog)/sintetizar
   (template_select+hydrator)/automatizar(playbooks) → ponderar (promote/demote/prune).
4. **Invariantes:** memoria semántica auto-indexada (reindex sana); lazo de telemetría cerrado;
   promoción↔degradación bidireccional; archivado soft reversible del board (`kanban_archive`/`unarchive`);
   GC seguro protege plantillas base y respeta single-use; fail-soft en todo; stdio (sin WebSockets
   de Go); privilegio FULL/DIMINISHED + manifiesto chmod + keywords bilingües EN/ES; auto-plug con
   hot-reload Connect-RPC `RefreshMcpServers` (cero reinicio de sesión).
5. **Estado:** 32 tools MCP; rama `main`; Semgrep 0; venv + DB en `~/.local/share/agent-os/`;
   auto-plug (`aep-sync.sh`) + hook pre-commit; hot-reload en vivo para Antigravity.
6. **Pendientes:** Todos los pendings (#1 feedback template→artefacto, #2 kanban archive, #3 discover
   bilingüe, #4 hardening pico tools) CERRADOS y verificados (Semgrep 0, MCP tests OK).
7. **Decisiones firmes y por qué:** skill-swarm es consumidor (no se le aporta); JinjaX rechazado
   (RE-as-SDD: patrones Jinja —StrictUndefined/defaults/tipos/no-eval— extraídos a `hydrator.py`).
8. **Fuentes de verdad:** `docs/STATE.md`, este archivo, y la memoria `aep-state-and-pendings`.

## DESCARTAR (ruido de proceso)
- Salidas largas de probes/semgrep/compilaciones ya resueltas (basta el veredicto).
- Diffs completos y hashes de commit intermedios (el `git log` los tiene).
- Warnings de entorno repetidos (Node.js CVE, HF token, avisos del embedder).
- Iteraciones de depuración ya superadas; detalles de llamadas MCP individuales.

## Regla
Conserva **decisiones, invariantes y pendientes con su porqué**; descarta la **evidencia de
ejecución** una vez que el veredicto quedó registrado. Ante la duda, preserva el *porqué*, no el *cómo*.

---

### Foco listo para pegar en `/compact`
```
/compact Conserva el estado de AEP: premisa agents-for-agents (entregar artefacto, IA expande
eficiencia), los 2 motores compartidos (ponder.py=confianza, matcher.py=relevancia), el flujo
discover→reutilizar/sintetizar/automatizar→ponderar, los invariantes (auto-index, lazo de
telemetría, promoción↔degradación, archivado reversible, GC seguro, fail-soft, stdio, hot-reload
Connect-RPC RefreshMcpServers), 32 tools en main (Semgrep 0), todos los pendings (#1,#2,#3,#4)
cerrados. Fuentes: docs/STATE.md, docs/COMPACT.md, memoria aep-state-and-pendings. Descarta
salidas largas de probes/semgrep/builds, diffs y warnings repetidos.
```
