"""Backlog: `aep_ctl` honra `select_fields` (project_fields) y reporta `unresolved_fields`."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import server


def _call(**kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(server.aep_ctl(**kw)))


def test_select_fields_projects_schema_payload() -> None:
    full = _call(action="schema", verbosity="summary")
    res = _call(action="schema", verbosity="summary", select_fields=["status"])
    assert res["status"] == full["status"]
    assert set(res) == {"status"}


def test_select_fields_reports_unresolved() -> None:
    res = _call(action="schema", verbosity="summary", select_fields=["status", "no.such.path"])
    assert res["unresolved_fields"] == ["no.such.path"]
    assert "status" in res


def test_without_select_fields_payload_is_unchanged() -> None:
    res = _call(action="schema", verbosity="summary")
    assert len(res) > 1 and "unresolved_fields" not in res
