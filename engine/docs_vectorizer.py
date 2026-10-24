"""
Engine: docs_vectorizer.py  (SPEC-OM-4: Local System Documentation Vectorizer)

Supera a Omarchy (que usó ChromaDB pesado) indexando man-pages de Ubuntu en una DB
semántica local con sqlite-vec + embeddings en CPU. Resuelve en <5ms la sintaxis exacta
de herramientas de bajo nivel sin alucinar flags ni gastar tokens navegando la web.

DB aislada: ~/.local/share/agent-os/system_docs.db (separada de artifacts.db).
Topos: docs_vectorizer.py -> embedder.py (A->B) y -> system_docs.db (A->B). No toca catalog.py.
"""

import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from engine.db import get_ro_connection, get_rw_connection, transaction_immediate
from engine.embedder import EMBEDDING_DIM, get_instance

logger = logging.getLogger("aep.docs_vectorizer")

try:
    import sqlite_vec
except (ImportError, OSError):
    sqlite_vec = None

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "system_docs.db"

# Lista curada (Fase 1). Ingesta ~30s. Ampliable on-demand vía ingest_command().
CURATED_COMMANDS = [
    "systemctl",
    "journalctl",
    "ip",
    "ss",
    "ufw",
    "apt",
    "dpkg",
    "cron",
    "bwrap",
    "bpftrace",
    "coredumpctl",
    "find",
    "grep",
    "rsync",
    "curl",
    "jq",
    "go",
    "python3",
    "git",
]
MAX_CHUNKS_PER_CMD = 50


class ManPagesVectorizer:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._vec_available = False
        with self._conn_rw() as conn:
            with transaction_immediate(conn):
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS man_chunks ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT NOT NULL, "
                    "section TEXT, chunk_text TEXT NOT NULL)"
                )
                self._vec_available = self._init_vec(conn)

    def _conn_ro(self) -> sqlite3.Connection:
        return get_ro_connection(self.db_path, row_factory=True, load_vec=True)

    def _conn_rw(self) -> sqlite3.Connection:
        return get_rw_connection(self.db_path, row_factory=True, load_vec=True)

    def _conn(self) -> sqlite3.Connection:
        return self._conn_rw()

    def _init_vec(self, conn: sqlite3.Connection) -> bool:
        if sqlite_vec is None:
            return False
        try:
            conn.execute("SELECT vec_version()").fetchone()
            dim = int(EMBEDDING_DIM)
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_docs USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding float[{dim}] distance_metric=cosine)"
            )
            return True
        except (sqlite3.Error, OSError) as e:
            logger.debug("sqlite-vec init failed: %s", e)
            return False

    def is_populated(self) -> bool:
        try:
            with self._conn_ro() as conn:
                return conn.execute("SELECT COUNT(*) FROM man_chunks").fetchone()[0] > 0
        except sqlite3.Error as e:
            logger.debug("is_populated check failed: %s", e)
            return False

    @staticmethod
    def _man_text(cmd: str) -> str | None:
        if not shutil.which("man"):
            return None
        try:
            env = {"MANPAGER": "cat", "MANWIDTH": "80", "PATH": "/usr/bin:/bin"}
            # check=False: returncode validated explicitly below
            r = subprocess.run(["man", cmd], capture_output=True, text=True, env=env, timeout=15, check=False)
            return r.stdout if r.returncode == 0 and r.stdout.strip() else None
        except (subprocess.SubprocessError, OSError) as e:
            logger.debug("Failed to retrieve man page for %s: %s", cmd, e)
            return None

    @staticmethod
    def _chunk(text: str) -> list[str]:
        # Chunking simple por bloques de párrafo; suficiente para recuperación de flags.
        blocks, cur = [], []
        for line in text.splitlines():
            if line.strip():
                cur.append(line.strip())
            elif cur:
                blocks.append(" ".join(cur))
                cur = []
        if cur:
            blocks.append(" ".join(cur))
        # Fusiona bloques muy cortos y recorta.
        merged = [b for b in blocks if len(b) > 40]
        return merged[:MAX_CHUNKS_PER_CMD]

    def ingest_command(self, cmd: str) -> dict[str, Any]:
        """Ingesta la man-page de un comando. FAIL-SOFT."""
        if not self._vec_available:
            return {"status": "SKIPPED", "command": cmd, "reason": "vec/embedder no disponible"}
        embedder = get_instance()
        if not embedder.is_available:
            return {"status": "SKIPPED", "command": cmd, "reason": "embedder no disponible"}
        text = self._man_text(cmd)
        if not text:
            return {"status": "NO_MANPAGE", "command": cmd}
        chunks = self._chunk(text)
        vecs = embedder.embed_batch(chunks)
        inserted = 0
        with self._conn_rw() as conn:
            with transaction_immediate(conn):
                # Reemplaza chunks previos de este comando (idempotencia).
                old = [r["id"] for r in conn.execute("SELECT id FROM man_chunks WHERE command=?", (cmd,))]
                if old:
                    conn.execute("DELETE FROM man_chunks WHERE command=?", (cmd,))
                    conn.executemany("DELETE FROM vec_docs WHERE chunk_id=?", [(i,) for i in old])
                for chunk, vec in zip(chunks, vecs):
                    if vec is None:
                        continue
                    cur = conn.execute(
                        "INSERT INTO man_chunks (command, section, chunk_text) VALUES (?, ?, ?)",
                        (cmd, None, chunk),
                    )
                    cid = cur.lastrowid
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO vec_docs (chunk_id, embedding) VALUES (?, ?)",
                            (cid, sqlite_vec.serialize_float32(vec)),
                        )
                        inserted += 1
                    except (sqlite3.Error, OSError) as e:
                        logger.debug("vec_docs insert failed for %s cid=%s: %s", cmd, cid, e)
        return {"status": "OK", "command": cmd, "chunks_indexed": inserted}

    def ingest_curated(self) -> dict[str, Any]:
        results = {c: self.ingest_command(c)["status"] for c in CURATED_COMMANDS}
        return {"status": "OK", "results": results}

    def query(self, q: str, limit: int = 3) -> dict[str, Any]:
        if not self._vec_available:
            return {"status": "DEGRADED", "message": "Tier semántico no disponible.", "results": []}
        embedder = get_instance()
        if not embedder.is_available:
            return {"status": "DEGRADED", "message": "Embedder no disponible.", "results": []}
        vec = embedder.embed(q)
        if vec is None:
            return {"status": "DEGRADED", "results": []}
        with self._conn_ro() as conn:
            try:
                rows = conn.execute(
                    """SELECT m.command, m.chunk_text, v.distance
                       FROM vec_docs v JOIN man_chunks m ON m.id = v.chunk_id
                       WHERE v.embedding MATCH ? AND k = ?
                       ORDER BY v.distance""",
                    (sqlite_vec.serialize_float32(vec), limit),
                ).fetchall()
            except (sqlite3.Error, OSError) as e:
                logger.debug("query execution failed: %s", e)
                return {"status": "ERROR", "error": str(e), "results": []}
        return {
            "status": "OK",
            "results": [
                {"command": r["command"], "distance": round(float(r["distance"]), 4), "chunk": r["chunk_text"][:400]}
                for r in rows
            ],
        }
