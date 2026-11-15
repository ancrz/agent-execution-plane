"""ONT-63 D3: protected roots are compared in lexical AND resolved form (symlinked parents like ~/.docker)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
from engine.privilege import CapabilityGuard


@pytest.fixture
def linked_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """HOME whose ~/.docker and ~/.aws are symlinks to directories outside HOME."""
    home = tmp_path / "home"
    home.mkdir()
    real_docker = tmp_path / "mnt" / "docker-data"
    real_aws = tmp_path / "mnt" / "aws-data"
    real_docker.mkdir(parents=True)
    real_aws.mkdir(parents=True)
    (real_docker / "config.json").write_text('{"auths": {}}')
    (real_aws / "credentials").write_text("[default]\n")
    (home / ".docker").symlink_to(real_docker)
    (home / ".aws").symlink_to(real_aws)
    (home / "work").mkdir()
    ext_link = tmp_path / "elsewhere"
    ext_link.mkdir()
    (ext_link / "cfg").symlink_to(real_docker / "config.json")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    return {
        "home": home,
        "real_docker": real_docker,
        "real_aws": real_aws,
        "ext_file_link": ext_link / "cfg",
    }


async def _run(name: str, params: dict) -> dict:
    return json.loads(await server.default_primitives(action="run", name=name, params=params, verbosity="detail"))


def _paths(env: dict[str, Path]) -> list[str]:
    home = env["home"]
    return [
        str(home / ".docker" / "config.json"),  # through the symlinked parent
        str(env["real_docker"] / "config.json"),  # the real location
        str(env["ext_file_link"]),  # external symlink to the file
        str(home / ".aws" / "credentials"),
        str(env["real_aws"] / "credentials"),
    ]


def test_protected_roots_has_lexical_and_resolved_forms(linked_home: dict[str, Path]) -> None:
    roots = CapabilityGuard.protected_roots()
    assert str(linked_home["home"] / ".docker" / "config.json") in roots
    assert str(linked_home["real_docker"] / "config.json") in roots
    assert str(linked_home["home"] / ".aws") in roots and str(linked_home["real_aws"]) in roots
    assert len(roots) == len(set(roots)) and "/etc/shadow" in roots


def test_guard_rejects_every_form(linked_home: dict[str, Path]) -> None:
    for path in _paths(linked_home):
        assert CapabilityGuard.is_path_blacklisted(path), path
    assert not CapabilityGuard.is_path_blacklisted(str(linked_home["home"] / "work"))
    assert not CapabilityGuard.is_path_blacklisted(str(linked_home["real_docker"].parent))


@pytest.mark.anyio
async def test_primitives_reject_symlinked_credential_stores(linked_home: dict[str, Path]) -> None:
    for path in _paths(linked_home):
        fp = (await _run("file-fingerprint", {"paths": [path]}))["result"]["files"][0]
        assert fp["status"] == "PARAM_ERROR" and not {"sha256", "size", "mtime_ns"} & set(fp), path
        assert (await _run("path-users", {"path": path}))["status"] == "PARAM_ERROR", path
        assert (await _run("dir-usage", {"path": path}))["status"] == "PARAM_ERROR", path


@pytest.mark.anyio
async def test_dir_usage_on_real_directory_of_a_protected_root_is_refused(linked_home: dict[str, Path]) -> None:
    assert (await _run("dir-usage", {"path": str(linked_home["real_aws"])}))["status"] == "PARAM_ERROR"
    assert (await _run("dir-usage", {"path": str(linked_home["home"] / ".aws")}))["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_dir_usage_skips_symlinked_protected_children(linked_home: dict[str, Path]) -> None:
    r = (await _run("dir-usage", {"path": str(linked_home["home"])}))["result"]
    # ~/.aws is a protected root itself (skipped); ~/.docker is a symlink that is never followed, so its
    # protected config.json is never reached. Either way no credential file is entered or summed.
    assert r["skipped_protected"] == 1 and r["files"] == 1  # the .docker symlink entry only
    assert ".aws" not in {c["name"] for c in r["top"]}


def test_sandbox_veto_list_uses_protected_roots(linked_home: dict[str, Path]) -> None:
    vetoed = server._sandbox_vetoed_paths()
    assert set(CapabilityGuard.protected_roots()) <= set(vetoed)
    # a toolchain root that is an ancestor of the REAL vetoed path must not be auto-mounted
    assert server._auto_mount_root_reject_reason(linked_home["real_docker"].parent) is not None
    assert server._auto_mount_root_reject_reason(linked_home["real_aws"]) is not None


def test_no_other_module_builds_its_own_veto_list() -> None:
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for f in [root / "server.py", *(root / "engine").glob("*.py")]:
        if f.name == "privilege.py":
            continue
        text = f.read_text(encoding="utf-8")
        if "HOME_BLACKLIST" in text or "PATH_BLACKLIST" in text:
            offenders.append(f.name)
    assert offenders == [] and CapabilityGuard.protected_roots()
