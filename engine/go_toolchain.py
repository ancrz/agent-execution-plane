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


# --------------------------------------------------------------------------- ONT-59 T3: curación mecánica en modo módulo
def build_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Entorno reproducible: sin descargas implícitas de toolchain (GOTOOLCHAIN=local), módulo editable, sin CGO."""
    env = dict(os.environ if base is None else base)
    env.update({"CGO_ENABLED": "0", "GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "local"})
    return env


def write_go_mod(build_dir: Path, art_name: str, version: str | None) -> Path:
    """go.mod mínimo: `module aep.local/<nombre>` + `go <major.minor del toolchain en uso>`."""
    mod = re.sub(r"[^A-Za-z0-9._-]", "_", art_name) or "artifact"
    mm = major_minor(version) or GO_SUPPORTED_MIN
    path = build_dir / "go.mod"
    path.write_text(f"module aep.local/{mod}\n\ngo {mm}\n", encoding="utf-8")
    return path


def gofmt_source(src: str) -> tuple[bool, str, str]:
    """Forma canónica (gofmt). Devuelve (ok, fuente_canónica, error). Sin gofmt -> (True, src, '') (no se puede curar)."""
    gofmt = gofmt_path()
    if not gofmt:
        return True, src, ""
    try:
        r = subprocess.run([gofmt], input=src, capture_output=True, text=True, timeout=30, check=False)
    except OSError, subprocess.SubprocessError:
        return True, src, ""
    if r.returncode != 0:
        return False, src, r.stderr.strip()
    return True, r.stdout, ""


def go_fix(build_dir: Path, *, apply: bool) -> dict[str, Any]:
    """`go fix -diff ./...` (modernizers, Go >= 1.26). Con apply=True ejecuta `go fix ./...`.
    Devuelve {available, lines, diff, applied}; `lines` cuenta las líneas +/- del diff (sin cabeceras)."""
    go = go_bin()
    out: dict[str, Any] = {"available": False, "lines": 0, "diff": "", "applied": False}
    if not go:
        return out
    env = build_env()
    try:
        d = subprocess.run(
            [go, "fix", "-diff", "./..."],
            cwd=str(build_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return out
    if d.returncode != 0 and not d.stdout:
        return out  # `go fix -diff` no soportado (Go < 1.26) o fallo: informativo, nunca bloqueante
    out["available"] = True
    out["diff"] = d.stdout
    out["lines"] = sum(1 for ln in d.stdout.splitlines() if ln[:1] in ("+", "-") and not ln.startswith(("+++", "---")))
    if apply and out["lines"]:
        try:
            a = subprocess.run(
                [go, "fix", "./..."],
                cwd=str(build_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            out["applied"] = a.returncode == 0
        except OSError, subprocess.SubprocessError:
            out["applied"] = False
    return out
