# Feature Chain Rollup: Pipeline Milestone History (Documents 1–16)

- **Document ID**: `feature_rollup.md`
- **Rollup Period**: 2026-10-23T04:41:56Z — 2026-10-30T19:30:00Z
- **Trigger**: Consolidated Pipeline Rollup Across Documents 1 to 24 (Autonomous Zero-Dependency Setup & Updater, Python 3.14 Production LTS Migration & Complete Tooling Self-Provisioning Complete)
- **Current Active Document**: [`feature_20261116_ont68_aep_findings.md`](feature_20261116_ont68_aep_findings.md)
- **Author**: Graphos (Universal State Manager & Knowledge Graph Custodian)

---

## Cadena nueva 66..70: ONT-66 (2026-11-15)

Cadena: `feature_20261115_ont65_zero_gaps.md` (último documento del rollup 61..65) → `feature_20261115_ont66_noisy_notices.md` (primero de la cadena 66..70).

| Documento | Intent | Commits (rango) | Veredicto | Suite | Gaps al cierre |
|---|---|---|---|---|---|
| ONT-66 | AEP ruidoso: `aep_notice` en todas las respuestas, `autoevol` `notices`/`ack`, análisis caliente, push MCP `aep.notice`, `ask_user` para reenviar | `7129048`..`5c93d12` (base `69b1b76`) | VERIFIED tras dos ciclos (ciclo 1 LOGIC_ERROR: presupuesto terse 414 > 400, literal de conteo, `_INSTRUCTIONS` 9465 > 9400, prueba vacua y bug de `cached_analysis`) | 1700 passed, 0 failed (reportado por Dokimos) | 0 |
| ONT-67 | uso de RAM medido: memfd sellado, descarga del embedder, caché sin AST, zstd en tmpfs y línea Memory | `47b1c14`..`e2f1e19` (base `2317d8d`) | VERIFIED en un ciclo | 1740 passed, 0 failed | 0 |
| ONT-68 | hallazgos reportados por AEP: caché ELF con hash de catálogo (T1, falso positivo corregido), `KEEP_EMBED_IDLE` reaplicado (T2, bug real) y extracción en frío robusta a carga (T3) | sin commit al cierre; base `dev` `c4345e8` | VERIFIED tras dos ciclos (ciclo 1 LOGIC_ERROR solo en tests: 3 tests sin `covers` de bordes, 3 gaps y 7 fallos) | 1751 passed, 0 failed (serie) | 0 |

**Ciclos de Dokimos por track:** ONT-66 2, ONT-67 1, ONT-68 2. Publicado en `dev` por Hermon; `main` a decisión del usuario.

## Rollup de cadena: ONT-61 a ONT-65 (2026-11-15)

Cadena: `feature_20261114_ont60_sandbox_packages.md` (último documento del rollup 7) → `feature_20261114_ont61_db_isolation.md` (primero) → `feature_20261115_ont62_health_and_update.md` → `feature_20261115_ont63_orientation_layer.md` → `feature_20261115_ont64_path_trim_and_doc_gate.md` → `feature_20261115_ont65_zero_gaps.md` (**quinto**, dispara este rollup).

Este rollup consolida ONT-61 a ONT-65. La sección "Registro posterior a Rollup 7" se conserva sin cambios.

| Documento | Intent | Commits (rango) | Veredicto | Suite | Gaps al cierre |
|---|---|---|---|---|---|
| ONT-61 | aislamiento de la DB real en la suite (G67: `AEP_DATA_HOME` único y conftest temporal) y fricciones G63–G66 | `8d271f4`..`1120056` (base `8d271f4`, HEAD `1120056`) | VERIFIED tras dos ciclos (ciclo 1 LOGIC_ERROR: om11–om13 usaban la DB real) | 1510 passed, 0 failed; ruff limpio; DB real intacta | G63–G67 cerrados |
| ONT-62 | pendientes menores (logs del front bajo `AEP_DATA_HOME`, `--check` por ruta real, sonda pueue, `scope` y `RUNNING_UNMANAGED`) y G71 de `setup.sh --update` | `67896be`..`da05dd1` (base `a25d4a0`) | VERIFIED tras dos ciclos (ciclo 1 LOGIC_ERROR: ruff reescribió la cabecera políglota de `aep-ctl`) | 1536 passed, 0 failed; ruff limpio | G68–G71 cerrados; `setup.sh --update` real pendiente en el host |
| ONT-63 | capa de orientación básica: ocho primitivas L0 de solo lectura, extensiones de `network probe` y `process_inspect(detail)`, escalera L0→L1→L2, WF-0 | `374f83d`..`98efe5b` (base `df039ee`) | VERIFIED tras tres ciclos; publicado en dev (Hermon, ff) | 1637 passed, 0 failed | sin dato de gaps en el registro de ONT-63; cosmético `aep_python.path` cerrado en ONT-64 |
| ONT-64 | recorte de `aep_python.path` por componente (bytes UTF-8) y puerta `test_ont41_coverage` en pre-commit; cierre del claim de conteo de ONT-63 | `4848735`, `4535d83`, `140a165` (base `fe59411`; HEAD en `fa1c1b9`) | VERIFIED en un ciclo; publicado en dev | 1657 passed, 0 failed | gate8 como baseline (1) |
| ONT-65 | cero gaps: `read_mods` (aristas `covers` débiles por lectura de archivos del proyecto), `GAPS_BASELINE` 0 | `9bb7758`, `7c29bfb`, `535b4b0`, `086dc02` (base `fa1c1b9`, HEAD `086dc02`) | VERIFIED tras dos ciclos (ciclo 1 LOGIC_ERROR: 3 tests con `gaps[0]` y 75 aristas desde fixtures) | 1666 passed, 0 failed | **0** (gate8 cubierto por `read_mods`) |

**Ciclos de Dokimos por track:** ONT-61 2, ONT-62 2, ONT-63 3, ONT-64 1, ONT-65 2.

**Métricas del tramo:**
- Tests: 1510 → 1666 (+156).
- Gaps: 1 → 0 (`GAPS_BASELINE` 1 → 0, sin enmascaramiento: el experimento de 5 funciones no pierde gaps).
- Veredictos: 5 de 5 VERIFIED final; `LOGIC_ERROR` en ciclos intermedios de ONT-61, ONT-62 y ONT-65 (uno cada uno), además de los ciclos intermedios de ONT-63 (tres ciclos en total, registro de ciclos no detallado aquí). Ninguno requirió PLAN_GAP.
- Publicación: ONT-61 a ONT-64 publicados en dev por Hermon (ff). ONT-65 publicado en dev y main por Hermon (ff; main autorizado por el usuario con condición 0 gaps).

**Invariantes que se consolidan en ONT-61 a ONT-65:**
1. La suite y la verificación no escriben en la DB real: cada test siembra su propio `AEP_DATA_HOME` (ONT-61), y el orquestador no opera sobre la base mientras Dokimos verifica (incidente del ciclo 1 de ONT-65).
2. La documentación es entrada de los gates: los `*.md` se leen como afirmaciones de conteo. Un commit de docs posterior a la verificación puede romper el gate (ONT-63 → ONT-64). El hook pre-commit lo impide desde `140a165` (ONT-64).
3. Las primitivas se extienden, no se duplican (regla NO DUPLICAR, ONT-63 y ONT-64).
4. Un cero de gaps solo vale si no está enmascarado: una arista débil resuelve únicamente la omisión del propio test (ONT-65).
5. Los tests no usan gaps reales como material; siembran los suyos (ONT-65, lección 2).
6. Modo Short por defecto; commit y push a `main` solo con autorización explícita del usuario (ONT-65, condicionada a 0 gaps).

**Lecciones agregadas:**
- Un fallo de RCA por documentación (ONT-63) se convierte en gate automático, no en una nota (ONT-64).
- Los tests de cobertura con dependencias de datos reales se rompen cuando el dato cambia de forma legítima (ONT-65). Deben sembrar sus datos.
- Todo cambio de estado en la base real durante una verificación contamina el veredicto (ONT-61 y ONT-65).

**Pendientes que cruzan documentos:**
- ONT-66 ENCOLADO: `aep_notice` ruidoso. AEP debe notificar al agente de turno lo que detecta y permitir que pregunte "AEP reporta x, y o z, ¿quieres mejorarlo?" (plan en `docs/pipeline/plan_ont66_noisy_notices.md`).
- Operativo: `setup.sh --update` real y reconexión del front en el host (ONT-62).
- Publicación de ONT-65 en `dev` y `main`: completada (ff).
- Opcional, sin impacto: truncado de 58 a 60 B en `aep_python.path` (ONT-64).

**Documento activo en la cadena:** [`feature_20261115_ont65_zero_gaps.md`](feature_20261115_ont65_zero_gaps.md) (quinto de la cadena desde el rollup 7; este rollup lo consolida).

**Próximo rollup:** al quinto documento posterior a `feature_20261115_ont65_zero_gaps.md` (0 de 5 al cierre de este documento; ONT-66 es el primero).

---

## Rollup de cadena: ONT-59 (2026-11-14)

Cadena nueva tras el rollup ONT-54 a ONT-58: `feature_20261114_ont58_pending.md` → `feature_20261114_ont59_go_philosophy_kanban.md`.

| Documento | Intent | Commits (rango) | Veredicto | Suite | Gaps al cierre |
|---|---|---|---|---|---|
| ONT-59 | kanban con la filosofía de Go: evidencia ligada a `(source_hash, toolchain)` (K1), fallos de build como valores (K2), gofmt y `go fix` antes de vet (K3), toolchain soportado (T4), canal `stable` de Go en `setup.sh` (T5) | `fa64ad7`..`9ee5d8c` | VERIFIED en un ciclo; publicado en dev y main | 1462 (0 fallos; ruff 318) | K1–K3 y T4–T5 cerrados; G61 y G62 abiertos (menores); G58–G60 siguen en ONT-60 |

---

## Rollup de cadena: ONT-54 a ONT-58 (2026-11-14)

Cadena: `feature_20261114_ont53_ort_synonyms_walk.md` (último documento del rollup anterior) → `ont54_round7` (primero) → `ont55_kanban_work` → `ont56_reclassify_snapshot` → `ont57_severity_table` → `ont58_pending` (**quinto**, dispara este rollup).

Este rollup consolida ONT-54 a ONT-58. La sección anterior (ONT-43 a ONT-53) se conserva sin cambios.

| Documento | Intent | Commits (rango) | Veredicto | Suite | Gaps al cierre |
|-----------|--------|-----------------|-----------|-------|----------------|
| ONT-54 | ronda 7: G43 alertas de crash agrupadas por archivo con paginación `cursor`, G44 `error_class` sin acentos, G45 etiqueta de `visual_inspect` y sha256 completo, G46 `destinations` de tcp_connect con BTF, G47 `next_action` de `playbook_run(create)` | `a482909`..`a7f7aea` | VERIFIED tras PLAN_GAP propio (ciclo 2 sobre copia de la DB real); publicado en dev | 1333 (0 fallos; ruff 296) | G43–G47 cerrados; G40 sigue parcial |
| ONT-55 | tarjetas de trabajo `kind=work` con estados BACKLOG/IN_PROGRESS/BLOCKED/DONE (G49), `advance` sin `to_state` y `PARAM_ERROR` con `valid_states` (G48) | `f6827ae`..`2077426` | VERIFIED en un ciclo; publicado en dev | 1345 (0 fallos; ruff 298) | G48, G49 cerrados |
| ONT-56 | reclasificación `kanban_board(reclassify)` por `task_id` o `title_like` (G50), `next_action` propio y NOOP terminal (G51), `_EXTERNAL_METHODS` congelado (backlog ONT-46) | `f083a92`..`42dbb72` | VERIFIED en un ciclo; publicado en dev | 1359 (0 fallos; ruff 303) | G50, G51 cerrados; backlog ONT-46 `_EXTERNAL_METHODS` resuelto |
| ONT-57 | severidad explícita por estado (G53), DRY_RUN con candidatos (G52), `reclassify` por `task_ids` y hint de reverso por ids (G54) | `13238bc`..`53958b8` | VERIFIED, publicado en dev | 1386 passed + 1 flake de carga (G56); ruff 307 | G52–G54 cerrados; G55 y G56 abiertos |
| ONT-58 | reverso exacto de reclassify con `prev_*` (G55), coste de extracción medido en subproceso limpio (G56), hints de DRY_RUN fuera (G57), defaults `Callable` en `_TypeIndex.resolve` (backlog ONT-46) | `83ed071`..`9942c70` | VERIFIED tras LOGIC_ERROR en T2 (ciclo 1); publicado en dev | 1396 (0 fallos; ruff 311) | G55, G56, G57 y backlog ONT-46 cerrados; K1–K3 (ONT-59) y G58–G60 (ONT-60) abiertos |

Cierre de ONT-58: G55, G56 y G57 cerrados; backlog ONT-46 vacío. G56 se cierra con la causa raíz medida: coste del proceso de la suite, no contención del planificador. Entorno: host Go 1.22.5 → 1.27.4 (`/mnt/apps/tools/go`).

Invariantes que se consolidan en ONT-54 a ONT-58:
1. Las columnas de migración son aditivas, idempotentes y con sentencias `ALTER` literales (ONT-55, ONT-58).
2. Cada estado emitido tiene severidad explícita (`INFO`, `WARN` o `ERROR`); un test impide estados sin clasificar (ONT-57).
3. Un reverso de reclasificación restaura el estado previo exacto cuando la tarjeta lo conserva (`prev_*`, ONT-58); sin `prev_*`, aplica el mapa.
4. Las mediciones de coste de extracción se hacen en subproceso limpio con umbral fijo; la guarda de pared solo detecta cuelgues (ONT-58).
5. Modo Short por defecto; el usuario autoriza commit y push.

Pendientes que cruzan documentos: K1–K3 (ONT-59, kanban con filosofía Go; toolchain soportado planificado en ONT-59: T4 toolchain soportado, T5 canal stable de Go en setup.sh) y G58–G60 (ONT-60, sandbox y chequeo de paquetes). G40 (coste de estado estable) sigue parcial desde ONT-53.

Documento activo en la cadena: [`feature_20261114_ont58_pending.md`](feature_20261114_ont58_pending.md) (quinto de la cadena desde el rollup anterior; este rollup lo consolida).

**Próximo rollup:** al quinto documento posterior a `feature_20261114_ont58_pending.md` (0 de 5 al cierre de este documento).

---

## Rollup de cadena: ONT-43 a ONT-53 (2026-11-14)

Cadena: `feature_20261113_004026_mcp_coverage_reinforcement.md` → `080406_ont45_topos_residue` → `ont46_extractor_precision` → `ont47_dogfood_frictions` → `ont48_dogfood_gaps` (quinto documento, rollup anterior) → `ont49_dogfood_round3` → `ont50_neighbors_projection` → `ont51_discover_supervise` → `ont52_round6` (noveno) → `ont53_ort_synonyms_walk` (**décimo**, dispara este rollup).

Este rollup consolida ONT-43 a ONT-52 según la sección anterior de este mismo archivo, que se conserva sin cambios. Lo nuevo es ONT-53:

| Documento | Intent | Commits (rango) | Veredicto | Suite | Gaps al cierre |
|-----------|--------|-----------------|-----------|-------|----------------|
| ONT-46 | precisión del extractor de hilos, aristas `weak` | `6b05f7b`..`2bd64f9` | VERIFIED, publicado en dev | 1147 | sin gap G |
| ONT-47 | nueve fricciones de dogfooding (T1-T9) | `c455b4b`..`c2f5152` | VERIFIED, publicado en dev | 1174 (1 fallo de carga conocido) | sin gap G |
| ONT-48 | trece gaps de la ronda 2 (G10–G26) | `05b9511`..`66b84d9` | VERIFIED, publicado en dev | 1230 (0 fallos) | G10–G26 cerrados |
| ONT-49 | cuatro fricciones de la ronda 3 (G27–G30) | `d0b436e`..`9b12da5` | VERIFIED | 1235 (0 fallos) | G27 cerrado solo en detección |
| ONT-50 | descubrimiento LAN (G21), proyección única (G18), G31, G32 | `36c36dc`..`dd0ca29` | VERIFIED, publicado en dev | 1266 (flake de carga conocido) | G18, G21, G31, G32 cerrados |
| ONT-51 | `discover` por afinidad (G33), supervisión sin aristas `weak`, hitos (G34) | `a15125c`..`4bf0fea` | VERIFIED, publicado en dev | 1271 (0 fallos) | G33, G34 cerrados |
| ONT-52 | ronda 6: G36–G39, routing de open ports, `_fast_dump` (T6 parcial) | `19494cc`..`cc10757` | VERIFIED tras LOGIC_ERROR cosmético (`eb63fc5`), publicado en dev | 1288 (+17) | G36–G39 cerrados; G40, G41, G42 abiertos |
| ONT-53 | G42 ORT por entorno (cerrado), G41 sinónimos EN+ES (cerrado), G40 recorrido AST único (cierre parcial) | `1630453`..`1a2d6d4` | VERIFIED tras reclasificar ciclo 1 como LOGIC_ERROR; publicado en dev | 1304 (0 fallos; ruff 290) | G41, G42 cerrados; G40 parcial (1,46–1,49 s estable; 1,3 s solo en frío) |
| ONT-54 | ronda 7: G43 alertas de crash agrupadas por archivo con paginación `cursor`, G44 `error_class` sin acentos, G45 etiqueta de `visual_inspect` y sha256 completo, G46 `destinations` de tcp_connect con BTF, G47 `next_action` de `playbook_run(create)` | `a482909`..`a7f7aea` | VERIFIED tras PLAN_GAP propio (ciclo 2 sobre copia de la DB real); publicado en dev | 1333 (0 fallos; ruff 296) | G43–G47 cerrados; G40 sigue parcial |
| ONT-55 | tarjetas de trabajo `kind=work` con estados BACKLOG/IN_PROGRESS/BLOCKED/DONE (G49), `advance` sin `to_state` y `PARAM_ERROR` con `valid_states` (G48) | `f6827ae`..`2077426` | VERIFIED en un ciclo; publicado en dev | 1345 (0 fallos; ruff 298) | G48, G49 cerrados |
| ONT-56 | reclasificación `kanban_board(reclassify)` por `task_id` o `title_like` (G50), `next_action` propio y NOOP terminal (G51), `_EXTERNAL_METHODS` congelado (backlog ONT-46) | `f083a92`..`42dbb72` | VERIFIED en un ciclo; publicado en dev | 1359 (0 fallos; ruff 303) | G50, G51 cerrados; backlog ONT-46 `_EXTERNAL_METHODS` resuelto |
| ONT-57 | severidad explícita por estado (G53), DRY_RUN con candidatos (G52), `reclassify` por `task_ids` y hint de reverso por ids (G54) | `13238bc`..`53958b8` | VERIFIED, publicado en dev | 1386 passed + 1 flake de carga (G56); ruff 307 | G52–G54 cerrados; G55 y G56 abiertos |

Cierre de ONT-55: G48 y G49 cerrados; migración idempotente verificada sobre copia de la base real (317 filas, tablero idéntico).

Cierre de ONT-57: G52, G53 y G54 cerrados; G55 y G56 abiertos (ver `feature_20261114_ont57_severity_table.md`).

Cierre de ONT-56: G50 y G51 cerrados; backlog ONT-46 `_EXTERNAL_METHODS` congelado como literal versionado. Reclasificación sobre copia de la base real: 17 candidatos, tablero y `work_lanes` según lo esperado, segunda aplicación `NOOP`.

Cierre de ONT-54: G43 a G47 cerrados sin gap nuevo; G40 sigue en cierre parcial. Gaps abiertos al cierre de ONT-53: G40 (cierre parcial, coste de estado estable). Backlog ONT-46 sin gap formal: defaults `Callable` en `_TypeIndex.resolve`; `_EXTERNAL_METHODS` por versión de Python.

Invariantes que se consolidan en ONT-53:
1. Ningún recorrido ni caché se guarda en objetos del grafo (`node.__dict__`); el caché de extracción tiene ámbito de análisis y se descarta al salir de `build_graph`. No se usa `gc.collect` como parche.
2. Equivalencia exacta de resultado: `root_hash`, nodos, aristas y gaps idénticos al base (verificado de nuevo por Graphos en solo lectura).
3. La telemetría de onnxruntime se desactiva por entorno antes del import, sin pisar un valor explícito del operador.
4. Una sola tabla de sinónimos de acciones (`engine.privilege.ACTION_SYNONYMS`) para EN y ES.
5. Modo Short por defecto; commit y push autorizados por el usuario, publicado en dev.

Pendientes que cruzan documentos: G40 (coste de estado estable, cierre parcial), backlog ONT-46 (defaults `Callable` en adaptadores; `_EXTERNAL_METHODS` por versión de Python), G27 (cerrado solo en detección), limitación VPN de ONT-50 en este host.

Documento activo en la cadena: [`feature_20261114_ont53_ort_synonyms_walk.md`](feature_20261114_ont53_ort_synonyms_walk.md) (décimo de la cadena; este rollup lo consolida).

**Próximo rollup:** al quinto documento posterior a `feature_20261114_ont53_ort_synonyms_walk.md` (4 de 5 al cierre de `feature_20261114_ont57_severity_table.md`; el siguiente documento dispara el rollup).

---

## Rollup de cadena: ONT-43 a ONT-52 (2026-11-14)

Cadena: `feature_20261113_004026_mcp_coverage_reinforcement.md` → `080406_ont45_topos_residue` → `ont46_extractor_precision` → `ont47_dogfood_frictions` → `ont48_dogfood_gaps` (quinto documento, dispara este rollup).

| Documento | Intent | Veredicto | Tests |
|-----------|--------|-----------|-------|
| 004026 | cobertura MCP (ONT-44) y trinquete de gaps | VERIFIED | 1147 |
| 080406 | residuo Topos (ONT-45), grafo de hilos por criticidad | VERIFIED | 1147 |
| ONT-46 | precisión del extractor de hilos, aristas `weak` | VERIFIED, publicado en dev | 1147 |
| ONT-47 | nueve fricciones de dogfooding (contratos compactos y aditivos) | VERIFIED, publicado en dev | 1174 (1 fallo de carga conocido) |
| ONT-48 | trece gaps de la ronda 2 (G10–G26) | VERIFIED, publicado en dev | 1230 (0 fallos) |
| ONT-49 | cuatro fricciones de la ronda 3 (G27–G30): `history_drop` de pueue, kanban, README | VERIFIED | 1235 (0 fallos) |
| ONT-50 | descubrimiento LAN (`network.neighbors`, G21), proyección única en compactos (G18), NOOP/SKIPPED/DRY_RUN como INFO (G31) y pueue terse (G32) | VERIFIED, publicado en dev | 1266 (flake de carga conocido, pasa aislado) |
| ONT-51 | `discover` recomienda la canonical call por afinidad (G33), `file_units` sin aristas `weak` (backlog ONT-46), hitos publicados fuera de pendiente (G34); extracción en frío: Aclarado por el orquestador: la aserción mide solo la primera extracción (< 2.0 s); los 3,5 s de fase call incluyen la segunda extracción de estabilidad de R. El margen se aborda en ONT-52 T6 (ast.dump ~21 % del tiempo) (margen en ONT-52 T6) | VERIFIED, publicado en dev | 1271 (0 fallos) |
| ONT-52 | ronda 6 de gaps: `firewall_status` veraz (G36), telemetría de onnxruntime (G37, residuo G42), etiqueta `[unreadable]` (G38), builtins en `browse` y `score_reason` (G39), routing de "list open ports" (G41 abierto para la frase en español), `_fast_dump` (T6 parcial, G40 abierto) | VERIFIED tras LOGIC_ERROR cosmético (ruff format, `eb63fc5`); publicado en dev | 1288 (+17; flake de carga conocido) |

Invariantes que se consolidan: `truncated ⇒ cursor` en el sobre; los modos `detail` no cambian de forma salvo indicación explícita; comandos outward-facing sólo con tier 7rwx y `confirm=True`; ninguna generación de grafo de árbol ajeno o sin commit se persiste; los tests no escriben en la base real.

Pendientes que cruzan documentos: T12/G18 (proyección duplicada, omitida por contrato de tests), G21 `network.neighbors` (decisión de diseño del usuario), G27 (cola pueue vaciada sin rastro), y el margen de extracción en frío de ONT-46 (1.5–1.7 s frente a un tope de 2.0 s).

Documento activo en la cadena: [`feature_20261114_ont52_round6.md`](feature_20261114_ont52_round6.md) (noveno de la cadena; el siguiente rollup corresponde al décimo, así que aquí solo consta la fila).

---

## 1. Executive Summary

This rollup breaks recursive token overload across historical pipeline artifacts by consolidating architectural decisions, invariants, and milestone achievements from the pipeline documents into a single dense summary.

```mermaid
flowchart LR
    subgraph RollupChain["Consolidated Pipeline History (Docs 1 to 24)"]
        direction LR
        D1["Doc 1: 044156<br/>(AEP FastMCP Core & Privilege Tiers)"]
        D2["Doc 2: 054100<br/>(sqlite-vec Memory & Crash Forensics)"]
        D3["Doc 3: 125603<br/>(Pico-Playbooks & Discover Router)"]
        D4["Doc 4: 120700<br/>(Template Feedback, Pico Hardening & 33 Tools)"]
        D5["Doc 5: 235900<br/>(Roadmap 33 to 16 Tools & Phase 1 Semantic Memory)"]
        D6["Doc 6: 003200<br/>(Phase 2 Task Management Unification & 23 Tools)"]
        D7["Doc 7: 010200<br/>(Phase 3 Automation Tool Unification & 20 Tools)"]
        D8["Doc 8: 013100<br/>(Phase 4 Artifact Synthesis & 17 Tools)"]
        D9["Doc 9: 015800<br/>(Phase 5 Async Dispatch & FD Hardening: 16 Tools)"]
        D10["Doc 10: 025400<br/>(Phase 6 Crash Forensics & Hardening: 15 Tools)"]
        D11["Doc 11: 034500<br/>(Phase 7 Orientation & Introspection Alignment: 15 Tools Parity)"]
        D12["Doc 12: 102000<br/>(Runtime Hardening, Secret Masking & Full README Sync: 7 Gaps Closed)"]
        D13["Doc 13: 115500<br/>(Memory-Mapped Hybrid SQLite Optimization: PRAGMA mmap_size 256MB)"]
        D14["Doc 14: 171500<br/>(Code Modernization, Ruff SAST, AnyIO & Anti-Deadlock SQLite)"]
        D15["Doc 15: 031500<br/>(5-Slot Hot Backup Engine, Offensive Countermeasures & Multi-Agent Segregation)"]
        D16["Doc 16: 051500<br/>(Autonomous Setup/Updater, Python 3.14 LTS Migration & Self-Provisioning)"]

                D17["Doc 17: 144500<br/>(ONT-13: Landlock LSM, Anti-Poisoning Backups & RAM Micro-Snapshots)"]
        D18["Doc 18: 235800<br/>(ONT-14: Public GitHub Release & Compliance)"]
        D19["Doc 19: 003000<br/>(AEP Agent Experience Evaluation Suite: 39 Passed)"]
        D20["Doc 20: 013500<br/>(ONT-15: Self-Evolutionary Suite & Kali Semantics)"]
        D21["Doc 21: 065200<br/>(ONT-18: Topos Anti-Cascade Battery & Setup Hardening)"]

        D1 --> D2 --> D3 --> D4 --> D5 --> D6 --> D7 --> D8 --> D9 --> D10 --> D11 --> D12 --> D13 --> D14 --> D15 --> D16 --> D17 --> D18 --> D19 --> D20 --> D21 --> D22 --> D23 --> D24 --> D25 --> D26
        D26["Doc 26: 211500<br/>(ONT-24 Verification: 69/69 Tests & 79 Mermaid Lint)"]
        D25["Doc 25: 210000<br/>(ONT-24 Execution: Non-Pico Concurrency & Kali Semantics)"]
        D24["Doc 24: 190000<br/>(ONT-23: Pico-Triad Multi-Agent Concurrency Isolation)"]
        D23["Doc 23: 173000<br/>(ONT-22: Spec OM-7 Omission Gaps & Multi-Agent Cache Piping)"]
        D22["Doc 22: 110500<br/>(ONT-21: Spec OM-7 IPC Socket Pool & Code Batch Mode)"]
    end
```

---

## 2. Document Evolution Matrix

| Doc # | Filename | Primary Scope & Architectural Additions | Resulting Tool Count | Key Invariants Established |
| :---: | :--- | :--- | :---: | :--- |
| **1** | `feature_20261023_044156.md` | Core FastMCP stdio server architecture; bubblewrap sandbox (`sandbox_run`); memfd in-RAM binary execution (`artifact_execute_in_ram`); headless visual inspection (`visual_inspect`); Unix octal privilege tiers (`FULL` / `DIMINISHED`). | 12 | Root is never assumed; escalation is per-tool via `sudo -n`; fail-soft degradation. |
| **2** | `feature_20261023_054100.md` | SQLite vector search with `sqlite-vec`; crash forensics (`diagnose_system_crashes`, `check_crash_alerts`); local man-page semantic store (`query_system_docs`); eBPF tracing (`kernel_trace`). | 18 | Auto-indexing at write-time; local offline man-pages prevent hallucinated CLI flags; crash dumps inspected without root panic. |
| **3** | `feature_20261023_125603_pico_playbooks_and_discovery.md` | Pico-Playbooks execution engine (`playbook_create`, `playbook_run`, `playbook_list`); semantic orientation router (`discover`); bilingual EN/ES lexical matching in `matcher.py`. | 24 | Discover is the primary agent entrypoint; playbooks enforce DAG dispatch with strict step verification; bilingual tags prevent English query misses. |
| **4** | `feature_20261023_120700_template_feedback_and_pico_hardening.md` | Template feedback loop (`source_template` + `proven` blocks); Pico tools hardening (kebab/snake normalization, SQLite blob in-RAM fallback, Pueue `DEGRADED` fail-soft); safe GC with cold-aging immunity; `playbook_prune` (tool 33); closed 5 tool-graph omission gaps. | 33 | 100% of tools mapped to capabilities; single-use successful artifacts immune to cold-aging; playbooks output full intermediate steps; RAM executions auto-canary Kanban tasks (`LINTED` → `CANARY`). |
| **5** | `feature_20261023_235900_phase1_semantic_memory_unification.md` | 7-Phase Tool Consolidation Roadmap (33 → 16 tools); Phase 1 fusion of `semantic_memory` (`artifact_query`, `artifact_catalog`, `artifact_reindex`, `artifact_prune` into polymorphic `artifact_catalog(action=...)`); Kanban Task 95 promoted to `PROMOTED` at `0.8875 TRUST`. | 30 (VERIFIED) | 1 capability fusion per phase; backward-compatible playbook dispatch aliases; zero disruption to underlying SQLite database; Semgrep 0 findings; all 4 actions + error guards validated. |
| **6** | `feature_20261024_003200_phase2_task_management_unification.md` | Phase 2 fusion of `task_management` (8 `kanban_*` tools into polymorphic `kanban_board(action=...)`); Kanban Task 97 promoted to `PROMOTED` at `0.925 TRUST`. | 23 (VERIFIED) | Polymorphic dispatcher covering 8 actions; strict parameter guards (`PARAM_ERROR`); invalid action handling (`INVALID_ACTION`); Semgrep 0 findings across 1,198 rules; 23 FastMCP schemas verified. |
| **7** | `feature_20261024_010200_phase3_automation_unification.md` | Phase 3 fusion of `automation` (4 `playbook_*` tools into polymorphic `playbook_run(action=...)`); non-recursion invariant enforced; Kanban Task 101 promoted to `PROMOTED` at `0.9979 TRUST`. | 20 (VERIFIED) | Polymorphic dispatcher covering 4 actions (`run`, `create`, `list`, `prune`); parameter guards (`PARAM_ERROR`); invalid action handling (`INVALID_ACTION`); recursion attempt triggers `LINT_ERROR`; Semgrep 0 findings; 20 FastMCP schemas verified. |
| **8** | `feature_20261024_013100_phase4_artifact_synthesis_unification.md` | Phase 4 fusion of `artifact_synthesis` (4 tools `template_catalog`, `template_select`, `artifact_hydrate`, `artifact_lint_and_build` into polymorphic `artifact_lint_and_build(action=...)`); 1-Step Template-to-Binary shortcut; Kanban Task 102 promoted to `PROMOTED` at `0.9964 TRUST`. | 17 (VERIFIED) | Polymorphic dispatcher covering 4 actions (`build`, `catalog`, `select`, `hydrate`); 1-step compilation shortcut; parameter guards (`PARAM_ERROR`, `HYDRATE_ERROR`, `INVALID_ACTION`); Semgrep 0 findings; 17 FastMCP schemas verified. |
| **9** | `feature_20261024_015800_phase5_async_dispatch_unification.md` | Phase 5 fusion of `async_dispatch` (2 tools `async_job_dispatch`, `async_job_inspect` into polymorphic `async_job_dispatch(action=...)`); Subprocess/FD Hardening (Gaps A, B, C); Kanban Task 105 promoted to `PROMOTED` at `0.9955 TRUST`. | **16 (VERIFIED)** | Polymorphic dispatcher covering 4 actions (`dispatch`, `inspect`, `status`, `log`); fail-soft `DEGRADED`; `pass_fds=(fd,)` + `timeout=30` in `artifact_execute_in_ram`; detached auto-start in `_ensure_pueue_daemon()`; schema pruning in `aep-sync.sh`; Semgrep 0 findings; 16 FastMCP schemas verified. |
| **10** | `feature_20261024_025400_phase6_crash_forensics_unification.md` | Phase 6 fusion of `crash_forensics` (2 tools `diagnose_system_crashes`, `check_crash_alerts` into polymorphic `diagnose_system_crashes(action="diagnose"|"alerts")`); Subprocess/FD Hardening in `_safe_run` (`stdin=DEVNULL`, `close_fds=True`, `timeout=15`); Kanban Task 106 promoted to `PROMOTED` at `0.8208 TRUST`. | **15 (VERIFIED)** | Polymorphic dispatcher covering actions (`diagnose`, `alerts`) + alias `check`; subprocess isolation with `close_fds=True`, `stdin=DEVNULL`, `timeout=15`; backward-compatible playbook lambda alias; auto-pruning of `check_crash_alerts.json`; Semgrep 0 findings; 15 FastMCP schemas verified. |
| **11** | `feature_20261024_034500_phase7_orientation_and_process_introspection.md` | Complete Tool Consolidation Roadmap (33 → 15 Tools) — Phase 7: Orientation & Process Introspection Alignment. Unify `discover` and `aep_capabilities` into polymorphic `discover(use_case, action="discover"|"capabilities", limit=3)`. Decouple `process_introspection` from `artifact_execute_in_ram` into dedicated `process_inspect(pid=0, limit=100)`. Synchronize `_CAPABILITIES` (16 capabilities) and bilingual `_CAP_KEYWORDS`. Kanban Task 108 promoted to `PROMOTED` at `0.8208 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | 100% 1:1 capability mapping (GAP-CP-01, GAP-CP-02, GAP-CP-03 closed); fail-soft process introspection (`/proc/PID/fd` safe classification into socket/pipe/device/file); zero unhandled exceptions on PID termination or permission denials; backward compatibility in playbook dispatchers. Roadmap 100% Complete. |
| **12** | `feature_20261024_102000_runtime_hardening_secrets_and_readme_sync.md` | Post-Consolidation Runtime Hardening, Secret Masking & Full README Sync. Remediated 7 operational gaps: GAP-SEC-01 (secret masking in logs and outputs), GAP-RT-01 (visual_inspect event loop decoupling via ThreadPoolExecutor), GAP-RT-02 (coredumpctl check harmonization across server.py and crash_router.py with exit code 1 handling), GAP-DX-01 (optional category in artifact_catalog query for cross-category kNN search), GAP-DX-02 (socket-to-PID correlation in aep_ctl network listeners), GAP-DX-03 (kanban demotion ergonomics supporting task_id), GAP-DOC-01 (full README sync to 15-tool bundle and diagram harmonization). Kanban Task 109 promoted to `PROMOTED` at `0.9949 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | Zero credential leakage in outputs and Pueue dumps; zero event loop collisions in headless Playwright; coredumpctl returns clean empty list when no dumps exist; artifact catalog supports global cross-category search; network listeners correlate to PIDs and processes; kanban demote accepts task_id or artifact_name; README.md in 100% sync with active FastMCP tools; Semgrep 0 findings across 1,198 rules. |
| **13** | `feature_20261024_115500_mmap_hybrid_sqlite_ram_persistence.md` | Memory-Mapped Hybrid SQLite Optimization (PRAGMA mmap_size 256MB & 64MB Cache). Standardized all 5 SQLite touchpoints (`catalog.py`, `kanban.py`, `crash_router.py`, `playbook.py`, `docs_vectorizer.py`) onto centralized factory `engine/db.py`. Enforces 256MB mmap zero-copy reads, 64MB RAM page cache, WAL journal mode, 10s busy timeout, normal synchronous, memory temp_store. Exposed live `storage_engine` and `db_telemetry` in `artifact_catalog(action="reindex")`. Passed 1,000-op multithreaded WAL stress test with 0 lock errors in 0.125s. Kanban Task 110 promoted to `PROMOTED` at `0.9958 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | RAM-speed vector searches and metadata queries backed by 100% Linux kernel zero-copy memory mapping; multi-agent concurrent access without lock contention; 100% ACID persistence on disk for cross-agent reuse; Semgrep 0 findings across 1,198 rules. |
| **14** | `feature_20261024_171500_code_modernization_and_concurrency_optimization.md` | Milestone ONT-10: Python 3.12 code modernization, strict Ruff SAST adherence (0 errors across E,W,F,I,UP,S,BLE,PLW,FURB), FastMCP stdio concurrency offloading via AnyIO worker thread pool (<2ms loop jitter), segregated RO/RW SQLite factory (`get_ro_connection` mode=ro vs `get_rw_connection` autocommit), explicit `transaction_immediate` (`BEGIN IMMEDIATE`) anti-deadlock context manager, WAL autocheckpoint tuning (1000 pages ~4MB), PLW1510 subprocess hardening with POSIX FD isolation (`pass_fds=(fd,)`, `timeout=30`, `close_fds=True`). Passed 6 Dokimos verification gates (1,000 concurrent ops in 0.14s with 0 lock errors); Task 111 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (16 Capabilities, 1:1 Parity)** | Multi-agent concurrent FastMCP stdio requests never stall event loop; SQLite lock-upgrade deadlocks eliminated; zero silent exception swallows; zero unchecked subprocesses; Semgrep 0 findings across 1,352 rules. |
| **15** | `feature_20261025_031500_backup_restore_and_offensive_countermeasures.md` | Milestone ONT-11: 5-slot online hot backup rotation pool (`conn.backup()`), SHA-256 pre-promotion checksums, atomic restore purging stale `-wal`/`-shm`, self-healing auto-recovery (`verify_and_auto_recover`), `CapabilityGuard` CBAC, in-RAM execution path blacklist (`/etc/shadow`, `/root`, `~/.ssh`), multi-agent caller context segregation (`agent_id: str = "default"`), hardened Bubblewrap (`--unshare-all`, `--cap-drop ALL`, isolated tmpfs), cryptographic SHA-256 hash-chain audit log (`security_audit_log`). Passed 7 Dokimos verification gates; Task 112 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Native SQLite Backup API mandatory for WAL backups (raw copy prohibited); atomic restore must unlink `-wal` and `-shm`; in-RAM binaries cannot access sensitive paths; Bubblewrap drops all capabilities; SHA-256 audit log is immutable with cryptographic hash-chaining; `agent_id` segregates multi-agent contexts. |
| **16** | `feature_20261025_051500_autonomous_setup_updater_and_python314_migration.md` | Milestone ONT-12: Autonomous zero-dependency bootstrapper, updater & health auditor (`scripts/setup.sh`), Python 3.14 Production LTS migration (`requires-python = ">=3.14"`, `target-version = "py314"`), hermetic Astral `uv` toolchain, user-space Golang auto-provisioning, static CGO_ENABLED=0 Go diagnostic probes (`socket-monitor`, `fd-rescuer`), Pueue daemon musl auto-download, bubblewrap containerization, Omarchy skills hub multi-agent symlinking, 6-gate idempotency test suite (`test_setup_idempotency.sh`). Passed 7 Dokimos verification gates (FastMCP parity 15 tools / 18 capabilities, read-only `--check`, idempotency, py314 hermetic venv, static probes, Ruff 0 errors, Semgrep 0 findings); Task 113 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | DIR-ONT-01 flag short-circuiting for `--check` (100% read-only, 0 mutations); DIR-ONT-02 atomic staging traps (`rm -rf "$TMP_DIR"`); DIR-ONT-03 subshell PATH injection; DIR-ONT-04 pure hermetic venv without host package pollution (PEP 668); pure user-space non-root fallback; dotfile idempotency (zero duplicate exports). |

| **17** | `feature_20261025_144500_re_as_sdd_landlock_ebpf_and_anti_poisoning_backups.md` | Milestone ONT-13: RE as SDD for Linux primitives (`docs/sdd/`), in-process Landlock LSM sandboxing (`engine/landlock.py`), anti-poisoning hot backup engine & quarantine (`engine/backup.py`), volatile RAM micro-snapshots (`engine/db.py`), eBPF security probing (`server.py`), Go static Landlock probe (`diagnostic/go/landlock-guard`), CLI integration (`scripts/aep-ctl`), and verification suite. Passed 7 Dokimos verification gates; Task 114 promoted to `PROMOTED` at `0.9250 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Landlock restricts kernel unprivileged paths; volatile RAM micro-snapshots bypass disk WAL corruption during incident response; backup quarantine isolates malicious payloads. |
| **18** | `feature_20261028_235800_prepare_and_publish_github_repository_public_release.md` | Milestone ONT-14: Public GitHub Release & Compliance. Apache 2.0 license (`LICENSE`), git config hardening (`.gitignore`, `.gitattributes`), EDR/sandbox security warnings & license badge in `README.md`, pre-deploy verification suite, remote sync preparation. Task 115 promoted to `PROMOTED` at `0.950 TRUST`. | **15 (18 Capabilities, 1:1 Parity)** | Zero leaked credentials or test DB artifacts in repository tree; deterministic reproducible builds. |
| **19** | `feature_20261030_003000_aep_agent_experience_evaluation.md` | Agent Experience Evaluation Suite (Gemini Flash 3.8 High & ChatGPT Terra Medium reports). Benchmarked 15 FastMCP tools, evaluated developer ergonomics, token overhead, and error recovery workflows. 39 passed in `tests/test_agent_experience_evaluation.py`. | **15 (18 Capabilities, 1:1 Parity)** | Empirical measurement of LLM agent interaction patterns, tool telemetry, and failure mode recovery. |
| **20** | `feature_20261030_013500_self_evolutionary_suite_and_kali_semantics.md` | Milestone ONT-15: Self-Evolutionary Suite & Kali-Style Semantic Ergonomics. Hermetic clean-install bootstrap in `catalog.py`/`kanban.py` (table guards on `_migrate`), single-source `CONTROL_PLANE_SCHEMA` in `privilege.py`, bwrap network isolation default (`share_net=False`), `RequestTelemetry` and envelope formatting, `discover` playbook `EAES-v2-Kali-Semantic`. 39/39 passed. Task 120 `PROMOTED`. | **15 (18 Capabilities, 1:1 Parity)** | Hermetic bootstrap without pre-existing HOME; bwrap sandbox blocks private paths by default; response token payloads reduced 70-85%. |
| **21** | `feature_20261030_065200_ont18_topos_anti_cascade_battery_and_setup_hardening.md` | Milestone ONT-18: Topos Anti-Cascade Omission Battery & Installation Pipeline Hardening. COALESCE `binary_blob`/`hash` upsert in `engine/catalog.py` to prevent ELF payload wipe on setup re-run, Pueue release tag regex fix in `scripts/setup.sh`, Step 8 quoted heredoc probe seeding with probe aliases (`socket_monitor`/`fd_rescuer`), `setup.sh --check` schema validation & zero-canary verification, 43 regression tests suite, doc badges. Task 122 `PROMOTED` (Score: 0.9940 TRUST, 43/43 Tests Passed). | **15 (18 Capabilities, 1:1 Parity)** | $X_1 \not\to X_2 \not\to X_1$: Re-running installer never wipes compiled binary payloads; diagnostics never mutate production state. |
| **22** | `feature_20261030_110500_ont21_spec_om7_ipc_socket_pool_and_code_batch_mode.md` | Milestone ONT-21: Spec OM-7 Shared-Memory UNIX Socket Pool (`/dev/shm/aep.sock`), Cloudflare-Style Ephemeral Batch/Code Mode with Server-Side Field Projection, control plane `ipc` domain, and SDD. Task 129 `PROMOTED` (Score: 1.0 TRUST, 58/58 Tests Passed, 0.52ms IPC, 74.6%–96.98% Token Reduction). | **15 (18 Capabilities, 1:1 Parity)** | Sub-millisecond warm IPC via `/dev/shm`; server-side field projection eliminates token waste; atomic cleanup of socket on exit. |
| **23** | `execution_report_20261030_173000_ont22_spec_om7_omission_gap_remediation.md` | Milestone ONT-22: Spec OM-7 Omission Gap Remediation & Multi-Agent Cache Piping (Short Mode). Smart field projection, `$cache.<key>` piping, `failed_steps` preservation, tool whitelist expansion, and 3-agent zero-token shared RAM handoff (`pragma` -> `dokimos` -> `graphos`). Task 130 `PROMOTED` (Score: 0.9250 TRUST, 62/62 Tests Passed). | **15 (18 Capabilities, 1:1 Parity)** | `$cache.<key>` and `$slot.<key>` preserve native types across turns; `failed_steps` never dropped; 15-tool invariant preserved. |
| **24** | `execution_report_20261030_190000_ont23_pico_triad_concurrency_isolation.md` | Milestone ONT-23: Pico-Triad Multi-Agent Concurrency Isolation (Short Mode). Isolated Go builds in `/dev/shm` + atomic `os.replace`, atomic `kanban.upsert_build_task` under `transaction_immediate`, precomputed vector embeddings outside write locks, and `playbook_run(action="run")` slot/piping/projection parity. Task 131 `PROMOTED` (Score: 0.9250 TRUST, 66/66 Tests Passed). | **15 (18 Capabilities, 1:1 Parity)** | Zero TOCTOU race conditions in Kanban; zero build collisions; write-lock hold times reduced >95%; 15-tool invariant preserved. |
| **25** | `execution_report_20261030_210000_ont24_non_pico_concurrency_and_kali_semantics.md` | Milestone ONT-24: Non-Pico Concurrency Protections & Kali Semantics. Serialized `record_audit_event()` with `_AUDIT_LOCK` + `transaction_immediate`, thread-safe RAM snapshots with `_SNAPSHOT_LOCK` (`check_same_thread=False`), double-checked lock on doc vectorizer, Kali-MCP semantic instructions (recipes `WF-1..WF-6`, Rule #7). | **15 (18 Capabilities, 1:1 Parity)** | Prevented SHA-256 chain forks under parallel subagent tool execution; thread-safe RAM snapshots without SQLite cross-thread exceptions. |
| **26** | `verification_report_20261030_211500_ont24_non_pico_concurrency_and_kali_semantics.md` | Milestone ONT-24: Verification Report for Non-Pico Concurrency & Kali Semantics. Verified 69/69 tests in pytest, 8 concurrent threads on audit ledger, multi-thread RAM micro-snapshots, and validated 79 Mermaid diagrams across 52 docs with 0 errors. Task 132 `PROMOTED` (Score: 0.9500 TRUST, 69/69 Tests Passed). | **15 (18 Capabilities, 1:1 Parity)** | 100% verified non-Pico concurrency isolation; zero broken links; 15-tool invariant preserved. |

---

## 3. Core System Invariants (Preserved Across All Phases)

1. **Agents-for-Agents Delivery (P0)**: The primary deliverable is the compiled, validated artifact and autonomous capability expansion without human intervention on deterministic engineering steps.
2. **Dual Engine Architecture**:
   - `engine/ponder.py`: Universal trust arbiter (confidence, multidimensional metrics, veto power, bands: `TRUST`, `CAUTION`, `WARNING`, `REJECT`).
   - `engine/matcher.py`: Universal relevance engine (BM25F multi-signal ranking, token matching, bilingual lexical tags).
3. **Pico-Lifecycle & Memory**:
   - Closed telemetry loop: every tool execution records latency, exit code, and success rates.
   - Kanban state progression: `BACKLOG` → `SYNTHESIZED` → `LINTED` → `CANARY` (auto-advanced by in-RAM run) → `PROMOTED`.
   - Safe GC: Templates and proven artifacts are protected from pruning; cold-aging never demotes artifacts with 100% success rate.
4. **Tool Reach & Security Boundaries (P1)**:
   - Tool consolidation shrinks tool sprawl while maintaining 100% capability reach.
   - All tools strictly operate within local authorizations (FastMCP stdio, bubblewrap, memfd_create).
   - Strict non-recursion invariant: meta-tools like `playbook_run` cannot be dispatched recursively within playbooks.
   - Ergonomic shortcuts: `artifact_lint_and_build(action="build")` executes atomic template-to-binary synthesis without intermediate agent round-trips.
5. **Subprocess & Descriptor Isolation Invariant**:
   - Long-running daemons must never be launched through `artifact_execute_in_ram`.
   - Volatile RAM binary executions must explicitly pass only intended descriptors via `pass_fds=(fd,)`, enforce strict timeouts (`timeout=30`), and guarantee cleanup in `finally` blocks.
   - Background daemons (like `pueued`) must be spawned detached with `stdin=DEVNULL`, `stdout=DEVNULL`, `stderr=DEVNULL`, `close_fds=True`, and `start_new_session=True` to prevent deadlocks on inherited communication pipes.
6. **Hot SQLite Anti-Deadlock Invariant**:
   - Readers strictly use read-only URIs (`file:...?mode=ro`, `query_only = ON`) and never acquire write locks or contend with writer transactions.
   - Writers configure autocommit mode (`isolation_level = None`) and execute write transactions exclusively through `transaction_immediate(conn)` which issues `BEGIN IMMEDIATE` upfront, acquiring the RESERVED lock at transaction start and eliminating lock upgrade deadlocks.
   - `PRAGMA wal_autocheckpoint = 1000` bounds WAL files to ~4MB, preventing fsync latency spikes.
   - Rejection of `multiprocessing` forks with open SQLite WAL file descriptors prevents POSIX lock and shared memory corruption.
7. **FastMCP Event Loop Concurrency Invariant**:
   - All 15 FastMCP tools in `server.py` are declared as non-blocking `async def` coroutines.
   - Synchronous blocking calls (SQLite queries, vector similarity scans, disk I/O, subprocess execution) must be offloaded to worker threads via `await anyio.to_thread.run_sync()`, guaranteeing stdio JSON-RPC loop jitter remains <2.0ms.
8. **Database Resilience & Disaster Recovery Invariant**:
   - SQLite backups under WAL mode must exclusively utilize the native SQLite Backup API (`conn.backup()`); raw filesystem copying (`shutil.copyfile`, `cp`) is strictly prohibited.
   - The backup rotation pool is strictly bounded to 5 FIFO slots (`artifacts.db.bak.1..5`) tracked in `backups_manifest.json` with SHA-256 byte checksums.
   - Atomic database restore must purge stale `-wal` and `-shm` sidecars prior to atomic file replacement (`os.replace`) to prevent catastrophic index desynchronization.
   - Automated self-healing corruption recovery (`verify_and_auto_recover`) automatically falls back to the newest healthy backup slot on corruption.
9. **Offensive Primitive Containment & Multi-Agent Segregation Invariant**:
   - In-RAM binary execution via `artifact_execute_in_ram` is bounded by strict canonical path blacklists (`/etc/shadow`, `/root`, `~/.ssh`, kernel memory nodes) and network egress policy boundaries.
   - `CapabilityGuard` enforces capability-based access control, preventing unprivileged agents from escalating privileges across tools or accessing sensitive operations.
   - Bubblewrap sandboxes enforce complete namespace unsharing (`--unshare-all`), total Linux capability dropping (`--cap-drop ALL`), and ephemeral isolated memory mounts (`--tmpfs /tmp`).
   - All 15 FastMCP tools enforce explicit `agent_id: str = "default"` caller context segregation with per-agent scratchpad directories and Pueue queue groups (`agent_{agent_id}`).
   - All security actions are recorded in an immutable cryptographic SHA-256 hash-chained audit log with universal secret masking ($H_n = \text{SHA256}(H_{n-1} + \dots)$) and active tamper detection.
10. **Autonomous Tooling Provisioning & Environment Hermeticity Invariant**:
    - System bootstrapping and updates must be autonomous and zero-dependency, self-provisioning `uv`, Python 3.14, Go, and Pueue in user-space if non-root.
    - Read-only health inspection (`--check`) must short-circuit upfront before any directory creation or network fetch (DIR-ONT-01), guaranteeing zero disk mutations and deterministic exit codes.
    - Remote downloads must be guarded with atomic cleanup traps (`rm -rf "$TMP_DIR"` on EXIT/INT/TERM, DIR-ONT-02).
    - Subshell and child processes must receive canonical PATH injection (`~/.local/bin`, `~/.local/share/go/bin`, `~/.local/share/agent-os/bin`, DIR-ONT-03).
    - Python virtual environments must be purely hermetic without host system site-packages (DIR-ONT-04), fully compliant with PEP 668.
    - Idempotency guards must prevent duplicate shell environment exports in user dotfiles.
11. **Topos Anti-Cascade & Idempotent Catalog Seeding Invariant**:
    - Artifact upserts in SQLite (`register_artifact`) must use `COALESCE(excluded.binary_blob, artifacts.binary_blob)` and `COALESCE(excluded.binary_hash, artifacts.binary_hash)` on name conflict, preventing binary_blob wipe cascades ($X_1 \not\to X_2 \not\to X_1$) during repeated installer or bootstrap executions.
    - Diagnostics and verification gates (`setup.sh --check`) must never seed canary artifacts into production catalogs (`auto_seed_canary=False`) and must assert schema column integrity directly against active SQLite stores.
12. **Shared-Memory IPC & Server-Side Field Projection Invariant (Spec OM-7)**:
    - IPC communication via UNIX domain sockets in `/dev/shm` must maintain warm connection reuse, strict file descriptor ownership with zero FD leaks, and graceful fallback to stdio.
    - Server-side field projection must filter responses before serialization to bound context window consumption, supporting smart dot-path fallbacks.
    - Multi-agent shared RAM session caches (`$cache.<key>`, `$slot.<key>`) must preserve cross-agent state across execution turns without context window bloat, and partial execution diagnostics (`failed_steps`) must never be dropped on failure.
13. **Pico-Triad Multi-Agent Concurrency Isolation Invariant (Spec OM-7 / ONT-23)**:
    - Artifact compilations must occur inside dedicated `/dev/shm` session slots and publish outputs atomically via hidden `.tmp` staging and `os.replace`, preventing binary corruption during concurrent agent builds.
    - Kanban task card creation and score progression during builds must be atomic via `upsert_build_task()` executed inside `transaction_immediate()`, eliminating TOCTOU race conditions.
    - Vector embeddings must be computed outside SQLite write transactions to minimize write-lock hold times and prevent primary key contention on vector virtual tables.
    - Saved playbooks (`action="run"`) must maintain full architectural parity with ephemeral batches (`action="batch"`), including slot leasing, inter-step parameter piping, session cache propagation, and server-side field projection.

---

## Rollup 2: ONT-29 to ONT-39 (Graphos G1, 2026-11-06)

- **Document ID**: `feature_rollup.md` (section "Rollup 2")
- **Covers**: 11 chain documents after the rollup of 2026-10-30: ONT-29, ONT-30, ONT-31, ONT-32, ONT-33, ONT-34, ONT-35, ONT-36, ONT-37, ONT-38, ONT-39 (`feature_20261106_000100_ont39_live_plane_hot_swap.md`).
- **Trigger**: the every-5th-document rule was not applied at documents 5 (ONT-33) and 10 (ONT-38). This section closes the gap. The next document, `feature_20261106_011249_ont40_autoevol.md`, is 12th in the chain since the rollup. The next rollup falls at the 15th document.
- **Note**: the heading of section 1 reads "Documents 1-16" and its body reads "1 to 24". The numbering is inconsistent in the original and is not corrected here.

### 2.1 Milestone history

| Intent | Document verdict | Key result | Ontos cycles |
|---|---|---|---|
| ONT-29 External consumption gaps and Chrysalis bridge | VERIFIED & PROMOTED | GAP-OM-17: Bernstein shared-write checks in `topos_audit_dag` (`resources`) | APPROVED, 0 co-dependencies |
| ONT-30 Schema evolution and runner ergonomics | VERIFIED & PROMOTED (99/99) | Cross-harness schema evolution | APPROVED, 0 co-dependencies (5 tasks) |
| ONT-31 RE as SDD, Kali MCP and native Antigravity | VERIFIED & PROMOTED | Dual-plane offensive and defensive primitives | APPROVED, 0 co-dependencies (6 tasks) |
| ONT-32 Native memory-first network telemetry | VERIFIED & PROMOTED | Architectural purification, container decoupling | APPROVED |
| ONT-33 Predictive privilege-aware setup | VERIFIED & PROMOTED | `sudo -n` non-interactive probing, chmod degradation matrix | APPROVED, 0 co-dependencies (5 tasks) |
| ONT-34 FastMCP tool 16 (`default_primitives`) | VERIFIED (123/123) | 15 to 16 tools, 18 to 19 capabilities, factory decoupling | APPROVED, 0 co-dependencies (9 tasks) |
| ONT-35 Version stamp integrity and sync | VERIFIED (133/133) | GAP-RT-04 drift freeze, GAP-RT-03 multi-harness sync | not recorded in document |
| ONT-36 Hardware domain and apport alerts | VERIFIED (143/143) | GAP-CP-05 admission, GAP-OM-20 alerts | 1 BLOCKED (R1-R5), then APPROVED |
| ONT-37 UMA admission, apport RFC822, pytest parsing | VERIFIED (153/153) | GAP-DX-06, GAP-OM-21, GAP-DX-07 | 1 BLOCKED, then APPROVED |
| ONT-38 README SSoT drift mitigation | VERIFIED & COMPLETED (153/153) | README synchronized to 16 tools, 19 capabilities, 9 domains | not recorded in document |
| ONT-39 / ONT-39b Live plane hot-swap | VERIFIED (L1 175 passed; fix cycle 179; ONT-39b 198 passed, 6 xfailed) | Front and backend split, fail-safe swap, D-18..D-21 hardening | not recorded in document; ONT-39b committed as `3515a22` |

### 2.2 Invariants that held across the period

1. Tool count moved only once, 15 to 16 (ONT-34). From ONT-35 onward it stayed at 16 until ONT-40 proposes 17 by explicit user decision.
2. Zero co-dependencies in every Ontos approval. Two BLOCKED cycles (ONT-36, ONT-37) were resolved by remediation, not by waiver.
3. The `sudo -n` non-interactive rule (ONT-33) and secret masking (GAP-SEC-01) carried through all later intents.
4. Single source of truth for the tool count was enforced by `scripts/aep-sync.sh --check` from ONT-35 onward.

### 2.3 Open items carried into ONT-40

- D-01 (verbosity claim against measured budget) remains open until L3. It is an xfail in the test suite.
- The ONT-39b state (`3515a22`) is committed. Its verification report is `verification_report_20261106_ont39_live_plane.md`.
- ONT-40 plan, its observations O-1 to O-8, and the task DAG: `feature_20261106_011249_ont40_autoevol.md`.

## Rollup 3: ONT-40 a L3 (Graphos G1, 2026-11-06)

Cadena desde Rollup 2: `feature_20261106_011249_ont40_autoevol.md` → `feature_20261106_080856_ont41_autoevol_heal.md` → `feature_20261106_172315_ont42a_harness_reconnect.md` → `feature_20261106_181608_l3_token_contract.md` → `feature_20261106_182001_ont42_judge_evolve.md`.

- **ONT-40 / ONT-41:** `autoevol` gana graph, gaps, spec, verify, fix_test y heal con LKG y self-heal del plano en vivo. VERIFIED.
- **ONT-42a:** `harness_reconnect` (RE-as-SDD). VERIFIED excepto T8 (smoke en vivo con sudo y TIOCSTI, user-gated).
- **L3:** contrato de tokens D-01..D-05 (summary compacto, detail sin cambios). VERIFIED con 0 ciclos de fix. Suite 576 passed, ruff limpio, 17 herramientas y 19 capacidades.
- **Backlog ONT-42:** D-01b, AE-1..AE-6. Su plan está en `feature_20261106_182001_ont42_judge_evolve.md`: 42b (B1 a B9, juez autónomo) y 42c (C1 a C7, `evolve`). DAG APPROVED. Pendiente Ontos.

**Invariantes preservadas:** 17 herramientas y 19 capacidades; R (raíz Merkle) sin cambio de esquema; el juez no hace commits (git entra por puerto inyectado); push solo con autorización explícita.

---

## Catch-up Rollup (documentos desde ONT-21 hasta ONT-42c, registrado 2026-11-07)

Este rollup estaba vencido. Cubre la cadena posterior a `feature_20261030_110500_ont21_spec_om7_ipc_socket_pool_and_code_batch_mode.md`.

- **ONT-22 a ONT-24**: concurrencia pico-trío, no pico y semántica Kali (reportes de ejecución).
- **ONT-29 a ONT-33**: estabilización del bridge AEP, schema y ergonomía del runner, telemetría de red sin dependencias, privilegio predictivo y degradación chmod.
- **ONT-34 a ONT-38**: primitivas por defecto y desacople de factorías, hardware y apport, UMA y parsing pytest, drift del README.
- **ONT-39 a ONT-41**: Live Plane hot-swap, `autoevol` thread graph y write-path con self-healing N0–N3. VERIFIED.
- **ONT-42a**: `harness_reconnect` multi-harness. VERIFIED excepto T8 (smoke en vivo, user-gated).
- **L3**: contrato de tokens D-01..D-05. VERIFIED en modo Short (576 passed).
- **ONT-42 (judge/evolve)**: B1–B8 integrados; B9 PLAN_GAP resuelto por G1–G4; B9 ACCEPT agy no discriminante.
- **Auditoría agy `1b983f1..b605677`**: DEFECTIVE → fixes `d0ff416..5bee5c1` → VERIFIED (659 passed, 0 xfail). Ver `feature_20261107_011128_agy_audit.md`.

**Decisiones acumuladas:** modo Short por defecto; AEP recarga sólo su propia sesión; push retenido hasta autorización.

**Documento activo:** [`feature_20261107_011128_agy_audit.md`](feature_20261107_011128_agy_audit.md)

## Rollup 5: E2 a E4 y sala limpia (Graphos G2, 2026-11-07)

Cadena desde el Catch-up Rollup: `feature_20261107_011128_agy_audit.md` → `feature_20261107_104734_e2_backlog_install.md` → `feature_20261107_113335_install_integrity_e3.md` → `feature_20261107_115813_e4_reconcile.md`.

- **Auditoría agy `1b983f1..b605677`**: DEFECTIVE → `d0ff416..5bee5c1` → VERIFIED (659 passed). Ya registrada en el Catch-up.
- **E2 specs incrementales** (`74d5968`, `eff04ac`): caché por `node_hash`, `stale_specs`, fail-open, tier < 6 no escribe. VERIFIED (772 passed). La spec es informativa.
- **Sala limpia, 3 rondas** (`92c9661..aa468e1`, `10b8608..f8b0d11`, `81ba56b`): ronda 3 INSTALA CON INTEGRIDAD (uv 0.13.7, Go 1.26.10, golangci-lint v2.15.0, pueue v4.0.4 con SHA calculado).
- **E3 supervisión OTP sobre SCC** (`096ef95..f8eaa9c`, aislamiento `9c6a913`): `one_for_one` / `rest_for_one`, clasificador restore/identical/out_of_lkg. VERIFIED (805 tests recolectados).
- **E4 reconciliación acotada por tier** (`a8308f8`, `07c023a`, `00886c3`): `autoevol(action="reconcile")` propone por defecto; abrir ciclos exige opt-in (`open_cycles=true` o `AEP_RECONCILE_OPEN=1`) con presupuesto propio `AEP_RECONCILE_MAX_OPENS` (defecto 1 / 24 h). Primer pase DEFECTIVE (3 menores) → 1 ciclo de corrección → VERIFIED (829 passed). Gaps 122 → 120.

**Plan E2–E4 de autohealing: cerrado.**

**Invariantes preservadas en el tramo:**
1. Ningún tier hace commit, merge, push ni `heal apply` desde reconcile; tier < 6 no escribe.
2. Modo Short por defecto; Archon y Ontos sólo en Full por petición del usuario.
3. Push a `origin/dev` user-gated; sin push en este tramo.
4. `resolve-revert` sólo por CLI humano con `--confirm`; `recovered: true` sólo con prueba git y testigo del gate.
5. El tope de ciclos de `evolve` (`AEP_AUTOEVOL_MAX_CYCLES`) y el presupuesto de apertura de reconcile (`AEP_RECONCILE_MAX_OPENS`) son independientes.

**Documento activo:** [`feature_20261107_115813_e4_reconcile.md`](feature_20261107_115813_e4_reconcile.md)

**Próximo rollup:** al quinto documento posterior a `feature_20261107_115813_e4_reconcile.md` (0 de 5 al cierre de este registro).

---

## Rollup 6: ONT-43 field report y backlog track A (Graphos G2, 2026-11-07)

Cadena desde Rollup 5: `feature_20261107_115813_e4_reconcile.md` → `feature_20261107_135303_ont43_field_report.md`.

**Nota de cadencia:** este rollup se pidió de forma explícita por el usuario. La regla de cada quinto documento no se cumple todavía (sólo hay un documento posterior al Rollup 5). El contador del quinto documento se reinicia aquí: el próximo rollup por regla llega al quinto documento posterior a `feature_20261107_135303_ont43_field_report.md`.

- **ONT-43 field report** (staged sobre `c0fb71a`, sin commit): los fallos reales de herramientas llegan a `autoevol` por cuarentena. `evol_hint` en sobres de error (lista blanca, firma sin texto, omitido en modos compactos, nunca en denegaciones); `autoevol(action="report")` registra candidatos (tier >= 5r-x, dedupe, tope 20/24 h) y promueve por reproducción (tier >= 6rw-, test `xfail(strict)` de la misma firma, sólo ese test, en `bwrap`, fail-closed). Gap `field_discrepancy` fuera de R, tratado como drift por reconcile. VERIFIED: 913 passed, ruff limpio, gaps 120, 17 tools / 19 capacidades.
- **Actualización 2026-11-12 (endurecimiento O1–O3 / R1–R3, staged):** `report` exige `tool`, `action`, `status` y `error_class` (el formato `{tool, expected, observed}` ya no se acepta); `sig = sha256(tool|action|status|error_class)[:12]`, verificada al registrar; el repro sólo puede ser `tests/field/test_fr_<sig>.py` con `xfail(strict=True, raises=<error_class>)`. VERIFIED: 987 passed, ruff limpio, gaps 120, 17 tools / 19 capacidades.
- **Backlog track A** (mismo tramo): caché E2 con `cover_hash` y hit malformado = miss; prueba de fusión de kwargs de helpers multi-sitio (sin defecto); sondas Go (errcheck ya resuelto; `go.mod` descartado por riesgo sobre el glob `tpl_*.go`; lint con `go.mod` temporal); setup sin red falla cerrado.
- **Ciclo de corrección:** Dokimos hallazgos F1 (promoción sin fallo cerrado cuando cae `bwrap`) y F2 (aserción vacía) → 1 ciclo Pragma → VERIFIED.

**Invariantes preservadas en el tramo:**
1. Un reporte de campo nunca abre ciclos ni modifica código; la cuarentena es dato inerte.
2. La promoción siempre corre en `bwrap` y falla cerrada.
3. `field_discrepancy` queda fuera de la raíz Merkle R y de la caché E2.
4. Ningún tier hace commit, merge, push ni `heal apply` desde reconcile; tier < 6 no escribe.
5. Modo Short por defecto; commit y push user-gated.

- **ONT-44 cobertura MCP (2026-11-13, Graphos G2):** 120 omisiones de cobertura de la superficie MCP reducidas a 46 con 5 archivos `tests/test_cov_*.py` (dos tracks Pragma en worktrees). Correcciones: P1 gate por tier en backup mutante; P2 `verify_integrity` de sólo lectura; P3 listeners paginados; P4 reindex `force` con SAVEPOINT; P5 schema summary 1524 a 1278 tokens. Trinquete `GAPS_BASELINE = 46`. VERIFIED: 1092 passed, ruff limpio, 17 tools / 19 capacidades. Decisión: `micro_snapshot` sin gate en servidor (diferencia con el CLI).

- **ONT-45 residuo Topos (2026-11-13, Graphos G2):** 46 omisiones de cobertura ordenadas en 4 niveles con clasificación Topos (dependencia / interdependencia / co-dependencia). Tres tracks Pragma en paralelo; Ontos BLOCKED rev1 (3 errores factuales) y APPROVED rev2; Dokimos DEFECTIVE (promesa falsa de `service.*` en `6rw-`, corregida) y VERIFIED. Gaps 46 a 1 (residuo visible: `test_gate8_semantic_sanitization`). VERIFIED: 1121 passed, ruff limpio, 0 co-dependencias, 0 claim_drift; sin código de producción tocado. Hallazgos: los claims `doc` no se comparan en `claim_drift`; `aep_front`/`aep_backend` sólo comparten protocolo de cable; `import aep_backend` corrompe fd 1 (guarda `_Fd1Guard`). Backlog: ONT-46 precisión del extractor.

**Documento activo:** [`feature_20261113_080406_ont45_topos_residue.md`](feature_20261113_080406_ont45_topos_residue.md)

**Próximo rollup:** al quinto documento posterior a `feature_20261113_004026_mcp_coverage_reinforcement.md` (2 de 5 al cierre de `feature_20261113_080406_ont45_topos_residue.md`).

## Rollup 7: ONT-46 a ONT-60 (Graphos G2, 2026-11-14)

Cadena desde Rollup 6: `feature_20261113_080406_ont45_topos_residue.md` → `feature_20261113_ont46_extractor_precision.md` → … → `feature_20261114_ont60_sandbox_packages.md`.

**Nota de cadencia:** la regla de cada quinto documento no se cumplió en ONT-50, ONT-55 ni ONT-60. Este rollup consolida los quince documentos y reinicia el contador.

| ONT | Documento | Resultado |
|-----|-----------|-----------|
| 46 | `feature_20261113_ont46_extractor_precision.md` | precisión del extractor de hilos |
| 47 | `feature_20261113_ont47_dogfood_frictions.md` | fricciones de dogfooding, ronda 1 |
| 48 | `feature_20261113_ont48_dogfood_gaps.md` | gaps de dogfooding, ronda 2 |
| 49 | `feature_20261114_ont49_dogfood_round3.md` | gaps de dogfooding, ronda 3 |
| 50 | `feature_20261114_ont50_neighbors_projection.md` | descubrimiento LAN y proyección única |
| 51 | `feature_20261114_ont51_discover_supervise.md` | discover por afinidad y supervisión |
| 52 | `feature_20261114_ont52_round6.md` | ronda 6 de gaps |
| 53 | `feature_20261114_ont53_ort_synonyms_walk.md` | telemetría ORT y sinónimos EN+ES |
| 54 | `feature_20261114_ont54_round7.md` | ronda 7 de gaps |
| 55 | `feature_20261114_ont55_kanban_work.md` | tarjetas de trabajo en kanban, 1345 passed |
| 56 | `feature_20261114_ont56_reclassify_snapshot.md` | reclasificación de tarjetas legadas, 1359 passed |
| 57 | `feature_20261114_ont57_severity_table.md` | severidad explícita por estado, 1386 passed |
| 58 | `feature_20261114_ont58_pending.md` | pendientes de ONT-57 cerrados, 1396 passed |
| 59 | `feature_20261114_ont59_go_philosophy_kanban.md` | kanban con la filosofía de Go, 1462 passed, publicado en dev y main |
| 60 | `feature_20261114_ont60_sandbox_packages.md` | VERIFIED tras dos ciclos (ciclo 1 de seguridad en T2 corregido), 1498 passed, docs publicados en dev |

**Invariantes preservadas en el tramo:**
1. Ninguna salida truncada sin `cursor`; la paginación no re-ejecuta el comando.
2. Un toolchain montado nunca expone una ruta vetada: ninguna raíz es igual o ancestra de una ruta de la blacklist.
3. La DB real no se toca desde las pruebas; el hallazgo G67 queda abierto para ONT-61 T0.
4. Ningún tier hace commit, merge o push desde Graphos; `main` no se toca en ONT-60.
5. Modo Short por defecto; commit y push user-gated.

## Registro posterior a Rollup 7

| ONT | Documento | Resultado |
|-----|-----------|-----------|
| 61 | `feature_20261114_ont61_db_isolation.md` | aislamiento de la DB real, VERIFIED tras dos ciclos, 1510 passed |
| 62 | `feature_20261115_ont62_health_and_update.md` | pendientes menores, falsos negativos de salud y G71 de `setup.sh --update`, VERIFIED tras dos ciclos, 1536 passed |
| 63 | `feature_20261115_ont63_orientation_layer.md` | capa de orientación básica: 8 primitivas L0, escalera L0-L2 y WF-0; VERIFIED tras tres ciclos, 1637 passed; publicado en dev (Hermon) |
| 64 | `feature_20261115_ont64_path_trim_and_doc_gate.md` | recorte de `aep_python.path` y puerta de docs en pre-commit, VERIFIED en un ciclo, 1657 passed; publicado en dev |
| 65 | `feature_20261115_ont65_zero_gaps.md` | cero gaps de cobertura, VERIFIED tras dos ciclos, 1666 passed |
| 66 | `feature_20261115_ont66_noisy_notices.md` | AEP ruidoso (`aep_notice`), VERIFIED tras dos ciclos, 1700 passed |
| 67 | `feature_20261116_ont67_ram_efficiency.md` | uso de RAM medido: memfd sellado, descarga del embedder, caché sin AST, zstd en tmpfs y línea Memory, VERIFIED en un ciclo, 1740 passed |

| 68 | `feature_20261116_ont68_aep_findings.md` | hallazgos reportados por AEP: caché ELF (falso positivo corregido), `KEEP_EMBED_IDLE` (bug real) y extracción en frío robusta a carga; VERIFIED tras dos ciclos, 1751 passed; publicado en `dev` y `main` (`6a359f7`) |

**Documento activo:** [`feature_20261116_ont68_aep_findings.md`](feature_20261116_ont68_aep_findings.md)

**Próximo rollup:** cadena 66..70; se dispara con ONT-70 (3 de 5 tras `feature_20261116_ont68_aep_findings.md`: ONT-66, ONT-67 y ONT-68 documentados y publicados en `main` `6a359f7`; ONT-69 no tiene intent definido; las filas 65 y 66 se añaden aquí porque faltaban en el registro).

**Corrección de registro:** el hallazgo 1 de `feature_20261116_ont67_ram_efficiency.md` (magic ELF "nunca coincide") era falso positivo, verificado con `od` en ONT-68. El hallazgo 3 (`KEEP_EMBED_IDLE`) era un bug real y queda resuelto en ONT-68.
