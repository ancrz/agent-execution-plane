"""
Engine: telemetry.py — Per-Request Resource Attribution, Token Estimation & Agent-Brief Envelope.

Provides low-overhead telemetry (RSS KiB, FD count, latency_ms, output_bytes, estimated_tokens)
and response normalization (summary/detail/brief modes, pagination cursors, and structured
agent_brief envelopes) without breaking backward-compatible JSON keys.

Topos: telemetry.py -> stdlib only (leaf module, zero internal imports, zero cycles).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def _self_resources() -> tuple[int, int]:
    """Return (rss_kb, fd_count) for the current process in <0.1ms."""
    rss_kb = 0
    fd_count = 0
    with contextlib.suppress(OSError, ValueError):
        status_path = Path("/proc/self/status")
        if status_path.exists():
            for line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split(":", 1)[1].strip().split()
                    if parts:
                        rss_kb = int(parts[0])
                    break
    with contextlib.suppress(OSError):
        fd_count = len(os.listdir("/proc/self/fd"))
    return rss_kb, fd_count


_STARTUP_RSS_KB, _STARTUP_FD_COUNT = _self_resources()


class RequestTelemetry:
    """Measures wall-clock latency, RSS delta, FD delta, serialized bytes, and estimated tokens."""

    def __init__(self, tool_name: str, action: str = "default") -> None:
        self.request_id = f"req_{uuid.uuid4().hex[:10]}"
        self.tool_name = tool_name
        self.action = action
        self.start_ns = time.perf_counter_ns()
        self.rss_before_kb, self.fd_before = _self_resources()

    def finish(self, serialized_bytes: int) -> dict[str, Any]:
        elapsed_ms = round((time.perf_counter_ns() - self.start_ns) / 1_000_000, 2)
        rss_after_kb, fd_after = _self_resources()
        return {
            "request_id": self.request_id,
            "tool": self.tool_name,
            "action": self.action,
            "latency_ms": elapsed_ms,
            "output_bytes": serialized_bytes,
            "estimated_tokens": max(1, round(serialized_bytes / 4)),
            "rss_kb": rss_after_kb,
            "rss_delta_kb": rss_after_kb - self.rss_before_kb,
            "rss_since_startup_kb": rss_after_kb - _STARTUP_RSS_KB,
            "fd_count": fd_after,
            "fd_delta": fd_after - self.fd_before,
        }


def infer_severity(status: str) -> str:
    st = (status or "OK").upper()
    if st in (
        "OK",
        "SUCCESS",
        "APPROVED",
        "CACHE_HIT",
        "ALLOWED",
        "SUPPORTED",
        "QUEUED",
        "PROMOTED",
        "CREATED",
        "DRY_RUN",
    ):
        return "INFO"
    if st in (
        "DEGRADED",
        "DIMINISHED",
        "CACHE_MISS",
        "PARTIAL",
        "UNSUPPORTED",
        "DISPLAY_UNAVAILABLE",
        "HOLD",
    ):
        return "WARN"
    return "ERROR"


MAX_SAFE_JSON_BYTES = 180_000


def _clamp_oversized_payload(payload: dict[str, Any], max_bytes: int = MAX_SAFE_JSON_BYTES) -> bool:
    """Prevent MCP stdio JSON-RPC line-buffer overflows by clamping huge nested lists/strings in-place."""
    clamped = False
    for k, v in list(payload.items()):
        if k in ("envelope", "telemetry"):
            continue
        if isinstance(v, str) and len(v) > 32_000 and k != "screenshot_base64":
            payload[k] = v[-32_000:]
            payload[f"{k}_clamped"] = True
            clamped = True
        elif isinstance(v, list) and len(v) > 50:
            payload[f"{k}_total_count"] = len(v)
            payload[k] = v[:50]
            clamped = True
        elif isinstance(v, dict) and len(json.dumps(v, ensure_ascii=False)) > max_bytes // 2:
            items = list(v.items())
            if len(items) > 50:
                payload[f"{k}_total_keys"] = len(items)
                payload[k] = dict(items[:50])
                clamped = True
    return clamped


def attach_envelope(
    payload: dict[str, Any],
    tracker: RequestTelemetry,
    *,
    verbosity: str = "detail",
    summary: str | None = None,
    evidence: Any | None = None,
    next_action: str | None = None,
    truncated: bool | None = None,
    cursor: str | None = None,
) -> str:
    """Attach telemetry and normalized agent-brief envelope fields while preserving existing keys."""
    mode = (verbosity or "detail").strip().lower()
    status_val = str(payload.get("status") or payload.get("verdict") or "OK")
    sev = infer_severity(status_val)

    if truncated is not None:
        payload["truncated"] = truncated
    elif "truncated" not in payload:
        payload["truncated"] = False

    if cursor is not None or "cursor" not in payload:
        payload["cursor"] = cursor

    if summary is None:
        summary = (
            payload.get("message")
            or payload.get("error")
            or payload.get("note")
            or f"{tracker.tool_name}:{tracker.action} completed with status {status_val}"
        )

    if next_action is None:
        if sev == "ERROR":
            next_action = "Inspect 'error' or 'valid' fields and retry with corrected parameters."
        elif payload.get("truncated"):
            next_action = "Pass verbosity='detail' or increase 'limit' / use 'cursor' to inspect remaining items."
        else:
            next_action = "Proceed with the next step in the agent workflow."

    envelope: dict[str, Any] = {
        "status": status_val,
        "severity": sev,
        "summary": summary,
        "truncated": bool(payload.get("truncated", False)),
        "cursor": payload.get("cursor"),
        "next_action": next_action,
    }
    if evidence is not None:
        envelope["evidence"] = evidence

    payload.setdefault("severity", sev)
    payload.setdefault("summary", summary)
    payload.setdefault("next_action", next_action)
    payload["envelope"] = envelope

    # Provisional serialization to compute exact byte & token footprint and guard JSON-RPC frame size
    provisional = json.dumps(payload, indent=2 if mode != "brief" else None, ensure_ascii=False)
    if len(provisional.encode("utf-8")) > MAX_SAFE_JSON_BYTES and _clamp_oversized_payload(payload):
        payload["truncated"] = True
        envelope["truncated"] = True
        provisional = json.dumps(payload, indent=2 if mode != "brief" else None, ensure_ascii=False)
    payload["telemetry"] = tracker.finish(len(provisional.encode("utf-8")))
    return json.dumps(payload, indent=2 if mode != "brief" else None, ensure_ascii=False)
