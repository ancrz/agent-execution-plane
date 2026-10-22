# Índice de Documentación Técnica — Agent Execution Plane (AEP)

Este directorio alberga la especificación canónica, la justificación arquitectónica y los análisis de fuente de la verdad que rigen el proyecto **Agent Execution Plane (AEP)**.

---

## Documentos Disponibles

### 1. [architecture.md](file:///home/ancruz/Documents/workspaces/agent-execution-plane/docs/architecture.md)
* **Título:** Arquitectura Híbrida de Control de Sistema para Agentes de IA en Ubuntu
* **Propósito:** Documento fundacional que establece la fusión entre el **Camino A** (Plano C2 de bajo nivel en memoria), el **Camino B** (Plano asíncrono y de usuario con colas y serialización estructurada) y la adopción de los patrones de **Omarchy**.
* **Contenido clave:** Matriz de fusión técnica, límites del kernel de Linux, catálogo inicial de herramientas MCP y consideraciones de diseño.

### 2. [spec_artifact_engine.md](file:///home/ancruz/Documents/workspaces/agent-execution-plane/docs/spec_artifact_engine.md)
* **Título:** Evolutionary Artifact Engine Specification (EAES-v1)
* **Propósito:** Norma formal que prohíbe la generación de scripts ad-hoc de Bash y establece el estándar de **Artefactos Atómicos en Golang** gobernados por contratos **CUE**.
* **Contenido clave:** Los 5 Axiomas contra la alucinación, diagrama de estados del ciclo de vida del artefacto, DDL de SQLite para `artifacts.db` y protocolo de calidad con `golangci-lint` en modo JSON.

### 3. [re_sdd_and_gap_analysis.md](file:///home/ancruz/Documents/workspaces/agent-execution-plane/docs/re_sdd_and_gap_analysis.md)
* **Título:** Análisis de Fuente de la Verdad, Metodología RE as SDD y Matriz de Inspiración
* **Propósito:** Auditoría transparente de la realidad física del sistema, justificación del por qué aplicamos ingeniería inversa en lugar de acoplar frameworks ofensivos pesados, y análisis de lecciones aprendidas de repositorios de referencia.
* **Contenido clave:**
  * **Inventario sincero:** Qué está 100% operativo, qué fue transmutado y qué queda pendiente de cableado.
  * **RE as SDD:** Descarte del peso muerto de Sliver C2 y extracción de la syscall pura `memfd_create`.
  * **Matriz de inspiración:** Lecciones de `termux-linux-deployer` (seeding y aislamiento en espacio de usuario), `openclaw` (rigor de contratos y `AGENTS.md`) y `sdk-agent-pipeline` (Topos DAG integrity y prevención de co-dependencias).
  * **Hoja de ruta:** Pasos técnicos para el cierre definitivo de brechas.
