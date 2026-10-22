# Análisis de Fuente de la Verdad, Metodología RE as SDD y Matriz de Inspiración

> **Fecha:** 2026-10-22  
> **Estado:** Documentación Técnica Maestra  
> **Ámbito:** Agent Execution Plane (AEP) — Ubuntu Linux Runtime

---

## 1. Inventario Sincero de la Fuente de la Verdad (Ground Truth Audit)

Para mantener la integridad epistemológica del proyecto y evitar que futuros agentes de IA o desarrolladores asuman funcionalidades inexistentes, este inventario desglosa con exactitud quirúrgica qué está físicamente operativo en el sistema, qué fue transmutado mediante ingeniería inversa (RE) y qué permanece pendiente de instalación o cableado.

```mermaid
flowchart TD
    subgraph FullyOperational["1. 100% Operativo y Físicamente Verificado"]
        O1["Compilador Golang (go build CGO_ENABLED=0)"]
        O2["Syscall nativa Linux os.memfd_create en Python"]
        O3["Catálogo SQLite (~/.local/share/agent-os/artifacts.db)"]
        O4["Sondas Atómicas Go (socket-monitor, fd-rescuer)"]
        O5["Servidor FastMCP (server.py con 9 tools)"]
        O6["Bubblewrap (/usr/bin/bwrap para sandboxing)"]
        O7["bpftrace (/usr/bin/bpftrace para eBPF)"]
        O8["Seeding Registrado en Claude Code, agy y Codex"]
    end

    subgraph RETransmuted["2. Transmutado mediante RE as SDD (Sin Framework Externo)"]
        R1["Sliver C2: No instalado. Primitiva memfd_create extraída directamente."]
        R2["Pico-Jenkins: No usa servidor Jenkins. Pipeline Go en RAM de 300ms."]
        R3["Pico-Ansible: No usa Ansible core. Contratos CUE + SQLite."]
    end

    subgraph PendingWiring["3. Pendiente de Instalación / Cableado (Deuda Técnica)"]
        P1["Pueue daemon (pueued no instalado en el SO)"]
        P2["Nushell (nu no instalado en el SO)"]
        P3["jc (wrapper JSON no instalado)"]
        P4["Sonda .bt de bpftrace en server.py"]
    end
```

### Tabla de Desglose de Componentes

| Componente | Proyectado en Documento Inicial | Estado Físico Real | Mecanismo Implementado | Brecha / Acción Requerida |
| :--- | :--- | :--- | :--- | :--- |
| **Sliver C2** | Instalar servidor completo con `curl \| bash`, base de datos y mTLS. | **Descartado el framework.** Primitiva extraída. | Syscall `os.memfd_create` nativa en Python 3 + `/proc/self/fd/<fd>`. | **Ninguna.** La primitiva fue implementada en su forma más pura y eficiente sin la sobrecarga ofensiva. |
| **Bubblewrap** | Sandbox efímero para pruebas. | **Instalado y Operativo.** | `/usr/bin/bwrap` invocado por `sandbox_run` en `server.py`. | **Ninguna.** Opera con namespaces nativos de Linux. |
| **bpftrace (eBPF)** | Observabilidad de kernel. | **Binario Instalado.** | Binario en `/usr/bin/bpftrace`. | **Falta cablear:** Falta escribir el script `.bt` en `server.py` para exponer métricas estructuradas en el MCP. |
| **Pico-Jenkins** | Pipeline de compilación y verificación. | **Instalado y Operativo.** | `go build` + `go vet` + inyección en RAM en < 300 ms. | **Ampliación:** Añadir `golangci-lint` en `~/.local/bin` para 40+ reglas estáticas adicionales. |
| **Pico-Ansible** | Catálogo declarativo de gestión. | **Instalado y Operativo.** | SQLite (`artifacts.db`) + `engine/catalog.py` + `engine/hydrator.py`. | **Ninguna.** Seeded con `socket-monitor` y `fd-rescuer`. |
| **Topos Guard** | Detector de co-dependencias. | **Instalado y Operativo.** | `engine/topos_guard.py` ejecutando algoritmo DFS de detección de ciclos en grafos DAG. | **Ninguna.** Probado con aserciones unitarias. |
| **Pueue Daemon** | Colas de tareas asíncronas. | **No instalado en el SO.** | El código de `server.py` lo invoca, pero el binario no existe. | **Gap Crítico:** Descargar binario estático de `pueued` a `~/.local/bin/`. |
| **Nushell (`nu`)** | Tuberías tipadas de shell. | **No instalado en el SO.** | `sys_json` en `~/.zshenv` está inerte. | **Gap Medio:** Descargar binario estático de `nu` a `~/.local/bin/`. |
| **`jc`** | Parser JSON de utilidades POSIX. | **No instalado en el SO.** | `jrun` en `~/.zshenv` está inerte. | **Gap Medio:** Instalar paquete Python con `pip install jc`. |

---

## 2. Justificación de "RE as SDD" (Reverse Engineering as Specification-Driven Development)

Una de las decisiones más críticas de este proyecto fue **no instalar ciegamente las herramientas de ciberseguridad ofensiva** (Sliver C2, Havoc, Mythic) a pesar de haberlas citado como fuente de inspiración.

### ¿Por qué aplicamos Ingeniería Inversa Orientada por Especificaciones?

```mermaid
flowchart LR
    subgraph BadPattern["Antipatrón: Acoplamiento Directo del C2"]
        C2F["Framework C2 Completo (Sliver/Mythic)"]
        C2F --> Noise["Demonio gRPC + Base de Datos + Certificados mTLS"]
        C2F --> AttackSurface["Firmas de Red Teaming / Posibles Falsos Positivos de EDR"]
        C2F --> CoDep["Co-dependencia Compleja de Configuración"]
    end

    subgraph GoodPattern["Metodología RE as SDD (Nuestra Elección)"]
        KernelPrimitive["Aislamiento de la Primitiva del Kernel (memfd_create)"]
        Spec["Especificación Formal Rígida (blueprint.md / EAES-v1)"]
        CleanCode["Implementación Ligera en Python + Go Nativo"]
        KernelPrimitive --> Spec --> CleanCode
    end
```

1. **Eliminación del Peso Muerto:**
   * Un framework C2 como Sliver incluye generadores de payloads para Windows (evasión de AMSI, NTDLL unhooking), protocolos de ofuscación de tráfico (DNS tunneling, WireGuard multiplexing) y gestión multi-operador. 
   * Para un agente de IA en un entorno local de Ubuntu, el 95% de ese código es **peso muerto** que consume memoria, introduce vectores de fallo y añade latencia.
2. **Prevención de Co-dependencias (Protocolo Topos):**
   * Instalar un C2 completo crea una relación de co-dependencia ($A \otimes B$) entre la infraestructura del agente y el demonio C2. Si el servidor gRPC de Sliver se corrompe o requiere renovación de certificados de operador, la IA queda completamente ciega e incapaz de operar el sistema.
   * Al extraer la primitiva pura (`memfd_create` nativo en el kernel), la herramienta se convierte en una **dependencia unidireccional limpia ($A \to B$)**, sin estado oculto ni demonios externos frágiles.
3. **El Rol de la Especificación (SDD - Specification-Driven Development):**
   * En lugar de depender de la documentación dispersa de herramientas de terceros, creamos una especificación formal (**EAES-v1** en `docs/spec_artifact_engine.md`).
   * La especificación define los contratos en **CUE** y las garantías de compilación estática. Esto permite que cualquier modelo de lenguaje (sea Gemini, Claude o Codex) comprenda de inmediato las restricciones formales sin alucinar parámetros inexistentes.

---

## 3. Matriz de Inspiración Arquitectónica (Repositorios de Referencia)

Para solventar las lagunas de las características y diseñar un plano de ejecución verdaderamente funcional, sintetizamos los mejores patrones de tres proyectos clave del espacio de trabajo:

```mermaid
flowchart TD
    subgraph Sources["Repositorios de Inspiración en el Workspace"]
        T["termux-linux-deployer"]
        O["openclaw"]
        S["sdk-agent-pipeline"]
    end

    subgraph FeaturesAdopted["Características Extraídas e Integradas en AEP"]
        F1["Bootstrap Idempotente + Seeding Multi-Agente (Claude, agy, Codex)"]
        F2["Aislamiento en Espacio de Usuario (~/.local/bin) sin dependencia de Root"]
        F3["Rigor en Especificaciones Formales y Contratos Declarativos"]
        F4["Topos DAG Integrity y Detección de Co-dependencias Cíclicas"]
    end

    T --> F1
    T --> F2
    O --> F3
    S --> F4
```

### 3.1. Lecciones de `termux-linux-deployer`
* **El Patrón de Seeding Idempotente:** De `scripts/ubuntu/setup-mcp.sh` adoptamos la técnica de consultar la existencia de clientes de IA (`claude`, `agy`, `codex`) y registrar de forma transversal e idempotente el servidor MCP mediante sus comandos CLI nativos, sin duplicar entradas ni romper archivos de configuración preexistentes.
* **Aislamiento en Espacio de Usuario:** `termux-linux-deployer` resuelve la instalación de herramientas en entornos con restricciones de privilegios (como Android/proot o entornos no-root) utilizando `~/.local/bin` y compilaciones estáticas, una lección directa para subsanar la ausencia de `sudo` en esta sesión.

### 3.2. Lecciones de `openclaw`
* **Cultura de Especificación Formal (`AGENTS.md` / `VISION.md`):** En `openclaw`, ninguna funcionalidad se programa sin un contrato previo que defina invariantes y objetivos. En AEP adoptamos esta disciplina mediante la especificación canónica **EAES-v1** y la redacción estricta de diagramas de estado.
* **Aislamiento de Entorno de Ejecución:** El uso de entornos reproducibles con configuraciones de linters estrictas (`.oxlintrc.json`, `.semgrepignore`) inspiró la integración de `golangci-lint` en modo JSON dentro de nuestro Pico-Jenkins.

### 3.3. Lecciones de `sdk-agent-pipeline`
* **Topos DAG Integrity:** De este proyecto heredamos la disciplina ontológica: la clasificación formal de relaciones entre módulos (**Dependencia**, **Interdependencia**, **Co-dependencia**).
* **Guardián de Circuitos (`ToposGuard`):** La implementación de `engine/topos_guard.py` proviene directamente de la necesidad identificada en `sdk-agent-pipeline` de validar matemáticamente que los grafos de ejecución no tengan ciclos antes de que un agente despache tareas concurrentes a los trabajadores.

---

## 4. Hoja de Ruta para el Cierre de Brechas (Technical Action Plan)

Para cerrar las lagunas identificadas en el inventario sincero, se ejecutarán los siguientes pasos técnicos:

1. **Descarga de Binarios Estáticos a `~/.local/bin` (Sin Sudo):**
   * Descargar release estático de `pueue` y `pueued` (Rust) desde GitHub Releases y activar el demonio de usuario `systemctl --user enable --now pueued` o `pueued -d`.
   * Descargar binario estático de Nushell (`nu`).
   * Instalar el paquete Python `jc` en el entorno de usuario con `pip install --user jc` o `uv pip install jc`.
2. **Cableado de la Sonda eBPF en `server.py`:**
   * Integrar la herramienta `kernel_trace_syscall` ejecutando `/usr/bin/bpftrace` con un script embebido de conteo de syscalls (`bpftrace -e 'tracepoint:raw_syscalls:sys_enter { @[comm] = count(); }'`).
3. **Validación End-to-End:**
   * Probar el ciclo completo: Invocación de herramienta MCP desde un cliente IA $\to$ Catálogo SQLite $\to$ Compilación Go $\to$ Inyección en RAM $\to$ Retorno JSON.
