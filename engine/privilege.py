"""
Engine: privilege.py — Modelo de niveles de capacidad (least-privilege por defecto).

Fuente de verdad única sobre el privilegio disponible. Las tools privilegiadas del stack
lo consultan para operar en dos niveles:

  - FULL       : el proceso es root, o puede escalar sin password (sudo -n). Alcance
                 de sistema (observabilidad kernel-wide, control de servicios, coredumps
                 de otros usuarios).
  - DIMINISHED : usuario sin vía de escalada. Alcance acotado al propio usuario/proceso;
                 la capacidad existe pero con apertura reducida (fail-soft, nunca excepción).

Diseño de seguridad: la escalada es por-tool y acotada; nunca se asume root. Un nivel más
alto AMPLÍA la apertura (self-scope -> system-scope), no es un requisito para operar.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.privilege")


TIER_7RWX = "7rwx"
TIER_6RW = "6rw-"
TIER_5RX = "5r-x"
TIER_4R = "4r--"
ALL_TIERS = (TIER_7RWX, TIER_6RW, TIER_5RX, TIER_4R)
TIER_OCTALS = {TIER_7RWX: 7, TIER_6RW: 6, TIER_5RX: 5, TIER_4R: 4}


class _PrivilegeCache:
    sudo_n: bool | None = None
    tier_info: dict[str, Any] | None = None

    @classmethod
    def reset(cls) -> None:
        """Reset cached privilege and tier evaluations (Ontos Advisory 2)."""
        cls.sudo_n = None
        cls.tier_info = None


def sudo_n_available() -> bool:
    """¿Hay sudo sin contraseña (escalada no-interactiva)? Resultado cacheado por proceso (timeout <= 3s)."""
    if _PrivilegeCache.sudo_n is None:
        try:
            _PrivilegeCache.sudo_n = (
                bool(shutil.which("sudo"))
                and subprocess.run(
                    ["sudo", "-n", "true"], capture_output=True, timeout=3, check=False
                ).returncode == 0
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("sudo -n check failed: %s", e)
            _PrivilegeCache.sudo_n = False
    return _PrivilegeCache.sudo_n


def detect_chmod_tier(workspace_path: Path | str | None = None) -> dict[str, Any]:
    """
    Determina predictivamente el nivel chmod del entorno actual (7rwx, 6rw-, 5r-x, 4r--).
    Garantiza cero bloqueos interactivos (sudo -n <= 3s timeout) y evaluación jerárquica.
    """
    forced = os.environ.get("AEP_FORCE_TIER") or os.environ.get("AEP_CHMOD_TIER")
    if forced and forced in ALL_TIERS:
        octal = TIER_OCTALS[forced]
        mode_map = {
            TIER_7RWX: "forced-root",
            TIER_6RW: "forced-user-rw",
            TIER_5RX: "forced-ro-exec",
            TIER_4R: "forced-auditor-ro",
        }
        return {
            "tier": forced,
            "octal": octal,
            "mode": mode_map.get(forced, "forced"),
            "is_root": forced == TIER_7RWX,
            "sudo_n": forced == TIER_7RWX,
            "workspace_writable": forced in (TIER_7RWX, TIER_6RW),
            "exec_permitted": forced in (TIER_7RWX, TIER_6RW, TIER_5RX),
            "probe_flags": {
                "forced": True,
                "euid": 0 if forced == TIER_7RWX else 1000,
                "sudo_n": forced == TIER_7RWX,
                "workspace_w_ok": forced in (TIER_7RWX, TIER_6RW),
                "dev_shm_w_ok": forced in (TIER_7RWX, TIER_6RW, TIER_5RX),
            },
            "degradation_plan": {
                "system_services": "MUTATE_SYSTEM" if octal == 7 else ("USER_SCOPE" if octal == 6 else "READ_ONLY"),
                "ebpf_tracing": "FULL" if octal == 7 else "FALLBACK_PROC_NET",
                "sandbox": "FULL" if octal in (7, 6) else ("RO_BIND" if octal == 5 else "DISABLED"),
                "build_synthesis": "FULL" if octal in (7, 6) else ("LINT_ONLY" if octal == 5 else "DISABLED"),
                "ram_execution": "FULL" if octal in (7, 6, 5) else "DISABLED",
            },
        }

    is_root = os.geteuid() == 0
    can_sudo = False if is_root else sudo_n_available()

    ws = Path(workspace_path).resolve() if workspace_path else Path(__file__).resolve().parent.parent
    ws_w_ok = os.access(ws, os.W_OK)
    shm_w_ok = os.access(Path("/dev/shm"), os.W_OK) if Path("/dev/shm").exists() else False
    exec_ok = os.access(Path("/proc/self/exe"), os.X_OK) or bool(shutil.which("python3") or shutil.which("sh"))

    if is_root or can_sudo:
        tier = TIER_7RWX
        mode = "direct-root" if is_root else "sudo-n"
    elif ws_w_ok and shm_w_ok:
        tier = TIER_6RW
        mode = "unprivileged-rw"
    elif exec_ok:
        tier = TIER_5RX
        mode = "restricted-ro-exec"
    else:
        tier = TIER_4R
        mode = "auditor-ro"

    octal = TIER_OCTALS[tier]

    return {
        "tier": tier,
        "octal": octal,
        "mode": mode,
        "is_root": is_root,
        "sudo_n": can_sudo,
        "workspace_writable": ws_w_ok,
        "exec_permitted": exec_ok,
        "probe_flags": {
            "forced": False,
            "euid": os.geteuid(),
            "sudo_n": can_sudo,
            "workspace_w_ok": ws_w_ok,
            "dev_shm_w_ok": shm_w_ok,
        },
        "degradation_plan": {
            "system_services": "MUTATE_SYSTEM" if octal == 7 else ("USER_SCOPE" if octal == 6 else "READ_ONLY"),
            "ebpf_tracing": "FULL" if octal == 7 else "FALLBACK_PROC_NET",
            "sandbox": "FULL" if octal in (7, 6) else ("RO_BIND" if octal == 5 else "DISABLED"),
            "build_synthesis": "FULL" if octal in (7, 6) else ("LINT_ONLY" if octal == 5 else "DISABLED"),
            "ram_execution": "FULL" if octal in (7, 6, 5) else "DISABLED",
        },
    }


def get_effective_chmod_tier(workspace_path: Path | str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    """Devuelve información estructurada del nivel chmod con caché a nivel de proceso."""
    if _PrivilegeCache.tier_info is None or force_refresh:
        _PrivilegeCache.tier_info = detect_chmod_tier(workspace_path)
    return _PrivilegeCache.tier_info


def privilege_prefix() -> list[str] | None:
    """[] si ya es root; ['sudo','-n'] si se puede escalar; None si no hay vía (DIMINISHED)."""
    eff = get_effective_chmod_tier()
    if eff["tier"] == TIER_7RWX:
        if eff.get("is_root") or os.geteuid() == 0:
            return []
        return ["sudo", "-n"]
    return None


def privilege_mode() -> str:
    """Etiqueta del modo efectivo: direct-root | sudo-n | unprivileged-rw | restricted-ro-exec | auditor-ro."""
    eff = get_effective_chmod_tier()
    return eff["mode"]


# Constantes de capacidades
CAP_RAM_EXEC = "ram_execution"
CAP_EPHEMERAL_SANDBOX = "ephemeral_sandbox"
CAP_ARTIFACT_SYNTHESIS = "artifact_synthesis"
CAP_ORIENTATION = "orientation"
CAP_SEMANTIC_MEMORY = "semantic_memory"
CAP_ASYNC_DISPATCH = "async_dispatch"
CAP_PROCESS_INTROSPECTION = "process_introspection"
CAP_SYSTEM_INSPECT = "system_inspect"
CAP_SERVICE_CONTROL = "service_control"
CAP_CRASH_FORENSICS = "crash_forensics"
CAP_KERNEL_OBSERVABILITY = "kernel_observability"
CAP_VISUAL_ACTUATION = "visual_actuation"
CAP_TOPOS_AUDIT = "topos_audit"
CAP_TASK_MANAGEMENT = "task_management"
CAP_AUTOMATION = "automation"
CAP_SYSTEM_DOCS = "system_docs"
CAP_BACKUP_ADMIN = "backup_admin"
CAP_AUDIT_READ = "audit_read"


def capability_tier() -> str:
    """FULL si hay root o escalada disponible (7rwx); DIMINISHED en caso contrario (6rw-, 5r-x, 4r--)."""
    eff = get_effective_chmod_tier()
    return "FULL" if eff["tier"] == TIER_7RWX else "DIMINISHED"


# ---------------------------------------------------------------------------
# Manifiesto de autonomía auto-descriptivo (códigos estilo chmod/777).
#
# Reutilizamos la tríada rwx de Unix, resignificada para la autonomía del agente:
#   r (4) = SENSAR     — leer estado/telemetría del sistema
#   w (2) = ACTUAR     — mutar estado del sistema
#   x (1) = EJECUTAR   — correr por caminos no-tradicionales (RAM / kernel / escalada)
# Cada capacidad lleva un octal por nivel (DIMINISHED vs FULL). El nivel más alto AMPLÍA
# la apertura; la mayoría de bits ya están disponibles en DIMINISHED (la autonomía no
# depende del privilegio: lo usa para ensanchar el alcance de self-scope a system/kernel).
# ---------------------------------------------------------------------------

# cap -> (bits_DIMINISHED, bits_FULL, scope_FULL, tools, descripción)
_CAPABILITIES = {
    "ram_execution": (5, 5, "self", ["artifact_execute_in_ram"], "Inyectar y correr ELF en RAM (memfd_create)"),
    "ephemeral_sandbox": (5, 5, "self", ["sandbox_run"], "Ejecutar aislado en sandbox bwrap"),
    "artifact_synthesis": (
        7,
        7,
        "self",
        ["artifact_lint_and_build"],
        "Sintetizar artefactos Go: inspección de plantillas, selección fuzzy, hidratación CUE y compilación/linting en RAM (artifact_lint_and_build: action='build'|'catalog'|'select'|'hydrate')",
    ),
    "orientation": (
        4,
        4,
        "self",
        ["discover"],
        "Traducir un caso de uso -> qué reutilizar/sintetizar/automatizar y manifiesto de autonomía (discover: action='discover'|'capabilities')",
    ),
    "semantic_memory": (
        6,
        6,
        "self",
        ["artifact_catalog"],
        "Leer/escribir, DESCUBRIR, AUTO-INDEXAR y PODAR (GC seguro) la memoria semántica (sqlite-vec)",
    ),
    "async_dispatch": (
        7,
        7,
        "self",
        ["async_job_dispatch"],
        "Despachar/inspeccionar tareas asíncronas en Pueue (async_job_dispatch: action='dispatch'|'inspect')",
    ),
    "process_introspection": (
        4,
        4,
        "system",
        ["process_inspect"],
        "Introspección de descriptores de procesos (/proc/PID/fd y estado)",
    ),
    "system_inspect": (4, 4, "system", ["aep_ctl"], "Leer red, almacenamiento y paquetes (aep-ctl)"),
    "service_control": (
        4,
        6,
        "system",
        ["aep_ctl"],
        "Controlar servicios: DIMINISHED solo scope-usuario; FULL muta sistema",
    ),
    "crash_forensics": (
        4,
        4,
        "system",
        ["diagnose_system_crashes"],
        "Forense de crashes y alertas proactivas: coredumps, journald y tickets (diagnose_system_crashes: action='diagnose'|'alerts')",
    ),
    "kernel_observability": (0, 4, "kernel", ["kernel_trace"], "Telemetría de kernel eBPF: requiere FULL (CAP_BPF)"),
    "visual_actuation": (5, 5, "self", ["visual_inspect"], "Renderizar y capturar UIs headless (/dev/shm)"),
    "topos_audit": (4, 4, "self", ["topos_audit_dag"], "Auditar DAGs y bloquear co-dependencias"),
    "task_management": (
        6,
        6,
        "self",
        ["kanban_board"],
        "Pico-Kanban: tareas atómicas + ponderación con promoción/degradación y archivado reversible",
    ),
    "automation": (
        7,
        7,
        "self",
        ["playbook_run"],
        "Pico-Playbooks: orquestación de flujos DAG, ejecución, listado, creación y poda segura (playbook_run: action='run'|'create'|'list'|'prune')",
    ),
    "backup_admin": (
        4,
        6,
        "system",
        ["aep_ctl"],
        "Gestión de copias de seguridad y rotación de backups (aep-ctl backup)",
    ),
    "audit_read": (4, 4, "self", ["aep_ctl"], "Inspección y verificación de la cadena de auditoría criptográfica"),
    "system_docs": (
        4,
        4,
        "self",
        ["query_system_docs"],
        "Memoria semántica local de man-pages (sqlite-vec): sintaxis exacta sin alucinar flags",
    ),
    "default_primitives": (
        5,
        5,
        "self",
        ["default_primitives"],
        "Ejecutar sondas de diagnóstico del sistema por defecto en RAM",
    ),
}

_PERM_TABLE = {7: "rwx", 6: "rw-", 5: "r-x", 4: "r--", 3: "-wx", 2: "-w-", 1: "--x", 0: "---"}

# Keywords BILINGÜES (EN/ES) por capacidad: anclas léxicas language-aligned para el enrutador
# `discover`. Las descriptions están en español y los names/tools en inglés, así que una query EN
# ("run binary", "memory", "trace kernel") tenía poco con qué casar. Esto cierra la colisión ES/EN:
# el matcher las pondera como tags (x2) sumadas a los nombres de tools. Ampliar aquí es barato.
_CAP_KEYWORDS = {
    "ram_execution": "run binary memfd fileless in-memory ejecutar binario memoria elf payload probe",
    "ephemeral_sandbox": "sandbox isolate bwrap jail contained run test pytest repo workspace mount ro_paths rw_paths working_dir aislar aislado seguro pruebas",
    "artifact_synthesis": "synthesize template catalog select hydrate lint build compile go binary cue contract schema validate code static analysis vet generar crear sintetizar plantilla catalogo seleccionar hidratar compilar construir binario",
    "orientation": "discover orient what to do route start where begin capabilities manifest status chmod permisos autonomy autonomia playbook tactical guide help how to use orientar descubrir enrutar empezar",
    "semantic_memory": "memory search recall catalog query reindex prune index vector embeddings reuse find store sqlite vec memoria buscar recordar catalogo consultar indice podar sanar reutilizar guardar",
    "async_dispatch": "async background queue long job pueue dispatch inspect status log test suite ruff pytest ci lint verify cola asincrono tarea larga despachar inspeccionar estado segundo plano",
    "process_introspection": "process inspect fd descriptor proc pid introspection open files socket pipes leak rss memory telemetry resource footprint proceso descriptor introspeccion archivos abiertos fugas",
    "system_inspect": "network storage packages inspect read system status listeners mounts disks schema aep_ctl control plane contract red almacenamiento paquetes inspeccionar sistema estado esquema",
    "service_control": "service control start stop restart systemd daemon unit servicio controlar arrancar detener reiniciar",
    "crash_forensics": "crash core dump forensic coredump diagnose fault alerts router ticket new proactive journalctl systemd errors crasheo volcado forense diagnosticar fallo alertas enrutador ticket nuevo proactivo",
    "kernel_observability": "kernel trace ebpf bpf syscall observe probe openat execve landlock denials trazar sondear llamadas sistema",
    "visual_actuation": "visual screenshot render headless ui browser page html dom layout playwright chromium visual captura renderizar pantalla navegador",
    "topos_audit": "audit dag graph dependency cycle codependency architecture code review structural verification validation plan auditar grafo dependencia ciclo arquitectura",
    "task_management": "task kanban board create advance promote demote reevaluate archive unarchive manage weigh track milestone state tarea tablero crear avanzar promover degradar reevaluar archivar desarchivar gestionar ponderar seguir",
    "automation": "automate playbook run create list prune workflow chain pipeline steps gc clean orchestrate automatizar ejecutar crear listar podar orquestar flujo secuencia pasos limpiar",
    "backup_admin": "backup restore recover rotation hot snapshot sqlite wal quarantine golden micro_snapshot copia seguridad restaurar",
    "audit_read": "audit log security chain cryptographic hash ledger tamper verify verificar auditoria cadena criptografica",
    "system_docs": "man manpage documentation syntax flags command help manual documentacion sintaxis comando",
    "default_primitives": "default primitives system diagnostic probes socket monitor fd rescuer disk usage mem stat landlock guard ram in-memory sondas diagnostico primitivas por defecto memoria",
}

# ---------------------------------------------------------------------------
# Matriz de Degradación Elegante Chmod de 4 Niveles (ONT-33)
# ---------------------------------------------------------------------------
CHMOD_DEGRADATION_MATRIX: dict[str, dict[str, dict[str, str]]] = {
    "tools": {
        "topos_audit_dag": {
            TIER_7RWX: "Full graph audit & resource hazard check",
            TIER_6RW: "Full graph audit & resource hazard check",
            TIER_5RX: "Full graph audit & resource hazard check",
            TIER_4R: "Full graph audit (pure in-RAM verification)",
        },
        "discover": {
            TIER_7RWX: "Full capability & schema reflection (7rwx)",
            TIER_6RW: "Full capability & schema reflection (6rw-)",
            TIER_5RX: "Reflects 5r-x tier & read-only tools",
            TIER_4R: "Reflects 4r-- tier & auditor mode",
        },
        "artifact_catalog": {
            TIER_7RWX: "Full RW indexing, query, and pruning",
            TIER_6RW: "Full RW indexing, query, and safe GC",
            TIER_5RX: "Read-only query & template browse",
            TIER_4R: "Read-only query (metadata inspection only)",
        },
        "artifact_lint_and_build": {
            TIER_7RWX: "Full build, hydrate, vet, & compile in RAM",
            TIER_6RW: "User-space compile in /dev/shm / tmpfs",
            TIER_5RX: "Template inspection & syntax linting",
            TIER_4R: "Template inspection (build disabled)",
        },
        "artifact_execute_in_ram": {
            TIER_7RWX: "Execute in anonymous RAM (memfd_create)",
            TIER_6RW: "Execute in anonymous RAM (memfd_create)",
            TIER_5RX: "Execute in anonymous RAM (isolated)",
            TIER_4R: "Disabled (status: PERMISSION_DENIED)",
        },
        "process_inspect": {
            TIER_7RWX: "Inspect all system PIDs, FDs, and sockets",
            TIER_6RW: "Inspect user-owned PIDs and AEP self",
            TIER_5RX: "Inspect self PID and open FDs",
            TIER_4R: "Inspect self PID memory footprint only",
        },
        "async_job_dispatch": {
            TIER_7RWX: "Dispatch to Pueue system/user daemon",
            TIER_6RW: "Dispatch to Pueue user daemon",
            TIER_5RX: "Synchronous in-RAM fallback execution",
            TIER_4R: "Status inspection only (dispatch disabled)",
        },
        "diagnose_system_crashes": {
            TIER_7RWX: "Inspect /var/crash & system journal",
            TIER_6RW: "Inspect user coredumps & user journal",
            TIER_5RX: "Inspect local user crash logs",
            TIER_4R: "Read-only crash alert inspection",
        },
        "sandbox_run": {
            TIER_7RWX: "Full Bubblewrap jail (--cap-drop ALL)",
            TIER_6RW: "User namespace Bubblewrap jail",
            TIER_5RX: "Read-only mounted Bubblewrap jail",
            TIER_4R: "Disabled or dry-run mock (parse='auto')",
        },
        "aep_ctl": {
            TIER_7RWX: "Full control across all 9 domains",
            TIER_6RW: "User-scope control across 9 domains",
            TIER_5RX: "Read-only queries across 9 domains",
            TIER_4R: "Auditor inspection across 9 domains",
        },
        "query_system_docs": {
            TIER_7RWX: "Full in-RAM semantic vector man-page search",
            TIER_6RW: "Full in-RAM semantic vector man-page search",
            TIER_5RX: "Full in-RAM semantic vector search",
            TIER_4R: "Full in-RAM semantic vector search",
        },
        "visual_inspect": {
            TIER_7RWX: "Full headless Chromium screenshot (/dev/shm)",
            TIER_6RW: "User headless Chromium screenshot",
            TIER_5RX: "Headless screenshot if display exists",
            TIER_4R: "Degrades to DISPLAY_UNAVAILABLE fail-soft",
        },
        "kernel_trace": {
            TIER_7RWX: "Full eBPF tracing (CAP_BPF / root)",
            TIER_6RW: "Degrades to in-RAM /proc/net telemetry",
            TIER_5RX: "Degrades to in-RAM /proc/net telemetry",
            TIER_4R: "Degrades to in-RAM /proc/net telemetry",
        },
        "kanban_board": {
            TIER_7RWX: "Full task creation, promotion, & archive",
            TIER_6RW: "Full task creation, promotion, & archive",
            TIER_5RX: "Read-only board inspection",
            TIER_4R: "Read-only board inspection",
        },
        "playbook_run": {
            TIER_7RWX: "Full DAG orchestration & batch execution",
            TIER_6RW: "Full DAG orchestration & batch execution",
            TIER_5RX: "Validation & dry-run planning",
            TIER_4R: "Validation & static DAG check only",
        },
        "default_primitives": {
            TIER_7RWX: "Full execution of all built-in primitives across host scope",
            TIER_6RW: "User-scope execution of built-in primitives in RAM",
            TIER_5RX: "Read-only inspection and isolated execution in RAM",
            TIER_4R: "Metadata inspection only (execution disabled: status PERMISSION_DENIED)",
        },
    },
    "domains": {
        "service": {
            TIER_7RWX: "Mutate system units (systemctl start/stop)",
            TIER_6RW: "Mutate user units (systemctl --user)",
            TIER_5RX: "Read-only unit status (systemctl status)",
            TIER_4R: "Read-only unit status (status: DEGRADED)",
        },
        "network": {
            TIER_7RWX: "Raw packet sniff, netfilter drop, probe",
            TIER_6RW: "Port probe, /proc/net sockets, ARP",
            TIER_5RX: "Port probe, /proc/net sockets, ARP",
            TIER_4R: "Cached socket table inspection",
        },
        "storage": {
            TIER_7RWX: "Mount table control, device inspection, df",
            TIER_6RW: "User mount inspection, workspace df",
            TIER_5RX: "User mount inspection, workspace df",
            TIER_4R: "Summary disk usage inspection",
        },
        "package": {
            TIER_7RWX: "Query & install packages via apt-get",
            TIER_6RW: "Inspect $PATH binaries & user venvs",
            TIER_5RX: "Inspect $PATH binaries & user venvs",
            TIER_4R: "Static toolchain report",
        },
        "backup": {
            TIER_7RWX: "5-slot FIFO hot backups & RAM snapshots",
            TIER_6RW: "5-slot FIFO hot backups & RAM snapshots",
            TIER_5RX: "Read-only backup integrity verification",
            TIER_4R: "Read-only backup integrity verification",
        },
        "audit": {
            TIER_7RWX: "Append to SHA-256 chain & verify integrity",
            TIER_6RW: "Append to SHA-256 chain & verify integrity",
            TIER_5RX: "Read-only SHA-256 chain verification",
            TIER_4R: "Read-only SHA-256 chain verification",
        },
        "ipc": {
            TIER_7RWX: "Manage /dev/shm/aep.sock pool & reap",
            TIER_6RW: "Manage /dev/shm/aep.sock pool & reap",
            TIER_5RX: "Client batch execution over socket",
            TIER_4R: "Read-only session pool telemetry",
        },
        "security": {
            TIER_7RWX: "Enforce host netfilter drops via nftables",
            TIER_6RW: "Simulated threat mitigation contracts",
            TIER_5RX: "Simulated threat mitigation contracts",
            TIER_4R: "Read-only firewall status report",
        },
        "hardware": {
            TIER_7RWX: "Full sysfs hardware & DRM accelerator admission with 4096 MiB safety margin",
            TIER_6RW: "User-space hardware introspection & accelerator admission",
            TIER_5RX: "Read-only hardware inventory & DRM accelerator detection",
            TIER_4R: "Static CPU/RAM inventory (accelerators disabled or mocked)",
        },
    },
}

# Single Source of Truth for the Control Plane Schema (shared by scripts/aep-ctl and server.py)
CONTROL_PLANE_SCHEMA: dict[str, dict[str, Any]] = {
    "service": {
        "actions": ["list", "status", "start", "stop", "restart"],
        "arg": "[name]",
        "scope": "systemd --user (DIMINISHED) | system (FULL)",
        "description": "List active systemd services or inspect/mutate a specific service unit without interactive pagers.",
        "preconditions": {
            "list": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "status": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "start": {"privilege_tier": "FULL", "required_fs": [], "fail_soft_behavior": "DEGRADED", "deterministic": True},
            "stop": {"privilege_tier": "FULL", "required_fs": [], "fail_soft_behavior": "DEGRADED", "deterministic": True},
            "restart": {"privilege_tier": "FULL", "required_fs": [], "fail_soft_behavior": "DEGRADED", "deterministic": True},
        },
    },
    "network": {
        "actions": ["inspect", "routes", "listeners", "probe", "interfaces", "arp"],
        "arg": "[target] [ports]",
        "description": "Inspect network interfaces, routing tables, active TCP/UDP listening sockets, local ARP tables, or probe TCP ports.",
        "preconditions": {
            "inspect": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/net/dev"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "routes": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/net/route"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "listeners": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/net/tcp"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "probe": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "interfaces": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/net/dev"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "arp": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/net/arp"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
        },
    },
    "storage": {
        "actions": ["usage", "mounts", "disks"],
        "arg": None,
        "description": "Inspect filesystem byte usage, mount trees, and block devices.",
        "preconditions": {
            "usage": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "mounts": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "disks": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
        },
    },
    "package": {
        "actions": ["installed", "list", "check", "info"],
        "arg": "[name]",
        "description": "Query Debian/Ubuntu dpkg state for installed packages and versions.",
        "preconditions": {
            "installed": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "list": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "check": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "info": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
        },
    },
    "backup": {
        "actions": [
            "backup",
            "restore",
            "status",
            "backup_status",
            "auto_recover",
            "verify_and_auto_recover",
            "verify_integrity",
            "micro_snapshot",
            "restore_micro_snapshot",
            "list_micro_snapshots",
            "clear_micro_snapshots",
            "golden",
            "restore_golden",
            "quarantine_status",
            "workspace_snapshot",
            "workspace_restore",
        ],
        "arg": "[slot_number|name]",
        "description": "Manage 5-slot hot SQLite backups, RAM micro-snapshots (catalog only), workspace snapshots/restores, canary integrity, and quarantine.",
        "preconditions": {
            act: {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True}
            for act in [
                "backup", "restore", "status", "backup_status", "auto_recover",
                "verify_and_auto_recover", "verify_integrity", "micro_snapshot",
                "restore_micro_snapshot", "list_micro_snapshots", "clear_micro_snapshots",
                "golden", "restore_golden", "quarantine_status", "workspace_snapshot", "workspace_restore",
            ]
        },
    },
    "security": {
        "actions": ["landlock_status", "status", "audit", "verify", "firewall_status", "nftables_inspect", "threat_mitigate"],
        "arg": "[target]",
        "description": "Check Linux Landlock LSM kernel ABI support, self-confinement readiness, verify audit chain, inspect firewall/nftables rules, and enforce deterministic netfilter hardening.",
        "preconditions": {
            "landlock_status": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "status": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "audit": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "verify": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "firewall_status": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "DEGRADED", "deterministic": True},
            "nftables_inspect": {"privilege_tier": "FULL", "required_fs": [], "fail_soft_behavior": "DEGRADED", "deterministic": True},
            "threat_mitigate": {"privilege_tier": "FULL", "required_fs": [], "fail_soft_behavior": "SIMULATED", "deterministic": True},
        },
    },
    "audit": {
        "actions": ["verify", "usage"],
        "arg": "[session_id]",
        "description": "Verify the SHA-256 tamper-evident cryptographic audit ledger or inspect per-agent tool usage summary.",
        "preconditions": {
            "verify": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "usage": {"privilege_tier": "DIMINISHED", "required_fs": [], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
        },
    },
    "ipc": {
        "actions": ["status", "ping", "lease", "release", "reap", "pool", "flush", "metrics", "stats", "cache"],
        "arg": "[session_id]",
        "description": "Shared-memory UNIX domain socket pool (/dev/shm/aep.sock) and ephemeral session slot management.",
        "preconditions": {
            act: {"privilege_tier": "DIMINISHED", "required_fs": ["/dev/shm"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True}
            for act in ["status", "ping", "lease", "release", "reap", "pool", "flush", "metrics", "stats", "cache"]
        },
    },
    "hardware": {
        "actions": ["inventory", "accelerators", "admit"],
        "arg": "[device|req_mib] [req_vram_mib] [req_gtt_mib] [margin_mib] | named: --vram, --gtt, --margin, --req",
        "description": (
            "Hardware introspection, CPU/RAM inventory, DRM accelerator (GPU/iGPU) detection, "
            "and pre-flight admission with UMA auto-routing (APUs route unqualified req_mib to GTT; "
            "dGPUs to VRAM) and mandatory 4096 MiB desktop safety margin on GTT."
        ),
        "preconditions": {
            "inventory": {"privilege_tier": "DIMINISHED", "required_fs": ["/proc/cpuinfo", "/proc/meminfo"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "accelerators": {"privilege_tier": "DIMINISHED", "required_fs": ["/sys/class/drm"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
            "admit": {"privilege_tier": "DIMINISHED", "required_fs": ["/sys/class/drm"], "fail_soft_behavior": "IN_MEMORY_FALLBACK", "deterministic": True},
        },
    },
}

_CAP_BINARIES: dict[str, list[str]] = {
    "ram_execution": [],
    "ephemeral_sandbox": ["bwrap"],
    "artifact_synthesis": ["go"],
    "orientation": [],
    "semantic_memory": [],
    "async_dispatch": ["pueue", "pueued"],
    "process_introspection": [],
    "system_inspect": ["ss", "ip", "findmnt", "lsblk", "dpkg-query"],
    "service_control": ["systemctl"],
    "crash_forensics": ["coredumpctl", "journalctl"],
    "kernel_observability": ["bpftrace"],
    "visual_actuation": ["chromium_or_playwright"],
    "topos_audit": [],
    "task_management": [],
    "automation": [],
    "backup_admin": [],
    "audit_read": [],
    "system_docs": ["man"],
    "default_primitives": [],
}

_CAP_TACTICAL: dict[str, dict[str, Any]] = {
    "orientation": {
        "when_to_use": "First call in any session to inspect permissions, binary readiness, tactical playbooks, or route a natural-language task.",
        "canonical_calls": [
            'discover(action="capabilities")',
            'discover(action="playbook")',
            'discover(use_case="run repository test suite in isolated sandbox")',
        ],
    },
    "topos_audit": {
        "when_to_use": "Before executing multi-step plans or code changes to verify zero circular co-dependencies (A <-> B).",
        "canonical_calls": [
            'topos_audit_dag(tasks=["plan", "code", "verify"], dependencies={"plan": [], "code": ["plan"], "verify": ["code"]})',
        ],
    },
    "ephemeral_sandbox": {
        "when_to_use": "Execute untrusted commands, linters, or repository test suites inside an isolated Bubblewrap namespace jail.",
        "canonical_calls": [
            'sandbox_run(command="pytest -q", working_dir="/path/to/repo", ro_paths=["/path/to/repo"], share_net=False)',
            "sandbox_run(command=\"python3 -c 'print(42)'\")",
        ],
    },
    "async_dispatch": {
        "when_to_use": "Run long-running test suites, builds, or linters asynchronously via Pueue without blocking the agent loop.",
        "canonical_calls": [
            'async_job_dispatch(action="dispatch", command="pytest -q", working_dir="/path/to/repo")',
            'async_job_dispatch(action="status", verbosity="summary")',
            'async_job_dispatch(action="log", task_id=1, lines=40)',
        ],
    },
    "system_inspect": {
        "when_to_use": "Query control-plane schema, network listeners, routes, storage mounts, or installed packages as compact typed JSON.",
        "canonical_calls": [
            'aep_ctl(action="schema")',
            'aep_ctl(domain="network", action="listeners", verbosity="summary", limit=20)',
            'aep_ctl(domain="storage", action="mounts", verbosity="summary")',
            'aep_ctl(domain="package", action="check", name="semgrep")',
        ],
    },
    "process_introspection": {
        "when_to_use": "Inspect open file descriptors (/proc/PID/fd), sockets, pipes, threads, and RSS memory delta of AEP or target PIDs.",
        "canonical_calls": [
            'process_inspect(pid=0, limit=25, verbosity="summary")',
            "process_inspect(pid=1234, limit=50)",
        ],
    },
    "ram_execution": {
        "when_to_use": "Execute pre-compiled static Go binaries from the catalog directly in anonymous RAM (memfd_create) with zero disk footprint.",
        "canonical_calls": [
            'artifact_execute_in_ram(name="socket_monitor", args=["--port=8080"])',
        ],
    },
    "artifact_synthesis": {
        "when_to_use": "Select, hydrate, vet, and compile static Go probes (CGO_ENABLED=0) from parameterized templates.",
        "canonical_calls": [
            'artifact_lint_and_build(action="catalog")',
            'artifact_lint_and_build(action="build", name="tcp_probe", intent="monitor tcp port", category="network", template_name="socket_monitor")',
        ],
    },
    "semantic_memory": {
        "when_to_use": "Search, query, reindex, or garbage-collect the hybrid SHA-256 + sqlite-vec artifact catalog.",
        "canonical_calls": [
            'artifact_catalog(action="browse", query="socket monitor", limit=5)',
            'artifact_catalog(action="query", intent="inspect open sockets", category="network")',
        ],
    },
    "crash_forensics": {
        "when_to_use": "Check proactive crash tickets or diagnose recent systemd/coredump failures with compact journal filtering.",
        "canonical_calls": [
            'diagnose_system_crashes(action="alerts")',
            'diagnose_system_crashes(action="diagnose", limit=5, verbosity="summary")',
        ],
    },
    "kernel_observability": {
        "when_to_use": "Run curated read-only eBPF probes (syscall counts, openat denials, execve monitor, Landlock audit) when in FULL tier.",
        "canonical_calls": [
            'kernel_trace(mode="syscall_count", duration_sec=2)',
            'kernel_trace(mode="security_open_denials", duration_sec=2)',
        ],
    },
    "visual_actuation": {
        "when_to_use": "Render a web UI in headless Chromium and capture a RAM screenshot (/dev/shm) with fail-soft fallback.",
        "canonical_calls": [
            'visual_inspect(url="http://localhost:8000", viewport_width=1280, viewport_height=800)',
        ],
    },
    "service_control": {
        "when_to_use": "Check or manage systemd services (user-scope in DIMINISHED, system-scope in FULL).",
        "canonical_calls": [
            'aep_ctl(domain="service", action="status", name="ssh")',
        ],
    },
    "backup_admin": {
        "when_to_use": "Create/restore 5-slot FIFO SQLite backups, ultra-fast RAM micro-snapshots, or inspect anti-poisoning quarantine.",
        "canonical_calls": [
            'aep_ctl(domain="backup", action="micro_snapshot", name="pre_change")',
            'aep_ctl(domain="backup", action="status")',
            'aep_ctl(domain="backup", action="verify_integrity")',
        ],
    },
    "audit_read": {
        "when_to_use": "Verify cryptographic integrity of the SHA-256 chained security audit log.",
        "canonical_calls": [
            'aep_ctl(domain="audit", action="verify")',
        ],
    },
    "task_management": {
        "when_to_use": "Track multi-step engineering state in SQLite (BACKLOG -> SYNTHESIZED -> LINTED -> CANARY -> PROMOTED) outside volatile LLM context.",
        "canonical_calls": [
            'kanban_board(action="board")',
            'kanban_board(action="create", title="feat: x", intent="implement x", category="engine")',
        ],
    },
    "automation": {
        "when_to_use": "Create or run parameterized multi-tool DAG playbooks, or execute single-turn ephemeral batches with in-RAM variable piping ($prev.*, $steps.<id>.*, $cache.<key>.*) and server-side field projection.",
        "canonical_calls": [
            'playbook_run(action="list")',
            'playbook_run(action="run", name="aep-self-diagnostic", return_only="last", select_fields=["status", "valid", "block_count"])',
            'playbook_run(action="batch", steps=[{"id": "s1", "tool": "process_inspect", "params": {"pid": 0}, "store_as": "proc"}], return_only="last", select_fields=["status", "pid", "fd_count"])',
        ],
    },
    "system_docs": {
        "when_to_use": "Retrieve exact CLI flag syntax from local vectorized man-pages without hallucinating options.",
        "canonical_calls": [
            'query_system_docs(query="bubblewrap bind mount read only", ingest_command="bwrap", limit=3)',
        ],
    },
    "default_primitives": {
        "when_to_use": "Execute built-in system introspection and diagnostic probes directly in RAM without template compilation.",
        "canonical_calls": [
            'default_primitives(action="list")',
            'default_primitives(action="info", name="socket-monitor")',
            'default_primitives(action="run", name="disk-usage", params={"path": "/"})',
        ],
    },
}


def check_binary_prerequisites() -> dict[str, dict[str, Any]]:
    """Inspect real host installation status for all binary prerequisites used across AEP."""
    binaries = [
        "bwrap",
        "pueue",
        "pueued",
        "go",
        "golangci-lint",
        "coredumpctl",
        "journalctl",
        "bpftrace",
        "ss",
        "ip",
        "findmnt",
        "lsblk",
        "dpkg-query",
        "systemctl",
        "man",
    ]
    status: dict[str, dict[str, Any]] = {}
    local_bin = Path.home() / ".local" / "bin"
    for b in binaries:
        found = shutil.which(b)
        if not found and (local_bin / b).exists():
            found = str(local_bin / b)
        status[b] = {"installed": bool(found), "path": found}

    # Check Chromium / Playwright availability for visual_inspect
    pw_browsers = (
        list((Path.home() / ".cache" / "ms-playwright").glob("chromium*"))
        if (Path.home() / ".cache" / "ms-playwright").exists()
        else []
    )
    sys_browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    browser_path = sys_browser or (str(pw_browsers[0]) if pw_browsers else None)
    status["chromium_or_playwright"] = {
        "installed": bool(browser_path),
        "path": browser_path,
    }
    return status


def tactical_playbook() -> dict[str, Any]:
    """Systems engineering semantic playbook: taxonomic catalog, canonical 1-liners, workflows, and RoE."""
    prereqs = check_binary_prerequisites()
    return {
        "status": "OK",
        "playbook_version": "EAES-v2-Standard-Telemetry",
        "overview": (
            "Agent Execution Plane (AEP) Tactical Guide. Designed for zero-hallucination, "
            "low-token consumption, and deterministic Linux control. Every tool returns typed JSON "
            "with request telemetry and an agent-brief envelope."
        ),
        "rules_of_engagement": [
            "1. TOKEN EFFICIENCY FIRST: Pass verbosity='summary' (or 'brief') on diagnostic calls (aep_ctl, diagnose_system_crashes, process_inspect) to cut payload size by 70-85%.",
            "2. SCHEMA WITHOUT GUESSING: Call aep_ctl(action='schema') to inspect all control-plane domains and valid actions before invoking aep_ctl.",
            "3. SANDBOX ISOLATION: sandbox_run defaults to share_net=False and hides the host workspace. Pass working_dir='/path/to/repo' or ro_paths=['/path'] to mount authorized directories safely.",
            "4. STATE EXTERNALIZATION: Record multi-step work in kanban_board and validate task dependencies with topos_audit_dag before mutating files.",
            "5. SNAPSHOT BEFORE MUTATION: Call aep_ctl(domain='backup', action='micro_snapshot', name='pre_edit') before risky database or catalog changes.",
            "6. EPHEMERAL PIPELINE BATCHING: Use playbook_run(action='batch', steps=[...], return_only='last', select_fields=[...]) or /dev/shm/aep.sock UNIX socket pool to execute multi-tool chains in a single turn and discard unneeded fields server-side (saving 80-98% tokens).",
            "7. ZERO-TOKEN MULTI-AGENT RAM HANDOFF & CONCURRENCY: Share state across agents in /dev/shm/aep_pool using params={'session_id': 'shared'} + store_as='key' and reference $cache.<key>.<field> (or $slot.<key>.<field>). All 16 tools (Pico-Kanban, Pico-Jenkins Go builds, Pico-Ansible playbooks, SHA-256 audit log, default primitives, and RAM snapshots) are collision-free under concurrent multi-agent execution.",
            "8. MULTI-AGENT RAM CAPABILITY CACHING (GAP-DOC-02): Subagents must call discover(action='capabilities', session_id='<shared-id>', verbosity='terse') to read cached capabilities directly from RAM slot, eliminating redundant 1.2k-1.9k token re-discovery taxes (>95% savings).",
            "9. TACTICAL SANDBOX RECIPES (ONT-30): Use sandbox-linter-fix (rw_paths=[<repo>]) for in-place formatting, untrusted-adversarial-probe (rw_paths=[<scratch>]) for isolated fuzzing, and composite-verification-runner (parse='auto') for unified ruff && pytest in 1 turn.",
            "10. VERIFY LOADED CODE (ONT-39): tras editar o recargar, discover(capabilities, terse) y exigir stale == false y code_fingerprint_loaded == code_fingerprint_disk; si no, el cambio NO está cargado. Cambios multiarchivo: crea .aep_swap_fence, edita, valida, borra el fence y verifica con discover(capabilities, terse).",
        ],
        "workflow_recipes": [
            {
                "id": "WF-1",
                "name": "Code, Contract & Architecture Audit",
                "steps": [
                    '1. discover(action="capabilities") -> Verify tier, binary readiness, and permissions.',
                    '2. aep_ctl(action="schema") -> Inspect unified control-plane contract.',
                    "3. topos_audit_dag(tasks=[...], dependencies={...}) -> Verify zero circular co-dependencies.",
                    '4. aep_ctl(domain="audit", action="verify") -> Verify SHA-256 security ledger integrity.',
                ],
            },
            {
                "id": "WF-2",
                "name": "Safe Sandboxed Repository Verification",
                "steps": [
                    '1. sandbox_run(command="pytest -q", working_dir="/path/to/repo", share_net=False) -> Run tests inside isolated Bubblewrap jail with read-only workspace bind.',
                    '2. async_job_dispatch(action="dispatch", command="ruff check . && pytest -q", working_dir="/path/to/repo") -> Offload long test suites to Pueue background queue.',
                ],
            },
            {
                "id": "WF-3",
                "name": "Low-Token System & Process Triage",
                "steps": [
                    '1. process_inspect(pid=0, limit=15, verbosity="summary") -> Check AEP RSS memory and FD deltas.',
                    '2. aep_ctl(domain="network", action="listeners", verbosity="summary", limit=15) -> List active ports compactly.',
                    '3. diagnose_system_crashes(action="diagnose", limit=5, verbosity="summary") -> Inspect compact systemd errors and coredumps.',
                ],
            },
            {
                "id": "WF-4",
                "name": "Zero-Disk Go Probe Synthesis & RAM Execution",
                "steps": [
                    '1. artifact_lint_and_build(action="select", intent="monitor tcp sockets") -> Rank proven templates.',
                    '2. artifact_lint_and_build(action="build", name="probe_1", intent="monitor tcp", category="network", template_name="socket_monitor") -> Hydrate, vet, and compile static ELF.',
                    '3. artifact_execute_in_ram(name="probe_1") -> Execute via memfd_create in RAM and auto-record canary metrics.',
                ],
            },
            {
                "id": "WF-5",
                "name": "Cloudflare-Style Ephemeral Batch & UNIX Socket Pool",
                "steps": [
                    '1. aep_ctl(domain="ipc", action="status", verbosity="summary") -> Check /dev/shm/aep.sock listener and active pool slots.',
                    '2. playbook_run(action="batch", steps=[{"id":"s1","tool":"process_inspect","params":{"pid":0}}, {"id":"s2","tool":"topos_audit_dag","params":{"tasks":["t1"],"dependencies":{}}}], return_only="last", select_fields=["status","verdict"]) -> Execute multi-step DAG in 1 turn with server-side field projection.',
                ],
            },
            {
                "id": "WF-6",
                "name": "Zero-Token Multi-Agent RAM Handoff & Collision-Free Pico-Triad",
                "steps": [
                    '1. Agent A (pragma): playbook_run(action="batch", params={"session_id":"team-1"}, agent_id="pragma", steps=[{"id":"b1","tool":"artifact_lint_and_build","params":{"action":"build","template_name":"mem-stat"},"store_as":"build_out"}]) -> Builds Go ELF in isolated /dev/shm slot and caches output.',
                    '2. Agent B (dokimos): playbook_run(action="batch", params={"session_id":"team-1"}, agent_id="dokimos", steps=[{"id":"c1","tool":"artifact_execute_in_ram","params":{"name":"$cache.build_out.name"}}, {"id":"c2","tool":"kanban_board","params":{"action":"promote","task_id":"$cache.build_out.kanban_task_id"}}], return_only="last", select_fields=["status","verdict"]) -> Reads Agent A state from /dev/shm RAM and promotes artifact in 1 turn.',
                ],
            },
            {
                "id": "WF-7",
                "name": "In-Place Linter Auto-Fix with Read-Write Sandbox (sandbox-linter-fix)",
                "steps": [
                    '1. sandbox_run(command="ruff format . && ruff check --fix .", working_dir="/path/to/repo", rw_paths=["/path/to/repo"], share_net=False, parse="auto", verbosity="summary") -> Formats and auto-fixes repo in place while isolating network and sensitive host directories.',
                ],
            },
            {
                "id": "WF-8",
                "name": "Untrusted Adversarial Probe & Isolated Fuzzing (untrusted-adversarial-probe)",
                "steps": [
                    '1. sandbox_run(command="python3 fuzzer.py", working_dir="/path/to/repo", ro_paths=["/path/to/repo"], rw_paths=["/path/to/scratch"], share_net=False, verbosity="summary") -> Executes adversarial or untrusted probes with read-only source repo, scratch-only write capability, and disabled network.',
                ],
            },
            {
                "id": "WF-9",
                "name": "Composite Single-Turn Linter & Test Verification (composite-verification-runner)",
                "steps": [
                    '1. sandbox_run(command="ruff check . && pytest -q", working_dir="/path/to/repo", share_net=False, parse="auto", verbosity="brief") -> Executes chained linter and test runner in a single turn, emitting composite parsed metrics (ruff violations + pytest counts/failures) without token bloat.',
                ],
            },
            {
                "id": "WF-10",
                "name": "Native Network Telemetry & Port Observability (aep_ctl network probe -> /proc/net/tcp socket inspection)",
                "steps": [
                    '1. aep_ctl(domain="network", action="probe", name="127.0.0.1", args="22,80,443") -> Pure in-RAM TCP port probe via asyncio/socket.',
                    '2. aep_ctl(domain="network", action="listeners", verbosity="summary") -> Direct in-memory /proc/net/tcp socket table inspection.',
                    '3. aep_ctl(domain="network", action="interfaces", verbosity="summary") -> Kernel /proc/net/dev traffic metrics.',
                ],
            },
            {
                "id": "WF-11",
                "name": "Security Observability & Netfilter Hardening (kernel_trace network sniff -> aep_ctl security nftables inspect -> idempotent threat mitigation)",
                "steps": [
                    '1. kernel_trace(mode="network_sniff", duration_sec=2) -> In-memory packet ingestion and header dissection.',
                    '2. aep_ctl(domain="security", action="nftables_inspect", verbosity="summary") -> Inspect active netfilter rule chains.',
                    '3. aep_ctl(domain="security", action="threat_mitigate", name="<target-ip>") -> Enforce deterministic netfilter hardening at host perimeter.',
                ],
            },
        ],
        "quick_reference": {
            "orient_and_readiness": 'discover(action="capabilities", verbosity="summary")',
            "tactical_guide": 'discover(action="playbook", verbosity="summary")',
            "control_plane_schema": 'aep_ctl(action="schema")',
            "compact_listeners": 'aep_ctl(domain="network", action="listeners", verbosity="summary")',
            "compact_mounts": 'aep_ctl(domain="storage", action="mounts", verbosity="summary")',
            "sandbox_repo_test": 'sandbox_run(command="pytest -q", working_dir="/path/to/repo", verbosity="summary")',
            "ram_micro_snapshot": 'aep_ctl(domain="backup", action="micro_snapshot", name="snap1")',
            "audit_ledger_verify": 'aep_ctl(domain="audit", action="verify", verbosity="summary")',
            "ipc_socket_status": 'aep_ctl(domain="ipc", action="status", verbosity="summary")',
            "ipc_shared_cache": 'aep_ctl(domain="ipc", action="cache", name="team-1")',
            "ephemeral_batch": 'playbook_run(action="batch", steps=[...], return_only="last", select_fields=["status"])',
            "terse_cached_capabilities": 'discover(action="capabilities", session_id="team-1", verbosity="terse")',
            "sandbox_linter_fix": 'sandbox_run(command="ruff check --fix .", working_dir="/path/to/repo", rw_paths=["/path/to/repo"], share_net=False, parse="auto", verbosity="summary")',
            "untrusted_adversarial_probe": 'sandbox_run(command="python3 probe.py", working_dir="/path/to/repo", rw_paths=["/path/to/scratch"], share_net=False, verbosity="summary")',
            "composite_verification": 'sandbox_run(command="ruff check . && pytest -q", working_dir="/path/to/repo", parse="auto", verbosity="brief")',
            "network_telemetry_probe": 'aep_ctl(domain="network", action="probe", name="127.0.0.1", args="22,80,443", verbosity="summary")',
            "incident_protocol_audit": 'aep_ctl(domain="security", action="nftables_inspect", verbosity="summary")',
            "default_primitives_run": 'default_primitives(action="run", name="disk-usage", verbosity="summary")',
            "default_primitives_list": 'default_primitives(action="list", verbosity="summary")',
        },
        "prerequisites_summary": {k: v["installed"] for k, v in prereqs.items()},
    }


def capability_manifest() -> dict:
    """Manifiesto de autonomía en primera vista para la IA que consume el MCP."""
    eff_tier_info = get_effective_chmod_tier()
    tier = capability_tier()
    idx = 1 if tier == "FULL" else 0
    prereqs = check_binary_prerequisites()
    caps = {}
    for name, (dim, full, scope, tools, desc) in _CAPABILITIES.items():
        bits = (dim, full)[idx]
        req_bins = _CAP_BINARIES.get(name, [])
        missing_bins = [b for b in req_bins if not prereqs.get(b, {}).get("installed", False)]
        tactical = _CAP_TACTICAL.get(name, {})
        is_ready = (bits > 0) and (len(missing_bins) == 0)
        mode = None
        if name == "crash_forensics":
            has_coredumpctl = prereqs.get("coredumpctl", {}).get("installed", False)
            has_var_crash = Path("/var/crash").is_dir()
            if has_coredumpctl:
                is_ready = (bits > 0) and ("journalctl" not in missing_bins)
                mode = "coredumpctl"
            elif has_var_crash:
                is_ready = bits > 0
                mode = "apport_fallback"
            else:
                is_ready = False
                mode = "none"

        cap_dict: dict[str, Any] = {
            "perm": f"{bits}{_PERM_TABLE[bits]}",  # p.ej. "4r--", "7rwx"
            "octal_now": bits,
            "octal_diminished": dim,
            "octal_full": full,
            "unlocks_with_full": full > dim,
            "ready": is_ready,
            "required_binaries": req_bins,
            "missing_binaries": missing_bins,
            "scope": scope if bits else "none",
            "tools": tools,
            "description": desc,
            "when_to_use": tactical.get("when_to_use", desc),
            "canonical_calls": tactical.get("canonical_calls", []),
            "keywords": _CAP_KEYWORDS.get(name, ""),
        }
        if mode is not None:
            cap_dict["mode"] = mode
        caps[name] = cap_dict
    return {
        "what_is_this": "AEP MCP: plano de ejecución para GESTIONAR LA AUTONOMÍA de agentes de IA. "
        "Gobernanza y ejecución determinista de telemetría de sistemas y observabilidad de seguridad (RAM exec, sandbox, eBPF, "
        "introspección) en capacidades agénticas gobernadas por privilegio.",
        "capability_tier": tier,
        "effective_chmod_tier": eff_tier_info["tier"],
        "chmod_octal": eff_tier_info["octal"],
        "privilege_mode": privilege_mode(),
        "degradation_matrix": CHMOD_DEGRADATION_MATRIX,
        "prerequisites": prereqs,
        "control_plane_domains": list(CONTROL_PLANE_SCHEMA.keys()),
        "tactical_hint": "Call discover(action='playbook') for systems engineering workflow recipes, canonical 1-liners, and token-saving Rules of Engagement.",
        "legend": {
            "r (4)": "SENSAR — leer estado/telemetría",
            "w (2)": "ACTUAR — mutar estado del sistema",
            "x (1)": "EJECUTAR — caminos no-tradicionales (RAM/kernel/escalada)",
            "octal_reference": _PERM_TABLE,
            "note": "Como chmod: cada capacidad es una tríada rwx. El nivel FULL ensancha "
            "la apertura (self -> system -> kernel); la autonomía base ya opera en DIMINISHED.",
        },
        "capabilities": caps,
    }


class PermissionDenied(Exception):
    """Excepción lanzada cuando una acción es bloqueada por CapabilityGuard."""

    def __init__(
        self,
        message: str,
        capability: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.capability = capability
        self.agent_id = agent_id
        self.action = action


class CapabilityGuard:
    """Motor de control de acceso basado en capacidades (CBAC)."""

    SYSTEM_MUTATION_ACTIONS: set[str] = {"system_service_mutate", "kernel_trace_start", "audit_purge"}

    PATH_BLACKLIST: tuple[str, ...] = (
        "/etc/shadow",
        "/etc/gshadow",
        "/etc/sudoers",
        "/etc/security",
        "/root",
        "/proc/kcore",
        "/dev/mem",
        "/dev/kmem",
    )

    @classmethod
    def is_path_blacklisted(cls, path_str: str) -> bool:
        """Comprueba si una ruta coincide con o está dentro de rutas restringidas."""
        try:
            p = Path(path_str).expanduser().resolve()
            resolved_str = str(p)
            ssh_dir = str(Path.home() / ".ssh")
            gnupg_dir = str(Path.home() / ".gnupg")
            if resolved_str == ssh_dir or resolved_str.startswith(ssh_dir + "/"):
                return True
            if resolved_str == gnupg_dir or resolved_str.startswith(gnupg_dir + "/"):
                return True
            for b in cls.PATH_BLACKLIST:
                if resolved_str == b or resolved_str.startswith(b + "/"):
                    return True
        except OSError, ValueError:
            return False
        return False

    @classmethod
    def verify_action(
        cls,
        agent_id: str,
        capability: str,
        action: str,
        target: str | None = None,
    ) -> None:
        """
        Lanza PermissionDenied si la acción solicitada viola las políticas de capacidad.
        """
        tier = capability_tier()
        norm_cap = capability.lower().removeprefix("cap_")

        # 1. Validación de blacklist de rutas
        if target and cls.is_path_blacklisted(target):
            raise PermissionDenied(
                f"Acceso denegado a ruta restringida '{target}' bajo capacidad '{capability}'.",
                capability=capability,
                agent_id=agent_id,
                action=action,
            )

        # 2. DIMINISHED vs FULL: acciones restringidas a nivel de sistema
        if tier == "DIMINISHED":
            if action in cls.SYSTEM_MUTATION_ACTIONS or norm_cap == "kernel_observability":
                raise PermissionDenied(
                    f"Agente '{agent_id}' en tier DIMINISHED no tiene autorización para '{action}' en '{capability}'. Requiere nivel FULL.",
                    capability=capability,
                    agent_id=agent_id,
                    action=action,
                )

    @classmethod
    def check_action(
        cls,
        agent_id: str,
        capability: str,
        action: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        """Evaluación fail-soft de autorización que devuelve diccionario estructurado."""
        try:
            cls.verify_action(agent_id, capability, action, target)
            return {"status": "ALLOWED", "allowed": True, "agent_id": agent_id, "capability": capability}
        except PermissionDenied as e:
            return {
                "status": "PERMISSION_DENIED",
                "allowed": False,
                "error": e.message,
                "agent_id": agent_id,
                "capability": capability,
                "action": action,
            }

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="AEP Predictive Privilege Prober & Chmod Degradation Matrix"
    )
    parser.add_argument(
        "--tier",
        action="store_true",
        help="Output strictly the detected chmod octal string (7rwx, 6rw-, 5r-x, 4r--)",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Output the full Chmod Graceful Degradation Matrix",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output formatted JSON",
    )
    args = parser.parse_args()

    eff = get_effective_chmod_tier()
    if args.tier:
        print(eff["tier"])
    elif args.matrix:
        print(json.dumps(CHMOD_DEGRADATION_MATRIX, indent=2))
    else:
        print(json.dumps(eff, indent=2))
