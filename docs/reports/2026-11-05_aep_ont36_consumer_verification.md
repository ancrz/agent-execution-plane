# AEP ONT-36: verificación desde consumidor (chrysalis-bridge)

- **Fecha:** 2026-11-05
- **Consumidor:** chrysalis-bridge (laboratorio LLM local, Gemma 4 E4B con Vulkan en una Radeon 780M)
- **AEP verificado:** `c04f838` (ONT-36: dominio hardware, admisión de aceleradores, alertas apport)
- **Host:** Ryzen 9 8945HS, iGPU 780M con UMA (1 GiB de VRAM carve-out y 15179 MiB de GTT), Ubuntu 26.04.1, kernel 7.0

## 1. Resultado por capacidad

| Capacidad | Llamada | Resultado | Veredicto |
|-----------|---------|-----------|-----------|
| Inventario de aceleradores (GAP-CP-05) | `aep_ctl(domain="hardware", action="accelerators")` | card1 AMD: VRAM 1024/454 libres, GTT 15179/15053 libres. 120 tok. | ✅ Cerrado |
| Admisión con 1 argumento | `admit name="card1" args=["6144"]` | REJECTED `insufficient_vram` (454 libres), aunque `gtt_available_mib` era 10957 | ⚠️ Ver GAP-DX-06 |
| Admisión con 2 argumentos | `admit name="card1" args=["0","6144"]` | OK `req_gtt_mib=6144`, margen 4096. 0.43 ms. | ✅ Funciona |
| Nombre de dispositivo erróneo | `admit name="6144"` | `device_6144_not_found` | ✅ Correcto, pero confuso (GAP-DX-06) |
| Alertas apport (GAP-OM-20) | `diagnose_system_crashes(action="alerts")` | Detecta 2 crashes: antigravity del 2026-10-31 y gnome-shell del 2026-11-04. Usa el sobre plano con `t`. | ✅ Mayormente cerrado; el parseo está incompleto (GAP-OM-21) |
| Sello de versión (GAP-RT-04) | `discover` | `loaded_commit`/`repo_head`/`stale` presentes | ✅ (ya verificado en ONT-35) |

## 2. Gaps nuevos

### GAP-DX-06: la semántica posicional de `hardware.admit` no se puede descubrir y no tiene en cuenta UMA

- **Observado:**
  - `name` es el dispositivo y `args` es una lista posicional `[req_vram_mib, req_gtt_mib]`. Ni el schema ni el error lo indican.
  - Con un solo argumento, la petición se carga entera a VRAM. En una iGPU con UMA, la VRAM es un carve-out de 1 GiB y la memoria útil real es GTT, así que la llamada intuitiva (`args=["6144"]`) se rechaza aunque haya 10.9 GiB disponibles.
  - Un agente que solo lea el rechazo concluiría que «no cabe», lo cual es falso.
- **Impacto:** se toma una decisión de admisión errónea en el caso exacto que motivó ONT-36: el incidente gnome-shell/GTT del 2026-11-04 ocurrió en esta misma iGPU.
- **Propuesta:**
  1. Usar parámetros nombrados: `params={"vram_mib": .., "gtt_mib": ..}`.
  2. Detectar UMA cuando `vram_total ≤ 2 GiB` y `gtt_total ≫ vram_total`, o con el flag de la APU. En ese caso, cargar la petición sin calificar a GTT, o rechazarla con `next_action` explicando que debe pasarse `gtt_mib`.
  3. `aep_ctl(action="schema")` debe listar la firma de `hardware.admit`.
- **Pruebas de aceptación:**
  - Un sysfs falso con UMA (1024 de VRAM y 15179 de GTT) y una petición de 6144 sin calificar da `admit=true` con la petición cargada a GTT.
  - En una dGPU (16384 de VRAM y 8192 de GTT) da `req_vram_mib=6144`.
  - El rechazo por VRAM en un host UMA incluye `next_action` que menciona `gtt_mib`.
  - El schema contiene la firma de `admit`.

### GAP-OM-21: las alertas apport no parsean `Signal`, `ProcCmdline` ni `Pid`

- **Observado:** las entradas devuelven `signal: "UNKNOWN"`, `pid: null` y `cmdline: null`, aunque los `.crash` de `/var/crash` contienen `Signal: 6`, `ProcCmdline:` y `Pid:` (formato RFC822 de apport; los campos base64 solo afectan a `CoreDump`).
- **Impacto:** el triage pierde precisamente el dato que distingue un SIGABRT (6, aserción/OOM del driver, como en el caso gnome-shell) de un SIGSEGV (11).
- **Propuesta:**
  - Parsear las cabeceras `Key: value` hasta la primera clave multilínea o base64.
  - Leer solo el prefijo del archivo (los `.crash` pueden pesar cientos de MB), por ejemplo los primeros 64 KiB.
  - Mapear el número de señal a su nombre (`6 → SIGABRT`).
- **Pruebas de aceptación:**
  - Un fixture `.crash` con `Signal: 6`, `Pid: 1234` y `ProcCmdline: /usr/bin/gnome-shell` produce `signal="SIGABRT"`, `pid=1234` y `cmdline` poblado.
  - Un fixture de 200 MB se procesa leyendo ≤ 64 KiB.

### GAP-DX-07 — `sandbox_run(parse="pytest")`: conteos incompletos y estado no contrastado con el resumen

- **Conteos incompletos:** el parser devuelve passed, failed, errors y skipped, pero omite `deselected`, `xfailed` y `xpassed`.
  - En chrysalis la suite por defecto deselecciona 6 tests (bench/llm), y Dokimos añadió un `xfail(strict=True)` como centinela de defecto.
  - Ninguno de los dos aparece en el sobre, así que un agente no puede distinguir «415 passed» de «415 passed, 1 xfailed, 6 deselected».
- **Estado basado solo en el exit code:** un Pragma ejecutó `pytest -x … | tail`. El pipe enmascaró el exit code (0) aunque el resumen decía `1 failed`.
  - Con `parse="pytest"`, el estado debería contrastarse con la línea de resumen. Si `failed > 0` o `errors > 0` y `rc == 0`, debería emitir `status=FAILED` y una advertencia `exit_code_masked`, o al menos un `next_action` que recomiende quitar el pipe.
  - Falta confirmar qué `parse` usó esa llamada concreta. La regla de contraste no depende de ello.
- **Pruebas de aceptación:**
  - Un fixture con `1 passed, 1 xfailed, 2 deselected` devuelve los cinco conteos.
  - El comando `sh -c 'pytest … ; true'` con un test fallido devuelve `status != OK`.

**Menores (sin ID, Dokimos T10):**
- **(a) `stdout_tail` repetido:** `sandbox_run(verbosity="brief")` sobre un script que lanza un subproceso repite la misma salida varias veces en `stdout_tail`. Probablemente se duplica la captura de stdout padre/hijo. Hay que deduplicar o capturar una sola vez.
- **(b) Sin cobertura:** `parse="pytest"` no extrae la línea de cobertura (`TOTAL … %`) cuando `pytest-cov` está activo.
- **(c) Ejecutar un script del scratchpad del agente exige `ro_paths` en cada llamada.** Se propone que `discover` anuncie un alias de «scratch» montado en solo lectura, o un parámetro `script=<path>` que monte su directorio en RO.

**Menor (sin ID):** no hay forma en una sola llamada de ejecutar pytest contra dos árboles (antes/después) para verificar una migración. Dokimos recurrió a Bash/Python. Es candidato a una receta de `playbook_run`, no necesariamente a una herramienta nueva.

## 3. Métricas de uso de AEP en esta iteración (chrysalis T10/T11)

| Agente | Herramienta | Llamadas | ms (tok) |
|--------|-------------|----------|----------|
| Pragma T11 | `sandbox_run` pytest | 5 | 717 (422), 24486 (631), 25722 (669), 2341 (1372, detail), 26299 (85) |
| Pragma T10 | `sandbox_run` pytest/ruff | 5 | 34239 (524), 24545 (456), 24015 (85); ruff 25 (360), 17 (80) |
| Dokimos T11 | `sandbox_run` pytest | 1 | 25370 (85) |

Observación: un run brief en verde cuesta ~85 tok, frente a 420–670 tok cuando hay fallos y 1372 tok con `detail`. La verbosidad graduada funciona; el coste se concentra en las iteraciones rojas, que es lo esperable.

### Herramientas del orquestador

| Herramienta | Llamadas | Tokens aprox. por respuesta | Latencia | Payload útil |
|-------------|----------|-----------------------------|----------|--------------|
| `topos_audit_dag` (11 nodos, `resources`) | 1 | ~150 | <5 ms | Alto: aprobó el plan de dos tracks con conjuntos de escritura disjuntos |
| `aep_ctl hardware accelerators` | 1 | 120 | <1 ms | Alto |
| `aep_ctl hardware admit` | 3 (2 por prueba y error) | 120 | 0.43 ms | Medio: 2 de las 3 llamadas se perdieron por GAP-DX-06 |
| `diagnose_system_crashes alerts` | 1 | ~250 | — | Medio: falta la señal (GAP-OM-21) |

**Coste del descubrimiento:** 2 de las 6 llamadas de esta iteración fueron prueba y error por una semántica que no se podía descubrir. Ese es el ahorro directo si se cierra GAP-DX-06.

## 4. Nota de diseño compartida (para AEP)

Chrysalis implementa una **matriz de advertencias por modelo** (T10), inspirada en `engine/privilege.py::detect_chmod_tier`. La precedencia es:

1. env forzado;
2. auto-declaración (`handshake`);
3. sondas medidas (`calibrate`).

El resultado es un nivel `recommended|neutral|discouraged|experimental` por acción. AEP podría aplicar el mismo patrón a su manifiesto de capacidades: además de anunciar el *tier de privilegio*, anunciaría el *ajuste por agente*. Por ejemplo, desaconsejaría `kernel_trace` para agentes que nunca consumen su salida, según la telemetría de uso por `agent_id`. Es una propuesta, no un gap.
