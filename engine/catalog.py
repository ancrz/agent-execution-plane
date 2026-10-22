"""
Engine: catalog.py
Description: Gestor del Catálogo de Artefactos de AEP (SQLite + Memoria Evolutiva).
Permite registrar contratos CUE, código fuente Go, métricas de éxito y consultar por intent_hash.
"""

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"


class ArtifactCatalog:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "database.sql"
        with self._get_connection() as conn:
            if schema_path.exists():
                conn.executescript(schema_path.read_text())
            else:
                conn.execute("""
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.execute("""
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
                """)
            conn.commit()

    @staticmethod
    def compute_intent_hash(intent: str, category: str) -> str:
        payload = f"{category.strip().lower()}::{intent.strip().lower()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def find_by_intent(self, intent: str, category: str) -> Optional[Dict[str, Any]]:
        intent_hash = self.compute_intent_hash(intent, category)
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE intent_hash = ? AND success_rate >= 0.85 ORDER BY success_rate DESC, execution_count DESC LIMIT 1",
                (intent_hash,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def register_artifact(
        self,
        name: str,
        intent: str,
        category: str,
        cue_contract: str,
        go_source: str,
        binary_blob: Optional[bytes] = None,
    ) -> str:
        artifact_id = str(uuid.uuid4())
        intent_hash = self.compute_intent_hash(intent, category)
        binary_hash = (
            hashlib.sha256(binary_blob).hexdigest() if binary_blob else None
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, name, intent_hash, category, cue_contract, go_source, binary_blob, binary_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    go_source = excluded.go_source,
                    cue_contract = excluded.cue_contract,
                    binary_blob = excluded.binary_blob,
                    binary_hash = excluded.binary_hash,
                    version = artifacts.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    artifact_id,
                    name,
                    intent_hash,
                    category,
                    cue_contract,
                    go_source,
                    binary_blob,
                    binary_hash,
                ),
            )
            conn.commit()
        return artifact_id

    def record_execution(
        self,
        artifact_id: str,
        exit_code: int,
        latency_ms: float,
        memory_peak_kb: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_metrics (
                    artifact_id, exit_code, latency_ms, memory_peak_kb, error_message
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, exit_code, latency_ms, memory_peak_kb, error_message),
            )

            # Actualizar tasa de éxito y latencia promedio
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
            conn.commit()

    def list_artifacts(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if category:
                rows = conn.execute(
                    "SELECT id, name, category, version, success_rate, execution_count, avg_latency_ms, created_at FROM artifacts WHERE category = ? ORDER BY execution_count DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, category, version, success_rate, execution_count, avg_latency_ms, created_at FROM artifacts ORDER BY execution_count DESC"
                ).fetchall()
            return [dict(r) for r in rows]
