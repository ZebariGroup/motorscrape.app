"""Optional self-hosted Chromium fetch (Playwright) — used before ZenRows/ScrapingBee when enabled."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_pw_semaphore: asyncio.Semaphore | None = None
_init_lock = asyncio.Lock()
_playwright: Any = None
_browser: Any = None


def _semaphore() -> asyncio.Semaphore:
    global _pw_semaphore
    if _pw_semaphore is None:
        _pw_semaphore = asyncio.Semaphore(max(1, settings.playwright_max_workers))
    return _pw_semaphore


async def _ensure_browser() -> Any:
    global _playwright, _browser
    async with _init_lock:
        if _browser is not None:
            try:
                if _browser.is_connected():
                    return _browser
            except Exception:
                pass
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
        launch_timeout = max(10_000, min(settings.playwright_timeout_ms, 120_000))
        _browser = await _playwright.chromium.launch(
            headless=True,
            timeout=launch_timeout,
            args=(
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
                "--ignore-certificate-errors",
            ),
        )
        return _browser


async def shutdown_playwright() -> None:
    """Close shared browser and playwright driver (e.g. on app shutdown)."""
    global _playwright, _browser
    async with _init_lock:
        if _browser is not None:
            try:
                await _browser.close()
            except Exception as e:
                logger.debug("Playwright browser close: %s", e)
            _browser = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception as e:
                logger.debug("Playwright stop: %s", e)
            _playwright = None


async def _apply_js_instructions(page: Any, js_instructions: str | None) -> None:
    if not js_instructions:
        return
    try:
        steps = json.loads(js_instructions)
    except (TypeError, json.JSONDecodeError):
        logger.debug("Unable to parse JS instructions JSON for %s", page.url if hasattr(page, "url") else "url")
        return
    if not isinstance(steps, list):
        logger.debug("Ignoring non-list JS instructions payload for %s", page.url if hasattr(page, "url") else "url")
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        if "evaluate" in step:
            raw_script = step.get("evaluate")
            if isinstance(raw_script, str) and raw_script.strip():
                try:
                    await page.evaluate(raw_script)
                except Exception as e:
                    logger.debug("Playwright JS evaluate failed for %s: %s", page.url, e)
        wait_ms = step.get("wait")
        if isinstance(wait_ms, (int, float)) and wait_ms > 0:
            await page.wait_for_timeout(int(wait_ms))


async def fetch_html_via_playwright(url: str, js_instructions: str | None = None) -> str | None:
    """
    Load URL in headless Chromium and return document HTML, or None on failure.

    Requires `playwright install chromium` (or bundled browsers) on the host.
    """
    if not settings.playwright_enabled:
        return None
    async with _semaphore():
        try:
            browser = await _ensure_browser()
            context = await browser.new_context(
                user_agent=_UA,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                device_scale_factor=1,
                has_touch=False,
                is_mobile=False,
                ignore_https_errors=True,
            )
            # Add stealth script to avoid basic bot detection
            await context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                """
            )
            page = await context.new_page()
            nav_timeout = max(5000, settings.playwright_timeout_ms)
            await page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
            post = max(0, settings.playwright_post_load_wait_ms)
            if post:
                await page.wait_for_timeout(post)
            # Wait for network idle to ensure JS renders if it's a SPA
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await _apply_js_instructions(page, js_instructions)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = await page.content()
            await context.close()
        except Exception as e:
            err = e.__class__.__name__ if not str(e) else str(e)
            logger.warning("Playwright fetch failed for %s: %s", url, err)
            return None
    if not html or len(html.strip()) < 80:
        return None
    return html
