"""
Engine: backup.py — Database Resilience & 5-Slot Online Hot Backup Rotation Engine.

Proporciona protección ACID y recuperación ante desastres sin bloqueo en SQLite bajo WAL:
  - 5-slot FIFO rotation pool (artifacts.db.bak.1 a artifacts.db.bak.5) + backups_manifest.json.
  - Native SQLite Backup API (conn.backup()) sobre conexiones de solo lectura (mode=ro).
  - Verificación previa a la promoción (PRAGMA integrity_check + SHA-256 byte checksums).
  - Purga atómica de archivos -wal y -shm antes de la sustitución atómica (os.replace).
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


@contextmanager
def backup_concurrency_lock(backups_dir: Path) -> Generator[None, None, None]:
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
    """Motor de gestión de copias de seguridad en caliente, rotación FIFO y restauración."""

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

    def create_backup(self) -> dict[str, Any]:
        """
        Crea un backup en caliente usando SQLite Backup API sobre conexión RO,
        rota el pool FIFO de 5 slots y verifica la integridad antes de promover.
        """
        with backup_concurrency_lock(self.backups_dir):
            if not self.db_path.exists():
                return {
                    "status": "SOURCE_NOT_FOUND",
                    "error": f"Base de datos de origen no encontrada: {self.db_path}",
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
            if not verify_db_integrity(staging_file):
                staging_file.unlink(missing_ok=True)
                return {
                    "status": "INTEGRITY_CHECK_FAILED",
                    "error": "PRAGMA integrity_check falló en el backup generado.",
                }

            # 4. Cálculo de metadatos SHA-256 y tamaño
            sha256_hash = compute_file_sha256(staging_file)
            size_bytes = staging_file.stat().st_size

            # Obtener page_count de la base de datos de respaldo
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

            # Desplazar slots en el manifiesto
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
            # Comprobar si la base de datos principal está sana
            if self.db_path.exists() and verify_db_integrity(self.db_path):
                return {
                    "status": "HEALTHY",
                    "recovered": False,
                    "message": "La base de datos principal pasa PRAGMA integrity_check; no se requiere auto-recuperación.",
                }

            logger.warning("Database corruption or absence detected on %s. Initiating auto-recovery...", self.db_path)

            # Escanear slots del 1 al 5
            for slot in range(1, MAX_BACKUP_SLOTS + 1):
                slot_file = self.backups_dir / f"artifacts.db.bak.{slot}"
                if slot_file.exists() and verify_db_integrity(slot_file):
                    logger.info("Found healthy backup in slot %s. Executing atomic restore...", slot)
                    # Liberar el lock temporalmente para restore_backup o llamar lógica interna
                    # Ya que tenemos el lock reentrante en el mismo proceso (fcntl sobre el mismo fd),
                    # restore_backup también adquiere el lock sin problema en el mismo contexto.
                    # Para máxima seguridad, realizamos la restauración directamente:
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

            # Fail-soft: ningún slot válido encontrado
            return {
                "status": "AUTO_RECOVER_FAILED",
                "recovered": False,
                "error": "No se encontró ningún slot de backup válido o no corrupto para auto-recuperar.",
            }

    def get_backup_status(self) -> dict[str, Any]:
        """Devuelve el estado del pool de rotación, archivos presentes y uso de disco."""
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

        return {
            "status": "OK",
            "backups_dir": str(self.backups_dir),
            "max_slots": MAX_BACKUP_SLOTS,
            "active_slots": manifest.get("active_slots", 0),
            "last_backup_timestamp": manifest.get("last_backup_timestamp"),
            "total_disk_bytes": total_bytes,
            "slots": slots_detail,
        }


# Funciones de conveniencia a nivel de módulo
def create_backup(db_path: Path | str | None = None, backups_dir: Path | str | None = None) -> dict[str, Any]:
    """Crea un backup en caliente usando BackupEngine."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).create_backup()


def restore_backup(
    slot_number: int = 1, db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Restaura un backup desde el slot especificado."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).restore_backup(slot_number=slot_number)


def verify_and_auto_recover(
    db_path: Path | str | None = None, backups_dir: Path | str | None = None
) -> dict[str, Any]:
    """Ejecuta auto-recuperación de autoreparación si la base de datos está dañada."""
    return BackupEngine(db_path=db_path, backups_dir=backups_dir).verify_and_auto_recover()


def get_backup_status(backups_dir: Path | str | None = None) -> dict[str, Any]:
    """Devuelve el estado actual de las copias de seguridad."""
    return BackupEngine(backups_dir=backups_dir).get_backup_status()
