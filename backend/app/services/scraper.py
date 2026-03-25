"""Fetch dealership pages via direct HTTP first, then managed scrapers (ZenRows / ScrapingBee) when needed."""

from __future__ import annotations

import logging
import re
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

PageKind = Literal["homepage", "inventory"]

_INVENTORY_URL_RE = re.compile(r'"inventoryApiURL"\s*:\s*"(?P<url>[^"]+)"')
# Extra embedded config keys seen on dealer SPAs
_EXTRA_API_RES = (
    re.compile(r'"inventoryApiUrl"\s*:\s*"(?P<url>[^"]+)"', re.I),
    re.compile(r'"inventory_url"\s*:\s*"(?P<url>[^"]+)"', re.I),
    re.compile(r'"inventoryEndpoint"\s*:\s*"(?P<url>[^"]+)"', re.I),
    re.compile(r"vehicle_data_url\s*=\s*['\"](?P<url>[^'\"]+)['\"]", re.I),
)
_WS_INV_FETCH_RE = re.compile(
    r'fetch\("(?P<url>/api/widget/ws-inv-data/getInventory)".*?body:decodeURI\("(?P<body>.*?)"\)',
    re.S,
)
_DDC_WIDGET_PROPS_RE = re.compile(
    r'DDC\.WidgetData\[[^\]]+\]\.props\s*=\s*\{(?P<body>.*?)\n\}\s*</script>',
    re.S,
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


async def _direct_get_with_express_www_fallback(url: str, timeout: httpx.Timeout) -> str:
    """
    Try direct GET; on 403 from an express.* host, try the same path on www.* once
    (some Dealer.com groups answer on www while express is Cloudflare-challenged).
    """
    try:
        return await _direct_get(url, timeout)
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

    if (
        page_kind == "inventory"
        and _host_is_express_retail(url)
        and (settings.zenrows_api_key or settings.scrapingbee_api_key)
    ):
        prefer_render = True

    def _m(key: str) -> None:
        if metrics is not None:
            metrics[key] = metrics.get(key, 0) + 1

    def _retry_waits(base_wait_ms: int) -> tuple[int, ...]:
        waits = [max(0, base_wait_ms)]
        if page_kind == "inventory":
            waits.append(max(base_wait_ms * 2, base_wait_ms + 3000, 6000))
        out: list[int] = []
        for wait in waits:
            if wait not in out:
                out.append(wait)
        return tuple(out)

    if prefer_render and page_kind == "inventory":
        if settings.zenrows_api_key:
            for wait_ms in _retry_waits(settings.zenrows_wait_ms):
                try:
                    html = await _zenrows_fetch(
                        url,
                        timeout,
                        js_render=True,
                        wait_ms=wait_ms,
                    )
                    html = await _maybe_append_inventory_api_data(url, html, timeout)
                    if _direct_html_sufficient(html, page_kind=page_kind):
                        _m("zenrows_rendered_ok")
                        return html, "zenrows_rendered"
                    _m("zenrows_rendered_insufficient")
                except Exception as e:
                    sanitized = str(e).replace(settings.zenrows_api_key, "***")
                    logger.warning("ZenRows preferred rendered fetch failed for %s: %s", url, sanitized)
                    failures.append(f"zenrows_rendered_preferred: {sanitized}")

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
                    logger.warning("ScrapingBee preferred rendered fetch failed for %s: %s", url, e)
                    failures.append(f"scrapingbee_rendered_preferred: {e}")

    # 1) Direct first (cheapest)
    try:
        html = await _direct_get_with_express_www_fallback(url, timeout)
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

        for wait_ms in _retry_waits(settings.zenrows_wait_ms):
            try:
                html = await _zenrows_fetch(
                    url,
                    timeout,
                    js_render=True,
                    wait_ms=wait_ms,
                )
                html = await _maybe_append_inventory_api_data(url, html, timeout)
                if _direct_html_sufficient(html, page_kind=page_kind):
                    _m("zenrows_rendered_ok")
                    return html, "zenrows_rendered"
                _m("zenrows_rendered_insufficient")
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
                logger.warning("ScrapingBee rendered fetch failed for %s: %s", url, e)
                failures.append(f"scrapingbee_rendered: {e}")

    # 4) If we had a direct body that was "insufficient", return it rather than failing completely
    try:
        html = await _direct_get_with_express_www_fallback(url, timeout)
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


def _direct_html_sufficient(html: str, *, page_kind: PageKind) -> bool:
    if _looks_like_block_page(html):
        return False
    if page_kind == "inventory" and _looks_like_placeholder_inventory(html):
        return False
    if page_kind == "inventory" and _looks_like_empty_inventory_shell(html):
        return False
    if _has_structured_inventory_hint(html):
        return True
    if _html_looks_inventory_ready(html):
        return True
    lower = html.lower()
    if page_kind == "homepage":
        return len(html) >= 1800 and ("href=" in lower or "inventory" in lower)
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


def _extract_inventory_get_requests(html: str, base_url: str) -> list[tuple[str, dict[str, str]]]:
    requests: list[tuple[str, dict[str, str]]] = []
    for match in _DDC_WIDGET_PROPS_RE.finditer(html):
        body = match.group("body")
        api_match = _INVENTORY_URL_RE.search(body)
        if not api_match:
            continue
        raw = api_match.group("url")
        fixed = raw.replace("\\/", "/")
        abs_url = urljoin(base_url, fixed)

        params_match = re.search(r'"params"\s*:\s*"(?P<params>[^"]*)"', body)
        query: dict[str, str] = {}
        if params_match:
            raw_params = params_match.group("params").replace("\\u0026", "&")
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
        for api_url, query in api_gets[:2]:
            try:
                r = await client.get(api_url, params=query or None, headers=_browser_headers())
                if r.status_code == 403 and settings.zenrows_api_key:
                    full_url = api_url
                    if query:
                        full_url = f"{api_url}?{urlencode(query)}"
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
        for api_url, body in api_posts[:2]:
            try:
                r = await client.post(
                    api_url,
                    headers={**_browser_headers(), "Content-Type": "application/json"},
                    content=body,
                )
                r.raise_for_status()
            except Exception as e:
                logger.debug("Inventory API POST failed for %s: %s", api_url, e)
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
