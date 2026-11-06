"""
Tests for D-08: capability manifest crash_forensics apport_fallback mode (ONT-38b-L1).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest import mock

import server
from engine.privilege import capability_manifest


def test_d08_crash_forensics_apport_fallback_on_host() -> None:
    """When coredumpctl is missing but /var/crash exists, crash_forensics reports ready=true and mode=apport_fallback."""
    # Under current environment, /var/crash exists and coredumpctl is absent
    if Path("/var/crash").is_dir():
        with mock.patch("engine.privilege.check_binary_prerequisites") as mock_prereqs:
            mock_prereqs.return_value = {
                "coredumpctl": {"installed": False},
                "journalctl": {"installed": True},
            }
            manifest = capability_manifest()
            cf = manifest["capabilities"]["crash_forensics"]
            assert cf["ready"] is True
            assert cf.get("mode") == "apport_fallback"

        # Also via server.discover
        raw = asyncio.run(server.discover(action="capabilities", verbosity="summary", force_refresh=True))
        data = json.loads(raw)
        cf_discover = data["capabilities"]["crash_forensics"]
        assert cf_discover["ready"] is True
        assert cf_discover.get("mode") == "apport_fallback"


def test_d08_crash_forensics_coredumpctl_mode() -> None:
    """When coredumpctl is installed, mode is coredumpctl and ready is True."""
    with mock.patch("engine.privilege.check_binary_prerequisites") as mock_prereqs:
        mock_prereqs.return_value = {
            "coredumpctl": {"installed": True},
            "journalctl": {"installed": True},
        }
        manifest = capability_manifest()
        cf = manifest["capabilities"]["crash_forensics"]
        assert cf["ready"] is True
        assert cf.get("mode") == "coredumpctl"


def test_d08_crash_forensics_ready_false_when_both_missing() -> None:
    """When neither coredumpctl nor /var/crash exists, ready is False."""
    with mock.patch("engine.privilege.check_binary_prerequisites") as mock_prereqs:
        mock_prereqs.return_value = {
            "coredumpctl": {"installed": False},
            "journalctl": {"installed": True},
        }
        with mock.patch("engine.privilege.Path.is_dir", return_value=False):
            manifest = capability_manifest()
            cf = manifest["capabilities"]["crash_forensics"]
            assert cf["ready"] is False
            assert cf.get("mode") == "none"
