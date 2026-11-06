# AEP: auditoría en vivo del MCP cargado, discrepancias con el README y harness de pruebas con Antigravity

- **Fecha:** 2026-11-05
- **Auditor:** Claude Code (orquestador), consumiendo el MCP `agent-execution-plane` en vivo
- **AEP auditado:** `b2afeb2` (`server_version=v0.2.8`, `schema_hash=a6bee7a5…0bb7d`, `stale=false`, tier `7rwx` vía `sudo -n`)
- **Método:** ~30 llamadas reales a las 16 tools, `pytest` en el host, `aep-sync.sh --check/--audit` y una sonda headless de Antigravity (`agy -p`)
- **Destinatario:** Antigravity, que debe reproducir las pruebas de la §5 tras cada cambio

---

## 1. Estado verificado

| Área | Evidencia | Estado |
|---|---|---|
| Inventario de tools | `discover(action="schema")` da `tools_count=16`; `server.py` tiene 16 `@mcp.tool`; `~/.gemini/antigravity/mcp/agent-execution-plane/` contiene 16 esquemas y `instructions.md` | ✅ Coincide con el README (16 tools / 19 capacidades) |
| Tests | `pytest -q` en el host: **153 passed** en 21.9 s, 6 warnings (`fork()` en un proceso multihilo, `engine/landlock.py:242`) | ✅ Coincide con el badge 153/153 |
| Validación de sincronización | `aep-sync.sh --check` da OK | ✅ |
| Readiness | 18/19 capacidades listas. `crash_forensics` aparece con `ready=false` porque falta `coredumpctl`. El fallback a Apport funciona: 2 alertas pendientes | ⚠️ Ver D-08 |
| Ledger de auditoría | `aep_ctl audit verify`: 408 bloques íntegros | ✅ |
| Memoria semántica | `artifact_catalog(query)` da CACHE_HIT por kNN en 31 ms. `query_system_docs` resuelve `bwrap --ro-bind` en 19 ms con unos 100 tokens | ✅ (ver D-06 sobre la calidad del hit) |
| Pico tools | `default_primitives run mem-stat`: 6.8 ms y 143 tokens. `topos_audit_dag`: 0.33 ms y 126 tokens. `kanban_board`: ~1 k tokens. `playbook_run list`: 5 playbooks, todos con veredicto TRUST | ✅ Funcionales |
| IPC / pool en RAM | `/dev/shm/aep.sock` activo, 2 de 16 slots, `fd_delta=0` | ✅ |
| Instancias vivas | `aep-sync.sh --audit` encuentra **3 instancias STALE**, una de ellas de Antigravity (PID 17815, anterior al HEAD) | ⚠️ Ver D-10 |
| Antigravity headless | `agy -p … --output-format json --mode plan` arranca un servidor AEP nuevo (PID 127123, mismo `schema_hash`) y responde en 20.9 s. El proceso termina limpio al acabar | ✅ Habilita pruebas sin intervención humana (§4) |

---

## 2. Eficiencia de tokens medida (el campo `t.tok` lo reporta el propio servidor)

| Llamada | Tokens | Valoración |
|---|---:|---|
| `discover(capabilities, summary)` | 1 391 | Aceptable para la primera llamada |
| `discover(capabilities, terse, session_id)` | 301 | ✅ Ahorro del 78 %. El README promete ~249 |
| `discover(playbook, summary)` | 2 865 | ⚠️ `select_fields` se ignoró (D-03) |
| `discover(schema, summary)` | **~18 000 (72 KB)** | ❌ `summary` no recorta nada (D-01) |
| `discover(schema, terse, select_fields=[…])` | 378 | ✅ La proyección funciona |
| `aep_ctl(schema, summary)` | 3 789 | ⚠️ Las precondiciones se repiten por cada acción (D-04) |
| `aep_ctl(ipc status, summary)` | 674 | ⚠️ El pool aparece duplicado (D-05) |
| `artifact_catalog(query)` / `playbook_run(list)` | 177 / 568 | ⚠️ Usan el sobre legacy `envelope`+`telemetry` en lugar de `t` (D-02) |
| `process_inspect(brief, limit=5)` / `default_primitives` / `topos` | 227 / 143 / 126 | ✅ Excelente |

---

## 3. Discrepancias y mejoras

Severidad: **A** = rompe una promesa del README o confunde a un agente; **M** = desperdicia tokens o introduce ruido; **B** = cosmético.

| ID | Sev | Área | README afirma | Realidad observada | Mejora propuesta | Prueba de aceptación |
|---|:-:|---|---|---|---|---|
| D-01 | A | `discover(schema)` | `verbosity` compacta las salidas | Con `verbosity="summary"` devuelve 72 KB y ~18 k tokens: el docstring y el JSON Schema completo de las 16 tools más la matriz de degradación. El cliente lo trunca | En `summary`, devolver solo `{tool: {params: [nombre:tipo=default], actions}}`. Dejar el JSON Schema completo para `detail` | `tok(schema, summary) < 3000` |
| D-02 | M | Sobre de respuesta | ONT-29: deduplicación del sobre y stub `t` compacto | `artifact_catalog`, `playbook_run` y `kanban_board` siguen emitiendo `envelope{}` (que duplica `status`, `summary`, etc.) más `telemetry{}` de unos 10 campos. El resto de tools emite `t` | Unificar todas las tools con `attach_envelope` en formato plano con `t`, y dejar `telemetry` solo para `detail` | Ninguna respuesta en `summary` contiene la clave `envelope` |
| D-03 | A | `select_fields` | «smart dot-path fallback» | (a) Una ruta inexistente (`workflows`) devuelve el payload **completo** sin avisar. (b) Una ruta con índice (`suggested_capability.0.capability`) convierte la lista en un objeto `{"0": …}`, lo que cambia el tipo | (a) Devolver solo las rutas resueltas más `unresolved_fields: [...]`. (b) Mantener las listas como listas | Una ruta inválida da `unresolved_fields` y la proyección indexada conserva el tipo `list` |
| D-04 | M | `aep_ctl(schema)` | Esquema compacto | `preconditions` se repite en cada una de las ~60 acciones, casi siempre con el mismo valor (`DIMINISHED/IN_MEMORY_FALLBACK/deterministic`) | Declarar `defaults` por dominio y listar solo las excepciones (por ejemplo `start: FULL`) | `tok < 1500` en `summary` |
| D-05 | M | `aep_ctl(ipc status)` | — | `session_pool` y `mux.pool` contienen el mismo objeto con todos sus slots | En `summary`, eliminar `mux.pool` y conservar solo los contadores | Desaparece el bloque duplicado |
| D-06 | M | Memoria semántica | Las bandas de confianza gobiernan la reutilización | `artifact_catalog(query, "monitorear sockets")` da CACHE_HIT con `socket_prov_demo` (`execution_count=0`), cuando existe `socket-monitor` con 93 ejecuciones y efectividad 0.997. El kNN gana a la confianza | Re-rankear el top-K semántico por `distance × ponder.effective` y penalizar `execution_count=0` | La consulta devuelve el artefacto probado |
| D-07 | A | `discover(use_case)` | Anclas bilingües, 10/10 probes | «recordar qué artefacto usé para monitorear sockets» da `LOW` con relevancia 0.06. «monitor open tcp sockets» da `LOW` y enruta a `process_introspection` en lugar de a `system_inspect`/`semantic_memory`. La llamada en frío tarda **5.0 s** por la carga del embedder | Recalibrar el umbral HIGH/LOW y añadir anclas (sockets, tcp, puertos) a `system_inspect`. Precargar el embedder en un hilo de arranque | Las dos queries dan `HIGH` y la primera llamada tarda menos de 500 ms |
| D-08 | M | Capacidades | `crash_forensics` operativa | Aparece con `ready=false` (falta `coredumpctl`) aunque el fallback a Apport sí funciona | Marcar `ready=true, mode="apport_fallback"` cuando existe `/var/crash` | `ready=true` con `mode` |
| D-09 | A | `aep-sync.sh` (hot reload de agy) | README §10 y memoria: «hot-reload RefreshMcpServers» | El bloque Python termina en `>/dev/null 2>&1 \|\| true` y el `curl` descarta su resultado, así que se imprime `ok "…hot-reload"` **siempre**, falle o no. Además, la instancia de Antigravity PID 17815 sigue STALE: `RefreshMcpServers` regenera los JSON de esquema pero **no reinicia** el proceso `server.py` | Capturar el código HTTP del `curl`, distinguir `reload_ok`, `reload_failed` y `no_language_server`, y después verificar con `--audit` que el PID cambió | El sync reporta un PID nuevo o una advertencia explícita |
| D-10 | M | Instancias | Se detectan las instancias stale | 3 instancias stale conviven con las nuevas (2 de Claude Code y 1 de Antigravity). `--audit` solo avisa | Añadir un modo opt-in `--audit --reap-stale` que mande SIGTERM únicamente a procesos `server.py` huérfanos (PPID=1) o con confirmación | Cero instancias stale después de la recarga |
| D-11 | B | Textos internos | 16 tools, WF-1..WF-11 | El docstring de `discover` dice «para las 15 herramientas» (`server.py:419`). `next_action` dice «WF-1..WF-9» (`server.py:652`). El resumen en caché de `schema` dice «15 tools, 0 domains» | Generar esos textos a partir de `len(_tools)` y del número de recetas | grep de «15 herramientas\|WF-1..WF-9» da 0 resultados |
| D-12 | B | Versionado | `server_version v0.2.8` | `pyproject.toml` tiene `version = "0.1.0"` y la última entrada de `CHANGELOG.md` es `0.2.7` (ONT-28). Faltan las entradas de ONT-29 a ONT-37 | Usar una única fuente de versión (`pyproject` → `server_version`) y completar el CHANGELOG | `importlib.metadata.version == server_version` |
| D-13 | M | Higiene del estado | Kanban y playbooks como memoria evolutiva | El tablero vivo tiene muchas tarjetas de prueba (`Test Add Alias Task` ×N, `Batch Task 1`, 35 en SYNTHESIZED). El playbook `pb_multi_isolation` acumula 164 ejecuciones. Pueue tiene 1 109 tareas. Las verificaciones de consumidor escriben en la DB de producción | Usar `agent_id="test-*"` o `AEP_DATA_DIR` efímero para las pruebas de consumidor, archivar las tarjetas `Test*` y añadir `async_job_dispatch(action="clean")` | `board` sin títulos `Test*`; Pueue con menos de 50 tareas terminadas |
| D-14 | B | README §14 | — | La fila «Network & Security (ONT-32)» habla de un «15-tool invariant». La fila «Omarchy & IPC» dice «109/109 tests». Ambas son valores históricos que contradicen el badge 153/153 | Unificar con el número actual o marcarlas como «histórico (ONT-xx)» | — |
| D-15 | B | README §13 | Árbol del repositorio | La lista de `tests/` coincide con el disco. En cambio, `docs/` solo lista `sdd/` y omite `reports/`, `pipeline/`, `COMPACT.md`, `STATE.md`, `PROJECT.md` y `MILESTONES.md` | Completar el árbol | — |
| D-16 | B | Ergonomía de `sandbox_run` | WF-2: `sandbox_run(pytest)` | Ejecutar la suite AEP *dentro* de `sandbox_run` falla en `test_sandbox_hides_the_host_workspace`: un bwrap anidado no puede crear namespaces | Marcar ese test con `skipif(os.environ.get("AEP_IN_SANDBOX"))` y exportar esa variable dentro del jail | La suite pasa dentro y fuera del sandbox |
| D-17 | B | Warnings | — | `DeprecationWarning: fork() en un proceso multihilo` en `landlock.py:242` (Python 3.14) | Usar `multiprocessing` con contexto `forkserver`, o `os.posix_spawn` con un helper | 0 warnings |

**Fuera del alcance de AEP, detectado de paso (seguridad):** en la configuración de `agy mcp list`, el servidor `jenkins-ci` lleva un `--api-token` en texto plano dentro de `args`, y `github-mcp-server` asigna a `GITHUB_PERSONAL_ACCESS_TOKEN` una *ruta* (`/home/ancruz/.env`) en lugar de un valor. Conviene rotar el token de Jenkins y moverlo a una variable de entorno.

---

## 4. ¿Puede Antigravity probar el MCP sin intervención humana? Sí

1. **Modo headless (verificado):** `agy -p "<prompt>" --output-format json --mode plan --print-timeout 180s`. Cada invocación arranca un `server.py` **nuevo** con el código del HEAD, así que **no depende del hot reload**. Este es el camino más fiable para pruebas controladas. Devuelve JSON (`status`, `response`, `usage`) que se puede parsear.
2. **Hot reload (sesiones IDE largas):** `RefreshMcpServers` sirve para refrescar esquemas, pero no reinicia el proceso (D-09). Para las pruebas no hay que confiar en él; debe usarse `agy -p`.
3. **Quién conduce a quién:** Claude Code (o un cron o Pueue) puede lanzar `agy -p` como juez externo, de modo que Antigravity actúe como **consumidor independiente** y no como autor. Coste medido: unos 35 k tokens de entrada por sonda.
4. **Restricciones:** usar `--mode plan` (solo lectura) en las sondas de verificación. Usar `--dangerously-skip-permissions` **solo** si se aprueba explícitamente para pruebas que mutan estado, y siempre con `agent_id="agy-test"`.

### Prompt canónico para Antigravity (batería de aceptación)

```text
Eres el consumidor de verificación del MCP agent-execution-plane. NO modifiques archivos.
Ejecuta, en orden, y para cada uno reporta {id, pass:bool, tok:int, nota}:
T1 discover(action="capabilities", verbosity="terse", session_id="agy-test") -> stale==false
T2 discover(action="schema", verbosity="summary") -> t.tok < 3000            (D-01)
T3 discover(action="playbook", select_fields=["nope"]) -> contiene unresolved_fields (D-03a)
T4 discover(use_case="monitor open tcp sockets", select_fields=["suggested_capability.0.capability"])
   -> suggested_capability es lista y confidence=="HIGH"                     (D-03b, D-07)
T5 artifact_catalog(action="query", intent="monitorear sockets TCP abiertos", category="network")
   -> execution_count > 0                                                    (D-06)
T6 aep_ctl(domain="ipc", action="status", verbosity="summary") -> sin clave mux.pool (D-05)
T7 playbook_run(action="list", verbosity="summary") -> sin clave envelope     (D-02)
T8 discover(action="capabilities") -> capabilities.crash_forensics.ready==true (D-08)
Responde SOLO un JSON {"commit":..., "results":[...], "passed":N, "failed":M}.
```

Hoy, contra `b2afeb2`, se espera que **T1 pase y que T2–T8 fallen**. Esa es la línea base de regresión.

---

## 5. Hoja de ruta hacia un estado estable (propuesta ONT-38b)

| Orden | Lote | IDs | Riesgo | Modo de pipeline sugerido |
|:-:|---|---|:-:|---|
| 1 | **Harness de verificación**: `scripts/aep-agy-probe.sh`, que envuelve `agy -p` con la batería de la §4 y el gate `passed==8`, y `tests/test_token_budgets.py`, que fija los presupuestos de `t.tok` por tool | — | Bajo | Short |
| 2 | Contrato de respuesta: D-01, D-02, D-03, D-04, D-05 (presupuestos de tokens y proyección) | A/M | Medio: cambia la forma del JSON, así que hay que avisar a chrysalis-bridge | Full |
| 3 | Relevancia: D-06 y D-07 (re-ranking con `ponder` y precarga del embedder) | A/M | Medio | Full |
| 4 | Fiabilidad del sync: D-09 y D-10 (reload verificable y reaping opt-in) | A | Medio: procesos de otros harness | Full |
| 5 | Higiene: D-13 (aislamiento de pruebas de consumidor y limpieza de Pueue y Kanban) | M | Bajo; requiere `apply=True` explícito | Short |
| 6 | Documentación y versión: D-08, D-11, D-12, D-14, D-15, D-16, D-17 | B | Bajo | Short / Documentation |

**Criterio de «estable»:** 153+ tests en verde, la batería `agy` 8/8 en verde, cero instancias STALE después de `aep-sync.sh`, presupuestos de tokens cumplidos y la versión unificada en `pyproject`, `server` y `CHANGELOG`.
