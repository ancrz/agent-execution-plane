"""The catalog DB and its directory must not be world/group readable."""

import os
import stat

from engine.catalog import ArtifactCatalog


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_new_catalog_db_is_0600_and_dir_0700(tmp_path) -> None:
    old_umask = os.umask(0o022)
    try:
        base = tmp_path / "agent-os"
        ArtifactCatalog(db_path=base / "artifacts.db")
    finally:
        os.umask(old_umask)
    assert _mode(base / "artifacts.db") == 0o600
    assert _mode(base) == 0o700
    for sidecar in base.glob("artifacts.db-*"):
        assert _mode(sidecar) & 0o077 == 0


def test_existing_permissive_db_is_tightened(tmp_path) -> None:
    db = tmp_path / "artifacts.db"
    db.touch(mode=0o644)
    db.chmod(0o644)
    ArtifactCatalog(db_path=db)
    assert _mode(db) == 0o600
