"""Executable evaluation of AEP's public agent-facing contracts.

The two strict xfails are intentional: they turn confirmed product gaps into
visible regression markers without making the existing release suite red.
When either behaviour is implemented, its test becomes an XPASS and must be
converted into a normal passing contract test.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CTL = PROJECT_ROOT / "scripts" / "aep-ctl"


def _run_ctl(*args: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(CTL), *args, "--json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(result.stdout)


def test_control_plane_schema_is_machine_discoverable() -> None:
    """The CLI can disclose its contract without parsing help text."""
    schema = _run_ctl("--schema")
    assert schema["status"] == "OK"
    domains = schema["domains"]
    assert isinstance(domains, dict)
    assert {"service", "network", "storage", "package", "backup", "security"} <= set(domains)


def test_invalid_control_action_returns_remediation() -> None:
    """An agent gets valid alternatives after an invalid action."""
    result = _run_ctl("storage", "not-an-action")
    assert result["status"] == "ERROR"
    assert result["valid"] == ["usage", "mounts", "disks"]


def test_sandbox_hides_the_host_workspace() -> None:
    """The default sandbox must not expose the AEP checkout implicitly."""
    import server

    result = json.loads(
        asyncio.run(server.sandbox_run(f"test ! -e {PROJECT_ROOT}"))
    )
    assert result["status"] == "SUCCESS"


@pytest.mark.xfail(
    strict=True,
    reason="Fresh ArtifactCatalog startup runs migrations before creating the base schema.",
)
def test_clean_home_bootstraps_the_mcp_runtime(tmp_path: Path) -> None:
    """A newly installed AEP runtime must import without pre-existing state."""
    env = os.environ | {
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import server; print('bootstrapped')"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bootstrapped"


@pytest.mark.xfail(
    strict=True,
    reason="The MCP advertises an audit domain, but the CLI schema omits it.",
)
def test_control_plane_schema_matches_advertised_mcp_domains() -> None:
    """The CLI schema and MCP aep_ctl domain contract must remain aligned."""
    schema = _run_ctl("--schema")
    domains = schema["domains"]
    assert isinstance(domains, dict)
    assert "audit" in domains
