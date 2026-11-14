"""
Engine: go_toolchain.py — resolución del toolchain Go que usa AEP (ONT-59 T4/T5).

Filosofía Go: toolchain explícito y soportado. Quien decide la versión es el montaje (setup.sh), no una
descarga implícita en mitad de un build; AEP solo la lee, la registra y avisa si está fuera de soporte.

Orden de resolución del binario `go`:
  1. env `AEP_GO_BIN` (ruta absoluta)  2. `AEP_GO_BIN` en toolchain.env (escrito por setup.sh)  3. `shutil.which("go")`.

Topos: hoja pura (stdlib). Sin imports del proyecto.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Política de Go: solo se parchean las dos últimas versiones mayores. Hoy (2026-11-14) son 1.27 y 1.26.
# Actualizar este valor (y GO_SUPPORTED_MIN en scripts/setup.sh) cuando salga Go 1.28.
GO_SUPPORTED_MIN = "1.26"

_CACHE: dict[str, Any] = {}


def toolchain_env_path() -> Path:
    base = os.environ.get("AEP_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share" / "agent-os"
    return root / "toolchain.env"


def read_toolchain_env() -> dict[str, str]:
    """Parsea toolchain.env (KEY=VALUE por línea, sin ejecutar nada). Vacío si no existe."""
    out: dict[str, str] = {}
    try:
        text = toolchain_env_path().read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip("'\"")
    return out


def go_bin() -> str | None:
    """Ruta del binario go: AEP_GO_BIN (env o toolchain.env, si es ejecutable) > PATH."""
    for cand in (os.environ.get("AEP_GO_BIN"), read_toolchain_env().get("AEP_GO_BIN")):
        if cand and os.access(cand, os.X_OK):
            return cand
    return shutil.which("go")


def _run_go(go: str, *args: str) -> str | None:
    try:
        r = subprocess.run([go, *args], capture_output=True, text=True, timeout=20, check=False)
    except OSError, subprocess.SubprocessError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def go_version() -> str | None:
    """`go env GOVERSION` (p. ej. 'go1.27.4'); None si no hay Go. Cache por proceso y por binario."""
    go = go_bin()
    if not go:
        return None
    key = f"version:{go}"
    if key not in _CACHE:
        _CACHE[key] = _run_go(go, "env", "GOVERSION") or None
    return _CACHE[key]


def gofmt_path() -> str | None:
    """gofmt no está en PATH en muchos montajes: se resuelve por `$(go env GOROOT)/bin/gofmt`."""
    go = go_bin()
    if not go:
        return None
    key = f"gofmt:{go}"
    if key not in _CACHE:
        found: str | None = None
        goroot = _run_go(go, "env", "GOROOT")
        if goroot:
            cand = Path(goroot) / "bin" / "gofmt"
            if os.access(cand, os.X_OK):
                found = str(cand)
        _CACHE[key] = found or shutil.which("gofmt")
    return _CACHE[key]


def _major_minor(version: str | None) -> tuple[int, int] | None:
    m = re.match(r"^(?:go)?(\d+)\.(\d+)", (version or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def major_minor(version: str | None) -> str | None:
    mm = _major_minor(version)
    return f"{mm[0]}.{mm[1]}" if mm else None


def supported(version: str | None) -> bool:
    """True si `version` >= GO_SUPPORTED_MIN. Versión ilegible o ausente -> False."""
    mm, floor = _major_minor(version), _major_minor(GO_SUPPORTED_MIN)
    return bool(mm and floor and mm >= floor)


def go_info() -> dict[str, Any]:
    ver = go_version()
    return {
        "version": ver,
        "bin": go_bin(),
        "gofmt": gofmt_path(),
        "supported": supported(ver),
        "supported_min": GO_SUPPORTED_MIN,
        "channel": read_toolchain_env().get("AEP_GO_CHANNEL"),
    }


def reset_cache() -> None:
    _CACHE.clear()
