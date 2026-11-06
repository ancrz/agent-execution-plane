# SDD ONT-39: AEP Live Plane, o cómo ver los cambios del servidor sin recargar el MCP

- **Autor (arquitecto):** Claude Code (orquestador)
- **Ejecutor:** Antigravity (`gemini-3.8-flash-high`), pipeline Topos en modo **Full**
- **Fecha:** 2026-11-05
- **Gaps que cierra:** D-09 y D-10 de `docs/reports/2026-11-05_aep_mcp_live_audit_and_agy_harness.md`
- **Premisa:** hecho por agentes y para agentes. Un agente no es una persona que reinicia su terminal. La superficie MCP debe ser **estable** y la implementación debe poder **intercambiarse en caliente**.

## 1. Problema

- Cada harness (Claude Code, Antigravity, Codex) lanza su propio `server.py` y lo mantiene vivo toda la sesión.
- Un commit nuevo deja esos procesos ejecutando código viejo: es el estado STALE que detecta `--audit`.
- `RefreshMcpServers` regenera los esquemas JSON de Antigravity, pero **no reinicia** el proceso.
- `stale` solo compara commits, así que no detecta cambios sin commitear del working tree.
- Resultado: el agente prueba código viejo creyendo que prueba código nuevo. Es un falso positivo de verificación.

## 2. Decisión

Se divide el servidor en dos procesos, con una dependencia unidireccional (front → backend, sin co-dependencia):

```
harness ──stdio/MCP──▶ aep_front.py (estable, ~300 líneas, rara vez cambia)
                           │  JSON-lines sobre socketpair privado (AF_UNIX)
                           ▼
                       aep_backend (worker: importa server.py y su tool manager de FastMCP)
                       gen N  ──swap atómico──▶  gen N+1 (se valida antes de la promoción)
```

- **Front** (`aep_front.py`, raíz del repo):
  - Usa el `Server` low-level de `mcp` (no FastMCP), para no validar los argumentos contra un esquema cacheado viejo; los pasa tal cual.
  - Implementa `tools/list`, que pide los esquemas al backend activo, y `tools/call`, que reenvía al backend.
  - Anuncia `capabilities.tools.listChanged = true`.
  - Solo depende de la stdlib y de `mcp`. **No importa `engine/`.**
- **Backend** (`aep_backend.py`):
  - Importa `server` y atiende `{"op":"list"}`, `{"op":"call","name":..,"args":..}` y `{"op":"health"}` usando el tool manager interno de `server.mcp`.
  - Un proceso por front (modo `private`, el que se implementa ahora). Así se preserva el aislamiento entre harnesses y un fallo no se propaga.
- **Fingerprint de código** (`code_fingerprint`):
  - Es el SHA-256 de `(ruta, mtime_ns, tamaño)` de `server.py`, `aep_backend.py`, `engine/**/*.py`, `templates/registry.json` y `schemas/*`.
  - Cuesta un `stat` por archivo; para ~40 archivos son menos de 2 ms.
  - Se evalúa **antes de cada `tools/call`**, con un debounce de 1 s. Opcionalmente también desde un hilo `inotify`, si existe en la stdlib vía `ctypes`; si no, solo por sondeo.

## 3. Protocolo de swap (fail-safe)

1. Se detecta que el fingerprint cambió.
2. Se arranca el backend gen N+1 y se espera su `health`, con un timeout de 20 s. El backend debe importar `server` y listar las tools.
3. Si el health es OK: se promueve N+1 a activo, las llamadas nuevas van a N+1, se drenan las llamadas en vuelo de N (máximo 30 s) y luego se manda SIGTERM a N.
4. Si el health falla: **se conserva N**. Se registra `last_reload_error` y el agente lo ve en `discover` (`severity=WARNING`, con `next_action`). Un código roto nunca sustituye a uno sano.
5. Si cambia el `schema_hash` entre N y N+1, se emite `notifications/tools/list_changed`.
6. Las llamadas en vuelo nunca se cortan. La llamada que disparó el swap se atiende con N+1.

## 4. Gobierno por tier (chmod)

| Tier | Comportamiento |
|---|---|
| `7rwx` / `6rw-` | Auto-swap activado (por defecto) |
| `5r-x` | Auto-swap activado (ejecutar está permitido y no hay escritura en disco) |
| `4r--` | **Watch-only**: no se swapea; se reporta `stale=true` con `next_action` |
| Override | `AEP_HOTSWAP=0` lanza `server.py` directo (modo legacy); `AEP_HOTSWAP_MODE=watch` fuerza watch-only |

## 5. Contrato de verificación del reload (obligatorio para todo agente)

`discover(action="capabilities", verbosity="terse")` debe incluir siempre:

`loaded_commit`, `repo_head`, `code_fingerprint_loaded`, `code_fingerprint_disk`, `stale` (true si cambia el commit **o** el fingerprint), `backend_generation`, `last_swap_at`, `last_reload_error`, `hotswap_mode` (`auto|watch|legacy`).

**Regla del agente:** después de editar código o de un reload, llamar a `discover(capabilities, terse)` y exigir `stale == false` y `code_fingerprint_loaded == code_fingerprint_disk`. Si no se cumple, el cambio **no** está cargado y cualquier prueba hecha sobre él es inválida.

## 6. Cambios en scripts

- `scripts/aep-mcp-launch.sh`: ejecuta `aep_front.py` por defecto; `AEP_HOTSWAP=0` ejecuta `server.py`.
- `scripts/aep-sync.sh`:
  - (a) El hot reload de Antigravity captura el código HTTP y distingue `reload_ok`, `reload_failed` y `no_language_server`, sin `ok` incondicional.
  - (b) Tras el sync, ejecuta `--audit` y reporta las instancias STALE reales.
  - (c) Las instancias legacy STALE siguen siendo warn-only. Se añade `--reap-stale`, opt-in, que solo envía SIGTERM a `server.py` huérfanos (PPID=1).
- `aep-sync.sh --print-fingerprint`: calcula el fingerprint esperado desde disco, para que un juez externo lo compare.

## 7. Topología y riesgos

- **Front → backend:** dependencia. El backend no conoce al front. El contrato JSON-lines se documenta en `aep_front.py`.
- **Riesgo, RAM:** dos procesos por harness durante el swap (unos 370 MB más, transitorios). Se mitiga terminando N en cuanto se drena.
- **Riesgo, estado en proceso:** el pool en `/dev/shm`, `_shared_session_cache` y el socket `aep.sock` viven en el backend. Con varios backends hay que verificar que el mux `aep.sock` tolera re-bind (unlink + bind) o que solo lo posee un backend; si no, debe degradar sin fallar.
- **Riesgo, el propio front:** si cambia `aep_front.py` sí hace falta un reload real. Por eso el front debe ser mínimo y estable. `discover` reporta `front_stale` comparando el mtime del front con el arranque.
- **Clientes con esquema cacheado** (Antigravity): los nombres de las tools son estables y el front no valida argumentos, así que un parámetro nuevo funciona aunque el cliente no lo vea en su esquema.

## 8. Criterios de aceptación (Dokimos)

1. Test e2e: arrancar el front por stdio, llamar a `discover` y anotar gen=1. Tocar un archivo de `engine/` (cambio inocuo con mtime nuevo) y llamar de nuevo: gen=2, `stale=false`, mismo PID de front y PID de backend distinto.
2. Introducir un `SyntaxError` en una copia temporal del repo: el swap falla, gen sigue en 1, `last_reload_error` no está vacío y las tools siguen respondiendo.
3. Una llamada larga en vuelo (`sandbox_run sleep 3`) durante el swap termina con éxito.
4. Al cambiar el esquema de una tool, el front emite `notifications/tools/list_changed`.
5. En tier `4r--` (simulado), no hay swap y aparece `stale=true`.
6. La suite completa sigue en verde y no hay fugas de FD en el front (`fd_delta == 0` tras 10 swaps).
7. **Juez externo:** `agy -p` (sesión nueva) y la sesión de Claude Code del orquestador ven el mismo `code_fingerprint` tras un commit, **sin reload**.

## 9. Integridad durante el hot-swap

Garantías que el front mantiene para que un swap nunca sirva código roto, a medio escribir o con estado perdido. Cubren D-18 a D-21.

1. **Validate-before-promote.** Un candidato (Gen N+1) se arranca aparte y debe pasar `health` y `list` antes de promoverse. Si falla, Gen N sigue sirviendo y el error se guarda en `last_reload_error`. Un código roto nunca sustituye a uno sano.
2. **Swap atómico bajo lock con drenaje.** La promoción ocurre dentro de `swap_lock`; el backend anterior solo se termina cuando sus llamadas en vuelo terminan (máx. 30 s). Las llamadas nuevas ya van a Gen N+1.
3. **Estado persistente fuera del proceso.** Nada que deba sobrevivir a un swap vive solo en RAM del backend: SQLite en modo WAL con `BEGIN IMMEDIATE` para escrituras concurrentes entre generaciones, y el pool de sesiones/artefactos en `/dev/shm/aep_pool`. Los cachés en proceso son prescindibles y se reconstruyen.
4. **Error de recarga no pegajoso (D-18).** `set_meta` acepta `None` explícito: solo se tocan las claves enviadas. El front no propaga `AEP_LAST_RELOAD_ERROR` a un candidato; el error se envía por `set_meta` únicamente al backend ACTIVO. `server.py` solo usa el fallback de entorno si el meta no trae la clave. Tras un swap correcto, o si el código vuelve al que ya corre, `last_reload_error` pasa a `None` y la severidad a INFO.
5. **Anti-tormenta y clasificación de fallos (D-19).** Cada fallo de swap se clasifica y se expone como `failure_kind` (`deterministic|transient`, también como prefijo de `last_reload_error`):
   - **deterministic**: el candidato terminó con un traceback (proceso salido y traceback o `SyntaxError` en su log). El front fija `failed_fingerprint` y no reintenta mientras el fingerprint en disco sea igual. Para forzar un nuevo intento hay que **tocar el archivo** (cambiar su mtime o contenido), lo que cambia el fingerprint.
   - **transient**: timeout de health, excepción de spawn o `list` fallido con el proceso vivo. No se fija `failed_fingerprint`; se reintenta con backoff de 1 s, 2 s y 4 s (máx. 3 intentos). Tras el tercer fallo transitorio se fija el fingerprint para evitar la tormenta; de nuevo, **tocar el archivo** fuerza el reintento.
   `swap_attempts` (en el meta de `discover`) cuenta los spawns de candidatos. Ajustes: `AEP_HOTSWAP_DEBOUNCE_S` (1.0 por defecto) y `AEP_HOTSWAP_HEALTH_TIMEOUT_S` (20 por defecto).
6. **Quiescencia (D-20a).** Solo se hace swap si el fingerprint es idéntico en dos lecturas separadas por `AEP_HOTSWAP_QUIESCE_MS` (por defecto 300 ms). Si cambia entre lecturas, se difiere a la siguiente llamada sin esperar al debounce.
7. **Fence explícito (D-20b).** Si existe `PROJECT_ROOT/.aep_swap_fence`, el front no hace swap y `discover` reporta `swap_fenced=true`; `stale` sigue siendo honesto. El fence se reevalúa tras adquirir `swap_lock` (antes del spawn) y otra vez antes de promover; si aparece en medio, el candidato se termina y no hay swap. Un fence con mtime superior a 600 s se ignora como huérfano y se reporta con `swap_fence_orphan=true`. El archivo está en `.gitignore`.
8. **Front autocontenido (D-21).** `aep_front.py` incluye una copia mínima de `code_fingerprint`, usada solo si `engine/fingerprint.py` no se puede importar, para que un front nuevo arranque aunque ese archivo vigilado esté roto. Un test garantiza hash idéntico entre ambas implementaciones.
9. **Logs por front.** Los logs del backend son `aep_backend_<front_pid>_gen<N>.log`. La retención de los últimos 5 es por `front_pid`, y los logs de fronts muertos con más de 1 día se eliminan.
10. **Stale honesto + regla del agente.** Mientras el código cargado difiera del de disco, `stale=true`; nunca se oculta. **Regla para cambios multiarchivo:** crear `.aep_swap_fence`, editar, validar, borrar el fence y luego verificar con `discover(capabilities, terse)` exigiendo `stale == false` y `code_fingerprint_loaded == code_fingerprint_disk`.
11. **Ruta del fence configurable (D-22).** `AEP_SWAP_FENCE_PATH` fija la ruta del fence (por defecto `PROJECT_ROOT/.aep_swap_fence`). Se lee en cada comprobación (inicial, bajo `swap_lock` y previa a promover), de modo que todas coinciden. Los tests de integridad lanzan el front con `AEP_SWAP_FENCE_PATH=<tmp>/fence` y nunca crean ni borran el fence real, que un agente puede estar usando durante un aterrizaje.
