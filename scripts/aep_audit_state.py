#!/usr/bin/env python3
"""
aep_audit_state.py (ONT-41 TC6/TC8): clasifica las instancias del front a partir de /dev/shm/aep_front_<pid>.json.

Clases (una por archivo valido con pid vivo):
  - serving_lkg   : el front sirve desde el LKG (serving_from == "lkg").
  - front_stale   : aep_front.py cambio despues de arrancar el front -> requiere RECONEXION del usuario.
  - backend_stale : el backend activo no coincide con el fingerprint del disco -> el auto-swap lo resuelve.
  - current       : al dia.
Los archivos de pids muertos se ignoran y se LIMPIAN (solo si son regulares, propios y no symlinks).
Los pids vivos sin archivo se etiquetan `legacy/unknown` (D-24: heuristica por mtime, la decide el llamante).

Uso: aep_audit_state.py <project_root> [--dir /dev/shm] [--no-clean] [pid ...]
Salida: JSON `{"instances": [...], "removed": [...]}` (una sola linea, sin ANSI).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

STATE_RE = re.compile(r"^aep_front_(\d+)\.json$")
STATE_MAX_BYTES = 64 * 1024


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def proc_start_time(pid: int) -> float | None:
    """Epoch de arranque del proceso (btime + starttime/CLK_TCK); None si no se puede leer."""
    try:
        stat_raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        start_ticks = int(stat_raw.rsplit(")", 1)[1].split()[19])
        btime = next(
            int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime")
        )
        return btime + start_ticks / os.sysconf("SC_CLK_TCK")
    except OSError, ValueError, IndexError, StopIteration:
        return None


def read_state(directory: Path, name: str) -> dict[str, Any] | None:
    """Lectura segura: O_NOFOLLOW, archivo regular, dueno == euid, tamano acotado. None si es invalido."""
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        )
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_size > STATE_MAX_BYTES:
            return None
        data = json.loads(os.read(fd, STATE_MAX_BYTES + 1).decode("utf-8", errors="replace"))
    except ValueError:
        return None
    finally:
        os.close(fd)
    return data if isinstance(data, dict) else None


def classify(
    state: dict[str, Any],
    *,
    disk_fingerprint: str,
    front_mtime: float,
    start_time: float | None,
) -> tuple[str, str]:
    if state.get("serving_from") == "lkg":
        return "serving_lkg", "sirve desde LKG; corrija el arbol y espere la promocion o reconecte"
    if start_time is not None and front_mtime > start_time:
        return "front_stale", "aep_front.py cambio tras el arranque: reconecte la sesion (el auto-swap no lo cubre)"
    if state.get("active_fingerprint") and state["active_fingerprint"] != disk_fingerprint:
        return "backend_stale", "el backend se reemplaza solo (auto-swap); no requiere reconexion"
    return "current", "al dia"


def audit(
    project_root: Path,
    shm_dir: Path = Path("/dev/shm"),
    *,
    clean: bool = True,
    running_pids: list[int] | None = None,
    fingerprint_fn: Callable[[str], str] | None = None,
    alive_fn: Callable[[int], bool] = pid_alive,
    start_fn: Callable[[int], float | None] = proc_start_time,
) -> dict[str, Any]:
    if fingerprint_fn is None:
        sys.path.insert(0, str(project_root))
        from engine.fingerprint import code_fingerprint as fingerprint_fn  # noqa: PLC0415
    disk_fp = fingerprint_fn(str(project_root))
    try:
        front_mtime = (project_root / "aep_front.py").stat().st_mtime
    except OSError:
        front_mtime = 0.0
    instances: list[dict[str, Any]] = []
    removed: list[str] = []
    seen: set[int] = set()
    try:
        names = sorted(n for n in os.listdir(shm_dir) if STATE_RE.match(n))
    except OSError:
        names = []
    for name in names:
        pid = int(STATE_RE.match(name).group(1))  # type: ignore[union-attr]
        if not alive_fn(pid):
            if clean and read_state(shm_dir, name) is not None:
                with contextlib.suppress(OSError):
                    os.unlink(shm_dir / name)
                    removed.append(name)
            continue
        state = read_state(shm_dir, name)
        if state is None:
            continue
        seen.add(pid)
        klass, detail = classify(state, disk_fingerprint=disk_fp, front_mtime=front_mtime, start_time=start_fn(pid))
        instances.append({"pid": pid, "class": klass, "detail": detail, "generation": state.get("generation")})
    for pid in running_pids or []:
        if pid not in seen and alive_fn(pid):
            instances.append(
                {"pid": pid, "class": "legacy/unknown", "detail": "sin archivo de estado (D-24): heuristica por mtime"}
            )
    return {"instances": instances, "removed": removed}


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(json.dumps({"error": "project_root requerido"}))
        return 2
    root = Path(args.pop(0))
    shm = Path("/dev/shm")
    clean = True
    pids: list[int] = []
    while args:
        a = args.pop(0)
        if a == "--dir" and args:
            shm = Path(args.pop(0))
        elif a == "--no-clean":
            clean = False
        elif a.isdigit():
            pids.append(int(a))
    print(json.dumps(audit(root, shm, clean=clean, running_pids=pids), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
