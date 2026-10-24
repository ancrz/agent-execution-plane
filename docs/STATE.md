# AEP — Estado del Proyecto (snapshot para continuidad)

> Fecha: 2026-10-23 · Servidor MCP: **33 tools** (16 capacidades 100% mapeadas) · Rama: `main` · Semgrep: 0 findings

Ancla del hilo: si la conversación se compacta o se reinicia, este documento + `docs/COMPACT.md`
+ la memoria `aep-state-and-pendings` permiten retomar sin perder contexto.

## Qué es
Agent Execution Plane (AEP): runtime **FastMCP (stdio)** *agents-for-agents* sobre Ubuntu.
Transmuta primitivas de herramientas ofensivas en capacidades agénticas gobernadas por privilegio.
Transparente al usuario; el entregable es **el artefacto** y que la IA **expanda su trabajo hacia
eficiencia**. Infra: venv `~/.local/share/agent-os/venv`; DB `~/.local/share/agent-os/artifacts.db`
(WAL, sqlite-vec); launcher + `aep-sync.sh` (auto-plug con hot-reload Connect-RPC para Antigravity y JSON-RPC para Codex; Claude Code desconectado por defecto con `--with-claude`) + hook pre-commit.

## Dos motores compartidos (una sola vara cada uno)
- **`engine/ponder.py`** — CONFIANZA (multidimensional quality/reliability/experience/recency +
  confidence + veto + bandas TRUST/CAUTION/WARNING/REJECT). Añadir/promover y podar/degradar.
- **`engine/matcher.py`** — RELEVANCIA (BM25F multi-señal, RE de skill-swarm; difflib stdlib).
  Buscar/elegir.

## Flujo del agente
`discover(use_case)` (orientar) → **reutilizar** (artifact_catalog) / **sintetizar** (template_select
+ hydrator con contratos tipados) / **automatizar** (playbooks con `async_job_inspect` y salida de pasos completa)
→ **ponderar** (promote/demote/prune). Memoria semántica auto-indexada en write-time (reindex sana); lazo de telemetría
cerrado (ejecuciones alimentan la ponderación); auto-canary en RAM (`artifact_execute_in_ram` avanza de `LINTED` a `CANARY`);
promoción↔degradación bidireccional; GC seguro que protege plantillas base y respeta single-use (inmune a cold-aging);
poda de playbooks (`playbook_prune`).

## Hecho (arco completo)
sqlite-vec (memoria híbrida) · 5 specs Omarchy (aep_ctl, crash routing, skills hub, man-pages,
headless) · privilegio FULL/DIMINISHED + manifiesto chmod · auto-plug (`aep-sync.sh` con hot-reload en vivo Connect-RPC `RefreshMcpServers` para Antigravity y JSON-RPC `config/mcpServer/reload` para OpenAI Codex con 33 tools; Claude Code desconectado por defecto en este host con opt-in `--with-claude` / `AEP_PLUG_CLAUDE=1`) · shell-agnóstico · Pueue ·
bpftrace (sudo -n) · Pico-Kanban (promote/demote/reevaluate + archive/unarchive reversible) ·
Pico-Playbooks (parametrizables vía hydrator RE-as-SDD de Jinja) · descubrimiento
(catalog/reindex/prune) · registry+selector de plantillas · `discover` enrutador (con anclas
léxicas bilingües EN/ES) · ponderación unificada (artefactos+playbooks) · **Feedback template→artefacto
(#1 cerrado: `source_template` + `catalog.template_feedback()` vía `ponder.py` + bloque `proven` en
`template_catalog`/`template_select`/`discover` sin alterar el ranking de `matcher.py`)** ·
**Revisión y endurecimiento de Pico Tools (#4 cerrado: `hydrator` kebab↔snake, `artifact_execute_in_ram`
fallback desde SQLite `binary_blob`, `async_job_*` fail-soft `DEGRADED`)** ·
**Cierre de brecha de omisión en ciclo de poda/reevaluación (`kanban.reevaluate` inmunidad al cold-aging
para artefactos single-use exitosos; `catalog.prune` desvincula binarios en disco; `playbook_prune` como
tool 33 con GC seguro e inmunidad a decaimiento por recency)** ·
**Cierre de 5 brechas de omisión del Grafo de Herramientas Topos (#1 100% de 33 tools mapeadas en 16 capacidades en privilege.py;
#2 plantillas Go parametrizadas con contratos y des-entrecomillado seguro en hydrator/server; #3 async_job_inspect en
_playbook_dispatch; #4 auto-canary en kanban vía artifact_execute_in_ram; #5 output completo de pasos en playbook_run)**.

## Pendientes
- **Todos los pendientes iniciales (#1, #2, #3, #4), el gap de poda y las 5 brechas de omisión del Grafo de Herramientas Topos están CERRADOS y VERIFICADOS por Dokimos.**
- Mejora opcional futura: indexar playbooks en `sqlite-vec` solo si el catálogo de automatizaciones crece significativamente.
- Régimen de mantenimiento: validación mediante llamadas MCP y Semgrep continuo.

## Coordinación / notas honestas
- El **README lo co-mantiene otro agente** (blindaje semántico) concurrentemente; coordinar.
- `aep-sync.sh` auto-pluga Antigravity (`RefreshMcpServers` Connect-RPC) y OpenAI Codex (`config/mcpServer/reload` JSON-RPC con 33 tools), mientras mantiene Claude Code desconectado por defecto en este host (`--with-claude` / `AEP_PLUG_CLAUDE=1` preserva el auto-plug).
- WebSockets de Go: **no requeridos** (stdio correcto; push futuro = MCP progress notifications).
- skill-swarm: **consumidor** (no API para contribuir skills); reusamos su matcher y señal de uso.
