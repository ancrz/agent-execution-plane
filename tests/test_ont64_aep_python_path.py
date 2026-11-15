"""ONT-64: aep_python.path is trimmed on directory boundaries, measured in UTF-8 bytes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from engine.primitives_orient import _aep_python

HOST_HOME = "/home/ancruz"
HOST_PY = f"{HOST_HOME}/Documents/workspaces/agent-execution-plane/.venv/bin/python"


def _path(monkeypatch: pytest.MonkeyPatch, exe: str, home: str = HOST_HOME) -> str:
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(home)))
    return _aep_python()["path"]


def test_short_path_under_home_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _path(monkeypatch, f"{HOST_HOME}/p/.venv/bin/python") == "~/p/.venv/bin/python"


def test_host_path_trims_on_component(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _path(monkeypatch, HOST_PY) == "…/workspaces/agent-execution-plane/.venv/bin/python"


def test_outside_home_long_path(monkeypatch: pytest.MonkeyPatch) -> None:
    exe = "/opt/some/very/long/prefix/for/an/interpreter/location/envs/project-x/bin/python"
    out = _path(monkeypatch, exe)
    assert out.startswith("…/") and len(out.encode()) <= 60
    assert exe.endswith(out[1:])  # tail of the original path
    assert exe[len(exe) - len(out[1:])] == "/"  # tail starts at a directory boundary


@pytest.mark.parametrize("name", ["x" * 200, "é" * 100, "日本語" * 40])
def test_giant_single_component(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    out = _path(monkeypatch, f"/opt/{name}")
    raw = out.encode()
    assert len(raw) <= 60
    raw.decode("utf-8")
    assert name.endswith(out[1:]) or out.startswith("…")


@pytest.mark.parametrize(
    "exe",
    [HOST_PY, "/a/" + "d/" * 40 + "python", "/usr/bin/python3", f"{HOST_HOME}/x/" + "y" * 80 + "/bin/python"],
)
def test_ellipsis_followed_by_slash(monkeypatch: pytest.MonkeyPatch, exe: str) -> None:
    out = _path(monkeypatch, exe)
    assert len(out.encode()) <= 60
    if out.startswith("…"):
        assert out.startswith("…/")
