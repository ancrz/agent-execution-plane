"""
Tests for D-11: dynamic tool, recipe and domain counts (ONT-38b-L1).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import server


def test_d11_negative_grep_server_py() -> None:
    """Ensure hardcoded '15 herramientas', 'WF-1..WF-9', and cached '15 tools, 0 domains' are absent from server.py."""
    server_py_path = Path(__file__).resolve().parent.parent / "server.py"
    content = server_py_path.read_text(encoding="utf-8")

    matches = re.findall(r"15 herramientas|WF-1\.\.WF-9|15 tools, 0 domains", content)
    assert not matches, f"Found hardcoded internal strings in server.py: {matches}"
    # The count that replaced the hardcoded string is derived from the live FastMCP tool manager.
    live_count = len(server.mcp._tool_manager._tools)
    assert f"{live_count} herramientas FastMCP" in (server.discover.__doc__ or "")


def test_d11_derived_tool_count_in_docstring_and_description() -> None:
    """discover.__doc__ and FastMCP description dynamically reflect the current tool count."""
    total_tools = len(server.mcp._tool_manager._tools)
    expected_phrase = f"{total_tools} herramientas FastMCP"

    assert server.discover.__doc__ is not None
    assert expected_phrase in server.discover.__doc__

    disc_tool = server.mcp._tool_manager._tools.get("discover")
    assert disc_tool is not None
    assert disc_tool.description is not None
    assert expected_phrase in disc_tool.description


def test_d11_derived_recipe_range_in_playbook_next_action() -> None:
    """discover(action='playbook') next_action dynamically reflects the actual workflow recipe range."""
    raw = asyncio.run(server.discover(action="playbook", verbosity="summary", force_refresh=True))
    payload = json.loads(raw)
    next_action = payload.get("next_action", "")
    assert "WF-1..WF-11" in next_action


def test_d11_derived_counts_in_schema_summary() -> None:
    """discover(action='schema') summary reflects dynamic tool count and domain count."""
    total_tools = len(server.mcp._tool_manager._tools)
    total_domains = len(server.CONTROL_PLANE_SCHEMA)

    raw = asyncio.run(server.discover(action="schema", verbosity="summary", force_refresh=True))
    payload = json.loads(raw)
    summary = payload.get("summary", "")
    expected_substring = f"{total_tools} tools, {total_domains} domains"
    assert expected_substring in summary, f"Expected '{expected_substring}' in summary '{summary}'"
