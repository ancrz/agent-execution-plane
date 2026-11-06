# Audit Report: ONT-42 (42b B1–B9, 42c C1–C7), Ontos, Stage 3, Full

**Verdict: APPROVED CON CONDICIONES VINCULANTES (1–16).** Hay un defecto de ordenamiento en el DAG (no es co-dependencia) y seis huecos de omisión de severidad alta. Todos se cierran con las condiciones de abajo y ninguna reabre un diseño. Pragma no arranca cada lote sin sus condiciones en el prompt. Dokimos verifica cada condición. No he ejecutado nada ni escrito en el repo.

## 1. Aristas del DAG (confirmación de §3.4)
- B1→B2, B2→B3, B1→B4, B6→B9, B8→B9 y C1..C7 son correctas.
- **Arista invertida.** Graphos puso B7→B3, pero B3 emite `tests{pin,validate}` y `pin` sale de `pinning_tests` (B7). La dependencia real es B3→B7 (dep). B7 no necesita código de B3, solo recibe `changed` como argumento, así que no es co-dep. En el orden de lotes, B3 (P1) llama a una función que aún no existe (P2).
- B5→B4 es espuria. Solo fuerza serialización y es inocua.
- C5, C6 y C7 sí dependen de C3/C4, porque el ledger registra merge y gate. Con las aristas actuales el DAG sigue acíclico.
- **Condición 1.** B3 entrega solo `change{nodes,files}`. El split `pin/validate` pasa a B8, que ya depende de B7. Corregir §3.4 a B3→∅ (tras B2), B7→∅ y B8→{B3,B7}.

## 2. Clasificación (confirmada con matices)
- `threads_evolve` → `threads_ops` → `threads_verify` es dep. Es válido solo si evolve **no escribe** en el store de ciclos de fix_test, solo lo consulta.
- evolve↔fix_test no es co-dep, siempre que se cumpla la condición 2.
- GitPort: `server` ↔ `engine` (puerto como Protocol) es interdep. Ya existe un patrón análogo (runner y dispatcher inyectados).
- GitPort envuelve fence, merge y push en el lado de `server`, porque `engine` no puede importar `aep_front`. El fence lo toma la implementación del puerto, no la máquina de estados (condición 8).
- **Condición 2.** evolve solo lee el ciclo de fix_test (lectura del store). Su estado vive en el ledger `evolve.*`. Test de import: `threads_ops` y `threads_verify` no importan `threads_evolve`.

## 3. B5 (seguridad del sandbox)
- **PYTHONPATH como protección es insuficiente, pero el editable no es el vector.**
  - El finder editable (`__editable___..._finder.py`) mapea `engine` a la ruta canónica y se registra con `sys.meta_path.append`. Va después de `PathFinder`, así que gana `sys.path` (cwd/PYTHONPATH).
  - Cuando importa código viejo es por falta de cwd/PYTHONPATH o por tener el repo canónico montado, no por el `.pth`.
- **El plan es erróneo en dos puntos de `sandbox_run`.**
  - El auto-resolve de symlinks del intérprete solo se activa cuando un `ro_path` contiene `.venv/bin/python` (`server.py:3086-3101`). Pasar `REPO_ROOT/.venv` directamente no lo dispara.
  - Montar `REPO_ROOT` para obtenerlo expone `.git`, el `engine` canónico y los secretos al código no confiable. Además, con ese montaje el MAPPING editable resolvería el código viejo sin error.
- **Condición 3.** `ro_paths` = `[tree, REPO_ROOT/.venv, <raíz uv python resuelta, p. ej. parents[2]>]` explícitos. Nunca `REPO_ROOT`. Fail-closed: si el venv o la base no existen, SANDBOX_UNAVAILABLE.
- **Condición 4.** Los siguientes puntos se verifican juntos:
  - **Mismo proceso.** El centinela corre en la misma invocación bwrap que pytest, con el mismo cwd (`working_dir=tree`) y el mismo env: `python -c "…" && python -m pytest …`. Una llamada aparte no prueba nada sobre la corrida real.
  - **Comparación.** Compara `Path(engine.__file__).resolve().is_relative_to(tree.resolve())`, no una cadena.
  - **Código de salida.** Sale con un código dedicado (p. ej. 97) mapeado a WRONG_TREE **antes** de las ramas 126/127/"exit sin resumen" de `_autoevol_test_runner`, que hoy lo convertirían en SANDBOX_UNAVAILABLE.
  - **Registro de WRONG_TREE.** Añadir a `REJECT_REASONS` (orden fijo) y a `ENVIRONMENTAL`. Es ambiental pero no reintentable por sí solo (condición 5).
- **Condición 5.** En el segundo WRONG_TREE consecutivo, EXHAUSTED sin esperar `MAX_ENV_RETRIES=10`. Es determinista, no transitorio.
- **Tests obligatorios.** Worktree sin `.venv` (cadena tree → canónico → UNAVAILABLE) y árbol con `engine/` falso (WRONG_TREE).
- **Medio.** `tree/.venv` sigue teniendo prioridad. Un `.venv` dentro de un worktree de agente es código no confiable que se ejecuta bajo bwrap, lo cual es aceptable porque está confinado. Documentarlo.

## 4. B6, B4, B7, B8 (cascada)
- **B6.** `awaiting:"env"` y `barrier:"n/a"` cambian el contrato de salida. Los tests de ONT-41 que fijan `awaiting:"reload"` (`test_ont41_fixcycle1`, `test_ont41_ops`) se actualizan en el mismo commit. Las salidas nuevas deben pasar por `fit` y respetar 350/1500 tokens.
- **B4.** La clave primaria es una clase de prioridad. Los tests ONT-40 de orden, `top_gap` en discover terse y `test_ont40_acceptance` sobre el repo real quedan en el mismo commit (R3 del plan). R no cambia por B4 porque `merkle_root` solo hashea nodos y aristas de dependencia (verificado).
- **B1.** Agrega un nodo test, así que R cambia en esa transición. "R estable" significa estable en esquema, no en valor. Aclararlo en el SDD.
- **B1+B4 acoplan.** Con el xfail D-01b abierto, `top_gap` es D-01b hasta B9. Ningún test ni playbook debe asumir otro top_gap.
- **B7 (coste y precisión).**
  - **Coste.** Parsear los 50 archivos de test con `ast` son decenas de ms a unos 300 ms. Aceptable con caché por `(ruta, mtime_ns, size)` de la **tree** auditada (no la canónica).
  - **Falsos positivos.** Nombres genéricos (`status`, `get`, `summary`) seleccionan casi todo. Exigir stoplist, identificadores de longitud ≥5 o calificados, y cap por B8.
  - **Falsos negativos.** El plan acota la búsqueda a nodos dentro de `assert`, pero los golden values suelen estar en una variable (`expected = {...}`) y compararse después, así que se pierden.
- **Condición 6.** El escaneo de B7 cubre todo el cuerpo de la función de test y las constantes de módulo que referencia, no solo los `assert`. Incluye la caché y la stoplist.
- **B8.** El cap de 24 puede ocultar un fallo real. Si `transitive_dropped>0`, el veredicto ACCEPT lleva `partial:true`. Nunca aplicar el cap con `apply`.

## 5. C3/C4 (carrera, fence, suite completa)
- **El ff-merge en el árbol canónico dispara hot-swap.** Hay que tomar el fence.
  - `aep_front.swap_fence_path` usa `AEP_SWAP_FENCE_PATH` o `PROJECT_ROOT/.aep_swap_fence`. El fence caduca como huérfano a los 600 s. El archivo está en `.gitignore`, así que no ensucia el árbol.
  - Un merge multi-archivo y un `git revert` escriben varios archivos en secuencia. Sin fence puede cargarse un conjunto a medias.
- **Condición 7.** Al ff-merge y al revert los envuelve el fence, creado con `O_EXCL`. Si ya existe, BLOCKED_GIT `fence_held` (no se pisa).
- **Condición 8.** El fence cubre solo merge/revert (segundos), nunca el gate ni el verify post-merge. Se libera en `finally` y después se exige `stale==false` y `code_fingerprint_loaded == code_fingerprint_disk` (regla ONT-39 #10) **antes del push**. Si hay stale o LKG, el push no ocurre.
- **"Árbol canónico limpio" es un test que hoy fallaría.**
  - El repo tiene `M docs/pipeline/feature_rollup.md` y `?? .claude/`.
  - **Condición 9.** Definir limpieza como "sin cambios en los **tracked** que toque el diff del merge". Ignorar untracked. Dejar que `git merge --ff-only` sea el árbitro final y tratar su rechazo como BLOCKED_GIT. Los TOCTOU entre el chequeo y el merge se cubren con el fence más `--ff-only`. Verificar `git rev-parse` del HEAD del branch igual al sha gateado.
- **C4: la suite completa no puede ser async en un worktree con el dispatcher actual.** Los 576 tests tardan ~2 min, más que el `_AUTOEVOL_TEST_TIMEOUT_S=120`. `_autoevol_dispatcher` rechaza todo `root` ajeno (F3) porque Pueue ejecuta en el host sin bwrap. Es decir, el diseño exige async y la política de seguridad lo prohíbe para exactamente el árbol que evolve usa.
- **Condición 10.**
  - **Sandbox.** Prohibido ejecutar el gate sin sandbox sobre el parche de un worktree.
  - **Chunking.** El gate se hace como lotes re-entrantes de sandbox_run (≤100 s cada uno), con progreso `gate i/n` persistido en el ledger. `awaiting:"gate"` mientras queden lotes.
  - **Mismos requisitos.** Mismo intérprete y centinela que B5.
  - **Veredicto.** Un fallo o `ran<selected` es rojo (sin merge). `unsandboxed` presente es rojo.
- **Nota.** Si se prefiere Pueue, el comando debe llevar el mismo envoltorio bwrap. Eso exige extraer el constructor de argv de `sandbox_run`, trabajo fuera del alcance del plan.

## 6. C2/C5/C6 (git, idempotencia, rollback)
- **Condición 11 (tabla C2).** Corregir la fila contradictoria de §5 del plan (el `7rwx, y 6rw- bajo FULL` ya fue resuelto por el orquestador): push y ff-merge **solo con etiqueta FULL (7rwx)**; 6rw-/DIMINISHED es commit local en `autoevol/<ciclo>` sin ff-merge a dev ni push; 5r-x/4r-- solo plan, sin escribir en el árbol. Test de matriz por octal/etiqueta; documentar en SDD §4/§7 (AP-1 queda restringido).
- **Condición 12 (prohibiciones git).** Sin `--force`, sin `+refspec`, sin `main`, sin rebase/reset/amend, sin `pull`. Se pushea con `git push origin dev` y `autoevol/<ciclo>` y refspec literal. Test grep/AST sobre el GitPort. Un push rechazado es BLOCKED_GIT, sin retry creativo.
- **Condición 13 (idempotencia).**
  - **Clave.** `tree_hash` es `git rev-parse <commit>^{tree}`, no mtimes. La clave del ledger se inserta atómicamente (`INSERT OR IGNORE` / UNIQUE).
  - **Reconciliación.** Si el proceso cae entre commit y registro, el estado se reconcilia leyendo el git real (la rama y el merge existen). Git es la fuente de verdad, el ledger el índice.
  - **Rama existente.** `autoevol/<ciclo>` existente con el mismo tree es idempotente. Con otro tree es BLOCKED_GIT (R5).
- **Condición 14 (tope de ciclos).** `AEP_AUTOEVOL_MAX_CYCLES=3` se persiste en el ledger. Un contador en memoria se reinicia en cada hot-swap, que esta misma función provoca. Definir "sesión" (p. ej. ventana de 24 h por DB).
- **Condición 15 (C6).** La reversión solo cuando el verify post-merge falla tras el ff y antes del push. Dado que el gate C4 corre sobre el mismo commit, ese camino es teóricamente redundante (solo cubre swap/LKG). Se mantiene `git revert` como commit nuevo dentro de fence, sin push. Tras el revert, `dev` queda adelantado a origin y cualquier push posterior (AP-1) empujaría el commit malo y su revert: el reporte lo marca, y evolve bloquea el push (BLOCKED_GIT `dev_dirty_by_revert`) hasta que el usuario decida.
- **Divergencia de `dev`.** Con 4 sesiones Pragma que commitean en dev, el ff será imposible en cuanto dev avance. Es esperado: BLOCKED_GIT `dev_ahead` sin rebase.

## 7. Omisiones restantes
- **Condición 16 (presupuesto y runbook).**
  - **Playbook.** Cualquier cambio de texto del playbook (~2990/3000) lleva test de bytes en el mismo commit. Si no cabe, se compensa comprimiendo otro texto, no se sube el tope.
  - **Auditoría D-01b.** El test de B1 debe fallar de forma estable (xfail strict) hasta B9 y no depender del orden de herramientas.
  - **Regla dura.** El plan no modifica env vars ni puertos nuevos de forma que obligue a un script `agent_*`. `AEP_AUTOEVOL_MAX_CYCLES` es env var nueva: añadirla a la documentación/runbook correspondiente (SDD y, si existe, `agent_*`). Pragma verifica si hay script `agent_*` aplicable.
- **Tool Awareness.** El plan declara las herramientas disponibles, pero no el fallback si `bwrap` o `pueue` no están. Cubierto por `SANDBOX_UNAVAILABLE` más las condiciones 3 y 10. Semgrep/grep para C3 se resuelve con test AST.

## 8. Viabilidad de las 4 sesiones Pragma
- Cada sesión de 50 turnos con un commit por tarea es factible para P1 (B1–B4) y P2 (B5–B8).
- La sesión 3 (B9 + C1–C3) concentra el dogfood y la primera integración git. Es la de mayor riesgo, porque B9 es una prueba de aceptación que puede escalar a PLAN_GAP.
- La sesión 4 (C4–C7) crece con las condiciones 8, 10, 13 y 15. Recomiendo un checkpoint de Dokimos tras C3, con las pruebas git en repos temporales con remoto bare, antes de C4–C7.
- Estimación: 4 sesiones realistas. El plan no se acorta a 3.

## 9. Findings con ontología
- Arista B7→B3 invertida: `Ontology: dep | cascade | medium`
- ro-bind de REPO_ROOT expone `.git`/engine canónico: `Ontology: dep | systemic | high`
- Centinela y mapeo de WRONG_TREE: `Ontology: dep | vertical | high`
- Fence ausente en ff-merge/revert: `Ontology: interdep | horizontal | high`
- Gate async vs F3 (dispatcher fail-closed): `Ontology: interdep | systemic | high`
- "Árbol limpio" imposible con untracked: `Ontology: dep | omission | high`
- Idempotencia y tope en memoria: `Ontology: dep | omission | medium`
- Escaneo de B7 solo en `assert`: `Ontology: dep | vertical | medium`
- C6 y push tras revert: `Ontology: dep | omission | medium`

Rutas relevantes: `/home/ancruz/Documents/workspaces/agent-execution-plane/server.py` (líneas 3075–3125 y 5159–5260), `/home/ancruz/Documents/workspaces/agent-execution-plane/engine/threads_ops.py` (líneas 37 y 225–260), `/home/ancruz/Documents/workspaces/agent-execution-plane/aep_front.py` (líneas 140–165), `/home/ancruz/Documents/workspaces/agent-execution-plane/docs/pipeline/feature_20261106_182001_ont42_judge_evolve.md`.