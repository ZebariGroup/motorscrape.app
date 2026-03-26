"""Scraper URL helper coverage for WAF-sensitive inventory hosts."""

from __future__ import annotations

from app.services.scraper import (
    _extract_inventory_api_urls,
    _extract_inventory_get_requests,
    _host_is_express_retail,
    _rewrite_inventory_get_query_for_page,
    _rewrite_inventory_post_body_for_page,
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


def test_rewrite_inventory_post_body_for_page_uses_start_offset() -> None:
    body = (
        '{"inventoryParameters":{"page":"2"},'
        '"preferences":{"pageSize":"18"},'
        '"pageAlias":"INVENTORY_LISTING_DEFAULT_AUTO_NEW"}'
    )
    rewritten = _rewrite_inventory_post_body_for_page(
        body,
        "https://dealer.example/new-inventory/index.htm?page=2",
    )
    assert '"start":"18"' in rewritten
    assert '"page":"2"' not in rewritten


def test_rewrite_inventory_post_body_injects_make_from_page_url() -> None:
    body = (
        '{"inventoryParameters":{"condition":"New"},'
        '"preferences":{"pageSize":"18"},'
        '"pageAlias":"INVENTORY_LISTING_DEFAULT_AUTO_NEW"}'
    )
    rewritten = _rewrite_inventory_post_body_for_page(
        body,
        "https://www.suburbanbuickgmcoftroy.com/new-inventory/index.htm?make=Buick",
    )
    import json
    payload = json.loads(rewritten)
    assert payload["inventoryParameters"]["make"] == "Buick"
    assert payload["inventoryParameters"]["condition"] == "New"


def test_rewrite_inventory_post_body_injects_make_and_model_from_page_url() -> None:
    body = (
        '{"inventoryParameters":{"condition":"New"},'
        '"preferences":{"pageSize":"18"},'
        '"pageAlias":"INVENTORY_LISTING_DEFAULT_AUTO_NEW"}'
    )
    rewritten = _rewrite_inventory_post_body_for_page(
        body,
        "https://dealer.example/new-inventory/index.htm?make=Chrysler&model=Pacifica",
    )
    import json
    payload = json.loads(rewritten)
    assert payload["inventoryParameters"]["make"] == "Chrysler"
    assert payload["inventoryParameters"]["model"] == "Pacifica"


def test_rewrite_inventory_get_query_for_page_merges_filter_scope() -> None:
    rewritten = _rewrite_inventory_get_query_for_page(
        {"make": "Jeep", "sortBy": "price", "params": "make=Jeep&sortBy=price"},
        "https://dealer.example/new-inventory/index.htm?make=Chrysler",
    )
    assert rewritten["make"] == "Chrysler"
    assert "make=Chrysler" in rewritten["params"]


def test_rewrite_inventory_get_query_for_page_rewrites_page_and_start() -> None:
    rewritten = _rewrite_inventory_get_query_for_page(
        {"pageSize": "9", "start": "0", "params": "pageSize=9&start=0"},
        "https://dealer.example/new-inventory/index.htm?make=Buick&page=2",
    )
    assert rewritten["pageSize"] == "9"
    assert rewritten["start"] == "9"
    assert rewritten["make"] == "Buick"
    assert "start=9" in rewritten["params"]


def test_extract_inventory_api_urls_normalizes_single_quoted_escaped_urls() -> None:
    html = """
    <script>
      {"inventoryApiUrl":"https:\\/\\/www.suburbanvolvocars.com\\/api\\/widget\\/ws-inv-data\\/getInventory","make":"Suburban"}
    </script>
    """
    urls = _extract_inventory_api_urls(html, "https://www.suburbanvolvocars.com/new-inventory/index.htm")
    assert urls == ["https://www.suburbanvolvocars.com/api/widget/ws-inv-data/getInventory"]


def test_extract_inventory_get_requests_handles_single_quote_and_param_order() -> None:
    html = """
    <script>
      DDC.WidgetData[0].props = {"params":"page=1&amp;pageSize=9&amp;start=0","inventoryApiUrl":'https://api.example.com/inventory'}
    </script>
    """
    requests = _extract_inventory_get_requests(html, "https://dealer.example/new-inventory/index.htm")
    assert len(requests) == 1
    api_url, query = requests[0]
    assert api_url == "https://api.example.com/inventory"
    assert query["page"] == "1"
    assert query["pageSize"] == "9"
    assert query["start"] == "0"
    assert query["params"] == "page=1&pageSize=9&start=0"


def test_rewrite_inventory_get_query_for_page_from_params_only() -> None:
    rewritten = _rewrite_inventory_get_query_for_page(
        {"params": "page=1&amp;pageSize=9&amp;start=0"},
        "https://dealer.example/new-inventory/index.htm?page=2",
    )
    assert rewritten["page"] == "2"
    assert rewritten["start"] == "9"
    assert "start=9" in rewritten["params"]
