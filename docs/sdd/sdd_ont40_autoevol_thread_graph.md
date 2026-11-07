# SDD ONT-40/41/42: `autoevol`, un grafo de hilos con integridad Merkle para auto-evolución y self-healing

- **Origen del diseño:** el usuario (arquitecto de producto) propone la tool `autoevol`: una red de hilos omnisciente que detecte gaps por omisión y dispare la auto-mejora de AEP.
- **Formalización:** Claude Code (orquestador)
- **Fecha:** 2026-11-06
- **Invariante que cambia:** de 16 a **17 tools**. Es una decisión explícita del usuario: `autoevol` es un dominio meta, no cabe en ninguna tool existente y por eso justifica la tool nueva.

## 0. Principio

> AEP debe auditarse a sí mismo como lo hizo el orquestador en `2026-11-05_aep_mcp_live_audit_and_agy_harness.md`, pero de forma continua, determinista y verificable. **La tool detecta, especifica, valida y promueve. El modelo crea.** Un servidor MCP no razona: la parte creativa (el parche) la escribe el agente llamante, y `autoevol` es el **juez y la compuerta** que garantiza que el parche no rompe el grafo.

## 1. El grafo de hilos (Thread Graph)

### 1.1 Nodos (hilos)

Cada hilo es una unidad con identidad estable y hash de contenido.

| Tipo | Ejemplos | Fuente de extracción (automática) |
|---|---|---|
| `tool` | `discover`, `aep_ctl` | Registro de FastMCP |
| `action` | `aep_ctl:backup.lkg_restore`, `discover:schema` | Tablas de dispatch y `CONTROL_PLANE_SCHEMA` |
| `capability` | `crash_forensics` | `engine/privilege._CAPABILITIES` |
| `function` | `engine.catalog.query` | AST (`ast`, stdlib) |
| `state` | tabla `kanban_tasks`, `/dev/shm/aep_pool` | DDL (`schemas/database.sql`) y escrituras detectadas en el AST |
| `test` | `tests/...::test_x` | Colección de pytest y mapa de cobertura |
| `claim` | afirmación del README o docstring («16 tools», «verbosity compacta») | Anclas de Markdown y docstrings, con patrones numéricos y de contrato |
| `budget` | presupuesto de tokens por tool y acción | `tests/test_token_budgets.py` |

### 1.2 Aristas tipadas

- `consumes` (A → B): dependencia.
- `contract` (A ↔ B a través de un nodo interfaz I): interdependencia válida.
- `writes` / `reads` (función → estado): Bernstein.
- `covers` (test → acción/función).
- `asserts` (claim → acción/tool/budget).
- `routes` (capability → tool/acción).
- `layer` (vertical: estado → engine → tool → cliente).

### 1.3 Integridad Merkle («pico-git» del grafo)

- `h(n) = SHA256(tipo ‖ id ‖ hash_contenido(n) ‖ sort(h(hijos por consumes/contract)))`.
- **Raíz** `R = SHA256(sort(h(n) para n sin padres))`.
- Cualquier cambio en un hilo se propaga hasta R. Es la misma propiedad que da a git su integridad, aplicada al **grafo semántico**, no a los bytes.
- Cada generación del grafo `(R, timestamp, git_commit, code_fingerprint)` se encadena en el ledger SHA-256 existente (`security_audit_log`).
- **No se duplica git.** El código sigue versionado en git y los hilos versionan la *estructura y las promesas*. «Pico-git» es este almacén de generaciones (`threads_gen`, en SQLite), consultable con `log`/`diff`, y **no es una tool aparte**.

## 2. Matemática de la integridad

1. **Clasificación de relaciones** (Topos): se calculan las componentes fuertemente conexas (Tarjan, O(V+E)) sobre `consumes ∪ writes→reads`.
   - SCC de tamaño 1: **dependencia**.
   - SCC con ciclo mediado por un nodo `contract`/interfaz: **interdependencia**.
   - SCC con ciclo sin interfaz: **co-dependencia**, que BLOQUEA.
   - Reutiliza `engine/topos_guard.py`.
2. **Bernstein (traza horizontal):** dos funciones del mismo nivel con `W(a) ∩ (R(b) ∪ W(b)) ≠ ∅` sin `contract` común producen un hazard (WARN).
3. **Omisión como completitud:** cada tipo t declara su conjunto requerido de aristas salientes `Req(t)`. Por ejemplo, `action` requiere `{implemented_by, covers⁻¹, asserts⁻¹ (documentada), routes⁻¹ (descubrible), privileged_by (tier)}`. Para cada nodo n: `Gap(n) = Req(tipo(n)) \ tipos(E_out(n))`. Una **omisión es una arista faltante**, y eso es computable.
4. **Drift (declarado vs observado):** `D = G_declarado △ G_observado` (diferencia simétrica entre lo que afirman los `claim` y lo que miden el AST, los tests, la telemetría y el ledger de uso). Por ejemplo, el claim «verbosity summary compacta» frente a un `budget` medido de 18 k da drift. **Así se habrían detectado automáticamente D-01 a D-17.**
5. **Priorización:** `score(gap) = severidad × centralidad(n) × |alcance(n)|`.
   - La centralidad se calcula con PageRank sobre `consumes`.
   - El alcance es el cierre transitivo inverso (blast radius). Primero se arregla el gap que más carga soporta.
6. **Prevención de la cascada de gaps (X1 → X2), garantía formal:** un parche P se acepta solo si:
   - `Gaps(G') ⊊ Gaps(G)`: monótono, el conjunto de gaps es estrictamente menor y **no aparece ninguno nuevo**;
   - `SCC_codep(G') = ∅`;
   - tests verdes;
   - presupuestos cumplidos.

   Si arreglar X1 crea X2, entonces `X2 ∉ Gaps(G)` y P se rechaza solo, sin intervención humana.

## 3. La tool `autoevol` (polimórfica, 17.ª tool)

| action | Qué hace | Tier mínimo |
|---|---|---|
| `graph` | Extrae o actualiza el grafo; devuelve R, conteos y SCCs (resumen en terse) | 4r-- |
| `gaps` | Gaps de omisión y drift, rankeados por score, con `select_fields` | 4r-- |
| `thread` | Inspecciona un hilo: aristas, alcance, centralidad y hash (también para crear o conectar el hilo de una función nueva) | 4r-- |
| `spec` | Para un gap: genera la mini-SDD (RE as SDD: Specify → Plan → Tasks → Validate) con los archivos y las pruebas de aceptación | 4r-- |
| `verify` | Evalúa el working tree actual frente a la generación base (monotonía de gaps, SCC, tests vía `sandbox_run`, presupuestos) y da ACCEPT o REJECT con el diff de gaps | 5r-x |
| `heal` | Self-healing (ONT-41): localiza los hilos rotos (diff contra LKG), da su alcance, el diff y el parche sugerido; con `apply=True`, `lkg_restore` **solo de los archivos de esos hilos**, con snapshot previo | 6rw- |
| `evolve` | Ciclo completo: `gaps → spec → (el agente parchea) → verify → promote` (hot-swap gate más registro de la generación y el commit según el tier) | 6rw- |
| `log` / `diff` | Historial de generaciones del grafo (pico-git) y diff semántico entre dos R | 4r-- |

**Creación de hilos nuevos** (la dificultad que señalas): **no depende de la memoria del modelo**. La extracción es automática (AST, pytest, anclas Markdown, `CONTROL_PLANE_SCHEMA`). Al escribir una función o acción nueva, el siguiente `graph` la detecta como nodo con `Gap = Req(t)` completo, es decir, *nace como gap*. El protocolo obliga a conectarla (test, doc, routing, tier) antes de promoverla. Lo único que el modelo aporta es la **semántica**: nombre, intención y contrato. `autoevol(spec)` propone un nombre canónico consistente con el vocabulario del grafo, usando los tokens de `matcher.py`.

## 4. Gobierno por tier y auto-commit

| Tier | Alcance |
|---|---|
| `7rwx` etiqueta `FULL` + remoto | `evolve` completo: commit en `autoevol/<ciclo>`, gate final (§9), ff-merge a `dev` y push de `dev` y `autoevol/<ciclo>` |
| `6rw-` / `DIMINISHED` | Solo commit local en `autoevol/<ciclo>`: sin ff-merge ni push |
| `5r-x` | `graph`, `gaps`, `spec`, `verify`. Los parches se proponen sin escribir en el árbol; `evolve` solo planifica |
| `4r--` | Solo lectura: `graph`, `gaps`, `thread`, `log`; `evolve` solo planifica |

Disparadores automáticos (sin bucle desbocado):
- Tras cada hot-swap promovido, el front marca `graph_dirty`.
- `discover(capabilities, terse)` expone `autoevol: {root, gaps_open, top_gap}`.
- `evolve` nunca se encadena a sí mismo: un ciclo por invocación y un máximo de N ciclos por sesión (`AEP_AUTOEVOL_MAX_CYCLES=3`, persistido en el ledger SQLite con ventana móvil de 24 h por DB; entero >= 1, inválido => 3), igual que el límite de 3 ciclos del pipeline.

## 5. Fases

| Fase | Contenido | Riesgo |
|---|---|---|
| **ONT-40** | `engine/threads.py` (extractores, Merkle, Tarjan/Bernstein, `Req(t)`, drift, ranking) y `autoevol(graph\|gaps\|thread\|log\|diff)`, en solo lectura | Bajo |
| **ONT-41** | `spec`, `verify` (gate de monotonía) y `heal` (LKG por hilo; integra el diseño de self-healing N0–N3) | Medio |
| **ONT-42** | `evolve` con auto-commit por tier y el disparador post-swap | Alto (auto-mutación), gateado |

## 6. Aceptación de ONT-40 (prueba de que «ve» la realidad)

1. Corrido sobre el commit `b2afeb2` (pre-L1), `gaps` debe redescubrir automáticamente al menos estos del informe manual: D-01 (claim de verbosity frente al budget), D-08, D-11 (claims numéricos de los docstrings frente al recuento real), D-12 (versión de pyproject frente a la del server) y D-14.
2. Corrido sobre el HEAD actual, esos gaps no aparecen (ya están cerrados) y se reportan los abiertos de D-01 a D-07 (xfail).
3. Un `SyntaxError` o una función nueva sin test aparece como gap con el alcance correcto.
4. R es determinista (dos extracciones del mismo árbol dan la misma R) y cambia ante cualquier cambio semántico.
5. `graph` en terse cuesta menos de 300 tokens y la extracción completa tarda menos de 2 s.

## 7. Decisiones (2026-11-06, después del plan de Archon)

| ID | Decisión | Quién |
|---|---|---|
| DQ-1 | §6.2 se corrige así: en HEAD, D-08, D-11, D-12 y D-14 **ausentes** y D-01 **presente** (sigue abierto hasta L3, es xfail strict) | Orquestador |
| DQ-2 | Se aprueba la capa `probes` (`probe=True`): subproceso `python -I` en el árbol destino, timeout de 10 s, solo lectura y BD temporal. Sus observaciones quedan **fuera de R** con su propio `obs_hash`, para no romper el determinismo | Orquestador |
| DQ-3 | `threads_gen` y el ledger se persisten solo con tier ≥ `6rw-`. En `4r--` se devuelve R con `persisted:false` | Orquestador |
| DQ-4 | `autoevol` se integra en la capacidad `topos_audit` (integridad estructural). Se mantienen **19 capacidades** y 17 tools | Orquestador |
| DQ-5 | Marcador histórico explícito `(histórico)`, `(historical)` o `<!-- aep:hist -->`. El CHANGELOG queda excluido de los claims | Orquestador |
| AP-1 | **Auto-push autorizado por el usuario, restringido (ONT-42c).** Solo con etiqueta `FULL` (7rwx), remoto alcanzable, `verify` = ACCEPT, gate final verde y `stale == false`. `6rw-`/`DIMINISHED` hace commit local y nunca ff-merge ni push. Se empuja `autoevol/<gap>` y el ff de `dev`. **Nunca** `--force`, nunca `main`, nunca reescribir historia. Un push rechazado se reporta (`BLOCKED_GIT`) y no se reintenta | Usuario |

**Premisa (usuario):** solo un agente que puede evaluarse a sí mismo puede evolucionar una herramienta que a su vez lo evoluciona. La consola es una limitación; el agente usa la capacidad de mayor alcance disponible.

## 8. Ciclo fix → test en tiempo real (aprovecha el Live Plane)

Como el reload es en vivo (ONT-39), el ciclo de corrección no reinicia nada:

1. **Selección de tests por el grafo:** `impacted_tests(Δ) = covers⁻¹(alcance(nodos_cambiados))`. Solo se ejecutan los tests que cubren los hilos alcanzados por el cambio; la suite completa queda para la compuerta final.
   - **ONT-40:** `thread` y `diff` ya devuelven `impacted_tests` (solo lectura).
2. **Barrera de recarga (obligatoria antes de probar):** tras el parche, esperar a que `backend_generation` se incremente y a que `code_fingerprint_loaded == code_fingerprint_disk` (con timeout). Si hay `last_reload_error` de tipo determinista, el test **no se ejecuta**: el fix falló en la importación, y eso se devuelve como resultado del ciclo. Así nunca se prueba código viejo.
3. **Ejecución:** los tests seleccionados corren vía `sandbox_run(parse="pytest")`, o `async_job_dispatch` si tardan más de 60 s. Las tools en vivo se prueban contra el backend recién promovido.
4. **Veredicto incremental:** `Gaps(G') ⊊ Gaps(G)` más los tests seleccionados en verde dan `fix_ok`; si no, se hace rollback por hilo (LKG) y se devuelve el diff.
   - **ONT-41:** `autoevol(action="fix_test", gap=..)` orquesta los pasos 1 a 4, con un máximo de 3 iteraciones por gap.

## 9. `evolve` (ONT-42c)

Máquina de estados re-entrante: `PLAN -> PATCH_AWAITED -> JUDGED(ACCEPT) -> COMMITTED -> (gate) -> MERGED -> PUSHED`; `BLOCKED_GIT` y `REVERTED` son laterales. Git es la verdad; el ledger es el índice y se reconcilia en cada reentrada.

- **Precondición (C7):** `Gaps(G') ⊊ Gaps(G)` recomputado sobre el árbol juzgado antes del commit; un gap nuevo (`NEW_GAPS`), una co-dependencia o la ausencia de progreso estricto dan `REJECT` sin commit. `R_before` (raíz de la base) y `R_after` (raíz del árbol parcheado) se registran en el ledger y en `evolve.committed`.
- **Gate final (C4):** suite completa en lotes re-entrantes de `sandbox_run` (<= 100 s, mismo intérprete y centinela `WRONG_TREE` que el juez) sobre el árbol *commiteado* exportado a un temporal (`tree == judged_tree`). Progreso `gate i/n`, `awaiting:"gate"`. Rojo, `ran < selected` o `unsandboxed` = `REJECT gate_failed`; sandbox caído = `REJECT sandbox_unavailable` (reintentable). Nunca sin sandbox.
- **Ledger (C5):** `evolve_keys` UNIQUE `(gap_canonical, base_R, tree_hash)` con `INSERT OR IGNORE` y `evolve_events` (`evolve.committed|gate|merged|reverted|pushed|blocked`). Misma clave desde otro ciclo = devuelve el estado existente, sin commit. Sin ledger no hay commit.
- **Rollback (C6):** solo si el verify post-merge falla tras el ff y antes del push: `git revert` como commit nuevo dentro del fence (O_EXCL, `finally`), sin push. Estado `REVERTED` y `BLOCKED_GIT dev_dirty_by_revert` (también para el push de otros ciclos) hasta decisión del usuario. Nunca reset/rebase/amend; `dev` adelantado = `BLOCKED_GIT dev_ahead`.
- **E1 (M-1):** la exigencia de cobertura directa aplica a gaps `drift`/`open_discrepancy` o parches que tocan código público.
