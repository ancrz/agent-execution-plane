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
import re
import time
import uuid
from pathlib import Path
from typing import Any

from engine.threads_field import field_sig


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
        "ARCHIVED",
        "UNARCHIVED",
        "PRUNED",
        "DEMOTED",
        "REEVALUATED",
        "REINDEXED",
        "CLEAN",
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
        "WARN",
    ):
        return "WARN"
    return "ERROR"


MAX_SAFE_JSON_BYTES = 180_000

# ONT-43 field report. Signal rule: a status is a TOOL FAILURE worth reporting only if it is `ERROR`, `*_ERROR`
# (PARAM_ERROR, ...), `EXEC_FAILED` or `FAILED`. Everything else is NOT a failure signal: policy denials
# (PERMISSION_DENIED, TIER_DENIED, BLOCKED, REJECTED, ...) are the governance layer working as designed, and
# INVALID_ACTION / NOT_FOUND are caller mistakes. A whitelist (not "severity == ERROR", which is the default for any
# unknown status) keeps denials out by construction.
_FIELD_ERROR_STATUSES = frozenset({"ERROR", "EXEC_FAILED", "FAILED"})
_FIELD_NO_HINT_MODES = frozenset({"brief", "terse", "cached"})
_ERROR_CLASS_KEYS = ("error_class", "error_type", "exception")
_ERROR_CLASS_MAX = 40
_NON_WORD_RE = re.compile(r"[^a-z0-9_]+")


def is_field_error_status(status: str) -> bool:
    st = (status or "").strip().upper()
    return st in _FIELD_ERROR_STATUSES or st.endswith("_ERROR")


# ONT-47 T6: exception-looking token at the start of a stderr line (e.g. "FileNotFoundError: [Errno 2] ...").
_STDERR_EXC_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b", re.MULTILINE)


def normalize_error_class(payload: dict[str, Any]) -> str:
    """
    Stable class of a failure (never the message). Priority: explicit exception/class key, else the FIRST TOKEN of
    `error`, else the LAST exception-looking line of `stderr` (ONT-47 T6), else "unknown".
    """
    raw: Any = next((payload[k] for k in _ERROR_CLASS_KEYS if payload.get(k)), None)
    if raw is None:
        text = str(payload.get("error") or "").strip()
        raw = text.split(None, 1)[0] if text else ""
        if not raw and isinstance(payload.get("stderr"), str):
            found = _STDERR_EXC_RE.findall(payload["stderr"])
            raw = found[-1] if found else ""
    if isinstance(raw, type):
        raw = raw.__name__
    cls = _NON_WORD_RE.sub("", str(raw).lower().split(".")[-1].split(":")[0])
    return cls[:_ERROR_CLASS_MAX] or "unknown"


def _clamp_oversized_payload(payload: dict[str, Any], max_bytes: int = MAX_SAFE_JSON_BYTES) -> bool:
    """Prevent MCP stdio JSON-RPC line-buffer overflows by clamping huge nested lists/strings in-place."""
    clamped = False
    for k, v in list(payload.items()):
        if k in ("envelope", "telemetry", "t"):
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
    severity: str | None = None,
    summary: str | None = None,
    evidence: Any | None = None,
    next_action: str | None = None,
    truncated: bool | None = None,
    cursor: str | None = None,
    telemetry: bool | None = None,
) -> str:
    """Attach telemetry and normalized agent-brief envelope fields while preserving existing keys."""
    mode = (verbosity or "detail").strip().lower()
    status_val = str(payload.get("status") or payload.get("verdict") or "OK")
    sev = str(severity or payload.get("severity") or infer_severity(status_val))

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

    is_compact = mode in ("summary", "brief", "terse", "cached")
    is_unindented = mode in ("brief", "terse", "cached")
    indent_val = None if is_unindented else 2

    payload.setdefault("status", status_val)
    payload["severity"] = sev
    payload.setdefault("summary", summary)
    payload.setdefault("next_action", next_action)
    if evidence is not None:
        payload.setdefault("evidence", evidence)

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

    # ONT-43: tiny evolution hint on tool failures (no raw error text; omitted in terse/brief/cached modes).
    # `autoevol(report)` never hints about itself.
    if (
        mode not in _FIELD_NO_HINT_MODES
        and is_field_error_status(status_val)
        and not (tracker.tool_name == "autoevol" and tracker.action == "report")
    ):
        eclass = normalize_error_class(payload)
        sig = field_sig(tracker.tool_name, tracker.action, status_val, eclass)
        status_tok = str(status_val).upper()
        payload["evol_hint"] = {
            "sig": sig,
            "status": status_tok,
            "error_class": eclass,
            "report": (
                f"autoevol(action='report', sig='{sig}', report={{tool: '{tracker.tool_name}', "
                f"action: '{tracker.action}', status: '{status_tok}', error_class: '{eclass}', expected, observed}})"
            ),
        }

    # In detail mode (and default): preserve payload['envelope'] for backward compatibility.
    # In compact modes (summary, brief, terse, cached): omit nested payload['envelope'] completely (GAP-OM-19).
    if not is_compact:
        payload["envelope"] = envelope
    elif "envelope" in payload:
        payload.pop("envelope", None)

    # Provisional serialization to compute exact byte & token footprint and guard JSON-RPC frame size
    provisional = json.dumps(payload, indent=indent_val, ensure_ascii=False)
    if len(provisional.encode("utf-8")) > MAX_SAFE_JSON_BYTES and _clamp_oversized_payload(payload):
        payload["truncated"] = True
        if not is_compact:
            envelope["truncated"] = True
        provisional = json.dumps(payload, indent=indent_val, ensure_ascii=False)

    prov_bytes = len(provisional.encode("utf-8"))
    elapsed_ms = round((time.perf_counter_ns() - tracker.start_ns) / 1_000_000, 2)
    estimated_tokens = max(1, round(prov_bytes / 4))

    # Telemetry configuration:
    if is_compact:
        if telemetry is True:
            payload["telemetry"] = tracker.finish(prov_bytes)
            payload.pop("t", None)
        elif telemetry is False:
            payload.pop("telemetry", None)
            payload.pop("t", None)
        else:
            payload["t"] = {"ms": elapsed_ms, "tok": estimated_tokens}
            payload.pop("telemetry", None)
    else:
        if telemetry is not False:
            payload["telemetry"] = tracker.finish(prov_bytes)
            payload.pop("t", None)
        else:
            payload.pop("telemetry", None)
            payload.pop("t", None)

    return json.dumps(payload, indent=indent_val, ensure_ascii=False)
