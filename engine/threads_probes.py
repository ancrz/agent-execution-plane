"""
Engine: threads_probes.py (ONT-40 T12: opt-in probes layer, DQ-2 / F5 / F14)

Observaciones de runtime del árbol destino. NO forman parte de R: cada observación queda fuera del
hash Merkle con su propio `obs_hash` (aristas `observes`).

Restricciones (F5), todas verificadas por tests:
  - solo con octal >= 5 (5r-x); por debajo devuelve SKIPPED, no error;
  - entorno en lista blanca; HOME, AEP_POOL_DIR y AEP_SOCKET_PATH en un tmpdir;
  - el hijo corre con AEP_FORCE_TIER=4r-- (C5): los probes NO validan tools que escriben;
  - `python -I -B` (sin PYTHON*, sin bytecode); el hijo neutraliza `ensure_ipc_server_started`;
  - jail bwrap (/dev/shm vacío). Fail-closed (H1): raíz ajena exige jail (si no hay: unavailable_no_jail); la caída
    a subproceso plano solo aplica al propio PROJECT_DIR y solo si bwrap no pudo arrancar (stderr `bwrap:`);
  - timeout de 10 s fail-open: un timeout es observación TIMEOUT, nunca un gap (O-8).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROBE_MIN_OCTAL = 5
PROBE_TIMEOUT_S = 10
SCHEMA_SUMMARY_MAX_TOKENS = 3000
_ENV_WHITELIST = ("PATH", "LANG", "LC_ALL")

_CHILD = r"""
import asyncio, json, os, sys
sys.path.insert(0, sys.argv[1])
import engine.ipc_pool as _p
_p.ensure_ipc_server_started = lambda *a, **k: None
import server
out = []
r = asyncio.run(server.discover(action="schema", verbosity="summary"))
tok = len(r) // 4
out.append({"probe": "schema_summary_tokens", "value": tok, "limit": __LIMIT__, "ok": tok <= __LIMIT__,
            "node": "action:discover:schema", "ref": "D-01",
            "detail": "discover(schema, summary) costs %d tokens (limit __LIMIT__)" % tok})
caps = json.loads(asyncio.run(server.discover(action="capabilities", verbosity="detail", force_refresh=True)))
cf = caps.get("capabilities", {}).get("crash_forensics", {})
has_crash = os.path.isdir("/var/crash")
ready = bool(cf.get("ready"))
out.append({"probe": "crash_forensics_ready", "value": ready, "mode": cf.get("mode"),
            "ok": ready or not has_crash, "node": "capability:crash_forensics", "ref": "D-08",
            "detail": "crash_forensics ready=%s mode=%s while /var/crash exists=%s" % (ready, cf.get("mode"), has_crash)})
print("AEP_PROBE_JSON=" + json.dumps(out))
""".replace("__LIMIT__", str(SCHEMA_SUMMARY_MAX_TOKENS))


def probe_env(tmp: Path) -> dict[str, str]:
    """Entorno en lista blanca del hijo: HOME, pool y socket aislados en `tmp`; tier forzado a 4r--."""
    env = {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ}
    env.update(
        HOME=str(tmp),
        TMPDIR=str(tmp),
        AEP_POOL_DIR=str(tmp / "pool"),
        AEP_SOCKET_PATH=str(tmp / "probe.sock"),
        AEP_FORCE_TIER="4r--",
        AEP_HOTSWAP="0",
    )
    return env


def _command(root: Path, tmp: Path, *, jail: bool) -> list[str]:
    base = [sys.executable, "-I", "-B", "-c", _CHILD, str(root)]
    if not jail:
        return base
    return [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/dev/shm",
        "--bind",
        str(tmp),
        str(tmp),
        "--unshare-net",
        "--die-with-parent",
        *base,
    ]


def _parse(stdout: str) -> list[dict[str, Any]] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith("AEP_PROBE_JSON="):
            try:
                return list(json.loads(line.removeprefix("AEP_PROBE_JSON=")))
            except ValueError:
                return None
    return None


def run_probes(
    root: Path | str, *, tier_octal: int, timeout: int = PROBE_TIMEOUT_S, allow_jail: bool = True
) -> dict[str, Any]:
    """Ejecuta los probes en un hijo aislado. Fail-open: nunca lanza ni produce gaps por fallos del probe."""
    if tier_octal < PROBE_MIN_OCTAL:
        return {"status": "SKIPPED", "reason": f"tier {tier_octal} < {PROBE_MIN_OCTAL} (5r-x)", "observations": []}
    base = Path(root).resolve()
    trusted = base == PROJECT_DIR  # solo el propio árbol es código de confianza (H1: fail-closed)
    jail = allow_jail and bool(shutil.which("bwrap")) and not os.environ.get("AEP_IN_SANDBOX")
    if not jail and not trusted:
        return {
            "status": "UNAVAILABLE",
            "probe_status": "unavailable_no_jail",
            "reason": "foreign root requires a bwrap jail (missing, disabled or AEP_IN_SANDBOX)",
            "observations": [],
        }
    tmp = Path(tempfile.mkdtemp(prefix="aep_probe_"))
    try:
        res: subprocess.CompletedProcess[str] | None = None
        for use_jail in [True, False] if jail else [False]:
            try:
                res = subprocess.run(
                    _command(base, tmp, jail=use_jail),
                    cwd=str(tmp),
                    env=probe_env(tmp),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "TIMEOUT", "timeout_s": timeout, "jail": use_jail, "observations": []}
            except OSError as exc:
                if use_jail and trusted:
                    continue  # bwrap no pudo lanzarse (binario ausente): solo el árbol propio cae a plano
                return {"status": "ERROR", "error": str(exc)[:200], "observations": []}
            obs = _parse(res.stdout)
            if obs is not None:
                return {"status": "OK", "jail": "bwrap" if use_jail else "none", "observations": obs}
            # Reintento sin jail únicamente si bwrap no arrancó Y el árbol es el propio.
            if use_jail and trusted and (res.stderr or "").startswith("bwrap:"):
                continue
            break
        return {"status": "ERROR", "error": ((res.stderr if res else "") or "")[-300:], "observations": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
