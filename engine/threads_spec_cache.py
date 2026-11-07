"""
Engine: threads_spec_cache.py (E2: specs incrementales por hilo)

`autoevol(spec)` no recalcula la mini-SDD de un gap cuyos hilos no cambiaron (RE-as-SDD sin retrabajo).

Eleccion de la clave: (gap canonico, terse, hash de los hilos del objetivo). Los hilos son el nodo del gap, los nodos
de su `change` y el modulo que los contiene, cada uno con su hash Merkle de hilo (`Analysis.node_hash`, que ya incluye
sus dependencias). NO se usa la raiz R global: cualquier edicion ajena la cambiaria e invalidaria todo. Aproximacion
asumida: tests impactados/pins y el nombre canonico dependen de vecinos fuera de la clave; se refrescan cuando cambia
algun hilo propio o el gap (es un cache de "hilos sin cambios", no de grafo completo).

Almacen: tabla `threads_spec_cache` en la BD de AEP (una fila por (gap, terse)). Fail-open: si la BD no existe, no
abre o falla, se recalcula y el resultado es el mismo; el cache nunca altera el contenido de la spec.
`stale_specs` lista los gaps cuyos hilos aparecen en el diff entre dos R.

Topos: hoja (solo `engine.db`). `threads_spec.cached_spec` y `threads.diff_generations` lo consumen; no importa
`threads*` para no crear codependencia (threads <-> cache).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from engine.db import get_db_connection, get_ro_connection

log = logging.getLogger(__name__)

DDL = """CREATE TABLE IF NOT EXISTS threads_spec_cache (
        gap_canonical TEXT NOT NULL,
        terse INTEGER NOT NULL,
        key_hash TEXT NOT NULL,
        deps_json TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (gap_canonical, terse)
    )"""


def thread_hashes(analysis: Any, gap: Any, change_nodes: list[str]) -> dict[str, str]:
    """Hash de hilo por nodo de la clave: nodo del gap, nodos de `change` y sus modulos."""
    graph = analysis.graph
    merkle = getattr(analysis, "node_hash", None) or {}
    ids = list(dict.fromkeys([gap.node, *change_nodes]))
    for nid in list(ids):
        node = graph.nodes.get(nid)
        if node is not None and node.type == "function":
            ids.append(f"module:{node.attrs.get('module', '')}")
    out: dict[str, str] = {}
    for nid in dict.fromkeys(ids):
        node = graph.nodes.get(nid)
        out[nid] = str(merkle.get(nid) or (node.content_hash if node is not None else ""))
    return out


def cache_key(gap: Any, terse: bool, deps: dict[str, str]) -> str:
    h = hashlib.sha256()
    parts = (
        gap.id,
        gap.kind,
        gap.node,
        str(gap.detail),
        str(gap.ref or ""),
        "t" if terse else "s",
        json.dumps(sorted(deps.items())),
    )
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _lookup(db: Path, gap_id: str, terse: bool, key: str) -> dict[str, Any] | None:
    if not db.exists():
        return None
    try:
        conn = get_ro_connection(db)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT key_hash, spec_json FROM threads_spec_cache WHERE gap_canonical = ? AND terse = ?",
            (gap_id, int(terse)),
        ).fetchone()
        if row is None or row["key_hash"] != key:
            return None
        loaded = json.loads(row["spec_json"])
        return loaded if isinstance(loaded, dict) else None
    except sqlite3.Error, ValueError:
        return None
    finally:
        conn.close()


def _store(db: Path, gap_id: str, terse: bool, key: str, deps: dict[str, str], spec: dict[str, Any]) -> None:
    if not db.exists():  # nunca crea la BD: sin BD el cache simplemente no existe
        return
    try:
        conn = get_db_connection(db)
        try:
            conn.execute(DDL)
            conn.execute(
                "INSERT OR REPLACE INTO threads_spec_cache VALUES (?, ?, ?, ?, ?, ?)",
                (gap_id, int(terse), key, json.dumps(deps, sort_keys=True), json.dumps(spec, default=str), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error, OSError:
        log.debug("threads_spec_cache: store skipped", exc_info=True)


def stale_specs(changed: set[str], *, db_path: Path | str) -> list[str]:
    """Gaps con spec cacheada cuyos hilos (clave) intersectan `changed` (nodos cambiados/eliminados entre dos R)."""
    if not changed:
        return []
    try:
        db = Path(db_path)
        if not db.exists():
            return []
        conn = get_ro_connection(db)
    except sqlite3.Error, OSError:
        return []
    try:
        rows = conn.execute("SELECT gap_canonical, deps_json FROM threads_spec_cache ORDER BY gap_canonical").fetchall()
        return sorted({r["gap_canonical"] for r in rows if changed & set(json.loads(r["deps_json"]))})
    except sqlite3.Error, ValueError:
        return []
    finally:
        conn.close()


def cached_gap_ids(db_path: Path | str) -> set[str]:
    """E4: ids de gaps con spec cacheada (solo lectura; sin BD o con error = conjunto vacio, nunca crea la BD)."""
    try:
        db = Path(db_path)
        if not db.exists():
            return set()
        conn = get_ro_connection(db)
    except sqlite3.Error, OSError:
        return set()
    try:
        return {r["gap_canonical"] for r in conn.execute("SELECT gap_canonical FROM threads_spec_cache")}
    except sqlite3.Error:
        return set()
    finally:
        conn.close()
