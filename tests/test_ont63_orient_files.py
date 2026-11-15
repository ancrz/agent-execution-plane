"""ONT-63 group (b): workspace-probe, file-fingerprint, dir-usage."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import server


@pytest.fixture(autouse=True)
def _data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "aep-data"
    home.mkdir()
    monkeypatch.setenv("AEP_DATA_HOME", str(home))
    return home


async def _run(name: str, params: dict) -> dict:
    return json.loads(await server.default_primitives(action="run", name=name, params=params, verbosity="detail"))


@pytest.mark.anyio
async def test_workspace_probe_git_python_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (repo / "a.py").write_text("x = 1\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "skip.js").write_text("//")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    full_env = {**os.environ, **env}
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=full_env)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=full_env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "i"], check=True, env=full_env)
    (repo / "b.py").write_text("y = 2\n")
    r = (await _run("workspace-probe", {"path": str(repo)}))["result"]
    assert r["git"]["branch"] == "main" and r["git"]["dirty_count"] == 1 and r["git"]["head"]
    assert "pyproject.toml" in r["manifests"]
    assert r["languages"]["python"] == 2 and "javascript" not in r["languages"]
    assert "pytest -q" in r["test_hints"]
    assert "sandbox_run(command='pytest -q'" in r["next_action"]
    assert r["truncated"] is False


@pytest.mark.anyio
async def test_workspace_probe_go_and_bad_path(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n")
    r = (await _run("workspace-probe", {"path": str(tmp_path)}))["result"]
    assert r["git"] is None and "go test ./..." in r["next_action"]
    assert (await _run("workspace-probe", {"path": str(tmp_path / "missing")}))["status"] == "PARAM_ERROR"
    assert (await _run("workspace-probe", {"path": os.path.expanduser("~/.ssh")}))["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_file_fingerprint_hash_and_metadata(tmp_path: Path) -> None:
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    link = tmp_path / "ln"
    link.symlink_to(f)
    r = (await _run("file-fingerprint", {"paths": [str(f), str(link), str(tmp_path / "nope")], "md5": True}))["result"]
    a, b, c = r["files"]
    assert a["sha256"] == hashlib.sha256(b"hello").hexdigest() and a["md5"] == hashlib.md5(b"hello").hexdigest()  # noqa: S324
    assert a["size"] == 5 and a["type"] == "file" and a["mode"].isdigit()
    assert b["type"] == "symlink" and b["symlink_target"] == str(f)
    assert c == {"path": str(tmp_path / "nope"), "exists": False}


@pytest.mark.anyio
async def test_file_fingerprint_rejects_protected_paths(tmp_path: Path) -> None:
    ssh = os.path.expanduser("~/.ssh")
    link = tmp_path / "to_ssh"
    link.symlink_to(ssh)
    data = await _run("file-fingerprint", {"paths": [ssh, ssh + "/id_rsa", "/etc/shadow", "/etc/sudoers.d", str(link)]})
    assert data["result"]["refused"] == 5
    for row in data["result"]["files"]:
        assert row["status"] == "PARAM_ERROR" and "sha256" not in row and "exists" not in row


@pytest.mark.anyio
async def test_file_fingerprint_data_home_db_allowed_other_refused(_data_home: Path) -> None:
    (_data_home / "x.db").write_bytes(b"db")
    (_data_home / "token.txt").write_text("t")
    rows = (await _run("file-fingerprint", {"paths": [str(_data_home / "x.db"), str(_data_home / "token.txt")]}))[
        "result"
    ]["files"]
    assert "sha256" in rows[0] and rows[1]["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_file_fingerprint_param_limits() -> None:
    assert (await _run("file-fingerprint", {"paths": []}))["status"] == "PARAM_ERROR"
    assert (await _run("file-fingerprint", {"paths": ["/tmp"] * 21}))["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_dir_usage_totals_top_and_no_symlink_follow(tmp_path: Path) -> None:
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "a").write_bytes(b"x" * 100_000)
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "b").write_bytes(b"y" * 10)
    (tmp_path / "ln").symlink_to(tmp_path / "big")
    r = (await _run("dir-usage", {"path": str(tmp_path), "top": 2}))["result"]
    assert r["files"] == 3  # two regular files + the symlink entry (never followed)
    assert r["apparent_bytes"] >= 100_010
    assert r["top"][0]["name"] == "big" and len(r["top"]) == 2
    assert r["truncated"] is False and "escalate" not in r


@pytest.mark.anyio
async def test_dir_usage_veto_and_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (await _run("dir-usage", {"path": os.path.expanduser("~/.gnupg")}))["status"] == "PARAM_ERROR"
    assert (await _run("dir-usage", {}))["status"] == "PARAM_ERROR"
    assert (await _run("dir-usage", {"path": str(tmp_path / "nope")}))["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_dir_usage_truncation_suggests_l2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.primitives_orient as po

    monkeypatch.setattr(po, "_DU_MAX_ENTRIES", 3)
    for i in range(6):
        (tmp_path / f"f{i}").write_text("x")
    r = (await _run("dir-usage", {"path": str(tmp_path)}))["result"]
    assert r["truncated"] is True and r["escalate"].startswith("L2")
