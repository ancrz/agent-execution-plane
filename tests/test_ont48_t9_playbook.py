"""ONT-48 T9 (G10): compact playbook <= 900 tokens; WF-10 uses the real aep_ctl contract."""

from __future__ import annotations

import asyncio
import json

import server


def _playbook(verbosity: str) -> dict:
    return json.loads(asyncio.run(server.discover(action="playbook", verbosity=verbosity, force_refresh=True)))


def test_summary_playbook_under_900_tokens() -> None:
    raw = json.dumps(_playbook("summary"), separators=(",", ":"))
    assert len(raw) // 4 <= 900, len(raw) // 4


def test_summary_shape_and_brief_equals_summary() -> None:
    s = _playbook("summary")
    assert all(":" not in r for r in s["rules_of_engagement"])
    assert all(set(r) == {"id", "name"} for r in s["workflow_recipes"])
    assert s["quick_reference"]["self_heal"]
    assert all(v is False for v in s["prerequisites_summary"].values())
    b = _playbook("brief")
    assert b["workflow_recipes"] == s["workflow_recipes"] and b["quick_reference"] == s["quick_reference"]


def test_detail_keeps_full_recipes_and_wf10_contract() -> None:
    d = _playbook("detail")
    wf10 = next(r for r in d["workflow_recipes"] if r["id"] == "WF-10")
    assert "steps" in wf10 and "target=" in wf10["steps"][0]
    assert len(d["rules_of_engagement"][0]) > 40
