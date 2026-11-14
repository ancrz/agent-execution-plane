# SDD: Gaps de dogfooding ronda 3 (ONT-49)

- **Registro**: `docs/pipeline/feature_20261114_ont49_dogfood_round3.md`
- **Estado**: VERIFIED (Dokimos), publicado en dev. Base `dev` `66b84d9`; commits `d0b436e`, `d1d6ad6`, `f5b8212`, `44b8d8d`.
- **Principio**: contratos aditivos. Los modos `detail` no cambian de forma salvo campos nuevos. Los budgets no suben. `truncated` implica `cursor`.

## 1. Archive sin candidatos (G28, `d0b436e`)

- Contrato: `archive` con `apply=True` y `candidate_count == 0` devuelve `status: NOOP`, `applied: false`, `archived: 0`.
- Con candidatos: `status: ARCHIVED`, `archived: n`.
- `hint` se omite cuando es `None`. Nunca se envía `hint: null`.
- `DRY_RUN` no cambia, salvo que `archived` aparece siempre.

## 2. Tablero terse plegado por límite (G29, `d1d6ad6`)

- `kanban_board(board, verbosity="terse")` devuelve sólo `status`, `counts`, `lane_totals`, `archived_total` y `threshold`.
- Si `limit > 0`, cada lane lista `[task_id, title[:60]]` hasta `limit` elementos.
- `summary` y `brief` no cambian: ya pliegan.
- Presupuesto: terse con `limit=1` y 45 tarjetas, <= 400 tok (medido: 175).

## 3. Ámbito de base de datos (G30, `d1d6ad6`)

- `kanban_board` y `artifact_catalog(browse)` en `detail` añaden `db_scope`: `"real"` o `"custom"`.
- `db_scope: "custom"` (ruta distinta a la por defecto o variable de entorno de DB fijada) añade `db_path`.
- En compactos sólo aparece `db_scope` cuando es `custom`.
- Propósito: que un verificador vea si una llamada está sobre la base real.

## 4. Historial de cola con caída (G27, `f5b8212`)

- Estado en RAM por sesión: último `total_tasks` observado.
- Si el total nuevo cae más de un 50 % y el anterior era >= 10, `async_job_dispatch(status)` añade `history_drop: {"from": n, "to": m}` y `severity: "WARN"`.
- Se registra el evento `jobs.history_drop` en `security_audit_log` mediante el helper de auditoría existente.
- Límite: detecta y audita la caída; no la impide.

## 5. Fixture om06 autocontenida (`f5b8212`)

- `test_gap_om06_async_job_dispatch_compact_status_pagination` siembra `pueue add -l seed-om06-<i> -- true` si hay menos de 6 tareas.
- No ejecuta `pueue clean`. No depende del historial del host.

## 6. README (`44b8d8d`)

- La fila `async_job_dispatch` declara `verbosity` por defecto `summary` y `limit` 15, igual que la firma en `server.py`. Sin test.

## 7. Fuera de contrato

- G18: proyección duplicada en `playbook_run(batch, select_fields)`. Omitida por contrato de tests; requiere decisión del usuario.
- G21: `network.neighbors`. No aprobado; decisión de diseño pendiente.
