"""Fetch dealership pages via managed scrapers (ZenRows / ScrapingBee) or direct HTTP."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_page_html(url: str) -> tuple[str, str]:
    """
    Return (html, method_used).
    Tries ZenRows, then ScrapingBee, then a plain httpx GET.
    """
    timeout = httpx.Timeout(settings.scrape_timeout)

    if settings.zenrows_api_key:
        try:
            html = await _zenrows_fetch(url, timeout)
            return html, "zenrows"
        except Exception as e:
            logger.warning("ZenRows fetch failed for %s: %s", url, e)

    if settings.scrapingbee_api_key:
        try:
            html = await _scrapingbee_fetch(url, timeout)
            return html, "scrapingbee"
        except Exception as e:
            logger.warning("ScrapingBee fetch failed for %s: %s", url, e)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(url, headers=_browser_headers())
        r.raise_for_status()
        return r.text, "direct"


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
        "js_render": "false",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(api_url, params=params)
        r.raise_for_status()
        return r.text


async def _scrapingbee_fetch(url: str, timeout: httpx.Timeout) -> str:
    """https://www.scrapingbee.com/documentation/"""
    base = "https://app.scrapingbee.com/api/v1/"
    qs = urlencode({"api_key": settings.scrapingbee_api_key, "url": url, "render_js": "false"})
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(f"{base}?{qs}")
        r.raise_for_status()
        return r.text
