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


def _zenrows_response_detail(response: httpx.Response) -> str:
    detail = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        parts: list[str] = []
        for key in ("title", "detail", "code", "message", "error"):
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text and text not in parts:
                parts.append(text)
        detail = " | ".join(parts)
    if not detail:
        detail = response.text.strip()
    detail = " ".join(detail.split())
    if len(detail) > 240:
        return detail[:237] + "..."
    return detail


def _zenrows_error_string(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        reason = error.response.reason_phrase
        detail = _zenrows_response_detail(error.response)
        return f"{status} {reason}: {detail}" if detail else f"{status} {reason}"
    return error.__class__.__name__ if not str(error) else str(error)


def _should_retry_zenrows_error_with_premium_proxy(error: Exception) -> bool:
    if settings.zenrows_premium_proxy:
        return False
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {403, 404, 422}
    lowered = _zenrows_error_string(error).lower()
    return "server disconnected" in lowered or "remoteprotocolerror" in lowered


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
        failures.append(f"{failure_label}: insufficient")
        if page_kind != "inventory":
            needs_premium = _should_retry_zenrows_with_premium_proxy(html, page_kind=page_kind)
    except Exception as e:
        err_str = _zenrows_error_string(e)
        sanitized = err_str.replace(settings.zenrows_api_key, "***")
        logger.warning("ZenRows %s failed for %s: %s", failure_label, url, sanitized)
        failures.append(f"{failure_label}: {sanitized}")
        if _should_retry_zenrows_error_with_premium_proxy(e):
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
        failures.append(f"{failure_label}_premium: insufficient")
    except Exception as e:
        err_str = _zenrows_error_string(e)
        sanitized = err_str.replace(settings.zenrows_api_key, "***")
        logger.warning("ZenRows %s with premium proxy failed for %s: %s", failure_label, url, sanitized)
        failures.append(f"{failure_label}_premium: {sanitized}")
    return None
