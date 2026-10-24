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

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine import ponder  # motor de ponderación multidimensional COMPARTIDO (artefactos + playbooks)

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

STATES = ["BACKLOG", "SYNTHESIZED", "LINTED", "CANARY", "PROMOTED", "REJECTED"]
PROMOTION_THRESHOLD = ponder.TRUST_BAND  # umbral de promoción (compat)

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
    archived INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kanban_state ON kanban_tasks(state);
CREATE INDEX IF NOT EXISTS idx_kanban_archived ON kanban_tasks(archived);
"""


class KanbanBoard:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_KANBAN_DDL)
            self._migrate(conn)
            conn.commit()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Migración in-code aditiva (idempotente): columnas nuevas sobre tableros ya existentes."""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(kanban_tasks)").fetchall()}
        if "archived" not in cols:
            conn.execute("ALTER TABLE kanban_tasks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kanban_archived ON kanban_tasks(archived)")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")  # comparte artifacts.db (WAL) sin locks
        except Exception:
            pass
        return conn

    # ------------------------------------------------------------------ ponderación (motor compartido)
    @staticmethod
    def _ponder(lint_passed: bool, canary_passed: bool, success_rate: float,
                execution_count: int, days_since_update: float) -> Dict[str, Any]:
        """Dimensiones ESPECÍFICAS de artefacto -> motor compartido ponder.finalize().
        reliability/experience solo con señal real (canary o ejecución); si no, se omiten
        (bajan confianza). Veto de fiabilidad: éxito<0.70 con historial impide TRUST."""
        dims: Dict[str, float] = {}
        dims["quality"] = 0.5 * (1.0 if lint_passed else 0.0) + 0.5 * (1.0 if canary_passed else 0.0)
        if execution_count > 0 or canary_passed:
            dims["reliability"] = max(0.0, min(1.0, success_rate))
            dims["experience"] = max(ponder.log_norm(execution_count, 10), 0.5 if canary_passed else 0.0)
        dims["recency"] = ponder.recency_decay(days_since_update)
        veto = execution_count > 0 and success_rate < 0.70
        return ponder.finalize(dims, reliability_veto=veto)

    def _artifact_stats(self, conn: sqlite3.Connection, name: Optional[str]) -> Dict[str, Any]:
        if not name:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False, "days_since": 0.0}
        row = conn.execute(
            "SELECT success_rate, execution_count, updated_at FROM artifacts WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return {"success_rate": 1.0, "execution_count": 0, "exists": False, "days_since": 0.0}
        return {"success_rate": row["success_rate"], "execution_count": row["execution_count"],
                "exists": True, "days_since": ponder.days_since(row["updated_at"])}

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
                        "dimensions": p["dimensions"], "threshold": ponder.TRUST_BAND,
                        "hint": "Sube confianza: ejecuta el artefacto (historial de éxito) o valida un canary."}
            conn.execute("UPDATE kanban_tasks SET state='PROMOTED', promotion_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (score, task_id))
            if stats["exists"]:
                # Marca el artefacto como reutilizable y guarda su ponderación.
                conn.execute("UPDATE artifacts SET reusable=1, promotion_score=? WHERE name=?", (score, t["artifact_name"]))
            conn.commit()
            return {"status": "PROMOTED", "artifact_name": t["artifact_name"],
                    "promotion_score": score, "confidence": p["confidence"],
                    "verdict": p["verdict"], "dimensions": p["dimensions"]}

    def demote(self, artifact_name: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Degrada explícitamente un artefacto (reusable=0). Inverso de promote."""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT success_rate, execution_count, updated_at FROM artifacts WHERE name=?",
                (artifact_name,),
            ).fetchone()
            if not r:
                return {"status": "ERROR", "error": f"artefacto '{artifact_name}' no existe"}
            p = self._ponder(True, True, r["success_rate"], r["execution_count"],
                             ponder.days_since(r["updated_at"]))
            conn.execute("UPDATE artifacts SET reusable=0, promotion_score=? WHERE name=?",
                         (p["effective"], artifact_name))
            conn.commit()
        return {"status": "DEMOTED", "artifact_name": artifact_name,
                "promotion_score": p["effective"], "verdict": p["verdict"], "reason": reason}

    def reevaluate(self) -> Dict[str, Any]:
        """Auto-corrección del conjunto confiable: re-pondera cada artefacto reusable=1 contra sus
        métricas ACTUALES (telemetría) y degrada (reusable=0) solo los que tienen fallo demostrado
        (éxito < 0.70) o caen a WARNING/REJECT. Los artefactos exitosos que envejecen hacia CAUTION
        conservan reusable=1 (inmunes al decaimiento por recency).
        Cierra el lazo promoción<->degradación: la confianza se gana y también se pierde."""
        demoted: List[Dict[str, Any]] = []
        kept = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, success_rate, execution_count, updated_at FROM artifacts WHERE reusable=1"
            ).fetchall()
            for r in rows:
                # Un artefacto reusable fue promovido (lint+canary pasaron); el cambio real
                # viene de su éxito histórico y frescura.
                p = self._ponder(True, True, r["success_rate"], r["execution_count"],
                                 ponder.days_since(r["updated_at"]))
                # Invariante: solo se degrada ante fallo DEMOSTRADO (éxito < 0.70 con historial)
                # o degradación severa a WARNING/REJECT. Envejecer a CAUTION con éxito >= 0.70
                # NO degrada: protege artefactos single-use exitosos del decaimiento temporal.
                should_demote = (
                    (r["execution_count"] > 0 and r["success_rate"] < 0.70)
                    or p["verdict"] in ("WARNING", "REJECT")
                )
                if should_demote:
                    conn.execute("UPDATE artifacts SET reusable=0, promotion_score=? WHERE name=?",
                                 (p["effective"], r["name"]))
                    demoted.append({"name": r["name"], "promotion_score": p["effective"],
                                    "verdict": p["verdict"], "success_rate": r["success_rate"]})
                else:
                    conn.execute("UPDATE artifacts SET promotion_score=? WHERE name=?",
                                 (p["effective"], r["name"]))
                    kept += 1
            conn.commit()
        return {"status": "OK", "reevaluated": len(demoted) + kept,
                "kept_trusted": kept, "demoted_count": len(demoted), "demoted": demoted}

    def archive(self, states: Optional[List[str]] = None, max_score: Optional[float] = None,
                protect_states: tuple = ("PROMOTED", "CANARY"), apply: bool = False) -> Dict[str, Any]:
        """Despeja el board archivando (soft, reversible) tareas estancadas.

        dry-run POR DEFECTO: el AGENTE juzga qué despejar vs el veredicto del ponderador — igual
        filosofía que artifact_prune, pero NO destruye (archived=1, recuperable con unarchive).
        Candidato = estado en `states` (def. LINTED+REJECTED) Y promotion_score < `max_score`
        (def. umbral TRUST) Y no está en `protect_states`. Las PROMOTED/CANARY nunca se tocan."""
        states = [s.upper() for s in (states or ["LINTED", "REJECTED"])]
        thr = ponder.TRUST_BAND if max_score is None else float(max_score)
        protect = {s.upper() for s in protect_states}
        states = [s for s in states if s not in protect]
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, state, artifact_name, promotion_score, attempts "
                "FROM kanban_tasks WHERE archived=0 ORDER BY id DESC"
            ).fetchall()
            candidates = [
                {"task_id": r["id"], "title": r["title"], "state": r["state"],
                 "artifact": r["artifact_name"], "score": r["promotion_score"], "attempts": r["attempts"]}
                for r in rows
                if r["state"] in states and r["state"] not in protect and r["promotion_score"] < thr
            ]
            if apply and candidates:
                ids = [c["task_id"] for c in candidates]
                conn.execute(
                    "UPDATE kanban_tasks SET archived=1, updated_at=CURRENT_TIMESTAMP "
                    f"WHERE id IN ({','.join('?' * len(ids))})", ids,
                )
                conn.commit()
        return {"status": "ARCHIVED" if apply else "DRY_RUN",
                "applied": apply, "threshold": thr, "states_scanned": states,
                "protected_states": sorted(protect), "candidate_count": len(candidates),
                "candidates": candidates,
                "hint": None if apply else "Revisa candidatos; repite con apply=True para despejar (reversible vía kanban_unarchive)."}

    def unarchive(self, task_id: int) -> Dict[str, Any]:
        """Reactiva una tarea archivada (archived=0). Inverso de archive — nada se pierde."""
        with self._conn() as conn:
            t = conn.execute("SELECT id, state FROM kanban_tasks WHERE id=?", (task_id,)).fetchone()
            if not t:
                return {"status": "ERROR", "error": f"task {task_id} no existe"}
            conn.execute("UPDATE kanban_tasks SET archived=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
            conn.commit()
        return {"status": "OK", "task_id": task_id, "state": t["state"], "archived": False}

    def board(self, include_archived: bool = False) -> Dict[str, Any]:
        """Vista del tablero agrupada por lane/estado (idioma agéntico, JSON tipado).
        Excluye archivadas por defecto; include_archived=True las muestra todas."""
        where = "" if include_archived else "WHERE archived=0"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, state, artifact_name, lint_passed, canary_passed, "
                f"promotion_score, attempts, archived FROM kanban_tasks {where} ORDER BY updated_at DESC"
            ).fetchall()
            archived_total = conn.execute(
                "SELECT COUNT(*) AS n FROM kanban_tasks WHERE archived=1"
            ).fetchone()["n"]
        lanes: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STATES}
        for r in rows:
            lanes[r["state"]].append({
                "task_id": r["id"], "title": r["title"], "artifact": r["artifact_name"],
                "lint": bool(r["lint_passed"]), "canary": bool(r["canary_passed"]),
                "score": r["promotion_score"], "attempts": r["attempts"],
                "archived": bool(r["archived"]),
            })
        return {"status": "OK", "threshold": PROMOTION_THRESHOLD,
                "counts": {s: len(lanes[s]) for s in STATES},
                "archived_total": archived_total, "lanes": lanes}
