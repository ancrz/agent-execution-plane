# SDD ONT-47: fricciones de dogfooding (contratos compactos y sobre truncado)

- **Estado**: VERIFIED, publicado en dev (commits `c455b4b`..`5377589` sobre `3541211`)
- **Registro**: `docs/pipeline/feature_20261113_ont47_dogfood_frictions.md` (anterior: `feature_20261113_ont46_extractor_precision.md`)
- **Modo**: Short
- **Módulos**: `server.py`, `engine/net_telemetry.py`, `engine/primitives.py`, `engine/telemetry.py`, `scripts/aep-ctl`

## 1. Specify

**Problema.** Ocho respuestas del plano vivo gastaban tokens sin aportar señal o rompían su propio contrato. Un booleano (`commit_drift`) sin explicación invitaba a recargar; un modo compacto volcaba todo; un `null` (`pid`) escondía un dato disponible; un `truncated: true` llegaba sin `cursor`; y una distancia de 0.30 se presentaba como `OK`.

**Criterio de éxito.**

1. Modo `detail` con la misma forma que `dev`.
2. Modos compactos con menos tokens y sin perder la información de decisión.
3. Invariante del sobre: `truncated ⇒ cursor` no nulo.
4. Ningún presupuesto de tokens sube; `GAPS_BASELINE` se mantiene en 1.
5. Ninguna base de datos real tocada por tests.

**Fuera de alcance.** Descubrimiento de vecinos de red (`network.neighbors`, G21): decisión de diseño del usuario. `aep_front.py` y `aep_backend.py`.

## 2. Plan

| Fricción | Decisión | Tarea |
|----------|----------|-------|
| F1 | Clave aditiva `drift_kind`, sólo cuando `commit_drift` es True; `commit_drift` sigue siendo bool | T1 |
| F2 | `socket-monitor` compacto pliega por estado y protocolo y pagina los listeners | T2 |
| F3 | Resolver inode → pid/proceso en `/proc`, sólo cuando se pide (`resolve_pids`) | T3 |
| F4 | Probe compacto con filas `open` y `closed_by_reason` | T4 |
| F5 | Señal de relevancia `confidence` a partir de `best_distance`, sin filtrar resultados | T5 |
| F6 | `error_class` desde la última línea de excepción de `stderr` | T6 |
| F7 | Paginación con `cursor` y `lane_totals` en el tablero; `cursor` en pueue status | T7 |
| F8 | Schema compacto por dominio | T8 |
| F9 | Fixture de `test_spec_om7_ipc_batch.py` aislada en tmp | T9 |

Regla de forma: sólo cambian los modos compactos y las claves aditivas. `detail` no cambia.

## 3. Tasks

| Tarea | Commit | Contrato o cambio |
|-------|--------|-------------------|
| T1 `discover` | `c455b4b` | `drift_kind: "docs_only" \| "code" \| "unverified"`, sólo con drift |
| T2 `socket-monitor` | `4f8048a` | `count`, `by_state`, `by_proto`, `listeners`, `limit` (25), `cursor`, `truncated` |
| T3 listeners | `dd0bb31` | `map_socket_inodes(inodes) -> dict[int, tuple[int, str]]`; `parse_proc_net_sockets(protocol, *, resolve_pids=False)` |
| T4 probe | `3158370` | `closed_by_reason: {timeout: n, refused: n, …}` en compacto |
| T5 docs | `1893ac6` | `best_distance`, `confidence` (HIGH ≤ 0.20, MEDIUM ≤ 0.28, LOW), `match_status: "NO_HIGH_CONFIDENCE_MATCH"` |
| T6 telemetry | `c084b29` | `normalize_error_class`: explícita → `error` → `stderr` → `unknown` |
| T7 envelope | `5a90232` | `kanban_board`: `cursor` (int), `lane_totals`; `async_job_dispatch(status)`: paginación con `cursor` |
| T8 schema | `4185412` | compacto por dominio: `domain`, `schema`, `precondition_defaults`, `degradation_matrix` (sin `domains`) |
| T9 aislamiento | `51a8eca` | `tests/test_spec_om7_ipc_batch.py` escribe en tmp, no en `artifacts.db` |
| T10 regresión | `5377589` | `tests/test_ont47_dogfood_frictions.py` in-process |

## 4. Contrato nuevo

```
discover(capabilities, terse)          + drift_kind (solo si commit_drift)
default_primitives(run, socket-monitor, summary)
    count, by_state{}, by_proto{}, listeners[] (solo LISTEN: proto, local, uid, pid?),
    limit=25, cursor=0, truncated, cursor (sobre)
    params.state presente -> pagina "sockets" de ese estado
aep_ctl(network, listeners)            pid/process por inode (resolve_pids=True)
aep_ctl(network, probe, summary)       ports solo open; closed_by_reason{}
query_system_docs(...)                 best_distance, confidence, match_status
kanban_board(board, summary)           cursor (int), lane_totals{}
async_job_dispatch(status, summary)    cursor cuando truncated
aep_ctl(domain=<d>, action=schema, summary)
    domain, schema, precondition_defaults, degradation_matrix (sin domains)
```

**Invariantes**

- `truncated ⇒ cursor is not None` en las respuestas de board y status (test genérico).
- `detail` conserva la forma de `dev`.
- `map_socket_inodes` es determinista para la misma vista de `/proc` y de un solo pase: ignora `PermissionError`, `FileNotFoundError` y `ProcessLookupError`.
- `normalize_error_class` es determinista: misma entrada, misma `error_class`.

## 5. Validate

| Verificación | Resultado |
|--------------|-----------|
| Suite completa (una corrida) | 1174 passed / 1 failed (fallo de carga de `test_cold_extraction_under_two_seconds_and_stable_r`, 2.083 s frente a 2.0 s; pasa aislado) |
| `ruff check` y `ruff format --check` | limpios (259 archivos) |
| Presupuestos de tokens | sin cambios |
| `GAPS_BASELINE` | 1 |
| `resolve_pids` | 18.5 ms en el host, tope 50 ms |
| `socket-monitor` summary | 3783 → 483 tok |
| `probe` summary | 570 → 102 tok |
| `schema` network summary | 1120 → 444 tok |
| `socket-monitor` y `schema` detail | sin cambios de forma (3903 y 3296 tok) |
| `query_system_docs` LOW | `best_distance` 0.2996, `NO_HIGH_CONFIDENCE_MATCH` |
| `sandbox_run` FileNotFoundError | `error_class` `unknown` → `filenotfounderror` |
| T9 | `run_count` de `pb_multi_isolation` estable en 840 |

Pendiente: repetir las 8 llamadas de la ronda 1 contra el plano vivo tras el hot-swap (paso posterior a Hermon).

## 6. Riesgos y backlog

- Margen de extracción en frío de ONT-46 (1.5–1.7 s frente a 2.0 s): el fallo de carga de esta corrida pertenece a ese margen, no a ONT-47.
- Diferencia de 1 token en `probe` detail (680 → 681): la forma de claves se conserva; causa no investigada (assumption: valores).
- Backlog ONT-48 (G10–G23): ver sección 7 del registro.
- Decisión abierta del usuario: `network.neighbors` (G21).
