"""
Engine: playbook.py — Pico-Playbooks: automatización por orquestación de tools/artefactos.

Completa la tríada Pico con la pieza que faltaba: pasar de CREAR artefactos a AUTOMATIZAR
flujos. Un playbook es una secuencia/DAG nombrada de pasos, cada uno invocando un tool o
artefacto ya existente, validada por topos_guard (cero co-dependencias) y ejecutable de un
tiro. Habilita, p.ej., un E2E que combine sondas Go (socket-monitor) + visual_inspect (GUI).

Este módulo SOLO almacena y valida/ordena el DAG. NO ejecuta ni importa server.py (evita
co-dependencia Topos): el ejecutor vive en server.py, que es quien tiene los tools. Relación:
playbook.py -> artifacts.db (A->B) y playbook.py -> topos_guard (A->B). Sin ciclos.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.topos_guard import ToposGuard, ToposVerdict

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

_PLAYBOOK_DDL = """
CREATE TABLE IF NOT EXISTS playbooks (
    name TEXT PRIMARY KEY,
    description TEXT,
    steps_json TEXT NOT NULL,            -- JSON: [{id, tool, params, depends_on}]
    run_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    last_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class PlaybookStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_PLAYBOOK_DDL)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")  # comparte artifacts.db (WAL)
        except Exception:
            pass
        return conn

    # ------------------------------------------------------------------ validación DAG
    @staticmethod
    def _normalize(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        norm = []
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or "tool" not in s:
                raise ValueError(f"paso {i} inválido: falta 'tool'")
            norm.append({
                "id": str(s.get("id") or f"s{i+1}"),
                "tool": str(s["tool"]),
                "params": s.get("params") or {},
                "depends_on": [str(d) for d in (s.get("depends_on") or [])],
            })
        ids = [s["id"] for s in norm]
        if len(ids) != len(set(ids)):
            raise ValueError("ids de paso duplicados")
        return norm

    @classmethod
    def validate_and_order(cls, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Valida el DAG con topos_guard y devuelve el orden topológico de ejecución."""
        norm = cls._normalize(steps)
        ids = [s["id"] for s in norm]
        deps = {s["id"]: [d for d in s["depends_on"] if d in ids] for s in norm}
        verdict, logs = ToposGuard.audit_task_dag(ids, deps)
        if verdict != ToposVerdict.APPROVED:
            return {"ok": False, "verdict": verdict, "logs": logs}
        # Topo-sort (Kahn) sobre deps: un paso corre tras sus depends_on.
        indeg = {i: 0 for i in ids}
        adj: Dict[str, List[str]] = {i: [] for i in ids}
        for sid, dlist in deps.items():
            for d in dlist:
                adj[d].append(sid)
                indeg[sid] += 1
        queue = [i for i in ids if indeg[i] == 0]
        order: List[str] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        if len(order) != len(ids):
            return {"ok": False, "verdict": "BLOCKED", "logs": ["orden topológico incompleto (ciclo)"]}
        by_id = {s["id"]: s for s in norm}
        return {"ok": True, "verdict": verdict, "order": order,
                "ordered_steps": [by_id[i] for i in order], "steps": norm}

    # ------------------------------------------------------------------ operaciones
    def create(self, name: str, description: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            v = self.validate_and_order(steps)
        except ValueError as e:
            return {"status": "ERROR", "error": str(e)}
        if not v["ok"]:
            return {"status": "BLOCKED", "verdict": v["verdict"], "logs": v["logs"]}
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO playbooks (name, description, steps_json) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
                "steps_json=excluded.steps_json, updated_at=CURRENT_TIMESTAMP",
                (name, description, json.dumps(v["steps"])),
            )
            conn.commit()
        return {"status": "OK", "name": name, "verdict": v["verdict"],
                "order": v["order"], "steps": len(v["steps"])}

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM playbooks WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = json.loads(d.pop("steps_json"))
        return d

    def list(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, description, run_count, success_count, last_status, "
                "json_array_length(steps_json) AS n_steps FROM playbooks ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def record_run(self, name: str, ok: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE playbooks SET run_count=run_count+1, "
                "success_count=success_count + ?, last_status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE name=?",
                (1 if ok else 0, "SUCCESS" if ok else "FAILED", name),
            )
            conn.commit()
