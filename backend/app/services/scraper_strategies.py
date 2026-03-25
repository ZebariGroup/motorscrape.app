"""
Pluggable fetch strategies for dealership HTML retrieval.

ZenRows / ScrapingBee steps use lazy imports of `scraper` helpers to avoid import cycles.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PageKind = Literal["homepage", "inventory"]


@runtime_checkable
class HtmlFetchStrategy(Protocol):
    """One ordered step in the scrape pipeline; returns (html, method) or None."""

    async def run(self) -> tuple[str, str] | None:
        """Success → (html, method_label); skip → None."""


async def zenrows_try_once(
    *,
    url: str,
    timeout: httpx.Timeout,
    page_kind: PageKind,
    failures: list[str],
    metric_bump: Callable[[str], None],
    js_render: bool,
    wait_ms: int = 0,
    metric_prefix: str,
    failure_label: str,
    js_instructions: str | None = None,
) -> str | None:
    """Single ZenRows attempt with optional premium retry; mirrors previous nested `_try_zenrows`."""
    from app.services.scraper import (  # noqa: PLC0415 — lazy import breaks cycle with zenrows helpers
        _direct_html_sufficient,
        _maybe_append_inventory_api_data,
        _should_retry_zenrows_with_premium_proxy,
        _zenrows_fetch,
    )

    html = None
    needs_premium = False
    try:
        html = await _zenrows_fetch(
            url,
            timeout,
            js_render=js_render,
            wait_ms=wait_ms,
            js_instructions=js_instructions,
        )
        html = await _maybe_append_inventory_api_data(url, html, timeout)
        if _direct_html_sufficient(html, page_kind=page_kind):
            metric_bump(f"{metric_prefix}_ok")
            return html
        metric_bump(f"{metric_prefix}_insufficient")
        needs_premium = _should_retry_zenrows_with_premium_proxy(html, page_kind=page_kind)
    except Exception as e:
        err_str = e.__class__.__name__ if not str(e) else str(e)
        sanitized = err_str.replace(settings.zenrows_api_key, "***")
        logger.warning("ZenRows %s failed for %s: %s", failure_label, url, sanitized)
        failures.append(f"{failure_label}: {sanitized}")
        if "403" in err_str or "404" in err_str or "422" in err_str or "429" in err_str:
            needs_premium = True

    if not needs_premium or settings.zenrows_premium_proxy:
        return None

    try:
        premium_html = await _zenrows_fetch(
            url,
            timeout,
            js_render=js_render,
            wait_ms=wait_ms,
            premium_proxy=True,
            js_instructions=js_instructions,
        )
        premium_html = await _maybe_append_inventory_api_data(url, premium_html, timeout)
        if _direct_html_sufficient(premium_html, page_kind=page_kind):
            metric_bump(f"{metric_prefix}_premium_ok")
            return premium_html
        metric_bump(f"{metric_prefix}_premium_insufficient")
    except Exception as e:
        err_str = e.__class__.__name__ if not str(e) else str(e)
        sanitized = err_str.replace(settings.zenrows_api_key, "***")
        logger.warning("ZenRows %s with premium proxy failed for %s: %s", failure_label, url, sanitized)
        failures.append(f"{failure_label}_premium: {sanitized}")
    return None
