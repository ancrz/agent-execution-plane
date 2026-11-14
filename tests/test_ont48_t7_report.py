"""ONT-48 T7 (G15): autoevol(report) never answers OK/empty without a reason; non-field statuses are rejected."""

from __future__ import annotations

from pathlib import Path

import server
from engine import threads_field

ROOT = Path(__file__).resolve().parent.parent


def test_report_without_sig_and_no_candidates_is_param_error(monkeypatch) -> None:
    monkeypatch.setattr(threads_field, "list_candidates", lambda *a, **k: [])
    res = server._autoevol_report(ROOT, 6, True, None, None, None, 10)
    assert res["status"] == "PARAM_ERROR"
    assert res["reason"] == "sig required (from evol_hint)"


def test_report_without_sig_lists_existing_candidates(monkeypatch) -> None:
    monkeypatch.setattr(threads_field, "list_candidates", lambda *a, **k: [{"sig": "a" * 12}])
    res = server._autoevol_report(ROOT, 6, True, None, None, None, 10)
    assert res["status"] == "OK" and res["candidates"]


def test_report_with_non_field_status_rejected() -> None:
    sig = threads_field.field_sig("t", "a", "OK", "x")
    res = server._autoevol_report(ROOT, 6, True, sig, None, {"tool": "t", "action": "a", "status": "OK"}, 10)
    assert res["status"] == "REJECTED_NOT_FIELD_ERROR"
    assert "reason" in res
