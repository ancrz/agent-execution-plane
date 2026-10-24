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

import os
import shutil
import subprocess
from typing import List, Optional

_SUDO_N_CACHE: Optional[bool] = None


def sudo_n_available() -> bool:
    """¿Hay sudo sin contraseña (escalada no-interactiva)? Resultado cacheado por proceso."""
    global _SUDO_N_CACHE
    if _SUDO_N_CACHE is None:
        try:
            _SUDO_N_CACHE = bool(shutil.which("sudo")) and subprocess.run(
                ["sudo", "-n", "true"], capture_output=True, timeout=5
            ).returncode == 0
        except Exception:
            _SUDO_N_CACHE = False
    return _SUDO_N_CACHE


def privilege_prefix() -> Optional[List[str]]:
    """[] si ya es root; ['sudo','-n'] si se puede escalar; None si no hay vía (DIMINISHED)."""
    if os.geteuid() == 0:
        return []
    return ["sudo", "-n"] if sudo_n_available() else None


def privilege_mode() -> str:
    """Etiqueta del modo efectivo: direct-root | sudo-n | unprivileged."""
    if os.geteuid() == 0:
        return "direct-root"
    return "sudo-n" if sudo_n_available() else "unprivileged"


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
    "ram_execution":        (5, 5, "self",   ["artifact_execute_in_ram"], "Inyectar y correr ELF en RAM (memfd_create)"),
    "ephemeral_sandbox":    (5, 5, "self",   ["sandbox_run"],             "Ejecutar aislado en sandbox bwrap"),
    "artifact_synthesis":   (7, 7, "self",   ["template_catalog", "template_select", "artifact_hydrate", "artifact_lint_and_build"], "Elegir plantilla (selector), sintetizar, lintar, compilar y persistir artefactos Go"),
    "orientation":          (4, 4, "self",   ["discover", "aep_capabilities"], "Traducir un caso de uso -> qué reutilizar/sintetizar/automatizar (enrutador discover)"),
    "semantic_memory":      (6, 6, "self",   ["artifact_catalog"], "Leer/escribir, DESCUBRIR, AUTO-INDEXAR y PODAR (GC seguro) la memoria semántica (sqlite-vec)"),
    "async_dispatch":       (7, 7, "self",   ["async_job_dispatch", "async_job_inspect"], "Despachar/inspeccionar tareas asíncronas (Pueue)"),
    "process_introspection":(4, 4, "system", ["artifact_execute_in_ram"], "Introspección de descriptores de procesos (/proc/PID/fd)"),
    "system_inspect":       (4, 4, "system", ["aep_ctl"],                 "Leer red, almacenamiento y paquetes (aep-ctl)"),
    "service_control":      (4, 6, "system", ["aep_ctl"],                 "Controlar servicios: DIMINISHED solo scope-usuario; FULL muta sistema"),
    "crash_forensics":      (4, 4, "system", ["diagnose_system_crashes", "check_crash_alerts"], "Forense de crashes: DIMINISHED propios; FULL todo el sistema"),
    "kernel_observability": (0, 4, "kernel", ["kernel_trace"],            "Telemetría de kernel eBPF: requiere FULL (CAP_BPF)"),
    "visual_actuation":     (5, 5, "self",   ["visual_inspect"],          "Renderizar y capturar UIs headless (/dev/shm)"),
    "topos_audit":          (4, 4, "self",   ["topos_audit_dag"],         "Auditar DAGs y bloquear co-dependencias"),
    "task_management":      (6, 6, "self",   ["kanban_board", "kanban_task_create", "kanban_advance", "kanban_promote", "kanban_demote", "kanban_reevaluate", "kanban_archive", "kanban_unarchive"], "Pico-Kanban: tareas atómicas + ponderación con promoción/degradación y archivado reversible"),
    "automation":           (7, 7, "self",   ["playbook_create", "playbook_run", "playbook_list", "playbook_prune"], "Pico-Playbooks: orquestar tools/artefactos en flujos DAG (E2E, verificación) y poda segura (playbook_prune)"),
    "system_docs":          (4, 4, "self",   ["query_system_docs"], "Memoria semántica local de man-pages (sqlite-vec): sintaxis exacta sin alucinar flags"),
}

_PERM_TABLE = {7: "rwx", 6: "rw-", 5: "r-x", 4: "r--", 3: "-wx", 2: "-w-", 1: "--x", 0: "---"}

# Keywords BILINGÜES (EN/ES) por capacidad: anclas léxicas language-aligned para el enrutador
# `discover`. Las descriptions están en español y los names/tools en inglés, así que una query EN
# ("run binary", "memory", "trace kernel") tenía poco con qué casar. Esto cierra la colisión ES/EN:
# el matcher las pondera como tags (x2) sumadas a los nombres de tools. Ampliar aquí es barato.
_CAP_KEYWORDS = {
    "ram_execution":        "run binary memfd fileless in-memory ejecutar binario memoria elf payload",
    "ephemeral_sandbox":    "sandbox isolate bwrap jail contained run aislar aislado seguro",
    "artifact_synthesis":   "synthesize generate build template compile go artifact create sintetizar plantilla compilar generar crear",
    "orientation":          "discover orient what to do route start where begin orientar descubrir enrutar empezar",
    "semantic_memory":      "memory search recall catalog query reindex prune index vector embeddings reuse find store memoria buscar recordar catalogo consultar indice podar sanar reutilizar guardar",
    "async_dispatch":       "async background job queue dispatch task pueue asincrono trabajo cola despachar tarea segundo plano",
    "process_introspection":"process inspect fd descriptor proc pid introspection proceso descriptor introspeccion",
    "system_inspect":       "network storage packages inspect read system status red almacenamiento paquetes inspeccionar sistema estado",
    "service_control":      "service control start stop restart systemd daemon servicio controlar arrancar detener reiniciar",
    "crash_forensics":      "crash core dump forensic coredump diagnose fault crasheo volcado forense diagnosticar fallo",
    "kernel_observability": "kernel trace ebpf bpf syscall observe probe kernel trazar sondear llamadas sistema",
    "visual_actuation":     "visual screenshot render headless ui browser page visual captura renderizar pantalla navegador",
    "topos_audit":          "audit dag graph dependency cycle codependency auditar grafo dependencia ciclo",
    "task_management":      "task kanban board manage promote weigh track tarea tablero gestionar promover ponderar seguir",
    "automation":           "automate playbook orchestrate workflow pipeline e2e steps prune gc clean podar limpiar automatizar orquestar flujo pasos",
    "system_docs":          "man manpage documentation syntax flags command help manual documentacion sintaxis comando manual",
}


def capability_manifest() -> dict:
    """Manifiesto de autonomía en primera vista para la IA que consume el MCP."""
    tier = capability_tier()
    idx = 1 if tier == "FULL" else 0
    caps = {}
    for name, (dim, full, scope, tools, desc) in _CAPABILITIES.items():
        bits = (dim, full)[idx]
        caps[name] = {
            "perm": f"{bits}{_PERM_TABLE[bits]}",      # p.ej. "4r--", "7rwx"
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
