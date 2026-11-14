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
    assert server._toolchain_auto_mounts([links], [])[0] == [str(root.resolve())]


def test_already_mounted_target_is_not_remounted(tmp_path: Path) -> None:
    root, links = _make_tool(tmp_path)
    assert server._toolchain_auto_mounts([links], [str(root.resolve())])[0] == []
    assert server._toolchain_auto_mounts([links], [str(tmp_path.resolve())])[0] == []


def test_blacklisted_root_is_never_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, links = _make_tool(tmp_path)
    monkeypatch.setattr(server.CapabilityGuard, "is_path_blacklisted", staticmethod(lambda p: str(root) in str(p)))
    assert server._toolchain_auto_mounts([links], [])[0] == []


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


# --------------------------------------------------------------------------- ONT-60 ciclo 2: vetoed ancestors
@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home" / "u"
    for sub in (".ssh", ".gnupg", ".local/share/agent-os", ".local/bin", "bin"):
        (home / sub).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AEP_DATA_HOME", raising=False)
    return home


def _link_to(tmp_path: Path, target: Path) -> Path:
    links = tmp_path / "vlinks"
    links.mkdir(exist_ok=True)
    for old in links.iterdir():
        old.unlink()
    (links / "x").symlink_to(target)
    return links


@pytest.mark.parametrize("target", ["/etc/shadow", "/", "/dev/null"])
def test_system_targets_are_never_mounted(tmp_path: Path, fake_home: Path, target: str) -> None:
    assert server.catalog is not None
    if not Path(target).exists():
        pytest.skip("target missing")
    mounts, skipped = server._toolchain_auto_mounts([_link_to(tmp_path, Path(target))], [])
    assert mounts == []
    for forbidden in ("/etc", "/dev", "/"):
        assert forbidden not in mounts
    if target != "/":
        assert skipped and skipped[0]["target"] == str(Path(target).resolve())


def test_home_bin_target_falls_back_to_binary_dir_never_home(tmp_path: Path, fake_home: Path) -> None:
    assert server.catalog is not None
    exe = fake_home / "bin" / "x"
    exe.write_text("#!/bin/sh\n")
    mounts, _ = server._toolchain_auto_mounts([_link_to(tmp_path, exe)], [])
    assert mounts == [str((fake_home / "bin").resolve())]
    assert str(fake_home) not in mounts


def test_local_bin_target_never_mounts_dot_local(tmp_path: Path, fake_home: Path) -> None:
    assert server.catalog is not None
    exe = fake_home / ".local" / "bin" / "x"
    exe.write_text("#!/bin/sh\n")
    mounts, _ = server._toolchain_auto_mounts([_link_to(tmp_path, exe)], [])
    assert str(fake_home / ".local") not in mounts and str(fake_home) not in mounts
    assert mounts == [str((fake_home / ".local" / "bin").resolve())]


def test_vetoed_dir_itself_is_skipped_with_reason(tmp_path: Path, fake_home: Path) -> None:
    assert server.catalog is not None
    secret = fake_home / ".ssh" / "key"
    secret.write_text("k")
    mounts, skipped = server._toolchain_auto_mounts([_link_to(tmp_path, secret)], [])
    assert mounts == [] and skipped and "vetoed" in skipped[0]["reason"]


def test_synthetic_go_style_install_mounts_its_root(tmp_path: Path, fake_home: Path) -> None:
    assert server.catalog is not None
    root = tmp_path / "mnt" / "apps" / "tools" / "go"
    (root / "bin").mkdir(parents=True)
    exe = root / "bin" / "go"
    exe.write_text("#!/bin/sh\n")
    mounts, skipped = server._toolchain_auto_mounts([_link_to(tmp_path, exe)], [])
    assert mounts == [str(root.resolve())] and skipped == []
