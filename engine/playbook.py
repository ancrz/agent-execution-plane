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

from engine import ponder  # motor de ponderación COMPARTIDO (misma vara que los artefactos)
from engine.topos_guard import ToposGuard, ToposVerdict

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

_PLAYBOOK_DDL = """
CREATE TABLE IF NOT EXISTS playbooks (
    name TEXT PRIMARY KEY,
    description TEXT,
    steps_json TEXT NOT NULL,            -- JSON: [{id, tool, params, depends_on}] (puede tener ${var})
    params_contract TEXT NOT NULL DEFAULT '[]',  -- JSON: [{name, type?, required?, default?}]
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
            # Migración idempotente: añade params_contract a DBs de playbooks previas.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(playbooks)")}
            if "params_contract" not in cols:
                conn.execute("ALTER TABLE playbooks ADD COLUMN params_contract TEXT NOT NULL DEFAULT '[]'")
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
    def create(self, name: str, description: str, steps: List[Dict[str, Any]],
               params_contract: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        try:
            v = self.validate_and_order(steps)
        except ValueError as e:
            return {"status": "ERROR", "error": str(e)}
        if not v["ok"]:
            return {"status": "BLOCKED", "verdict": v["verdict"], "logs": v["logs"]}
        contract = params_contract or []
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO playbooks (name, description, steps_json, params_contract) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
                "steps_json=excluded.steps_json, params_contract=excluded.params_contract, "
                "updated_at=CURRENT_TIMESTAMP",
                (name, description, json.dumps(v["steps"]), json.dumps(contract)),
            )
            conn.commit()
        return {"status": "OK", "name": name, "verdict": v["verdict"],
                "order": v["order"], "steps": len(v["steps"]),
                "params": [c.get("name") for c in contract]}

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM playbooks WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = json.loads(d.pop("steps_json"))
        try:
            d["params_contract"] = json.loads(d.get("params_contract") or "[]")
        except Exception:
            d["params_contract"] = []
        return d

    @staticmethod
    def _weighting(run_count: int, success_count: int, updated_at: Any) -> Dict[str, Any]:
        """Ponderación de un playbook con el MISMO motor multidimensional que los artefactos.
        quality=1.0 (validado por construcción: DAG+lint en create); reliability/experience solo
        con historial de corridas; recency por última actualización; veto si éxito<0.70."""
        dims: Dict[str, float] = {"quality": 1.0}
        if run_count > 0:
            sr = success_count / run_count
            dims["reliability"] = max(0.0, min(1.0, sr))
            dims["experience"] = ponder.log_norm(run_count, 10)
        else:
            sr = 1.0
        dims["recency"] = ponder.recency_decay(ponder.days_since(updated_at))
        veto = run_count > 0 and sr < 0.70
        return ponder.finalize(dims, reliability_veto=veto)

    def list(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, description, run_count, success_count, last_status, updated_at, "
                "json_array_length(steps_json) AS n_steps FROM playbooks ORDER BY updated_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            w = self._weighting(r["run_count"], r["success_count"], r["updated_at"])
            d["weighting"] = {"effective": w["effective"], "verdict": w["verdict"],
                              "confidence": w["confidence"]}
            out.append(d)
        # Ordena por ponderación (mejor primero), como el catálogo de artefactos.
        out.sort(key=lambda x: x["weighting"]["effective"], reverse=True)
        return out

    def record_run(self, name: str, ok: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE playbooks SET run_count=run_count+1, "
                "success_count=success_count + ?, last_status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE name=?",
                (1 if ok else 0, "SUCCESS" if ok else "FAILED", name),
            )
            conn.commit()

    def prune(self, names: Optional[List[str]] = None, apply: bool = False) -> Dict[str, Any]:
        """Poda destructiva SEGURA de playbooks con fallo demostrado o explícitamente indicados.

        Candidatos = playbooks con demonstrated failure (run_count > 0 y success_rate < 0.70)
        O explícitamente listados en `names`.
        Playbooks con success_rate >= 0.70 (y los de run_count == 0 salvo en names) JAMÁS
        se podan por antigüedad (inmunes al decaimiento por recency).
        apply=False (default) -> DRY_RUN; apply=True -> borra de SQLite."""
        target_names = set(names) if names else None
        candidates = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, description, run_count, success_count, updated_at FROM playbooks"
            ).fetchall()
            for r in rows:
                name = r["name"]
                rc = r["run_count"]
                sc = r["success_count"]
                failed = rc > 0 and (sc / rc) < 0.70
                explicit = target_names is not None and name in target_names
                if failed or explicit:
                    candidates.append({
                        "name": name,
                        "run_count": rc,
                        "success_count": sc,
                        "success_rate": round(sc / rc, 2) if rc > 0 else 0.0,
                        "reason": "FAILED" if failed else "EXPLICIT_NAME",
                    })

            if not apply:
                return {
                    "status": "DRY_RUN",
                    "count": len(candidates),
                    "candidates": candidates,
                    "note": "Revisa candidatos. Aplica con apply=True para eliminar de SQLite.",
                }

            removed = []
            for c in candidates:
                conn.execute("DELETE FROM playbooks WHERE name = ?", (c["name"],))
                removed.append(c["name"])
            conn.commit()
            return {"status": "PRUNED", "count": len(removed), "removed": removed}
