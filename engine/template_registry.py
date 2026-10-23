"""
Engine: template_registry.py — Tabla descriptiva de plantillas + selector de plantilla.

Responde "¿qué plantilla para mi caso de uso?": una tabla descriptiva amplia
(capacidad/categoría/tags/descripción/params) y un SELECTOR que rankea por relevancia usando el
motor de emparejamiento COMPARTIDO (engine/matcher.py, RE de skill-swarm). Agnóstico a la BD:
matchea en memoria sobre metadatos, siempre disponible.

Topos: template_registry.py -> matcher.py (A->B). Sin ciclos.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine import matcher

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "templates" / "registry.json"


class TemplateRegistry:
    def __init__(self, registry_path: Optional[Path] = None):
        self.path = registry_path or REGISTRY_PATH
        self.templates: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.templates = data.get("templates", [])
        except Exception:
            self.templates = []

    def catalog(self, feedback: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """La tabla amplia para que el agente elija al momento."""
        fb = feedback or {}
        default_proven = {
            "artifacts_built": 0, "reusable_count": 0, "total_executions": 0,
            "effective": 0.0, "verdict": "UNPROVEN", "confidence": 0.0,
        }
        return [
            {"name": t["name"], "category": t.get("category"), "capability": t.get("capability"),
             "tags": t.get("tags", []), "description": t.get("description", ""),
             "params": t.get("params", []), "source": t.get("source"),
             "proven": fb.get(t["name"], dict(default_proven))}
            for t in self.templates
        ]

    def select(self, intent: str, limit: int = 5, feedback: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Rankea plantillas por relevancia al caso de uso (vía matcher compartido)."""
        fb = feedback or {}
        default_proven = {
            "artifacts_built": 0, "reusable_count": 0, "total_executions": 0,
            "effective": 0.0, "verdict": "UNPROVEN", "confidence": 0.0,
        }
        docs = [
            {"name": t["name"], "tags": t.get("tags", []), "description": t.get("description", ""),
             "category": t.get("category"), "capability": t.get("capability"),
             "params": t.get("params", []), "source": t.get("source")}
            for t in self.templates
        ]
        ranked = matcher.rank(intent, docs, limit=limit)
        return [
            {"name": r["name"], "category": r.get("category"), "capability": r.get("capability"),
             "relevance": r["relevance"], "why": r["why"], "description": r.get("description", ""),
             "params": r.get("params", []), "source": r.get("source"),
             "proven": fb.get(r["name"], dict(default_proven))}
            for r in ranked
        ]

    def redundancy(self, tag_overlap: float = 0.6) -> List[Dict[str, Any]]:
        """Detecta pares de plantillas con alto solape de tags (candidatas a convivir en una)."""
        out = []
        ts = self.templates
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a = set(x.lower() for x in ts[i].get("tags", []))
                b = set(x.lower() for x in ts[j].get("tags", []))
                if not a or not b:
                    continue
                jac = len(a & b) / len(a | b)
                if jac >= tag_overlap:
                    out.append({"pair": [ts[i]["name"], ts[j]["name"]],
                                "tag_jaccard": round(jac, 3),
                                "hint": "Alto solape: evaluar fusionar en una sola plantilla."})
        return out
