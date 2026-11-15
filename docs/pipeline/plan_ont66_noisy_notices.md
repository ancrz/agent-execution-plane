# ONT-66 — AEP ruidoso: notificar al agente de turno lo que detecta (Short). ENCOLADO tras ONT-65 (publicación a main).
Usuario 2026-11-15: "encolalo como ONT-66 -> añadido debe ser ruidoso, debe notificarle a la agente de turno, cuando hay algo
que notificar, si el propio agente con el feedback de AEP debe poder notificar 'AEP reporta x, y ò Z, quieres mejorarlo?'"

RCA (orquestador, 2026-11-15): AEP detecta pero no anuncia. Hoy ni el claim_drift del README (ONT-63→64) ni la omisión gate8 se
notificaron: los halló un test y una consulta manual. Único canal: `reconcile_top` (server.py:6647) — solo en
discover(capabilities, terse); usa SOLO el análisis en caché (frío tras cada hot-swap); include_omissions=False; sin push MCP.

## Diseño (decidido)
T1 Análisis caliente: tras cada carga/hot-swap del backend (y al arrancar), lanzar en segundo plano (hilo/tarea, no bloquea
   ninguna llamada; fail-soft) th.analyze(REPO_ROOT) para poblar la caché. Re-análisis también si cambia el fingerprint de
   código en disco. Coste ~1 s fuera del camino crítico.
T2 Registro de avisos (engine/notices.py, nuevo): fuente única de "cosas que notificar" con id estable, severidad
   (INFO/WARN/ERROR según engine/telemetry), resumen ≤120 B y `next_action` concreto. Fuentes: gaps del análisis en caché
   (TODOS los tipos, incluidas omisiones: claim_drift, omission, codep…), señales del plano (front_stale, stale,
   last_reload_error, lkg drift), y reportes de campo promovidos (autoevol report). Estado por sesión de servidor:
   new | seen | acked; resuelto desaparece solo cuando el análisis ya no lo ve.
T3 RUIDOSO — piggyback en TODAS las respuestas: attach_envelope añade `aep_notice` a la respuesta de CUALQUIER tool mientras
   haya avisos no reconocidos (acked), en todas las verbosidades incluido terse:
   {"count": n, "top": ["claim_drift README tool_count 30≠17", ...≤3], "severity": max,
    "ask_user": "AEP reporta: <x>, <y> o <z>. ¿Quieres mejorarlo?",
    "next_action": "autoevol(action='spec', gap='<id>')" , "ack": "autoevol(action='ack', ids=[...])"}
   Tope ≤350 B (recorta top). No se suprime por repetición: se repite en cada respuesta hasta ack o resolución (eso es
   "ruidoso"). Un aviso NUEVO tras un ack vuelve a aparecer. `ask_user` está redactado para que el agente lo reenvíe tal cual
   al usuario. Excepción: las respuestas de `autoevol(action='ack'|'gaps'|'spec')` no duplican el bloque (ya tratan de ello).
T4 Push MCP: cuando el conjunto de avisos cambia (nuevo id o severidad sube), el front/backend emite una notificación MCP
   `notifications/message` (logging, level warning|error, logger "aep.notice") con el mismo `ask_user`; la
   capability `logging` declarada. Si el cliente no la muestra, T3 garantiza que el agente lo vea igual.
T5 Acciones: `autoevol(action='notices')` lista avisos con estado; `autoevol(action='ack', ids=[...] | all=True)` los marca
   acked (tier >= 4r--, por sesión de servidor; no muta el repo ni la BD real salvo el ledger con tier >= 6rw-).
T6 orient y discover(capabilities, terse|summary) incluyen `aep_notice` (mismo bloque) y `gaps_open`; reconcile_top se
   mantiene. discover(use_case) también lo lleva por T3.
T7 Instrucciones MCP: una línea (≤120 B, _INSTRUCTIONS ≤ 9500 B): "If a response has aep_notice, relay its ask_user to the
   user before continuing." Playbook WF-0: tras orient, atender aep_notice.

## Reglas
Budgets existentes: el bloque aep_notice SOLO aparece si hay avisos; los tests de budget corren sin avisos (o se excluye el
bloque del cómputo con justificación escrita) — NO subir budgets en silencio. Estados nuevos clasificados (test_ont57).
Sin avisos → respuestas byte-idénticas a hoy (test). Hot-swap: la tarea de análisis no debe retrasar el swap ni filtrar FDs
(criterio de test C6). Tests con AEP_DATA_HOME temporal; no escribir "<n> herramientas/tools/capacidades" en docs.
Tests: drift sembrado en una copia → aep_notice aparece en una tool cualquiera (p. ej. process_inspect) con ask_user;
ack lo silencia; drift nuevo reaparece; resolución lo retira; push MCP emitido una vez por cambio (cliente MCP de prueba);
sin avisos, respuestas idénticas; análisis caliente tras swap en <3 s sin bloquear.
