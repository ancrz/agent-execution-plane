"""
Tests for D-16: sandbox_run exports AEP_IN_SANDBOX=1 and skipif guard (ONT-38b-L1).
"""

from __future__ import annotations

import asyncio
import inspect
import json

import server
from tests.test_agent_experience_evaluation import test_sandbox_hides_the_host_workspace


def test_d16_sandbox_run_exports_aep_in_sandbox_env() -> None:
    """sandbox_run exports AEP_IN_SANDBOX=1 inside the jail."""
    res = asyncio.run(server.sandbox_run("echo __AEP_VAL=$AEP_IN_SANDBOX"))
    payload = json.loads(res)
    assert payload.get("status") == "SUCCESS"
    assert "__AEP_VAL=1" in payload.get("stdout", "")


def test_d16_skipif_marker_present() -> None:
    """test_sandbox_hides_the_host_workspace has pytest skipif marker for AEP_IN_SANDBOX."""
    marks = getattr(test_sandbox_hides_the_host_workspace, "pytestmark", [])
    skip_marks = [m for m in marks if m.name == "skipif"]
    assert len(skip_marks) >= 1
    assert "AEP_IN_SANDBOX" in str(skip_marks[0].kwargs.get("reason", ""))
    # The skip reason names the same variable that sandbox_run exports into the jail.
    assert "AEP_IN_SANDBOX" in inspect.getsource(server.sandbox_run)
