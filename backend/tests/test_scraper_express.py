"""Scraper URL helper coverage for WAF-sensitive inventory hosts."""

from __future__ import annotations

from app.services.scraper import (
    _host_is_express_retail,
    _should_prefer_zenrows_render,
    _should_retry_zenrows_with_premium_proxy,
    _www_swap_express_url,
)


def test_host_is_express_retail() -> None:
    assert _host_is_express_retail("https://express.suburbanvolvocars.com/inventory/")
    assert not _host_is_express_retail("https://www.suburbanvolvocars.com/")
    assert not _host_is_express_retail("https://inventory.dealer.com/")


def test_www_swap_express_url() -> None:
    swapped = _www_swap_express_url("https://express.suburbanvolvocars.com/inventory/?q=1")
    assert swapped is not None
    assert swapped.startswith("https://www.suburbanvolvocars.com/inventory/")
    assert "q=1" in swapped


def test_should_prefer_zenrows_render_for_inventory_shells() -> None:
    html = '<html><body><div id="hits"></div><div class="loader-hits">Loading...</div></body></html>'
    assert _should_prefer_zenrows_render(html, page_kind="inventory")
    assert not _should_prefer_zenrows_render(html, page_kind="homepage")


def test_should_retry_zenrows_with_premium_proxy_for_block_pages() -> None:
    html = "<html><body>Client Challenge</body></html>"
    assert _should_retry_zenrows_with_premium_proxy(html, page_kind="homepage")


def test_should_retry_zenrows_with_premium_proxy_for_inventory_placeholders() -> None:
    html = '<html><body><div class="vehicle-card vehicle-card--mod skeleton"></div></body></html>'
    assert _should_retry_zenrows_with_premium_proxy(html, page_kind="inventory")
