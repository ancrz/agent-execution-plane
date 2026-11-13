# SDD ONT-45: residuo del grafo de hilos por criticidad (Topos)

- **Estado**: VERIFIED (staged sobre `e1d661f`, sin commit)
- **Registro**: `docs/pipeline/feature_20261113_080406_ont45_topos_residue.md`
- **Modo**: Short

## 1. Niveles

| Nivel | Criticidad | Relación Topos | Reach |
|-------|-----------|----------------|-------|
| N1 | Contrato de `aep_ctl` sin declarar (26 acciones) | Dependencia (README consume código) | 4 |
| N2 | Núcleo del plano vivo sin `covers` | Interdependencia documentada (protocolo de cable) entre `aep_front` y `aep_backend`; sin co-dependencia | 2 |
| N3 | Puntos de entrada | Dependencia hacia N2 | 1 |
| N4 | Tests sin referencia a código | Dependencia (test → código) | 1 |

Criterio de orden: primero lo que un consumidor (LLM o humano) lee como contrato; luego lo que ejecuta el proceso; por último lo que sólo prueba.

## 2. Cómo nace cada arista (verificado en `engine/threads_extractors.py`)

- **`asserts` desde claim doc**: el extractor escanea sólo `README.md` y `server._INSTRUCTIONS`. Una línea que cita entre comillas o backticks el dominio y la acción produce `claim → action`. `docs/` no cuenta.
- **`asserts` desde budget**: un test con kwargs literales `domain=` y `action=` cuyo id exista en el schema. Un id desconocido cae a `*` y duplica la clave D-04; por eso cada id se afirma.
- **`covers`**: un test cuyo AST referencia el símbolo. Las acciones sólo nacen de kwargs literales; los métodos como `Clase.metodo`.
- **Drift**: los claims `doc` NO se comparan en `claim_drift` (`_DRIFT_KINDS` = `tool_count`, `capability_count`, `wf_range`, `version`). El budget es la única mitad que detecta regresión.

## 3. Reglas de budgets por acción

1. Sólo acciones de lectura. Nunca mutantes.
2. Descartar cualquier acción cuyo resultado dependa del host (interfaces, arp, disks).
3. Límite = medido en este host × 1.5, redondeado, y < 1500.
4. Afirmar que el id generado no es `*` (existe `budget:aep_ctl:<dominio>.<accion>:summary` en el grafo).

## 4. Guarda de fd 1

`import aep_backend` ejecuta `os.dup2(sys.stderr.fileno(), 1)` y reasigna `sys.stdout` al importar. La regla es:

- Importar siempre dentro de `_Fd1Guard` (`tests/test_cov_live_plane_core.py`): guarda `os.dup(1)` y `sys.stdout`, importa, restaura en `finally`.
- Afirmar que el fd 1 queda restaurado tras la importación.
- Resetear `BACKEND_META` tras cada test.

## 5. Reglas de edición del README

- Sólo añadir líneas. No editar líneas existentes: el id del claim hashea el texto.
- No escribir conteos desnudos ("26 acciones", "17 tools") en formas que casen `_text_claims`.
- Las filas de contrato citan literalmente `aep_ctl(domain="...", action="...")`.

## 6. Verificación

- `threads.analyze` antes y después: cero claims nuevos en `_DRIFT_KINDS`, cero `claim_drift`, cero co-dependencias.
- `test_d11_dynamic_counts` en verde; D-04 intacto (< 1500 tokens).
- Gaps: 46 a 1 (`GAPS_BASELINE=1`).
