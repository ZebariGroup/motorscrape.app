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
_DIRECT_FIRST_RENDER_PREFERRED_PLATFORMS = frozenset({
    "dealer_on",
    "ford_family_inventory",
    "gm_family_inventory",
    "honda_acura_inventory",
    "toyota_lexus_oem_inventory",
})

# OEM Sonic / si-vehicle-box SRP — same readiness rules as Ford family (placeholders, JSON-LD counts).
_SONIC_STYLE_INVENTORY_PLATFORMS = frozenset(
    {
        "ford_family_inventory",
        "kia_inventory",
    }
)
# Nissan/INFINITI pages share the Sonic shell but often include enough JSON-LD
# in the direct response for structured extraction.  They use the relaxed
# _SONIC_RELAXED_INVENTORY_PLATFORMS path which accepts direct HTML when the
# page has sufficient vehicle signals.
_SONIC_RELAXED_INVENTORY_PLATFORMS = frozenset(
    {
        "nissan_infiniti_inventory",
        "toyota_lexus_oem_inventory",
    }
)

# Long-lived clients reuse TLS sessions and connection pools (per-request timeout still applies).
_scraper_client_lock = asyncio.Lock()
_direct_httpx_client: httpx.AsyncClient | None = None
_standard_httpx_client: httpx.AsyncClient | None = None
_HTTPX_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=100)


async def _get_direct_httpx_client() -> httpx.AsyncClient:
    """Direct dealer fetches (verify=False for broken dealer TLS)."""
    global _direct_httpx_client
    if _direct_httpx_client is None:
        async with _scraper_client_lock:
            if _direct_httpx_client is None:
                _direct_httpx_client = httpx.AsyncClient(
                    verify=False,
                    follow_redirects=True,
                    limits=_HTTPX_LIMITS,
                    timeout=httpx.Timeout(30.0),
                )
    return _direct_httpx_client


async def _get_standard_httpx_client() -> httpx.AsyncClient:
    """ZenRows, ScrapingBee, and inventory API enrichment (verified TLS)."""
    global _standard_httpx_client
    if _standard_httpx_client is None:
        async with _scraper_client_lock:
            if _standard_httpx_client is None:
                _standard_httpx_client = httpx.AsyncClient(
                    follow_redirects=True,
                    limits=_HTTPX_LIMITS,
                    timeout=httpx.Timeout(30.0),
                )
    return _standard_httpx_client


async def close_scraper_http_clients() -> None:
    """Close pooled httpx clients (app shutdown)."""
    global _direct_httpx_client, _standard_httpx_client
    async with _scraper_client_lock:
        if _direct_httpx_client is not None:
            await _direct_httpx_client.aclose()
            _direct_httpx_client = None
        if _standard_httpx_client is not None:
            await _standard_httpx_client.aclose()
            _standard_httpx_client = None


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


def _zenrows_cooldown_remaining_seconds() -> float:
    return max(0.0, _zenrows_cooldown_until_monotonic - time.monotonic())


async def _await_zenrows_cooldown_if_needed() -> None:
    remaining = _zenrows_cooldown_remaining_seconds()
    if remaining <= 0:
        return
    logger.info("Waiting %.1fs for ZenRows cooldown before retrying", remaining)
    await asyncio.sleep(remaining)


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
    # Dealer Spike cached inventory JS can be generic all-inventory (VehInv.js)
    # or split by new/used (NVehInv.js / UVehInv.js).
    re.compile(r'["\'](?P<url>/imglib/Inventory/cache/\d+/(?:[NU])?VehInv\.js[^"\']*)["\']', re.I),
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
    "inventory-card",
    "featuredvehicle",
    "vehiclecard",
    "inventory_list",
    "inventory-listing",
    "sbalerttitle",
    "srpvehicle",
    "v7list-results__item",
    "v7list-vehicle",
    "vehicle-heading__link",
    "si-vehicle-box",
    "inventory_listing",
    "unlockctadiscountdata",
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
    # Akamai behavioral challenge pages (Tesla and other OEM sites) can return
    # 200 HTML shells that look "non-empty" but contain no inventory content.
    "sec-if-cpt-container",
    "scf-akamai-logo",
    "akamai-protected-by",
)
_STRUCTURE_HINTS = (
    '"inventory":',
    '"inventoryapiurl"',
    "__next_data__",
    '"@type":"vehicle"',
    '"@type": "vehicle"',
    '"vehicleidentificationnumber"',
    '"vdpurl"',
    'name="boat_details"',
    "name='boat_details'",
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
            "v7list-results__item",
            "v7list-vehicle",
            "vehicle-heading__link",
            "data-component=\"result-tile\"",
            "data-component='result-tile'",
        )
        if marker in lower
    )
    html_sufficient = _direct_html_sufficient(html, page_kind=page_kind, platform_id=platform_id)
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
        err_lower = str(e).lower()
        if (
            url.startswith("https://")
            and (
                "tlsv1 alert internal error" in err_lower
                or "sslv3_alert_handshake_failure" in err_lower
                or "sslv3 alert handshake failure" in err_lower
            )
        ):
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
            # Inventory SRPs already consume most of the dealer worker budget through
            # provider detection, rendering, and pagination. A second managed-render
            # wait tends to create long-tail timeouts in production without improving
            # yield enough, so keep inventory pages to a single rendered wait.
            return tuple(waits)
        out: list[int] = []
        for wait in waits:
            if wait not in out:
                out.append(wait)
        return tuple(out)

    effective_url = url
    inventory_render_plan = inventory_render_plan_for_url(url, platform_id=platform_id) if page_kind == "inventory" else None
    playwright_instructions = inventory_render_plan.playwright_instructions if inventory_render_plan else None
    zenrows_js_instructions = inventory_render_plan.zenrows_js_instructions if inventory_render_plan else None
    attempted_playwright_early = False

    if (
        prefer_render
        and page_kind == "inventory"
        and platform_id not in _DIRECT_FIRST_RENDER_PREFERRED_PLATFORMS
    ):
        # Some platforms truly need a browser pass first, but DealerOn inventory pages are often
        # fully SSR and should stay on the cheap direct path before trying Playwright.
        attempted_playwright_early = True
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
            if _direct_html_sufficient(html, page_kind=page_kind, platform_id=platform_id):
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

    if not attempted_playwright_early:
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
                platform_id=platform_id,
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
            render_wait_ms = (
                effective_render_plan.zenrows_wait_ms
                if effective_render_plan and effective_render_plan.zenrows_wait_ms is not None
                else settings.zenrows_wait_ms
            )
            for wait_ms in _retry_waits(
                render_wait_ms,
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
                    platform_id=platform_id,
                )
                if html is not None:
                    return html, "zenrows_rendered"

    # 3) ScrapingBee: static then rendered
    if settings.scrapingbee_api_key:
        try:
            html = await _scrapingbee_fetch(effective_url, timeout, render_js=False)
            html = await _maybe_append_inventory_api_data(effective_url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind, platform_id=platform_id):
                _m("scrapingbee_static_ok")
                return html, "scrapingbee_static"
            _m("scrapingbee_static_insufficient")
            failures.append("scrapingbee_static: insufficient")
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
                    if _direct_html_sufficient(html, page_kind=page_kind, platform_id=platform_id):
                        _m("scrapingbee_rendered_ok")
                        return html, "scrapingbee_rendered"
                    _m("scrapingbee_rendered_insufficient")
                    failures.append("scrapingbee_rendered: insufficient")
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
    if hits.select_one(
        "[data-vehicle], .result-wrap.new-vehicle, .carbox, .vehicle-card, .si-vehicle-box, .v7list-results__item, .v7list-vehicle, .vehicle-heading__link"
    ):
        return False
    return True


def _dealer_on_has_only_skeleton_cards(html: str) -> bool:
    """DealerOn SRPs ship empty skeleton vehicle-card divs that JS populates later.

    When every vehicle-card element carries the ``skeleton`` class and there are
    no populated data-vin attributes beyond JSON-LD, direct HTML is insufficient
    and the page must be JS-rendered to get real inventory.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    cards = soup.select(".vehicle-card")
    if not cards:
        return False
    non_skeleton = [c for c in cards if "skeleton" not in (c.get("class") or [])]
    if non_skeleton:
        return False
    populated = soup.select("[data-vehicle-title], [data-make], [data-model]")
    return len(populated) == 0


def _has_dom_inventory_result_tiles(html: str) -> bool:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    return (
        soup.find("li", attrs={"data-component": "result-tile"}) is not None
        or soup.select_one("[data-component='result-tile']") is not None
    )


def _has_rendered_marinemax_cards(html: str) -> bool:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    for anchor in soup.select("a.mmx-boat-card[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or "{" in href or href.startswith(":"):
            continue
        title = anchor.select_one(".title")
        title_text = title.get_text(" ", strip=True) if title else ""
        if title_text and "{{" not in title_text:
            return True
    for anchor in soup.select("a[href*='/boats-for-sale/details/']"):
        href = str(anchor.get("href") or "").strip()
        if href and "{{" not in href and "{" not in href:
            return True
    for node in soup.select("[class*='boat-card'] a[href], .boat-card a[href]"):
        href = str(node.get("href") or "").strip()
        if not href or "{" in href:
            continue
        title = node.get_text(" ", strip=True)
        if title and "{{" not in title and len(title) > 3:
            return True
    return False


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


def _has_rendered_sonic_vehicle_cards(html: str) -> bool:
    """True when Sonic/TeamVelocity inventory cards are present in DOM, not just script blobs."""
    lower = html.lower()
    # Team Velocity "design-2" / Vue SRPs often put VDP URLs only in @click handlers or JSON
    # blobs — no <a href="/viewdetails/..."> until hydration. Treat multiple /viewdetails/
    # references plus listing chrome as populated HTML so we do not misclassify as a thin SPA.
    if (
        lower.count("/viewdetails/") >= 3
        and (
            "inventory_listing" in lower
            or "vehiclebox" in lower
            or "srp-vehicles-container" in lower
        )
    ):
        return True
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return False
    return (
        soup.select_one(".si-vehicle-box") is not None
        or soup.select_one(".inventory_listing a[href*='/viewdetails/']") is not None
        or soup.select_one("a[href*='/viewdetails/']") is not None
    )


def _looks_like_sonic_teamvelocity_spa(html: str) -> bool:
    """Detect Sonic/TeamVelocity DMS inventory pages that are pure Vue SPAs.
    These pages embed a small number of vehicles in JSON-LD for SEO but load
    the full inventory list via JavaScript — direct HTML is always incomplete.
    """
    lower = html.lower()
    if not (
        "inventory_listing" in lower
        and "secureoffersites.com" in lower
        and ("teamvelocityportal.com" in lower or "sonic" in lower or "resultcount" in lower)
    ):
        return False
    # If we can see rendered cards in the DOM, this is not a thin JS shell.
    return not _has_rendered_sonic_vehicle_cards(html)


def _count_structured_vehicle_signals(html: str) -> int:
    lower = html.lower()
    return sum(
        lower.count(marker)
        for marker in (
            '"@type":"vehicle"',
            '"@type": "vehicle"',
            '"vehicleidentificationnumber"',
            '"vdpurl"',
            '"/viewdetails/',
        )
    )


def _has_tesla_inventory_payload_hint(html: str) -> bool:
    lower = html.lower()
    if "tesla" not in lower:
        return False
    if "/inventory/new/" in lower or "/inventory/used/" in lower:
        return True
    return '"vin"' in lower and ('"model"' in lower or "cybertruck" in lower)


_SONIC_JSONLD_SUFFICIENT_THRESHOLD = 6


def _direct_html_sufficient(html: str, *, page_kind: PageKind, platform_id: str | None = None) -> bool:
    if _looks_like_block_page(html):
        return False
    if page_kind == "inventory" and _looks_like_sonic_teamvelocity_spa(html):
        # Sonic/TeamVelocity SPA pages embed JSON-LD for SEO but load inventory
        # via Vue.js.  When the JSON-LD has enough vehicle signals, accept the
        # direct HTML so structured extraction can pull from the JSON-LD without
        # waiting for a full JS render.
        vehicle_signals = _count_structured_vehicle_signals(html)
        if vehicle_signals >= _SONIC_JSONLD_SUFFICIENT_THRESHOLD:
            return True
        return False
    if page_kind == "inventory" and platform_id in _SONIC_STYLE_INVENTORY_PLATFORMS:
        if _looks_like_placeholder_inventory(html):
            return False
        if _looks_like_empty_inventory_shell(html):
            return False
        if _html_looks_inventory_ready(html, platform_id=platform_id):
            return True
        vehicle_signals = _count_structured_vehicle_signals(html)
        if _has_structured_inventory_hint(html) and vehicle_signals >= 3:
            return True
        if vehicle_signals >= _SONIC_JSONLD_SUFFICIENT_THRESHOLD:
            return True
    elif page_kind == "inventory" and platform_id in _SONIC_RELAXED_INVENTORY_PLATFORMS:
        if _looks_like_placeholder_inventory(html):
            return False
        if _looks_like_empty_inventory_shell(html):
            return False
        if _html_looks_inventory_ready(html, platform_id=platform_id):
            return True
        if _has_structured_inventory_hint(html):
            return True
        if _count_structured_vehicle_signals(html) >= 3:
            return True
    elif page_kind == "inventory" and platform_id == "oneaudi_falcon":
        if _looks_like_placeholder_inventory(html):
            return False
        if _looks_like_empty_inventory_shell(html):
            return False
        if _html_looks_inventory_ready(html, platform_id=platform_id):
            return True
        if _has_structured_inventory_hint(html) and _count_structured_vehicle_signals(html) >= 3:
            return True
    elif page_kind == "inventory" and platform_id == "dealer_on":
        if _looks_like_empty_inventory_shell(html):
            return False
        if _dealer_on_has_only_skeleton_cards(html):
            return False
        if _html_looks_inventory_ready(html, platform_id=platform_id):
            return True
    elif page_kind == "inventory" and platform_id == "tesla_inventory":
        if _looks_like_empty_inventory_shell(html):
            return False
        if _html_looks_inventory_ready(html, platform_id=platform_id):
            return True
        if _has_tesla_inventory_payload_hint(html):
            return True
    elif _has_structured_inventory_hint(html):
        return True
    if page_kind == "inventory" and _looks_like_placeholder_inventory(html):
        return False
    if page_kind == "inventory" and _looks_like_empty_inventory_shell(html):
        return False
    if _html_looks_inventory_ready(html, platform_id=platform_id):
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
        "Accept-Encoding": "gzip, deflate, br",
    }


def _fallback_browser_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _inventory_api_headers(*, content_type: str | None = None) -> dict[str, str]:
    headers = {
        **_browser_headers(),
        # Dealer.com inventory APIs sometimes return Brotli bodies that the runtime
        # does not transparently decode, so prefer identity/gzip here.
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "identity",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def _direct_get(url: str, timeout: httpx.Timeout) -> str:
    client = await _get_direct_httpx_client()
    r = await client.get(url, headers=_browser_headers(), timeout=timeout)
    if r.status_code == 403:
        retry = await client.get(url, headers=_fallback_browser_headers(), timeout=timeout)
        retry.raise_for_status()
        return retry.text
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
    await _await_zenrows_cooldown_if_needed()

    attempts = max(1, int(settings.zenrows_request_attempts))
    backoff_seconds = max(0.0, float(settings.zenrows_retry_backoff_ms) / 1000.0)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        await _await_zenrows_cooldown_if_needed()
        try:
            zenrows_sem = await _zenrows_concurrency_gate()
            managed_sem = await _managed_scraper_concurrency_gate()
            async with managed_sem:
                async with zenrows_sem:
                    client = await _get_standard_httpx_client()
                    r = await client.get(api_url, params=params, timeout=timeout)
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
            client = await _get_standard_httpx_client()
            r = await client.get(f"{base}?{qs}", timeout=timeout)
            r.raise_for_status()
            return r.text


def _html_looks_inventory_ready(html: str, *, platform_id: str | None = None) -> bool:
    lower = html.lower()
    if platform_id == "dealer_spike":
        # Dealer Spike motorcycle SRPs often render inventory rows without modern
        # card classes; rely on repeated stock/detail signals to avoid false
        # "insufficient" classifications on fully populated pages.
        stock_rows = lower.count("stock #</strong>")
        detail_links = lower.count("view details")
        if stock_rows >= 3 and detail_links >= 3:
            return True
    if platform_id in _SONIC_STYLE_INVENTORY_PLATFORMS:
        return (
            "vehicle_results_label" in lower
            or "inventory_listing" in lower
            or "si-vehicle-box" in lower
            or "/viewdetails/" in lower
            or any(marker in lower for marker in _INVENTORY_HINTS)
            or _has_dom_inventory_result_tiles(html)
        )
    if platform_id in _SONIC_RELAXED_INVENTORY_PLATFORMS:
        return (
            "vehicle_results_label" in lower
            or "inventory_listing" in lower
            or "si-vehicle-box" in lower
            or "/viewdetails/" in lower
            or "ws-inv-data" in lower
            or "inventoryapiurl" in lower
            or any(marker in lower for marker in _INVENTORY_HINTS)
            or _has_dom_inventory_result_tiles(html)
        )
    return (
        any(marker in lower for marker in _INVENTORY_HINTS)
        or _has_dom_inventory_result_tiles(html)
        or _has_rendered_marinemax_cards(html)
    )


_DEALER_SPIKE_VEHICLES_RE = re.compile(
    r"(?:^|\xef\xbb\xbf|\ufeff|;)\s*var\s+Vehicles\s*=\s*(\[.*?\])\s*;?\s*$",
    re.S | re.M,
)


def _extract_dealer_spike_vehicle_js(text: str) -> list[dict]:
    """Parse Dealer Spike Marine NVehInv.js / UVehInv.js into vehicle dicts."""
    m = _DEALER_SPIKE_VEHICLES_RE.search(text)
    if not m:
        return []
    try:
        records = json.loads(m.group(1), strict=False)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(records, list):
        return []
    out: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        make = r.get("manuf") or r.get("brand")
        model = r.get("model")
        if not make and not model:
            continue
        stock = r.get("stockno") or r.get("id")
        year = r.get("bike_year") or r.get("year")
        price = r.get("price") or r.get("sale_price") or r.get("MSRP") or r.get("retail_price")
        vin = r.get("vin")
        condition_code = str(r.get("type") or "").upper()
        condition = "new" if condition_code == "N" else ("used" if condition_code in ("U", "P") else None)
        image = r.get("bike_image") or r.get("stock_image")
        hours = r.get("enginehours")
        unit_id = r.get("id")
        out.append({k: v for k, v in {
            "make": make,
            "model": model,
            "year": year,
            "stock": stock,
            "vin": vin,
            "price": price,
            "condition": condition,
            "color": r.get("color"),
            "engineHours": hours,
            "image_url": image,
            "_dealer_spike_unit_id": unit_id,
        }.items() if v not in (None, "", 0)})
    logger.info("Dealer Spike NVehInv.js: parsed %d vehicle records", len(out))
    return out


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
    for key in ("page", "pageindex", "pt", "_p", "pn", "pg", "p", "currentpage"):
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
        path_lower = parts.path.rstrip("/").lower()
        path_segments = [segment for segment in path_lower.split("/") if segment]
        scoped_inventory_model_path = (
            len(path_segments) >= 4
            and path_segments[0] == "inventory"
            and path_segments[1] in {"new", "used"}
        )
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
            "pg",
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
            if scoped_inventory_model_path:
                # Jeffrey Acura / Team Velocity-style model pages often publish marketing
                # facets like paymenttype/years/instock in addition to the real
                # /inventory/new/{make}/{model} path. Those noisy query variants can
                # return thinner HTML than the canonical model landing, so keep only
                # structural paging/sort keys on these scoped URLs.
                dropped = True
                continue
            if lower.startswith("paymenttype") or lower == "payment":
                dropped = True
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
        if lower in {"page", "pageindex", "pt", "_p", "pn", "pg", "p", "currentpage"}:
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
        page_param_keys = ("page", "pt", "_p", "pn", "pg", "currentpage", "pageindex", "p")
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
    client = await _get_standard_httpx_client()
    for api_url, body in api_posts[:2]:
        try:
            rewritten_body = _rewrite_inventory_post_body_for_page(body, page_url)
            r = await client.post(
                api_url,
                headers=_inventory_api_headers(content_type="application/json"),
                content=rewritten_body,
                timeout=timeout,
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
            r = await client.get(
                api_url,
                params=rewritten_query or None,
                headers=_inventory_api_headers(),
                timeout=timeout,
            )
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
            r = await client.get(api_url, headers=_inventory_api_headers(), timeout=timeout)
            r.raise_for_status()
        except Exception as e:
            logger.debug("Inventory API fetch failed for %s: %s", api_url, e)
            continue
        content = r.text.strip()
        # Dealer Spike NVehInv.js uses `var Vehicles=[...]` format — parse and re-inject as JSON.
        # The file often starts with a UTF-8 BOM (\ufeff) so check both with and without it.
        content_stripped = content.lstrip("\ufeff\xef\xbb\xbf")
        if content_stripped.startswith("var Vehicles") or "var Vehicles=" in content[:80]:
            dsp_records = _extract_dealer_spike_vehicle_js(content)
            if dsp_records:
                payloads.append(json.dumps({"inventory": dsp_records}, separators=(",", ":")))
            continue
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
