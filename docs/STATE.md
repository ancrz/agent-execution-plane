# AEP — Estado del Proyecto (snapshot para continuidad)

> Fecha: 2026-10-23 · Servidor MCP: **32 tools** · Rama: `main` · Semgrep: 0 findings

Ancla del hilo: si la conversación se compacta o se reinicia, este documento + `docs/COMPACT.md`
+ la memoria `aep-state-and-pendings` permiten retomar sin perder contexto.

## Qué es
Agent Execution Plane (AEP): runtime **FastMCP (stdio)** *agents-for-agents* sobre Ubuntu.
Transmuta primitivas de herramientas ofensivas en capacidades agénticas gobernadas por privilegio.
Transparente al usuario; el entregable es **el artefacto** y que la IA **expanda su trabajo hacia
eficiencia**. Infra: venv `~/.local/share/agent-os/venv`; DB `~/.local/share/agent-os/artifacts.db`
(WAL, sqlite-vec); launcher + `aep-sync.sh` (auto-plug) + hook pre-commit.

## Dos motores compartidos (una sola vara cada uno)
- **`engine/ponder.py`** — CONFIANZA (multidimensional quality/reliability/experience/recency +
  confidence + veto + bandas TRUST/CAUTION/WARNING/REJECT). Añadir/promover y podar/degradar.
- **`engine/matcher.py`** — RELEVANCIA (BM25F multi-señal, RE de skill-swarm; difflib stdlib).
  Buscar/elegir.

## Flujo del agente
`discover(use_case)` (orientar) → **reutilizar** (artifact_catalog) / **sintetizar** (template_select
+ hydrator) / **automatizar** (playbooks) → **ponderar** (promote/demote/prune). Memoria semántica
auto-indexada en write-time (reindex sana); lazo de telemetría cerrado (ejecuciones alimentan la
ponderación); promoción↔degradación bidireccional; GC seguro que protege plantillas base.

## Hecho (arco completo)
sqlite-vec (memoria híbrida) · 5 specs Omarchy (aep_ctl, crash routing, skills hub, man-pages,
headless) · privilegio FULL/DIMINISHED + manifiesto chmod · auto-plug · shell-agnóstico · Pueue ·
bpftrace (sudo -n) · Pico-Kanban (promote/demote/reevaluate + archive/unarchive reversible) ·
Pico-Playbooks (parametrizables vía hydrator RE-as-SDD de Jinja) · descubrimiento
(catalog/reindex/prune) · registry+selector de plantillas · `discover` enrutador (con anclas
léxicas bilingües EN/ES) · ponderación unificada (artefactos+playbooks).

## Pendientes
- Feedback template→artefacto exitoso (`source_template` + agregación ponder + metadato `proven`
  en el selector sin reordenar relevancia); (vec-indexing de playbooks solo si el set crece).
- Revisar los demás pico tools.
- Régimen de continuación: iteración solo diseño; validación mediante llamadas MCP.

## Coordinación / notas honestas
- El **README lo co-mantiene otro agente** (blindaje semántico) concurrentemente; coordinar.
- Las tools nuevas entran MCP-live al **reiniciar la sesión** del cliente (launcher ya registrado).
- WebSockets de Go: **no requeridos** (stdio correcto; push futuro = MCP progress notifications).
- skill-swarm: **consumidor** (no API para contribuir skills); reusamos su matcher y señal de uso.
