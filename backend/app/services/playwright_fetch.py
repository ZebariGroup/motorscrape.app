"""Optional self-hosted Chromium fetch (Playwright) — used before ZenRows/ScrapingBee when enabled."""

from __future__ import annotations

import asyncio
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
                "--window-size=1365,900",
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


async def fetch_html_via_playwright(url: str) -> str | None:
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
                viewport={"width": 1365, "height": 900},
                locale="en-US",
            )
            page = await context.new_page()
            nav_timeout = max(5000, settings.playwright_timeout_ms)
            await page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout)
            post = max(0, settings.playwright_post_load_wait_ms)
            if post:
                await page.wait_for_timeout(post)
            html = await page.content()
            await context.close()
        except Exception as e:
            err = e.__class__.__name__ if not str(e) else str(e)
            logger.warning("Playwright fetch failed for %s: %s", url, err)
            return None
    if not html or len(html.strip()) < 80:
        return None
    return html
