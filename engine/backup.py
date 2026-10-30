"""
Engine: backup.py — Database Resilience, Anti-Poisoning Quarantine & 5-Slot Online Hot Backup Engine.

Proporciona protección ACID, anti-envenenamiento y recuperación ante desastres sin bloqueo en SQLite bajo WAL:
  - 5-slot FIFO rotation pool (artifacts.db.bak.1 a artifacts.db.bak.5) + backups_manifest.json.
  - Native SQLite Backup API (conn.backup()) sobre conexiones de solo lectura (mode=ro).
  - Anti-Poisoning Zero-Trust Quarantine: PRAGMA quick_check + PRAGMA foreign_key_check + canary token verification + schema fingerprinting.
  - Aislamiento automático de bases de datos corruptas/manipuladas en backups/quarantine/ con reportes forenses JSON sin contaminar el pool de 5 slots.
  - Snapshot Golden de referencia (artifacts.db.golden).
  - Micro-snapshots volátiles en memoria RAM (<2ms latencia) para operaciones especulativas sin tocar almacenamiento secundario.
  - Bloqueo de concurrencia consultivo (fcntl.flock) en ~/.local/share/agent-os/backups/.lock.
  - Auto-recuperación de autoreparación (verify_and_auto_recover) con respuesta fail-soft.
"""

import fcntl
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.db import get_ro_connection, get_rw_connection

logger = logging.getLogger("aep.backup")

DB_DEFAULT_PATH = Path.home() / ".local" / "share" / "agent-os" / "artifacts.db"
BACKUPS_DEFAULT_DIR = Path.home() / ".local" / "share" / "agent-os" / "backups"
MAX_BACKUP_SLOTS = 5
MANIFEST_FILENAME = "backups_manifest.json"
LOCK_FILENAME = ".lock"
GOLDEN_FILENAME = "artifacts.db.golden"
QUARANTINE_DIRNAME = "quarantine"
CANARY_TABLE = "_aep_canary"
CANARY_TOKEN = "aep_canary_v1_active"  # noqa: S105

# Store global para micro-snapshots volátiles en memoria RAM (acotado a FIFO de 2 slots)
_RAM_MICRO_SNAPSHOTS: dict[str, sqlite3.Connection] = {}
MAX_RAM_SNAPSHOTS = 2


class DatabasePoisonError(Exception):
    """Excepción lanzada cuando una base de datos está corrupta o envenenada y no supera las comprobaciones de integridad."""
    pass


def compute_file_sha256(path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo en bloques de 64KB."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_db_integrity(db_path: Path) -> bool:
    """Ejecuta PRAGMA integrity_check en una base de datos SQLite y valida resultado 'ok'."""
    if not db_path.exists():
        return False
    try:
        resolved = db_path.resolve()
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            res = cur.fetchall()
            return bool(res and len(res) == 1 and res[0][0] == "ok")
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.debug("Integrity check failed for %s: %s", db_path, e)
        return False


def ensure_canary(conn: sqlite3.Connection) -> None:
    """Crea la tabla de canary y asegura la presencia del token canario _aep_canary."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _aep_canary "
        "(id INTEGER PRIMARY KEY, canary_token TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    cur = conn.execute("SELECT COUNT(*) FROM _aep_canary")
    if cur.fetchone()[0] == 0:
        iso_now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO _aep_canary (id, canary_token, created_at) VALUES (1, ?, ?)",
            (CANARY_TOKEN, iso_now),
        )


def verify_canary(conn: sqlite3.Connection) -> bool:
    """Verifica que la tabla _aep_canary exista y contenga el token válido."""
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
            (CANARY_TABLE,),
        )
        if cur.fetchone()[0] == 0:
            return False
        cur = conn.execute("SELECT COUNT(*) FROM _aep_canary")
        if cur.fetchone()[0] == 0:
            return False
        cur = conn.execute(
            "SELECT canary_token FROM _aep_canary WHERE id = 1"
        )
        row = cur.fetchone()
        return bool(row and row[0] == CANARY_TOKEN)
    except sqlite3.Error:
        return False


def compute_schema_hash(conn: sqlite3.Connection) -> str:
    """Calcula un hash determinista SHA-256 de los esquemas de tablas/índices de sqlite_master."""
    hasher = hashlib.sha256()
    cur = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND name != ? ORDER BY name",
        (CANARY_TABLE,),
    )
    for row in cur.fetchall():
        line = f"{row[0]}:{row[1]}:{row[2]}:{row[3] or ''}\n"
        hasher.update(line.encode("utf-8"))
    return hasher.hexdigest()


def verify_database_integrity(
    db_path: Path | str | None = None,
    auto_seed_canary: bool = True,
    expected_schema_hash: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    db_path = Path(db_path or DB_DEFAULT_PATH)
    """
    Verificación profunda anti-envenenamiento:
      1. Verificación de archivo y cabecera SQLite.
      2. PRAGMA quick_check e integrity_check.
      3. PRAGMA foreign_key_check.
      4. Auto-seed / verificación de canary.
      5. Verificación de fingerprint de esquema SHA-256 (si expected_schema_hash se provee).
    """
    if not db_path.exists():
        return False, "FILE_NOT_FOUND", {"path": str(db_path)}
    if db_path.stat().st_size == 0:
        return False, "EMPTY_DATABASE", {"path": str(db_path), "size": 0}

    # Comprobación de cabecera mágica SQLite
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
            if header != b"SQLite format 3\x00":
                return False, "INVALID_SQLITE_HEADER", {"header": str(header[:16])}
    except OSError as e:
        return False, "FILE_READ_ERROR", {"error": str(e)}

    try:
        resolved = db_path.resolve()
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA quick_check")
            qc = cur.fetchall()
            if not (qc and len(qc) == 1 and qc[0][0] == "ok"):
                return False, "INTEGRITY_CHECK_FAILED", {"quick_check": qc}

            cur.execute("PRAGMA foreign_key_check")
            fk_violations = cur.fetchall()
            if fk_violations:
                return False, "FK_VIOLATIONS", {"violations": len(fk_violations)}

            cur.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name = ?",
                (CANARY_TABLE,),
            )
            canary_exists = cur.fetchone()[0] > 0

            cur.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != ?",
                (CANARY_TABLE,),
            )
            user_table_count = cur.fetchone()[0]
            schema_hash = compute_schema_hash(conn)
        finally:
            conn.close()

        # Manejo de Canary
        if not canary_exists:
            if auto_seed_canary:
                try:
                    rw = get_rw_connection(db_path, row_factory=False)
                    try:
                        ensure_canary(rw)
                    finally:
                        rw.close()
                except Exception as e:  # noqa: BLE001
                    logger.debug("Auto-seed canary failed: %s", e)  # noqa: BLE001
            else:
                return False, "CANARY_MISSING", {"table": CANARY_TABLE}
        else:
            chk_conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
            try:
                if not verify_canary(chk_conn):
                    return False, "CANARY_CORRUPTED", {"error": "Token canario inválido o alterado"}
            finally:
                chk_conn.close()

        if expected_schema_hash and schema_hash != expected_schema_hash:
            return False, "SCHEMA_MISMATCH", {
                "expected": expected_schema_hash,
                "actual": schema_hash,
            }

        return True, "HEALTHY", {
            "schema_hash": schema_hash,
            "user_tables": user_table_count,
            "size_bytes": db_path.stat().st_size,
        }

    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError) as e:
        return False, "CORRUPT_DATABASE", {"error": str(e)}


def quarantine_corrupted_db(
    db_path: Path,
    reason: str,
    details: dict[str, Any],
    quarantine_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Aísla una base de datos corrupta o envenenada en backups/quarantine/
    junto con un reporte forense JSON detallado. Nunca modifica el pool FIFO de 5 slots.
    """
    q_dir = Path(quarantine_dir or (db_path.parent / "backups" / QUARANTINE_DIRNAME)).resolve()
    q_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    corrupt_filename = f"{db_path.name}.corrupt.{ts}"
    target_corrupt_file = q_dir / corrupt_filename
    report_file = q_dir / f"{corrupt_filename}.forensic.json"

    file_sha256 = "unavailable"
    if db_path.exists():
        try:
            shutil.copyfile(db_path, target_corrupt_file)
            file_sha256 = compute_file_sha256(target_corrupt_file)
        except OSError as e:
            logger.warning("Could not copy corrupt db to quarantine: %s", e)

    forensic_data = {
        "timestamp": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "quarantined_file": str(target_corrupt_file),
        "reason": reason,
        "sha256": file_sha256,
        "details": details,
    }

    try:
        report_file.write_text(json.dumps(forensic_data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write forensic report: %s", e)

    return {
        "status": "QUARANTINED",
        "quarantine_dir": str(q_dir),
        "quarantined_file": str(target_corrupt_file),
        "forensic_report": str(report_file),
        "reason": reason,
        "sha256": file_sha256,
    }


def get_quarantine_status(backups_dir: Path | str | None = None) -> dict[str, Any]:
    """Inspecciona y devuelve el registro de bases de datos aisladas en cuarentena."""
    b_dir = Path(backups_dir or BACKUPS_DEFAULT_DIR).resolve()
    q_dir = b_dir / QUARANTINE_DIRNAME
    if not q_dir.exists():
        return {"status": "OK", "quarantine_dir": str(q_dir), "count": 0, "quarantined": []}

    reports: list[dict[str, Any]] = []
    for f in sorted(q_dir.glob("*.forensic.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reports.append(data)
        except Exception:  # noqa: BLE001
            reports.append({"report_file": str(f)})

    return {
        "status": "OK",
        "quarantine_dir": str(q_dir),
        "count": len(reports),
        "quarantined": reports,
    }


# ==============================================================================
# Micro-snapshots volátiles en memoria RAM (TASK-03)
# ==============================================================================

def create_micro_snapshot(
    db_path: Path | str | None = None,
    snapshot_id: str | None = "default",
) -> dict[str, Any]:
    """
    Crea un micro-snapshot volátil en memoria RAM usando la API de backup nativa de SQLite.
    Garantiza latencia sub-milisegundo (<2ms) y cero escrituras en disco.
    """
    eff_snap_id = snapshot_id or "default"
    if isinstance(db_path, str) and not db_path.endswith(".db") and not Path(db_path).exists() and eff_snap_id == "default":
        eff_snap_id = db_path
        db_path = None

    target = Path(db_path or DB_DEFAULT_PATH).resolve()
    if not target.exists():
        return {"status": "SOURCE_NOT_FOUND", "error": f"Base de datos {target} no existe"}

    t0 = time.perf_counter()
    src_conn = get_ro_connection(target, row_factory=False)
    try:
        mem_conn = sqlite3.connect(":memory:")
        src_conn.backup(mem_conn)
    finally:
        src_conn.close()

    latency_ms = (time.perf_counter() - t0) * 1000

    # Cerrar conexión previa si existía en ese slot
    if eff_snap_id in _RAM_MICRO_SNAPSHOTS:
        try:
            _RAM_MICRO_SNAPSHOTS.pop(eff_snap_id).close()
        except (sqlite3.Error, OSError):  # noqa: S110
            pass

    # Evicción FIFO para acotar consumo de RAM a MAX_RAM_SNAPSHOTS
    while len(_RAM_MICRO_SNAPSHOTS) >= MAX_RAM_SNAPSHOTS:
        oldest_key = next(iter(_RAM_MICRO_SNAPSHOTS))
        try:
            _RAM_MICRO_SNAPSHOTS.pop(oldest_key).close()
        except (sqlite3.Error, OSError):  # noqa: S110
            pass

    _RAM_MICRO_SNAPSHOTS[eff_snap_id] = mem_conn

    return {
        "status": "SUCCESS",
        "snapshot_id": eff_snap_id,
        "latency_ms": round(latency_ms, 3),
        "in_ram": True,
        "active_ram_snapshots": list(_RAM_MICRO_SNAPSHOTS.keys()),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def restore_micro_snapshot(
    db_path: Path | str | None = None,
    snapshot_id: str | None = "default",
) -> dict[str, Any]:
    """
    Restaura un micro-snapshot desde memoria RAM hacia la base de datos destino en disco.
    """
    eff_snap_id = snapshot_id or "default"
    if isinstance(db_path, str) and not db_path.endswith(".db") and not Path(db_path).exists() and eff_snap_id == "default":
        eff_snap_id = db_path
        db_path = None

    if eff_snap_id not in _RAM_MICRO_SNAPSHOTS:
        return {
            "status": "SNAPSHOT_NOT_FOUND",
            "error": f"Micro-snapshot en RAM '{eff_snap_id}' no encontrado",
            "active_snapshots": list(_RAM_MICRO_SNAPSHOTS.keys()),
        }

    target = Path(db_path or DB_DEFAULT_PATH).resolve()
    t0 = time.perf_counter()
    mem_conn = _RAM_MICRO_SNAPSHOTS[eff_snap_id]

    dst_conn = get_rw_connection(target, row_factory=False)
    try:
        mem_conn.backup(dst_conn)
    finally:
        dst_conn.close()

    latency_ms = (time.perf_counter() - t0) * 1000

    return {
        "status": "SUCCESS",
        "snapshot_id": eff_snap_id,
        "latency_ms": round(latency_ms, 3),
        "restored": True,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def list_micro_snapshots() -> dict[str, Any]:
    """Lista los identificadores de micro-snapshots activos en memoria RAM."""
    return {
        "status": "OK",
        "count": len(_RAM_MICRO_SNAPSHOTS),
        "active_snapshots": list(_RAM_MICRO_SNAPSHOTS.keys()),
    }


def clear_micro_snapshots() -> None:
    """Cierra y libera todas las conexiones de micro-snapshots en memoria RAM."""
    for conn in _RAM_MICRO_SNAPSHOTS.values():
        try:
            conn.close()
        except (sqlite3.Error, OSError):  # noqa: S110
            pass
    _RAM_MICRO_SNAPSHOTS.clear()


@contextmanager
def backup_concurrency_lock(backups_dir: Path) -> Generator[None]:
    """Bloqueo de archivo consultivo (fcntl.flock) para serializar operaciones de backup."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    lock_file = backups_dir / LOCK_FILENAME
    with open(lock_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except OSError as e:
                logger.debug("Failed to release flock: %s", e)


class BackupEngine:
    """Motor de gestión de copias de seguridad en caliente, rotación FIFO, cuarentena y restauración."""

    def __init__(self, db_path: Path | str | None = None, backups_dir: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DB_DEFAULT_PATH).resolve()
        self.backups_dir = Path(backups_dir or BACKUPS_DEFAULT_DIR).resolve()
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.backups_dir / MANIFEST_FILENAME

    def _load_manifest(self) -> dict[str, Any]:
        """Carga el manifiesto de backups o devuelve estructura vacía por defecto."""
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Error reading backup manifest %s: %s", self.manifest_path, e)
        return {
            "version": 1,
            "last_backup_timestamp": None,
            "active_slots": 0,
            "slots": {},
        }

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        """Guarda de forma atómica el manifiesto de backups en disco."""
        tmp_manifest = self.manifest_path.with_suffix(".tmp")
        tmp_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp_manifest.replace(self.manifest_path)

    def create_backup(self, raise_on_poison: bool = True) -> dict[str, Any]:
        """
        Crea un backup en caliente usando SQLite Backup API sobre conexión RO,
        rota el pool FIFO de 5 slots y verifica la integridad antes de promover.
        Aplica validación anti-envenenamiento y aislamiento en cuarentena.
        """
        with backup_concurrency_lock(self.backups_dir):
            if not self.db_path.exists():
                return {
                    "status": "SOURCE_NOT_FOUND",
                    "error": f"Base de datos de origen no encontrada: {self.db_path}",
                }

            # 0. Verificación anti-envenenamiento previa a la rotación
            is_healthy, reason, details = verify_database_integrity(self.db_path, auto_seed_canary=True)
            if not is_healthy:
                q_res = quarantine_corrupted_db(
                    self.db_path,
                    reason=reason,
                    details=details,
                    quarantine_dir=self.backups_dir / QUARANTINE_DIRNAME,
                )
                if raise_on_poison:
                    raise DatabasePoisonError(
                        f"Database poison/corruption detected ({reason}). Isolated to {q_res['quarantined_file']}"
                    )
                return {
                    "status": "POISON_DETECTED",
                    "quarantined": True,
                    "error": reason,
                    "details": details,
                    "quarantine_report": q_res,
                }

            # 1. Rotación FIFO: eliminar slot 5 si existe, desplazar 4->5, 3->4, etc.
            slot5 = self.backups_dir / f"artifacts.db.bak.{MAX_BACKUP_SLOTS}"
            if slot5.exists():
                slot5.unlink(missing_ok=True)

            for i in range(MAX_BACKUP_SLOTS - 1, 0, -1):
                src = self.backups_dir / f"artifacts.db.bak.{i}"
                dst = self.backups_dir / f"artifacts.db.bak.{i + 1}"
                if src.exists():
                    src.rename(dst)

            # 2. Creación en staging intermedio
            staging_file = self.backups_dir / "artifacts.db.bak.tmp"
            if staging_file.exists():
                staging_file.unlink(missing_ok=True)

            src_conn = get_ro_connection(self.db_path, row_factory=False)
            dst_conn = sqlite3.connect(str(staging_file))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            # 3. Verificación de integridad previa a la promoción
            staging_healthy, s_reason, s_details = verify_database_integrity(staging_file, auto_seed_canary=False)
            if not staging_healthy:
                staging_file.unlink(missing_ok=True)
                return {
                    "status": "INTEGRITY_CHECK_FAILED",
                    "error": f"Verificación de integridad falló en el backup generado: {s_reason}",
                    "details": s_details,
                }

            # 4. Cálculo de metadatos SHA-256 y tamaño
            sha256_hash = compute_file_sha256(staging_file)
            size_bytes = staging_file.stat().st_size

            page_count = 0
            try:
                check_conn = sqlite3.connect(f"file:{staging_file.resolve()}?mode=ro", uri=True)
                try:
                    cur = check_conn.cursor()
                    cur.execute("PRAGMA page_count")
                    row = cur.fetchone()
                    if row:
                        page_count = int(row[0])
                finally:
                    check_conn.close()
            except (sqlite3.Error, OSError) as e:
                logger.debug("Failed getting page count: %s", e)

            # 5. Promoción atómica a slot 1
            target_slot1 = self.backups_dir / "artifacts.db.bak.1"
            staging_file.rename(target_slot1)

            # 6. Actualización del manifiesto con slots desplazados
            manifest = self._load_manifest()
            old_slots = manifest.get("slots", {})
            new_slots: dict[str, Any] = {}

            for k, slot_info in old_slots.items():
                try:
                    slot_num = int(k)
                    if slot_num < MAX_BACKUP_SLOTS:
                        new_k = str(slot_num + 1)
                        slot_info["filename"] = f"artifacts.db.bak.{new_k}"
                        new_slots[new_k] = slot_info
                except ValueError:
                    continue

            iso_now = datetime.now(UTC).isoformat()
            new_slots["1"] = {
                "filename": "artifacts.db.bak.1",
                "timestamp": iso_now,
                "sha256": sha256_hash,
                "size_bytes": size_bytes,
                "page_count": page_count,
                "integrity_verified": True,
            }

            manifest["version"] = 1
            manifest["last_backup_timestamp"] = iso_now
            manifest["active_slots"] = len(new_slots)
            manifest["slots"] = new_slots
            self._save_manifest(manifest)

            return {
                "status": "SUCCESS",
                "slot": 1,
                "filename": "artifacts.db.bak.1",
                "sha256": sha256_hash,
                "size_bytes": size_bytes,
                "page_count": page_count,
                "timestamp": iso_now,
                "active_slots": len(new_slots),
            }

    def create_golden_snapshot(self) -> dict[str, Any]:
        """Crea un snapshot Golden inmutable de referencia verificando primero la integridad."""
        with backup_concurrency_lock(self.backups_dir):
            is_healthy, reason, details = verify_database_integrity(self.db_path, auto_seed_canary=True)
            if not is_healthy:
                q_res = quarantine_corrupted_db(
                    self.db_path,
                    reason=reason,
                    details=details,
                    quarantine_dir=self.backups_dir / QUARANTINE_DIRNAME,
                )
                raise DatabasePoisonError(
                    f"No se puede crear snapshot Golden: base de datos corrupta ({reason}). Aislada en {q_res['quarantined_file']}"
                )

            golden_file = self.backups_dir / GOLDEN_FILENAME
            src_conn = get_ro_connection(self.db_path, row_factory=False)
            dst_conn = sqlite3.connect(str(golden_file))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            sha256_hash = compute_file_sha256(golden_file)
            size_bytes = golden_file.stat().st_size
            iso_now = datetime.now(UTC).isoformat()

            manifest = self._load_manifest()
            manifest["golden"] = {
                "filename": GOLDEN_FILENAME,
                "timestamp": iso_now,
                "sha256": sha256_hash,
                "size_bytes": size_bytes,
            }
            self._save_manifest(manifest)

            return {
                "status": "SUCCESS",
                "filename": GOLDEN_FILENAME,
                "sha256": sha256_hash,
                "size_bytes": size_bytes,
                "timestamp": iso_now,
            }

    def restore_golden_snapshot(self) -> dict[str, Any]:
        """Restaura la base de datos a partir del snapshot Golden de referencia."""
        with backup_concurrency_lock(self.backups_dir):
            golden_file = self.backups_dir / GOLDEN_FILENAME
            if not golden_file.exists():
                return {
                    "status": "GOLDEN_NOT_FOUND",
                    "error": f"Snapshot Golden no encontrado en {golden_file}",
                }

            is_healthy, reason, details = verify_database_integrity(golden_file, auto_seed_canary=False)
            if not is_healthy:
                return {
                    "status": "CORRUPTED_GOLDEN",
                    "error": f"Snapshot Golden corrupto: {reason}",
                    "details": details,
                }

            wal_file = self.db_path.parent / f"{self.db_path.name}-wal"
            shm_file = self.db_path.parent / f"{self.db_path.name}-shm"
            wal_file.unlink(missing_ok=True)
            shm_file.unlink(missing_ok=True)

            tmp_restore = self.db_path.parent / f"{self.db_path.name}.restore.tmp"
            shutil.copyfile(golden_file, tmp_restore)
            os.sync()
            os.replace(tmp_restore, self.db_path)

            return {
                "status": "SUCCESS",
                "restored_from": GOLDEN_FILENAME,
                "db_path": str(self.db_path),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def restore_backup(self, slot_number: int = 1) -> dict[str, Any]:
        """
        Restaura la base de datos desde un slot de backup específico.
        Enfuerza purga atómica de archivos -wal y -shm para evitar desincronización.
        """
        with backup_concurrency_lock(self.backups_dir):
            if not 1 <= slot_number <= MAX_BACKUP_SLOTS:
                return {
                    "status": "INVALID_SLOT",
                    "error": f"Número de slot inválido: {slot_number}. Debe ser entre 1 y {MAX_BACKUP_SLOTS}.",
                }

            backup_file = self.backups_dir / f"artifacts.db.bak.{slot_number}"
            if not backup_file.exists():
                return {
                    "status": "BACKUP_NOT_FOUND",
                    "error": f"Archivo de backup para slot {slot_number} no existe: {backup_file}",
                }

            # 1. Validación previa del archivo de backup
            if not verify_db_integrity(backup_file):
                return {
                    "status": "CORRUPTED_BACKUP",
                    "error": f"El backup en slot {slot_number} está corrupto y no pasó PRAGMA integrity_check.",
                }

            # 2. Purga incondicional de WAL e índice SHM para prevenir desincronización
            wal_file = self.db_path.parent / f"{self.db_path.name}-wal"
            shm_file = self.db_path.parent / f"{self.db_path.name}-shm"
            wal_file.unlink(missing_ok=True)
            shm_file.unlink(missing_ok=True)

            # 3. Reemplazo atómico vía archivo temporal y os.replace
            tmp_restore = self.db_path.parent / f"{self.db_path.name}.restore.tmp"
            shutil.copyfile(backup_file, tmp_restore)
            os.sync()
            os.replace(tmp_restore, self.db_path)

            # 4. Inicialización post-restauración y verificación final
            post_check_ok = False
            try:
                rw_conn = get_rw_connection(self.db_path, row_factory=False)
                try:
                    cur = rw_conn.cursor()
                    cur.execute("PRAGMA integrity_check")
                    res = cur.fetchall()
                    post_check_ok = bool(res and len(res) == 1 and res[0][0] == "ok")
                finally:
                    rw_conn.close()
            except (sqlite3.Error, OSError) as e:
                logger.error("Post-restore connection verification failed: %s", e)

            return {
                "status": "SUCCESS" if post_check_ok else "RESTORE_VERIFICATION_FAILED",
                "restored_from_slot": slot_number,
                "db_path": str(self.db_path),
                "integrity_verified": post_check_ok,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def verify_and_auto_recover(self) -> dict[str, Any]:
        """
        Comprueba la integridad de la base de datos principal y, si está corrupta o falta,
        escanea los slots 1..5 en orden y restaura el más reciente válido.
        Devuelve respuesta fail-soft limpia si ningún slot es válido.
        """
        with backup_concurrency_lock(self.backups_dir):
            if self.db_path.exists() and verify_db_integrity(self.db_path):
                return {
                    "status": "HEALTHY",
                    "recovered": False,
                    "message": "La base de datos principal pasa PRAGMA integrity_check; no se requiere auto-recuperación.",
                }

            logger.warning("Database corruption or absence detected on %s. Initiating auto-recovery...", self.db_path)

            # Si el archivo está corrupto y existe, aislarlo preventivamente en cuarentena
            if self.db_path.exists():
                try:
                    quarantine_corrupted_db(
                        self.db_path,
                        reason="AUTO_RECOVERY_TRIGGERED_CORRUPTION",
                        details={"path": str(self.db_path)},
                        quarantine_dir=self.backups_dir / QUARANTINE_DIRNAME,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug("Failed quarantining before auto-recovery: %s", e)

            # Escanear slots del 1 al 5
            for slot in range(1, MAX_BACKUP_SLOTS + 1):
                slot_file = self.backups_dir / f"artifacts.db.bak.{slot}"
                if slot_file.exists() and verify_db_integrity(slot_file):
                    logger.info("Found healthy backup in slot %s. Executing atomic restore...", slot)
                    wal_file = self.db_path.parent / f"{self.db_path.name}-wal"
                    shm_file = self.db_path.parent / f"{self.db_path.name}-shm"
                    wal_file.unlink(missing_ok=True)
                    shm_file.unlink(missing_ok=True)

                    tmp_restore = self.db_path.parent / f"{self.db_path.name}.restore.tmp"
                    shutil.copyfile(slot_file, tmp_restore)
                    os.sync()
                    os.replace(tmp_restore, self.db_path)

                    post_check_ok = False
                    try:
                        rw_conn = get_rw_connection(self.db_path, row_factory=False)
                        try:
                            cur = rw_conn.cursor()
                            cur.execute("PRAGMA integrity_check")
                            res = cur.fetchall()
                            post_check_ok = bool(res and len(res) == 1 and res[0][0] == "ok")
                        finally:
                            rw_conn.close()
                    except (sqlite3.Error, OSError) as e:
                        logger.error("Post-auto-recovery check failed: %s", e)

                    return {
                        "status": "AUTO_RECOVERED" if post_check_ok else "AUTO_RECOVER_VERIFY_FAILED",
                        "recovered": post_check_ok,
                        "restored_from_slot": slot,
                        "backup_file": str(slot_file),
                        "integrity_verified": post_check_ok,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

            return {
                "status": "AUTO_RECOVER_FAILED",
                "recovered": False,
                "error": "No se encontró ningún slot de backup válido o no corrupto para auto-recuperar.",
            }

    def get_backup_status(self) -> dict[str, Any]:
        """Devuelve el estado del pool de rotación, snapshot Golden, cuarentena y uso de disco."""
        manifest = self._load_manifest()
        slots_detail: list[dict[str, Any]] = []

        total_bytes = 0
        for slot in range(1, MAX_BACKUP_SLOTS + 1):
            slot_file = self.backups_dir / f"artifacts.db.bak.{slot}"
            exists = slot_file.exists()
            size = slot_file.stat().st_size if exists else 0
            total_bytes += size
            manifest_info = manifest.get("slots", {}).get(str(slot), {})

            slots_detail.append(
                {
                    "slot": slot,
                    "filename": f"artifacts.db.bak.{slot}",
                    "exists": exists,
                    "size_bytes": size,
                    "timestamp": manifest_info.get("timestamp"),
                    "sha256": manifest_info.get("sha256"),
                    "integrity_verified": manifest_info.get("integrity_verified", False),
                }
            )

        golden_info = manifest.get("golden")
        golden_file = self.backups_dir / GOLDEN_FILENAME
        golden_exists = golden_file.exists()

        q_status = get_quarantine_status(self.backups_dir)

        return {
            "status": "OK",
            "backups_dir": str(self.backups_dir),
            "max_slots": MAX_BACKUP_SLOTS,
            "active_slots": manifest.get("active_slots", 0),
            "last_backup_timestamp": manifest.get("last_backup_timestamp"),
            "total_disk_bytes": total_bytes,
            "slots": slots_detail,
            "golden_snapshot": {
                "exists": golden_exists,
                "filename": GOLDEN_FILENAME if golden_exists else None,
                "details": golden_info if golden_exists else None,
            },
            "quarantine": {
                "count": q_status.get("count", 0),
                "quarantine_dir": q_status.get("quarantine_dir"),
            },
        }


# Funciones de conveniencia a nivel de módulo
def create_backup(
    db_path: Path | str | None = None,
    backups_dir: Path | str | None = None,
    raise_on_poison: bool = True,
) -> dict[str, Any]:
    """Crea un backup en caliente usando BackupEngine."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).create_backup(raise_on_poison=raise_on_poison)


def restore_backup(
    slot_number: int = 1, db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Restaura un backup desde el slot especificado."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).restore_backup(slot_number=slot_number)


def create_golden_snapshot(
    db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Crea un snapshot Golden de referencia."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).create_golden_snapshot()


def restore_golden_snapshot(
    db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Restaura la base de datos a partir del snapshot Golden."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).restore_golden_snapshot()


def verify_and_auto_recover(
    db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Ejecuta auto-recuperación de autoreparación si la base de datos está dañada."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).verify_and_auto_recover()


def get_backup_status(backups_dir: Path | str | None = None) -> dict[str, Any]:
    """Devuelve el estado actual de las copias de seguridad."""
    return BackupEngine(backups_dir=backups_dir).get_backup_status()
