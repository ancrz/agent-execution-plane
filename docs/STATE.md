# AEP — Estado del Proyecto (snapshot para continuidad)

> Fecha: 2026-10-24 · Servidor MCP: **15 tools** (15 capacidades 100% mapeadas) · Rama: `main` · Semgrep: 0 findings

Ancla del hilo: si la conversación se compacta o se reinicia, este documento + `docs/COMPACT.md`
+ la memoria `aep-state-and-pendings` permiten retomar sin perder contexto.

## Qué es
Agent Execution Plane (AEP): runtime **FastMCP (stdio)** *agents-for-agents* sobre Ubuntu.
Transmuta primitivas de herramientas ofensivas en capacidades agénticas gobernadas por privilegio.
Transparente al usuario; el entregable es **el artefacto** y que la IA **expanda su trabajo hacia
eficiencia**. Infra: venv `~/.local/share/agent-os/venv`; DB `~/.local/share/agent-os/artifacts.db`
(WAL, sqlite-vec); launcher + `aep-sync.sh` (auto-plug con hot-reload Connect-RPC para Antigravity y JSON-RPC para Codex con 15 tools; Claude Code desconectado por defecto con `--with-claude`) + hook pre-commit.

## Dos motores compartidos (una sola vara cada uno)
- **`engine/ponder.py`** — CONFIANZA (multidimensional quality/reliability/experience/recency +
  confidence + veto + bandas TRUST/CAUTION/WARNING/REJECT). Añadir/promover y podar/degradar.
- **`engine/matcher.py`** — RELEVANCIA (BM25F multi-señal, RE de skill-swarm; difflib stdlib).
  Buscar/elegir.

## Flujo del agente
`discover(use_case)` (orientar) → **reutilizar/consultar/sanar/podar** (artifact_catalog con `action="browse"|"query"|"reindex"|"prune"`) / **sintetizar** (artifact_lint_and_build con `action="catalog"|"select"|"hydrate"|"build"`, con atajo ergonómico de 1 paso plantilla->binario) / **despachar asíncrono** (async_job_dispatch con `action="dispatch"|"inspect"|"status"|"log"`) / **inspección forense** (diagnose_system_crashes con `action="diagnose"|"alerts"` y blindaje de subproceso DEVNULL+close_fds+timeout) / **inspección forense** (diagnose_system_crashes con `action="diagnose"|"alerts"` y blindaje de subproceso DEVNULL+close_fds+timeout) / **automatizar** (playbook_run con `action="run"|"create"|"list"|"prune"`, DAGs validados por Topos y salida de pasos completa)
→ **gestionar y ponderar** (kanban_board con `action="board"|"create"|"advance"|"promote"|"demote"|"reevaluate"|"archive"|"unarchive"`). Memoria semántica auto-indexada en write-time (reindex sana); lazo de telemetría
cerrado (ejecuciones alimentan la ponderación); auto-canary en RAM (`artifact_execute_in_ram` avanza de `LINTED` a `CANARY`);
promoción↔degradación bidireccional; GC seguro que protege plantillas base y respeta single-use (inmune a cold-aging);
poda de playbooks (`playbook_run(action="prune")`).

## Invariante de Aislamiento de Subprocesos y Descriptores
- **Prohibido lanzar daemons en RAM:** Jamás ejecutar daemons de segundo plano (`pueued`, servicios) a través de `artifact_execute_in_ram`.
- **Aislamiento estricto de FDs:** `artifact_execute_in_ram` utiliza exclusivamente `pass_fds=(fd,)`, `timeout=30` con fail-soft `TIMEOUT`, y limpieza determinista en bloque `finally`.
- **Daemons desacoplados:** Los daemons de fondo deben auto-iniciarse con stdio en `DEVNULL`, `close_fds=True` y `start_new_session=True` para prevenir deadlocks por herencia de pipes de comunicación MCP.
- **Aislamiento en consultas de diagnóstico:** `_safe_run` en `diagnose_system_crashes` aísla stdin con `DEVNULL`, fuerza `close_fds=True`, aplica `timeout=15` y captura `subprocess.TimeoutExpired` junto a `FileNotFoundError`.
- **Aislamiento en consultas de diagnóstico:** `_safe_run` en `diagnose_system_crashes` aísla stdin con `DEVNULL`, fuerza `close_fds=True`, aplica `timeout=15` y captura `subprocess.TimeoutExpired` junto a `FileNotFoundError`.

## Hecho (arco completo)
sqlite-vec (memoria híbrida) · 5 specs Omarchy (aep_ctl, crash routing, skills hub, man-pages,
headless) · privilegio FULL/DIMINISHED + manifiesto chmod · auto-plug (`aep-sync.sh` con hot-reload en vivo Connect-RPC `RefreshMcpServers` para Antigravity y JSON-RPC `config/mcpServer/reload` para OpenAI Codex con 16 tools; poda de esquemas huérfanos; Claude Code desconectado por defecto con opt-in `--with-claude`) · shell-agnóstico · Pueue ·
bpftrace (sudo -n) · Pico-Kanban unificado (tablero, tareas, avance, promoción/degradación, reevaluación, archivado/desarchivado reversible con dry-run) ·
Pico-Playbooks unificado (playbook_run con run/create/list/prune; parametrizables vía hydrator RE-as-SDD de Jinja; no-recursión garantizada) ·
Pico-Síntesis unificada (artifact_lint_and_build con build/catalog/select/hydrate; atajo de 1 paso plantilla->binario en RAM) ·
Pico-Async unificado (async_job_dispatch con dispatch/inspect/status/log; auto-start desacoplado de pueued; fail-soft DEGRADED) ·
descubrimiento (catalog/reindex/prune) · registry+selector de plantillas · `discover` enrutador (con anclas
léxicas bilingües EN/ES) · ponderación unificada (artefactos+playbooks) · **Feedback template→artefacto
(#1 cerrado)** · **Endurecimiento de Pico Tools (#4 cerrado)** · **Cierre de brecha en ciclo de poda/reevaluación** ·
**Cierre de 5 brechas de omisión del Grafo de Herramientas Topos**.

- **Consolidación de herramientas — Fase 1 `semantic_memory` CERRADA y VERIFICADA (33 → 30 tools MCP):** Fusión de la capacidad `semantic_memory` unificando `artifact_query`, `artifact_catalog`, `artifact_reindex` y `artifact_prune` en el endpoint polimórfico `artifact_catalog(action=...)`. Retrocompatibilidad en `_playbook_dispatch`, validación estricta ONT-01 (`PARAM_ERROR`), Semgrep 0 hallazgos, Tarea Kanban 95 PROMOTED con 0.8875 TRUST.
- **Consolidación de herramientas — Fase 2 `task_management` CERRADA y VERIFICADA (30 → 23 tools MCP):** Fusión de la capacidad `task_management` unificando los 8 endpoints `kanban_*` en un único endpoint polimórfico `kanban_board(action=...)`. Validación estricta ONT-02 (`PARAM_ERROR`), validación de acción (`INVALID_ACTION`), anclas léxicas bilingües, 0 hallazgos en Semgrep (1,198 reglas), 23 esquemas JSON confirmados por `aep-sync.sh --check`, y Tarea Kanban 97 PROMOTED con 0.925 TRUST.
- **Consolidación de herramientas — Fase 3 `automation` CERRADA y VERIFICADA (23 → 20 tools MCP):** Fusión de la capacidad `automation` unificando los 4 endpoints `playbook_*` en un único endpoint polimórfico `playbook_run(action=...)`. Validación estricta ONT-03 (`PARAM_ERROR`, `INVALID_ACTION`), invariante de no-recursión (`LINT_ERROR`), hints modernizados, sincronización de manifiesto en `engine/privilege.py`, 0 hallazgos en Semgrep, 20 esquemas confirmados, y Tarea Kanban 101 PROMOTED con 0.9979 TRUST.
- **Consolidación de herramientas — Fase 4 `artifact_synthesis` CERRADA y VERIFICADA (20 → 17 tools MCP):** Fusión de la capacidad `artifact_synthesis` unificando los 4 endpoints de síntesis en `artifact_lint_and_build(action=...)`. Atajo de 1 paso plantilla->binario en RAM, validación estricta ONT-04 (`PARAM_ERROR`, `HYDRATE_ERROR`, `INVALID_ACTION`), manifiesto sincronizado, 0 hallazgos en Semgrep, 17 esquemas confirmados, y Tarea Kanban 102 PROMOTED con 0.9964 TRUST.
- **Consolidación de herramientas — Fase 5 `async_dispatch` CERRADA y VERIFICADA (17 → 16 tools MCP) + Blindaje Subprocess/FD:** Fusión de `async_job_dispatch` y `async_job_inspect` en el endpoint polimórfico `async_job_dispatch(action="dispatch"|"inspect"|"status"|"log", ...)`. Retrocompatibilidad en `_playbook_dispatch()` mediante lambda alias. Cierre de 3 brechas de omisión críticas tras incidente de freeze por pipes heredadas de `pueued`: Gap A (`pass_fds=(fd,)`, `timeout=30`, `finally: os.close(fd)` en `artifact_execute_in_ram`), Gap B (`_ensure_pueue_daemon` con stdio `DEVNULL`, `close_fds=True`, `start_new_session=True` y `timeout=10`), Gap C (`scripts/aep-sync.sh` con poda automática de esquemas huérfanos y recarga síncrona). Semgrep 0 hallazgos, 16 esquemas JSON confirmados, y Tarea Kanban 105 PROMOTED con 0.9955 TRUST.
- **Consolidación de herramientas — Fase 6 `crash_forensics` CERRADA y VERIFICADA (16 → 15 tools MCP) + Blindaje Subproceso/Timeout:** Fusión de `diagnose_system_crashes` y `check_crash_alerts` en el endpoint polimórfico `diagnose_system_crashes(action="diagnose"|"alerts", limit=5, resolve_after_report=False)` con alias `check`. Retrocompatibilidad en `_playbook_dispatch()` mediante lambda forwarder. Endurecimiento de `_safe_run` con `stdin=DEVNULL`, `close_fds=True` y `timeout=15` atrapando `TimeoutExpired` y `FileNotFoundError`. Poda automática de `check_crash_alerts.json` en `aep-sync.sh`. Semgrep 0 hallazgos (1,198 reglas), exactamente 15 esquemas JSON confirmados, y Tarea Kanban 106 PROMOTED con 0.8208 TRUST.
- **Consolidación de herramientas — Fase 6 `crash_forensics` CERRADA y VERIFICADA (16 → 15 tools MCP) + Blindaje Subproceso/Timeout:** Fusión de `diagnose_system_crashes` y `check_crash_alerts` en el endpoint polimórfico `diagnose_system_crashes(action="diagnose"|"alerts", limit=5, resolve_after_report=False)` con alias `check`. Retrocompatibilidad en `_playbook_dispatch()` mediante lambda forwarder. Endurecimiento de `_safe_run` con `stdin=DEVNULL`, `close_fds=True` y `timeout=15` atrapando `TimeoutExpired` y `FileNotFoundError`. Poda automática de `check_crash_alerts.json` en `aep-sync.sh`. Semgrep 0 hallazgos (1,198 reglas), exactamente 15 esquemas JSON confirmados, y Tarea Kanban 106 PROMOTED con 0.8208 TRUST.

## Pendientes
- **Fases 1 a 6 del Complete Tool Consolidation Roadmap (33 → 15 tools MCP) CERRADAS y VERIFICADAS por Dokimos.**
- **Fase 7 (`orientation` & `process_introspection`): Fusión de `discover` + `aep_capabilities` en `discover(action="discover"|"capabilities")` y creación de un endpoint dedicado para `process_introspection` (`proc_fd_inspect`), alcanzando paridad perfecta 1:1 (16 tools / 16 capacidades) es el siguiente objetivo inmediato.**
- Mejora opcional futura: indexar playbooks en `sqlite-vec` solo si el catálogo de automatizaciones crece significativamente.
- Régimen de mantenimiento: validación mediante llamadas MCP y Semgrep continuo.

## Coordinación / notas honestas
- El **README lo co-mantiene otro agente** (blindaje semántico) concurrentemente; coordinar.
- `aep-sync.sh` auto-pluga Antigravity (`RefreshMcpServers` Connect-RPC) y OpenAI Codex (`config/mcpServer/reload` JSON-RPC con 15 tools), mientras mantiene Claude Code desconectado por defecto en este host (`--with-claude` / `AEP_PLUG_CLAUDE=1` preserva el auto-plug).
- WebSockets de Go: **no requeridos** (stdio correcto; push futuro = MCP progress notifications).
