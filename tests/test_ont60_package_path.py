"""ONT-60 T3: `package check` falls back to PATH when dpkg does not know the binary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent
CTL = ROOT / "scripts" / "aep-ctl"


def _check(name: str, path: str) -> dict:
    env = {**os.environ, "PATH": path, "PYTHONPATH": str(ROOT)}
    r = subprocess.run(
        [sys.executable, str(CTL), "package", "check", name, "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    return json.loads(r.stdout)


def test_package_check_falls_back_to_path(tmp_path: Path) -> None:
    assert Path(server.AEP_CTL) == CTL
    real = tmp_path / "opt" / "fakego" / "bin"
    real.mkdir(parents=True)
    tool = real / "fakego"
    tool.write_text("#!/bin/sh\necho 'fakego version 9.9.9'\n")
    tool.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fakego").symlink_to(tool)
    out = _check("fakego", f"{bindir}:/usr/bin:/bin")
    assert out["installed"] is True
    assert out["source"] == "path"
    assert out["path"] == str(bindir / "fakego")
    assert out["realpath"] == str(tool.resolve())
    assert out["version"] == "fakego version 9.9.9"


def test_package_check_missing_is_not_installed(tmp_path: Path) -> None:
    assert Path(server.AEP_CTL) == CTL
    out = _check("definitely-not-a-real-bin-ont60", f"{tmp_path}:/usr/bin:/bin")
    assert out["installed"] is False


def test_package_check_dpkg_source() -> None:
    assert Path(server.AEP_CTL) == CTL
    out = _check("bash", "/usr/bin:/bin")
    if out.get("status") == "DEGRADED":
        return
    assert out["installed"] is True
    assert out["source"] in {"dpkg", "path"}


def test_ctl_script_is_the_one_the_server_spawns() -> None:
    assert Path(server.AEP_CTL) == CTL


@pytest.mark.parametrize("bad", ["../etc/passwd", "go;id", "-W", "a b", "$(id)"])
def test_package_check_rejects_invalid_names(bad: str, tmp_path: Path) -> None:
    assert Path(server.AEP_CTL) == CTL
    out = _check(bad, f"{tmp_path}:/usr/bin:/bin")
    assert out["status"] == "PARAM_ERROR"
