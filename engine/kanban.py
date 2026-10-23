"""
Engine: kanban.py — Pico-Kanban: tablero de estados ABSTRACTO para gestión agéntica.

Completa la tríada Pico (Claw/Ansible/Jenkins) con un tablero kanban mínimo en SQLite que:
  1. Da al agente una memoria de trabajo para gestionar una actividad por tareas atómicas.
  2. PONDERA cada artefacto (linters + estados + éxito histórico) y decide cuándo promoverlo
     como plantilla reutilizable en el tiempo.

Es "idioma agéntico": transparente para el usuario (no lo ve salvo que pregunte), el agente
lo lee/escribe vía tools MCP tipadas — nunca SQL crudo desde el LLM.

Lane/estados (DAG, sin ciclos salvo re-trabajo explícito a BACKLOG):
    BACKLOG -> SYNTHESIZED -> LINTED -> CANARY -> PROMOTED | REJECTED

Topos: kanban.py -> artifacts.db (A->B). Conexión propia; no importa catalog.py.
"""

import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

STATES = ["BACKLOG", "SYNTHESIZED", "LINTED", "CANARY", "PROMOTED", "REJECTED"]
PROMOTION_THRESHOLD = 0.70

_KANBAN_DDL = """
CREATE TABLE IF NOT EXISTS kanban_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    intent TEXT,
    category TEXT,
    artifact_name TEXT,                 -- enlace opcional al artefacto ponderado
    state TEXT NOT NULL DEFAULT 'BACKLOG',
    lint_passed INTEGER NOT NULL DEFAULT 0,
    canary_passed INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    promotion_score REAL NOT NULL DEFAULT 0.0,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kanban_state ON kanban_tasks(state);
"""


class KanbanBoard:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_KANBAN_DDL)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ ponderación
    @staticmethod
    def _score(lint_passed: bool, canary_passed: bool, success_rate: float, execution_count: int) -> float:
        """ Pondera un artefacto en [0,1]. Linters y estados (canary) pesan tanto como el
        éxito histórico: es lo que permite confiar en un artefacto ANTES de reutilizarlo."""
        exec_factor = min(1.0, math.log1p(max(0, execution_count)) / math.log(11))  # satura ~10 ejecuciones
        return round(
            0.30 * (1.0 if lint_passed else 0.0)
            + 0.30 * (1.0 if canary_passed else 0.0)
            + 0.30 * max(0.0, min(1.0, success_rate))
            + 0.10 * exec_factor,
            4,
        )

    def _artifact_stats(self, conn: sqlite3.Connection, name: Optional[str]) -> Dict[str, Any]:
        if not name:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False}
        row = conn.execute(
            "SELECT success_rate, execution_count FROM artifacts WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False}
        return {"success_rate": row["success_rate"], "execution_count": row["execution_count"], "exists": True}

    # ------------------------------------------------------------------ operaciones
    def create_task(self, title: str, intent: str = "", category: str = "",
                    artifact_name: Optional[str] = None) -> Dict[str, Any]:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO kanban_tasks (title, intent, category, artifact_name, state) "
                "VALUES (?, ?, ?, ?, 'BACKLOG')",
                (title, intent, category, artifact_name),
            )
            conn.commit()
            return {"status": "OK", "task_id": cur.lastrowid, "state": "BACKLOG"}

    def advance(self, task_id: int, to_state: str, lint_passed: Optional[bool] = None,
                canary_passed: Optional[bool] = None, note: Optional[str] = None) -> Dict[str, Any]:
        to_state = to_state.upper()
        if to_state not in STATES:
            return {"status": "ERROR", "error": f"estado inválido: {to_state}", "valid": STATES}
        with self._conn() as conn:
            t = conn.execute("SELECT * FROM kanban_tasks WHERE id = ?", (task_id,)).fetchone()
            if not t:
                return {"status": "ERROR", "error": f"task {task_id} no existe"}
            lp = t["lint_passed"] if lint_passed is None else int(lint_passed)
            cp = t["canary_passed"] if canary_passed is None else int(canary_passed)
            stats = self._artifact_stats(conn, t["artifact_name"])
            score = self._score(bool(lp), bool(cp), stats["success_rate"], stats["execution_count"])
            conn.execute(
                "UPDATE kanban_tasks SET state=?, lint_passed=?, canary_passed=?, "
                "promotion_score=?, attempts=attempts+1, note=COALESCE(?,note), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (to_state, lp, cp, score, note, task_id),
            )
            conn.commit()
            return {"status": "OK", "task_id": task_id, "state": to_state,
                    "promotion_score": score, "eligible_for_promotion": score >= PROMOTION_THRESHOLD and bool(lp) and bool(cp)}

    def promote(self, task_id: int) -> Dict[str, Any]:
        """Promueve el artefacto ligado como REUTILIZABLE si su ponderación lo amerita."""
        with self._conn() as conn:
            t = conn.execute("SELECT * FROM kanban_tasks WHERE id = ?", (task_id,)).fetchone()
            if not t:
                return {"status": "ERROR", "error": f"task {task_id} no existe"}
            stats = self._artifact_stats(conn, t["artifact_name"])
            score = self._score(bool(t["lint_passed"]), bool(t["canary_passed"]),
                                 stats["success_rate"], stats["execution_count"])
            if not (bool(t["lint_passed"]) and bool(t["canary_passed"]) and score >= PROMOTION_THRESHOLD):
                conn.execute("UPDATE kanban_tasks SET promotion_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (score, task_id))
                conn.commit()
                return {"status": "REJECTED", "reason": "ponderación insuficiente",
                        "promotion_score": score, "threshold": PROMOTION_THRESHOLD,
                        "needs": {"lint_passed": True, "canary_passed": True, "score_min": PROMOTION_THRESHOLD}}
            conn.execute("UPDATE kanban_tasks SET state='PROMOTED', promotion_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (score, task_id))
            if stats["exists"]:
                # Marca el artefacto como reutilizable y guarda su ponderación.
                conn.execute("UPDATE artifacts SET reusable=1, promotion_score=? WHERE name=?", (score, t["artifact_name"]))
            conn.commit()
            return {"status": "PROMOTED", "artifact_name": t["artifact_name"], "promotion_score": score}

    def board(self) -> Dict[str, Any]:
        """Vista del tablero agrupada por lane/estado (idioma agéntico, JSON tipado)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, state, artifact_name, lint_passed, canary_passed, "
                "promotion_score, attempts FROM kanban_tasks ORDER BY updated_at DESC"
            ).fetchall()
        lanes: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STATES}
        for r in rows:
            lanes[r["state"]].append({
                "task_id": r["id"], "title": r["title"], "artifact": r["artifact_name"],
                "lint": bool(r["lint_passed"]), "canary": bool(r["canary_passed"]),
                "score": r["promotion_score"], "attempts": r["attempts"],
            })
        return {"status": "OK", "threshold": PROMOTION_THRESHOLD,
                "counts": {s: len(lanes[s]) for s in STATES}, "lanes": lanes}
