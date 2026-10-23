"""
Engine: template_registry.py — Tabla descriptiva de plantillas + selector de plantilla.

Responde "¿qué plantilla para mi caso de uso?" (lo que antes no tenía respuesta): una tabla
descriptiva amplia (capacidad/categoría/tags/descripción/params) y un SELECTOR que rankea las
plantillas por relevancia.

RE-as-SDD del matcher de skill-swarm-mcp (se extrae el PATRÓN, no la librería): scoring compuesto
multi-señal — exact/prefix/phrase sobre el nombre, BM25F ponderado por campo (name×3/tags×2/desc×1),
Jaccard de tags y fuzzy (difflib, stdlib — en vez de rapidfuzz, sin dep nueva). Agnóstico a la BD:
matchea en memoria sobre metadatos, siempre disponible (deja cómoda a la IA consumidora).

Topos: módulo hoja; no importa otros módulos de AEP.
"""

import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "templates" / "registry.json"

# Pesos de señal (RE de skill-swarm; suma = 100, se normaliza).
_SIGNAL_WEIGHTS = {
    "exact_match": 30.0, "prefix_match": 20.0, "phrase_match": 15.0,
    "bm25f": 15.0, "jaccard_tags": 10.0, "fuzzy_name": 7.0, "fuzzy_desc": 3.0,
}
_TOTAL_WEIGHT = sum(_SIGNAL_WEIGHTS.values())
_FIELD_BOOSTS = {"name": 3.0, "tags": 2.0, "description": 1.0}
_BM25_K1, _BM25_B = 1.2, 0.3


def _tok(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


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

    # ------------------------------------------------------------------ tabla descriptiva
    def catalog(self) -> List[Dict[str, Any]]:
        """La tabla amplia para que el agente elija al momento."""
        return [
            {"name": t["name"], "category": t.get("category"), "capability": t.get("capability"),
             "tags": t.get("tags", []), "description": t.get("description", ""),
             "params": t.get("params", []), "source": t.get("source")}
            for t in self.templates
        ]

    # ------------------------------------------------------------------ BM25F (corpus pequeño)
    def _bm25f_prep(self):
        fields = {"name": [], "tags": [], "description": []}
        df: Dict[str, int] = {}
        for t in self.templates:
            ftok = {
                "name": _tok(t.get("name", "")),
                "tags": _tok(" ".join(t.get("tags", []))),
                "description": _tok(t.get("description", "")),
            }
            for f in fields:
                fields[f].append(ftok[f])
            for term in set(ftok["name"] + ftok["tags"] + ftok["description"]):
                df[term] = df.get(term, 0) + 1
        avgdl = {f: (sum(len(d) for d in fields[f]) / max(len(self.templates), 1)) for f in fields}
        return fields, df, avgdl

    def _bm25f_score(self, qtok, idx, fields, df, avgdl) -> float:
        n = len(self.templates)
        total = 0.0
        for term in qtok:
            if term not in df:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            wtf = 0.0
            for f, boost in _FIELD_BOOSTS.items():
                toks = fields[f][idx]
                cnt = toks.count(term)
                fl = len(toks)
                wtf += boost * cnt / (1 - _BM25_B + _BM25_B * fl / max(avgdl[f], 1.0))
            total += idf * (wtf / (_BM25_K1 + wtf))
        return total

    # ------------------------------------------------------------------ selector
    def select(self, intent: str, limit: int = 5, threshold: float = 0.03) -> List[Dict[str, Any]]:
        """Rankea plantillas por relevancia al caso de uso (scoring compuesto multi-señal)."""
        q = (intent or "").lower().strip()
        qtok = _tok(intent)
        if not qtok or not self.templates:
            return []
        qset = set(qtok)
        fields, df, avgdl = self._bm25f_prep()
        results = []
        for idx, t in enumerate(self.templates):
            name = t.get("name", "").lower()
            tags = [x.lower() for x in t.get("tags", [])]
            desc = t.get("description", "").lower()
            combined = f"{name} {' '.join(tags)} {desc}"
            tagset = set(_tok(" ".join(tags)))

            sig = {}
            sig["exact_match"] = 1.0 if q == name else 0.0
            sig["prefix_match"] = 1.0 if name.startswith(q) else (0.7 if q in name else (0.5 if name in q else 0.0))
            sig["phrase_match"] = 1.0 if q in combined else 0.0
            sig["bm25f"] = min(self._bm25f_score(qtok, idx, fields, df, avgdl) / 5.0, 1.0)
            inter = len(qset & tagset)
            union = len(qset | tagset)
            sig["jaccard_tags"] = inter / union if union else 0.0
            sig["fuzzy_name"] = SequenceMatcher(None, q, name).ratio()
            sig["fuzzy_desc"] = SequenceMatcher(None, q, desc).ratio()  # partial-ish

            score = sum(_SIGNAL_WEIGHTS[k] * sig[k] for k in _SIGNAL_WEIGHTS) / _TOTAL_WEIGHT
            if score >= threshold:
                top_signals = sorted(
                    ((k, round(v, 2)) for k, v in sig.items() if v > 0),
                    key=lambda kv: -kv[1])[:3]
                results.append({
                    "name": t["name"], "category": t.get("category"),
                    "capability": t.get("capability"), "relevance": round(score, 4),
                    "why": [k for k, _ in top_signals], "description": t.get("description", ""),
                    "params": t.get("params", []), "source": t.get("source"),
                })
        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------ redundancia
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
