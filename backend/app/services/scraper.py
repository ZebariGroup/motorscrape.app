"""Fetch dealership pages via direct HTTP first, then managed scrapers (ZenRows / ScrapingBee) when needed."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.dealer_platforms import inventory_render_plan_for_url
from app.services.scraper_strategies import zenrows_try_once

logger = logging.getLogger(__name__)

_zenrows_semaphore: asyncio.Semaphore | None = None
_zenrows_sem_lock = asyncio.Lock()
_scrapingbee_semaphore: asyncio.Semaphore | None = None
_scrapingbee_sem_lock = asyncio.Lock()
_managed_scraper_semaphore: asyncio.Semaphore | None = None
_managed_scraper_sem_lock = asyncio.Lock()
_zenrows_cooldown_until_monotonic: float = 0.0

_ZENROWS_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 520, 522, 524})


async def _zenrows_concurrency_gate() -> asyncio.Semaphore:
    global _zenrows_semaphore
    if _zenrows_semaphore is None:
        async with _zenrows_sem_lock:
            if _zenrows_semaphore is None:
                _zenrows_semaphore = asyncio.Semaphore(max(1, settings.zenrows_max_concurrency))
    return _zenrows_semaphore


async def _scrapingbee_concurrency_gate() -> asyncio.Semaphore:
    global _scrapingbee_semaphore
    if _scrapingbee_semaphore is None:
        async with _scrapingbee_sem_lock:
            if _scrapingbee_semaphore is None:
                _scrapingbee_semaphore = asyncio.Semaphore(max(1, settings.scrapingbee_max_concurrency))
    return _scrapingbee_semaphore


async def _managed_scraper_concurrency_gate() -> asyncio.Semaphore:
    global _managed_scraper_semaphore
    if _managed_scraper_semaphore is None:
        async with _managed_scraper_sem_lock:
            if _managed_scraper_semaphore is None:
                _managed_scraper_semaphore = asyncio.Semaphore(max(1, settings.managed_scraper_max_concurrency))
    return _managed_scraper_semaphore


def _zenrows_cooldown_active() -> bool:
    return time.monotonic() < _zenrows_cooldown_until_monotonic


def _set_zenrows_cooldown(reason: str) -> None:
    global _zenrows_cooldown_until_monotonic
    cooldown_seconds = max(0, int(settings.zenrows_cooldown_seconds))
    if cooldown_seconds <= 0:
        return
    _zenrows_cooldown_until_monotonic = max(
        _zenrows_cooldown_until_monotonic,
        time.monotonic() + float(cooldown_seconds),
    )
    logger.warning("ZenRows cooldown activated for %ss (%s)", cooldown_seconds, reason)

PageKind = Literal["homepage", "inventory"]

_INVENTORY_URL_RE = re.compile(r'["\']inventoryApiURL["\']\s*:\s*["\'](?P<url>[^"\']+)["\']', re.I)
# Extra embedded config keys seen on dealer SPAs
_EXTRA_API_RES = (
    re.compile(r'["\']inventoryApiUrl["\']\s*:\s*["\'](?P<url>[^"\']+)["\']', re.I),
    re.compile(r'["\']inventoryApiURL["\']\s*:\s*["\'](?P<url>[^"\']+)["\']', re.I),
    re.compile(r'["\']inventory_url["\']\s*:\s*["\'](?P<url>[^"\']+)["\']', re.I),
    re.compile(r'["\']inventoryEndpoint["\']\s*:\s*["\'](?P<url>[^"\']+)["\']', re.I),
    re.compile(r'vehicle_data_url\s*=\s*[\'"](?P<url>[^\'"]+)[\'"]', re.I),
)
_WS_INV_FETCH_RE = re.compile(
    r'fetch\("(?P<url>/api/widget/ws-inv-data/getInventory)".*?body:decodeURI\("(?P<body>.*?)"\)',
    re.S,
)
_DDC_WIDGET_PROPS_RE = re.compile(
    r'DDC\.WidgetData\[[^\]]+\]\.props\s*=\s*\{(?P<body>.*?)\}\s*</script>',
    re.S,
)
# Looser pairing for Toyota/Lexus-style Dealer.com SPAs: API URL + params may sit outside WidgetData blocks.
_DDC_WIDGET_INVENTORY_PAIR_RE = re.compile(
    r'["\'](?:inventoryApiURL|inventoryApiUrl)["\']\s*:\s*["\'](?P<url>[^"\']+)["\']'
    r"[\s\S]{0,2400}?"
    r'["\'](?:params|widgetParams|inventoryParams)["\']\s*:\s*["\'](?P<params>[^"\']*)["\']',
    re.I,
)
_DDC_WIDGET_INVENTORY_PAIR_RE_REVERSE = re.compile(
    r'["\'](?:params|widgetParams|inventoryParams)["\']\s*:\s*["\'](?P<params>[^"\']*)["\']'
    r"[\s\S]{0,2400}?"
    r'["\'](?:inventoryApiURL|inventoryApiUrl)["\']\s*:\s*["\'](?P<url>[^"\']+)["\']',
    re.I,
)
_INVENTORY_HINTS = (
    "vehicle-card-title",
    "vehicle-card",
    "vehicle-card--mod",
    "vehiclecard",
    "inventory_list",
    "inventory-listing",
    "srpvehicle",
)
_BLOCK_MARKERS = (
    "cf-browser-verification",
    "checking your browser",
    "just a moment",
    "attention required",
    "enable javascript",
    "datadome",
    "perimeterx",
    "px-captcha",
    "captcha.js",
    "access denied",
    "request blocked",
    "client challenge",
)
_STRUCTURE_HINTS = (
    '"inventory":',
    '"inventoryapiurl"',
    "__next_data__",
    '"@type":"vehicle"',
    '"@type": "vehicle"',
    '"vehicleidentificationnumber"',
    '"vdpurl"',
)
_PLACEHOLDER_MARKERS = (
    "srp-inventory skeleton",
    "vehicle-card--mod skeleton",
    "card-skeleton-image",
    "vehicle-card vehicle-card--mod skeleton",
)


def _host_is_express_retail(url: str) -> bool:
    """Dealer 'express store' subdomains (e.g. express.dealer.com) sit behind strict WAF; prefer managed fetch."""
    try:
        host = urlsplit(url).netloc.lower().split("@")[-1]
    except Exception:
        return False
    if not host:
        return False
    no_port = host.split(":")[0]
    return no_port == "express" or no_port.startswith("express.")


def _www_swap_express_url(url: str) -> str | None:
    """express.dealer.com/path -> www.dealer.com/path when the group runs inventory on both."""
    try:
        parts = urlsplit(url)
        host = parts.netloc.lower().split("@")[-1].split(":")[0]
        if not host.startswith("express."):
            return None
        base = host.removeprefix("express.")
        if not base or base.startswith("express."):
            return None
        www_host = f"www.{base}"
        return urlunsplit((parts.scheme, www_host, parts.path, parts.query, parts.fragment))
    except Exception:
        return None


async def _playwright_pass(
    url: str,
    timeout: httpx.Timeout,
    *,
    page_kind: PageKind,
    failures: list[str],
    metric_bump: Callable[[str], None],
    js_instructions: str | None = None,
    platform_id: str | None = None,
) -> tuple[str, str] | None:
    if not settings.playwright_enabled:
        return None
    instruction_steps = 0
    targeted_waits = False
    if js_instructions:
        try:
            from app.services.playwright_fetch import _instruction_steps as _pw_instruction_steps
            from app.services.playwright_fetch import _instructions_include_targeted_waits as _pw_targeted_waits

            steps = _pw_instruction_steps(js_instructions)
            instruction_steps = len(steps)
            targeted_waits = _pw_targeted_waits(steps)
        except Exception:
            pass
    if instruction_steps > 0:
        metric_bump("playwright_recipe_used")
    if targeted_waits:
        metric_bump("playwright_recipe_targeted_waits")
    if platform_id:
        metric_bump(f"playwright_recipe_platform_{platform_id}")
    try:
        from app.services.playwright_fetch import fetch_html_via_playwright
    except ImportError as e:
        failures.append(f"playwright: ImportError: {e}")
        metric_bump("playwright_import_error")
        return None
    try:
        html = await fetch_html_via_playwright(url, js_instructions=js_instructions)
    except Exception as e:
        err_str = e.__class__.__name__ if not str(e) else str(e)
        failures.append(f"playwright: {err_str}")
        logger.debug("Playwright pass exception for %s: %s", url, err_str)
        metric_bump("playwright_error")
        return None
    if not html:
        failures.append("playwright: empty")
        metric_bump("playwright_empty")
        logger.info(
            "Playwright returned empty HTML for %s (platform=%s steps=%s targeted_waits=%s)",
            url,
            platform_id or "",
            instruction_steps,
            targeted_waits,
        )
        return None
    html = await _maybe_append_inventory_api_data(url, html, timeout)
    lower = html.lower()
    inventory_signal_count = sum(
        1
        for marker in (
            "[data-vehicle",
            "result-wrap new-vehicle",
            "vehicle-card",
            "vehicle-card--mod",
            "si-vehicle-box",
            "data-component=\"result-tile\"",
            "data-component='result-tile'",
        )
        if marker in lower
    )
    html_sufficient = _direct_html_sufficient(html, page_kind=page_kind)
    logger.info(
        "Playwright fetched %s (platform=%s steps=%s targeted_waits=%s html_chars=%s inventory_signals=%s sufficient=%s)",
        url,
        platform_id or "",
        instruction_steps,
        targeted_waits,
        len(html),
        inventory_signal_count,
        html_sufficient,
    )
    if html_sufficient:
        metric_bump("playwright_ok")
        return html, "playwright"
    failures.append("playwright: insufficient")
    metric_bump("playwright_insufficient")
    return None


async def _direct_get_with_express_www_fallback(url: str, timeout: httpx.Timeout) -> str:
    """
    Try direct GET; on 403 from an express.* host, try the same path on www.* once
    (some Dealer.com groups answer on www while express is Cloudflare-challenged).
    Also handles TLS internal errors by trying http:// if it's a known problematic host.
    """
    try:
        return await _direct_get(url, timeout)
    except httpx.ConnectError as e:
        if "tlsv1 alert internal error" in str(e).lower() and url.startswith("https://"):
            logger.info("TLS internal error on %s; retrying with http://", url)
            alt = url.replace("https://", "http://", 1)
            return await _direct_get(alt, timeout)
        raise
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 403 or not _host_is_express_retail(url):
            raise
        alt = _www_swap_express_url(url)
        if not alt or alt.rstrip("/") == url.rstrip("/"):
            raise
        logger.info("403 on express inventory; retrying direct on www equivalent: %s", alt)
        return await _direct_get(alt, timeout)


async def fetch_page_html(
    url: str,
    *,
    page_kind: PageKind = "inventory",
    prefer_render: bool = False,
    metrics: dict[str, int] | None = None,
    platform_id: str | None = None,
) -> tuple[str, str]:
    """
    Return (html, method_used).

    Order: direct HTTP → optional inventory API enrichment → if insufficient or direct fails,
    optional Playwright (self-hosted Chromium) → ZenRows (static, then JS render) →
    ScrapingBee → last-chance direct body.

    method_used values: direct, playwright, zenrows_static, zenrows_rendered,
    scrapingbee_static, scrapingbee_rendered, direct_fallback.
    """
    timeout = httpx.Timeout(settings.scrape_timeout)
    failures: list[str] = []
    allow_managed_js_render = (
        page_kind == "inventory" or prefer_render or settings.homepage_managed_js_render
    )

    if (
        page_kind == "inventory"
        and _host_is_express_retail(url)
        and (settings.zenrows_api_key or settings.scrapingbee_api_key)
    ):
        prefer_render = True

    def _m(key: str) -> None:
        if metrics is not None:
            metrics[key] = metrics.get(key, 0) + 1

    def _retry_waits(base_wait_ms: int, *, has_embedded_waits: bool = False) -> tuple[int, ...]:
        if has_embedded_waits:
            return (0,)
        waits = [max(0, base_wait_ms)]
        if page_kind == "inventory":
            waits.append(max(base_wait_ms * 2, base_wait_ms + 3000, 6000))
        out: list[int] = []
        for wait in waits:
            if wait not in out:
                out.append(wait)
        return tuple(out)

    effective_url = url
    inventory_render_plan = inventory_render_plan_for_url(url, platform_id=platform_id) if page_kind == "inventory" else None
    playwright_instructions = inventory_render_plan.playwright_instructions if inventory_render_plan else None
    zenrows_js_instructions = inventory_render_plan.zenrows_js_instructions if inventory_render_plan else None

    if prefer_render and page_kind == "inventory":
        # OneAudi Falcon (and similar): try local browser before paid JS render APIs.
        pw_early = await _playwright_pass(
            url,
            timeout,
            page_kind=page_kind,
            failures=failures,
            metric_bump=_m,
            js_instructions=playwright_instructions,
            platform_id=platform_id,
        )
        if pw_early is not None:
            return pw_early

        if settings.zenrows_api_key:
            for wait_ms in _retry_waits(
                settings.zenrows_wait_ms,
                has_embedded_waits=bool(zenrows_js_instructions),
            ):
                html = await zenrows_try_once(
                    url=url,
                    timeout=timeout,
                    page_kind=page_kind,
                    failures=failures,
                    metric_bump=_m,
                    js_render=True,
                    wait_ms=wait_ms,
                    metric_prefix="zenrows_rendered",
                    failure_label="zenrows_rendered_preferred",
                    js_instructions=zenrows_js_instructions,
                )
                if html is not None:
                    return html, "zenrows_rendered"

        if settings.scrapingbee_api_key:
            for wait_ms in _retry_waits(settings.scrapingbee_wait_ms):
                try:
                    html = await _scrapingbee_fetch(
                        url,
                        timeout,
                        render_js=True,
                        wait_ms=wait_ms,
                    )
                    html = await _maybe_append_inventory_api_data(url, html, timeout)
                    if _direct_html_sufficient(html, page_kind=page_kind):
                        _m("scrapingbee_rendered_ok")
                        return html, "scrapingbee_rendered"
                    _m("scrapingbee_rendered_insufficient")
                except Exception as e:
                    err_str = e.__class__.__name__ if not str(e) else str(e)
                    logger.warning("ScrapingBee preferred rendered fetch failed for %s: %s", url, err_str)
                    failures.append(f"scrapingbee_rendered_preferred: {err_str}")

    direct_urls = [url]
    saw_cloudflare_block = False
    if page_kind == "inventory":
        sanitized_url = _sanitize_inventory_query_url(url)
        if sanitized_url.rstrip("/") != url.rstrip("/"):
            direct_urls.append(sanitized_url)

    # 1) Direct first (cheapest), with optional inventory URL sanitization retry.
    for idx, direct_url in enumerate(direct_urls):
        effective_url = direct_url
        try:
            html = await _direct_get_with_express_www_fallback(direct_url, timeout)
            html = await _maybe_append_inventory_api_data(direct_url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind):
                if idx > 0:
                    logger.info("Direct fetch recovered via sanitized URL: %s -> %s", url, direct_url)
                _m("direct_ok")
                return html, "direct"
            if _should_prefer_zenrows_render(html, page_kind=page_kind):
                prefer_render = True
            logger.info(
                "Direct fetch insufficient for %s (%s), escalating to managed scrapers",
                direct_url,
                page_kind,
            )
            _m("direct_insufficient")
            break
        except Exception as e:
            err_str = e.__class__.__name__ if not str(e) else str(e)
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403:
                try:
                    block_text = (e.response.text or "").lower()
                except Exception:
                    block_text = ""
                if "cloudflare" in block_text or "cf-ray" in e.response.headers:
                    saw_cloudflare_block = True
            failures.append(f"direct: {err_str}")
            logger.debug("Direct fetch failed for %s: %s", direct_url, err_str)
            _m("direct_failed")
            if idx + 1 < len(direct_urls):
                continue

    pw_result = await _playwright_pass(
        effective_url,
        timeout,
        page_kind=page_kind,
        failures=failures,
        metric_bump=_m,
        js_instructions=playwright_instructions if page_kind == "inventory" else None,
        platform_id=platform_id,
    )
    if pw_result is not None:
        return pw_result

    # 2) ZenRows: static then rendered
    if settings.zenrows_api_key:
        if not prefer_render:
            failure_count_before_static = len(failures)
            html = await zenrows_try_once(
                url=effective_url,
                timeout=timeout,
                page_kind=page_kind,
                failures=failures,
                metric_bump=_m,
                js_render=False,
                metric_prefix="zenrows_static",
                failure_label="zenrows_static",
            )
            if html is not None:
                return html, "zenrows_static"
            # ZenRows RESP001 means static mode could not get page content and JS render is required.
            # Allow homepage rendered fallback in this case even when homepage_managed_js_render is off.
            if not allow_managed_js_render and page_kind == "homepage":
                recent_failures = " | ".join(failures[failure_count_before_static:])
                if "resp001" in recent_failures.lower() or "javascript rendering" in recent_failures.lower():
                    allow_managed_js_render = True
                    logger.info(
                        "ZenRows static indicated JS requirement for homepage %s; enabling rendered fallback",
                        effective_url,
                    )

        if allow_managed_js_render:
            effective_render_plan = (
                inventory_render_plan_for_url(effective_url, platform_id=platform_id)
                if page_kind == "inventory"
                else None
            )
            js_instructions = effective_render_plan.zenrows_js_instructions if effective_render_plan else None
            for wait_ms in _retry_waits(
                settings.zenrows_wait_ms,
                has_embedded_waits=bool(js_instructions),
            ):

                html = await zenrows_try_once(
                    url=effective_url,
                    timeout=timeout,
                    page_kind=page_kind,
                    failures=failures,
                    metric_bump=_m,
                    js_render=True,
                    wait_ms=wait_ms,
                    metric_prefix="zenrows_rendered",
                    failure_label="zenrows_rendered",
                    js_instructions=js_instructions,
                )
                if html is not None:
                    return html, "zenrows_rendered"

    # 3) ScrapingBee: static then rendered
    if settings.scrapingbee_api_key:
        try:
            html = await _scrapingbee_fetch(effective_url, timeout, render_js=False)
            html = await _maybe_append_inventory_api_data(effective_url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind):
                _m("scrapingbee_static_ok")
                return html, "scrapingbee_static"
        except Exception as e:
            err_str = e.__class__.__name__ if not str(e) else str(e)
            logger.warning("ScrapingBee static fetch failed for %s: %s", url, err_str)
            failures.append(f"scrapingbee_static: {err_str}")

        if allow_managed_js_render:
            for wait_ms in _retry_waits(settings.scrapingbee_wait_ms):
                try:
                    html = await _scrapingbee_fetch(
                        effective_url,
                        timeout,
                        render_js=True,
                        wait_ms=wait_ms,
                    )
                    html = await _maybe_append_inventory_api_data(effective_url, html, timeout)
                    if _direct_html_sufficient(html, page_kind=page_kind):
                        _m("scrapingbee_rendered_ok")
                        return html, "scrapingbee_rendered"
                    _m("scrapingbee_rendered_insufficient")
                except Exception as e:
                    err_str = e.__class__.__name__ if not str(e) else str(e)
                    logger.warning("ScrapingBee rendered fetch failed for %s: %s", url, err_str)
                    failures.append(f"scrapingbee_rendered: {err_str}")

    # 4) If we had a direct body that was "insufficient", return it rather than failing completely
    try:
        html_fallback = await _direct_get_with_express_www_fallback(effective_url, timeout)
        html_fallback = await _maybe_append_inventory_api_data(effective_url, html_fallback, timeout)
        if _has_block_markers(html_fallback):
            raise RuntimeError("blocked")
        if "site currently not available" in html_fallback.lower() or "seite vorübergehend" in html_fallback.lower():
            raise RuntimeError("unavailable")
        _m("direct_fallback_ok")
        return html_fallback, "direct_fallback"
    except Exception as e:
        err_str = e.__class__.__name__ if not str(e) else str(e)
        if str(e) in ("blocked", "unavailable"):
            err_str = str(e)
        failures.append(f"direct_retry: {err_str}")

        # If the fallback attempt succeeded but was thin, return it
        if (
            "html_fallback" in locals()
            and html_fallback
            and len(html_fallback) > 10
            and not _has_block_markers(html_fallback)
        ):
            if (
                "site currently not available" not in html_fallback.lower()
                and "seite vorübergehend" not in html_fallback.lower()
                and "denied" not in html_fallback.lower()
            ):
                _m("direct_fallback_ok")
                return html_fallback, "direct_fallback"

    # If we had a thin HTML from the first pass that wasn't blocked, return it
    if "html" in locals() and html and len(html) > 10 and not _has_block_markers(html):
        if "site currently not available" not in html.lower() and "seite vorübergehend" not in html.lower() and "denied" not in html.lower():
            _m("direct_fallback_ok")
            return html, "direct_fallback"

    detail = " | ".join(failures)
    if (
        saw_cloudflare_block
        and not settings.zenrows_api_key
        and not settings.scrapingbee_api_key
        and not settings.playwright_enabled
    ):
        detail = (
            detail
            + " | cloudflare_blocked_no_fallback: set PLAYWRIGHT_ENABLED=true "
            + "or configure ZENROWS_API_KEY/SCRAPINGBEE_API_KEY"
        )
    raise RuntimeError(f"All fetch methods failed for {effective_url}: {detail}") from None


def _looks_like_block_page(html: str) -> bool:
    if not html or len(html.strip()) < 200:
        return True
    lower = html.lower()
    return any(m in lower for m in _BLOCK_MARKERS)


def _has_block_markers(html: str) -> bool:
    if not html:
        return False
    lower = html.lower()
    return any(m in lower for m in _BLOCK_MARKERS)


def _has_structured_inventory_hint(html: str) -> bool:
    lower = html.lower()
    return any(h in lower for h in _STRUCTURE_HINTS)


def _looks_like_placeholder_inventory(html: str) -> bool:
    lower = html.lower()
    return any(marker in lower for marker in _PLACEHOLDER_MARKERS)


def _looks_like_empty_inventory_shell(html: str) -> bool:
    lower = html.lower()
    if "loader-hits" not in lower or 'id="hits"' not in lower:
        return False
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    hits = soup.select_one("#hits")
    if hits is None:
        return False
    if hits.select_one("[data-vehicle], .result-wrap.new-vehicle, .carbox, .vehicle-card, .si-vehicle-box"):
        return False
    return True


def _has_dom_inventory_result_tiles(html: str) -> bool:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    return (
        soup.find("li", attrs={"data-component": "result-tile"}) is not None
        or soup.select_one("[data-component='result-tile']") is not None
    )


def _should_prefer_zenrows_render(html: str, *, page_kind: PageKind) -> bool:
    if page_kind != "inventory":
        return False
    if _has_structured_inventory_hint(html):
        return False
    return (
        _looks_like_block_page(html)
        or _looks_like_placeholder_inventory(html)
        or _looks_like_empty_inventory_shell(html)
    )


def _should_retry_zenrows_with_premium_proxy(html: str, *, page_kind: PageKind) -> bool:
    if settings.zenrows_premium_proxy:
        return False
    if page_kind == "inventory" and _has_structured_inventory_hint(html):
        return False
    return _looks_like_block_page(html) or (
        page_kind == "inventory"
        and (
            _looks_like_placeholder_inventory(html)
            or _looks_like_empty_inventory_shell(html)
        )
    )


def _direct_html_sufficient(html: str, *, page_kind: PageKind) -> bool:
    if _looks_like_block_page(html):
        return False
    if _has_structured_inventory_hint(html):
        return True
    if page_kind == "inventory" and _looks_like_placeholder_inventory(html):
        return False
    if page_kind == "inventory" and _looks_like_empty_inventory_shell(html):
        return False
    if _html_looks_inventory_ready(html):
        return True
    lower = html.lower()
    if page_kind == "homepage":
        return len(html) >= 1800 and ("href=" in lower or "inventory" in lower)
    if "site currently not available" in lower or "seite vorübergehend" in lower:
        return False
    # Inventory pages often return large SEO shells or placeholder grids.
    return False


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


async def _direct_get(url: str, timeout: httpx.Timeout) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
        r = await client.get(url, headers=_browser_headers())
        r.raise_for_status()
        return r.text


async def _zenrows_fetch(
    url: str,
    timeout: httpx.Timeout,
    *,
    js_render: bool,
    wait_ms: int = 0,
    premium_proxy: bool = False,
    js_instructions: str | None = None,
) -> str:
    """https://docs.zenrows.com/universal-scraper-api"""
    api_url = "https://api.zenrows.com/v1/"
    params: dict[str, str] = {
        "apikey": settings.zenrows_api_key,
        "url": url,
        "js_render": "true" if js_render else "false",
    }
    if js_render and wait_ms > 0 and not js_instructions:
        params["wait"] = str(wait_ms)
    if js_render and js_instructions:
        params["js_instructions"] = js_instructions
    if settings.zenrows_premium_proxy or premium_proxy:
        params["premium_proxy"] = "true"
    if _zenrows_cooldown_active():
        raise RuntimeError("ZenRows temporarily in cooldown")

    attempts = max(1, int(settings.zenrows_request_attempts))
    backoff_seconds = max(0.0, float(settings.zenrows_retry_backoff_ms) / 1000.0)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        if _zenrows_cooldown_active():
            raise RuntimeError("ZenRows temporarily in cooldown")
        try:
            zenrows_sem = await _zenrows_concurrency_gate()
            managed_sem = await _managed_scraper_concurrency_gate()
            async with managed_sem:
                async with zenrows_sem:
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                        r = await client.get(api_url, params=params)
            if r.status_code in _ZENROWS_TRANSIENT_STATUS_CODES:
                if attempt < attempts:
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
                    continue
                _set_zenrows_cooldown(f"http_{r.status_code}")
            r.raise_for_status()
            return r.text
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code in _ZENROWS_TRANSIENT_STATUS_CODES and attempt < attempts:
                await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
                continue
            if e.response.status_code in _ZENROWS_TRANSIENT_STATUS_CODES:
                _set_zenrows_cooldown(f"http_{e.response.status_code}")
            raise
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            if attempt < attempts:
                await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("ZenRows request failed without response")


async def _scrapingbee_fetch(
    url: str,
    timeout: httpx.Timeout,
    *,
    render_js: bool,
    wait_ms: int = 0,
) -> str:
    """https://www.scrapingbee.com/documentation/"""
    base = "https://app.scrapingbee.com/api/v1/"
    q: dict[str, str | int] = {
        "api_key": settings.scrapingbee_api_key,
        "url": url,
        "render_js": "true" if render_js else "false",
    }
    if render_js and wait_ms > 0:
        q["wait"] = wait_ms
    qs = urlencode(q)
    scrapingbee_sem = await _scrapingbee_concurrency_gate()
    managed_sem = await _managed_scraper_concurrency_gate()
    async with managed_sem:
        async with scrapingbee_sem:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(f"{base}?{qs}")
                r.raise_for_status()
                return r.text


def _html_looks_inventory_ready(html: str) -> bool:
    lower = html.lower()
    return any(marker in lower for marker in _INVENTORY_HINTS) or _has_dom_inventory_result_tiles(html)


def _extract_inventory_api_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for m in _INVENTORY_URL_RE.finditer(html):
        raw = m.group("url")
        fixed = _normalize_embedded_inventory_value(raw)
        abs_url = urljoin(base_url, fixed)
        if abs_url not in urls:
            urls.append(abs_url)
    for cre in _EXTRA_API_RES:
        for m in cre.finditer(html):
            raw = m.group("url")
            fixed = _normalize_embedded_inventory_value(raw)
            abs_url = urljoin(base_url, fixed)
            if abs_url not in urls:
                urls.append(abs_url)
    return urls


def _extract_inventory_post_requests(html: str, base_url: str) -> list[tuple[str, str]]:
    requests: list[tuple[str, str]] = []
    for m in _WS_INV_FETCH_RE.finditer(html):
        abs_url = urljoin(base_url, m.group("url"))
        body = m.group("body")
        try:
            decoded = unquote(body)
        except Exception:
            decoded = body
        decoded = decoded.replace("\\/", "/")
        if (abs_url, decoded) not in requests:
            requests.append((abs_url, decoded))
    return requests


def _inventory_page_number_from_url(url: str) -> int:
    try:
        query = {k.lower(): v for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
    except Exception:
        return 1
    for key in ("page", "pageindex", "pt", "_p", "pn", "p", "currentpage"):
        raw = query.get(key)
        if not raw:
            continue
        try:
            page_num = int(raw)
        except ValueError:
            continue
        if page_num > 0:
            return page_num
    return 1


def _sanitize_inventory_query_url(url: str) -> str:
    """
    Strip site-specific facet filters that can trigger 403s on public SRP links.
    Keep explicit make/model/paging/sort keys.
    """
    try:
        parts = urlsplit(url)
        if not parts.query:
            return url
        keep_explicit = {
            "make",
            "model",
            "supermodel",
            "trim",
            "year",
            "condition",
            "type",
            "inventorytype",
            "search",
            "q",
            "page",
            "pageindex",
            "pt",
            "_p",
            "pn",
            "p",
            "currentpage",
            "sort",
            "orderby",
            "order",
            "view",
            "perpage",
            "pagesize",
            "page_size",
            "size",
            "limit",
            "offset",
            "start",
        }
        in_pairs = parse_qsl(parts.query, keep_blank_values=True)
        out_pairs: list[tuple[str, str]] = []
        dropped = False
        for key, value in in_pairs:
            lower = key.lower()
            if lower in keep_explicit:
                out_pairs.append((key, value))
                continue
            if lower.startswith("_dfr[") or "[" in key or "]" in key:
                dropped = True
                continue
            out_pairs.append((key, value))
        if not dropped:
            return url
        query = urlencode(out_pairs, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        return url


def _normalize_embedded_inventory_value(raw: str, *, decode_query: bool = False) -> str:
    if not raw:
        return ""
    fixed = raw.replace("\\/", "/").replace("\\u002f", "/").replace("\\u0026", "&")
    fixed = html.unescape(fixed)
    if decode_query:
        try:
            fixed = unquote(fixed)
        except Exception:
            pass
    return fixed


_DDC_PATH_SLUG_TO_MAKE: dict[str, str] = {
    "alfa-romeo": "Alfa Romeo",
    "buick": "Buick",
    "cadillac": "Cadillac",
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "chrysler": "Chrysler",
    "dodge": "Dodge",
    "ford": "Ford",
    "gmc": "GMC",
    "jeep": "Jeep",
    "lincoln": "Lincoln",
    "ram": "Ram",
    "honda": "Honda",
    "acura": "Acura",
    "toyota": "Toyota",
    "lexus": "Lexus",
    "nissan": "Nissan",
    "infiniti": "Infiniti",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "bmw": "BMW",
    "mini": "MINI",
    "mercedes-benz": "Mercedes-Benz",
    "audi": "Audi",
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "volvo": "Volvo",
    "subaru": "Subaru",
    "mazda": "Mazda",
    "mitsubishi": "Mitsubishi",
    "genesis": "Genesis",
    "porsche": "Porsche",
    "land-rover": "Land Rover",
    "jaguar": "Jaguar",
    "fiat": "FIAT",
    "maserati": "Maserati",
    "ferrari": "Ferrari",
    "lamborghini": "Lamborghini",
    "bentley": "Bentley",
    "rolls-royce": "Rolls-Royce",
}


def _make_from_ddc_path(url_path: str) -> str | None:
    """Extract make name from Dealer.com path patterns like /new-buick/ or /new-gmc/."""
    import re as _re
    path = (url_path or "").lower().strip("/")
    m = _re.match(r"^(new|used)-(.+?)(?:/|$)", path)
    if not m:
        return None
    slug = m.group(2)
    if slug in ("inventory", "vehicles", "specials", "featured"):
        return None
    if slug in _DDC_PATH_SLUG_TO_MAKE:
        return _DDC_PATH_SLUG_TO_MAKE[slug]
    simple = slug.replace("-", " ").strip()
    for known_slug, make_name in _DDC_PATH_SLUG_TO_MAKE.items():
        if simple == known_slug.replace("-", " "):
            return make_name
    return None


def _rewrite_inventory_post_body_for_page(body: str, page_url: str) -> str:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return body
    if not isinstance(payload, dict):
        return body
    inventory_params = payload.get("inventoryParameters")
    if not isinstance(inventory_params, dict):
        return body

    page_query = {
        k.lower(): v
        for k, v in parse_qsl(urlsplit(page_url).query, keep_blank_values=True)
        if k
    }
    # Inject filters from query params (e.g. ?make=Buick&model=Enclave)
    for url_key, body_key in (
        ("make", "make"),
        ("model", "model"),
        ("supermodel", "superModel"),
        ("gvbodystyle", "gvBodyStyle"),
        ("bodystyle", "bodyStyle"),
    ):
        value = page_query.get(url_key)
        if value:
            inventory_params[body_key] = value
    # Also inject make from path-based filtering (e.g. /new-buick/vehicles-troy-mi.htm)
    # only when the body doesn't already have a make and the query didn't provide one.
    if not inventory_params.get("make") and not page_query.get("make"):
        path_make = _make_from_ddc_path(urlsplit(page_url).path)
        if path_make:
            inventory_params["make"] = path_make

    page_num = _inventory_page_number_from_url(page_url)
    if page_num > 1:
        prefs = payload.get("preferences")
        page_size_raw = prefs.get("pageSize") if isinstance(prefs, dict) else None
        try:
            page_size = int(str(page_size_raw).strip()) if page_size_raw is not None else 12
        except ValueError:
            page_size = 12
        start = max(0, (page_num - 1) * max(1, page_size))
        inventory_params.pop("page", None)
        inventory_params["start"] = str(start)

    return json.dumps(payload, separators=(",", ":"))


def _rewrite_inventory_get_query_for_page(
    query: dict[str, str],
    page_url: str,
) -> dict[str, str]:
    rewritten = dict(query or {})
    page_pairs = [(k, v) for k, v in parse_qsl(urlsplit(page_url).query, keep_blank_values=True) if k]
    if not rewritten and not page_pairs:
        return rewritten

    raw_params = rewritten.get("params")
    if isinstance(raw_params, str):
        decoded_params = _normalize_embedded_inventory_value(raw_params, decode_query=True)
        if decoded_params:
            for key, value in parse_qsl(decoded_params, keep_blank_values=True):
                if not key:
                    continue
                existing_key = {k.lower(): k for k in rewritten if k != "params"}.get(key.lower())
                if existing_key is None:
                    rewritten[key] = value

    lower_to_key = {k.lower(): k for k in rewritten if k != "params"}
    page_key_name: str | None = None
    page_key_value: str | None = None
    for key, value in page_pairs:
        lower = key.lower()
        if lower in {"page", "pageindex", "pt", "_p", "pn", "p", "currentpage"}:
            page_key_name = key
            page_key_value = value
            continue
        existing_key = lower_to_key.get(lower)
        if existing_key:
            rewritten[existing_key] = value
        else:
            rewritten[key] = value
            lower_to_key[lower] = key

    page_num = _inventory_page_number_from_url(page_url)
    if page_num > 1:
        page_param_keys = ("page", "pt", "_p", "pn", "currentpage", "pageindex", "p")
        page_size_keys = (
            "page_size",
            "pagesize",
            "size",
            "limit",
            "hitsperpage",
            "perpage",
            "resultsperpage",
            "recordsperpage",
        )
        offset_keys = ("start", "offset", "from", "recordstart", "skip", "startrow")
        page_size: int | None = None
        for lower in page_size_keys:
            existing_key = lower_to_key.get(lower)
            if not existing_key:
                continue
            try:
                page_size = int(str(rewritten.get(existing_key, "")).strip())
                if page_size > 0:
                    break
            except ValueError:
                continue
        page_key = next((lower_to_key.get(lower) for lower in page_param_keys if lower_to_key.get(lower)), None)
        if page_key:
            rewritten[page_key] = str(page_num)
        elif page_key_name and page_key_value:
            rewritten[page_key_name] = str(page_num)
            lower_to_key[page_key_name.lower()] = page_key_name
        elif page_size is not None:
            rewritten["page"] = str(page_num)
            lower_to_key["page"] = "page"
        if page_size is not None:
            start_value = str(max(0, (page_num - 1) * page_size))
            for lower in offset_keys:
                existing_key = lower_to_key.get(lower)
                if existing_key:
                    rewritten[existing_key] = start_value

    params_pairs = [(k, v) for k, v in rewritten.items() if k != "params" and k]
    if params_pairs:
        rewritten["params"] = urlencode(params_pairs)
    else:
        rewritten.pop("params", None)
    return rewritten


def _extract_inventory_get_requests(html: str, base_url: str) -> list[tuple[str, dict[str, str]]]:
    requests: list[tuple[str, dict[str, str]]] = []
    for pattern in (_DDC_WIDGET_INVENTORY_PAIR_RE, _DDC_WIDGET_INVENTORY_PAIR_RE_REVERSE):
        for match in pattern.finditer(html):
            raw = _normalize_embedded_inventory_value(match.group("url"))
            abs_url = urljoin(base_url, raw)
            raw_params = _normalize_embedded_inventory_value(
                match.group("params"),
                decode_query=True,
            )
            query: dict[str, str] = {k: v for k, v in parse_qsl(raw_params, keep_blank_values=True) if k}
            if raw_params:
                query["params"] = raw_params
            req = (abs_url, query)
            if req not in requests:
                requests.append(req)
    for match in _DDC_WIDGET_PROPS_RE.finditer(html):
        body = match.group("body")
        api_match = _INVENTORY_URL_RE.search(body)
        if not api_match:
            continue
        raw = _normalize_embedded_inventory_value(api_match.group("url"))
        fixed = raw
        abs_url = urljoin(base_url, fixed)

        params_match = re.search(
            r'["\'](?:params|widgetParams|inventoryParams)["\']\s*:\s*["\'](?P<params>[^"\']*)["\']',
            body,
        )
        query: dict[str, str] = {}
        if params_match:
            raw_params = _normalize_embedded_inventory_value(
                params_match.group("params"),
                decode_query=True,
            )
            query = {k: v for k, v in parse_qsl(raw_params, keep_blank_values=True) if k}
            if raw_params:
                query["params"] = raw_params

        req = (abs_url, query)
        if req not in requests:
            requests.append(req)
    return requests


async def _maybe_append_inventory_api_data(
    page_url: str,
    html: str,
    timeout: httpx.Timeout,
) -> str:
    api_urls = _extract_inventory_api_urls(html, page_url)
    api_gets = _extract_inventory_get_requests(html, page_url)
    api_posts = _extract_inventory_post_requests(html, page_url)
    # If cards are already rendered and we do not see any API clues, there is nothing to enrich.
    if _html_looks_inventory_ready(html) and not api_urls and not api_gets and not api_posts:
        return html
    if not api_urls and not api_gets and not api_posts:
        return html

    payloads: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for api_url, body in api_posts[:2]:
            try:
                rewritten_body = _rewrite_inventory_post_body_for_page(body, page_url)
                r = await client.post(
                    api_url,
                    headers={**_browser_headers(), "Content-Type": "application/json"},
                    content=rewritten_body,
                )
                r.raise_for_status()
            except Exception as e:
                logger.debug("Inventory API POST failed for %s: %s", api_url, e)
                continue
            content = r.text.strip()
            if not content.startswith("{"):
                continue
            payloads.append(content)
        if payloads:
            injected = "".join(
                f'\n<script type="application/json" data-ms-source="inventory-api">{p}</script>\n'
                for p in payloads
            )
            logger.info(
                "Enriched %s with %d inventory API payload(s)",
                page_url,
                len(payloads),
            )
            return html + injected
        for api_url, query in api_gets[:2]:
            try:
                rewritten_query = _rewrite_inventory_get_query_for_page(query, page_url)
                r = await client.get(api_url, params=rewritten_query or None, headers=_browser_headers())
                if r.status_code == 403 and settings.zenrows_api_key:
                    full_url = api_url
                    if rewritten_query:
                        full_url = f"{api_url}?{urlencode(rewritten_query)}"
                    content = await _zenrows_fetch(full_url, timeout, js_render=False)
                    payloads.append(content)
                    continue
                r.raise_for_status()
            except Exception as e:
                logger.debug("Inventory API GET failed for %s: %s", api_url, e)
                continue
            content = r.text.strip()
            if not content.startswith("{"):
                continue
            payloads.append(content)
        for api_url in api_urls[:2]:
            try:
                r = await client.get(api_url, headers=_browser_headers())
                r.raise_for_status()
            except Exception as e:
                logger.debug("Inventory API fetch failed for %s: %s", api_url, e)
                continue
            content = r.text.strip()
            if not content.startswith("{"):
                continue
            payloads.append(content)

    if not payloads:
        return html

    injected = "".join(
        f'\n<script type="application/json" data-ms-source="inventory-api">{p}</script>\n'
        for p in payloads
    )
    logger.info(
        "Enriched %s with %d inventory API payload(s)",
        page_url,
        len(payloads),
    )
    return html + injected
