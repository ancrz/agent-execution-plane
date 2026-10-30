"""
Engine: headless_display.py  (SPEC-OM-5: Headless Visual & Display Actuator)

Desacopla la "visión" de la máquina física: renderiza y captura UIs en un servidor sin
monitor. Usa Chromium headless nativo de Playwright (no requiere Xvfb ni sudo). Xvfb/cage
queda como ruta opcional para apps que exijan un display X real; no es el camino primario.

Capturas en /dev/shm (RAM pura), destruidas tras la prueba. FAIL-SOFT: si Playwright o el
navegador no están, devuelve DISPLAY_UNAVAILABLE sin lanzar.

Topos: server.py -> headless_display.py (A->B). Sin acoplamiento con otros módulos de AEP.
"""

import base64
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("aep.display")

SHM_DIR = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path("/tmp")
MAX_SHM_SCREENSHOTS = 5


def _prune_old_shm_screenshots() -> None:
    """Keep at most MAX_SHM_SCREENSHOTS in /dev/shm so RAM tmpfs stays bounded."""
    try:
        shots = sorted(SHM_DIR.glob("aep_shot_*.png"), key=lambda p: p.stat().st_mtime)
        while len(shots) > MAX_SHM_SCREENSHOTS:
            oldest = shots.pop(0)
            oldest.unlink(missing_ok=True)
    except OSError as e:
        logger.debug("Failed pruning old shm screenshots: %s", e)


def visual_inspect(
    url: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    selector: str | None = None,
    full_page: bool = True,
    return_base64: bool = False,
    timeout_ms: int = 15000,
) -> dict[str, Any]:
    """Renderiza `url` en Chromium headless y captura un screenshot.
    `url` puede ser http(s):// o un file:// local. FAIL-SOFT ante ausencia de navegador."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "status": "DISPLAY_UNAVAILABLE",
            "message": "Playwright no instalado. pip install playwright && playwright install chromium",
        }

    shot_path = SHM_DIR / f"aep_shot_{uuid.uuid4().hex[:12]}.png"
    start = time.time()
    text_excerpt = ""
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--password-store=basic", "--use-mock-keychain"],
                )
            except (RuntimeError, OSError) as exc:
                return {
                    "status": "DISPLAY_UNAVAILABLE",
                    "message": f"No se pudo lanzar Chromium: {exc}. Ejecuta: playwright install chromium",
                }
            try:
                page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
                page.goto(url, timeout=timeout_ms, wait_until="load")
                title = page.title()
                try:
                    raw_txt = page.inner_text("body") or ""
                    text_excerpt = " ".join(raw_txt.split())[:300]
                except (RuntimeError, OSError, ValueError):
                    text_excerpt = ""
                if selector:
                    el = page.query_selector(selector)
                    if el is None:
                        browser.close()
                        return {"status": "SELECTOR_NOT_FOUND", "url": url, "selector": selector}
                    el.screenshot(path=str(shot_path))
                else:
                    page.screenshot(path=str(shot_path), full_page=full_page)
            finally:
                browser.close()

        data = shot_path.read_bytes()
        sha256_hex = hashlib.sha256(data).hexdigest()
        result: dict[str, Any] = {
            "status": "SUCCESS",
            "url": url,
            "title": title,
            "viewport": {"width": viewport_width, "height": viewport_height},
            "screenshot_bytes": len(data),
            "screenshot_sha256": sha256_hex[:16],
            "screenshot_path": str(shot_path),
            "text_excerpt": text_excerpt,
            "latency_ms": round((time.time() - start) * 1000, 2),
        }
        if return_base64:
            result["screenshot_base64"] = base64.b64encode(data).decode("ascii")
        _prune_old_shm_screenshots()
        return result
    except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
        shot_path.unlink(missing_ok=True)
        return {"status": "ERROR", "url": url, "error": str(exc)}
