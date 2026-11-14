"""ONT-54 T5 (G47): playbook create gives a concrete run next_action; zero-savings estimate is omitted when compact."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import server
from engine.playbook import PlaybookStore

STEPS = [{"id": "s1", "tool": "process_inspect", "params": {"pid": 0, "limit": 2}}]


def _create(**kw: Any) -> dict[str, Any]:
    return json.loads(asyncio.run(server.playbook_run(action="create", description="d", **kw)))


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PlaybookStore:
    s = PlaybookStore(db_path=tmp_path / "pb.db")
    monkeypatch.setattr(server, "playbook_store", s)
    return s


def test_create_next_action_lists_required_params(store: PlaybookStore) -> None:
    res = _create(
        name="pb_hint",
        steps=STEPS,
        params_contract=[{"name": "target"}, {"name": "opt", "required": False}, {"name": "dflt", "default": 1}],
    )
    assert res["status"] == "OK"
    assert res["next_action"] == 'playbook_run(action="run", name="pb_hint", vars={"target": "<target>"})'


def test_create_without_params_has_bare_run(store: PlaybookStore) -> None:
    res = _create(name="pb_bare", steps=STEPS)
    assert res["next_action"] == 'playbook_run(action="run", name="pb_bare")'


def test_failed_create_keeps_generic_next_action(store: PlaybookStore) -> None:
    res = _create(name="pb_bad", steps=[{"id": "s1", "tool": "no_such_tool", "params": {}}])
    assert res["status"] == "LINT_ERROR" and "playbook_run(action=" not in res["next_action"]


def _batch(verbosity: str) -> dict[str, Any]:
    return json.loads(asyncio.run(server.playbook_run(action="batch", steps=STEPS, verbosity=verbosity)))


def test_zero_savings_omitted_in_compact_kept_in_detail() -> None:
    for mode in ("summary", "brief", "terse"):
        assert "token_savings_estimate" not in _batch(mode), mode
    assert _batch("detail")["token_savings_estimate"]["saved_bytes"] == 0


def test_positive_savings_kept_in_compact() -> None:
    res = json.loads(
        asyncio.run(
            server.playbook_run(
                action="batch", steps=STEPS, return_only="last", select_fields=["status", "pid"], verbosity="summary"
            )
        )
    )
    assert res["token_savings_estimate"]["saved_bytes"] > 0
