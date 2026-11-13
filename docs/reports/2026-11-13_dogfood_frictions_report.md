# Informe de dogfooding AEP — 2026-11-13 (ONT-47 en pausa, ONT-48 candidatos)

Autor: orquestador (Claude Fable 5.1) usando las tools de AEP contra el plano vivo (`dev` @ `3541211`, tier 7rwx,
backend gen 4). Regla del usuario: usar AEP es imperativo y, al usarlo, identificar gaps.

## Estado del pipeline al pausar

Estado: VERIFIED, publicado en dev. Dokimos: 1174 passed / 1 failed en 183,85 s; el único fallo es `test_cold_extraction_under_two_seconds_and_stable_r` por carga (2,083 s frente a 2,0 s), pasa aislado. ruff check y format limpios (259 archivos); GAPS_BASELINE 1; budgets sin cambios. Registro de Graphos: `docs/pipeline/feature_20261113_ont47_dogfood_frictions.md`.

Historial previo a la verificación (la sección original de la pausa se conserva debajo):

- Pragma terminó ONT-47 (T1–T10) en el worktree
  `.claude/worktrees/agent-a0087296b87a19bbe` (rama `worktree-agent-a0087296b87a19bbe`), base `3541211`,
  10 commits `c455b4b..5377589`, árbol limpio, 8 archivos (server.py, engine/net_telemetry.py,
  engine/primitives.py, engine/telemetry.py, scripts/aep-ctl, tests/test_cov_control_plane.py,
  tests/test_spec_om7_ipc_batch.py, tests/test_ont47_dogfood_frictions.py nuevo con 28 tests).
- Dokimos fue lanzado y DETENIDO por pausa del usuario antes de emitir veredicto. Nada integrado en `dev`.
- Plan: scratchpad `plan_ont47.md`; gaps ronda 2: scratchpad `gaps_dogfood_round2.md` (copiados abajo).
- Kanban real: tarjetas 495 (ONT-47) y 496 (ONT-48 candidatos) creadas por tool.

## Ronda 1 → ONT-47 (implementado, pendiente de verificación)

| # | Fricción observada (llamada real) | Fix de Pragma |
|---|---|---|
| F1 | `discover(capabilities, terse)`: `commit_drift: true` junto a `stale: false` tras commit solo-docs | `drift_kind` docs_only/code/unverified; summary lo explica (c455b4b) |
| F2 | `default_primitives(run, socket-monitor, summary)`: 70 sockets, 6020 tok | plegado `by_state`/`by_proto`, `listeners` paginados, `limit`/`cursor` nuevos; ~650 tok (4f8048a) |
| F3 | `network.listeners` a 7rwx: `pid`/`process` null con inode disponible | `map_socket_inodes`, `parse_proc_net_sockets(resolve_pids=True)`; 18–21 ms en el host (dd0bb31) |
| F4 | `network.probe` summary: 25 filas closed/timeout, 783 tok | compactos solo `open` + `closed_by_reason`; ~114 tok (3158370) |
| F5 | `query_system_docs` devuelve ruido (distancia 0.30) como OK | `best_distance`, `confidence` HIGH≤0.20/MEDIUM≤0.28/LOW, `match_status` (1893ac6) |
| F6 | `sandbox_run` con FileNotFoundError en stderr → `error_class: unknown` | `normalize_error_class` lee la última línea de excepción del stderr (c084b29) |
| F7 | `kanban_board(board)`, `async_job_dispatch(status)`: `truncated: true, cursor: null` | `cursor` + `lane_totals`; paginación en pueue (5a90232) |
| F8 | `aep_ctl(domain=network, action=schema)`: 9 dominios + schema, 1717 tok | compacto solo el dominio (4185412) |
| F9 | Kanban real contaminado por tests | culpable: fixture de `tests/test_spec_om7_ipc_batch.py` no aislaba `playbook_store` (824→836 runs de `pb_multi_isolation`); corregida (51a8eca). Tarjetas 144/145/148/158/159 sin origen en el repo (manuales) |

Verificado por el orquestador: el probe al gateway era correcto (80/443 realmente cerrados); solo era verboso.

## Ronda 2 → ONT-48 candidatos (sin implementar)

- G10 `discover(playbook, summary)` = 2990 tok; WF-10 usa `name=`/`args=` y el schema `[target] [ports]`.
- G11 `artifact_execute_in_ram`, `kernel_trace`: `truncated` sin `cursor`; canary 76 elegible sin `next_action` de promote.
- G12 `aep_ctl(audit, usage)`: 975 tok con `bytes: 0, tokens: 0` en todo (telemetría nunca rellenada).
- G13 `service.status ssh` con `LoadState: not-found` → `OK/INFO` (debería NOT_FOUND/WARN).
- G14 `diagnose_system_crashes`: timestamps mixtos (fecha humana vs microsegundos string).
- G15 `autoevol(report)` sin `sig` y status OK → `candidates: []` sin razón.
- G16 `autoevol(log)`: generación 112 con `git_commit: unknown`, 1086 nodos, 629 gaps persistida (árbol parcial).
- G17 `playbook_run(list)`: `pb_multi_isolation` 824 runs desde tests (misma raíz que F9, ya corregida).
- G18 `playbook_run(batch, select_fields)`: proyección duplicada (`output.routes` y `routes`).
- G19 `network.probe` mapa de servicios corto (631 → unknown).
- G20 catálogo de plantillas en español, resto en inglés.
- G21 Capacidad ausente: descubrimiento de vecinos LAN. Propuesta `aep_ctl(network, neighbors)`:
  interfaces UP → prefijos de `routes` → barrido UDP asyncio para poblar ARP (≥ 6rw-) → `/proc/net/arp` +
  mDNS/WS-Discovery → `probe` opcional por vecino; 5r-x/4r-- solo lectura pasiva. Decisión de diseño del usuario.
- G22 `kanban_board(archive, task_id=N)` ignora `task_id`: barrido DRY_RUN de LINTED/REJECTED; BACKLOG y
  SYNTHESIZED no archivables; `unarchive` sí acepta `task_id`. Asimetría.
- G23 `kanban_board(create)` sin `description`/`refs`.

Aciertos a conservar: `autoevol(thread)` (578 tok, consumidores + tests impactados), `topos_audit_dag`,
`playbook_run(batch)` con `select_fields` (−90 %), `hardware.inventory`, `storage.usage`, `ipc.status`,
`backup.lkg_status`, `kernel_trace` (80 k eventos en 251 tok).

## Reanudar

1. Lanzar Dokimos sobre el worktree (suite completa una vez, ruff, Topos T1–T10, budgets, GAPS_BASELINE=1,
   T9 sin tocar la DB real, scope 8 archivos).
2. Graphos G2 → Hermon: ff-merge bajo `.aep_swap_fence`, push ff `dev` (7rwx, VERIFIED+G2).
3. Repetir las 8 llamadas de la ronda 1 contra el plano vivo y anotar tokens antes/después.
4. Si el usuario aprueba `network.neighbors`, planificar ONT-48 con G10–G23.
