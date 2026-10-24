"""
Engine: crash_router.py  (SPEC-OM-2: Active Crash Routing & Proactive Self-Healing)

Transmuta `coredumpctl` (crash triage ofensivo) en un enrutador PROACTIVO de fallos
hacia el agente. Modo POLLING on-demand (sin unit systemd, sin sudo): en cada llamada
diffea `coredumpctl list` contra la tabla `crash_events` y devuelve lo nuevo.

# Mejora futura: modo push en tiempo real vía systemd path unit requiere acceso a nivel
# de sistema; el polling es suficiente para Fase 1 y 100% espacio de usuario.

Topos: crash_router.py -> artifacts.db es dependencia unidireccional (A -> B). Abre su
PROPIA conexión; NO importa catalog.py. El DDL autoritativo de crash_events vive en
schemas/database.sql; _init_table() aquí es solo una red de seguridad idempotente.
"""

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.db import get_db_connection
from engine.privilege import capability_tier, privilege_prefix

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

_CRASH_DDL = """
CREATE TABLE IF NOT EXISTS crash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,   -- clave de de-duplicación (pid+timestamp+exe)
    pid INTEGER,
    signal TEXT,
    executable TEXT,
    event_timestamp TEXT,
    coredump_info TEXT,                 -- JSON crudo de coredumpctl
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class CrashRouter:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_CRASH_DDL)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path, row_factory=True, load_vec=False)

    def sync_coredumps(self, limit: int = 100) -> int:
        """Lee los coredumps recientes y registra los nuevos. Devuelve cuántos nuevos.
        FAIL-SOFT: si coredumpctl no existe, devuelve 0 sin lanzar."""
        if not shutil.which("coredumpctl"):
            return 0
        try:
            # Nivel FULL (root/sudo -n) ve coredumps de todo el sistema; DIMINISHED, los propios.
            # --reverse + -n limita (fix Ontos SF-2: sin esto podría volcar miles de filas).
            prefix = privilege_prefix() or []
            r = subprocess.run(
                prefix + ["coredumpctl", "list", "--json=short", "--reverse", "-n", str(limit)],
                capture_output=True, text=True,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return 0
            entries = json.loads(r.stdout)
        except Exception:
            return 0

        new = 0
        with self._conn() as conn:
            for e in entries:
                pid = e.get("pid")
                ts = str(e.get("time", ""))
                exe = e.get("exe", "")
                fp = f"{pid}:{ts}:{exe}"
                try:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO crash_events
                           (fingerprint, pid, signal, executable, event_timestamp, coredump_info)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (fp, pid, str(e.get("sig", "")), exe, ts, json.dumps(e)),
                    )
                    if cur.rowcount:
                        new += 1
                except Exception:
                    pass
            conn.commit()
        return new

    def pending_alerts(self, resolve_after_report: bool = False) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, pid, signal, executable, event_timestamp, coredump_info "
                "FROM crash_events WHERE resolved = 0 ORDER BY id DESC"
            ).fetchall()
            alerts = []
            for r in rows:
                d = dict(r)
                try:
                    d["coredump_info"] = json.loads(d["coredump_info"])
                except Exception:
                    pass
                alerts.append(d)
            if resolve_after_report and alerts:
                conn.execute("UPDATE crash_events SET resolved = 1 WHERE resolved = 0")
                conn.commit()
        return alerts

    def check(self, resolve_after_report: bool = False) -> Dict[str, Any]:
        new = self.sync_coredumps()
        alerts = self.pending_alerts(resolve_after_report)
        return {
            "status": "OK" if shutil.which("coredumpctl") else "DEGRADED",
            "capability_tier": capability_tier(),
            "scope": "system" if privilege_prefix() else "user",
            "new_since_last_check": new,
            "pending_count": len(alerts),
            "alerts": alerts,
            "note": None if shutil.which("coredumpctl")
            else "coredumpctl ausente; enrutador inerte (fail-soft).",
        }
