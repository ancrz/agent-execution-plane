"""setup.sh sin red: la descarga falla (curl roto) y la instalacion debe fallar cerrada, con mensaje claro y sin binarios a medias."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from engine.privilege import check_binary_prerequisites

ROOT = Path(__file__).resolve().parent.parent


def _run_setup(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "setup.sh", project / "scripts" / "setup.sh")  # PROJECT_ROOT aislado (sin git)
    home = tmp_path / "home"
    home.mkdir()
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    stubs = tmp_path / "stubbin"
    stubs.mkdir()
    curl = stubs / "curl"
    curl.write_text("#!/bin/sh\necho 'curl: (6) Could not resolve host' >&2\nexit 6\n")
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    env = {
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "PATH": f"{stubs}:/usr/bin:/bin",  # sin uv/go/golangci-lint reales: el instalador debe descargarlos
        "AEP_FORCE_TIER": "6rw-",
        "LANG": "C",
    }
    res = subprocess.run(
        ["bash", str(project / "scripts" / "setup.sh")],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
        check=False,
    )
    return res, home, scratch


def test_setup_fails_closed_when_download_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert not any(Path(p, "uv").exists() for p in ("/usr/bin", "/bin")), "el test asume que uv no esta en /usr/bin"
    script = (ROOT / "scripts" / "setup.sh").read_text()  # el instalador fija golangci-lint y verifica su SHA-256
    assert re.search(r'^GL_SHA256_amd64="[0-9a-f]{64}"$', script, re.MULTILINE)
    assert re.search(r'^GL_SHA256_arm64="[0-9a-f]{64}"$', script, re.MULTILINE)
    assert re.search(r"golangci-lint v\d+\.\d+\.\d+", script)
    res, home, scratch = _run_setup(tmp_path)
    out = res.stdout + res.stderr
    assert res.returncode == 1, out
    assert "Descarga fallida para uv.tar.gz" in out
    assert "uv no disponible y la descarga verificada falló; no se puede continuar." in out
    assert "uv operativo" not in out  # nunca declara exito
    # sin binario parcial ni residuos: ni uv/uvx, ni el tarball descargado, ni el TMP_DIR de la corrida
    assert not (home / ".local" / "bin" / "uv").exists()
    assert not (home / ".local" / "bin" / "uvx").exists()
    assert list(scratch.iterdir()) == []
    assert not os.path.lexists(home / ".local" / "share" / "go")
    # el detector de prerequisitos de AEP, en el entorno que dejo la corrida fallida, no ve toolchain a medias
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{tmp_path / 'stubbin'}:/usr/bin:/bin")
    status = check_binary_prerequisites()
    assert status["go"]["installed"] is False, status["go"]
    assert status["golangci-lint"]["installed"] is False, status["golangci-lint"]
