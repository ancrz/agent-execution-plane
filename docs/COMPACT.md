# Context Compaction Guidance & Pipeline State — AEP

## 1. Directivas de Compactación (Preserve / Drop)

### Preserve:
- **Modo del Pipeline**: Full Pipeline activo (Topos Integrity Protocol, disciplina $A \to B$ acíclica, cero co-dependencias).
- **Hito Activo / Estado**: Milestone **ONT-24** completado, verificado y promocionado (`Task #132`, Score: `0.9500 TRUST`).
- **Arquitectura de Herramientas**: Invariante estricto de **15 herramientas FastMCP** (0 dispersión de herramientas).
- **Especificación OM-7 (IPC & Batch Mode)**:
  - Socket UNIX persistente: `/dev/shm/aep.sock` (AF_UNIX, framing delimitado por saltos de línea, cero fugas de descriptores `fd_delta == 0`).
  - Pool de sesiones en memoria: `/dev/shm/aep_pool/slot_<id>` (hasta 16 slots, TTL 60s, leasing concurrente atómico y desalojo seguro).
  - Ejecución por lotes efímera (Cloudflare-style): `playbook_run(action="batch")` y `playbook_run(action="run")` con piping inter-pasos (`$prev.*`, `$steps.<id>.*`), caché compartida en RAM multi-agente (`$cache.<key>`), y preservación incondicional de errores (`failed_steps`).
  - Proyección de campos en servidor (`select_fields`, `return_only`): Reducción de 80–95% de tokens descartando metadatos directamente en RAM, con fallback inteligente de dot-path.
- **Aislamiento de Concurrencia Multi-Agente**:
  - **Tríada Pico**: Compilación Go de Pico-Jenkins en slots `/dev/shm` + `os.replace` atómico (`GAP-OM23-1`), upsert atómico de tareas en Pico-Kanban con `transaction_immediate` (`GAP-OM23-2`), paridad de piping en Pico-Ansible (`GAP-OM23-3`), y cálculo de embeddings fuera de locks SQLite en el catálogo (`GAP-OM23-4`).
  - **Subsistemas Extra-Pico**: Serialización del ledger de auditoría SHA-256 con `_AUDIT_LOCK` + `transaction_immediate` (`engine/security.py`), sincronización de micro-snapshots `:memory:` bajo `_SNAPSHOT_LOCK` con `check_same_thread=False` (`engine/backup.py`), y *double-checked locking* del vectorizador de documentación (`server.py`).
- **Semántica Kali-MCP**: Enriquecimiento de `server._INSTRUCTIONS` y `engine/privilege.py` con recetas de despliegue (`WF-1` a `WF-6`), Regla de Compromiso #7 (*Zero-Token Multi-Agent RAM Handoff & Collision-Free Concurrency*), y 9 dominios en el plano de control (`aep_ctl`).
- **Estado de Git & Despliegue**: Commit `532473c` en ramas sincronizadas `dev` y `main` sobre `https://github.com/ancruz/agent-execution-plane.git`. Árbol de trabajo limpio (`working tree clean`).
- **Puertas de Verificación**: 69/69 pruebas unitarias e integración aprobadas (`pytest -v`), 0 errores de linter (`ruff check .`), `scripts/setup.sh --check` en estado `HEALTHY (Exit 0)`, sincronización `aep-sync.sh` completada para Antigravity (`agy`), Claude Code y Codex.
- **Integridad Visual**: 79 diagramas Mermaid validados a lo largo de 52 archivos Markdown (0 errores de balance o sintaxis).

### Drop:
- Salidas intermedias y volcados de consola de `pytest`, `ruff` o `git push`.
- Diagnósticos superados y errores de depuración ya corregidos (p. ej. `SNAPSHOT_NOT_FOUND` por límite FIFO resuelto en tests).
- Planes de trabajo previos reemplazados por la especificación e implementación final de ONT-24.

---

## 2. Archivos Modificados e Impacto Arquitectónico

1. `engine/security.py`: Serialización de `record_audit_event()` con `_AUDIT_LOCK` + `transaction_immediate` evitando bifurcaciones en el hash chain SHA-256.
2. `engine/backup.py`: Concurrencia segura en micro-snapshots `:memory:` con `_SNAPSHOT_LOCK` y `check_same_thread=False`.
3. `server.py`: Lock singleton en vectorizador de documentación y enriquecimiento semántico estilo Kali-MCP (`_INSTRUCTIONS`, recetas `WF-1..WF-6`, regla #7).
4. `engine/privilege.py`: Integración de regla #7 y receta `WF-6` en capacidades y playbooks tácticos.
5. `tests/test_spec_om7_ipc_batch.py`: Incorporación de `TestNonPicoSystemWideConcurrency` (23 tests del hito, 69 tests totales).
6. `README.md`: Actualización de arquitectura de 3 capas, especificación OM-7 y diagramas Mermaid.
7. `docs/sdd/sdd_om7_ipc_socket_pool_and_code_batch_mode.md`: Flujo del equipo multi-agente en memoria RAM.
8. `CHANGELOG.md`: Registro formal de versión `0.2.3`.
9. `docs/MILESTONES.md`: Gráfico de refuerzo de intenciones (M77–M80) y matriz de hitos actualizada.

---

## 3. Próximas Acciones
- Esperar siguiente requerimiento del usuario o nuevas especificaciones de casos de uso sobre el plano de ejecución AEP.
- Mantener el invariante de 15 herramientas FastMCP y verificación estricta de cero fugas en descriptores de archivo.
