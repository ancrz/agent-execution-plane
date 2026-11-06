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


def test_dedupe_mux_pool_only_outside_detail() -> None:
    mux = {"pool": {"slots": 1}, "requests_handled": 2}
    assert server._dedupe_mux_pool(mux, "summary") == {"requests_handled": 2}
    assert server._dedupe_mux_pool(mux, "detail") == mux
    assert "pool" in mux


def test_compact_control_plane_defaults_and_exceptions() -> None:
    base = {"privilege_tier": "DIMINISHED", "required_fs": [], "deterministic": True}
    schema = {
        "d": {
            "actions": ["a", "b", "c"],
            "description": "prose",
            "preconditions": {
                "a": dict(base),
                "b": dict(base),
                "c": {**base, "privilege_tier": "FULL"},
            },
        }
    }
    domains, defaults = server._compact_control_plane(schema)
    assert defaults == base
    assert domains["d"]["exceptions"] == {"c": {"privilege_tier": "FULL"}}
    assert "preconditions" not in domains["d"] and "description" not in domains["d"]


def test_project_fields_reports_unresolved_without_full_fallback() -> None:
    from engine.ipc_pool import project_fields

    data = {"status": "OK", "big": {"x": 1}}
    assert project_fields(data, ["nope"]) == {"unresolved_fields": ["nope"]}
    mixed = project_fields(data, ["status", "nope.deep"])
    assert mixed == {"status": "OK", "unresolved_fields": ["nope.deep"]}


def test_project_fields_indexed_paths_preserve_lists() -> None:
    from engine.ipc_pool import project_fields

    data = {"items": [{"a": 1, "b": 2}, {"a": 3, "b": 4}], "m": {"l": [[{"k": 1, "z": 0}]]}}
    out = project_fields(data, ["items.1.a", "items.0.b", "items.1.b", "m.l.0.0.k"])
    assert out["items"] == [{"a": 3, "b": 4}, {"b": 2}]
    assert out["m"]["l"] == [[{"k": 1}]]
