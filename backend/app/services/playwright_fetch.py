"""Optional self-hosted Chromium fetch (Playwright) — used before ZenRows/ScrapingBee when enabled."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import unquote

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


def _page_url(page: Any) -> str:
    try:
        return str(page.url)
    except Exception:
        return "url"


def _instruction_steps(js_instructions: str | None) -> list[dict[str, Any]]:
    if not js_instructions:
        return []
    try:
        steps = json.loads(js_instructions)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _instruction_timeout_ms(step: dict[str, Any], default_ms: int = 4000) -> int:
    raw = step.get("timeout_ms")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    return default_ms


def _instructions_include_targeted_waits(steps: list[dict[str, Any]]) -> bool:
    return any(
        any(key in step for key in ("wait_for_selector", "wait_for_url", "wait_for_response_url"))
        for step in steps
    )


async def _apply_js_instructions(page: Any, js_instructions: str | None) -> None:
    steps = _instruction_steps(js_instructions)
    if not steps:
        if js_instructions:
            logger.debug("Unable to use JS instructions payload for %s", _page_url(page))
        return
    for step in steps:
        if "evaluate" in step:
            raw_script = step.get("evaluate")
            if isinstance(raw_script, str) and raw_script.strip():
                try:
                    await page.evaluate(raw_script)
                except Exception as e:
                    logger.debug("Playwright JS evaluate failed for %s: %s", _page_url(page), e)
        wait_ms = step.get("wait")
        if isinstance(wait_ms, (int, float)) and wait_ms > 0:
            await page.wait_for_timeout(int(wait_ms))
        selector = step.get("wait_for_selector")
        if isinstance(selector, str) and selector.strip():
            try:
                state = step.get("state")
                if state not in {"attached", "detached", "visible", "hidden"}:
                    state = "visible"
                await page.wait_for_selector(
                    selector,
                    state=state,
                    timeout=_instruction_timeout_ms(step),
                )
            except Exception as e:
                logger.debug("Playwright wait_for_selector failed for %s: %s", _page_url(page), e)
        click_selector = step.get("click")
        if isinstance(click_selector, str) and click_selector.strip():
            try:
                await page.click(click_selector, timeout=_instruction_timeout_ms(step))
            except Exception as e:
                logger.debug("Playwright click failed for %s: %s", _page_url(page), e)
        wait_for_url = step.get("wait_for_url")
        if isinstance(wait_for_url, str) and wait_for_url.strip():
            try:
                timeout_ms = _instruction_timeout_ms(step)
                if wait_for_url.startswith("re:"):
                    await page.wait_for_url(re.compile(wait_for_url[3:]), timeout=timeout_ms)
                else:
                    await page.wait_for_url(lambda current: wait_for_url in str(current), timeout=timeout_ms)
            except Exception as e:
                logger.debug("Playwright wait_for_url failed for %s: %s", _page_url(page), e)
        response_url = step.get("wait_for_response_url")
        if isinstance(response_url, str) and response_url.strip():
            try:
                response_status = step.get("status")
                timeout_ms = _instruction_timeout_ms(step)
                await page.wait_for_response(
                    lambda response: response_url in response.url
                    and (not isinstance(response_status, int) or response.status == response_status),
                    timeout=timeout_ms,
                )
            except Exception as e:
                logger.debug("Playwright wait_for_response failed for %s: %s", _page_url(page), e)
        scroll = step.get("scroll")
        if scroll == "bottom":
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as e:
                logger.debug("Playwright scroll-bottom failed for %s: %s", _page_url(page), e)
        elif scroll == "top":
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception as e:
                logger.debug("Playwright scroll-top failed for %s: %s", _page_url(page), e)
        elif isinstance(scroll, dict):
            x = scroll.get("x", 0)
            y = scroll.get("y", 0)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                try:
                    await page.evaluate("([x, y]) => window.scrollBy(x, y)", [int(x), int(y)])
                except Exception as e:
                    logger.debug("Playwright scroll-by failed for %s: %s", _page_url(page), e)


async def fetch_html_via_playwright(url: str, js_instructions: str | None = None) -> str | None:
    """
    Load URL in headless Chromium and return document HTML, or None on failure.

    Requires `playwright install chromium` (or bundled browsers) on the host.
    """
    if not settings.playwright_enabled:
        return None
    steps = _instruction_steps(js_instructions)
    targeted_waits = _instructions_include_targeted_waits(steps)
    async with _semaphore():
        context: Any = None
        try:
            browser = await _ensure_browser()
            context_kwargs: dict[str, Any] = {
                "user_agent": _UA,
                "viewport": {"width": 1920, "height": 1080},
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "device_scale_factor": 1,
                "has_touch": False,
                "is_mobile": False,
                "ignore_https_errors": True,
            }
            if settings.playwright_proxy_url:
                from urllib.parse import urlparse
                parsed_proxy = urlparse(settings.playwright_proxy_url)
                proxy_server = f"{parsed_proxy.scheme}://{parsed_proxy.hostname}"
                if parsed_proxy.port:
                    proxy_server += f":{parsed_proxy.port}"
                proxy_config: dict[str, str] = {"server": proxy_server}
                if parsed_proxy.username:
                    proxy_config["username"] = unquote(parsed_proxy.username)
                if parsed_proxy.password:
                    proxy_config["password"] = unquote(parsed_proxy.password)
                context_kwargs["proxy"] = proxy_config

            context = await browser.new_context(**context_kwargs)
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
            # Wait for network idle to ensure JS renders if it's a SPA.
            # Recipe pages already have targeted selector waits so 4s is enough;
            # generic pages use 6s — longer waits are wasted on ad/analytics pixels.
            try:
                await page.wait_for_load_state("networkidle", timeout=4000 if targeted_waits else 6000)
            except Exception:
                pass
            await _apply_js_instructions(page, js_instructions)
            if not targeted_waits:
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            html = await page.content()
        except Exception as e:
            err = e.__class__.__name__ if not str(e) else str(e)
            logger.warning("Playwright fetch failed for %s: %s", url, err)
            return None
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug("Playwright context close failed for %s: %s", url, e)
    if not html or len(html.strip()) < 80:
        return None
    return html
