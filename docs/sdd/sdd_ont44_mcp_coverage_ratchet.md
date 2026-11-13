# SDD ONT-44: trinquete de cobertura del MCP

- **Estado**: VERIFIED (staged sobre `e0a9317`, sin commit)
- **Registro**: `docs/pipeline/feature_20261113_004026_mcp_coverage_reinforcement.md`
- **Modo**: Short

## 1. Problema

AEP se autodiagnostica con `autoevol(action="gaps")`. Al inicio del tramo había 120 omisiones de cobertura: superficie MCP expuesta sin test. El objetivo es que esa cifra sólo pueda bajar.

## 2. Trinquete `GAPS_BASELINE`

- Constante: `GAPS_BASELINE = 46` en `tests/test_ont41_coverage.py`.
- Aserción: `len(analysis.gaps) <= GAPS_BASELINE` sobre el grafo real del proyecto.
- Regla: al cubrir un gap, se baja la constante en el mismo cambio. Subirla exige una justificación en el comentario que la acompaña (el archivo ya lo exige para la subida de 103 a 122).
- Regla: un gap nuevo sin test hace fallar la suite. No se corrige cambiando la constante sino añadiendo cobertura.

## 3. Qué cuenta como `covers`

Confirmado empíricamente en esta tanda (comportamiento de `engine/threads_extractors.py`):

- Una arista `covers` desde un nodo `test` hacia una función o acción la cubre de forma **directa**.
- La cobertura **transitiva** se propaga por aristas de consumo; un nivel `none` indica que no hay cadena de cobertura.
- Una acción cuenta como cubierta si existe un nodo `action:` alias con arista `covers`.
- Los nodos públicos sin cobertura se cuentan en el resumen de cobertura.
- La capa de cobertura es de sólo lectura: no altera la raíz Merkle R ni los gaps.

Reglas prácticas verificadas: una arista `covers` hacia una acción solo nace de kwargs literales (`action="..."`, `domain="..."`), no de nombres parametrizados; un método de clase solo resuelve si se invoca como `Clase.metodo(instancia, ...)` o se referencia por su nombre calificado; una función suelta, por referencia directa al símbolo importado.

## 4. Reglas de tests sin mutar el host

- Los tests de efecto trabajan sobre directorios temporales (`tmp_path`) y bases de datos temporales. No escriben en la base de datos real del usuario.
- Las acciones mutantes se prueban comprobando un hash de la DB antes y después de la denegación.
- Las pruebas de Landlock y de sandbox se ejecutan dentro del propio mecanismo de confinamiento; no se amplían permisos del host.
- La suite no ejecuta acciones de sistema con efecto real (red, paquetes, servicios) fuera de mocks o de comprobaciones de denegación.

Estas reglas describen cómo se escribieron los tests de este tramo. Son una convención, no un mecanismo que las imponga.

## 5. Gating de backup por tier

- `BACKUP_MUTATING_ACTIONS` (en `engine/privilege.py`) lista las acciones que mutan el backup.
- `MIN_OCTAL` fija el tier mínimo. Bajo 6 la respuesta es `PERMISSION_DENIED`.
- El schema anunciado incluye `min_chmod_octal=6` para esas acciones.
- Excepción conocida: `micro_snapshot` y `clear_micro_snapshots` no tienen gate en servidor, porque operan sólo en RAM. El CLI `scripts/aep-ctl` sí los gatea. La diferencia queda documentada y no se corrige en este tramo.

## 6. `shared_exceptions` en el schema

- Las excepciones idénticas que aplican a tres o más acciones se pliegan en un bloque `shared_exceptions`, con una `legend` que explica la notación.
- Efecto: el schema summary baja de 1524 a 1278 tokens (D-04).
- Las acciones con excepciones distintas no se pliegan.

## 7. Residuo

- 15 tests antiguos sin referencia a código del proyecto.
- Gaps de tipo `asserts` (acción con test, sin aserción sobre el resultado).
- Sin `covers`: `aep_front.main`, `aep_front.create_front_server`, `aep_backend.main`, `BackendWorker`.
