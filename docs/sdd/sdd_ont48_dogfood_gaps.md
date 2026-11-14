# SDD: gaps de dogfooding ronda 2 (ONT-48)

- **Registro de pipeline**: `docs/pipeline/feature_20261113_ont48_dogfood_gaps.md` (anterior: `feature_20261113_ont47_dogfood_frictions.md`)
- **Estado**: VERIFIED (Dokimos, 1230 passed, 0 failed). Publicado en dev (commit de Hermon).
- **Base**: `dev` `c2f5152`. Rango: `aab6d4e`..`8f68910` (13 commits).
- **Regla de forma**: `detail` no cambia de forma salvo donde se indica. Cambios de forma sólo en compactos; el resto es aditivo.
- **Invariante del sobre**: `truncated = True` implica `cursor` no nulo (aplica a `execute_in_ram`, `kernel_trace`, board y pueue).

## 1. Seguridad y ejecución

### 1.1 `sandbox_run` (G24, `aab6d4e`)
- Los binds de usuario van primero; después `_bwrap_device_args()` emite `--proc /proc --dev /dev --tmpfs /dev/shm`. El `/dev` del sandbox es devtmpfs propio, así `/dev/null` es escribible.
- Con `rw_paths`, `/` ya no entra en `ro_mounts`. El bind ro se limita a `working_dir`, `ro_paths` y toolchain.
- `EXEC_SUSPECT`: exit 0 con `Traceback (most recent call last)` o `PermissionError` en stdout/stderr. Lleva `hint`. No es un error de campo.

### 1.2 `async_job_dispatch` (G25, `5f01529`)
- `OUTWARD_COMMANDS` (módulo-nivel, regex, documentada): `git push`, `git tag -a|--annotate` seguido de push en el mismo comando, `docker push`, `gh pr merge`, `gh release create`, `npm publish`, `twine upload`, `uv publish`, `cargo publish`, `pip upload`.
- Si el comando casa: tier < 7rwx → `PERMISSION_DENIED` con `matched` y `hint`. Tier 7rwx sin `confirm=True` → `CONFIRM_REQUIRED` con `matched` y `hint`. Con ambos se despacha y se escribe `job.outward_confirmed` en el ledger de audit.
- En ningún caso bloqueado se encola nada.
- `label` vacío → `aep-<tool>-<sha256(cmd)[:8]>` y `label_generated: true`.
- Nuevo parámetro: `confirm: bool = False`.

## 2. Persistencia del grafo (G16, G26, `437307e`)

`persist_generation` no persiste si:
- `git_commit == "unknown"` → `reason: "unknown_commit"`;
- el `root` analizado no es el `REPO_ROOT` del servidor (comparado con `Path.resolve()`) → `reason: "foreign_root"`;
- `node_count < 0.5 ×` el último `node_count` del mismo `root_path` → `reason: "node_count_drop"`.

Respuesta: `{"persisted": false, "reason": ...}`. Filas nuevas de `autoevol(log)` llevan `root_path` (columna nueva `root_path TEXT`, migración idempotente). Las filas anteriores no tienen `root_path`, así que `node_count_drop` no actúa hasta la primera fila con `root_path`.

## 3. Kanban (G22, G23, `5d3fa78`, `c1e7a25`)

- `archive(task_id=N)`: archiva esa tarjeta en cualquier lane salvo `PROMOTED`, que pasa a `PROTECTED`. Responde `applied: true`. Reversible con `unarchive`. `task_id` tiene prioridad sobre `states`.
- Barrido sin `task_id`: la respuesta DRY_RUN incluye `states_scanned`. Nuevo filtro opcional `title_like` (LIKE SQL parametrizado). Sin `states` explícitos, el barrido con `title_like` abarca las lanes no protegidas.
- `create` acepta `description` y `refs` (lista de strings). Columnas nuevas `description TEXT` y `refs TEXT` (JSON), migración idempotente. Se muestran en `detail`, no en `summary`.

## 4. Servicios, autoevol y crashes

- **G13 (`05b9511`)** `aep_ctl(service, status)`: `LoadState == "not-found"` → `status: NOT_FOUND`, `severity: WARN`, `next_action` que sugiere `aep_ctl(package, check, name=...)`. Mismo criterio en `scripts/aep-ctl`.
- **G15 (`7311d90`)** `autoevol(report)`: sin `sig` → `PARAM_ERROR` con `reason: "sig required (from evol_hint)"`. Con status que no es de error de campo (`is_field_error_status` falso) → `REJECTED_NOT_FIELD_ERROR` con `reason`. Nunca `OK` con `candidates: []` sin `reason`.
- **G14 (`d6860cc`)** `ts_iso` en `recent_systemd_errors` (desde microsegundos) y en `recent_coredumps` (desde `time`). Los campos originales se conservan.

## 5. Cursores, compactos y medidas (G10, G11, G12, G18, `cfae6c5`, `fc59cf6`, `71fbaf9`)

- **G11**: `artifact_execute_in_ram` y `kernel_trace` ganan `cursor: int = 0` sobre la lista truncada. Si `kanban_canary.eligible_for_promotion` es true, `next_action = kanban_board(action="promote", task_id=<id>)`.
- **G10**: `discover(playbook)` en `summary` y `brief`: `rules_of_engagement` (título hasta el primer `:`), `workflow_recipes` como `[{id, name}]`, `quick_reference` completo, `prerequisites_summary` sólo con claves en false. Objetivo ≤ 900 tok (medido 820). `detail` sin cambios. WF-10 usa `target=`/`ports=` (firma real de `aep_ctl`); `name`/`args` quedan como alias documentados.
- **G12**: `audit.usage` (`engine/security.get_agent_usage_summary`) persiste `tok` en el evento y lo agrega. Donde el ledger no registra tamaños, los campos a cero se eliminan en compacto y se declara `fields_unavailable: ["bytes","tokens"]`.
- **G18 omitida (T12, sin commit)**: `playbook_run(batch, select_fields)` sigue duplicando `output.routes` y `routes`. Pendiente.

## 6. Catálogo y telemetría (G19, G20, `ed4967c`, `8f68910`)

- Mapa de servicios TCP ampliado: 111 rpcbind, 139 netbios, 548 afp, 631 ipp, 1900 ssdp, 2049 nfs, 3702 ws-discovery, 5353 mdns, 5900 vnc, 8006 proxmox, 9100 jetdirect.
- Descripciones de plantillas en inglés en `templates/registry.json`. Se conserva `description_es`.

## 7. Fuera de contrato

- **G21 `network.neighbors`**: no aprobado. Requiere decisión de diseño del usuario.
- **G27 cola pueue vaciada sin rastro**: abierto. Propuesta: evento de audit si el total de tareas cae más de un 50 % entre llamadas y fixture con historial propio. No implementado.
- `aep_front.py` y `aep_backend.py` sin cambios (no hace falta `harness_reconnect`).
