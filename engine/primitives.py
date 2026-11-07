"""
Engine: primitives.py — Built-in Diagnostic & Introspection Primitives Runtime.

Pure in-memory, instant execution of foundational diagnostic probes:
  - socket-monitor (via engine.net_telemetry)
  - fd-rescuer (via /proc/PID/fd inspection)
  - disk-usage (via shutil.disk_usage & os.statvfs)
  - mem-stat (via /proc/meminfo parsing)
  - landlock-guard (via engine.landlock)

Decoupled from template compilation and artifact synthesis lifecycle (Milestone ONT-34).
Governed under 4-tier Unix chmod octal privilege matrix (7rwx, 6rw-, 5r-x, 4r--).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from engine.landlock import get_landlock_status
from engine.net_telemetry import parse_proc_net_sockets

logger = logging.getLogger("aep.primitives")

DEFAULT_PRIMITIVES_REGISTRY: dict[str, dict[str, Any]] = {
    "socket-monitor": {
        "name": "socket-monitor",
        "category": "network",
        "capability": "system_inspect",
        "tags": ["sockets", "tcp", "udp", "ports", "listen", "netstat", "connections", "network"],
        "description": "Lista sockets TCP/UDP del host (LISTEN y ESTABLISHED) leyendo el kernel sin invocar netstat; salida JSON tipada.",
        "params": {
            "state": {
                "type": "string",
                "required": False,
                "default": "",
                "description": "Filtrar por estado TCP (LISTEN, ESTABLISHED, etc.) o vacío para todos",
            }
        },
        "required_tier": "5r-x",
    },
    "fd-rescuer": {
        "name": "fd-rescuer",
        "category": "process",
        "capability": "process_introspection",
        "tags": ["file", "descriptors", "fd", "proc", "process", "hung", "deadlock", "leak"],
        "description": "Inspecciona /proc/PID/fd de un proceso para diagnosticar hilos colgados, deadlocks o fugas de descriptores.",
        "params": {
            "pid": {
                "type": "int",
                "required": False,
                "default": 0,
                "description": "PID a inspeccionar (0 = auto-inspección del proceso AEP)",
            }
        },
        "required_tier": "5r-x",
    },
    "disk-usage": {
        "name": "disk-usage",
        "category": "filesystem",
        "capability": "system_inspect",
        "tags": ["disk", "storage", "statfs", "free", "used", "space", "filesystem", "capacity", "mount"],
        "description": "Uso de disco del sistema de archivos vía shutil.disk_usage y statvfs: total, libre y usado en bytes.",
        "params": {
            "path": {
                "type": "string",
                "required": False,
                "default": "/",
                "description": "Ruta de directorio o punto de montaje a consultar",
            }
        },
        "required_tier": "4r--",
    },
    "mem-stat": {
        "name": "mem-stat",
        "category": "memory",
        "capability": "system_inspect",
        "tags": ["memory", "ram", "meminfo", "free", "available", "total", "swap", "usage"],
        "description": "Uso de memoria: lee /proc/meminfo y reporta RAM total, libre y disponible en bytes.",
        "params": {},
        "required_tier": "4r--",
    },
    "landlock-guard": {
        "name": "landlock-guard",
        "category": "security",
        "capability": "security_sandbox",
        "tags": ["landlock", "sandbox", "lsm", "security", "isolation", "kernel", "filesystem", "probe"],
        "description": "Sonda en memoria para auditar soporte y confinamiento de Landlock LSM (Kernel 5.13+) vía syscalls puras.",
        "params": {},
        "required_tier": "5r-x",
    },
}


def normalize_primitive_name(name: str) -> str:
    """Normalize primitive name: lower-case, replace '_' with '-'."""
    return name.strip().lower().replace("_", "-")


def _run_socket_monitor(params: dict[str, Any]) -> dict[str, Any]:
    state_filter = str(params.get("state") or "").strip().upper()
    sockets = parse_proc_net_sockets(protocol="all")
    if state_filter:
        sockets = [s for s in sockets if str(s.get("state", "")).upper() == state_filter]
    return {
        "primitive": "socket-monitor",
        "count": len(sockets),
        "filter_state": state_filter or "ALL",
        "sockets": sockets,
    }


def _run_fd_rescuer(params: dict[str, Any]) -> dict[str, Any]:
    pid_param = params.get("pid")
    try:
        pid = int(pid_param) if pid_param is not None else 0
    except ValueError, TypeError:
        pid = 0
    effective_pid = os.getpid() if pid <= 0 else pid

    fd_dir = Path(f"/proc/{effective_pid}/fd")
    fds: list[dict[str, Any]] = []
    if fd_dir.exists():
        try:
            for entry in sorted(os.listdir(fd_dir), key=lambda x: int(x) if x.isdigit() else 999999):
                link_path = fd_dir / entry
                try:
                    target = os.readlink(link_path)
                    fds.append({"fd": int(entry) if entry.isdigit() else entry, "target": target})
                except OSError, PermissionError:
                    fds.append({"fd": int(entry) if entry.isdigit() else entry, "target": "<unreadable>"})
        except (OSError, PermissionError) as e:
            logger.debug("Failed listing /proc/%d/fd: %s", effective_pid, e)

    return {
        "primitive": "fd-rescuer",
        "pid": effective_pid,
        "fd_count": len(fds),
        "descriptors": fds,
    }


def _run_disk_usage(params: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(params.get("path") or "/").strip()
    target_path = Path(raw_path or "/")
    effective_path = str(target_path) if target_path.exists() else "/"

    usage = shutil.disk_usage(effective_path)
    percent_used = round((usage.used / usage.total) * 100.0, 2) if usage.total > 0 else 0.0

    st_vfs = os.statvfs(effective_path)
    return {
        "primitive": "disk-usage",
        "path": effective_path,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "percent_used": percent_used,
        "block_size": st_vfs.f_frsize,
        "total_blocks": st_vfs.f_blocks,
        "free_blocks": st_vfs.f_bavail,
    }


def _run_mem_stat(params: dict[str, Any]) -> dict[str, Any]:
    meminfo_path = Path("/proc/meminfo")
    info: dict[str, int] = {}
    if meminfo_path.exists():
        try:
            content = meminfo_path.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                if ":" in line:
                    key, rest = line.split(":", 1)
                    parts = rest.strip().split()
                    if parts and parts[0].isdigit():
                        val_kb = int(parts[0])
                        info[key.strip()] = val_kb * 1024
        except OSError as e:
            logger.debug("Failed reading /proc/meminfo: %s", e)

    total = info.get("MemTotal", 0)
    free = info.get("MemFree", 0)
    available = info.get("MemAvailable", free)
    used = max(0, total - available) if total > 0 else 0
    percent_used = round((used / total) * 100.0, 2) if total > 0 else 0.0

    return {
        "primitive": "mem-stat",
        "total_bytes": total,
        "free_bytes": free,
        "available_bytes": available,
        "used_bytes": used,
        "percent_used": percent_used,
        "swap_total_bytes": info.get("SwapTotal", 0),
        "swap_free_bytes": info.get("SwapFree", 0),
    }


def _run_landlock_guard(params: dict[str, Any]) -> dict[str, Any]:
    ll_status = get_landlock_status()
    return {
        "primitive": "landlock-guard",
        **ll_status,
    }


_RUNNERS = {
    "socket-monitor": _run_socket_monitor,
    "fd-rescuer": _run_fd_rescuer,
    "disk-usage": _run_disk_usage,
    "mem-stat": _run_mem_stat,
    "landlock-guard": _run_landlock_guard,
}


def list_primitives() -> list[dict[str, Any]]:
    """List all registered default primitives and their descriptors."""
    return list(DEFAULT_PRIMITIVES_REGISTRY.values())


def get_primitive_info(name: str) -> dict[str, Any] | None:
    """Get metadata for a specific primitive by name or alias."""
    norm = normalize_primitive_name(name)
    return DEFAULT_PRIMITIVES_REGISTRY.get(norm)


def execute_primitive(
    name: str,
    params: dict[str, Any] | None = None,
    tier: str = "6rw-",
) -> dict[str, Any]:
    """
    Execute a default primitive in-RAM under chmod privilege governance.

    In 4r-- (auditor mode), execution is disabled fail-soft: returns status: PERMISSION_DENIED.
    """
    norm = normalize_primitive_name(name)
    if norm not in DEFAULT_PRIMITIVES_REGISTRY:
        return {
            "status": "ERROR",
            "chmod_tier": tier,
            "primitive": norm,
            "error": f"Unknown primitive '{name}'. Available: {list(DEFAULT_PRIMITIVES_REGISTRY.keys())}",
        }

    # 4-tier degradation enforcement: 4r-- denies execution
    if tier == "4r--":
        return {
            "status": "PERMISSION_DENIED",
            "chmod_tier": tier,
            "primitive": norm,
            "summary": f"Execution of primitive '{norm}' is disabled in 4r-- (auditor mode).",
        }

    runner = _RUNNERS.get(norm)
    if not runner:
        return {
            "status": "ERROR",
            "chmod_tier": tier,
            "primitive": norm,
            "error": f"No runner registered for primitive '{norm}'",
        }

    effective_params = params or {}
    try:
        data = runner(effective_params)
        return {
            "status": "OK",
            "chmod_tier": tier,
            "primitive": norm,
            "result": data,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("Error executing primitive %s: %s", norm, e)
        return {
            "status": "ERROR",
            "chmod_tier": tier,
            "primitive": norm,
            "error": str(e),
        }
