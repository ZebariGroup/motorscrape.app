"""Fetch dealership pages via direct HTTP first, then managed scrapers (ZenRows / ScrapingBee) when needed."""

from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlencode
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PageKind = Literal["homepage", "inventory"]

_INVENTORY_URL_RE = re.compile(r'"inventoryApiURL"\s*:\s*"(?P<url>[^"]+)"')
# Extra embedded config keys seen on dealer SPAs
_EXTRA_API_RES = (
    re.compile(r'"inventoryApiUrl"\s*:\s*"(?P<url>[^"]+)"', re.I),
    re.compile(r'"inventory_url"\s*:\s*"(?P<url>[^"]+)"', re.I),
    re.compile(r'"inventoryEndpoint"\s*:\s*"(?P<url>[^"]+)"', re.I),
)
_INVENTORY_HINTS = (
    "vehicle-card-title",
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
)
_STRUCTURE_HINTS = (
    '"inventory":',
    '"inventoryapiurl"',
    "__next_data__",
    "application/ld+json",
    '"@type":"vehicle"',
    '"@type": "vehicle"',
    '"vehicleidentificationnumber"',
    '"vdpurl"',
)


async def fetch_page_html(
    url: str,
    *,
    page_kind: PageKind = "inventory",
    metrics: dict[str, int] | None = None,
) -> tuple[str, str]:
    """
    Return (html, method_used).

    Order: direct HTTP → optional inventory API enrichment → if insufficient, ZenRows
    (static, then JS render) → same for ScrapingBee → last-chance direct error.

    method_used values: direct, zenrows_static, zenrows_rendered, scrapingbee_static,
    scrapingbee_rendered (and direct after managed retry is still the managed tag that succeeded).
    """
    timeout = httpx.Timeout(settings.scrape_timeout)
    failures: list[str] = []

    def _m(key: str) -> None:
        if metrics is not None:
            metrics[key] = metrics.get(key, 0) + 1

    # 1) Direct first (cheapest)
    try:
        html = await _direct_get(url, timeout)
        html = await _maybe_append_inventory_api_data(url, html, timeout)
        if _direct_html_sufficient(html, page_kind=page_kind):
            _m("direct_ok")
            return html, "direct"
        logger.info("Direct fetch insufficient for %s (%s), escalating to managed scrapers", url, page_kind)
        _m("direct_insufficient")
    except Exception as e:
        failures.append(f"direct: {e}")
        logger.debug("Direct fetch failed for %s: %s", url, e)
        _m("direct_failed")

    # 2) ZenRows: static then rendered
    if settings.zenrows_api_key:
        try:
            html = await _zenrows_fetch(url, timeout, js_render=False)
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind):
                _m("zenrows_static_ok")
                return html, "zenrows_static"
        except Exception as e:
            sanitized = str(e).replace(settings.zenrows_api_key, "***")
            logger.warning("ZenRows static fetch failed for %s: %s", url, sanitized)
            failures.append(f"zenrows_static: {sanitized}")

        try:
            html = await _zenrows_fetch(
                url,
                timeout,
                js_render=True,
                wait_ms=settings.zenrows_wait_ms,
            )
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            _m("zenrows_rendered_ok")
            return html, "zenrows_rendered"
        except Exception as e:
            sanitized = str(e).replace(settings.zenrows_api_key, "***")
            logger.warning("ZenRows rendered fetch failed for %s: %s", url, sanitized)
            failures.append(f"zenrows_rendered: {sanitized}")

    # 3) ScrapingBee: static then rendered
    if settings.scrapingbee_api_key:
        try:
            html = await _scrapingbee_fetch(url, timeout, render_js=False)
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind):
                _m("scrapingbee_static_ok")
                return html, "scrapingbee_static"
        except Exception as e:
            logger.warning("ScrapingBee static fetch failed for %s: %s", url, e)
            failures.append(f"scrapingbee_static: {e}")

        try:
            html = await _scrapingbee_fetch(
                url,
                timeout,
                render_js=True,
                wait_ms=settings.scrapingbee_wait_ms,
            )
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            _m("scrapingbee_rendered_ok")
            return html, "scrapingbee_rendered"
        except Exception as e:
            logger.warning("ScrapingBee rendered fetch failed for %s: %s", url, e)
            failures.append(f"scrapingbee_rendered: {e}")

    # 4) If we had a direct body that was "insufficient", return it rather than failing completely
    try:
        html = await _direct_get(url, timeout)
        html = await _maybe_append_inventory_api_data(url, html, timeout)
        _m("direct_fallback_ok")
        return html, "direct"
    except Exception as e:
        failures.append(f"direct_retry: {e}")

    detail = " | ".join(failures)
    raise RuntimeError(f"All fetch methods failed for {url}: {detail}") from None


def _looks_like_block_page(html: str) -> bool:
    if not html or len(html.strip()) < 200:
        return True
    lower = html.lower()
    return any(m in lower for m in _BLOCK_MARKERS)


def _has_structured_inventory_hint(html: str) -> bool:
    lower = html.lower()
    return any(h in lower for h in _STRUCTURE_HINTS)


def _direct_html_sufficient(html: str, *, page_kind: PageKind) -> bool:
    if _looks_like_block_page(html):
        return False
    if _has_structured_inventory_hint(html):
        return True
    if _html_looks_inventory_ready(html):
        return True
    lower = html.lower()
    if page_kind == "homepage":
        return len(html) >= 1800 and ("href=" in lower or "inventory" in lower)
    # inventory page: allow smaller SPAs if structured markers exist; else need size/cards
    return len(html) >= 5000 or _html_looks_inventory_ready(html)


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
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers=_browser_headers())
        r.raise_for_status()
        return r.text


async def _zenrows_fetch(
    url: str,
    timeout: httpx.Timeout,
    *,
    js_render: bool,
    wait_ms: int = 0,
) -> str:
    """https://docs.zenrows.com/universal-scraper-api"""
    api_url = "https://api.zenrows.com/v1/"
    params: dict[str, str] = {
        "apikey": settings.zenrows_api_key,
        "url": url,
        "js_render": "true" if js_render else "false",
    }
    if js_render and wait_ms > 0:
        params["wait"] = str(wait_ms)
    if settings.zenrows_premium_proxy:
        params["premium_proxy"] = "true"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(api_url, params=params)
        r.raise_for_status()
        return r.text


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
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(f"{base}?{qs}")
        r.raise_for_status()
        return r.text


def _html_looks_inventory_ready(html: str) -> bool:
    lower = html.lower()
    return any(marker in lower for marker in _INVENTORY_HINTS)


def _extract_inventory_api_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for m in _INVENTORY_URL_RE.finditer(html):
        raw = m.group("url")
        fixed = raw.replace("\\/", "/")
        abs_url = urljoin(base_url, fixed)
        if abs_url not in urls:
            urls.append(abs_url)
    for cre in _EXTRA_API_RES:
        for m in cre.finditer(html):
            raw = m.group("url")
            fixed = raw.replace("\\/", "/")
            abs_url = urljoin(base_url, fixed)
            if abs_url not in urls:
                urls.append(abs_url)
    return urls


async def _maybe_append_inventory_api_data(
    page_url: str,
    html: str,
    timeout: httpx.Timeout,
) -> str:
    # If cards are already rendered there is nothing to enrich.
    if _html_looks_inventory_ready(html):
        return html

    api_urls = _extract_inventory_api_urls(html, page_url)
    if not api_urls:
        return html

    payloads: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
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
