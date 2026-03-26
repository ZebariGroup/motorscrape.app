"""Fetch dealership pages via direct HTTP first, then managed scrapers (ZenRows / ScrapingBee) when needed."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.services.dealer_platforms import zenrows_inventory_js_instructions_for_url
from app.services.scraper_strategies import zenrows_try_once

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
# Looser pairing for Toyota/Lexus-style Dealer.com SPAs: API URL + params may sit outside WidgetData blocks.
_DDC_WIDGET_INVENTORY_PAIR_RE = re.compile(
    r'"(?:inventoryApiURL|inventoryApiUrl)"\s*:\s*"(?P<url>[^"]+)"'
    r"[\s\S]{0,900}?"
    r'"(?:params|widgetParams|inventoryParams)"\s*:\s*"(?P<params>[^"]*)"',
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
) -> tuple[str, str] | None:
    if not settings.playwright_enabled:
        return None
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
        return None
    html = await _maybe_append_inventory_api_data(url, html, timeout)
    if _direct_html_sufficient(html, page_kind=page_kind):
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

    inventory_js_instructions = (
        zenrows_inventory_js_instructions_for_url(url, platform_id=platform_id)
        if page_kind == "inventory"
        else None
    )

    if prefer_render and page_kind == "inventory":
        # OneAudi Falcon (and similar): try local browser before paid JS render APIs.
        pw_early = await _playwright_pass(
            url,
            timeout,
            page_kind=page_kind,
            failures=failures,
            metric_bump=_m,
            js_instructions=inventory_js_instructions,
        )
        if pw_early is not None:
            return pw_early

        if settings.zenrows_api_key:
            for wait_ms in _retry_waits(settings.zenrows_wait_ms):
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
                    js_instructions=inventory_js_instructions,
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

    # 1) Direct first (cheapest)
    try:
        html = await _direct_get_with_express_www_fallback(url, timeout)
        html = await _maybe_append_inventory_api_data(url, html, timeout)
        if _direct_html_sufficient(html, page_kind=page_kind):
            _m("direct_ok")
            return html, "direct"
        if _should_prefer_zenrows_render(html, page_kind=page_kind):
            prefer_render = True
        logger.info("Direct fetch insufficient for %s (%s), escalating to managed scrapers", url, page_kind)
        _m("direct_insufficient")
    except Exception as e:
        err_str = e.__class__.__name__ if not str(e) else str(e)
        failures.append(f"direct: {err_str}")
        logger.debug("Direct fetch failed for %s: %s", url, err_str)
        _m("direct_failed")

    pw_result = await _playwright_pass(
        url,
        timeout,
        page_kind=page_kind,
        failures=failures,
        metric_bump=_m,
        js_instructions=inventory_js_instructions if page_kind == "inventory" else None,
    )
    if pw_result is not None:
        return pw_result

    # 2) ZenRows: static then rendered
    if settings.zenrows_api_key:
        if not prefer_render:
            html = await zenrows_try_once(
                url=url,
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

        for wait_ms in _retry_waits(settings.zenrows_wait_ms):
            js_instructions = zenrows_inventory_js_instructions_for_url(url, platform_id=platform_id)

            html = await zenrows_try_once(
                url=url,
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
            html = await _scrapingbee_fetch(url, timeout, render_js=False)
            html = await _maybe_append_inventory_api_data(url, html, timeout)
            if _direct_html_sufficient(html, page_kind=page_kind):
                _m("scrapingbee_static_ok")
                return html, "scrapingbee_static"
        except Exception as e:
            err_str = e.__class__.__name__ if not str(e) else str(e)
            logger.warning("ScrapingBee static fetch failed for %s: %s", url, err_str)
            failures.append(f"scrapingbee_static: {err_str}")

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
                logger.warning("ScrapingBee rendered fetch failed for %s: %s", url, err_str)
                failures.append(f"scrapingbee_rendered: {err_str}")

    # 4) If we had a direct body that was "insufficient", return it rather than failing completely
    try:
        html_fallback = await _direct_get_with_express_www_fallback(url, timeout)
        html_fallback = await _maybe_append_inventory_api_data(url, html_fallback, timeout)
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
        if "html_fallback" in locals() and html_fallback and len(html_fallback) > 10 and not _has_block_markers(html_fallback):
            if "site currently not available" not in html_fallback.lower() and "seite vorübergehend" not in html_fallback.lower() and "denied" not in html_fallback.lower():
                _m("direct_fallback_ok")
                return html_fallback, "direct_fallback"

    # If we had a thin HTML from the first pass that wasn't blocked, return it
    if "html" in locals() and html and len(html) > 10 and not _has_block_markers(html):
        if "site currently not available" not in html.lower() and "seite vorübergehend" not in html.lower() and "denied" not in html.lower():
            _m("direct_fallback_ok")
            return html, "direct_fallback"

    detail = " | ".join(failures)
    raise RuntimeError(f"All fetch methods failed for {url}: {detail}") from None


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
    if js_render and wait_ms > 0:
        params["wait"] = str(wait_ms)
    if js_render and js_instructions:
        params["js_instructions"] = js_instructions
    if settings.zenrows_premium_proxy or premium_proxy:
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
    return any(marker in lower for marker in _INVENTORY_HINTS) or _has_dom_inventory_result_tiles(html)


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


def _inventory_page_number_from_url(url: str) -> int:
    try:
        query = {k.lower(): v for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
    except Exception:
        return 1
    for key in ("page", "pt", "_p", "pn", "currentpage"):
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


def _rewrite_inventory_post_body_for_page(body: str, page_url: str) -> str:
    page_num = _inventory_page_number_from_url(page_url)
    if page_num <= 1:
        return body
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return body
    if not isinstance(payload, dict):
        return body
    inventory_params = payload.get("inventoryParameters")
    if not isinstance(inventory_params, dict):
        return body
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

    lower_to_key = {k.lower(): k for k in rewritten if k != "params"}
    page_key_name: str | None = None
    page_key_value: str | None = None
    for key, value in page_pairs:
        lower = key.lower()
        if lower in {"page", "pt", "_p", "pn", "currentpage"}:
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
        page_param_keys = ("page", "pt", "_p", "pn", "currentpage")
        page_size_keys = ("pagesize", "size", "limit", "hitsperpage", "perpage", "resultsperpage", "recordsperpage")
        offset_keys = ("start", "offset", "from", "recordstart")
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
    for match in _DDC_WIDGET_INVENTORY_PAIR_RE.finditer(html):
        raw = match.group("url").replace("\\/", "/")
        abs_url = urljoin(base_url, raw)
        raw_params = match.group("params").replace("\\u0026", "&")
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
