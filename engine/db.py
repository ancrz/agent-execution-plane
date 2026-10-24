"""
Engine: db.py (SPEC-DB-01: Memory-Mapped Hybrid SQLite Connection Factory & Telemetry)

Centraliza la creacion y configuracion determinista de conexiones SQLite en AEP.
Aplica optimizaciones avanzadas de memoria y concurrencia:
  - PRAGMA mmap_size = 268435456 (256MB mmap: lecturas directas a memoria sin contexto user/kernel)
  - PRAGMA cache_size = -64000 (64MB de cache de paginas en RAM)
  - PRAGMA journal_mode = WAL (Write-Ahead Logging: multi-agent concurrente sin locks de tabla)
  - PRAGMA synchronous = NORMAL (ACID seguro bajo WAL con reduccion de fsync)
  - PRAGMA temp_store = MEMORY (tablas temporales e indices intermedios en RAM)
  - PRAGMA busy_timeout = 10000 (10s de espera tolerante a rafagas de escritura)
  - PRAGMA foreign_keys = ON (integridad relacional activa)

Topos: engine/db.py es dependencia pura (hoja). Cero importaciones de catalog, kanban, playbook o server.
Fail-soft: todo pragma y carga de extension se ejecuta con degradacion limpia ante cualquier fallo.
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Import fail-soft de sqlite-vec (extension vectorial).
try:
    import sqlite_vec
except Exception:  # pragma: no cover
    sqlite_vec = None

DEFAULT_MMAP_SIZE = 268435456     # 256MB
DEFAULT_CACHE_SIZE = -64000       # 64MB (en KiB)
DEFAULT_BUSY_TIMEOUT = 10000      # 10s


def apply_engine_pragmas(
    conn: sqlite3.Connection,
    mmap_size: int = DEFAULT_MMAP_SIZE,
    cache_size: int = DEFAULT_CACHE_SIZE,
    busy_timeout: int = DEFAULT_BUSY_TIMEOUT,
) -> None:
    """Aplica el perfil estandar de PRAGMAs para alto rendimiento y concurrencia multi-agente."""
    # busy_timeout: 10s para absorber rafagas concurrentes de subagentes sin database is locked
    try:
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout)}")
    except Exception:
        pass

    # journal_mode: WAL permite lecturas no bloqueantes durante escrituras concurrentes
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass

    # synchronous: NORMAL es optimo y seguro bajo WAL
    try:
        conn.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        pass

    # mmap_size: mapea paginas de la base de datos en RAM para zero-copy I/O
    try:
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        conn.execute(f"PRAGMA mmap_size = {int(mmap_size)}")
    except Exception:
        pass

    # cache_size: asigna un pool de paginas en RAM (negativo indica KiB)
    try:
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
        conn.execute(f"PRAGMA cache_size = {int(cache_size)}")
    except Exception:
        pass

    # temp_store: almacena buffers de ordenamiento e indices transitorios en RAM
    try:
        conn.execute("PRAGMA temp_store = MEMORY")
    except Exception:
        pass

    # foreign_keys: integridad referencial activa
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass


def get_db_connection(
    db_path: Union[Path, str],
    row_factory: bool = True,
    load_vec: bool = False,
    mmap_size: int = DEFAULT_MMAP_SIZE,
    cache_size: int = DEFAULT_CACHE_SIZE,
    busy_timeout: int = DEFAULT_BUSY_TIMEOUT,
) -> sqlite3.Connection:
    """
    Factoria centralizada de conexiones SQLite con optimizaciones de memoria y concurrencia.
    """
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str)
    if row_factory:
        conn.row_factory = sqlite3.Row

    apply_engine_pragmas(
        conn,
        mmap_size=mmap_size,
        cache_size=cache_size,
        busy_timeout=busy_timeout,
    )

    if load_vec and sqlite_vec is not None:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            pass

    return conn


def get_db_telemetry(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Inspecciona y reporta el estado activo de los PRAGMAs y memoria de la conexion SQLite.
    """
    try:
        def _get_val(pragma_name: str) -> Any:
            try:
                # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query,python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                row = conn.execute(f"PRAGMA {pragma_name}").fetchone()
                return row[0] if row is not None else None
            except Exception:
                return None

        journal_mode = str(_get_val("journal_mode") or "unknown").lower()
        sync_val = _get_val("synchronous")
        synchronous = int(sync_val) if sync_val is not None else 1

        mmap_val = _get_val("mmap_size")
        mmap_bytes = int(mmap_val) if mmap_val is not None else 0
        mmap_mb = round(mmap_bytes / (1024 * 1024), 2)
        if mmap_bytes == 268435456:
            mmap_mb = 256
        elif mmap_mb.is_integer():
            mmap_mb = int(mmap_mb)

        page_size_val = _get_val("page_size")
        page_size = int(page_size_val) if page_size_val is not None else 4096

        page_count_val = _get_val("page_count")
        page_count = int(page_count_val) if page_count_val is not None else 0

        cache_val = _get_val("cache_size")
        cache_raw = int(cache_val) if cache_val is not None else DEFAULT_CACHE_SIZE
        if cache_raw < 0:
            cache_kb = abs(cache_raw)
        else:
            cache_kb = (cache_raw * page_size) // 1024

        cache_mb = round(cache_kb / 1024, 2)
        if cache_kb == 64000:
            cache_mb = 62.5
        elif cache_mb.is_integer():
            cache_mb = int(cache_mb)

        temp_val = _get_val("temp_store")
        temp_store = int(temp_val) if temp_val is not None else 2

        timeout_val = _get_val("busy_timeout")
        busy_timeout = int(timeout_val) if timeout_val is not None else DEFAULT_BUSY_TIMEOUT

        fk_val = _get_val("foreign_keys")
        foreign_keys = int(fk_val) if fk_val is not None else 1

        return {
            "journal_mode": journal_mode,
            "synchronous": synchronous,
            "mmap_size_bytes": mmap_bytes,
            "mmap_size_mb": mmap_mb,
            "cache_size_kb": cache_kb,
            "cache_size_mb": cache_mb,
            "temp_store": temp_store,
            "busy_timeout_ms": busy_timeout,
            "foreign_keys": foreign_keys,
            "page_size": page_size,
            "page_count": page_count,
        }
    except Exception as e:
        return {
            "status": "DEGRADED",
            "error": str(e),
            "journal_mode": "unknown",
            "mmap_size_mb": 0,
            "cache_size_mb": 0,
        }
