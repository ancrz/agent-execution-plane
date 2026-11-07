"""ONT-41 TC2: LKG/serving meta in discover(capabilities): emitted only when non-default, budgets intact."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import server
from tests.test_ont41_front import kill_backend, new_mgr, tree  # noqa: F401  (tree is a fixture)

NEW_KEYS = ("serving_from", "lkg_fingerprint", "reload_error", "lkg_module_drift")
STRUCT = {
    "type": "SyntaxError",
    "file": "engine/matcher.py",
    "line": 3,
    "msg": "invalid syntax",
    "fingerprint": "ab" * 8,
}


def caps(verbosity: str) -> dict[str, Any]:
    raw = asyncio.run(
        server.discover(action="capabilities", verbosity=verbosity, session_id="t-meta", force_refresh=True)
    )
    return json.loads(raw)


def tokens(payload: dict[str, Any]) -> int:
    t = payload.get("t")
    return int(t["tok"]) if isinstance(t, dict) and "tok" in t else int(payload["telemetry"]["estimated_tokens"])


def test_new_keys_absent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lambda: {})
    payload = caps("terse")
    assert not any(k in payload for k in NEW_KEYS)
    meta = server._get_live_meta()
    assert meta["serving_from"] is None and meta["reload_error"] is None and meta["lkg_module_drift"] is False


def lkg_meta() -> dict[str, Any]:
    return {
        "serving_from": "lkg",
        "lkg_fingerprint": "f" * 64,
        "last_reload_error": "[deterministic] Reload Gen 2 health failed: SyntaxError",
        "last_reload_error_struct": STRUCT,
        "failure_kind": "SERVING_LKG",
        "lkg_module_drift": True,
    }


def test_serving_lkg_meta_emitted_stale_forced_and_terse_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lkg_meta)
    terse = caps("terse")
    assert terse["serving_from"] == "lkg" and terse["failure_kind"] == "SERVING_LKG"
    assert terse["reload_error"] == "SyntaxError@matcher.py:3" and terse["lkg_module_drift"] is True
    assert terse["stale"] is True
    assert tokens(terse) <= 400, tokens(terse)  # discover terse stays <= 400 even in SERVING_LKG


def test_summary_budget_intact_in_serving_lkg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_BACKEND_META_GETTER", lkg_meta)
    summary = caps("summary")
    assert summary["reload_error"] == STRUCT and summary["serving_from"] == "lkg" and tokens(summary) < 6000, tokens(
        summary
    )


def test_backend_process_reports_serving_lkg_end_to_end(tree: Path) -> None:  # noqa: F811
    async def _run() -> None:
        mgr = new_mgr()
        try:
            await mgr.get_or_start_backend()
            clean = json.loads(await mgr.call_tool("discover", {"action": "capabilities", "verbosity": "terse"}))
            assert not any(k in clean for k in NEW_KEYS)
            for _ in range(3):
                kill_backend(mgr)
                await mgr.get_or_start_backend()
            terse = json.loads(await mgr.call_tool("discover", {"action": "capabilities", "verbosity": "terse"}))
            assert terse["serving_from"] == "lkg" and terse["failure_kind"] == "SERVING_LKG"
            assert terse["lkg_fingerprint"] == str(mgr.lkg_fingerprint)[:8] and terse["stale"] is True
            assert tokens(terse) <= 400
            assert "lkg_module_drift" not in terse and "reload_error" not in terse
        finally:
            await mgr.shutdown()

    asyncio.run(_run())
