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
import logging
import shutil
import signal
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from engine.db import get_ro_connection, get_rw_connection, transaction_immediate
from engine.privilege import capability_tier, privilege_prefix

logger = logging.getLogger("aep.crash_router")

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
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn_rw() as conn:
            with transaction_immediate(conn):
                conn.executescript(_CRASH_DDL)

    def _conn_ro(self) -> sqlite3.Connection:
        return get_ro_connection(self.db_path, row_factory=True, load_vec=False)

    def _conn_rw(self) -> sqlite3.Connection:
        return get_rw_connection(self.db_path, row_factory=True, load_vec=False)

    def _conn(self) -> sqlite3.Connection:
        return self._conn_rw()

    def sync_coredumps(self, limit: int = 100) -> int:
        """Lee los coredumps recientes y registra los nuevos. Devuelve cuántos nuevos.
        FAIL-SOFT: si coredumpctl no existe, devuelve 0 sin lanzar."""
        if not shutil.which("coredumpctl"):
            return 0
        try:
            prefix = privilege_prefix() or []
            r = subprocess.run(
                prefix + ["coredumpctl", "list", "--json=short", "--reverse", "-n", str(limit)],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return 0
            entries = json.loads(r.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
            logger.debug("sync_coredumps fetch/parse error: %s", e)
            return 0

        new = 0
        with self._conn_rw() as conn:
            with transaction_immediate(conn):
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
                    except sqlite3.Error as ex:
                        logger.debug("Failed to insert crash event %s: %s", fp, ex)
        return new

    def pending_alerts(self, resolve_after_report: bool = False) -> list[dict[str, Any]]:
        conn_fn = self._conn_rw if resolve_after_report else self._conn_ro
        with conn_fn() as conn:
            if resolve_after_report:
                with transaction_immediate(conn):
                    rows = conn.execute(
                        "SELECT id, pid, signal, executable, event_timestamp, coredump_info "
                        "FROM crash_events WHERE resolved = 0 ORDER BY id DESC"
                    ).fetchall()
                    alerts = []
                    for r in rows:
                        d = dict(r)
                        try:
                            d["coredump_info"] = json.loads(d["coredump_info"])
                        except json.JSONDecodeError as e:
                            logger.debug("Failed to decode coredump_info JSON: %s", e)
                        if isinstance(d.get("coredump_info"), dict):
                            if "cmdline" not in d or d["cmdline"] is None:
                                d["cmdline"] = d["coredump_info"].get("cmdline")
                        alerts.append(d)
                    if alerts:
                        conn.execute("UPDATE crash_events SET resolved = 1 WHERE resolved = 0")
            else:
                rows = conn.execute(
                    "SELECT id, pid, signal, executable, event_timestamp, coredump_info "
                    "FROM crash_events WHERE resolved = 0 ORDER BY id DESC"
                ).fetchall()
                alerts = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["coredump_info"] = json.loads(d["coredump_info"])
                    except json.JSONDecodeError as e:
                        logger.debug("Failed to decode coredump_info JSON: %s", e)
                    if isinstance(d.get("coredump_info"), dict):
                        if "cmdline" not in d or d["cmdline"] is None:
                            d["cmdline"] = d["coredump_info"].get("cmdline")
                    alerts.append(d)
        return alerts

    def sync_apport(self, crash_dir: Path | str = Path("/var/crash")) -> int:
        """Sincroniza archivos .crash de Apport en crash_events con de-duplicación por fingerprint.
        FAIL-SOFT: Si /var/crash no existe o no se puede leer, devuelve 0 sin lanzar (R-4)."""
        cd = Path(crash_dir)
        if not cd.exists() or not cd.is_dir():
            return 0

        try:
            crash_files = [p for p in cd.glob("*.crash") if p.is_file()]
        except OSError as e:
            logger.debug("Failed listing crash directory %s: %s", cd, e)
            return 0

        new = 0
        with self._conn_rw() as conn:
            with transaction_immediate(conn):
                for cf in crash_files:
                    try:
                        st = cf.stat()
                        mtime = int(st.st_mtime)
                    except OSError:
                        continue

                    fp = f"apport:{cf.name}:{mtime}"

                    # Intentar leer headers con fallback ante PermissionError / OSError (R-4)
                    exe: str | None = None
                    sig: str | None = None
                    date_str: str | None = None
                    pid: int | None = None
                    cmdline: str | None = None
                    problem_type: str | None = None

                    MAX_HEADER_BYTES = 65536
                    bytes_read = 0
                    try:
                        with cf.open("r", encoding="utf-8", errors="replace") as f:
                            for line in f:
                                bytes_read += len(line.encode("utf-8", errors="replace"))
                                if bytes_read > MAX_HEADER_BYTES:
                                    break
                                if line.startswith(("CoreDump:", "Traceback:", "Stacktrace:")):
                                    break
                                if line.startswith("ExecutablePath:"):
                                    exe = line.split(":", 1)[1].strip()
                                elif line.startswith("Signal:"):
                                    raw_sig = line.split(":", 1)[1].strip()
                                    try:
                                        sig = signal.Signals(int(raw_sig)).name
                                    except (ValueError, TypeError):
                                        sig = str(raw_sig) if raw_sig else "UNKNOWN"
                                elif line.startswith("Pid:"):
                                    raw_pid = line.split(":", 1)[1].strip()
                                    try:
                                        pid = int(raw_pid)
                                    except (ValueError, TypeError):
                                        pid = None
                                elif line.startswith("ProcCmdline:"):
                                    cmdline = line.split(":", 1)[1].strip()
                                elif line.startswith("Date:"):
                                    date_str = line.split(":", 1)[1].strip()
                                elif line.startswith("ProblemType:"):
                                    problem_type = line.split(":", 1)[1].strip()
                    except (PermissionError, OSError) as pe:
                        logger.debug("Permission/IO error reading %s; using stat fallback: %s", cf, pe)

                    # Stat fallback si no fue posible leer o faltan campos
                    if not exe:
                        clean_stem = cf.stem
                        clean_stem = clean_stem.removeprefix("_")
                        parts = clean_stem.rsplit(".", 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            clean_stem = parts[0]
                        exe = "/" + clean_stem.replace("_", "/")
                    if not sig:
                        sig = "UNKNOWN"
                    if not date_str:
                        date_str = str(mtime)

                    info = {
                        "source": "apport",
                        "file": cf.name,
                        "size_bytes": st.st_size,
                        "mtime": mtime,
                        "uid": st.st_uid,
                        "cmdline": cmdline,
                        "problem_type": problem_type,
                    }

                    try:
                        cur = conn.execute(
                            """INSERT OR IGNORE INTO crash_events
                               (fingerprint, pid, signal, executable, event_timestamp, coredump_info)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (fp, pid, sig, exe, date_str, json.dumps(info)),
                        )
                        if cur.rowcount:
                            new += 1
                    except sqlite3.Error as ex:
                        logger.debug("Failed to insert apport crash event %s: %s", fp, ex)

        return new

    def check(self, resolve_after_report: bool = False) -> dict[str, Any]:
        new_core = self.sync_coredumps()
        new_app = self.sync_apport()
        new = new_core + new_app
        alerts = self.pending_alerts(resolve_after_report)

        has_coredumpctl = shutil.which("coredumpctl") is not None
        has_apport = Path("/var/crash").is_dir()

        if has_coredumpctl:
            status = "OK"
            source = "coredumpctl"
            note = None
        elif has_apport or len(alerts) > 0:
            status = "OK"
            source = "apport"
            note = "coredumpctl ausente; alertas sincronizadas via Apport (/var/crash)."
        else:
            status = "DEGRADED"
            source = "none"
            note = "coredumpctl ausente; enrutador inerte (fail-soft)."

        return {
            "status": status,
            "source": source,
            "capability_tier": capability_tier(),
            "scope": "system" if privilege_prefix() else "user",
            "new_since_last_check": new,
            "pending_count": len(alerts),
            "alerts": alerts,
            "note": note,
        }
