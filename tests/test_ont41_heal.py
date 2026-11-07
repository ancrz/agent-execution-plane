"""ONT-41 TB2: threads_heal (sanación acotada a hilos rotos contra el LKG). AEP_DATA_HOME=tmp en todos."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

import aep_lkg
from engine import threads_heal

REPO = Path(__file__).resolve().parent.parent
BROKEN_FILE = "engine/fingerprint.py"
BENIGN_FILE = "engine/topos_guard.py"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("server.py", "aep_backend.py", "aep_front.py", "aep_lkg.py", "pyproject.toml"):
        shutil.copy2(REPO / name, repo / name)
    for sub in ("engine", "templates", "schemas", "scripts"):
        shutil.copytree(REPO / sub, repo / sub, ignore=shutil.ignore_patterns("__pycache__"))
    key = aep_lkg.save(repo, "g1", "fp", "schema", "head")["key"]
    return {"repo": repo, "key": key}


def break_files(repo: Path) -> str:
    original = (repo / BROKEN_FILE).read_text()
    (repo / BROKEN_FILE).write_text(original + "\ndef broken(:\n    pass\n")
    # Cambio benigno en otro archivo: debe quedar intacto tras heal.
    (repo / BENIGN_FILE).write_text((repo / BENIGN_FILE).read_text() + "\n# local edit kept\n")
    return original


def test_heal_clean_when_identical(world: dict[str, Any]) -> None:
    res = threads_heal.heal(world["repo"])
    assert res["status"] == "CLEAN" and res["threads"] == [] and res["key"] == world["key"]


def test_heal_no_lkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "empty"))
    assert threads_heal.heal(tmp_path)["status"] == "NO_LKG"


def test_heal_lists_broken_thread_and_file(world: dict[str, Any]) -> None:
    repo = world["repo"]
    break_files(repo)
    res = threads_heal.heal(repo)
    assert res["status"] == "BROKEN" and not res["applied"]
    assert res["files"] == [BROKEN_FILE]
    (entry,) = res["threads"]
    assert entry["module"] == "module:engine.fingerprint"
    assert "syntax_error" in entry["kinds"] and entry["syntax_error"].startswith("SyntaxError")
    assert entry["restorable"] and entry["scope"]
    assert entry["diff"]["hunks"] and any("broken" in ln for h in entry["diff"]["hunks"] for ln in h["lines"])
    assert "# local edit kept" in (repo / BENIGN_FILE).read_text()


def test_apply_restores_only_that_file_with_snapshot_first(world: dict[str, Any]) -> None:
    repo = world["repo"]
    original = break_files(repo)
    seen: dict[str, Any] = {}

    def snapshot(files: list[str]) -> dict[str, Any]:
        seen["files"] = files
        seen["broken_on_disk"] = "def broken(:" in (repo / BROKEN_FILE).read_text()
        return {"ok": True, "id": "snap-1"}

    res = threads_heal.heal(repo, apply=True, snapshot_fn=snapshot)
    assert res["status"] == "HEALED" and res["applied"] and res["restored"] == [BROKEN_FILE]
    assert seen == {"files": [BROKEN_FILE], "broken_on_disk": True}
    assert res["snapshot"]["id"] == "snap-1"
    assert (repo / BROKEN_FILE).read_text() == original
    assert "# local edit kept" in (repo / BENIGN_FILE).read_text()
    assert threads_heal.heal(repo)["threads"] == []


@pytest.mark.parametrize("failure", ["raise", "false", "error_dict"])
def test_snapshot_failed_writes_nothing(world: dict[str, Any], failure: str) -> None:
    repo = world["repo"]
    break_files(repo)
    before = (repo / BROKEN_FILE).read_text()

    def snapshot(files: list[str]) -> Any:
        if failure == "raise":
            raise OSError("no space")
        return False if failure == "false" else {"ok": False, "error": "denied"}

    res = threads_heal.heal(repo, apply=True, snapshot_fn=snapshot)
    assert res["status"] == "SNAPSHOT_FAILED" and not res["applied"] and res["restored"] == []
    assert (repo / BROKEN_FILE).read_text() == before


def test_apply_requires_snapshot_fn(world: dict[str, Any]) -> None:
    repo = world["repo"]
    break_files(repo)
    before = (repo / BROKEN_FILE).read_text()
    res = threads_heal.heal(repo, apply=True)
    assert res["status"] == "SNAPSHOT_REQUIRED" and (repo / BROKEN_FILE).read_text() == before


def test_corrupt_lkg_refused(world: dict[str, Any]) -> None:
    repo = world["repo"]
    break_files(repo)
    (aep_lkg.tree_path(world["key"]) / BROKEN_FILE).write_text("x = 1\n")
    res = threads_heal.heal(repo, key=world["key"], apply=True, snapshot_fn=lambda files: None)
    assert res["status"] == "LKG_INVALID" and "def broken(:" in (repo / BROKEN_FILE).read_text()


def test_no_server_import() -> None:
    src = (REPO / "engine" / "threads_heal.py").read_text()
    assert "import server" not in src and "from server" not in src
    # Runtime check: importing the module (and calling its entry point's module) must not pull in server.
    import subprocess
    import sys

    probe = "import sys; from engine import threads_heal; assert callable(threads_heal.heal); print('server' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", probe], cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
    assert threads_heal.heal.__module__ == "engine.threads_heal"
