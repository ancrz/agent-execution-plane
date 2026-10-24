<a id="top"></a>

# Agent Execution Plane (AEP)

**Plano de Control de Sistema y Suite de Ejecución de Alta Resiliencia para Agentes de IA sobre Ubuntu/Linux**

> [!IMPORTANT]
> **Arquitectura de Runtime y Plano de Ejecución para Agentes**
> AEP es una **suite de ingeniería de sistemas y runtime agéntico** orientada a
> proveer un plano de ejecución determinista, no-bloqueante, tipado y asíncrono para
> LLMs y agentes autónomos, fundamentado en primitivas estándar de bajo nivel del
> kernel Linux (namespaces, memoria anónima volátil, descriptores y telemetría dinámica)
> sobre entornos Ubuntu/Linux.

---

## Índice

1. [El Reto de Ejecución: Consola Tradicional vs. Runtime Agéntico](#1-el-reto-de-ejecución-consola-tradicional-vs-runtime-agéntico)
2. [Arquitectura Global (4 Capas)](#2-arquitectura-global-4-capas)
   - [Desglose Arquitectónico de las 4 Capas](#desglose-arquitectónico-de-las-4-capas)
   - [Especificación Detallada de Capas](#especificación-detallada-de-capas)
3. [Primitivas del Kernel Linux de Alto Rendimiento → Capacidades Agénticas Resilientes](#3-primitivas-del-kernel-linux-de-alto-rendimiento--capacidades-agénticas-resilientes)
4. [Catálogo de 15 Herramientas MCP](#4-catálogo-de-15-herramientas-mcp)
   - [Tablas de Referencia Maestra de las 15 Herramientas FastMCP](#tablas-de-referencia-maestra-de-las-15-herramientas-fastmcp)
   - [Ciclo de Vida y Encadenamiento de Capacidades (Skill Chaining)](#ciclo-de-vida-y-encadenamiento-de-capacidades-skill-chaining)
5. [Memoria Semántica Híbrida (sqlite-vec)](#5-memoria-semántica-híbrida-sqlite-vec)
   - [Persistencia y cómo la lee el agente](#persistencia-y-cómo-la-lee-el-agente)
   - [Pico-Kanban: ponderación de artefactos (idioma agéntico)](#pico-kanban-ponderación-de-artefactos-idioma-agéntico)
6. [Mejoras de Omarchy (5 Specs Agnósticas)](#6-mejoras-de-omarchy-5-specs-agnósticas)
   - [Matriz de Especificaciones Agnósticas de Omarchy](#matriz-de-especificaciones-agnósticas-de-omarchy)
   - [Especificaciones Técnicas Detalladas (SPEC-OM-1 a SPEC-OM-5)](#especificaciones-técnicas-detalladas-spec-om-1-a-spec-om-5)
   - [Arquitectura y Flujo de Datos de las Mejoras Omarchy](#arquitectura-y-flujo-de-datos-de-las-mejoras-omarchy)
7. [Modelo de Privilegio de Dos Niveles + Manifiesto](#7-modelo-de-privilegio-de-dos-niveles--manifiesto)
8. [Auto-Plug: Autogestión Atómica del MCP](#8-auto-plug-autogestión-atómica-del-mcp)
9. [Entorno Shell-Agnóstico](#9-entorno-shell-agnóstico)
10. [Instalación desde Cero](#10-instalación-desde-cero)
11. [Estructura del Repositorio](#11-estructura-del-repositorio)
12. [Inventario Sincero de la Fuente de la Verdad](#12-inventario-sincero-de-la-fuente-de-la-verdad)
13. [RE as SDD y Matriz de Inspiración](#13-re-as-sdd-y-matriz-de-inspiración)

---

## 1. El Reto de Ejecución: Consola Tradicional vs. Runtime Agéntico

La consola Unix tradicional fue concebida para operadores humanos interactivos, un paradigma
fundamentalmente hostil para la ejecución autónoma de modelos de lenguaje (LLMs):
- **Procesos bloqueantes**: Pagers interactivos (`less`, `more`), prompts interactivos imprevistos
  y bloqueos de `stdin` detienen indefinidamente los subprocesos del agente.
- **Salida desestructurada y desalineada**: El parseo de texto plano vía pipelines ad-hoc (`grep`,
  `awk`, `sed`) introduce fragilidad sintáctica y consume tokens en ruido de formato en lugar de
  señal estructurada.
- **Dispersión y contención en disco**: La creación de binarios o scripts temporales en el sistema de
  archivos introduce latencia de sincronización de E/S, fragmentación, colisiones de nombres y
  residuos que requieren mantenimiento secundario.

AEP desacopla al agente de la terminal interactiva mediante dos mecanismos principales: **despacho
asíncrono de colas sin bloqueo** (vía Pueue, entregando un `task_id` inmediato) y **ejecución volátil
en memoria RAM** mediante descriptores anónimos (`memfd_create` + `/proc/self/fd/`).

Esta técnica de staging en memoria anónima no es un artificio exótico, sino una **primitiva
estándar de ingeniería de sistemas Linux de alto rendimiento** ampliamente adoptada en infraestructuras
críticas:
- **Compositores Wayland (Weston / wlroots)**: Transferencia zero-copy de buffers de memoria compartida
  (`wl_shm`) entre clientes y compositor mediante paso de descriptores `memfd_create` sobre sockets de
  dominio Unix (`AF_UNIX`).
- **QEMU / KVM (`memory-backend-memfd`)**: Asignación de memoria anónima para RAM invitada en
  virtualización de alto rendimiento, habilitando memoria compartida inter-VM (`ivshmem`) y
  descriptores compartidos para `vhost-user` con DPDK.
- **PulseAudio & PipeWire**: Transferencia de buffers de streaming de audio en tiempo real y cero copia
  entre el servidor de medios y los clientes sin cuellos de botella de sincronización en el sistema de archivos.

```mermaid
flowchart LR
    subgraph Hostile["Entorno de Consola Tradicional (Fricciones de Automatización)"]
        H1["Subprocesos bloqueantes<br/>(pagers, prompts, sudo interactivo)"]
        H2["Texto plano desalineado<br/>(awk/sed/grep) = tokens quemados"]
        H3["Huella en disco<br/>(temporales dispersos)"]
    end
    subgraph AEP["Resolución AEP (Runtime Agéntico Determinista)"]
        S1["Ejecución en RAM<br/>memfd_create + fexecve"]
        S2["Salida tipada JSON<br/>+ memoria semántica"]
        S3["Colas asíncronas<br/>Pueue (task_id inmediato)"]
    end
    H1 --> S3
    H2 --> S2
    H3 --> S1
```

[↑ Volver arriba](#top)

---

## 2. Arquitectura Global (4 Capas)

```mermaid
flowchart TD
    subgraph L3["Capa 3: Interfaz Agéntica"]
        Agent["Agente de IA (Claude Code / Antigravity / Codex / Gemini)"]
        MCP["Servidor FastMCP (server.py) — 32 tools"]
        Agent -->|stdio / JSON-RPC| MCP
    end
    subgraph L2["Capa 2: Motores (engine/)"]
        Catalog["catalog.py + embedder.py<br/>(memoria semántica sqlite-vec)"]
        Crash["crash_router.py"]
        Docs["docs_vectorizer.py"]
        Headless["headless_display.py"]
        Priv["privilege.py<br/>(FULL / DIMINISHED)"]
        Topos["topos_guard.py"]
        MCP --> Catalog & Crash & Docs & Headless & Priv & Topos
    end
    subgraph L1["Capa 1: Herencia de Shell (agnóstica)"]
        Env["config/shell/aep-env.sh<br/>(bash / zsh / sh)"]
        Ctl["scripts/aep-ctl"]
        Agent -.->|subproceso| Env
    end
    subgraph L0["Capa 0: Kernel y Runtime Ubuntu"]
        K1["RAM: memfd_create + fexecve"]
        K2["bwrap / eBPF / coredumpctl"]
        K3["Pueue daemon · venv ONNX"]
        Catalog --> K1
        Crash --> K2
        Headless --> K3
    end
```

### Desglose Arquitectónico de las 4 Capas

| Capa | Nivel de Abstracción | Módulos & Componentes | Primitivas Subyacentes & Protocolos | Garantías & Rol en el Runtime |
| :---: | :--- | :--- | :--- | :--- |
| **Capa 3** | **Interfaz Agéntica (RPC)** | `server.py` (FastMCP)<br/>`aep_capabilities` | JSON-RPC 2.0 sobre `stdio`<br/>FastMCP SDK | Punto de entrada unificado para LLMs y agentes (Claude Code, Antigravity `agy`, OpenAI Codex, Gemini CLI). Expone 15 herramientas atómicas, tipadas y no-bloqueantes. |
| **Capa 2** | **Motores de Ejecución y Memoria (`engine/`)** | `catalog.py`<br/>`embedder.py`<br/>`kanban.py`<br/>`crash_router.py`<br/>`docs_vectorizer.py`<br/>`headless_display.py`<br/>`topos_guard.py`<br/>`privilege.py` | SQLite 3 (WAL mode)<br/>`sqlite-vec` extension<br/>ONNX Runtime (bge-small)<br/>Playwright Chromium (`/dev/shm`) | Núcleo de lógica agéntica: memoria semántica híbrida, gestión de tareas Pico-Kanban con ponderación multidimensional, enrutamiento proactivo de coredumps, verificación topológica de grafos DAG y gobierno de privilegios en dos tiers (`FULL`/`DIMINISHED`). |
| **Capa 1** | **Herencia de Shell Agnóstica** | `config/shell/aep-env.sh`<br/>`scripts/install-shell-env.sh`<br/>`scripts/aep-ctl` | POSIX Shell estándar (`sh`, `bash`, `zsh`, `dash`)<br/>Variables de entorno (`PAGER=cat`) | Sanitiza el entorno de ejecución de subprocesos contra bloqueos (`stdin`, pagers interactivos). CLI determinista `aep-ctl` para control del sistema mediante contratos JSON tipados con autodocumentación (`--schema`). |
| **Capa 0** | **Kernel Linux & Runtime Ubuntu** | Primitivas del Kernel Linux<br/>`Pueue` daemon (musl)<br/>`bwrap` (Bubblewrap)<br/>`systemd` / `journald` | `memfd_create(2)`<br/>Linux User & PID Namespaces<br/>eBPF / kprobes (`bpftrace`)<br/>`systemd-coredump` / `ptrace` | Cimientos de alto rendimiento y bajo nivel: staging de binarios ELF volátiles en RAM sin residuo en disco, aislamiento en submilisegundos mediante namespaces no-privilegiados, colas asíncronas no-bloqueantes y telemetría de kernel no-invasiva. |

#### Especificación Detallada de Capas

1. **Capa 3: Interfaz Agéntica (FastMCP RPC)**:
   - **Protocolo y Transporte**: Opera sobre la especificación estándar Model Context Protocol (MCP) utilizando el framework **FastMCP** en `server.py`. Toda la comunicación se realiza a través de `stdio` mediante mensajes estructurados **JSON-RPC 2.0**, eliminando la necesidad de exponer puertos TCP o gestionar autenticación de red local insegura.
   - **Autodescripción en Primera Vista**: La herramienta fundacional `aep_capabilities()` actúa como apretón de manos inicial, devolviendo un manifiesto estilo `chmod`/777 (`r`=sensar, `w`=actuar, `x`=ejecutar). Esto instruye al LLM sobre sus facultades operativas inmediatas según el nivel de privilegio detectado (`FULL` o `DIMINISHED`).
   - **Multi-Cliente Universal**: Diseñado para ser consumido de forma idéntica por múltiples agentes autónomos (Claude Code, Antigravity `agy`, OpenAI Codex, Gemini CLI) mediante el launcher unificado `scripts/aep-mcp-launch.sh`.

2. **Capa 2: Motores de Ejecución y Memoria (`engine/`)**:
   - **Memoria Semántica Híbrida (`catalog.py`, `embedder.py`)**: Persiste metadatos de artefactos en `~/.local/share/agent-os/artifacts.db` con modo WAL. Implementa recuperación en dos niveles: coincidencia exacta por hash SHA-256 en tiempo O(1), y búsqueda por similitud de coseno mediante la extensión `sqlite-vec` y el modelo local `bge-small-en-v1.5` sobre ONNX Runtime.
   - **Pico-Kanban de Ponderación (`kanban.py`)**: Mantiene un tablero de estados abstracto (`BACKLOG` → `SYNTHESIZED` → `LINTED` → `CANARY` → `PROMOTED`/`REJECTED`) para estructurar actividades complejas en tareas atómicas y ponderar artefactos con un motor de confianza multidimensional (`quality`, `reliability`, `experience`, `recency`) con veto por fallos.
   - **Enrutamiento Proactivo de Fallos (`crash_router.py`)**: Interroga a `coredumpctl` periódicamente, deduplicando caídas mediante huellas hash compuestas (`pid:timestamp:executable`) para suministrar al agente alertas tempranas antes de que ejecute mutaciones en el sistema.
   - **Vectorización de Documentación (`docs_vectorizer.py`)**: Ingiere y segmenta páginas de manual `man` de Ubuntu en párrafos, vectorizándolos localmente en `system_docs.db` para resolver la sintaxis exacta de utilidades de sistema en menos de 5 ms sin consultas web.
   - **Actuador Visual Headless (`headless_display.py`)**: Orquesta instancias de Chromium sin cabeza vía Playwright, permitiendo renderizar URLs y capturar pantallas directamente en memoria RAM (`/dev/shm`) codificadas en Base64 para inspección visual automatizada.
   - **Guardián Topológico (`topos_guard.py`)**: Aplica el Topos Integrity Protocol analizando grafos dirigidos acíclicos de tareas para certificar ausencia de ciclos o co-dependencias (A <-> B) antes de autorizar la ejecución.
   - **Control de Privilegio (`privilege.py`)**: Detecta dinámicamente el contexto de permisos (`euid == 0` o `sudo -n true`), garantizando que las herramientas degraden elegantemente (*fail-soft*) a espacio de usuario sin lanzar excepciones no controladas.

3. **Capa 1: Herencia de Shell Agnóstica**:
   - **Sanitización de Entorno POSIX (`config/shell/aep-env.sh`)**: Archivo de entorno universal que fuerza `PAGER=cat`, `MANPAGER=cat`, `DEBIAN_FRONTEND=noninteractive` y exporta rutas críticas al `PATH`. Garantiza que cualquier subproceso hijo no se congele esperando interacción en terminales interactivas.
   - **Instalación Idempotente Multi-Shell (`scripts/install-shell-env.sh`)**: Inyecta selectores atómicos con bloques de control en `~/.bashrc`, `~/.zshenv` y `~/.profile`, soportando indistintamente Bash, Zsh y Dash sin requerir frameworks de shell de terceros.
   - **Plano de Control CLI Determinista (`scripts/aep-ctl`)**: Utilidad modular en Python stdlib que expone subdominios (`service`, `network`, `storage`, `package`). Toda invocación genera salida JSON estructurada y soporta introspección de contratos vía `--schema`.

4. **Capa 0: Kernel Linux y Runtime de Sistema**:
   - **Memoria Anónima Volátil (`memfd_create`)**: Primitiva nativa del kernel Linux (disponible desde glibc 2.27 / kernel 3.17) que permite alojar y ejecutar código binario ELF puramente en RAM a través de `/proc/self/fd/`, eludiendo el subsistema de archivos en disco secundario.
   - **Aislamiento por Namespaces (`bwrap`)**: Utiliza Bubblewrap para confinar ejecuciones potencialmente peligrosas dentro de namespaces no-privilegiados de usuario, montaje, PID y red, con sistemas de archivos de solo lectura y directorios `/tmp` volátiles en memoria.
   - **Observabilidad Dinámica (`bpftrace` / eBPF)**: Permite adjuntar sondas kprobes y tracepoints en caliente al núcleo para contabilizar llamadas al sistema, monitorizar aperturas de ficheros o rastrear conexiones TCP con scripts curados de solo-lectura y auto-terminación.
   - **Forense Post-Mortem de Sistema**: Utilidades nativas `systemd-coredump` y `journalctl` para recuperación de volcados de memoria, extracción de trazas de pila e inspección de logs de eventos críticos a nivel de sistema.
   - **Gestor de Colas Asíncronas (`Pueue`)**: Demonio de ejecución en segundo plano compilado estáticamente con `musl`, capaz de gestionar colas de tareas con grupos y límites de paralelismo sin bloquear el flujo conversacional del agente.

[↑ Volver arriba](#top)

---

## 3. Primitivas del Kernel Linux de Alto Rendimiento → Capacidades Agénticas Resilientes

Las primitivas de bajo nivel del kernel Linux se estructuran y exponen como capacidades de
ejecución agéntica de alta resiliencia gobernadas por un modelo de privilegios de dos niveles.
**Todas verificadas end-to-end.**

```mermaid
flowchart LR
    subgraph Off["Primitiva del Kernel e Ingeniería de Sistemas"]
        O1["Staging de ejecutables ELF en memoria anónima (memfd_create)"]
        O2["Introspección dinámica de hilos y descriptores (/proc, ptrace)"]
        O3["Aislamiento estricto de namespaces de Linux (bwrap)"]
        O4["Análisis forense post-mortem de coredumps y señales"]
        O5["Sondas dinámicas de observabilidad en kernel (eBPF / kprobes)"]
        O6["Auditoría de grafos dirigidos acíclicos (DAG de dependencias)"]
        O7["Despacho asíncrono no-bloqueante y control de colas"]
    end
    subgraph Ag["Capacidad agéntica AEP (tool MCP)"]
        A1["artifact_execute_in_ram"]
        A2["fd-rescuer (rescate de hilos)"]
        A3["sandbox_run (bwrap efímero)"]
        A4["diagnose_system_crashes (RCA)"]
        A5["kernel_trace (observabilidad)"]
        A6["topos_audit_dag (anti-codependencia)"]
        A7["async_job_dispatch (Pueue)"]
    end
    O1 --> A1
    O2 --> A2
    O3 --> A3
    O4 --> A4
    O5 --> A5
    O6 --> A6
    O7 --> A7
```

| Primitiva del Kernel / Runtime | Clasificación en Ingeniería de Sistemas | Capacidad Agéntica Resiliente (Tool MCP) | Estado |
| :--- | :--- | :--- | :--- |
| `memfd_create` (glibc 2.27+) | Staging en memoria anónima volátil (cero I/O en disco) | `artifact_execute_in_ram`: Inyección y ejecución directa en RAM | ✅ Operativo |
| `/proc/$PID/fd` + `ptrace` | Introspección no-destructiva y recuperación de hilos | `fd-rescuer`: Rescate no-invasivo de descriptores y estado colgado | ✅ Operativo |
| `bwrap` (Linux namespaces) | Sandbox efímero no-privilegiado (user, pid, mount, net) | `sandbox_run`: Aislamiento determinista en sub-milisegundo | ✅ Operativo |
| `coredumpctl` + `libunwind` | Triaje post-mortem automatizado de coredumps y stack traces | `diagnose_system_crashes`: RCA autónomo y fail-soft | ✅ Operativo |
| eBPF (`bpftrace`) | Telemetría y observabilidad dinámica de kernel no-invasiva | `kernel_trace`: Trazado seguro en tiempo de ejecución | ✅ Operativo (FULL) |
| Teoría de Grafos (DAG) | Análisis de acoplamiento topológico y detección de ciclos | `topos_audit_dag`: Guardián Topos anti-codependencia | ✅ Operativo |
| Cola asíncrona (`Pueue`) | Despacho de tareas basado en eventos y control sin bloqueo | `async_job_dispatch` / `async_job_inspect`: Ejecución en background | ✅ Operativo |

> **Nota sobre `memfd_create(2)`**: Esta primitiva de memoria anónima es el estándar de la
> industria para comunicación y ejecución de alto rendimiento sin sobrecarga de sistema de archivos,
> utilizada por **Wayland** (Weston/wlroots para buffers `wl_shm`), **QEMU / KVM** (asignación de
> RAM invitada para `ivshmem` y `vhost-user`) y **PulseAudio & PipeWire** (buffers de audio en tiempo real).

[↑ Volver arriba](#top)

---

## 4. Catálogo de 15 Herramientas MCP

```mermaid
flowchart TD
    Root["aep_capabilities()<br/>👉 PRIMERA LLAMADA: manifiesto de autonomía"]
    Root --> G1 & G2 & G3 & G4 & G5
    subgraph G1["Artefactos evolutivos"]
        T1["artifact_query (semántico)"]
        T2["artifact_hydrate"]
        T3["artifact_lint_and_build"]
        T4["artifact_execute_in_ram"]
    end
    subgraph G5["Pico-Kanban (ponderación)"]
        T15["kanban_board"]
        T16["kanban_task_create"]
        T17["kanban_advance"]
        T18["kanban_promote"]
    end
    subgraph G2["Ejecución y async"]
        T5["sandbox_run"]
        T6["async_job_dispatch"]
        T7["async_job_inspect"]
    end
    subgraph G3["Observabilidad / forense"]
        T8["diagnose_system_crashes"]
        T9["check_crash_alerts"]
        T10["kernel_trace (eBPF)"]
    end
    subgraph G4["Gestión de sistema (Omarchy)"]
        T11["aep_ctl"]
        T12["query_system_docs"]
        T13["visual_inspect"]
        T14["topos_audit_dag"]
    end
```

### Tablas de Referencia Maestra de las 15 Herramientas FastMCP

El plano expone 15 herramientas RPC organizadas en dominios operacionales más el punto de entrada raíz. Todas retornan cadenas JSON tipadas y deterministas, garantizando cero fallos no controlados (*fail-soft*).

#### Punto de Entrada & Manifiesto de Autonomía (Root)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `aep_capabilities` | `FULL` / `DIMINISHED` | `aep_capabilities() -> str`<br/>*(Sin parámetros)* | Evalúa `euid == 0` y disponibilidad de `sudo -n`. Genera un manifiesto en tríada octal estilo `chmod` (`r`=sensar, `w`=actuar, `x`=ejecutar) mapeando 13 capacidades agénticas con su alcance (`self`, `system`, `kernel`). | `{"what_is_this": str, "capability_tier": "FULL"|"DIMINISHED", "privilege_mode": str, "capabilities": {...}}` | Siempre retorna JSON determinista válido. Cero excepciones. |

#### Dominio 1: Artefactos Evolutivos & Ciclo en Memoria (4 Herramientas)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `artifact_query` | `DIMINISHED` | `artifact_query(intent: str, category: str) -> str` | Recuperación en 2 niveles: Tier 1 busca coincidencia exacta por hash SHA-256 en O(1); Tier 2 aplica embedding local ONNX (`bge-small-en-v1.5`) y búsqueda KNN coseno en `sqlite-vec` (umbral ≤ 0.32). | Hit: `{"status": "CACHE_HIT", "artifact_id": str, "name": str, "retrieval_mode": "exact_hash"|"semantic_cosine", ...}`<br/>Miss: `{"status": "CACHE_MISS", "available_templates": [...], ...}` | Si `sqlite-vec` o el modelo no están disponibles, degrada transparentemente a búsqueda exclusiva por hash. |
| `artifact_lint_and_build` | `DIMINISHED` | `artifact_lint_and_build(action: str = "build", name: Optional[str] = None, intent: Optional[str] = None, category: Optional[str] = None, go_source: Optional[str] = None, template_name: Optional[str] = None, source_template: Optional[str] = None, params: Optional[Dict[str, Any]] = None, cue_contract: str = "", limit: int = 5) -> str` | Punto único para consultar catálogo de plantillas (`catalog`), rankear plantillas por relevancia (`select`), hidratar código Go (`hydrate`), y compilar binarios con validación estática `go vet`/`golangci-lint` (`build`), incluyendo atajo ergonómico de 1 paso plantilla->binario. | JSON tipado dependiente de la acción (`status`, `templates`, `matches`, `go_source`, `artifact_id`, `binary_path`). | Respuestas estructuradas con `status: "PARAM_ERROR"` ante parámetros faltantes, `status: "HYDRATE_ERROR"` ante fallos de plantilla, e `status: "INVALID_ACTION"` ante acciones no reconocidas. Cero excepciones no controladas. |
| `artifact_execute_in_ram` | `DIMINISHED` | `artifact_execute_in_ram(name: str, args: Optional[List[str]] = None) -> str` | Carga el binario ELF en un descriptor anónimo volátil vía `memfd_create` y lo ejecuta directamente en RAM mediante `/proc/self/fd/<fd>`. Mide latencia y actualiza métricas históricas de confiabilidad en SQLite. | `{"status": "SUCCESS"|"EXEC_FAILED", "exit_code": int, "latency_ms": float, "output": Any, "metric_recorded": bool}` | Códigos de salida distintos de cero o errores de ejecución retornan JSON con `stderr` y alimentan la tasa histórica de fallo. |
| `artifact_catalog` | `DIMINISHED` | `artifact_catalog(category: Optional[str] = None, query: Optional[str] = None, limit: int = 10) -> str` | Descubrimiento del catálogo: 'qué soluciones tengo'. Con `query`, top-K semántico (embeddings auto-indexados); sin `query`, ranking por confianza (`reusable` + `promotion_score` + éxito). Incluye `capability_tier`. | `{"status": "OK", "capability_tier": str, "count": int, "artifacts": [{"name": str, "reusable": int, "promotion_score": float, "semantic_distance"?: float}]}` | Si falta `sqlite-vec`/embedder, degrada a ranking relacional por confianza. |

#### Dominio 2: Pico-Kanban & Ponderación Multidimensional (1 Herramienta Unificada)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `kanban_board` | `DIMINISHED` | `kanban_board(action: str = "board", include_archived: bool = False, task_id: Optional[int] = None, title: str = "", intent: str = "", category: str = "", artifact_name: Optional[str] = None, to_state: str = "", lint_passed: Optional[bool] = None, canary_passed: Optional[bool] = None, note: Optional[str] = None, reason: Optional[str] = None, states: Optional[List[str]] = None, max_score: Optional[float] = None, apply: bool = False) -> str` | Punto único para consultar tablero (`board`), crear tareas (`create`), avanzar estados (`advance`), evaluar y promover (`promote`), degradar explícitamente (`demote`), reevaluar flota (`reevaluate`) y archivar/desarchivar de forma reversible (`archive`/`unarchive`). | JSON tipado dependiente de la acción (`status`, `lanes`, `task_id`, `promotion_score`, `verdict`, `candidates`). | Respuestas estructuradas con `status: "PARAM_ERROR"` ante parámetros faltantes e `status: "INVALID_ACTION"` ante acciones no reconocidas. Cero excepciones no controladas. |

#### Dominio 3: Aislamiento & Ejecución Asíncrona (2 Herramientas)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `sandbox_run` | `DIMINISHED` | `sandbox_run(command: str, share_net: bool = True) -> str` | Ejecuta comandos arbitrarios dentro de un sandbox `bwrap` efímero con directorios raíz de solo-lectura (`/usr`, `/bin`, `/lib`), un `/tmp` en RAM tmpfs y namespaces de PID/red aislados. | `{"exit_code": int, "stdout": str, "stderr": str}`<br/>Error: `{"status": "ERROR", "error": str}` | Si `bwrap` falta o el subproceso falla, captura la salida estándar y error sin lanzar excepciones. |
| `async_job_dispatch` | `DIMINISHED` | `async_job_dispatch(action: str = "dispatch", command: Optional[str] = None, label: Optional[str] = None, group: str = "default", working_dir: Optional[str] = None, task_id: Optional[int] = None, lines: int = 50) -> str` | Punto único para encolar comandos asíncronos en Pueue (`dispatch`) o consultar estado y logs estructurados (`inspect` / `status` / `log`). Incorpora auto-start desacoplado de pueued y fail-soft DEGRADED. | JSON tipado dependiente de la acción (`status`, `task_id`, `group`, `command`, cola Pueue o log de tarea). | Respuestas estructuradas con `status: "PARAM_ERROR"` ante parámetros faltantes, `status: "DEGRADED"` ante ausencia de daemon, y `status: "INVALID_ACTION"` ante acciones no reconocidas. Cero excepciones. |

#### Dominio 4: Forense de Crashes & Observabilidad de Kernel (2 Herramientas)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `diagnose_system_crashes` | `FULL` / `DIMINISHED` | `diagnose_system_crashes(action: str = "diagnose", limit: int = 5, resolve_after_report: bool = False) -> str` | Forense de crashes unificado: acción `"diagnose"` (default) inspecciona coredumps y errores críticos de journalctl; acción `"alerts"` (alias `"check"`) realiza polling proactivo de alertas en `crash_events` sin interrumpir. | `{"status": "OK"|"DEGRADED", "scope": "system"|"user", ...}` / `{"status": "OK", "new_crashes_synced": int, "alerts": [...]}` | Subproceso aislado (`stdin=DEVNULL`, `close_fds=True`, `timeout=15`). Degrada a `DEGRADED` si faltan fuentes de systemd. Cero excepciones. |
| `kernel_trace` | `FULL` | `kernel_trace(mode: str = "syscall_count", duration_sec: int = 3) -> str` | Observabilidad no-invasiva en kernel vía `bpftrace` (`syscall_count`, `file_opens`, `tcp_connect`). Ejecuta scripts curados de solo-lectura con salida automática tras `duration_sec` (1 a 30 s). | `{"status": "OK", "capability_tier": "FULL", "mode": str, "duration_sec": int, "counts": {...}}` | Requiere `CAP_BPF` / `sudo -n`. Si se invoca en `DIMINISHED`, responde `status: "DEGRADED"` informando del requerimiento. |

#### Dominio 5: Gestión de Sistema & Primitivas Omarchy (4 Herramientas)

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `aep_ctl` | `FULL` / `DIMINISHED` | `aep_ctl(domain: str, action: str, name: Optional[str] = None) -> str` | Enrutador determinista hacia `scripts/aep-ctl` para `service`, `network`, `storage` y `package`. Lecturas no requieren privilegios; mutaciones de servicios en `DIMINISHED` usan `systemd --user`, en `FULL` usan `sudo -n`. | JSON tipado estandarizado dependiente del dominio (`status`, `properties`, `interfaces`, `disks`, `packages`). | Parámetros omitidos devuelven JSON con `status: "ERROR"`, `exit_code: 1` y contrato de uso `--schema`. |
| `query_system_docs` | `DIMINISHED` | `query_system_docs(query: str, limit: int = 3, ingest_command: Optional[str] = None) -> str` | Vectorizador semántico offline de páginas `man` sobre `system_docs.db` (`sqlite-vec`). Resuelve sintaxis y flags exactas en <5 ms sin navegación web. `ingest_command` ingiere comandos adicionales bajo demanda. | `{"status": "OK", "query": str, "results": [{"command": str, "section": str, "distance": float, "chunk_text": str}]}` | Carga perezosa del vectorizador. Si faltan dependencias vectoriales, entrega respuesta degradada con instrucciones. |
| `visual_inspect` | `DIMINISHED` | `visual_inspect(url: str, viewport_width: int = 1280, viewport_height: int = 800, selector: Optional[str] = None, full_page: bool = True) -> str` | Renderiza URLs locales (`file://`) o remotas en Chromium headless vía Playwright. Captura pantallas en memoria RAM (`/dev/shm`) y retorna el screenshot codificado en Base64 con destrucción inmediata de residuos. | `{"status": "SUCCESS", "url": str, "title": str, "viewport": {...}, "screenshot_bytes": int, "screenshot_base64": str}` | Si Playwright o Chromium no están instalados, devuelve `status: "DISPLAY_UNAVAILABLE"` con comando de resolución. |
| `topos_audit_dag` | `DIMINISHED` | `topos_audit_dag(tasks: List[str], dependencies: Dict[str, List[str]]) -> str` | Guardián del Topos Integrity Protocol. Ejecuta ordenamiento topológico y detección de ciclos en grafos de tareas. Bloquea de inmediato planes con co-dependencias circulares (A <-> B) antes de iniciar la ejecución. | Aprobado: `{"verdict": "APPROVED", "details": [...]}`<br/>Bloqueado: `{"verdict": "BLOCKED", "details": [...], "remediation": str}` | Algoritmo determinista en memoria sin dependencias externas ni operaciones de E/S. |

#### Dominio 6: Automatización por Orquestación — Pico-Playbooks (1 Herramienta Unificada)

Encadenan tools/artefactos existentes en flujos DAG (p.ej. E2E: sonda Go + `visual_inspect`). El DAG se valida con `topos_guard` (cero co-dependencias) y el ejecutor despacha a una **whitelist** de tools (acota el blast radius).

| Herramienta | Privilegio | Firma & Parámetros | Mecánica & Propósito Operativo | Contrato de Salida JSON | Garantía Fail-Soft |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `playbook_run` | `DIMINISHED` | `playbook_run(action: str = "run", name: Optional[str] = None, vars: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, stop_on_error: bool = True, description: Optional[str] = None, intent_description: Optional[str] = None, steps: Optional[List[Dict[str, Any]]] = None, params_contract: Optional[List[Dict[str, Any]]] = None, names: Optional[List[str]] = None, apply: bool = False) -> str` | Punto único para ejecutar flujos DAG (`run`), definir automatizaciones con validación topológica y linting de whitelist (`create`), listar inventario con métricas (`list`), y ejecutar poda destructiva segura con dry-run (`prune`). | JSON tipado dependiente de la acción (`status`, `playbook`, `steps_run`, `results`, `playbooks`, `candidates`). | Respuestas estructuradas con `status: "PARAM_ERROR"` ante parámetros faltantes, `status: "INVALID_ACTION"` ante acciones no reconocidas, y `status: "LINT_ERROR"` ante intentos de recursión. Cero excepciones no controladas. |

---

### Evolución reciente (orientación, descubrimiento, automatización y auto-corrección)

Además de los dominios anteriores, el plano incorporó **2 motores compartidos** (una sola vara cada uno) y **herramientas de orientación / ciclo de vida**:

- **`engine/ponder.py`** — vara de **CONFIANZA** (multidimensional: quality/reliability/experience/recency + confianza + veto). La usan artefactos **y** playbooks para añadir (promover) y podar (degradar).
- **`engine/matcher.py`** — vara de **RELEVANCIA** (BM25F multi-señal, RE de skill-swarm). La usan `template_select` y `discover`.

| Herramienta | Propósito |
| :--- | :--- |
| `discover(use_case)` | **Orientación**: caso de uso → capacidad (con anclas léxicas bilingües EN/ES) + reutilizar(artefactos)/sintetizar(plantillas)/automatizar(playbooks), rankeado. Primera parada. |
| `artifact_catalog(action="browse"|"query"|"reindex"|"prune", ...)` | **Memoria semántica unificada**: `browse` (ranking de confianza o top-K semántico), `query` (búsqueda híbrida de caché), `reindex` (sanar embeddings), `prune` (GC destructivo seguro con dry-run). |
| `artifact_lint_and_build(action="build"|"catalog"|"select"|"hydrate", ...)` | Síntesis y ciclo de vida de artefactos: catálogo descriptivo de plantillas (`catalog`), selector por relevancia multi-señal (`select`), hidratación atómica Go (`hydrate`), y compilación con compuertas de calidad (`build`) con atajo de 1 paso. |
| `playbook_run(action="run"|"create"|"list"|"prune", ...)` | Pico-Playbooks unificado: orquestar tools en flujos DAG validados por Topos; parametrizables (`${var}`); ejecución, listado y GC seguro de automatizaciones. |
| `kanban_board(action="board"|"create"|"advance"|"promote"|"demote"|"reevaluate"|"archive"|"unarchive", ...)` | Pico-Kanban unificado: tablero por carriles, creación de tareas, avance de estado, promoción/degradación de confianza, reevaluación de flota y archivado reversible con dry-run. |

> Flujo del agente: **`discover` (orientar) → reutilizar/sintetizar/automatizar (decidir) → ponderar (añadir/podar)**. Todo con varas unificadas y transparente al usuario (agents-for-agents).

### Ciclo de Vida y Encadenamiento de Capacidades (Skill Chaining)

El siguiente diagrama ilustra cómo un agente autónomo encadena de forma determinista las 15 herramientas de AEP a lo largo de un ciclo de ejecución completo, integrando auto-descubrimiento, auditoría topológica, síntesis con compuertas de calidad, ejecución volátil en RAM, paralelismo asíncrono y auto-remediación proactiva:

```mermaid
flowchart TD
    subgraph S1["1. Descubrimiento & Autonomía"]
        Init["Inicio de Interacción"] --> Cap["aep_capabilities()<br/>Evaluar privilegios (FULL vs DIMINISHED)"]
        Cap --> Audit["topos_audit_dag()<br/>Auditar DAG de tareas y bloquear co-dependencias"]
        Audit --> Task["kanban_task_create()<br/>Registrar tarea en lane BACKLOG"]
    end

    subgraph S2["2. Recuperación & Síntesis de Artefactos"]
        Task --> Query["artifact_query(intent, category)<br/>Recuperación híbrida (Hash + sqlite-vec)"]
        Query --> Branch{"¿Estado en Catálogo?"}
        Branch -->|"CACHE_HIT (Validado)"| Hit["Recuperar binario existente de memoria"]
        Branch -->|"CACHE_MISS"| Hydrate["artifact_hydrate()<br/>Instanciar plantilla Go con parámetros"]
        Hydrate --> Synth["artifact_lint_and_build()<br/>go vet (gate) + golangci-lint (advisory)<br/>Compilación estática CGO_ENABLED=0"]
        Synth --> LintLane["kanban_advance()<br/>Mover tarea a estado LINTED"]
    end

    subgraph S3["3. Ejecución Volátil & Validación Canary"]
        Hit --> ExecRAM["artifact_execute_in_ram()<br/>Inyección en RAM vía memfd_create<br/>Ejecución /proc/self/fd/"]
        LintLane --> ExecRAM
        ExecRAM --> AdvCanary["kanban_advance()<br/>Avanzar a CANARY (canary_passed=True)"]
        AdvCanary --> Promote["kanban_promote()<br/>Evaluar trust score multidimensional<br/>(quality, reliability, experience, recency)"]
        Promote --> PBranch{"¿Score ≥ 0.70 & Veto OK?"}
        PBranch -->|"Aprobado"| Promoted["PROMOTED<br/>Marcado reusable=1 en catálogo"]
        PBranch -->|"Rechazado"| Rejected["REJECTED<br/>Permanece como artefacto efímero"]
    end

    subgraph S4["4. Vías Alternativas & Resiliencia Concurrente"]
        Audit -.->|"Comando untrusted"| Sand["sandbox_run()<br/>Aislamiento estricto bwrap"]
        Audit -.->|"Larga duración"| AsyncD["async_job_dispatch()<br/>Encolar en Pueue (task_id inmediato)"]
        AsyncD --> AsyncI["async_job_inspect()<br/>Sondear status y logs no-bloqueantes"]
        Cap -.->|"Monitoreo proactivo"| CrashCheck["check_crash_alerts()<br/>Polling de coredumps contra SQLite"]
        CrashCheck -->|"Alertas pendientes"| CrashDiag["diagnose_system_crashes()<br/>RCA con stack trace y señales"]
    end
```

[↑ Volver arriba](#top)

---

## 5. Memoria Semántica Híbrida (sqlite-vec)

Resuelve la fragilidad del hash estricto ante la variabilidad léxica de los LLMs con recuperación
en **2 tiers**: hash exacto `O(1)` y, si falla, KNN coseno sobre `sqlite-vec`.

```mermaid
flowchart LR
    Q["Intención del agente<br/>(lenguaje natural variable)"] --> T1{"Tier 1:<br/>hash SHA-256 exacto"}
    T1 -->|hit| R["Artefacto + binario ELF"]
    T1 -->|miss| T2["Tier 2: embedding local<br/>bge-small-en-v1.5 (384-dim, ONNX, offline)"]
    T2 --> KNN{"KNN coseno<br/>distancia ≤ 0.32"}
    KNN -->|match| R
    KNN -->|no match| Miss["CACHE_MISS → sintetizar"]
    R --> RAM["Inyección en RAM<br/>memfd_create"]
```

- Umbral `0.32` **calibrado empíricamente** (paráfrasis del mismo intent ~0.28–0.30; intents distintos ≥0.36).
- **Fail-soft total:** sin `sqlite-vec`/embedder, el catálogo opera idéntico al modo solo-hash.

### Persistencia y cómo la lee el agente

La base `~/.local/share/agent-os/artifacts.db` es la **memoria evolutiva** del sistema:

- **Vive fuera del repo** (espacio de usuario, gitignored). Persiste entre sesiones, reinicios
  del MCP (auto-plug) y reboots. Backup = copiar el archivo (un solo fichero ACID, embeddings incluidos).
- **El LLM nunca toca SQL.** La única vía de lectura/escritura son las tools MCP tipadas
  (`artifact_query`, `kanban_board`, …): la capa de tools ES el contrato. Esto erradica
  inyección y alucinación de esquema, y mantiene al agente desacoplado del almacenamiento.
- **Longitudinal:** `execution_metrics` acumula éxito/latencia por artefacto en el tiempo; los
  embeddings permiten recuerdo semántico; el Kanban pondera qué merece reutilizarse.

### Pico-Kanban: ponderación de artefactos (idioma agéntico)

Tablero de estados **abstracto** en la misma DB, transparente para el usuario, que el agente usa
como memoria de trabajo por **tareas atómicas** y para decidir **qué artefacto se promueve** como
plantilla reutilizable. Un artefacto solo se marca `reusable=1` cuando su **ponderación** lo amerita.

```mermaid
stateDiagram-v2
    [*] --> BACKLOG
    BACKLOG --> SYNTHESIZED
    SYNTHESIZED --> LINTED: go vet / golangci-lint
    LINTED --> CANARY: dry-run en RAM (memfd)
    CANARY --> PROMOTED: score ≥ 0.70 (reusable=1)
    LINTED --> REJECTED: ponderación insuficiente
    CANARY --> REJECTED
    PROMOTED --> [*]
```

**Ponderación multidimensional consciente de confianza** (adaptada del *trust engine* de
`skill-swarm-mcp` — a su vez inspirado en npms.io / OpenSSF Scorecard / SourceRank):

| Dimensión | Peso | Señal |
| :--- | :---: | :--- |
| `quality` | 0.35 | linters (go vet/golangci) + canary (dry-run en RAM) |
| `reliability` | 0.30 | tasa de éxito histórica |
| `experience` | 0.15 | log-normalizado de ejecuciones (canary da base) |
| `recency` | 0.20 | decaimiento exponencial (half-life 45 días) |

`effective = Σ(dimensión·peso) × confidence`, donde `confidence = dimensiones_con_señal / 4`.
Un artefacto **sin historial** tiene baja confianza aunque su score bruto sea alto → no se promueve a
ciegas. Veredictos: **TRUST ≥ 0.75** (promovido), **CAUTION ≥ 0.50**, **WARNING ≥ 0.25**, **REJECT**.
Un **veto de fiabilidad** impide TRUST si hay fallos demostrados (`éxito < 0.70` con ejecuciones).

[↑ Volver arriba](#top)

---

## 6. Mejoras de Omarchy (5 Specs Agnósticas)

Las innovaciones del "Agentic OS" de Omarchy (acopladas a Arch/Hyprland) descompuestas en 5
especificaciones **distro-agnósticas** sobre Ubuntu.

```mermaid
flowchart TD
    subgraph OM["Omarchy (Arch/Hyprland) → specs agnósticas"]
        S1["OM-1 · aep_ctl<br/>Plano de control unificado (JSON)"]
        S2["OM-2 · check_crash_alerts<br/>Crash routing proactivo (polling)"]
        S3["OM-3 · Skills Hub<br/>symlinks Claude/agy/Codex/Gemini"]
        S4["OM-4 · query_system_docs<br/>man-pages vectorizadas (sqlite-vec)"]
        S5["OM-5 · visual_inspect<br/>display headless (Playwright /dev/shm)"]
    end
    S1 & S2 & S3 & S4 & S5 --> V["Cero co-dependencias (Topos)<br/>· fail-soft · salida JSON tipada"]
```

### Matriz de Especificaciones Agnósticas de Omarchy

| Especificación | Nombre & Enfoque | Componente AEP | Mecánica Subyacente | Desacoplamiento de Omarchy (Ubuntu) | Garantía Fail-Soft |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SPEC-OM-1** | **Unified System Control Plane** | `aep_ctl`<br/>`scripts/aep-ctl` | Enrutador CLI determinista hacia `systemctl`, `ip`, `ss`, `df`, `dpkg` con validación de esquemas JSON. | Sustituye comandos de Arch (`pacman`, scripts bash ad-hoc) por utilidades POSIX universales de Ubuntu/Debian. | Peticiones inválidas retornan JSON con `exit_code: 1` y documentación de uso (`--schema`). Binarios faltantes emiten `DEGRADED`. |
| **SPEC-OM-2** | **Active Crash Routing & Proactive Self-Healing** | `check_crash_alerts`<br/>`diagnose_system_crashes` | Polling periódico que calcula huellas hash (`pid:time:exe`) de coredumps y persiste eventos en `crash_events`. | Elimina la dependencia de path units de systemd o servicios en segundo plano con permisos de root en Arch. | Si `coredumpctl` falta (contenedores), retorna `status: "DEGRADED"` sin interrumpir la ejecución del agente. |
| **SPEC-OM-3** | **Universal Multi-Agent Skills Hub** | Granja de symlinks<br/>`scripts/setup.sh` | Enlace simbólico convergente desde `~/.agents/skills/` hacia los directorios de Claude, Antigravity, Codex y Gemini. | Desacopla las habilidades del entorno Hyprland/Arch, permitiendo sincronización universal multi-agente en Ubuntu. | Enlace idempotente; si un agente no está instalado en el host, la rutina continúa sin arrojar errores. |
| **SPEC-OM-4** | **Local System Docs Vectorizer** | `query_system_docs`<br/>`engine/docs_vectorizer.py` | Base vectorial local `system_docs.db` con `sqlite-vec` y embeddings en CPU (`bge-small-en-v1.5`) sobre páginas `man`. | Reemplaza bases ChromaDB pesadas y llamadas a APIs de LLMs por inferencia ONNX offline en submilisegundos. | Carga perezosa; si el motor vectorial o el modelo faltan, entrega respuesta estructurada degradada sin excepciones. |
| **SPEC-OM-5** | **Headless Visual & Display Actuator** | `visual_inspect`<br/>`engine/headless_display.py` | Automatización de navegador Chromium headless vía Playwright con capturas efímeras en RAM (`/dev/shm`). | Elimina la necesidad de compositor Wayland/Hyprland o servidores X11 físicos (`Xvfb`) para auditoría de interfaces. | Si Playwright o Chromium no están instalados, emite `DISPLAY_UNAVAILABLE` con la receta exacta para su resolución. |

---

#### Especificaciones Técnicas Detalladas (SPEC-OM-1 a SPEC-OM-5)

#### 1. SPEC-OM-1: Unified System Control Plane (`aep_ctl` / `scripts/aep-ctl`)
- **Objetivo**: Proveer un punto de entrada CLI y RPC determinista para que los modelos de lenguaje inspeccionen y muten el estado del sistema operativo sin alucinar flags ni parsear salidas de texto no estructuradas.
- **Dominios Funcionales**:
  - `service`: Inspecciona estado (`status`) o muta unidades (`start`, `stop`, `restart`). En modo `DIMINISHED` se acota automáticamente a `systemctl --user`; en `FULL` ejecuta `sudo -n systemctl`.
  - `network`: Inspección general de interfaces (`inspect` vía `ip -j addr`), tabla de enrutamiento (`routes` vía `ip -j route`) y sockets en escucha (`listeners` parseando `ss -tuln` en JSON).
  - `storage`: Uso de particiones (`usage` parseando `df -B1`), puntos de montaje activos (`mounts`) y topología de discos (`disks` vía `lsblk -J`).
  - `package`: Paquetes instalados (`installed` vía `dpkg-query`), comprobación de presencia (`check`) e información de versión y dependencias (`info` vía `apt-cache policy`).
- **Garantías**: Cero salida interactiva (suprime pagers), autodocumentación con `--schema` que retorna el contrato de cada dominio, y código de salida 1 con JSON de uso cuando faltan argumentos.

#### 2. SPEC-OM-2: Active Crash Routing & Proactive Self-Healing (`check_crash_alerts`)
- **Objetivo**: Transformar el análisis forense pasivo de coredumps en un lazo proactivo de alerta temprana para prevenir que el agente construya sobre un sistema inestable.
- **Mecánica de Sincronización**:
  1. Ejecuta `coredumpctl list --json=short --reverse -n 100` de forma no-invasiva.
  2. Extrae para cada entrada el PID, timestamp del suceso y ruta del binario colapsado, componiendo una huella única digital `pid:timestamp:executable`.
  3. Ejecuta una sentencia atómica `INSERT OR IGNORE` en la tabla `crash_events` de `artifacts.db`.
  4. Retorna exclusivamente las alertas no resueltas (`resolved = 0`), permitiendo al agente invocar `diagnose_system_crashes()` para obtener el stack trace y planificar la remediación antes de seguir ejecutando tareas.
- **Desacoplamiento**: A diferencia de Omarchy que dependía de scripts específicos para el gestor de ventanas de Arch, opera puramente en espacio de usuario sobre cualquier distribución Ubuntu/Debian con systemd.

#### 3. SPEC-OM-3: Universal Multi-Agent Skills Hub
- **Objetivo**: Consolidar las habilidades y herramientas agénticas en una única fuente de la verdad canónica (`~/.agents/skills/`), eliminando discrepancias entre los entornos de ejecución de distintos agentes.
- **Arquitectura de Enlaces Simbólicos**:
  - Directorio Canónico: `~/.agents/skills/` (leído de forma nativa por OpenAI Codex).
  - Enlace Gemini CLI: `~/.gemini/skills/` -> `~/.agents/skills/`.
  - Enlace Antigravity (`agy`): `~/.gemini/config/skills/` -> `~/.agents/skills/`.
  - Enlace Migración Antigravity: `~/.gemini/antigravity-cli/skills/` -> `~/.agents/skills/`.
- **Garantías de Mantenimiento**: Las modificaciones efectuadas en una habilidad por cualquier subagente se reflejan en tiempo real para todos los clientes sin necesidad de sincronizaciones manuales o copias redundantes.

#### 4. SPEC-OM-4: Local System Docs Vectorizer (`query_system_docs`)
- **Objetivo**: Resolver en tiempo real dudas sobre la sintaxis exacta, banderas y opciones de configuración de utilidades Linux estándar sin requerir conexión a internet ni incurrir en consumo excesivo de tokens de contexto.
- **Pipeline de Ingesta y Recuperación**:
  - **Ingesta**: Ejecuta `man <cmd>` configurando `MANPAGER=cat` y `MANWIDTH=80` para extraer texto plano limpio. Divide el manual en bloques de párrafo coherentes (máximo 50 fragmentos por comando).
  - **Vectorización Local**: Calcula embeddings semánticos de 384 dimensiones mediante el modelo cuantizado `bge-small-en-v1.5` ejecutado sobre CPU con ONNX Runtime.
  - **Almacenamiento**: Persiste los fragmentos y sus vectores en `~/.local/share/agent-os/system_docs.db` utilizando la tabla virtual `vec_docs` de `sqlite-vec`.
  - **Consulta**: La función `query_system_docs(query, limit)` vectoriza la consulta del agente y ejecuta búsqueda por distancia de coseno, devolviendo los párrafos más relevantes en menos de 5 ms.

#### 5. SPEC-OM-5: Headless Visual & Display Actuator (`visual_inspect`)
- **Objetivo**: Dotar a los agentes de capacidades de inspección visual en entornos de servidor o instancias cloud privadas de monitor físico, permitiendo auditar dashboards, aplicaciones web o documentación generada localmente.
- **Ciclo de Vida de Captura en RAM**:
  1. Instancia el navegador Chromium sin cabeza mediante Playwright (`headless=True`, flags `--no-sandbox`).
  2. Carga la URL indicada (`http://`, `https://` o `file://` local) configurando el viewport solicitado (por defecto 1280x800).
  3. Espera el evento de ciclo de vida `load` de la página. Si se proporciona un selector CSS, aísla el elemento correspondiente.
  4. Vuelca la captura gráfica directamente en memoria compartida volátil `/dev/shm/aep_shot_<uuid>.png`.
  5. Codifica los bytes del archivo en una cadena Base64, computa la latencia y elimina inmediatamente el archivo temporal de RAM (`/dev/shm`), garantizando cero persistencia en almacenamiento secundario.

---

### Arquitectura y Flujo de Datos de las Mejoras Omarchy

El siguiente diagrama detalla la arquitectura en tres niveles que articula las herramientas de Omarchy con los motores de AEP y las primitivas subyacentes del sistema operativo Ubuntu:

```mermaid
flowchart TD
    subgraph Agents["Capa de Agentes & Tools MCP"]
        T1["aep_ctl(domain, action)"]
        T2["check_crash_alerts() / diagnose_system_crashes()"]
        T3["Universal Skills Hub (Multi-Agent Registry)"]
        T4["query_system_docs(query, limit)"]
        T5["visual_inspect(url, viewport)"]
    end

    subgraph Adapters["Capa de Adaptadores & Motores AEP"]
        A1["scripts/aep-ctl<br/>(CLI determinista con contratos --schema)"]
        A2["engine/crash_router.py<br/>(De-duplicación por huella pid:time:exe)"]
        A3["scripts/setup.sh & aep-sync.sh<br/>(Gestor de symlinks convergentes)"]
        A4["engine/docs_vectorizer.py<br/>(Chunking de man + Embeddings ONNX CPU)"]
        A5["engine/headless_display.py<br/>(Playwright Chromium headless)"]
    end

    subgraph OS["Capa de Primitivas Ubuntu / Kernel Linux"]
        OS1["systemctl --user / sudo -n systemctl<br/>ss · ip · df · dpkg-query"]
        OS2["systemd-coredump · journalctl -p err<br/>SQLite: crash_events (~/.local/share/agent-os/artifacts.db)"]
        OS3["Granja de enlaces (~/.agents/skills)<br/>Claude · Antigravity · Codex · Gemini"]
        OS4["man pages (MANPAGER=cat)<br/>SQLite: vec_docs (~/.local/share/agent-os/system_docs.db)"]
        OS5["Buffers volátiles en RAM (/dev/shm)<br/>Capturas base64 efímeras (cero I/O en disco)"]
    end

    T1 --> A1 --> OS1
    T2 --> A2 --> OS2
    T3 --> A3 --> OS3
    T4 --> A4 --> OS4
    T5 --> A5 --> OS5
```

[↑ Volver arriba](#top)

---

## 7. Modelo de Privilegio de Dos Niveles + Manifiesto

Las tools privilegiadas operan en dos niveles (least-privilege por defecto). `aep_capabilities()`
devuelve un **manifiesto auto-descriptivo estilo `chmod`/777** para que la IA consumidora entienda,
en primera vista, qué puede hacer **ahora**.

```mermaid
flowchart TD
    Start["¿euid == 0?"] -->|sí| Full["FULL (direct-root)"]
    Start -->|no| Sudo{"¿sudo -n disponible?"}
    Sudo -->|sí| FullE["FULL (sudo-n) — escalada acotada"]
    Sudo -->|no| Dim["DIMINISHED — alcance al usuario, fail-soft"]
    Full & FullE --> Scope["Alcance: self → system → kernel"]
    Dim --> ScopeD["Alcance: self (base de autonomía completa)"]
```

**Códigos de capacidad** (tríada rwx resignificada): `r`=SENSAR, `w`=ACTUAR, `x`=EJECUTAR por caminos no-tradicionales.

| octal | perm | significado |
| :---: | :---: | :--- |
| 7 | `rwx` | sensar + actuar + ejecutar |
| 6 | `rw-` | sensar + actuar |
| 5 | `r-x` | sensar + ejecutar |
| 4 | `r--` | solo sensar |
| 0 | `---` | sin acceso (requiere FULL) |

> La autonomía base opera completa en **DIMINISHED**; el nivel **FULL** solo ensancha
> `kernel_observability` (`0→4`) y `service_control` (`4→6`). El privilegio es **apertura, no prerequisito**.

[↑ Volver arriba](#top)

---

## 8. Auto-Plug: Autogestión Atómica del MCP

Tras cualquier cambio, `aep-sync.sh` **valida** (compila + importa el server) y **solo si pasa**
re-registra el MCP en todos los clientes, apuntando a un launcher estable que resuelve el intérprete
por sí mismo. Un hook `pre-commit` corre la misma validación.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Cambio en código
    participant Sync as aep-sync.sh
    participant Val as Validación (--check)
    participant Launch as aep-mcp-launch.sh
    participant Clients as Claude / agy / Codex / Gemini

    Dev->>Sync: ./aep-sync.sh (o --watch / pre-commit)
    Sync->>Val: py_compile + import server
    alt validación falla
        Val-->>Sync: ✗ (no se enchufa un server roto)
    else validación OK
        Val-->>Sync: ✓
        Sync->>Clients: re-registrar apuntando a Launch
        Launch->>Launch: resolver venv / python3 + PATH al arranque
    end
```

[↑ Volver arriba](#top)

---

## 9. Entorno Shell-Agnóstico

La herencia de entorno **no asume Oh My Zsh**. Un archivo POSIX único se hace `source` desde los rc
nativos. Probado en **bash, zsh y dash**.

```mermaid
flowchart LR
    Env["config/shell/aep-env.sh<br/>(POSIX: PAGER=cat, PATH, wrappers)"]
    Install["scripts/install-shell-env.sh<br/>(idempotente, marcador)"]
    Install --> B["~/.bashrc"]
    Install --> Z["~/.zshenv"]
    Install --> P["~/.profile"]
    B & Z & P -->|source| Env
```

[↑ Volver arriba](#top)

---

## 10. Instalación desde Cero

```bash
cd /ruta/a/agent-execution-plane
./scripts/setup.sh        # idempotente, espacio de usuario, sin sudo en el camino crítico
```

`setup.sh` provisiona el venv semántico (`sqlite-vec` + `fastembed` + Playwright), compila las sondas
Go, descarga Pueue (musl, user-space), instala la herencia de shell agnóstica, el hook pre-commit y
re-registra el MCP en todos los agentes vía `aep-sync.sh`.

```mermaid
flowchart TD
    A["setup.sh"] --> B["venv + sqlite-vec/fastembed/playwright"]
    A --> C["sondas Go (CGO_ENABLED=0)"]
    A --> D["Pueue musl → ~/.local/bin"]
    A --> E["install-shell-env.sh (bash/zsh/sh)"]
    A --> F["hook pre-commit (core.hooksPath)"]
    A --> G["aep-sync.sh → registro MCP multi-agente"]
```

[↑ Volver arriba](#top)

---

## 11. Estructura del Repositorio

```
agent-execution-plane/
├── server.py                       # Servidor FastMCP (15 tools RPC)
├── engine/
│   ├── catalog.py                  # Catálogo + memoria semántica híbrida
│   ├── embedder.py                 # Embedder local ONNX (fail-soft)
│   ├── hydrator.py                 # Hidratador de plantillas Go
│   ├── topos_guard.py              # Detector de co-dependencias DAG
│   ├── privilege.py                # Niveles FULL/DIMINISHED + manifiesto
│   ├── crash_router.py             # Crash routing proactivo (OM-2)
│   ├── docs_vectorizer.py          # Man-pages vectorizadas (OM-4)
│   └── headless_display.py         # Display headless Playwright (OM-5)
├── schemas/
│   ├── database.sql                # DDL (artifacts, metrics, crash_events)
│   └── artifact_contract.cue       # Contratos declarativos CUE
├── templates/                      # Sondas atómicas Go (socket-monitor, fd-rescuer)
├── config/shell/aep-env.sh         # Herencia de entorno POSIX (agnóstica)
├── scripts/
│   ├── setup.sh                    # Instalador idempotente desde cero
│   ├── aep-ctl                     # Plano de control unificado (OM-1)
│   ├── aep-mcp-launch.sh           # Launcher estable (auto-plug)
│   ├── aep-sync.sh                 # Autogestión atómica + registro MCP
│   ├── install-shell-env.sh        # Instalador de herencia de shell
│   └── hooks/pre-commit            # Gate de validación
├── .gitattributes · .gitignore
└── README.md                       # Fuente única de verdad (este archivo)
```

[↑ Volver arriba](#top)

---

## 12. Inventario Sincero de la Fuente de la Verdad

| Componente | Estado Físico Real | Nota |
| :--- | :--- | :--- |
| `memfd_create` (RAM exec) | ✅ Operativo | Primitiva estándar del kernel Linux (glibc 2.27+ / POSIX); staging en memoria anónima (cero I/O en disco) |
| `bwrap` (sandbox) | ✅ Operativo | `sandbox_run` |
| `bpftrace` (eBPF) | ✅ Operativo (FULL) | `kernel_trace`; escala vía `sudo -n`, degrada a DIMINISHED |
| Pueue (async) | ✅ Operativo | musl 4.0.4 en `~/.local/bin`, verificado end-to-end |
| Memoria semántica (`sqlite-vec`) | ✅ Operativo | Recuperación híbrida 2-tier, fail-soft |
| Pico-Kanban (ponderación) | ✅ Operativo | Tablero abstracto en `artifacts.db`; promueve artefactos a `reusable` por score |
| Pico-Playbooks (automatización) | ✅ Operativo | Orquesta tools/artefactos en flujos DAG validados por Topos; ejecución E2E y ponderación por éxito |
| Descubrimiento del catálogo | ✅ Operativo | `artifact_catalog`: browse por confianza + top-K semántico |
| Omarchy (5 specs) | ✅ Operativo | `aep_ctl`, crash routing, hub+Gemini, man-pages, headless |
| Privilegio FULL/DIMINISHED | ✅ Operativo | `privilege.py` + manifiesto `aep_capabilities` |
| Auto-plug MCP | ✅ Operativo | launcher + `aep-sync.sh` (+ `--watch`) |
| Herencia shell agnóstica | ✅ Operativo | bash/zsh/dash; sin Oh My Zsh |
| Nushell (`nu`) / `jc` | ⏳ Pendiente (no crítico) | `aep_ctl` ya entrega JSON tipado |

[↑ Volver arriba](#top)

---

## 13. RE as SDD y Matriz de Inspiración

El desarrollo de AEP aplica Ingeniería Inversa Orientada por Especificaciones (RE as SDD) para
desacoplar primitivas del kernel de dependencias complejas o implementaciones monolíticas:
**(1)** aislar la primitiva del kernel Linux, **(2)** formalizar su especificación agnóstica de plataforma,
y **(3)** construir una implementación minimalista, tipada y verificada end-to-end.

```mermaid
flowchart LR
    subgraph Ref["Repositorios de inspiración"]
        R1["termux-linux-deployer<br/>(perfil de shell único · seeding)"]
        R2["termux-ubuntu-bootstrap<br/>(instalador idempotente · logging)"]
        R3["openclaw<br/>(contratos · AGENTS.md)"]
        R4["sdk-agent-pipeline<br/>(Topos DAG integrity)"]
    end
    subgraph AEP["Patrones adoptados en AEP"]
        F1["aep-env.sh sourced + multi-agente"]
        F2["setup.sh idempotente user-space"]
        F3["contratos CUE + EAES-v1"]
        F4["topos_guard anti-codependencia"]
    end
    R1 --> F1
    R2 --> F2
    R3 --> F3
    R4 --> F4
```

> Este `README.md` es la **fuente única de verdad** del proyecto: toda la especificación,
> arquitectura y auditoría viven aquí, sin documentación dispersa.

[↑ Volver arriba](#top)
