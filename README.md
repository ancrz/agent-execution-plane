<a id="top"></a>

# Agent Execution Plane (AEP)

**Plano de Control de Sistema y Suite de Ejecución de Alta Resiliencia para Agentes de IA sobre Ubuntu/Linux**

> [!IMPORTANT]
> **Declaración de Premisa (Anti-Malware / De-weaponization)**
> AEP **no** es un framework de ciberseguridad ofensiva ni una herramienta de *Red Teaming*.
> Es una **suite de ingeniería de sistemas y runtime agéntico** que aplica **Ingeniería Inversa
> orientada por Especificaciones (RE as SDD)** sobre primitivas de bajo nivel históricamente
> atrapadas en frameworks C2 y herramientas de introspección de kernel, **transmutándolas** en un
> plano de ejecución no-bloqueante, tipado y asíncrono para LLMs y agentes autónomos.

---

## Índice

1. [El Isomorfismo: Operador C2 ↔ Agente de IA](#1-el-isomorfismo-operador-c2--agente-de-ia)
2. [Arquitectura Global (4 Capas)](#2-arquitectura-global-4-capas)
3. [Descomposición Ofensiva → Capacidad Agéntica](#3-descomposición-ofensiva--capacidad-agéntica)
4. [Catálogo de 19 Herramientas MCP](#4-catálogo-de-19-herramientas-mcp)
5. [Memoria Semántica Híbrida (sqlite-vec)](#5-memoria-semántica-híbrida-sqlite-vec)
6. [Mejoras de Omarchy (5 Specs Agnósticas)](#6-mejoras-de-omarchy-5-specs-agnósticas)
7. [Modelo de Privilegio de Dos Niveles + Manifiesto](#7-modelo-de-privilegio-de-dos-niveles--manifiesto)
8. [Auto-Plug: Autogestión Atómica del MCP](#8-auto-plug-autogestión-atómica-del-mcp)
9. [Entorno Shell-Agnóstico](#9-entorno-shell-agnóstico)
10. [Instalación desde Cero](#10-instalación-desde-cero)
11. [Estructura del Repositorio](#11-estructura-del-repositorio)
12. [Inventario Sincero de la Fuente de la Verdad](#12-inventario-sincero-de-la-fuente-de-la-verdad)
13. [RE as SDD y Matriz de Inspiración](#13-re-as-sdd-y-matriz-de-inspiración)

---

## 1. El Isomorfismo: Operador C2 ↔ Agente de IA

Los frameworks de Command & Control (Sliver, Mythic, Cobalt Strike) nunca fueron concebidos para
destruir: fueron diseñados para **operar bajo hostilidad e invisibilidad de interfaz** — cero
interacción humana, cero tolerancia a procesos colgados, comunicación asíncrona serializada y
ejecución quirúrgica en RAM. Para un agente de IA, la consola Unix tradicional es **exactamente el
mismo entorno hostil**. AEP se apropia del *motor* (no de la evasión de EDR) y se lo entrega al agente.

```mermaid
flowchart LR
    subgraph Hostile["Entorno hostil (igual para el operador C2 y el agente)"]
        H1["Subprocesos bloqueantes<br/>(pagers, prompts, sudo interactivo)"]
        H2["Texto plano desalineado<br/>(awk/sed/grep) = tokens quemados"]
        H3["Huella en disco<br/>(temporales dispersos)"]
    end
    subgraph AEP["Resolución AEP (mecanismo desmilitarizado)"]
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
        MCP["Servidor FastMCP (server.py) — 19 tools"]
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

[↑ Volver arriba](#top)

---

## 3. Descomposición Ofensiva → Capacidad Agéntica

Cada primitiva "atrapada" en herramientas ofensivas se extrajo y re-especificó como capacidad de
gestión agéntica gobernada por privilegio. **Todas verificadas end-to-end.**

```mermaid
flowchart LR
    subgraph Off["Técnica ofensiva original"]
        O1["Sliver: ejecución ELF en RAM"]
        O2["ptrace / process injection"]
        O3["Sandbox escape (namespaces)"]
        O4["Exploit crash triage"]
        O5["eBPF rootkits / sniffers"]
        O6["BloodHound (teoría de grafos)"]
        O7["C2 beaconing / sleep"]
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

| Primitiva ofensiva | Clasificación tradicional | Transmutación agéntica | Estado |
| :--- | :--- | :--- | :--- |
| `memfd_create` (Sliver) | Ejecución en RAM, evasión EDR | Inyección de binarios verificados en RAM | ✅ Operativo |
| `ptrace` + `/proc/$PID/fd` | Inyección / lectura de memoria | Introspección y rescate de procesos colgados | ✅ Operativo |
| `bwrap` (namespaces) | Jailbreak / aislamiento | Sandbox efímero de sub-milisegundo | ✅ Operativo |
| `coredumpctl` + libunwind | Desarrollo de exploits | Root Cause Analysis autónomo (fail-soft) | ✅ Operativo |
| eBPF (`bpftrace`) | Rootkits / sniffers | Observabilidad de kernel no-invasiva | ✅ Operativo (FULL) |
| Grafos (BloodHound) | Attack paths en AD | Guardián Topos anti-codependencia | ✅ Operativo |
| Beaconing / sleep | Check-in C2 periódico | Despacho asíncrono (Pueue) | ✅ Operativo |

[↑ Volver arriba](#top)

---

## 4. Catálogo de 19 Herramientas MCP

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
├── server.py                       # Servidor FastMCP (19 tools RPC)
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
| `memfd_create` (RAM exec) | ✅ Operativo | Primitiva pura; framework C2 no instalado |
| `bwrap` (sandbox) | ✅ Operativo | `sandbox_run` |
| `bpftrace` (eBPF) | ✅ Operativo (FULL) | `kernel_trace`; escala vía `sudo -n`, degrada a DIMINISHED |
| Pueue (async) | ✅ Operativo | musl 4.0.4 en `~/.local/bin`, verificado end-to-end |
| Memoria semántica (`sqlite-vec`) | ✅ Operativo | Recuperación híbrida 2-tier, fail-soft |
| Pico-Kanban (ponderación) | ✅ Operativo | Tablero abstracto en `artifacts.db`; promueve artefactos a `reusable` por score |
| Omarchy (5 specs) | ✅ Operativo | `aep_ctl`, crash routing, hub+Gemini, man-pages, headless |
| Privilegio FULL/DIMINISHED | ✅ Operativo | `privilege.py` + manifiesto `aep_capabilities` |
| Auto-plug MCP | ✅ Operativo | launcher + `aep-sync.sh` (+ `--watch`) |
| Herencia shell agnóstica | ✅ Operativo | bash/zsh/dash; sin Oh My Zsh |
| Nushell (`nu`) / `jc` | ⏳ Pendiente (no crítico) | `aep_ctl` ya entrega JSON tipado |

[↑ Volver arriba](#top)

---

## 13. RE as SDD y Matriz de Inspiración

Acoplar frameworks ofensivos completos introduce ruido, co-dependencias y firmas. En su lugar:
**(1)** aislamos la primitiva del kernel, **(2)** escribimos la especificación formal, **(3)**
construimos una implementación limpia y verificada.

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
