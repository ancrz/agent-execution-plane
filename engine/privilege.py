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


class _PrivilegeCache:
    sudo_n: bool | None = None


def sudo_n_available() -> bool:
    """¿Hay sudo sin contraseña (escalada no-interactiva)? Resultado cacheado por proceso."""
    if _PrivilegeCache.sudo_n is None:
        try:
            _PrivilegeCache.sudo_n = (
                bool(shutil.which("sudo"))
                and subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5, check=False).returncode == 0
            )
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("sudo -n check failed: %s", e)
            _PrivilegeCache.sudo_n = False
    return _PrivilegeCache.sudo_n


def privilege_prefix() -> list[str] | None:
    """[] si ya es root; ['sudo','-n'] si se puede escalar; None si no hay vía (DIMINISHED)."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"] if sudo_n_available() else None


def privilege_mode() -> str:
    """Etiqueta del modo efectivo: direct-root | sudo-n | unprivileged."""
    if os.geteuid() == 0:
        return "direct-root"
    return "sudo-n" if sudo_n_available() else "unprivileged"



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
    """FULL si hay root o escalada disponible; DIMINISHED en caso contrario."""
    return "FULL" if privilege_prefix() is not None else "DIMINISHED"


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
    "backup_admin": (4, 6, "system", ["aep_ctl"], "Gestión de copias de seguridad y rotación de backups (aep-ctl backup)"),
    "audit_read": (4, 4, "self", ["aep_ctl"], "Inspección y verificación de la cadena de auditoría criptográfica"),
    "system_docs": (
        4,
        4,
        "self",
        ["query_system_docs"],
        "Memoria semántica local de man-pages (sqlite-vec): sintaxis exacta sin alucinar flags",
    ),
}

_PERM_TABLE = {7: "rwx", 6: "rw-", 5: "r-x", 4: "r--", 3: "-wx", 2: "-w-", 1: "--x", 0: "---"}

# Keywords BILINGÜES (EN/ES) por capacidad: anclas léxicas language-aligned para el enrutador
# `discover`. Las descriptions están en español y los names/tools en inglés, así que una query EN
# ("run binary", "memory", "trace kernel") tenía poco con qué casar. Esto cierra la colisión ES/EN:
# el matcher las pondera como tags (x2) sumadas a los nombres de tools. Ampliar aquí es barato.
_CAP_KEYWORDS = {
    "ram_execution": "run binary memfd fileless in-memory ejecutar binario memoria elf payload",
    "ephemeral_sandbox": "sandbox isolate bwrap jail contained run aislar aislado seguro",
    "artifact_synthesis": "synthesize template catalog select hydrate lint build compile go binary cue generate create sintetizar plantilla catalogo seleccionar hidratar compilar construir binario generar crear",
    "orientation": "discover orient what to do route start where begin capabilities manifest status chmod permisos autonomy autonomia orientar descubrir enrutar empezar",
    "semantic_memory": "memory search recall catalog query reindex prune index vector embeddings reuse find store memoria buscar recordar catalogo consultar indice podar sanar reutilizar guardar",
    "async_dispatch": "async background queue long job pueue dispatch inspect status log cola asincrono tarea larga despachar inspeccionar estado segundo plano",
    "process_introspection": "process inspect fd descriptor proc pid introspection open files socket pipes leak proceso descriptor introspeccion archivos abiertos fugas",
    "system_inspect": "network storage packages inspect read system status red almacenamiento paquetes inspeccionar sistema estado",
    "service_control": "service control start stop restart systemd daemon servicio controlar arrancar detener reiniciar",
    "crash_forensics": "crash core dump forensic coredump diagnose fault alerts router ticket new proactive crasheo volcado forense diagnosticar fallo alertas enrutador ticket nuevo proactivo",
    "kernel_observability": "kernel trace ebpf bpf syscall observe probe kernel trazar sondear llamadas sistema",
    "visual_actuation": "visual screenshot render headless ui browser page visual captura renderizar pantalla navegador",
    "topos_audit": "audit dag graph dependency cycle codependency auditar grafo dependencia ciclo",
    "task_management": "task kanban board create advance promote demote reevaluate archive unarchive manage weigh track tarea tablero crear avanzar promover degradar reevaluar archivar desarchivar gestionar ponderar seguir",
    "automation": "automate playbook run create list prune workflow chain pipeline steps gc clean automatizar ejecutar crear listar podar orquestar flujo secuencia pasos limpiar",
    "backup_admin": "backup restore recover rotation hot snapshot copia seguridad restaurar",
    "audit_read": "audit log security chain cryptographic verificar auditoria cadena",
    "system_docs": "man manpage documentation syntax flags command help manual documentacion sintaxis comando manual",
}


def capability_manifest() -> dict:
    """Manifiesto de autonomía en primera vista para la IA que consume el MCP."""
    tier = capability_tier()
    idx = 1 if tier == "FULL" else 0
    caps = {}
    for name, (dim, full, scope, tools, desc) in _CAPABILITIES.items():
        bits = (dim, full)[idx]
        caps[name] = {
            "perm": f"{bits}{_PERM_TABLE[bits]}",  # p.ej. "4r--", "7rwx"
            "octal_now": bits,
            "octal_diminished": dim,
            "octal_full": full,
            "unlocks_with_full": full > dim,
            "scope": scope if bits else "none",
            "tools": tools,
            "description": desc,
            "keywords": _CAP_KEYWORDS.get(name, ""),
        }
    return {
        "what_is_this": "AEP MCP: plano de ejecución para GESTIONAR LA AUTONOMÍA de agentes de IA. "
        "Transmuta primitivas de herramientas ofensivas (RAM exec, sandbox, eBPF, "
        "introspección) en capacidades agénticas gobernadas por privilegio.",
        "capability_tier": tier,
        "privilege_mode": privilege_mode(),
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
        except (OSError, ValueError):
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
