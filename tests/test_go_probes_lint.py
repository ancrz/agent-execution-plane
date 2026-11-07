"""Sondas Go (templates/tpl_*.go): `go vet` y `golangci-lint` v2 limpios por modulo (errcheck incluido).

El repo no lleva `go.mod`: las plantillas son archivos `package main` sueltos y el build del producto
(`artifact_lint_and_build`) escribe UN archivo en un scratch y corre `go vet <archivo>` / `go build <archivo>`, asi que un
`go.mod` en `templates/` no aporta (y varios `main` en un mismo paquete romperian `./...`). Cada sonda se valida aqui en un
modulo temporal propio, que es la forma por-modulo de ejecutar los linters.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engine.hydrator import TemplateHydrator

HYDRATOR = TemplateHydrator()
TEMPLATES = sorted(HYDRATOR.templates_dir / name for name in HYDRATOR.list_available_templates())
GO = shutil.which("go")
GOLANGCI = shutil.which("golangci-lint")


def _module(tmp_path: Path, tpl: Path) -> Path:
    assert tpl.name in TemplateHydrator().list_available_templates()  # solo plantillas que el producto hidrata
    mod = tmp_path / tpl.stem
    mod.mkdir()
    (mod / "main.go").write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
    (mod / "go.mod").write_text(f"module aepprobe/{tpl.stem}\n\ngo 1.22\n", encoding="utf-8")
    return mod


def test_templates_are_discovered() -> None:
    assert len(TemplateHydrator().list_available_templates()) >= 5


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.stem)
def test_go_vet_per_module(tmp_path: Path, tpl: Path) -> None:
    res = subprocess.run(["go", "vet", "./..."], cwd=_module(tmp_path, tpl), capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr


@pytest.mark.skipif(GOLANGCI is None or GO is None, reason="golangci-lint/go not installed")
@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.stem)
def test_golangci_lint_per_module_has_no_issues(tmp_path: Path, tpl: Path) -> None:
    res = subprocess.run(
        ["golangci-lint", "run", "--default=standard", "-E", "errcheck", "./..."],
        cwd=_module(tmp_path, tpl),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
