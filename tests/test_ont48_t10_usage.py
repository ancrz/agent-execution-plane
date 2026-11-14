"""ONT-48 T10 (G12): usage summary drops permanently-zero bytes/tokens in compact mode."""

from __future__ import annotations

import sqlite3

from engine.security import _ensure_audit_table, get_agent_usage_summary, record_audit_event


def _conn(details: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    _ensure_audit_table(conn)
    record_audit_event(conn, "a1", "discover", "capabilities", "FULL", "OK", details=details)
    return conn


def test_compact_without_sizes_drops_zero_fields() -> None:
    usage = get_agent_usage_summary(_conn({"latency_ms": 2.0}), compact=True)
    agent = usage["agents"]["a1"]
    assert "bytes" not in agent and "tokens" not in agent
    assert "bytes" not in agent["tools"]["discover"]
    assert usage["fields_unavailable"] == ["bytes", "tokens"]


def test_detail_keeps_shape() -> None:
    usage = get_agent_usage_summary(_conn({"latency_ms": 2.0}))
    assert usage["agents"]["a1"]["bytes"] == 0 and "fields_unavailable" not in usage


def test_compact_keeps_fields_when_ledger_has_sizes() -> None:
    usage = get_agent_usage_summary(_conn({"output_bytes": 400, "latency_ms": 1.0}), compact=True)
    assert usage["agents"]["a1"]["bytes"] == 400 and usage["agents"]["a1"]["tokens"] == 100
    assert "fields_unavailable" not in usage
