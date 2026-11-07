"""Dokimos audit (range 1b983f1..b605677): strict xfails for findings D-HR-1..D-HR-3, D-AE-1. Remove xfail when fixed."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from engine import harness_reconnect as hr
from engine import threads_extractors as tx
from tests.test_ont42a_harness_reconnect import _mk_proc, _pts_nr, _Rec


def test_find_harness_never_returns_non_ancestor(tmp_path: Path) -> None:
    _mk_proc(tmp_path, 100, 1, "/usr/bin/python3", _pts_nr(3))
    _mk_proc(tmp_path, 300, 1, "/home/u/.local/share/claude/versions/2.1.319", _pts_nr(0))  # sibling, not an ancestor
    res = hr.find_harness(tmp_path, 100, os.getuid(), target_harness="claude")
    assert res["found"] is False


def test_certify_requires_confirm_before_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    import server

    rec = _Rec()
    monkeypatch.setattr(hr, "real_adapters", lambda audit=None: rec.adapters())
    server._ipc_harness_reconnect({"mode": "certify"}, None, "t")
    assert rec.helper_calls == 0


def test_helper_payload_allowlist_is_reconnect_only() -> None:
    assert "hello world" not in hr.HELPER_SCRIPT


def test_control_plane_ipc_actions_visible_to_extractor() -> None:
    tree = ast.parse(Path("engine/privilege.py").read_text())
    value = tx.literal_dict_best_effort(tx.find_module_assign(tree, "CONTROL_PLANE_SCHEMA"))
    assert isinstance(value.get("ipc"), dict) and "harness_reconnect" in value["ipc"]["actions"]
    assert isinstance(value.get("backup"), dict)
