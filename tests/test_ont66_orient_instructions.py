"""ONT-66 T6/T7: orient y discover(capabilities) llevan `gaps_open` + `aep_notice`; instrucciones MCP y playbook WF-0."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from test_ont66_notice_piggyback import _CLEAN, _reanalyze, repo  # noqa: F401  (fixture re-export)

import server

RELAY_LINE = "If a response has `aep_notice`, relay its `ask_user` to the user before continuing."


def _orient() -> dict[str, Any]:
    return json.loads(asyncio.run(server.default_primitives(action="run", name="orient", verbosity="summary")))


def _caps(verbosity: str) -> dict[str, Any]:
    return json.loads(asyncio.run(server.discover(action="capabilities", verbosity=verbosity)))


def test_instructions_carry_the_relay_line_within_budget() -> None:
    assert RELAY_LINE in server._INSTRUCTIONS
    line = next(ln for ln in server._INSTRUCTIONS.splitlines() if RELAY_LINE in ln)
    assert len(line.encode("utf-8")) <= 120
    assert len(server._INSTRUCTIONS.encode("utf-8")) <= 9500


def test_orient_reports_gaps_open_and_notice_only_when_findings_exist(repo: Path) -> None:  # noqa: F811
    out = _orient()
    assert out["result"]["gaps_open"] == 1 and out["aep_notice"]["count"] == 1
    _reanalyze(repo, _CLEAN)
    clean = _orient()
    assert "gaps_open" not in clean["result"] and "aep_notice" not in clean


def test_capabilities_terse_and_summary_carry_gaps_open_and_notice(repo: Path) -> None:  # noqa: F811
    for verbosity in ("terse", "summary"):
        out = _caps(verbosity)
        assert out["gaps_open"] == 1 and "ask_user" in out["aep_notice"]
    _reanalyze(repo, _CLEAN)
    for verbosity in ("terse", "summary"):
        out = _caps(verbosity)
        assert "gaps_open" not in out and "aep_notice" not in out


def test_playbook_wf0_tells_the_agent_to_attend_aep_notice() -> None:
    raw = asyncio.run(server.discover(action="playbook", verbosity="detail"))
    wf0 = next(r for r in json.loads(raw)["workflow_recipes"] if r["id"] == "WF-0")
    assert any("aep_notice" in step and "ask_user" in step for step in wf0["steps"])
