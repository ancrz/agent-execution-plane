"""
Engine: threads_ledger.py (ONT-42c C5/C7: ledger SQLite de `autoevol(evolve)`)

Condiciones Ontos 13 y 14: git es la fuente de verdad y el ledger es el indice.

  - `evolve_keys`: una fila por intento de evolve, UNIQUE (gap_canonical, base_r, tree_hash) con `INSERT OR IGNORE`.
    Una llamada repetida con la misma clave devuelve la fila existente y no crea otro commit. Guarda `r_before` /
    `r_after` (raiz Merkle del grafo antes y despues del parche, C7) y el estado reconciliado con git.
  - `evolve_events`: eventos `evolve.*` (committed, gate, merged, reverted, pushed, blocked) con su carga.
  - Tope de ciclos (`AEP_AUTOEVOL_MAX_CYCLES`, defecto 3) contado en la propia BD sobre una ventana de 24 h:
    sobrevive a los hot-swaps y reinicios que esta misma funcion provoca (un contador en memoria se perderia).

No importa `server` ni `threads_evolve` (arista dep unidireccional: evolve -> ledger).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.db import get_db_connection, transaction_immediate

DEFAULT_MAX_CYCLES = 3
WINDOW_SECONDS = 24 * 3600
REVERTED = "REVERTED"
_LOCK = threading.Lock()

DDL = (
    """CREATE TABLE IF NOT EXISTS evolve_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gap_canonical TEXT NOT NULL,
        base_r TEXT NOT NULL,
        tree_hash TEXT NOT NULL,
        cycle TEXT NOT NULL,
        state TEXT NOT NULL,
        r_before TEXT NOT NULL DEFAULT '',
        r_after TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        UNIQUE (gap_canonical, base_r, tree_hash)
    )""",
    """CREATE TABLE IF NOT EXISTS evolve_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        kind TEXT NOT NULL,
        cycle TEXT NOT NULL,
        data_json TEXT NOT NULL
    )""",
)


def max_cycles_from_env(raw: str | None) -> int:
    """`AEP_AUTOEVOL_MAX_CYCLES`: entero >= 1; ausente o invalido => 3."""
    try:
        value = int(str(raw).strip())
    except TypeError, ValueError:
        return DEFAULT_MAX_CYCLES
    return value if value >= 1 else DEFAULT_MAX_CYCLES


class EvolveLedger:
    """Ledger en la BD de AEP. `db_path` y `clock` inyectables (tests: BD temporal, reloj falso)."""

    def __init__(
        self, db_path: Path | str, *, max_cycles: int = DEFAULT_MAX_CYCLES, clock: Callable[[], float] = time.time
    ) -> None:
        self._path = Path(db_path)
        self.max_cycles = max(1, int(max_cycles))
        self._clock = clock

    def _conn(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_db_connection(self._path)
        for stmt in DDL:
            conn.execute(stmt)
        return conn

    # -- idempotencia + tope (condiciones 13 y 14) ----------------------------------------------
    def claim(self, gap: str, base_r: str, tree: str, cycle: str, *, r_before: str, r_after: str) -> dict[str, Any]:
        """Reserva la clave. `{"claimed": True}` si es nueva; `{"claimed": False, "row": ...}` si ya existia
        (misma clave: duplicado o reentrada del mismo ciclo); `{"claimed": False, "capped": True}` si se agoto el tope."""
        now = self._clock()
        conn = self._conn()
        try:
            with _LOCK, transaction_immediate(conn):
                row = conn.execute(
                    "SELECT cycle, state, r_before, r_after FROM evolve_keys "
                    "WHERE gap_canonical = ? AND base_r = ? AND tree_hash = ?",
                    (gap, base_r, tree),
                ).fetchone()
                if row is not None:
                    return {
                        "claimed": False,
                        "row": {"cycle": row[0], "state": row[1], "r_before": row[2], "r_after": row[3]},
                    }
                used = conn.execute(
                    "SELECT COUNT(*) FROM evolve_keys WHERE created_at > ?", (now - WINDOW_SECONDS,)
                ).fetchone()[0]
                if used >= self.max_cycles:
                    return {"claimed": False, "capped": True, "used": int(used), "max": self.max_cycles}
                conn.execute(
                    "INSERT OR IGNORE INTO evolve_keys (gap_canonical, base_r, tree_hash, cycle, state, r_before, r_after, "
                    "created_at) VALUES (?, ?, ?, ?, 'CLAIMED', ?, ?, ?)",
                    (gap, base_r, tree, cycle, r_before, r_after, now),
                )
            return {"claimed": True, "used": int(used) + 1, "max": self.max_cycles}
        finally:
            conn.close()

    def set_state(self, cycle: str, state: str) -> None:
        """Indice reconciliado con git: se llama en cada transicion y en cada reentrada."""
        conn = self._conn()
        try:
            with _LOCK, transaction_immediate(conn):
                conn.execute(
                    "UPDATE evolve_keys SET state = ? WHERE cycle = ? AND state != ?", (state, cycle, REVERTED)
                )
        finally:
            conn.close()

    def get(self, cycle: str) -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT gap_canonical, base_r, tree_hash, state, r_before, r_after FROM evolve_keys WHERE cycle = ? "
                "ORDER BY id DESC LIMIT 1",
                (cycle,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        keys = ("gap", "base_r", "tree", "state", "r_before", "r_after")
        return dict(zip(keys, row, strict=True))

    def mark_reverted(self, cycle: str) -> None:
        conn = self._conn()
        try:
            with _LOCK, transaction_immediate(conn):
                conn.execute("UPDATE evolve_keys SET state = ? WHERE cycle = ?", (REVERTED, cycle))
        finally:
            conn.close()

    def resolve_revert(self, cycle: str) -> None:
        """Decision del usuario sobre un revert: libera el bloqueo de push (`dev_dirty_by_revert`). Sin superficie MCP."""
        conn = self._conn()
        try:
            with _LOCK, transaction_immediate(conn):
                conn.execute(
                    "UPDATE evolve_keys SET state = 'REVERT_RESOLVED' WHERE cycle = ? AND state = ?", (cycle, REVERTED)
                )
        finally:
            conn.close()

    def revert_pending(self) -> bool:
        """True si algun ciclo quedo revertido sin decision del usuario: dev esta adelantado a origin por el revert."""
        conn = self._conn()
        try:
            row = conn.execute("SELECT 1 FROM evolve_keys WHERE state = ? LIMIT 1", (REVERTED,)).fetchone()
        finally:
            conn.close()
        return row is not None

    # -- eventos evolve.* -------------------------------------------------------------------------
    def event(self, kind: str, cycle: str, data: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            with _LOCK, transaction_immediate(conn):
                conn.execute(
                    "INSERT INTO evolve_events (ts, kind, cycle, data_json) VALUES (?, ?, ?, ?)",
                    (self._clock(), kind, cycle, json.dumps(data, sort_keys=True, separators=(",", ":"))),
                )
        finally:
            conn.close()

    def events(self, cycle: str | None = None) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            if cycle:
                rows = conn.execute(
                    "SELECT kind, cycle, data_json FROM evolve_events WHERE cycle = ? ORDER BY id", (cycle,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT kind, cycle, data_json FROM evolve_events ORDER BY id").fetchall()
        finally:
            conn.close()
        return [{"kind": r[0], "cycle": r[1], "data": json.loads(r[2])} for r in rows]
