"""ONT-41 TC6: scripts/aep_audit_state.py con archivos sinteticos (front_stale | backend_stale | lkg | pids muertos | legacy)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from engine import fingerprint

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("aep_audit_state", REPO / "scripts" / "aep_audit_state.py")
assert _spec and _spec.loader
audit_mod = importlib.util.module_from_spec(_spec)
sys.modules["aep_audit_state"] = audit_mod
_spec.loader.exec_module(audit_mod)

DISK_FP = "disk-fp"


def _state(shm: Path, pid: int, **kw: Any) -> None:
    data = {"pid": pid, "generation": 2, "active_fingerprint": DISK_FP, "serving_from": "disk", **kw}
    f = shm / f"aep_front_{pid}.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    f.chmod(0o600)


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, Path]:
    shm = tmp_path / "shm"
    shm.mkdir()
    root = tmp_path / "proj"
    root.mkdir()
    (root / "aep_front.py").write_text("x = 1\n", encoding="utf-8")
    return shm, root


def _run(
    shm: Path, root: Path, alive: set[int], start: float | None, running: list[int] | None = None, clean: bool = True
) -> dict[str, Any]:
    assert fingerprint.code_fingerprint(str(REPO))  # el hash real del arbol es el mismo que el script importa
    return audit_mod.audit(
        root,
        shm,
        clean=clean,
        running_pids=running,
        fingerprint_fn=lambda _r: DISK_FP,
        alive_fn=lambda p: p in alive,
        start_fn=lambda _p: start,
    )


def test_classes_front_backend_lkg_current(env: tuple[Path, Path]) -> None:
    shm, root = env
    mtime = (root / "aep_front.py").stat().st_mtime
    _state(shm, 11)
    _state(shm, 12, active_fingerprint="other")
    _state(shm, 13, serving_from="lkg")
    got = {i["pid"]: i["class"] for i in _run(shm, root, {11, 12, 13}, start=mtime + 100)["instances"]}
    assert got == {11: "current", 12: "backend_stale", 13: "serving_lkg"}
    stale = {i["pid"]: i["class"] for i in _run(shm, root, {11, 12}, start=mtime - 100)["instances"]}
    assert stale == {11: "front_stale", 12: "front_stale"}  # front_stale prevalece: exige reconexion


def test_dead_pids_ignored_and_cleaned_and_legacy_label(env: tuple[Path, Path]) -> None:
    shm, root = env
    _state(shm, 21)
    keep = _run(shm, root, set(), None, clean=False)
    assert keep["instances"] == [] and (shm / "aep_front_21.json").exists()
    res = _run(shm, root, {31}, None, running=[31])
    assert res["removed"] == ["aep_front_21.json"] and not (shm / "aep_front_21.json").exists()
    assert res["instances"] == [{"pid": 31, "class": "legacy/unknown", "detail": res["instances"][0]["detail"]}]


def test_unsafe_files_are_refused(env: tuple[Path, Path], tmp_path: Path) -> None:
    shm, root = env
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"pid": 41}), encoding="utf-8")
    (shm / "aep_front_41.json").symlink_to(real)
    (shm / "aep_front_42.json").write_text("{" + "x" * (audit_mod.STATE_MAX_BYTES + 5), encoding="utf-8")
    (shm / "aep_front_43.json").write_text("not json", encoding="utf-8")
    assert _run(shm, root, {41, 42, 43}, None)["instances"] == []


def test_cli_emits_one_json_line(env: tuple[Path, Path]) -> None:
    shm, root = env
    out = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "aep_audit_state.py"),
            str(REPO),
            "--dir",
            str(shm),
            "--no-clean",
            str(os.getpid()),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)
    assert fingerprint.code_fingerprint(str(REPO))
    assert data["instances"][0]["class"] == "legacy/unknown"
