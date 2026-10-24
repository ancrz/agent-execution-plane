"""
Engine: catalog.py
Description: Gestor del Catálogo de Artefactos de AEP (SQLite + Memoria Evolutiva).

Memoria híbrida en 2 tiers:
  - Tier 1 (exacto, O(1)): hash SHA-256 de la intención -> B-Tree.
  - Tier 2 (semántico): KNN coseno sobre sqlite-vec (vec0) con embeddings locales de 384-dim.

Ambos tiers son FAIL-SOFT: si sqlite-vec o el embedder no están disponibles, el catálogo
opera idénticamente al comportamiento previo (solo hash), sin romper ninguna llamada.

Relación Topos: catalog.py -> embedder.py es dependencia unidireccional (A -> B). Sin ciclos.
"""

import hashlib
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from engine import ponder
from engine.db import (
    get_db_telemetry,
    get_ro_connection,
    get_rw_connection,
    transaction_immediate,
)
from engine.embedder import EMBEDDING_DIM, get_instance

logger = logging.getLogger("aep.catalog")

# Import fail-soft de sqlite-vec (extensión vectorial). Si falta, el tier semántico se desactiva.
try:
    import sqlite_vec
except (ImportError, OSError) as e:  # pragma: no cover
    logger.debug("sqlite_vec import failed: %s", e)
    sqlite_vec = None

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"

# Umbral de distancia coseno calibrado empíricamente para bge-small-en-v1.5:
# paráfrasis del mismo intent ~0.28-0.30; intents distintos >= 0.36. 0.32 deja margen.
DEFAULT_SEMANTIC_THRESHOLD = 0.32


class ArtifactCatalog:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Estado de disponibilidad del tier vectorial: se fija UNA vez en _init_db y
        # es de solo-lectura después (fix Ontos HF-2: _get_connection no lo reescribe).
        self._vec_available = False
        self._init_db()

    # ------------------------------------------------------------------ conexión
    def _get_ro_conn(self) -> sqlite3.Connection:
        """Obtiene conexion estandarizada de solo lectura (mode=ro)."""
        return get_ro_connection(self.db_path, row_factory=True, load_vec=True)

    def _get_rw_conn(self) -> sqlite3.Connection:
        """Obtiene conexion estandarizada de lectura/escritura con isolation_level=None."""
        return get_rw_connection(self.db_path, row_factory=True, load_vec=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Obtiene conexión estandarizada con mmap de 256MB, caché de 64MB y sqlite-vec."""
        return self._get_rw_conn()

    def storage_telemetry(self) -> dict[str, Any]:
        """Telemetría del motor de almacenamiento SQLite (mmap, caché, WAL)."""
        try:
            with self._get_ro_conn() as conn:
                return get_db_telemetry(conn)
        except (sqlite3.Error, OSError) as e:
            logger.debug("Failed to retrieve storage telemetry: %s", e)
            return {"status": "ERROR", "error": str(e)}

    # ------------------------------------------------------------------ init/migración
    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "database.sql"
        with self._get_rw_conn() as conn:
            with transaction_immediate(conn):
                if schema_path.exists():
                    conn.executescript(schema_path.read_text())
                else:
                    conn.executescript(_FALLBACK_SCHEMA)
                self._migrate(conn)
                # Disponibilidad del tier vectorial: decidida UNA sola vez aquí (fix CF-2).
                self._vec_available = self._init_vec_table(conn)
            # WAL: persistente a nivel-archivo (lo heredan todas las conexiones: crash_router,
            # kanban, aep-sync). Permite lecturas concurrentes del agente mientras se escribe.
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA optimize")  # refresca estadísticas del planner
            except sqlite3.Error as e:
                logger.debug("Failed setting journal_mode or optimize: %s", e)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Migración idempotente en código (evita archivos SQL frágiles bajo set -e)."""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(artifacts)")}
        if "intent_description" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN intent_description TEXT NOT NULL DEFAULT ''")
        if "reusable" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN reusable INTEGER NOT NULL DEFAULT 1")
        if "promotion_score" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN promotion_score REAL NOT NULL DEFAULT 0.0")
        if "source_template" not in cols:
            conn.execute("ALTER TABLE artifacts ADD COLUMN source_template TEXT NOT NULL DEFAULT ''")

    def _init_vec_table(self, conn: sqlite3.Connection) -> bool:
        """Crea la tabla virtual vec0 una sola vez. Devuelve True si el tier vectorial sirve."""
        if sqlite_vec is None:
            return False
        try:
            conn.execute("SELECT vec_version()").fetchone()  # confirma extensión cargada
            # La dimensión es parte de la DDL del tipo de vec0 y NO puede ir como parámetro
            # ligado. `dim` se fuerza a int desde una constante interna del módulo, por lo que
            # no existe superficie de inyección (no hay entrada de usuario en esta cadena).
            dim = int(EMBEDDING_DIM)
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_artifacts USING vec0("
                f"artifact_id TEXT PRIMARY KEY, intent_embedding float[{dim}] distance_metric=cosine)"
            )
            return True
        except sqlite3.Error as e:
            logger.debug("Failed to create vec_artifacts virtual table: %s", e)
            return False

    # ------------------------------------------------------------------ hashing
    @staticmethod
    def compute_intent_hash(intent: str, category: str) -> str:
        payload = f"{category.strip().lower()}::{intent.strip().lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------ tier 1: hash exacto
    def find_by_intent(self, intent: str, category: str) -> dict[str, Any] | None:
        intent_hash = self.compute_intent_hash(intent, category)
        with self._get_ro_conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE intent_hash = ? AND success_rate >= 0.85 "
                "ORDER BY success_rate DESC, execution_count DESC LIMIT 1",
                (intent_hash,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    # ------------------------------------------------------------------ tier 2: KNN semántico
    def find_by_semantic(
        self, intent: str, category: str | None = None, threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    ) -> dict[str, Any] | None:
        if not self._vec_available or sqlite_vec is None:
            return None
        embedder = get_instance()
        if not embedder.is_available:
            return None
        vec = embedder.embed(intent)
        if vec is None:
            return None
        with self._get_ro_conn() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT a.*, v.distance AS _distance
                    FROM vec_artifacts v
                    JOIN artifacts a ON a.id = v.artifact_id
                    WHERE v.intent_embedding MATCH ? AND k = 10
                    ORDER BY v.distance
                    """,
                    (sqlite_vec.serialize_float32(vec),),
                ).fetchall()
            except sqlite3.Error as e:
                logger.debug("Failed executing KNN query in find_by_semantic: %s", e)
                return None
        # Filtro en Python: categoría + umbral + tasa de éxito (la vtable KNN no admite
        # restricciones extra fiables junto al MATCH).
        for row in rows:
            d = row["_distance"]
            if d <= threshold and (category is None or row["category"] == category) and row["success_rate"] >= 0.85:
                res = dict(row)
                res.pop("_distance", None)
                res["retrieval_mode"] = "semantic_knn"
                res["semantic_distance"] = round(float(d), 4)
                return res
        return None

    # ------------------------------------------------------------------ híbrido
    def find_hybrid(
        self, intent: str, category: str | None = None, threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    ) -> dict[str, Any] | None:
        """Tier 1 (hash exacto, O(1)) y, si falla, Tier 2 (KNN semántico)."""
        if category is not None:
            exact = self.find_by_intent(intent, category)
            if exact:
                exact["retrieval_mode"] = "exact_hash"
                exact["semantic_distance"] = None
                return exact
        return self.find_by_semantic(intent, category, threshold)

    # ------------------------------------------------------------------ registro
    def register_artifact(
        self,
        name: str,
        intent: str,
        category: str,
        cue_contract: str,
        go_source: str,
        binary_blob: bytes | None = None,
        intent_description: str = "",
        source_template: str = "",
    ) -> str:
        new_id = str(uuid.uuid4())
        intent_hash = self.compute_intent_hash(intent, category)
        binary_hash = hashlib.sha256(binary_blob).hexdigest() if binary_blob else None
        description = intent_description.strip() or intent.strip()

        with self._get_rw_conn() as conn:
            with transaction_immediate(conn):
                # RETURNING id (SQLite >= 3.35) devuelve el id REAL de la fila, tanto en
                # INSERT nuevo como en ON CONFLICT -> evita el UUID fantasma (fix Ontos CF-1).
                row = conn.execute(
                    """
                    INSERT INTO artifacts (
                        id, name, intent_hash, category, cue_contract, go_source,
                        binary_blob, binary_hash, intent_description, source_template
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        intent_hash = excluded.intent_hash,
                        category = excluded.category,
                        go_source = excluded.go_source,
                        cue_contract = excluded.cue_contract,
                        binary_blob = excluded.binary_blob,
                        binary_hash = excluded.binary_hash,
                        intent_description = excluded.intent_description,
                        source_template = CASE WHEN excluded.source_template != '' THEN excluded.source_template ELSE artifacts.source_template END,
                        version = artifacts.version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        new_id,
                        name,
                        intent_hash,
                        category,
                        cue_contract,
                        go_source,
                        binary_blob,
                        binary_hash,
                        description,
                        source_template,
                    ),
                ).fetchone()
                real_id = row["id"] if row else new_id

                # Embedding en el tier vectorial. Falla aislada: nunca rompe el registro.
                self._upsert_embedding(conn, real_id, description)
        return real_id

    def _upsert_embedding(self, conn: sqlite3.Connection, artifact_id: str, text: str) -> None:
        if not self._vec_available or sqlite_vec is None:
            return
        embedder = get_instance()
        if not embedder.is_available:
            return
        vec = embedder.embed(text)
        if vec is None:
            return
        try:
            conn.execute(
                "INSERT OR REPLACE INTO vec_artifacts (artifact_id, intent_embedding) VALUES (?, ?)",
                (artifact_id, sqlite_vec.serialize_float32(vec)),
            )
        except (sqlite3.Error, OSError) as e:
            logger.debug("Failed upserting embedding for %s: %s", artifact_id, e)

    # ------------------------------------------------------------------ métricas
    def record_execution(
        self,
        artifact_id: str,
        exit_code: int,
        latency_ms: float,
        memory_peak_kb: int | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._get_rw_conn() as conn:
            with transaction_immediate(conn):
                conn.execute(
                    """
                    INSERT INTO execution_metrics (
                        artifact_id, exit_code, latency_ms, memory_peak_kb, error_message
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (artifact_id, exit_code, latency_ms, memory_peak_kb, error_message),
                )
                stats = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        AVG(CASE WHEN exit_code = 0 THEN 1.0 ELSE 0.0 END) as success_rate,
                        AVG(latency_ms) as avg_latency
                    FROM execution_metrics WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()

                if stats and stats["total"]:
                    conn.execute(
                        """
                        UPDATE artifacts SET
                            execution_count = ?,
                            success_rate = ?,
                            avg_latency_ms = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            stats["total"],
                            round(stats["success_rate"], 3),
                            round(stats["avg_latency"], 2),
                            artifact_id,
                        ),
                    )

    def record_execution_by_name(
        self,
        name: str,
        exit_code: int,
        latency_ms: float,
        error_message: str | None = None,
    ) -> bool:
        """Registra una ejecución buscando el artefacto por nombre. Cierra el lazo de
        telemetría: alimenta success_rate/execution_count que ponderan la reutilización.
        Best-effort: si el nombre no es un artefacto catalogado, no hace nada."""
        try:
            with self._get_ro_conn() as conn:
                row = conn.execute("SELECT id FROM artifacts WHERE name = ?", (name,)).fetchone()
            if not row:
                return False
            self.record_execution(row["id"], exit_code, latency_ms, error_message=error_message)
            return True
        except (sqlite3.Error, OSError) as e:
            logger.debug("Failed recording execution by name for %s: %s", name, e)
            return False

    def list_artifacts(self, category: str | None = None) -> list[dict[str, Any]]:
        with self._get_ro_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT id, name, category, version, success_rate, execution_count, "
                    "avg_latency_ms, created_at FROM artifacts WHERE category = ? "
                    "ORDER BY execution_count DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, category, version, success_rate, execution_count, "
                    "avg_latency_ms, created_at FROM artifacts ORDER BY execution_count DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def browse(self, category: str | None = None, query: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Descubrimiento del catálogo para el agente: 'qué soluciones tengo disponibles'.
        - Con `query`: top-K semántico (embeddings auto-indexados) ordenado por cercanía.
        - Sin `query`: listado rankeado por reutilizable y ponderación (lo más confiable primero).
        Devuelve metadatos de decisión (reusable, promotion_score, éxito), no el binario.

        SQL con literales estáticos y entradas (category/limit) siempre parametrizadas (?)."""
        lim = max(1, limit)

        # Ruta semántica: top-K por similitud (si hay query + vec + embedder).
        if query and self._vec_available and sqlite_vec is not None:
            emb = get_instance()
            if emb.is_available:
                vec = emb.embed(query)
                if vec is not None:
                    with self._get_ro_conn() as conn:
                        try:
                            rows = conn.execute(
                                "SELECT a.name, a.category, a.intent_description, a.reusable, "
                                "a.promotion_score, a.success_rate, a.execution_count, a.source_template, "
                                "v.distance AS _d "
                                "FROM vec_artifacts v JOIN artifacts a ON a.id = v.artifact_id "
                                "WHERE v.intent_embedding MATCH ? AND k = ? ORDER BY v.distance",
                                (sqlite_vec.serialize_float32(vec), lim),
                            ).fetchall()
                        except sqlite3.Error as e:
                            logger.debug("Failed querying KNN in browse: %s", e)
                            rows = []
                    out = []
                    for r in rows:
                        d = dict(r)
                        if category and d.get("category") != category:
                            continue
                        d["semantic_distance"] = round(float(d.pop("_d")), 4)
                        out.append(d)
                    return out

        # Ruta relacional: ranking por confianza (reusable, score, éxito, uso).
        with self._get_ro_conn() as conn:
            if category:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                rows = conn.execute(
                    "SELECT name, category, intent_description, reusable, promotion_score, "
                    "success_rate, execution_count, source_template FROM artifacts "
                    "WHERE category = ? "
                    "ORDER BY reusable DESC, promotion_score DESC, success_rate DESC, execution_count DESC LIMIT ?",
                    (category, lim),
                ).fetchall()
            else:
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                rows = conn.execute(
                    "SELECT name, category, intent_description, reusable, promotion_score, "
                    "success_rate, execution_count, source_template FROM artifacts "
                    "ORDER BY reusable DESC, promotion_score DESC, success_rate DESC, execution_count DESC LIMIT ?",
                    (lim,),
                ).fetchall()
        return [dict(r) for r in rows]

    def prune(self, protect: set | None = None, apply: bool = False) -> dict[str, Any]:
        """Poda destructiva SEGURA de artefactos que perdieron la confianza.

        Candidato = reusable=0 (ya degradado por reevaluate = fallo DEMOSTRADO) y NO protegido.
        Los single-use exitosos quedan reusable=1 -> jamás son candidatos. Las plantillas base
        (protect) nunca se podan: son contexto semilla. `apply=False` -> dry-run para juzgar
        contra el ponderador antes de destruir; `apply=True` -> borra (artefacto + vector + binario)."""
        protect = set(protect or set())
        bin_dir = Path.home() / ".local" / "share" / "agent-os" / "bin"
        with self._get_ro_conn() as conn:
            rows = conn.execute(
                "SELECT id, name, success_rate, execution_count, promotion_score FROM artifacts WHERE reusable = 0"
            ).fetchall()
            candidates = [dict(r) for r in rows if r["name"] not in protect]
            if not apply:
                return {
                    "status": "DRY_RUN",
                    "count": len(candidates),
                    "candidates": candidates,
                    "protected": sorted(protect),
                    "note": "Revisa (tú vs el ponderador). Aplica con apply=True para destruir.",
                }

        removed = []
        with self._get_rw_conn() as conn:
            with transaction_immediate(conn):
                for c in candidates:
                    conn.execute("DELETE FROM artifacts WHERE id = ?", (c["id"],))
                    try:
                        conn.execute("DELETE FROM vec_artifacts WHERE artifact_id = ?", (c["id"],))
                    except sqlite3.Error as e:
                        logger.debug("Failed deleting vec_artifacts for %s: %s", c["id"], e)
                    try:
                        (bin_dir / c["name"]).unlink(missing_ok=True)
                    except OSError as e:
                        logger.debug("Failed unlinking binary for %s: %s", c["name"], e)
                    removed.append(c["name"])
        return {
            "status": "PRUNED",
            "count": len(removed),
            "removed": removed,
            "protected": sorted(protect),
        }

    def index_coverage(self) -> dict[str, Any]:
        """Cobertura del índice semántico: cuántos artefactos tienen embedding en vec."""
        if not self._vec_available or sqlite_vec is None:
            return {"vec_available": False, "artifacts": 0, "indexed": 0, "missing": 0}
        with self._get_ro_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            try:
                indexed = conn.execute("SELECT COUNT(*) FROM vec_artifacts").fetchone()[0]
            except sqlite3.Error as e:
                logger.debug("Failed counting vec_artifacts: %s", e)
                indexed = 0
        return {
            "vec_available": True,
            "artifacts": total,
            "indexed": indexed,
            "missing": max(0, total - indexed),
        }

    def reindex(self, force: bool = False) -> dict[str, Any]:
        """Auto-sanado del índice semántico: embebe toda fila sin embedding (o TODAS si force).
        Hace buscable lo que otros agentes/vías registraron sin indexar. Fail-soft. El embedder
        solo se carga si hay trabajo pendiente (no penaliza el arranque ni el hook pre-commit)."""
        if not self._vec_available or sqlite_vec is None:
            return {"status": "DEGRADED", "reason": "sqlite-vec no disponible", "indexed": 0}
        with self._get_ro_conn() as conn:
            rows = conn.execute("SELECT id, name, intent_description FROM artifacts").fetchall()
            have = set()
            if not force:
                try:
                    have = {r["artifact_id"] for r in conn.execute("SELECT artifact_id FROM vec_artifacts")}
                except sqlite3.Error as e:
                    logger.debug("Failed fetching vec_artifacts in reindex: %s", e)
                    have = set()
            pending = [r for r in rows if force or r["id"] not in have]
            if not pending:
                return {
                    "status": "OK",
                    "indexed": 0,
                    "skipped": len(rows),
                    "total": len(rows),
                    "note": "índice ya completo",
                    "db_telemetry": self.storage_telemetry(),
                }

        embedder = get_instance()  # solo se carga el modelo si hay trabajo real
        if not embedder.is_available:
            return {"status": "DEGRADED", "reason": "embedder no disponible", "indexed": 0}

        indexed = 0
        with self._get_rw_conn() as conn:
            with transaction_immediate(conn):
                for r in pending:
                    text = (r["intent_description"] or "").strip() or r["name"]
                    vec = embedder.embed(text)
                    if vec is None:
                        continue
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO vec_artifacts (artifact_id, intent_embedding) VALUES (?, ?)",
                            (r["id"], sqlite_vec.serialize_float32(vec)),
                        )
                        indexed += 1
                    except (sqlite3.Error, OSError) as e:
                        logger.debug("Failed inserting vec_artifacts for %s: %s", r["id"], e)

        return {
            "status": "OK",
            "indexed": indexed,
            "skipped": len(rows) - len(pending),
            "total": len(rows),
            "db_telemetry": self.storage_telemetry(),
        }

    def get_binary_blob(self, name: str) -> bytes | None:
        """Recupera el blob binario compilado de un artefacto desde SQLite por nombre."""
        try:
            with self._get_ro_conn() as conn:
                row = conn.execute("SELECT binary_blob FROM artifacts WHERE name = ?", (name,)).fetchone()
                if row and row["binary_blob"]:
                    return bytes(row["binary_blob"])
        except (sqlite3.Error, OSError) as e:
            logger.debug("Failed retrieving binary blob for %s: %s", name, e)
        return None

    def template_feedback(self, template_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """Calcula telemetría y confianza agregada (Pico-Ponder) para plantillas según
        el comportamiento histórico de los artefactos derivados de ellas."""
        known_names = set(template_names or [])
        groups: dict[str, list[dict[str, Any]]] = {}
        with self._get_ro_conn() as conn:
            rows = conn.execute(
                "SELECT name, source_template, reusable, promotion_score, "
                "success_rate, execution_count, updated_at FROM artifacts"
            ).fetchall()

        for r in rows:
            d = dict(r)
            st = (d.get("source_template") or "").strip()
            if not st:
                candidate = d["name"].replace("_", "-")
                if candidate in known_names:
                    st = candidate
                elif candidate in {"socket-monitor", "fd-rescuer", "disk-usage", "mem-stat"}:
                    st = candidate
            if st:
                groups.setdefault(st, []).append(d)

        out: dict[str, dict[str, Any]] = {}
        target_keys = set(template_names) if template_names is not None else set(groups.keys())

        for tpl in target_keys:
            group = groups.get(tpl, [])
            if not group:
                out[tpl] = {
                    "artifacts_built": 0,
                    "reusable_count": 0,
                    "total_executions": 0,
                    "effective": 0.0,
                    "verdict": "UNPROVEN",
                    "confidence": 0.0,
                }
                continue

            artifacts_built = len(group)
            reusable_count = sum(1 for a in group if a.get("reusable") == 1)
            total_executions = sum(int(a.get("execution_count") or 0) for a in group)

            dims: dict[str, float] = {
                "quality": reusable_count / artifacts_built,
            }
            veto = False
            if total_executions > 0:
                weighted_sr = sum(float(a.get("success_rate", 1.0)) * int(a.get("execution_count") or 0) for a in group)
                avg_sr = weighted_sr / total_executions
                dims["reliability"] = max(0.0, min(1.0, avg_sr))
                dims["experience"] = ponder.log_norm(total_executions, 10)
                veto = avg_sr < 0.70

            recencies = [ponder.recency_decay(ponder.days_since(a.get("updated_at"))) for a in group]
            dims["recency"] = max(recencies) if recencies else 1.0

            p = ponder.finalize(dims, reliability_veto=veto)
            out[tpl] = {
                "artifacts_built": artifacts_built,
                "reusable_count": reusable_count,
                "total_executions": total_executions,
                "effective": p["effective"],
                "verdict": p["verdict"],
                "confidence": p["confidence"],
            }

        return out


_FALLBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    intent_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    cue_contract TEXT NOT NULL,
    go_source TEXT NOT NULL,
    binary_blob BLOB,
    binary_hash TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    success_rate REAL NOT NULL DEFAULT 1.0,
    execution_count INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms REAL NOT NULL DEFAULT 0.0,
    intent_description TEXT NOT NULL DEFAULT '',
    source_template TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS execution_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    exit_code INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    memory_peak_kb INTEGER,
    error_message TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
);
"""
