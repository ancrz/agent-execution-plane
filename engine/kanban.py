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

# Modelo de ponderación multidimensional CONSCIENTE DE CONFIANZA, adaptado del trust engine
# de skill-swarm-mcp (dimensiones ponderadas + confidence + bandas de veredicto; a su vez
# inspirado en npms.io / OpenSSF Scorecard / SourceRank). Clave: un artefacto sin historial
# tiene baja CONFIANZA aunque su score bruto sea alto -> no se promueve a ciegas.
DIMENSION_WEIGHTS = {
    "quality": 0.35,      # linters (go vet/golangci) + canary (dry-run en RAM)
    "reliability": 0.30,  # tasa de éxito histórica
    "experience": 0.15,   # cuán battle-tested (log de ejecuciones; canary da base)
    "recency": 0.20,      # frescura: decae si el artefacto lleva tiempo sin validarse
}
TRUST_BAND = 0.75        # effective >= -> PROMOTED
CAUTION_BAND = 0.50      # effective >= -> reutilizable con reserva
WARNING_BAND = 0.25
RECENCY_HALF_LIFE_DAYS = 45
PROMOTION_THRESHOLD = TRUST_BAND  # umbral de promoción (compat)


def _log_norm(value: int, midpoint: int) -> float:
    """Normalización logarítmica: 0 en value=0, ~1.0 en value=midpoint (satura)."""
    if value <= 0:
        return 0.0
    return min(math.log10(1 + value) / math.log10(1 + midpoint), 1.0)


def _recency_decay(days: float) -> float:
    """Decaimiento exponencial: 1.0 recién validado, ~0.5 a RECENCY_HALF_LIFE_DAYS."""
    return math.exp(-math.log(2) / RECENCY_HALF_LIFE_DAYS * max(0.0, days))

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
        try:
            conn.execute("PRAGMA busy_timeout = 5000")  # comparte artifacts.db (WAL) sin locks
        except Exception:
            pass
        return conn

    # ------------------------------------------------------------------ ponderación
    @staticmethod
    def _ponder(lint_passed: bool, canary_passed: bool, success_rate: float,
                execution_count: int, days_since_update: float) -> Dict[str, Any]:
        """Ponderación multidimensional con confianza. Devuelve effective + detalle.

        Las dimensiones sin señal real (reliability/experience sin ninguna ejecución ni canary)
        se OMITEN: no suman al total Y bajan la confianza (doble penalización conservadora, como
        el trust engine de skill-swarm). effective = total_ponderado * confidence."""
        dims: Dict[str, float] = {}
        # quality: siempre conocida (sabemos el resultado de lint y canary).
        dims["quality"] = 0.5 * (1.0 if lint_passed else 0.0) + 0.5 * (1.0 if canary_passed else 0.0)
        # reliability/experience: solo con señal real (al menos un canary o una ejecución).
        if execution_count > 0 or canary_passed:
            dims["reliability"] = max(0.0, min(1.0, success_rate))
            dims["experience"] = max(_log_norm(execution_count, 10), 0.5 if canary_passed else 0.0)
        # recency: siempre conocida (sabemos cuándo se validó por última vez).
        dims["recency"] = _recency_decay(days_since_update)

        total = sum(dims[k] * DIMENSION_WEIGHTS[k] for k in dims)
        confidence = len(dims) / len(DIMENSION_WEIGHTS)
        effective = round(total * confidence, 4)
        if effective >= TRUST_BAND:
            verdict = "TRUST"
        elif effective >= CAUTION_BAND:
            verdict = "CAUTION"
        elif effective >= WARNING_BAND:
            verdict = "WARNING"
        else:
            verdict = "REJECT"
        # Veto de fiabilidad (hard rule): fallos DEMOSTRADOS vetan la promoción. Un artefacto
        # con historial y éxito < 0.70 no puede ser TRUST por mucha calidad/frescura que tenga.
        if execution_count > 0 and success_rate < 0.70 and verdict == "TRUST":
            verdict = "CAUTION"
        return {
            "effective": effective, "raw": round(total, 4), "confidence": round(confidence, 2),
            "verdict": verdict, "dimensions": {k: round(v, 3) for k, v in dims.items()},
        }

    @staticmethod
    def _days_since(ts: Optional[str]) -> float:
        if not ts:
            return 0.0
        from datetime import datetime, timezone
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(ts.split(".")[0], fmt).replace(tzinfo=timezone.utc)
                return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
            except Exception:
                continue
        return 0.0

    def _artifact_stats(self, conn: sqlite3.Connection, name: Optional[str]) -> Dict[str, Any]:
        if not name:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False, "days_since": 0.0}
        row = conn.execute(
            "SELECT success_rate, execution_count, updated_at FROM artifacts WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False, "days_since": 0.0}
        return {"success_rate": row["success_rate"], "execution_count": row["execution_count"],
                "exists": True, "days_since": self._days_since(row["updated_at"])}

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
            p = self._ponder(bool(lp), bool(cp), stats["success_rate"],
                             stats["execution_count"], stats["days_since"])
            conn.execute(
                "UPDATE kanban_tasks SET state=?, lint_passed=?, canary_passed=?, "
                "promotion_score=?, attempts=attempts+1, note=COALESCE(?,note), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (to_state, lp, cp, p["effective"], note, task_id),
            )
            conn.commit()
            return {"status": "OK", "task_id": task_id, "state": to_state,
                    "promotion_score": p["effective"], "verdict": p["verdict"],
                    "confidence": p["confidence"], "dimensions": p["dimensions"],
                    "eligible_for_promotion": p["verdict"] == "TRUST"}

    def promote(self, task_id: int) -> Dict[str, Any]:
        """Promueve el artefacto ligado como REUTILIZABLE si su ponderación lo amerita."""
        with self._conn() as conn:
            t = conn.execute("SELECT * FROM kanban_tasks WHERE id = ?", (task_id,)).fetchone()
            if not t:
                return {"status": "ERROR", "error": f"task {task_id} no existe"}
            stats = self._artifact_stats(conn, t["artifact_name"])
            p = self._ponder(bool(t["lint_passed"]), bool(t["canary_passed"]),
                             stats["success_rate"], stats["execution_count"], stats["days_since"])
            score = p["effective"]
            if p["verdict"] != "TRUST":
                conn.execute("UPDATE kanban_tasks SET promotion_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (score, task_id))
                conn.commit()
                return {"status": "REJECTED", "reason": f"confianza insuficiente (verdict={p['verdict']})",
                        "promotion_score": score, "confidence": p["confidence"],
                        "dimensions": p["dimensions"], "threshold": TRUST_BAND,
                        "hint": "Sube confianza: ejecuta el artefacto (historial de éxito) o valida un canary."}
            conn.execute("UPDATE kanban_tasks SET state='PROMOTED', promotion_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (score, task_id))
            if stats["exists"]:
                # Marca el artefacto como reutilizable y guarda su ponderación.
                conn.execute("UPDATE artifacts SET reusable=1, promotion_score=? WHERE name=?", (score, t["artifact_name"]))
            conn.commit()
            return {"status": "PROMOTED", "artifact_name": t["artifact_name"],
                    "promotion_score": score, "confidence": p["confidence"],
                    "verdict": p["verdict"], "dimensions": p["dimensions"]}

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
