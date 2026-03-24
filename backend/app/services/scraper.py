"""Fetch dealership pages via managed scrapers (ZenRows / ScrapingBee) or direct HTTP."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_INVENTORY_URL_RE = re.compile(r'"inventoryApiURL"\s*:\s*"(?P<url>[^"]+)"')
_INVENTORY_HINTS = (
    "vehicle-card-title",
    "vehiclecard",
    "inventory_list",
    "inventory-listing",
    "srpvehicle",
)


async def fetch_page_html(url: str) -> tuple[str, str]:
    """
    Return (html, method_used).
    Tries ZenRows, then ScrapingBee, then a plain httpx GET.
    """
    timeout = httpx.Timeout(settings.scrape_timeout)
    failures: list[str] = []

    if settings.zenrows_api_key:
        try:
            html = await _zenrows_fetch(url, timeout)
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            return html, "zenrows"
        except Exception as e:
            sanitized = str(e).replace(settings.zenrows_api_key, "***")
            logger.warning("ZenRows fetch failed for %s: %s", url, sanitized)
            failures.append(f"zenrows: {sanitized}")

    if settings.scrapingbee_api_key:
        try:
            html = await _scrapingbee_fetch(url, timeout)
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            return html, "scrapingbee"
        except Exception as e:
            logger.warning("ScrapingBee fetch failed for %s: %s", url, e)
            failures.append(f"scrapingbee: {e}")

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(url, headers=_browser_headers())
            r.raise_for_status()
            html = await _maybe_append_inventory_api_data(url, r.text, timeout)
            return html, "direct"
    except Exception as e:
        failures.append(f"direct: {e}")
        detail = " | ".join(failures)
        raise RuntimeError(f"All fetch methods failed for {url}: {detail}") from e


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


async def _zenrows_fetch(url: str, timeout: httpx.Timeout) -> str:
    """https://docs.zenrows.com/universal-scraper-api"""
    api_url = "https://api.zenrows.com/v1/"
    params = {
        "apikey": settings.zenrows_api_key,
        "url": url,
        "js_render": "true",
        "wait": "5000",
    }
    if settings.zenrows_premium_proxy:
        params["premium_proxy"] = "true"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(api_url, params=params)
        r.raise_for_status()
        return r.text


async def _scrapingbee_fetch(url: str, timeout: httpx.Timeout) -> str:
    """https://www.scrapingbee.com/documentation/"""
    base = "https://app.scrapingbee.com/api/v1/"
    qs = urlencode(
        {
            "api_key": settings.scrapingbee_api_key,
            "url": url,
            "render_js": "true",
            "wait": "5000",
        }
    )
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
