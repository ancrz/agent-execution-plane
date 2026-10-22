# Arquitectura Híbrida de Control de Sistema para Agentes de IA en Ubuntu
**De la Shell POSIX Tradicional a un Plano de Control C2 + Agentic OS (Camino A + Camino B + Omarchy Patterns + MCP)**

---

## 1. Contexto, Historia y Ventajas de los Componentes Base

Para superar las limitaciones de **Zsh + Oh My Zsh** (diseñado para la ergonomía visual humana pero ineficiente para los subprocesos de un LLM debido al ruido del texto plano y los bloqueos de entrada/salida), esta arquitectura fusiona el poder de los frameworks de **Command & Control (C2)** con gestores modernos de colas asíncronas y serialización estructurada.

### 1.1. Camino A: El Plano de Bajo Nivel y Memoria (Sliver C2)
* **Historia y Origen:** Desarrollado por **Bishop Fox** y lanzado en 2019 como una alternativa de código abierto, multiplataforma y modular frente a sistemas comerciales cerrados como *Cobalt Strike* o *Brute Ratel*. Escrito íntegramente en **Go**, nació para ofrecer implantes dinámicos compilados al vuelo y un servidor colaborativo basado en **gRPC sobre mTLS**.
* **Por qué supera a una Shell tradicional:**
  1. **Primitivas Nativas vs. `fork/exec`:** Mientras Zsh levanta un binario externo por cada comando (`ps`, `ss`, `cat`), el implante de Sliver ejecuta llamadas al sistema directamente desde su propio proceso en Go y devuelve estructuras tipadas mediante **Protobuf**.
  2. **Ejecución en Memoria en Linux (`memfd_create`):** Permite inyectar y ejecutar binarios ELF directamente en la memoria RAM del kernel de Linux usando descriptores de archivo anónimos, sin escribir en el disco duro.
  3. **Pivoting y Red Intrínseca:** Levanta túneles WireGuard, proxies SOCKS5 en memoria y redirecciones de puertos sin depender de demonios externos ni configuraciones frágiles de `iptables`.
  4. **Automatización por Diseño (`sliver-py`):** Su arquitectura gRPC permite que un script en Python o un servidor MCP controle el implante en milisegundos sin intervención humana.

### 1.2. Camino B: El Plano de Ejecución de Usuario y Asíncrono (Pueue + Xonsh + Nushell + `jc`)
Los implantes C2 son quirúrgicos, pero no están diseñados para mantener el estado de variables de entorno complejas o compilar código pesado durante 20 minutos. Aquí entra el Camino B:

* **Pueue (Process Queue Daemon):**
  * *Historia:* Creado por Arne Beer (`Nukesor`) en **Rust** como una alternativa ligera a sistemas pesados de colas empresariales (como Celery o Slurm) enfocada en la consola local.
  * *Ventajas para la IA:* Elimina para siempre el bloqueo de subprocesos (*hanging commands*). El agente lanza cualquier tarea larga (`pueue add -- comando`), recibe un `task_id` instantáneo en menos de $2\text{ ms}$, y consulta el progreso o los logs aislados en formato JSON (`pueue status --json`).
* **Xonsh (Python-powered Shell):**
  * *Historia:* Iniciado en 2015 por Anthony Scopatz para fusionar la sintaxis de Bash con el runtime completo de Python 3 en un mismo intérprete.
  * *Ventajas para la IA:* Actúa como un "implante en espacio de usuario". Permite al agente invocar librerías del sistema (`psutil`, `os`, `socket`, `sliver-py`) directamente en la línea de comandos sin levantar subprocesos adicionales.
* **Nushell (`nu`) y `jc` (JSON Convert):**
  * *Historia:* Nushell (2019, Rust) replanteó las tuberías de Unix inspirándose en PowerShell y programación funcional para que todo sea una tabla tipada. `jc` (creado por Kelly Brazil) nació para envolver binarios clásicos de Unix (`df`, `mount`, `ss`, `systemctl`) y escupir diccionarios JSON.
  * *Ventajas para la IA:* Reducen drásticamente el consumo de tokens del LLM al eliminar la necesidad de usar expresiones regulares (`awk`, `sed`, `grep`) sobre salidas de texto desalineadas.

---

## 2. Consolidación Técnica: Matriz de Fusión (Camino A + Camino B en Ubuntu)

| Capacidad / Operación | Quién la ejecuta | Mecanismo Técnico en Ubuntu |
| :--- | :--- | :--- |
| **Inspección rápida de red, sockets y procesos** | **Camino A (Sliver)** | Llamadas directas vía Protobuf (`session.netstat()`, `session.ps()`) sin invocar binarios `/bin/*`. |
| **Ejecución de binarios aislados en RAM** | **Camino A (Sliver)** | Syscall `memfd_create` + `fexecve` gestionada por el implante local en modo *Session*. |
| **Túneles de red, SOCKS5 y Port Forwarding** | **Camino A (Sliver)** | Multiplexación en memoria sobre el canal mTLS/WireGuard del implante. |
| **Compilaciones, Docker builds, tests y scripts largos** | **Camino B (Pueue)** | Encolado asíncrono (`pueued`) con captura independiente de `stdout`/`stderr` y persistencia ante fallos. |
| **Herencia en subprocesos nativos del Agente** | **Camino B (`~/.zshenv`)** | Inyección de variables anti-bloqueo (`PAGER=cat`) y funciones wrapper JSON en cada hilo hijo que abra el agente. |
| **Consultas complejas sobre archivos y telemetría** | **Camino B (Nushell / `jc`)** | Pipelines tipados (`nu -c "... \| to json"`) consumidos directamente por el agente. |

### Límites Físicos y de Kernel que NO aplican en Ubuntu
1. **APIs exclusivas de Windows:** Técnicas de *Havoc* o *Brute Ratel* como *NTDLL Unhooking*, *AMSI/ETW Patching*, *Indirect Syscalls* sobre Win32 API o *COFF/BOFs* de Windows no existen en Linux. En Ubuntu el control de bajo nivel opera sobre **`ptrace`, `/proc`, namespaces, cgroups y eBPF**.
2. **Persistencia de variables en el implante C2:** El implante de Sliver no guarda variables `export FOO=bar` entre un comando `execute` y el siguiente (solo mantiene el directorio actual con `cd`). El estado de entorno persistente lo maneja el **Camino B**.
3. **TUIs Interactivas:** Ninguno de los caminos debe ejecutar herramientas visuales como `htop`, `vim` o prompts de `sudo` interactivos dentro del canal RPC; todo debe ser estrictamente no-interactivo.

---

## 3. Validación de "Omarchy": ¿Qué resolvió ya y qué adoptamos en nuestro Plan?

### 3.1. ¿Qué es Omarchy realmente?
**Omarchy** (creada por David Heinemeier Hansson —DHH— en 2025 y consolidada en 2026 con su versión *4.0 Quattro* bajo la *Omacom Foundation*) es una distribución Linux de código abierto basada en **Arch Linux + Hyprland + Quickshell**, definida como **"The Agentic OS for the age of agents"** (tiene un proyecto hermano previo para Ubuntu llamado *Omakub*, aunque la innovación de agentes vive en Omarchy).

### 3.2. Veredicto de Validación: ¿Resolvió Omarchy nuestra arquitectura?
**Lo resolvió a mitad de camino (en la capa de Sistema Operativo, Escritorio y Skills), pero NO en la capa de bajo nivel C2 ni en un motor de colas asíncronas.**

Tras auditar la arquitectura abierta de Omarchy (`github.com/omacom/omarchy` y el ecosistema comunitario como `omarchy-skills` y `omarchy-mcp`), este es el desglose exacto de qué existe y qué no:

#### Lo que Omarchy SÍ resolvió (y que debemos **copiar/adoptar** sin reinventar):
1. **Unificación del Plano de Control del Sistema (`omarchy` CLI):** En lugar de que la IA adivine dónde están los archivos de configuración dispersos en `/etc` o `~/.config`, Omarchy expone un único binario/CLI (`omarchy`) con subcomandos deterministas y autodocumentados (`--help` estructurado) para controlar ventanas, capturas, audio, temas, servicios y paquetes.
2. **Enrutamiento Automático de Crashes al Agente (`systemd-coredump` hook):** Omarchy vigila los fallos del sistema a nivel de kernel/systemd. Cuando un binario colapsa (segmentation fault / core dump), captura el volcado y se lo entrega pre-empaquetado al agente por defecto para su diagnóstico inmediato.
3. **Patrón de Carpeta Única de Skills (Symlink Hub):** En lugar de configurar herramientas distintas para Claude Code, Codex, OpenCode, Cursor o Grok, Omarchy utiliza una única jerarquía de *Agent Skills* (`~/.local/share/omarchy/skills` o `~/.agents/skills`) enlazada simbólicamente a los directorios de todos los agentes CLI instalados (que además se cargan bajo demanda o *lazy-loading*).
4. **Conocimiento Semántico Local (`omarchy-mcp`):** La comunidad ya resolvió el MCP de documentación local usando **ChromaDB + `all-MiniLM-L6-v2`** para que el agente consulte manuales del sistema y wikis offline sin gastar tokens buscando en la web.

#### Lo que Omarchy NO resolvió (y por qué nuestro MCP sigue siendo indispensable):
* Omarchy **no incluye un motor C2 en memoria** como Sliver (no hace inyección ELF con `memfd_create`, ni pivoting SOCKS5/WireGuard integrado, ni inspección vía Protobuf).
* Omarchy **no tiene un gestor de colas de procesos asíncronos** como `Pueue` para evitar que los subprocesos largos de los agentes bloqueen el hilo de ejecución.
* Omarchy está atado a **Arch Linux (`pacman`) y Hyprland/Quickshell**. Como tu sistema operativo base es **Ubuntu**, debemos portar sus patrones arquitectónicos (el CLI unificado, el hook de `systemd-coredump` y el hub de *Skills*) sobre nuestro stack **Ubuntu + Sliver + Pueue**.

---

## 4. Plan Maestro: Construcción del MCP Unificado ("OmniShell-C2-MCP") e Instalación

Para evitar duplicar lo que Omarchy ya demostró que funciona, combinaremos **3 capas**:
1. **Herencia directa en subprocesos (`~/.zshenv` + Skills al estilo Omarchy)** para cuando el agente use su propia consola integrada.
2. **Servidor FastMCP en Python (`c2_system_mcp.py`)** que une el cliente gRPC de **Sliver (`sliver-py`)**, el demonio **Pueue**, el motor **Nushell** y el analizador de **Core Dumps** en una sola interfaz de herramientas tipadas.
3. **Script de Aprovisionamiento Automatizado para Ubuntu** que instala y enlaza todo el ecosistema.

### 4.1. Arquitectura del Servidor MCP a Construir

```mermaid
flowchart TD
    subgraph AgentLayer["Agente de IA (Claude Code / OpenCode / Antigravity / Cursor)"]
        A["Agente Autónomo de IA"]
    end

    subgraph Layer1["Capa de Herencia (~/.zshenv + Skills Hub)"]
        H1["Variables anti-bloqueo (PAGER=cat)"]
        H2["Symlink Hub de Skills (Omarchy Way)"]
        H3["CLI unificado: sysctl-ai"]
    end

    subgraph LayerMCP["Servidor FastMCP (OmniShell-C2-MCP)"]
        M1["FastMCP Engine (Python 3 + Pydantic + Catalog)"]
    end

    subgraph BackendA["Camino A: Inyección de Memoria y C2"]
        S1["Sliver Daemon / memfd_create en RAM"]
        S2["Inspección vía Protobuf / gRPC"]
    end

    subgraph BackendB["Camino B + Patrones Omarchy"]
        B1["Pueue Daemon (Colas Asíncronas)"]
        B2["Nushell / jc (Salidas Tipadas)"]
        B3["systemd-coredump (Forense de Fallos)"]
    end

    A -->|1. Subprocesos Nativos (Shell)| Layer1
    A -->|2. Protocolo MCP (stdio/SSE)| LayerMCP
    Layer1 --> BackendA
    LayerMCP -->|gRPC / memfd| BackendA
    LayerMCP -->|JSON IPC / CLI| BackendB
```

### 4.2. Catálogo de Herramientas (Tools) del Servidor MCP

El servidor MCP expondrá únicamente **6 herramientas de alto impacto** (para no saturar la ventana de contexto del agente, delegando el resto a los *Skills* estilo Omarchy):

1. `c2_implant_inspect(target: Literal["ps", "netstat", "ifconfig", "env"])`: Consulta directamente al implante local de Sliver vía gRPC (`sliver-py`), devolviendo un esquema JSON limpio desde la memoria sin ejecutar binarios de `/bin`.
2. `c2_execute_in_memory(elf_path: str, args: list[str])`: Usa la primitiva `execute-assembly` / `sideload` de Sliver sobre `memfd_create` para correr binarios en RAM sin tocar el disco.
3. `c2_network_pivot(action: Literal["start_socks5", "stop_socks5", "portfwd_add"], port: int, remote_target: str)`: Abre o cierra túneles de red gestionados por el implante de Sliver.
4. `async_job_dispatch(command: str, group: str = "default", working_dir: str = ".")`: Encola tareas pesadas en el demonio **Pueue** (`Camino B`) y devuelve el `task_id` de inmediato.
5. `async_job_inspect(task_id: int | None = None, tail_lines: int = 50)`: Recupera el estado JSON de la cola de Pueue y las últimas líneas de salida sin bloquear al agente.
6. `diagnose_system_crashes(limit: int = 5)`: *(Inspirado en Omarchy)* Consulta `coredumpctl --json=short` y `journalctl -p err -o json`, extrayendo el stacktrace de cualquier aplicación o servicio que haya fallado recientemente en Ubuntu.

---

## 5. Implementación Paso a Paso en Ubuntu

### Fase 1: Aprovisionamiento de Componentes Base (Ubuntu)

Ejecuta este bloque para instalar los motores del **Camino B** (`jc`, `jq`, `pueue`, `nushell`, `systemd-coredump`) y el gestor de paquetes `uv` para el MCP:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "[1/5] Instalando utilidades estructuradas, Pueue y captura de Core Dumps..."
sudo apt update && sudo apt install -y \
    jq jc ripgrep fd-find pueue systemd-coredump build-essential curl git

echo "[2/5] Instalando Nushell en Ubuntu..."
if ! command -v nu &> /dev/null; then
    curl -fsSL https://apt.fury.io/nushell/gpg.key | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/fury-nushell.gpg
    echo "deb https://apt.fury.io/nushell/ /" | sudo tee /etc/apt/sources.list.d/fury.list
    sudo apt update && sudo apt install -y nushell
fi

echo "[3/5] Activando el demonio de colas Pueue a nivel de usuario..."
systemctl --user enable --now pueued || pueued -d

echo "[4/5] Instalando uv (Gestor de entornos Python ultrarrápido para el MCP)..."
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "[5/5] Creando estructura de Skills Unificados (Patrón Omarchy)..."
mkdir -p "$HOME/.local/share/agent-os/skills"
mkdir -p "$HOME/.local/share/agent-os/mcp"
mkdir -p "$HOME/.claude/skills"
# Enlace simbólico único para que cualquier agente herede las mismas skills
ln -sfn "$HOME/.local/share/agent-os/skills" "$HOME/.claude/skills/agent-os"
```

### Fase 2: Despliegue de Sliver C2 Local y Auto-Implante (Camino A)

```bash
# 1. Instalar Sliver Server y Client
curl https://sliver.sh/install | sudo bash

# 2. Generar perfil de operador para el Servidor MCP (gRPC sobre 127.0.0.1)
mkdir -p "$HOME/.sliver-client/configs"
sudo sliver-server operator \
    --name mcp_orchestrator \
    --lhost 127.0.0.1 \
    --save "$HOME/.sliver-client/configs/mcp_orchestrator.cfg"
sudo chown "$USER:$USER" "$HOME/.sliver-client/configs/mcp_orchestrator.cfg"

# 3. Dentro de la consola de sliver-server (ejecutar una vez):
# sliver > mtls --lhost 127.0.0.1 --lport 8888 --persistent
# sliver > generate --mtls 127.0.0.1:8888 --os linux --arch amd64 --format executable --save /home/$USER/.local/bin/local-c2-implant
# Luego agregar /home/$USER/.local/bin/local-c2-implant a una cola fija de Pueue o servicio systemd --user.
```

### Fase 3: Código Base del Servidor MCP (`~/.local/share/agent-os/mcp/server.py`)

Este servidor utiliza **FastMCP**, **Pydantic** y se conecta tanto a **Sliver (`sliver-py`)** como a **Pueue**, **Nushell** y **`coredumpctl`**:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mcp[cli]>=1.2.0",
#     "sliver-py>=0.0.19",
#     "pydantic>=2.0.0",
# ]
# ///

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Literal, Optional
from mcp.server.fastmcp import FastMCP
from sliver import SliverClientConfig, SliverClient

mcp = FastMCP("Ubuntu-C2-AgenticOS")

SLIVER_CFG = Path.home() / ".sliver-client" / "configs" / "mcp_orchestrator.cfg"

async def _get_active_sliver_session():
    """Conecta al demonio local de Sliver vía gRPC y obtiene la primera sesión activa."""
    if not SLIVER_CFG.exists():
        raise FileNotFoundError(f"No se encontró el perfil gRPC de Sliver en {SLIVER_CFG}")
    config = SliverClientConfig.parse_config_file(str(SLIVER_CFG))
    client = SliverClient(config)
    await client.connect()
    sessions = await client.sessions()
    if not sessions:
        raise RuntimeError("Sliver gRPC activo, pero no hay implantes en modo Session conectados.")
    return await client.interact_session(sessions[0].ID)

@mcp.tool()
async def c2_implant_inspect(target: Literal["ps", "netstat", "ifconfig"]) -> str:
    """
    [CAMINO A - Sliver C2] Inspecciona procesos, sockets o interfaces de red directamente
    desde la memoria del implante usando Protobuf sin invocar binarios del sistema.
    """
    session = await _get_active_sliver_session()
    if target == "ps":
        procs = await session.ps()
        return json.dumps([
            {"pid": p.Pid, "ppid": p.Ppid, "executable": p.Executable, "owner": p.Owner}
            for p in procs
        ], indent=2)
    elif target == "netstat":
        conns = await session.netstat(tcp=True, udp=True, ipv4=True, listening=True)
        return json.dumps([
            {"local": c.LocalAddr, "remote": c.RemoteAddr, "protocol": c.Protocol, "state": c.SkState, "pid": c.Process.Pid if c.Process else None}
            for c in conns.Entries
        ], indent=2)
    elif target == "ifconfig":
        ifaces = await session.ifconfig()
        return json.dumps([
            {"name": i.Name, "mac": i.MAC, "ips": [ip for ip in i.IPAddresses]}
            for i in ifaces.NetInterfaces
        ], indent=2)

@mcp.tool()
def async_job_dispatch(command: str, label: Optional[str] = None, working_dir: Optional[str] = None) -> str:
    """
    [CAMINO B - Pueue] Encola un comando pesado o de larga duración en segundo plano.
    Devuelve inmediatamente el task_id para evitar bloqueos de subprocesos.
    """
    cmd = ["pueue", "add", "--print-task-id"]
    if label:
        cmd.extend(["--label", label])
    if working_dir:
        cmd.extend(["--working-directory", working_dir])
    cmd.extend(["--", command])
    
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.dumps({"status": "queued", "task_id": int(res.stdout.strip()), "command": command})

@mcp.tool()
def async_job_inspect(task_id: Optional[int] = None, lines: int = 40) -> str:
    """
    [CAMINO B - Pueue] Consulta el estado en JSON de la cola asíncrona o extrae el log de un task_id.
    """
    if task_id is not None:
        res = subprocess.run(["pueue", "log", str(task_id), "--lines", str(lines), "--json"], capture_output=True, text=True)
        return res.stdout
    res = subprocess.run(["pueue", "status", "--json"], capture_output=True, text=True)
    return res.stdout

@mcp.tool()
def nu_structured_query(nu_pipeline: str) -> str:
    """
    [CAMINO B - Nushell] Ejecuta un pipeline tipado de Nushell y garantiza salida en JSON.
    Ejemplo: 'ls /var/log | where size > 1mb | sort-by modified -r'
    """
    full_cmd = f"({nu_pipeline}) | to json"
    res = subprocess.run(["nu", "-c", full_cmd], capture_output=True, text=True)
    if res.returncode != 0:
        return json.dumps({"error": res.stderr.strip()})
    return res.stdout

@mcp.tool()
def diagnose_system_crashes(limit: int = 5) -> str:
    """
    [PATRÓN OMARCHY] Inspecciona volcados de memoria (systemd-coredump) y errores críticos
    recientes del sistema en formato JSON para autodiagnóstico del agente.
    """
    coredumps = subprocess.run(["coredumpctl", "list", "--json=short", "-n", str(limit)], capture_output=True, text=True)
    journal_errs = subprocess.run(["journalctl", "-p", "err", "-n", str(limit), "-o", "json"], capture_output=True, text=True)
    return json.dumps({
        "recent_coredumps": json.loads(coredumps.stdout) if coredumps.returncode == 0 and coredumps.stdout else [],
        "recent_systemd_errors": [json.loads(line) for line in journal_errs.stdout.splitlines() if line.strip()]
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
```

### Fase 4: Herencia en Subprocesos (`~/.zshenv`) y Registro en el Agente

Para que el agente tenga poder **tanto vía MCP como cuando ejecuta subprocesos directos en su consola**, añade a tu `~/.zshenv`:

```zsh
# ~/.zshenv - Herencia Universal para Subprocesos de Agentes de IA
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PAGER="cat"
export SYSTEMD_PAGER="cat"
export GIT_PAGER="cat"
export DEBIAN_FRONTEND="noninteractive"

# Wrapper JSON instantáneo (Camino B)
jrun() { jc --pretty "$@"; }

# Atajo al encolador asíncrono Pueue para subprocesos directos
bg_exec() { pueue add --print-task-id -- "$@"; }
bg_stat() { pueue status --json; }

# Telemetría en un solo comando vía Nushell
sys_json() { nu -c "sys host | merge (sys mem) | to json"; }
```

Finalmente, registra el servidor MCP en tu agente principal (por ejemplo, en Claude Code):

```bash
chmod +x ~/.local/share/agent-os/mcp/server.py
claude mcp add --scope user ubuntu-c2-os -- uv run ~/.local/share/agent-os/mcp/server.py
```

---

## 6. Resumen de Ventajas Competitivas de tu Arquitectura Final

1. **No reinventas lo que Omarchy ya perfeccionó:** Adoptas el patrón de **carpeta única de Skills enlazada por symlinks**, el concepto de **CLI unificado** y el **diagnóstico automático de Core Dumps (`systemd-coredump`)** sin tener que abandonar Ubuntu por Arch Linux.
2. **Doble vía de ejecución (MCP + Herencia en Subprocesos):** Si usas un CLI/TUI que soporta MCP, invoca las herramientas de `server.py`. Si el agente decide abrir un subproceso de shell (`zsh -c`), hereda automáticamente `~/.zshenv` con `Pueue`, `Nushell` y `jc`.
3. **Potencia C2 real sin bloqueos:** Tienes la introspección en memoria y capacidades de red de **Sliver C2 (Camino A)** respaldadas por las colas asíncronas indestructibles de **Pueue (Camino B)**.