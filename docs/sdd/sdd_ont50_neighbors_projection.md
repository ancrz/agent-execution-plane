# SDD: Descubrimiento de vecinos LAN, proyección única y fricciones ronda 4 (ONT-50)

- **Registro**: `docs/pipeline/feature_20261114_ont50_neighbors_projection.md`
- **Estado**: VERIFIED (Dokimos), publicado en dev. Base `dev` `4f6aaf0`; commits `36c36dc`, `d058642`, `5c9b934`, `296b8b7`, `ab4ab3b`, `d0433e6`, `5ebc80f` (y `9b12da5` de docs).
- **Principio**: contratos aditivos. Los modos `detail` no cambian de forma, salvo los campos que se indican. Los budgets no suben. `truncated` implica `cursor`. Ningún test emite tráfico de red real.

## 1. `aep_ctl(domain="network", action="neighbors")` (G21)

### 1.1 Parámetros

Se pasan por los campos existentes de `aep_ctl`; no hay parámetros nuevos en la firma:

| Campo | Uso |
|-------|-----|
| `name` | Interfaz opcional (p. ej. `wlp4s0`). `target` se acepta como alias. |
| `args` | Lista o cadena separada por comas con `sweep`, `nosweep`, `probe` y `timeout=<ms>` (por defecto 800). |
| `limit` / `cursor` | Paginado del sobre. `truncated` implica `cursor`. |

Reglas: `sweep` solo con tier >= 6rw-; prefijos de /22 o más estrechos; `probe` como máximo sobre 16 vecinos.

### 1.2 Algoritmo (`engine/net_telemetry.py`, `discover_neighbors`)

1. Interfaces UP con IPv4 y prefijos `scope link` de la tabla de rutas. Se ignoran `lo`, `utun*`, `tun*`, `wg*`, `docker*`, `br-*` y `veth*` salvo que se pidan por `name`. Prefijos más anchos que /22 (1024 hosts) van a `skipped_prefixes` con razón.
2. Barrido (solo si tier >= 6rw- y sin `nosweep`):
   - **Primario**: `connect_ex` no bloqueante a TCP/80 por host, cerrado de inmediato. El SYN que sale del host hace que el kernel resuelva ARP. Lotes de 256 (`NEIGHBOR_SWEEP_BATCH`).
   - **Fallback**: UDP/9 solo si todo el primer lote devuelve `EPERM` o `EACCES`.
   - Espera `timeout_ms` para que el kernel pueble ARP. Sin ICMP raw ni privilegios.
   - En tier < 6: `sweep: false`, `reason: "tier < 6rw-"`, solo lectura pasiva.
3. Relectura de `/proc/net/arp`: solo filas con `flags != 0x0` y MAC distinta de `00:00:00:00:00:00`. Cada vecino es `{ip, mac, iface, source: "arp", oui}`, donde `oui` son los tres primeros bytes en mayúsculas (sin tabla de fabricantes).
4. Egress: si un barrido de >= 16 hosts (`NEIGHBOR_EGRESS_MIN_SWEPT`) deja <= 1 vecino y ninguna fila ARP nueva (ni `INCOMPLETE`) frente a la lectura previa, se emite `egress_blocked_suspected: true` y una nota en `limits`. Es heurística, no prueba de causa.
5. `probe=True`: `probe_tcp_ports` sobre los vecinos, máximo 16 (`NEIGHBOR_PROBE_MAX`). El resto cuenta en `probe_skipped`.

### 1.3 Salida

- **Compacta (por defecto)**: `{status, iface, prefixes, swept_hosts, sweep, sweep_method, neighbors, count, duration_ms, limits}`, más `egress_blocked_suspected` cuando aplica y `skipped_prefixes` si hay. Cada vecino conserva solo `ip`, `mac` e `iface`.
- **Detail**: añade `arp_raw_count`, `sweep_errors` (separado por método), `probe_skipped` y `probe` por vecino.
- `sweep_method`: `tcp_syn`, `udp` o `none`.
- `neighbors` se ordena por IP y se pagina por `limit`/`cursor`.

### 1.4 Matriz de degradación y routing

| Tier | Comportamiento |
|------|----------------|
| 7rwx / 6rw- | barrido por TCP SYN (fallback UDP/9) y lectura pasiva de ARP |
| 5r-x / 4r-- | solo lectura pasiva de ARP (`sweep: false`) |

- `SCHEMA["network"]["actions"]` incluye `neighbors`, con `required_fs: ["/proc/net/arp", "/proc/net/route"]`, `privilege_tier: DIMINISHED`, `fail_soft_behavior: DEGRADED`.
- `discover("find hosts on my LAN")` enruta con confianza HIGH a `aep_ctl network neighbors`; las palabras clave viven en `engine/privilege.py`.
- `scripts/aep-ctl network neighbors [iface] [sweep|nosweep,probe,timeout=<ms>]`, sin red en los tests.

## 2. Proyección única en `playbook_run` compacto (G18)

- `project_fields(data, select_fields, *, single_projection=False)` en `engine/ipc_pool.py`.
- Con `single_projection=True` (verbosity `summary`, `brief` o `terse`), un valor resuelto por el fallback inteligente de `output` se emite **una vez** en el nivel superior. No se escribe el espejo `output.<path>`.
- `return_only=all` omite también `results` cuando la proyección ya lo cubre.
- `token_savings_estimate` se recalcula sobre lo emitido.
- `detail` conserva `output` y la proyección.
- **Cambio de contrato**: en compacto, `output.<clave>` deja de existir para las claves proyectadas. Quien lea `output` en compacto debe leer el nivel superior o pedir `verbosity="detail"`.
- **Tests adaptados** en `tests/test_spec_om7_ipc_batch.py`: `om22_1_smart_projection_fallbacks`, `pico_ansible_saved_playbook_multi_agent_isolation_and_piping`, `om15_batch_discover_and_cache_piping`. Leen la clave en el nivel superior y afirman la ausencia de `output`. El test nuevo `tests/test_ont50_projection.py` cubre compacto sin `output` duplicado y `detail` con ambos.

## 3. Severidad INFO para `NOOP`, `DRY_RUN` y `SKIPPED` (G31)

- `engine/telemetry.py`: `NOOP` y `SKIPPED` entran en la lista de estados no-error. `_NEUTRAL_NEXT_ACTION_STATUSES = {NOOP, DRY_RUN, SKIPPED}` fija el `next_action` neutro: `"Nothing to do; adjust filters or apply=true."`.
- Severidad INFO en `attach_envelope`.
- `NOT_FOUND` ya era WARN y no cambia.
- **Cambio de contrato**: quien filtre por WARN deja de ver estos estados.

## 4. `async_job_dispatch(status)` terse plegado (G32)

- Modo `terse`: misma fila que `summary`, `{id, label, command[:80], group, status}`.
- `groups` se omite salvo que algún grupo no esté `Running`.
- **Cambio de forma en terse**: sin `groups` cuando todos están `Running`.
- Test de presupuesto en `tests/test_ont50_pueue_terse.py`.

## 5. Verificación

- Suite completa: **1266 passed**, baseline 1235 (**+31 casos** en `tests/test_ont50_*.py`: 29 funciones, una parametrizada en 3 estados). Un flake de carga en `test_cold_extraction` (ONT-46) pasa aislado.
- `ruff`: limpio (282 archivos). Budgets sin diff. `GAPS_BASELINE` 1; `own_gaps` `[]`.
- Tests del contrato neighbors: monkeypatch de `parse_proc_net_arp`, rutas, `inspect` y sockets. Prefijo /24 sintético, tier 4 con `sweep: false`, prefijo /16 a `skipped_prefixes`, `probe` limitado a 16, orden y cursor, schema con `neighbors`, CLI con `nosweep` sin red.
- Medidas en vivo (tier 7rwx, host real): 254 hosts barridos, 1 vecino, 804 ms; `nosweep` 0,2 ms; `egress_blocked_suspected: true` por VPN con kill-switch (ver §6).

## 6. Limitación: VPN con kill-switch

El host de medición tiene VPN con kill-switch (tabla `inet windscribe`) que bloquea el egress a la LAN. El barrido sale, pero no aparecen vecinos. La heurística `egress_blocked_suspected` lo señala. La atribución a la VPN es un diagnóstico del orquestador, sin aislamiento causal comprobado.

## 7. Fuera de alcance

- ARP crudo por `AF_PACKET` (requiere privilegios).
- Tabla OUI de fabricantes (solo se entregan los tres bytes en `oui`).
- Escucha pasiva de mDNS (5353), SSDP (1900) o similares; no se abren sockets de escucha ni multicast.
