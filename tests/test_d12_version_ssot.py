"""
Tests for D-12: single source of truth versioning via pyproject.toml (ONT-38b-L1).
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path

import server


def test_d12_pyproject_matches_server_version() -> None:
    """pyproject.toml project.version matches server.SERVER_VERSION and discover(action='capabilities')."""
    pyproj_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproj_path, "rb") as f:
        data = tomllib.load(f)

    raw_version = data["project"]["version"]
    assert raw_version == "0.2.8"

    expected_server_version = f"v{raw_version}"
    assert server.SERVER_VERSION == expected_server_version

    # Check via discover(action='capabilities') across verbosities
    for verbosity in ("detail", "summary", "terse"):
        res = asyncio.run(server.discover(action="capabilities", verbosity=verbosity, force_refresh=True))
        payload = json.loads(res)
        assert payload.get("server_version") == expected_server_version


def test_d12_changelog_has_028_entry_with_ont_milestones() -> None:
    """CHANGELOG.md contains [0.2.8] - 2026-11-05 entry summarizing ONT-29..ONT-38."""
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    content = changelog_path.read_text(encoding="utf-8")

    assert "## [0.2.8] - 2026-11-05" in content

    for milestone in (
        "ONT-29",
        "ONT-30",
        "ONT-31",
        "ONT-32",
        "ONT-33",
        "ONT-34",
        "ONT-35",
        "ONT-36",
        "ONT-37",
        "ONT-38",
    ):
        assert milestone in content, f"Milestone {milestone} missing from CHANGELOG.md"
