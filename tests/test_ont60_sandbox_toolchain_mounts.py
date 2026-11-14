"""ONT-60 T2: toolchains linked outside the sandbox mounts are auto-mounted (ro) and reported."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

import server

BWRAP = shutil.which("bwrap")


def _make_tool(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "opt" / "faketool"
    (root / "bin").mkdir(parents=True)
    exe = root / "bin" / "faketool"
    exe.write_text("#!/bin/sh\necho faketool-ok\n")
    exe.chmod(0o755)
    links = tmp_path / "links"
    links.mkdir()
    (links / "faketool").symlink_to(exe)
    return root, links


def test_mount_root_is_install_root_dedup_and_skips_dangling(tmp_path: Path) -> None:
    root, links = _make_tool(tmp_path)
    (links / "faketool2").symlink_to(root / "bin" / "faketool")  # same root: deduplicated
    (links / "ghost").symlink_to(tmp_path / "nowhere" / "bin" / "ghost")  # dangling: ignored
    (links / "plain").write_text("not a symlink")
    assert server._toolchain_auto_mounts([links], []) == [str(root.resolve())]


def test_already_mounted_target_is_not_remounted(tmp_path: Path) -> None:
    root, links = _make_tool(tmp_path)
    assert server._toolchain_auto_mounts([links], [str(root.resolve())]) == []
    assert server._toolchain_auto_mounts([links], [str(tmp_path.resolve())]) == []


def test_blacklisted_root_is_never_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, links = _make_tool(tmp_path)
    monkeypatch.setattr(server.CapabilityGuard, "is_path_blacklisted", staticmethod(lambda p: str(root) in str(p)))
    assert server._toolchain_auto_mounts([links], []) == []


@pytest.mark.skipif(BWRAP is None, reason="bwrap not installed")
def test_sandbox_runs_a_tool_linked_outside_the_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, links = _make_tool(tmp_path)
    monkeypatch.setattr(server, "_SANDBOX_TOOL_LINK_DIRS", (str(links),))
    out = json.loads(asyncio.run(server.sandbox_run(command=f"{links}/faketool", ro_paths=[str(links)])))
    if out["status"] == "EXEC_FAILED" and "namespace" in out.get("stderr", ""):
        pytest.skip("sandbox cannot run in this environment")
    assert out["status"] == "SUCCESS", out
    assert "faketool-ok" in out["stdout"]
    assert out["auto_mounts"] == [str(root.resolve())]


@pytest.mark.skipif(BWRAP is None or shutil.which("go") is None, reason="bwrap or go not installed")
def test_go_version_inside_sandbox() -> None:
    out = json.loads(asyncio.run(server.sandbox_run(command="go version")))
    if out["status"] == "EXEC_FAILED" and "namespace" in out.get("stderr", ""):
        pytest.skip("sandbox cannot run in this environment")
    assert out["status"] == "SUCCESS", out
    assert out["stdout"].startswith("go version go")
