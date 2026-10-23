"""
Engine: matcher.py — Motor de emparejamiento multi-señal COMPARTIDO (RE de skill-swarm).

La vara con que se decide "¿qué candidato encaja con este caso de uso?". RE-ado del matcher de
skill-swarm-mcp (BM25F + señales), implementado en stdlib puro (difflib, sin rapidfuzz). Lo usan
el selector de plantillas, el enrutador discover() y cualquier ranking por relevancia.

Señales: exact/prefix/phrase sobre el nombre + BM25F ponderado por campo (name×3/tags×2/desc×1)
+ Jaccard de tags + fuzzy (name/desc). Agnóstico al dominio: recibe docs {key,name,tags,description}.
"""

import math
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List

_SIGNAL_WEIGHTS = {
    "exact_match": 30.0, "prefix_match": 20.0, "phrase_match": 15.0,
    "bm25f": 15.0, "jaccard_tags": 10.0, "fuzzy_name": 7.0, "fuzzy_desc": 3.0,
}
_TOTAL_WEIGHT = sum(_SIGNAL_WEIGHTS.values())
_FIELD_BOOSTS = {"name": 3.0, "tags": 2.0, "description": 1.0}
_BM25_K1, _BM25_B = 1.2, 0.3


def _tok(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _bm25f_index(docs: List[Dict[str, Any]]):
    fields = {"name": [], "tags": [], "description": []}
    df: Dict[str, int] = {}
    for d in docs:
        ftok = {
            "name": _tok(d.get("name", "")),
            "tags": _tok(" ".join(d.get("tags", []) or [])),
            "description": _tok(d.get("description", "")),
        }
        for f in fields:
            fields[f].append(ftok[f])
        for term in set(ftok["name"] + ftok["tags"] + ftok["description"]):
            df[term] = df.get(term, 0) + 1
    n = max(len(docs), 1)
    avgdl = {f: sum(len(x) for x in fields[f]) / n for f in fields}
    return fields, df, avgdl


def _bm25f_score(qtok, idx, fields, df, avgdl, n) -> float:
    total = 0.0
    for term in qtok:
        if term not in df:
            continue
        idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
        wtf = 0.0
        for f, boost in _FIELD_BOOSTS.items():
            toks = fields[f][idx]
            wtf += boost * toks.count(term) / (1 - _BM25_B + _BM25_B * len(toks) / max(avgdl[f], 1.0))
        total += idf * (wtf / (_BM25_K1 + wtf))
    return total


def rank(query: str, docs: List[Dict[str, Any]], limit: int = 5,
         threshold: float = 0.03) -> List[Dict[str, Any]]:
    """Rankea `docs` por relevancia a `query`. Cada doc: {key?, name, tags?, description?, ...}.
    Devuelve los docs (tal cual) + `relevance` + `why` (señales que dispararon), ordenados."""
    q = (query or "").lower().strip()
    qtok = _tok(query)
    if not qtok or not docs:
        return []
    qset = set(qtok)
    fields, df, avgdl = _bm25f_index(docs)
    n = len(docs)
    out = []
    for idx, d in enumerate(docs):
        name = (d.get("name", "") or "").lower()
        tags = [t.lower() for t in (d.get("tags", []) or [])]
        desc = (d.get("description", "") or "").lower()
        combined = f"{name} {' '.join(tags)} {desc}"
        tagset = set(_tok(" ".join(tags)))
        sig = {
            "exact_match": 1.0 if q == name else 0.0,
            "prefix_match": 1.0 if name.startswith(q) else (0.7 if q in name else (0.5 if name and name in q else 0.0)),
            "phrase_match": 1.0 if q in combined else 0.0,
            "bm25f": min(_bm25f_score(qtok, idx, fields, df, avgdl, n) / 5.0, 1.0),
            "jaccard_tags": (len(qset & tagset) / len(qset | tagset)) if (qset | tagset) else 0.0,
            "fuzzy_name": SequenceMatcher(None, q, name).ratio(),
            "fuzzy_desc": SequenceMatcher(None, q, desc).ratio(),
        }
        score = sum(_SIGNAL_WEIGHTS[k] * sig[k] for k in _SIGNAL_WEIGHTS) / _TOTAL_WEIGHT
        if score >= threshold:
            why = [k for k, _ in sorted(((k, v) for k, v in sig.items() if v > 0),
                                        key=lambda kv: -kv[1])[:3]]
            out.append({**d, "relevance": round(score, 4), "why": why})
    out.sort(key=lambda r: r["relevance"], reverse=True)
    return out[:limit]
