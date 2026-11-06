"""
Engine: lkg_ctl.py (ONT-41 TC3: aep_ctl(domain="backup") lkg_status | lkg_diff | lkg_restore)

Camino unico y seguro sobre `aep_lkg` compartido por el servidor y `scripts/aep-ctl`:
  - lkg_status: lectura (cualquier tier).
  - lkg_diff:   lectura de archivos (`name` = rutas relativas separadas por coma).
  - lkg_restore: tier >= 6rw-; SIEMPRE ensaya primero (dry-run); solo escribe con `apply=True`, tras crear un
    workspace_snapshot (`snapshot_fn(files)`); si el snapshot falla no se escribe nada.
Topos: depende de `aep_lkg`; no importa `server` (el tier y el snapshot se inyectan).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import aep_lkg

ACTIONS: tuple[str, ...] = ("lkg_status", "lkg_diff", "lkg_restore")
MIN_RESTORE_OCTAL = 6
MAX_FILES = 50
_SNAPSHOT_BAD = ("ERROR", "PERMISSION_DENIED", "NOT_FOUND", "QUOTA_EXCEEDED")


def _snapshot_ok(result: Any) -> bool:
    if result is False:
        return False
    if isinstance(result, dict):
        status = str(result.get("status", "")).upper()
        return not (result.get("ok") is False or result.get("error") or status in _SNAPSHOT_BAD)
    return True


def _files_arg(name: str | None) -> list[str]:
    return [p.strip() for p in (name or "").split(",") if p.strip()][:MAX_FILES]


def lkg_status() -> dict[str, Any]:
    keys = aep_lkg.list_keys()
    key = aep_lkg.latest()
    out: dict[str, Any] = {"status": "OK" if key else "NO_LKG", "key": key, "snapshots": len(keys)}
    if key:
        manifest = aep_lkg.read_manifest(key)
        out.update(
            ts=manifest.get("ts"),
            generation=manifest.get("generation"),
            files=len(manifest["files"]),
            code_fingerprint=manifest.get("code_fingerprint"),
        )
    return out


def lkg_ctl(
    action: str,
    name: str | None,
    *,
    repo_root: Path | str,
    tier_octal: int,
    apply: bool = False,
    snapshot_fn: Callable[[list[str]], Any] | None = None,
) -> dict[str, Any]:
    try:
        if action == "lkg_status":
            return lkg_status()
        key = aep_lkg.latest()
        if not key:
            return {"status": "NO_LKG"}
        files = _files_arg(name)
        if not files:
            return {"status": "ERROR", "error": "name debe indicar archivo(s) relativos separados por coma."}
        if action == "lkg_diff":
            return {"status": "OK", "key": key, "diffs": [aep_lkg.diff(key, f, repo_root) for f in files[:5]]}
        if action != "lkg_restore":
            return {"status": "ERROR", "error": f"accion lkg desconocida: {action}", "valid": list(ACTIONS)}
        if tier_octal < MIN_RESTORE_OCTAL:
            return {"status": "PERMISSION_DENIED", "error": "lkg_restore requiere tier >= 6rw-.", "chmod_tier_octal": tier_octal}
        dry = aep_lkg.restore_files(key, files, repo_root, dry_run=True)
        if not apply or not any(f["would_change"] for f in dry["files"]):
            return {"status": "DRY_RUN", "applied": False, "plan": dry["files"], "next": "repetir con params={'apply': true}"}
        if snapshot_fn is None:
            return {"status": "SNAPSHOT_REQUIRED", "applied": False, "plan": dry["files"]}
        try:
            snap = snapshot_fn(list(files))
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del snapshot aborta sin escribir
            return {"status": "SNAPSHOT_FAILED", "applied": False, "error": f"{type(exc).__name__}: {exc}"}
        if not _snapshot_ok(snap):
            return {"status": "SNAPSHOT_FAILED", "applied": False, "error": "snapshot_fn reported failure"}
        done = aep_lkg.restore_files(key, files, repo_root, dry_run=False)
        return {"status": "RESTORED", "applied": True, "restored": done["restored"], "snapshot": snap}
    except aep_lkg.LkgError as exc:
        return {"status": "ERROR", "error": str(exc)[:200]}
