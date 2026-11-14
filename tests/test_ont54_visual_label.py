"""ONT-54 T4 (G45): visual_inspect summary falls back to the URL's last segment; sha256 is the full digest."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import server
from engine import headless_display


@pytest.mark.parametrize(
    ("title", "url", "expected"),
    [
        ("", "file:///repo/README.md", "README.md"),
        (None, "https://example.com/a/b/?q=1#frag", "b"),
        ("  ", "https://example.com", "example.com"),
        ("Real Title", "file:///x.html", "Real Title"),
    ],
)
def test_visual_label(title: Any, url: str, expected: str) -> None:
    assert server._visual_label(title, url) == expected


def test_summary_uses_url_segment_when_title_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = {"status": "SUCCESS", "url": "file:///repo/README.md", "title": "", "screenshot_bytes": 7}
    monkeypatch.setattr(headless_display, "visual_inspect", lambda *a, **k: dict(fake))
    res = json.loads(asyncio.run(server.visual_inspect(url="file:///repo/README.md")))
    assert res["summary"].startswith("Rendered 'README.md' (7 bytes")
    assert res["status"] == "SUCCESS"


def test_screenshot_sha256_is_full_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("playwright")
    page = tmp_path / "p.html"
    page.write_text("<html><head><title>t</title></head><body>x</body></html>", encoding="utf-8")
    monkeypatch.setattr(headless_display, "SHM_DIR", tmp_path)
    res = headless_display.visual_inspect(page.as_uri())
    if res.get("status") != "SUCCESS":
        pytest.skip(f"headless browser unavailable: {res.get('status')}")
    assert len(res["screenshot_sha256"]) == 64
    assert res["screenshot_sha256"] == hashlib.sha256(Path(res["screenshot_path"]).read_bytes()).hexdigest()
