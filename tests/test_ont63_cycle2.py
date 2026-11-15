"""ONT-63 cycle 2: instructions size, aep_python, probe port cap, credential-store vetoes, dir-usage skips."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import server
from engine.privilege import CapabilityGuard

_STORES = (".aws", ".config/gcloud", ".kube", ".docker/config.json", ".ssh", ".gnupg")


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    for rel in _STORES:
        target = home / rel
        if rel.endswith(".json"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True)
            (target / "credentials").write_text("secret-material" * 100)
    (home / "work").mkdir()
    (home / "work" / "a.txt").write_text("x" * 1000)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AEP_DATA_HOME", str(tmp_path / "data"))
    return home


async def _run(name: str, params: dict) -> dict:
    return json.loads(await server.default_primitives(action="run", name=name, params=params, verbosity="detail"))


def test_instructions_mention_wf0_within_budget() -> None:
    assert "WF-0" in server._INSTRUCTIONS and "WF-1..WF-11" in server._INSTRUCTIONS
    assert len(server._INSTRUCTIONS.encode()) <= 9400


@pytest.mark.anyio
async def test_host_info_reports_aep_python() -> None:
    import sys

    py = (await _run("host-info", {}))["result"]["aep_python"]
    assert len(py["path"].encode()) <= 60 and py["version"].count(".") >= 1
    home = str(Path.home())
    expected = "~" + sys.executable[len(home) :] if sys.executable.startswith(home + "/") else sys.executable
    assert py["path"] == expected or (py["path"].startswith("…") and expected.endswith(py["path"][1:]))
    summary = json.loads(await server.default_primitives(action="run", name="orient", verbosity="summary"))
    assert summary["result"]["aep_python"] == py


@pytest.mark.anyio
async def test_legacy_range_args_capped_at_1024() -> None:
    big = json.loads(await server.aep_ctl(domain="network", action="probe", name="127.0.0.1", args="1-3000"))
    assert big["status"] == "PARAM_ERROR" and "escáner" in big["error"]
    huge = json.loads(await server.aep_ctl(domain="network", action="probe", name="127.0.0.1", args="1-999999999"))
    assert huge["status"] == "PARAM_ERROR"
    ok = json.loads(await server.aep_ctl(domain="network", action="probe", name="127.0.0.1", args="1-3,22"))
    assert ok["status"] == "OK" and ok["scanned_ports"] == 4


@pytest.mark.parametrize("rel", _STORES)
def test_guard_blacklists_credential_stores(fake_home: Path, rel: str) -> None:
    assert CapabilityGuard.is_path_blacklisted(str(fake_home / rel))
    link = fake_home / "work" / "link"
    link.symlink_to(fake_home / rel)
    assert CapabilityGuard.is_path_blacklisted(str(link))
    assert not CapabilityGuard.is_path_blacklisted(str(fake_home / "work"))


@pytest.mark.anyio
@pytest.mark.parametrize("rel", [".aws", ".config/gcloud", ".kube", ".docker/config.json"])
async def test_primitives_refuse_credential_stores_even_via_symlink(fake_home: Path, rel: str) -> None:
    link = fake_home / "work" / "lnk"
    link.symlink_to(fake_home / rel)
    for path in (str(fake_home / rel), str(link)):
        fp = (await _run("file-fingerprint", {"paths": [path]}))["result"]["files"][0]
        assert fp["status"] == "PARAM_ERROR" and "sha256" not in fp
        assert (await _run("dir-usage", {"path": path}))["status"] == "PARAM_ERROR"
        assert (await _run("path-users", {"path": path}))["status"] == "PARAM_ERROR"


@pytest.mark.anyio
async def test_dir_usage_skips_protected_children(fake_home: Path) -> None:
    r = (await _run("dir-usage", {"path": str(fake_home)}))["result"]
    assert r["skipped_protected"] == len(_STORES)
    names = {c["name"] for c in r["top"]}
    assert names.isdisjoint({".aws", ".kube", ".ssh", ".gnupg"}) and "work" in names
    assert r["apparent_bytes"] < 2000  # the credential files (1500 B each) are not summed
