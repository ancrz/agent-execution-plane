"""Direct unit tests for the L3 contract-compaction helpers (D-01..D-05)."""

from __future__ import annotations

import server


def test_json_type_renders_unions() -> None:
    assert server._json_type({"type": "string"}) == "string"
    assert server._json_type({"anyOf": [{"type": "object"}, {"type": "null"}]}) == "object|null"
    assert server._json_type(None) == "any"


def test_actions_from_doc_inline_and_bullets() -> None:
    assert server._actions_from_doc('x action="a"|"b"|"c" y') == ["a", "b", "c"]
    doc = "intro\naction:\n  - 'run' (default): does x\n  - 'batch' | 'code': y\nother"
    assert server._actions_from_doc(doc) == ["run", "batch", "code"]
    assert server._actions_from_doc("nothing here") == []


def test_compact_tools_schema_shape() -> None:
    payload = {
        "status": "OK",
        "tools": {
            "t": {
                "description": 'action="x"|"y"',
                "parameters": {"properties": {"n": {"type": "integer", "default": 3}, "s": {"type": "string"}}},
            }
        },
        "degradation_matrix": {"big": 1},
        "preconditions": {"d": {}},
    }
    out = server._compact_tools_schema(payload)
    assert out["tools"] == {"t": {"params": ["n:integer=3", "s:string"], "actions": ["x", "y"]}}
    assert "degradation_matrix" not in out and "preconditions" not in out
