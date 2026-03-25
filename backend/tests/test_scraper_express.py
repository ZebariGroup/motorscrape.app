"""Express retail subdomain URL helpers (Cloudflare / WAF-sensitive inventory hosts)."""

from __future__ import annotations

from app.services.scraper import _host_is_express_retail, _www_swap_express_url


def test_host_is_express_retail() -> None:
    assert _host_is_express_retail("https://express.suburbanvolvocars.com/inventory/")
    assert not _host_is_express_retail("https://www.suburbanvolvocars.com/")
    assert not _host_is_express_retail("https://inventory.dealer.com/")


def test_www_swap_express_url() -> None:
    swapped = _www_swap_express_url("https://express.suburbanvolvocars.com/inventory/?q=1")
    assert swapped is not None
    assert swapped.startswith("https://www.suburbanvolvocars.com/inventory/")
    assert "q=1" in swapped
