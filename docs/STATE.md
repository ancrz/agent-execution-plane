# AEP — Estado del Proyecto (snapshot para continuidad)

> Fecha: 2026-10-24 · Servidor MCP: **17 tools** (16 capacidades 100% mapeadas) · Rama: `main` · Semgrep: 0 findings

Ancla del hilo: si la conversación se compacta o se reinicia, este documento + `docs/COMPACT.md`
+ la memoria `aep-state-and-pendings` permiten retomar sin perder contexto.

## Qué es
Agent Execution Plane (AEP): runtime **FastMCP (stdio)** *agents-for-agents* sobre Ubuntu.
Transmuta primitivas de herramientas ofensivas en capacidades agénticas gobernadas por privilegio.
Transparente al usuario; el entregable es **el artefacto** y que la IA **expanda su trabajo hacia
eficiencia**. Infra: venv `~/.local/share/agent-os/venv`; DB `~/.local/share/agent-os/artifacts.db`
(WAL, sqlite-vec); launcher + `aep-sync.sh` (auto-plug con hot-reload Connect-RPC para Antigravity y JSON-RPC para Codex con 17 tools; Claude Code desconectado por defecto con `--with-claude`) + hook pre-commit.

## Dos motores compartidos (una sola vara cada uno)
- **`engine/ponder.py`** — CONFIANZA (multidimensional quality/reliability/experience/recency +
  confidence + veto + bandas TRUST/CAUTION/WARNING/REJECT). Añadir/promover y podar/degradar.
- **`engine/matcher.py`** — RELEVANCIA (BM25F multi-señal, RE de skill-swarm; difflib stdlib).
  Buscar/elegir.

## Flujo del agente
`discover(use_case)` (orientar) → **reutilizar/consultar/sanar/podar** (artifact_catalog con `action="browse"|"query"|"reindex"|"prune"`) / **sintetizar** (artifact_lint_and_build con `action="catalog"|"select"|"hydrate"|"build"`, con atajo ergonómico de 1 paso plantilla->binario) / **automatizar** (playbook_run con `action="run"|"create"|"list"|"prune"`, DAGs validados por Topos y salida de pasos completa)
→ **gestionar y ponderar** (kanban_board con `action="board"|"create"|"advance"|"promote"|"demote"|"reevaluate"|"archive"|"unarchive"`). Memoria semántica auto-indexada en write-time (reindex sana); lazo de telemetría
cerrado (ejecuciones alimentan la ponderación); auto-canary en RAM (`artifact_execute_in_ram` avanza de `LINTED` a `CANARY`);
promoción↔degradación bidireccional; GC seguro que protege plantillas base y respeta single-use (inmune a cold-aging);
poda de playbooks (`playbook_run(action="prune")`).

## Hecho (arco completo)
sqlite-vec (memoria híbrida) · 5 specs Omarchy (aep_ctl, crash routing, skills hub, man-pages,
headless) · privilegio FULL/DIMINISHED + manifiesto chmod · auto-plug (`aep-sync.sh` con hot-reload en vivo Connect-RPC `RefreshMcpServers` para Antigravity y JSON-RPC `config/mcpServer/reload` para OpenAI Codex con 17 tools; Claude Code desconectado por defecto en este host con opt-in `--with-claude` / `AEP_PLUG_CLAUDE=1`) · shell-agnóstico · Pueue ·
bpftrace (sudo -n) · Pico-Kanban unificado (tablero, tareas, avance, promoción/degradación, reevaluación, archivado/desarchivado reversible con dry-run) ·
Pico-Playbooks unificado (playbook_run con run/create/list/prune; parametrizables vía hydrator RE-as-SDD de Jinja; no-recursión garantizada) ·
Pico-Síntesis unificada (artifact_lint_and_build con build/catalog/select/hydrate; atajo de 1 paso plantilla->binario en RAM) · descubrimiento
(catalog/reindex/prune) · registry+selector de plantillas · `discover` enrutador (con anclas
léxicas bilingües EN/ES) · ponderación unificada (artefactos+playbooks) · **Feedback template→artefacto
(#1 cerrado: `source_template` + `catalog.template_feedback()` vía `ponder.py` + bloque `proven` en
`artifact_lint_and_build(action="catalog"/"select")`/`discover` sin alterar el ranking de `matcher.py`)** ·
**Revisión y endurecimiento de Pico Tools (#4 cerrado: `hydrator` kebab↔snake, `artifact_execute_in_ram`
fallback desde SQLite `binary_blob`, `async_job_*` fail-soft `DEGRADED`)** ·
**Cierre de brecha de omisión en ciclo de poda/reevaluación (`kanban.reevaluate` inmunidad al cold-aging
para artefactos single-use exitosos; `catalog.prune` desvincula binarios en disco; poda de playbooks
con GC seguro e inmunidad a decaimiento por recency)** ·
**Cierre de 5 brechas de omisión del Grafo de Herramientas Topos (#1 100% de tools mapeadas en 16 capacidades en privilege.py;
#2 plantillas Go parametrizadas con contratos y des-entrecomillado seguro en hydrator/server; #3 async_job_inspect en
_playbook_dispatch; #4 auto-canary en kanban vía artifact_execute_in_ram; #5 output completo de pasos en playbook_run)**.

- **Consolidación de herramientas — Fase 1 `semantic_memory` CERRADA y VERIFICADA (33 → 30 tools MCP):** Fusión de la capacidad `semantic_memory` unificando `artifact_query`, `artifact_catalog`, `artifact_reindex` y `artifact_prune` en el endpoint polimórfico `artifact_catalog(action=...)`. Retrocompatibilidad en `_playbook_dispatch`, validación estricta ONT-01 (`PARAM_ERROR`), Semgrep 0 hallazgos, Tarea Kanban 95 PROMOTED con 0.8875 TRUST.
- **Consolidación de herramientas — Fase 2 `task_management` CERRADA y VERIFICADA (30 → 23 tools MCP):** Fusión de la capacidad `task_management` unificando los 8 endpoints `kanban_*` (`kanban_board`, `kanban_task_create`, `kanban_advance`, `kanban_promote`, `kanban_demote`, `kanban_reevaluate`, `kanban_archive`, `kanban_unarchive`) en un único endpoint polimórfico `kanban_board(action=...)`. Validación estricta de parámetros ONT-02 (`PARAM_ERROR`), validación de acción (`INVALID_ACTION`), enriquecimiento de anclas léxicas bilingües en `_CAP_KEYWORDS["task_management"]`, sincronización de manifiesto en `engine/privilege.py`, modernización de hints en `engine/kanban.py`, 0 hallazgos en Semgrep (1,198 reglas), 23 esquemas JSON confirmados por `aep-sync.sh --check`, y Tarea Kanban 97 PROMOTED con 0.925 TRUST.
- **Consolidación de herramientas — Fase 3 `automation` CERRADA y VERIFICADA (23 → 20 tools MCP):** Fusión de la capacidad `automation` unificando los 4 endpoints `playbook_*` (`playbook_create`, `playbook_run`, `playbook_list`, `playbook_prune`) en un único endpoint polimórfico `playbook_run(action=...)`. Validación estricta de parámetros ONT-03 (`PARAM_ERROR`), validación de acción (`INVALID_ACTION`), preservación estricta de la invariante de no-recursión (`LINT_ERROR` en creación ante intentos de llamada a `playbook_run` dentro de playbooks), modernización de hints en `server.py:discover()` y `engine/playbook.py:prune()`, sincronización de manifiesto en `engine/privilege.py` con anclas léxicas bilingües, 0 hallazgos en Semgrep (1,198 reglas), 20 esquemas JSON confirmados por `aep-sync.sh --check`, y Tarea Kanban 101 PROMOTED con 0.9979 TRUST.
- **Consolidación de herramientas — Fase 4 `artifact_synthesis` CERRADA y VERIFICADA (20 → 17 tools MCP):** Fusión de la capacidad `artifact_synthesis` unificando los 4 endpoints `template_catalog`, `template_select`, `artifact_hydrate` y `artifact_lint_and_build` en un único endpoint polimórfico `artifact_lint_and_build(action="build"|"catalog"|"select"|"hydrate", ...)`. Incorporación del atajo ergonómico de 1 paso plantilla->binario (auto-hidratación en RAM al compilar sin llamadas intermedias), validación estricta de parámetros ONT-04 (`PARAM_ERROR`, `HYDRATE_ERROR`, `INVALID_ACTION`), sincronización de manifiesto y anclas léxicas bilingües en `engine/privilege.py`, 0 hallazgos en Semgrep (1,198 reglas), 17 esquemas JSON confirmados por `aep-sync.sh --check`, y Tarea Kanban 102 PROMOTED con 0.9964 TRUST.

## Pendientes
- **Fase 5 del Complete Tool Consolidation Roadmap (`async_dispatch`: 2 herramientas `async_job_dispatch`, `async_job_inspect` -> 1 polymorphic `async_job_dispatch` tool, reduciendo 17 → 16 tools) es el siguiente objetivo inmediato.**
- Fases 5 a 7 del Complete Tool Consolidation Roadmap (17 → 16 tools) encoladas en backlog arquitectónico.
- Mejora opcional futura: indexar playbooks en `sqlite-vec` solo si el catálogo de automatizaciones crece significativamente.
- Régimen de mantenimiento: validación mediante llamadas MCP y Semgrep continuo.

## Coordinación / notas honestas
- El **README lo co-mantiene otro agente** (blindaje semántico) concurrentemente; coordinar.
- `aep-sync.sh` auto-pluga Antigravity (`RefreshMcpServers` Connect-RPC) y OpenAI Codex (`config/mcpServer/reload` JSON-RPC con 17 tools), mientras mantiene Claude Code desconectado por defecto en este host (`--with-claude` / `AEP_PLUG_CLAUDE=1` preserva el auto-plug).
- WebSockets de Go: **no requeridos** (stdio correcto; push futuro = MCP progress notifications).
