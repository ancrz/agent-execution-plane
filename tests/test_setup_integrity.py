"""First-install integrity: degraded (not ERROR) states when system prerequisites are missing."""

import contextlib

import playwright.sync_api as pw

from engine import headless_display


class _FakeChromium:
    def launch(self, **_kwargs):
        raise pw.Error("BrowserType.launch: error while loading shared libraries: libnss3.so")


class _FakePW:
    chromium = _FakeChromium()


def test_visual_inspect_missing_system_libs_is_display_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(pw, "sync_playwright", lambda: contextlib.nullcontext(_FakePW()))
    res = headless_display.visual_inspect("file:///nonexistent.html")
    assert res["status"] == "DISPLAY_UNAVAILABLE"
    assert "install-deps" in res["message"]


def test_sandbox_run_without_bwrap_is_degraded(monkeypatch) -> None:
    import asyncio
    import json

    import server

    monkeypatch.setattr(server.shutil, "which", lambda _name, *a, **k: None)
    res = json.loads(asyncio.run(server.sandbox_run("echo hi")))
    assert res["status"] == "DEGRADED"
    assert any("bubblewrap" in r for r in res["remediation"])
