"""ONT-59 T4: toolchain Go explícito y soportado (engine/go_toolchain.py + discover + aviso en build)."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import stat
from pathlib import Path

import pytest

import server
from engine import catalog as catalog_mod
from engine import go_toolchain
from engine.catalog import ArtifactCatalog
from engine.kanban import KanbanBoard
from engine.privilege import _PrivilegeCache

GO = shutil.which("go")


@pytest.fixture(autouse=True)
def _fresh_cache():
    go_toolchain.reset_cache()
    yield
    go_toolchain.reset_cache()


def _fake_go(tmp_path: Path, version: str, goroot: Path | None = None) -> Path:
    """Un 'go' falso que responde a `go env GOVERSION|GOROOT`."""
    goroot = goroot or tmp_path / "goroot"
    (goroot / "bin").mkdir(parents=True, exist_ok=True)
    gofmt = goroot / "bin" / "gofmt"
    gofmt.write_text("#!/bin/sh\ncat\n")
    gofmt.chmod(gofmt.stat().st_mode | stat.S_IXUSR)
    fake = tmp_path / "bin" / "go"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text(
        f'#!/bin/sh\nif [ "$1 $2" = "env GOVERSION" ]; then echo {version}; exit 0; fi\n'
        f'if [ "$1 $2" = "env GOROOT" ]; then echo {goroot}; exit 0; fi\nexit 1\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("go1.27.4", True),
        ("go1.26.11", True),
        ("go1.26", True),
        ("go1.25.9", False),
        ("go1.22.5", False),
        ("go2.0", True),
        ("garbage", False),
        (None, False),
    ],
)
def test_supported_policy(version: str | None, expected: bool) -> None:
    assert go_toolchain.GO_SUPPORTED_MIN == "1.26"
    assert go_toolchain.supported(version) is expected


def test_major_minor() -> None:
    assert go_toolchain.major_minor("go1.27.4") == "1.27"
    assert go_toolchain.major_minor("nope") is None


def test_version_and_gofmt_resolved_from_goroot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_go(tmp_path, "go1.27.4")
    monkeypatch.setenv("AEP_GO_BIN", str(fake))
    assert go_toolchain.go_bin() == str(fake)
    assert go_toolchain.go_version() == "go1.27.4"
    assert go_toolchain.gofmt_path() == str(tmp_path / "goroot" / "bin" / "gofmt")
    info = go_toolchain.go_info()
    assert info["version"] == "go1.27.4" and info["supported"] is True and info["gofmt"].endswith("gofmt")


def test_version_is_cached_per_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_go(tmp_path, "go1.27.4")
    monkeypatch.setenv("AEP_GO_BIN", str(fake))
    assert go_toolchain.go_version() == "go1.27.4"
    fake.write_text("#!/bin/sh\necho go1.1.1\n")
    assert go_toolchain.go_version() == "go1.27.4"  # cache hit, no re-exec
    go_toolchain.reset_cache()
    assert go_toolchain.go_version() == "go1.1.1"


def test_aep_go_bin_from_toolchain_env_and_fallback_to_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_go(tmp_path, "go1.26.11")
    monkeypatch.delenv("AEP_GO_BIN", raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "toolchain.env").write_text(
        f"# setup\nAEP_GO_CHANNEL=stable\nAEP_GO_BIN='{fake}'\nAEP_GO_VERSION=1.26.11\n", encoding="utf-8"
    )
    assert go_toolchain.read_toolchain_env()["AEP_GO_CHANNEL"] == "stable"
    assert go_toolchain.go_bin() == str(fake)
    assert go_toolchain.go_info()["channel"] == "stable"
    # ruta no ejecutable en toolchain.env -> cae a PATH
    (tmp_path / "data" / "toolchain.env").write_text("AEP_GO_BIN=/no/such/go\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(fake.parent))
    assert go_toolchain.go_bin() == str(fake)


def test_no_go_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEP_GO_BIN", raising=False)
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert go_toolchain.go_bin() is None and go_toolchain.go_version() is None and go_toolchain.gofmt_path() is None
    assert go_toolchain.go_info()["supported"] is False


def test_discover_capabilities_detail_has_go_block_and_terse_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        go_toolchain, "go_info", lambda: {"version": "go1.27.4", "gofmt": "/x/gofmt", "supported": True}
    )
    detail = json.loads(asyncio.run(server.discover(action="capabilities", verbosity="detail", force_refresh=True)))
    assert detail["go"] == {"version": "go1.27.4", "gofmt": "/x/gofmt", "supported": True}
    terse = json.loads(asyncio.run(server.discover(action="capabilities", verbosity="terse", force_refresh=True)))
    assert "go" not in terse


class _FakeEmbedder:
    is_available = True

    def embed(self, text: str) -> list[float]:
        return [0.0] * 384


@pytest.fixture
def build_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(catalog_mod, "get_instance", _FakeEmbedder)
    db = tmp_path / "artifacts.db"
    monkeypatch.setattr(server, "catalog", ArtifactCatalog(db_path=db))
    monkeypatch.setattr(server, "kanban", KanbanBoard(db_path=db))
    bin_dir = tmp_path / "bin_out"
    bin_dir.mkdir()
    monkeypatch.setattr(server, "TEMP_BIN_DIR", bin_dir)
    monkeypatch.setenv("AEP_FORCE_TIER", "6rw-")
    _PrivilegeCache.reset()
    yield tmp_path
    _PrivilegeCache.reset()


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
def test_build_with_outdated_toolchain_warns_but_succeeds(build_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(go_toolchain, "go_version", lambda: "go1.22.5")
    res = json.loads(
        asyncio.run(
            server.artifact_lint_and_build(
                action="build", template_name="mem-stat", name="t59_outdated", verbosity="detail"
            )
        )
    )
    assert res["status"] == "SUCCESS"
    assert res["toolchain_outdated"] is True and res["severity"] == "WARN"
    assert "go1.22.5" in res["summary"] and "1.26" in res["summary"]


@pytest.mark.skipif(GO is None, reason="go toolchain not installed")
def test_build_with_supported_toolchain_has_no_warning(build_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(go_toolchain, "go_version", lambda: "go1.27.4")
    res = json.loads(
        asyncio.run(
            server.artifact_lint_and_build(action="build", template_name="mem-stat", name="t59_ok", verbosity="detail")
        )
    )
    assert res["status"] == "SUCCESS" and "toolchain_outdated" not in res
    assert res["severity"] != "WARN"
    assert re.fullmatch(r"go\d+\.\d+(\.\d+)?", res["toolchain"])


def test_server_never_shells_out_to_bare_go() -> None:
    """vet/build/fmt/fix usan go_toolchain.go_bin() (AEP_GO_BIN), nunca `go` por PATH a pelo."""
    src = (Path(server.__file__)).read_text(encoding="utf-8")
    assert '["go",' not in src
