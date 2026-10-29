"""
Engine: landlock.py — Linux Landlock LSM In-Process Filesystem Sandboxing Engine.

Proporciona aislamiento de sistema de archivos sin privilegios de root directamente
en el proceso o subprocesos hijos utilizando la interfaz de llamadas al sistema
de Linux Landlock LSM (Kernel 5.13+):
  - SYS_landlock_create_ruleset (444)
  - SYS_landlock_add_rule (445)
  - SYS_landlock_restrict_self (446)
  - prctl PR_SET_NO_NEW_PRIVS (38)

Topos Invariant: Hoja pura sin dependencias de otros módulos del engine (DIR-ONT-07).
Fail-soft: Detecta soporte de kernel y degrada limpiamente si Landlock no está activo (DIR-ONT-01).
"""

import ctypes
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.landlock")

# Constantes de Syscalls Linux x86_64
SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
PR_SET_NO_NEW_PRIVS = 38

# Banderas de Landlock
LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
LANDLOCK_RULE_PATH_BENEATH = 1

# Máscaras de permisos de sistema de archivos (ABI v1)
ACCESS_FS_EXECUTE = 1 << 0
ACCESS_FS_WRITE_FILE = 1 << 1
ACCESS_FS_READ_FILE = 1 << 2
ACCESS_FS_READ_DIR = 1 << 3
ACCESS_FS_REMOVE_DIR = 1 << 4
ACCESS_FS_REMOVE_FILE = 1 << 5
ACCESS_FS_MAKE_CHAR = 1 << 6
ACCESS_FS_MAKE_DIR = 1 << 7
ACCESS_FS_MAKE_REG = 1 << 8
ACCESS_FS_MAKE_SOCK = 1 << 9
ACCESS_FS_MAKE_FIFO = 1 << 10
ACCESS_FS_MAKE_BLOCK = 1 << 11
ACCESS_FS_MAKE_SYM = 1 << 12

# Máscaras ampliadas (ABI v2 / v3)
ACCESS_FS_REFER = 1 << 13
ACCESS_FS_TRUNCATE = 1 << 14

# Máscaras agrupadas
READ_ACCESS_MASK = ACCESS_FS_EXECUTE | ACCESS_FS_READ_FILE | ACCESS_FS_READ_DIR
WRITE_ACCESS_MASK = (
    ACCESS_FS_WRITE_FILE
    | ACCESS_FS_REMOVE_DIR
    | ACCESS_FS_REMOVE_FILE
    | ACCESS_FS_MAKE_CHAR
    | ACCESS_FS_MAKE_DIR
    | ACCESS_FS_MAKE_REG
    | ACCESS_FS_MAKE_SOCK
    | ACCESS_FS_MAKE_FIFO
    | ACCESS_FS_MAKE_BLOCK
    | ACCESS_FS_MAKE_SYM
    | ACCESS_FS_TRUNCATE
)
FULL_FS_ACCESS_V1 = (1 << 13) - 1
FULL_FS_ACCESS_V3 = (1 << 15) - 1


class LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class LandlockPathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _get_libc() -> ctypes.CDLL:
    return ctypes.CDLL("libc.so.6", use_errno=True)


def get_landlock_status() -> dict[str, Any]:
    """
    Consulta al kernel la compatibilidad y versión de Landlock LSM sin crear reglas.
    Llamada syscall(SYS_LANDLOCK_CREATE_RULESET, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION).
    """
    try:
        libc = _get_libc()
        res = libc.syscall(SYS_LANDLOCK_CREATE_RULESET, 0, 0, LANDLOCK_CREATE_RULESET_VERSION)
        if res > 0:
            return {
                "status": "SUPPORTED",
                "supported": True,
                "abi_version": int(res),
                "features": {
                    "v1_basic": res >= 1,
                    "v2_refer": res >= 2,
                    "v3_truncate": res >= 3,
                },
            }
        errno = ctypes.get_errno()
        return {
            "status": "UNSUPPORTED",
            "supported": False,
            "abi_version": 0,
            "errno": errno,
            "message": f"Landlock no soportado por el kernel activo (errno {errno}).",
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("Landlock check failed: %s", e)
        return {
            "status": "DEGRADED",
            "supported": False,
            "abi_version": 0,
            "error": str(e),
        }


class LandlockSandbox:
    """
    Constructor y ejecutor de políticas de restricción de sistema de archivos Landlock LSM.
    Permite definir listas blancas de rutas con lectura y lectura/escritura.
    """

    def __init__(
        self,
        allowed_read_paths: list[str | Path] | None = None,
        allowed_write_paths: list[str | Path] | None = None,
        read_paths: list[str | Path] | None = None,
        write_paths: list[str | Path] | None = None,
    ) -> None:
        reads = allowed_read_paths if allowed_read_paths is not None else (read_paths or [])
        writes = allowed_write_paths if allowed_write_paths is not None else (write_paths or [])
        self.allowed_read_paths: list[Path] = [Path(p).resolve() for p in reads]
        self.allowed_write_paths: list[Path] = [Path(p).resolve() for p in writes]

    def add_read_path(self, path: str | Path) -> None:
        """Añade una ruta permitida solo para lectura."""
        p = Path(path).resolve()
        if p not in self.allowed_read_paths:
            self.allowed_read_paths.append(p)

    def add_write_path(self, path: str | Path) -> None:
        """Añade una ruta permitida para lectura y escritura."""
        p = Path(path).resolve()
        if p not in self.allowed_write_paths:
            self.allowed_write_paths.append(p)

    def apply(self) -> dict[str, Any]:
        """
        Aplica las restricciones Landlock irrevocablemente en el proceso actual.
        DIR-ONT-01: Obliga prctl(PR_SET_NO_NEW_PRIVS, 1) antes de SYS_landlock_restrict_self.
        """
        status = get_landlock_status()
        if not status.get("supported"):
            return {
                "status": "UNSUPPORTED",
                "applied": False,
                "error": status.get("message", "Landlock no soportado"),
            }

        abi = status.get("abi_version", 1)
        handled = FULL_FS_ACCESS_V3 if abi >= 3 else FULL_FS_ACCESS_V1
        read_mask = READ_ACCESS_MASK
        write_mask = (READ_ACCESS_MASK | WRITE_ACCESS_MASK) if abi < 3 else (READ_ACCESS_MASK | WRITE_ACCESS_MASK | ACCESS_FS_TRUNCATE)

        libc = _get_libc()
        attr = LandlockRulesetAttr(handled_access_fs=handled)
        ruleset_fd = libc.syscall(
            SYS_LANDLOCK_CREATE_RULESET,
            ctypes.byref(attr),
            ctypes.sizeof(attr),
            0,
        )
        if ruleset_fd < 0:
            errno = ctypes.get_errno()
            return {"status": "ERROR", "applied": False, "error": f"Error al crear ruleset: errno {errno}"}

        rules_added = 0
        try:
            # 1. Reglas de solo lectura
            for rpath in self.allowed_read_paths:
                if not rpath.exists():
                    continue
                fd = os.open(str(rpath), os.O_PATH | os.O_CLOEXEC)
                try:
                    beneath = LandlockPathBeneathAttr(allowed_access=read_mask, parent_fd=fd)
                    ret = libc.syscall(SYS_LANDLOCK_ADD_RULE, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(beneath), 0)
                    if ret == 0:
                        rules_added += 1
                finally:
                    os.close(fd)

            # 2. Reglas de lectura y escritura
            for wpath in self.allowed_write_paths:
                if not wpath.exists():
                    continue
                fd = os.open(str(wpath), os.O_PATH | os.O_CLOEXEC)
                try:
                    beneath = LandlockPathBeneathAttr(allowed_access=write_mask, parent_fd=fd)
                    ret = libc.syscall(SYS_LANDLOCK_ADD_RULE, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(beneath), 0)
                    if ret == 0:
                        rules_added += 1
                finally:
                    os.close(fd)

            # 3. DIR-ONT-01: prctl PR_SET_NO_NEW_PRIVS (38)
            pr_ret = libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
            if pr_ret != 0:
                errno = ctypes.get_errno()
                return {"status": "ERROR", "applied": False, "error": f"prctl PR_SET_NO_NEW_PRIVS falló: errno {errno}"}

            # 4. Restringir el proceso
            rest_ret = libc.syscall(SYS_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0)
            if rest_ret != 0:
                errno = ctypes.get_errno()
                return {"status": "ERROR", "applied": False, "error": f"SYS_landlock_restrict_self falló: errno {errno}"}

            return {
                "status": "APPLIED",
                "applied": True,
                "abi_version": abi,
                "rules_added": rules_added,
            }
        finally:
            os.close(ruleset_fd)

    def run_isolated_probe(self, probe_write_target: str | Path) -> dict[str, Any]:
        """
        Ejecuta un sondeo aislado en un subproceso hijo para verificar la efectividad
        del confinamiento Landlock sin restringir el proceso padre de AEP.
        """
        target_path = Path(probe_write_target).resolve()
        r_pipe, w_pipe = os.pipe()

        pid = os.fork()
        if pid == 0:
            os.close(r_pipe)
            apply_res = self.apply()
            probe_result = {
                "supported": apply_res.get("applied", False),
                "enforced": apply_res.get("applied", False),
                "apply_status": apply_res,
                "write_attempted": str(target_path),
                "write_blocked": False,
                "error": None,
            }

            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write("probe_test")
                probe_result["write_blocked"] = False
            except PermissionError as pe:
                probe_result["write_blocked"] = True
                probe_result["error"] = str(pe)
            except Exception as e:  # noqa: BLE001
                probe_result["write_blocked"] = False
                probe_result["error"] = str(e)

            payload = json.dumps(probe_result).encode("utf-8")
            os.write(w_pipe, payload)
            os.close(w_pipe)
            os._exit(0)

        os.close(w_pipe)
        data = b""
        while chunk := os.read(r_pipe, 4096):
            data += chunk
        os.close(r_pipe)
        _, status = os.waitpid(pid, 0)

        if not data:
            return {"status": "ERROR", "error": "No output from isolated probe"}

        try:
            return json.loads(data.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"status": "ERROR", "raw": data.decode("utf-8", errors="replace"), "error": str(e)}


def run_isolated_probe(
    probe_write_target: str | Path,
    read_paths: list[str | Path] | None = None,
    write_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Sondeo de confinamiento Landlock en subproceso hijo aislado."""
    sandbox = LandlockSandbox(read_paths=read_paths or ["/"], write_paths=write_paths or [])
    return sandbox.run_isolated_probe(probe_write_target)
