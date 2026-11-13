# Feature: Fricciones de dogfooding (ONT-47)

- **Documento**: `feature_20261113_ont47_dogfood_frictions.md`
- **Anterior en la cadena**: [`feature_20261113_ont46_extractor_precision.md`](feature_20261113_ont46_extractor_precision.md)
- **Intent**: cerrar nueve fricciones observadas al usar AEP contra el plano vivo (tokens desperdiciados, booleanos ambiguos, campos null, sobres que rompen su contrato, ruido presentado como acierto, datos de prueba en la base de producción) y dejar registrado el backlog ONT-48 que la misma ronda identificó
- **Pipeline mode**: **Short** (orquestador en modo inline; Archon y Ontos descartados por decisión del usuario, con presupuesto controlado). El plan inline está en el scratchpad `plan_ont47.md`
- **Stage**: Graphos G2 (post-Dokimos, veredicto **VERIFIED**)
- **Worktree**: `/home/ancruz/Documents/workspaces/agent-execution-plane/.claude/worktrees/agent-a0087296b87a19bbe` (rama `worktree-agent-a0087296b87a19bbe`, HEAD `5377589`)
- **Base**: `3541211` (rama `dev`)
- **Commits de Pragma** (10, sin commit de Graphos): `c455b4b`..`5377589` (T1 a T10)
- **Routing de este G2**: Graphos G2 → Orchestrator → **Hermon** (commit en este track; ff a `dev` y push user-gated)
- **Nota sobre el nombre**: el nombre de archivo sigue la convención de ONT-46 (fecha y descriptor, sin HHMMSS) y la indicación del orquestador; si se quiere el formato estricto `feature_YYYYMMDD_HHMMSS.md`, Hermon o el orquestador deciden el renombrado

## 1. Origen: ronda de dogfooding (2026-11-13)

El orquestador ejecutó una ronda de casos pequeños usando las tools de AEP contra el plano vivo (`dev` @ `3541211`, tier 7rwx, backend gen 4). Esto se hizo por mandato explícito del usuario: usar AEP es imperativo y, al usarlo, identificar gaps. Graphos no ejecutó tools de AEP en este registro; sólo documenta lo que la ronda reportó y lo que Dokimos verificó.

| # | Fricción observada (llamada real) | Fix (tarea) | Commit |
|---|-----------------------------------|-------------|--------|
| F1 | `discover(capabilities, terse)` tras un commit solo-docs: `commit_drift: true` junto a `stale: false` | T1: `drift_kind` (`docs_only` / `code` / `unverified`) sólo cuando hay drift | `c455b4b` |
| F2 | `default_primitives(run, socket-monitor, summary)`: 70 sockets completos, 6020 tokens | T2: plegado `by_state` / `by_proto`, `listeners` paginados, `limit` / `cursor` | `4f8048a` |
| F3 | `aep_ctl(network, listeners)` a 7rwx: `pid: null` y `process: null` en todas las filas aunque el socket trae `inode` | T3: `map_socket_inodes` y `parse_proc_net_sockets(resolve_pids=True)` | `dd0bb31` |
| F4 | `aep_ctl(network, probe, summary)`: 25 filas `closed/timeout` aunque `open_ports` está vacío | T4: compacto sólo `open` + `closed_by_reason` | `3158370` |
| F5 | `query_system_docs("how does hot-swap decide stale vs commit_drift")`: chunks de `ss`, `apt`, `git bisect` a distancia 0.30–0.32 con status OK | T5: `best_distance`, `confidence` (HIGH / MEDIUM / LOW), `match_status` | `1893ac6` |
| F6 | `sandbox_run` fallido con `FileNotFoundError` en `stderr`: `error_class: "unknown"` | T6: `normalize_error_class` lee la última línea de excepción de `stderr` | `c084b29` |
| F7 | `kanban_board(board, summary)` y `async_job_dispatch(status, summary)`: `truncated: true` con `cursor: null` | T7: `cursor` y `lane_totals` en el tablero; paginación en pueue status | `5a90232` |
| F8 | `aep_ctl(domain="network", action="schema", summary)`: los 9 dominios completos (1717 tok); el filtro por dominio no reducía | T8: compacto sólo el dominio pedido (`domain`, `schema`, `precondition_defaults`, `degradation_matrix`) | `4185412` |
| F9 | Kanban de producción contaminado: 163 tarjetas SYNTHESIZED "Test Add Alias Task" y 5 BACKLOG de prueba | T9: la fixture de `tests/test_spec_om7_ipc_batch.py` no aislaba `playbook_store`; ahora usa tmp | `51a8eca` |
| (T10) | Regresión transversal de las nueve fricciones | Suite nueva `tests/test_ont47_dogfood_frictions.py` (in-process, DBs en tmp) | `5377589` |

Origen de F9 (detalle): `pb_multi_isolation` pasó de 824 a 836 runs en la base real porque los tests de `test_spec_om7_ipc_batch.py` escribían en `~/.local/share/agent-os/artifacts.db`. Las tarjetas 144, 145, 148, 158 y 159 no tienen origen en el repo (creadas a mano); no se tocan en este track. La limpieza de la base real la hace el orquestador por tool (`kanban_board(archive)`), no los tests.

Observación de la ronda que no es fricción: el probe al gateway era correcto (80 y 443 realmente cerrados, verificado con `/dev/tcp`); sólo era verboso.

## 2. Plan y decisiones de diseño

- **Regla de forma**: el modo `detail` no cambia de forma. Los cambios de forma son sólo en modos compactos (`summary`, `brief`, `terse`) o aditivos (`drift_kind`, `closed_by_reason`, `confidence`, `match_status`, `best_distance`, `lane_totals`).
- **Invariante del sobre**: `truncated = True` implica `cursor` no nulo (T7 lo restablece en board y status).
- **Ningún presupuesto de tokens sube** (`tests/test_token_budgets.py`).
- **Fuera de alcance**: descubrimiento de vecinos de red (`network.neighbors`, G21): decisión de diseño pendiente del usuario. `aep_front.py` y `aep_backend.py` sin cambios. Limpieza de la base kanban real: lo hace el orquestador por tool.
- **Umbrales de relevancia (T5)**: 0.20 y 0.28 como constantes con nombre, justificados en el docstring con lo observado (0.22 acierto real de `socket-monitor`; 0.30–0.32 ruido).

## 3. Cambios de Pragma por tarea

| Tarea | Commit | Archivos principales | Cambio |
|-------|--------|----------------------|--------|
| T1 | `c455b4b` | `server.py` | `drift_kind` sólo cuando `commit_drift` es True; `commit_drift` sigue siendo bool; `summary` explica docs_only |
| T2 | `4f8048a` | `engine/primitives.py`, `server.py` | `socket-monitor` compacto con `count`, `by_state`, `by_proto`, `listeners` paginados (`limit` 25 por defecto, `cursor`); `state` filtra y pagina `sockets`; `detail` sin cambios |
| T3 | `dd0bb31` | `engine/net_telemetry.py`, `server.py`, `scripts/aep-ctl` | `map_socket_inodes` (un pase sobre `/proc/[0-9]*/fd`, ignora `PermissionError`, `FileNotFoundError`, `ProcessLookupError`); `resolve_pids=True` en `listeners` |
| T4 | `3158370` | `engine/net_telemetry.py`, `server.py` | Probe compacto: `ports` sólo con filas `open`; `closed_by_reason` ({timeout, refused, …}); `open_ports`, `open_count`, `closed_count`, `scan_duration_ms` sin cambios |
| T5 | `1893ac6` | `server.py`, `engine/docs_vectorizer.py` (exposición de distancia) | `best_distance`, `confidence`, `match_status: NO_HIGH_CONFIDENCE_MATCH` en LOW; `next_action` específico; resultados no se filtran |
| T6 | `c084b29` | `engine/telemetry.py` | Orden de prioridad: claves explícitas, `error`, última línea de excepción de `stderr`, `unknown`; normalización como antes |
| T7 | `5a90232` | `server.py` | `kanban_board` acepta `cursor`, devuelve `lane_totals`; `async_job_dispatch(status)` pagina con `cursor` cuando `truncated` |
| T8 | `4185412` | `server.py`, `scripts/aep-ctl` | Schema por dominio compacto sin `domains`; `detail` completo; misma regla en CLI |
| T9 | `51a8eca` | `tests/test_spec_om7_ipc_batch.py` (+3 líneas) | Fixture aislada en tmp; `run_count` de `pb_multi_isolation` estable en 840 |
| T10 | `5377589` | `tests/test_ont47_dogfood_frictions.py` (nuevo, 358 líneas), `tests/test_cov_control_plane.py` (cambio de 2 líneas) | Regresión T1–T9. El cambio de `test_cov_control_plane.py` no tiene justificación explícita en este registro; revisar el diff de `5377589` antes de publicar |

Diff acumulado `3541211..5377589`: 8 archivos, +599 / −20 líneas (`server.py` 102 líneas tocadas, `engine/net_telemetry.py` 78, `engine/primitives.py` 59, `engine/telemetry.py` 12, `scripts/aep-ctl` 5, tests 3 archivos).

## 4. Ruta de resolución y blast radius

- **Ruta**: Short. Plan inline del orquestador y un único track de Pragma en un worktree dedicado. Sin paralelismo.
- **Tools de la ronda y de Pragma**: las tools AEP del orquestador contra el plano vivo para la ronda; Pragma usó git, pytest y ruff sobre el worktree.
- **Blast radius de producción**: `server.py` (discover, default_primitives, aep_ctl, query_system_docs, kanban_board, async_job_dispatch, sandbox_run/envelope), `engine/net_telemetry.py`, `engine/primitives.py`, `engine/telemetry.py`, `scripts/aep-ctl`. `engine/docs_vectorizer.py` sólo para exponer distancia. Sin tiers ni API de privilegio nuevos.
- **Blast radius de tests**: tests nuevos (T10) y un ajuste de fixture (T9). Ninguna aserción existente debilitada.
- **Contrato de cambio (sobre MCP)**: aditivo en modo `detail`; cambio de forma sólo en compacto. El sobre `attach_envelope` lo usan todas las tools; T6 es determinista.

## 5. Verificación de Dokimos: VERIFIED

Veredicto: **VERIFIED**, con un fallo de carga documentado.

| Ítem | Resultado |
|------|-----------|
| Suite completa (una corrida) | **1174 passed / 1 failed** en 183.85 s |
| Único fallo | `tests/test_ont40_acceptance.py::test_cold_extraction_under_two_seconds_and_stable_r`: 2.083 s frente a 2.0 s, por carga |
| Repetición aislada del fallo | pasa; el orquestador lo repitió dos veces con el mismo resultado |
| Relación con ONT-47 | ninguno de los 8 archivos tocados pertenece al extractor de hilos (`engine/threads*.py` no está en el diff); margen de extracción en frío ya registrado como backlog de ONT-46 (1.5–1.7 s frente al tope de 2.0 s) |
| `ruff check` y `ruff format --check` | limpios (259 archivos) |
| Budgets (`tests/test_token_budgets.py`) | sin cambios; ninguno sube |
| `GAPS_BASELINE` | 1 (se mantiene); `own_gaps == []` |
| Scope | 8 archivos (ver sección 3); `aep_front` y `aep_backend` intactos |
| Aserciones | ninguna relajada |
| T9 | confirmado: `tests/test_spec_om7_ipc_batch.py` ya no escribe en la base real (`run_count` de `pb_multi_isolation` estable en 840) |

Registro del fallo: no es un LOGIC_ERROR de ONT-47. Dokimos lo clasifica como flakiness por carga del host, con el mismo margen conocido que ONT-46 dejó en backlog. Riesgo residual: el test puede seguir fallando en hosts cargados; se mantiene en backlog de ONT-46, no se maquilla.

## 6. Medidas

Medidas in-process contra `dev`, salvo donde se indica. Los números de la ronda 1 (llamada real en el plano vivo) se citan aparte porque incluyen la envoltura del MCP.

| Fricción | Antes (dev) | Después | Observación |
|----------|-------------|---------|-------------|
| F1 `discover` terse | sin `drift_kind` | +25 tok sólo con drift | la clave aparece únicamente cuando hay drift |
| F2 `socket-monitor` summary | 3783 tok (ronda 1 real: 6020) | 483 tok | paginado con `limit` 25 |
| F2 `socket-monitor` detail | 3903 tok | 3903 tok | forma de `dev` conservada |
| F3 `listeners` a 7rwx | 0 de 47 filas con pid | 33 de 47 filas con pid | 18.5 ms de resolución (presupuesto < 50 ms) |
| F4 `probe` summary | 570 tok (ronda 1 real: 783) | 102 tok | `closed_by_reason` en lugar de filas cerradas |
| F4 `probe` detail | 680 tok | 681 tok | +1 tok; forma de claves conservada (ver nota) |
| F5 `query_system_docs` | distancia 0.2996 presentada como OK | `confidence: LOW`, `match_status: NO_HIGH_CONFIDENCE_MATCH` | `next_action` de refinado |
| F6 `sandbox_run` error_class | `unknown` | `filenotfounderror` | derivado de `stderr` |
| F7 `kanban_board` board | `truncated: true`, `cursor: null` | `cursor: 5` y `lane_totals` | invariante restablecida |
| F8 `schema` network summary | 1120 tok | 444 tok | sólo el dominio |
| F8 `schema` detail | 3296 tok | 3296 tok | forma de `dev` conservada |

Nota sobre F4 detail (+1 tok): la forma de claves se conserva; la diferencia de 1 token se atribuye a valores (assumption: no investigada en este track).

Presupuestos de tokens: ninguno sube. Los cambios de forma compacta bajan tokens; los de detail son neutros.

## 7. Backlog ONT-48 (candidatos de la ronda 2, sin implementar)

Registrados tal como los dejó el informe del orquestador. Ninguno entra en ONT-47.

- G10 `discover(playbook, summary)` = 2990 tok; WF-10 usa `name=`/`args=` y el schema `[target] [ports]`.
- G11 `artifact_execute_in_ram`, `kernel_trace`: `truncated` sin `cursor`; canary 76 elegible sin `next_action` de promote.
- G12 `aep_ctl(audit, usage)`: 975 tok con `bytes: 0, tokens: 0` en todo (telemetría nunca rellenada).
- G13 `service.status ssh` con `LoadState: not-found` → `OK/INFO` (debería ser NOT_FOUND/WARN).
- G14 `diagnose_system_crashes`: timestamps mixtos (fecha humana frente a microsegundos en string).
- G15 `autoevol(report)` sin `sig` y status OK → `candidates: []` sin razón.
- G16 `autoevol(log)`: generación 112 con `git_commit: unknown`, 1086 nodos, 629 gaps persistidos (árbol parcial).
- G17 `playbook_run(list)`: `pb_multi_isolation` con 824 runs desde tests (misma raíz que F9, ya corregida).
- G18 `playbook_run(batch, select_fields)`: proyección duplicada (`output.routes` y `routes`).
- G19 `network.probe` mapa de servicios corto (631 → unknown).
- G20 catálogo de plantillas en español, resto en inglés.
- G21 **Capacidad ausente: descubrimiento de vecinos LAN.** Propuesta `aep_ctl(network, neighbors)`: interfaces UP → prefijos de `routes` → barrido UDP asyncio para poblar ARP (≥ 6rw-) → `/proc/net/arp` + mDNS / WS-Discovery → `probe` opcional por vecino; 5r-x y 4r-- sólo lectura pasiva. **Decisión de diseño pendiente del usuario.**
- G22 `kanban_board(archive, task_id=N)` ignora `task_id`: barrido DRY_RUN de LINTED/REJECTED; BACKLOG y SYNTHESIZED no archivables; `unarchive` sí acepta `task_id`. Asimetría.
- G23 `kanban_board(create)` sin `description` ni `refs`.

Aciertos a conservar (sin cambios): `autoevol(thread)` (578 tok, consumidores y tests impactados), `topos_audit_dag`, `playbook_run(batch)` con `select_fields` (−90 %), `hardware.inventory`, `storage.usage`, `ipc.status`, `backup.lkg_status`, `kernel_trace` (80 k eventos en 251 tok).

## 8. Métricas del pipeline

- **Modo**: Short.
- **Archon ↔ Ontos**: 0 ciclos (no aplica en Short).
- **Pragma ↔ Dokimos**: 0 ciclos de corrección; un veredicto VERIFIED a la primera pasada de Dokimos.
- **Correcciones del orquestador en ruta**: ninguna registrada en el informe.
- **Dokimos approximation ratio**: no aplica (sin trazas Scrutator).
- **Duración total**: no medida en este registro.
- **Repetición de las 8 llamadas en el plano vivo tras el hot-swap**: pendiente (es el siguiente paso de Hermon).

## 9. Estado del pipeline

- Graphos G2 registra VERIFIED. No hay commit de Graphos.
- Documentación actualizada en este G2: este registro, `docs/sdd/sdd_ont47_dogfood_frictions.md`, `README.md` (badge 1174, párrafo ONT-47 y grafo de hitos), `docs/STATE.md`, `docs/COMPACT.md`, `docs/MILESTONES.md` (sección 14).
- Estado: **VERIFIED, publicado en dev**. Hermon hace el ff de `dev` y el push sólo con autorización del usuario.
- Rollup: este documento es el cuarto de la cuenta desde `feature_20261113_004026_mcp_coverage_reinforcement.md` (004026 → 080406 → ont46 → ont47). El próximo documento de la cadena será el quinto y dispara `feature_rollup.md`. **No se regenera en este G2.**

## 10. Evolución del estado

```mermaid
flowchart LR
    A["A: base dev 3541211 (1147 passed, gaps 1)"] --> A1["A.1: plan inline Short y ronda dogfood (F1-F9)"]
    A1 --> A2["A.2: Pragma T1-T9 c455b4b..51a8eca (9 fixes)"]
    A2 --> A3["A.3: Pragma T10 5377589 (suite de regresion)"]
    A3 --> A4["A.4: Dokimos VERIFIED: 1174 passed, 1 fallo de carga conocido"]
    A4 --> A5["A.5: Graphos G2 registra VERIFIED (este documento)"]
    A5 --> A6["A.6: Hermon commit en este track (pendiente)"]
    A6 --> A7["A.7: ff a dev y push (user-gated)"]
    A7 --> A8["A.8: repetir las 8 llamadas en el plano vivo (pendiente)"]
    A8 --> A9["A.9: decision network.neighbors (usuario) y ONT-48"]
```

## 11. Archivos de esta tanda

- Producción (Pragma, 8 archivos): `server.py`, `engine/net_telemetry.py`, `engine/primitives.py`, `engine/telemetry.py`, `scripts/aep-ctl`, y `engine/docs_vectorizer.py` sólo para la distancia.
- Tests (Pragma): `tests/test_ont47_dogfood_frictions.py` (nuevo), `tests/test_cov_control_plane.py`, `tests/test_spec_om7_ipc_batch.py`.
- Documentación de este G2 (sin commit): `docs/pipeline/feature_20261113_ont47_dogfood_frictions.md`, `docs/sdd/sdd_ont47_dogfood_frictions.md`, `docs/reports/2026-11-13_dogfood_frictions_report.md` (estado actualizado), `README.md`, `docs/STATE.md`, `docs/COMPACT.md`, `docs/MILESTONES.md`.
