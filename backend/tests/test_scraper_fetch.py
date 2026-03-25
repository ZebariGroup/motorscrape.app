"""Integration-style tests for fetch_page_html with mocked HTTP."""

from __future__ import annotations

import pytest
import respx
from app.services.scraper import fetch_page_html
from httpx import Response


def _inventory_html() -> str:
    return """<!DOCTYPE html><html><body>
    <div class="vehicle-card" data-vin="1HGCV1F30MA000001" data-make="Honda" data-model="Accord">
      <span class="price">$28,000</span>
    </div>
    <script type="application/json">{"inventory":[{"make":"Honda","model":"Accord","vin":"1HGCV1F30MA000001"}]}</script>
    </body></html>"""


def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    s = Settings()
    monkeypatch.setattr("app.services.scraper.settings", s)
    monkeypatch.setattr("app.services.playwright_fetch.settings", s)


@pytest.fixture
def clear_scraper_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "")
    monkeypatch.setenv("SCRAPINGBEE_API_KEY", "")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "false")
    _fresh_settings(monkeypatch)


@pytest.fixture
def zenrows_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "false")
    _fresh_settings(monkeypatch)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_direct_ok(clear_scraper_keys: None) -> None:
    respx.get("https://dealer.example/inventory.htm").mock(return_value=Response(200, text=_inventory_html()))
    html, method = await fetch_page_html("https://dealer.example/inventory.htm", page_kind="inventory")
    assert method == "direct"
    assert "vehicle-card" in html


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_direct_insufficient_then_fallback(clear_scraper_keys: None) -> None:
    thin = "<html><body><p>ok</p></body></html>"
    respx.get("https://dealer.example/inv.htm").mock(return_value=Response(200, text=thin))
    html, method = await fetch_page_html("https://dealer.example/inv.htm", page_kind="inventory")
    assert method == "direct_fallback"
    assert thin in html or html == thin


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_express_403_www_retry(clear_scraper_keys: None) -> None:
    url_express = "https://express.dealer.example/new-inventory/index.htm"
    url_www = "https://www.dealer.example/new-inventory/index.htm"

    def route(req: object) -> Response:
        u = str(getattr(req, "url", ""))
        if "express." in u:
            return Response(403, text="blocked")
        return Response(200, text=_inventory_html())

    respx.get(url_express).mock(return_value=Response(403, text="blocked"))
    respx.get(url_www).mock(return_value=Response(200, text=_inventory_html()))

    html, method = await fetch_page_html(url_express, page_kind="inventory")
    assert method == "direct"
    assert "vehicle-card" in html


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_zenrows_static_after_direct_fails(zenrows_key: None) -> None:
    respx.get("https://blocked.example/").mock(return_value=Response(403, text="denied"))
    respx.get("https://api.zenrows.com/v1/").mock(
        return_value=Response(200, text="<html><body>" + _inventory_html() + "</body></html>")
    )

    html, method = await fetch_page_html("https://blocked.example/", page_kind="homepage")
    assert method == "zenrows_static"
    assert "vehicle-card" in html or "inventory" in html


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_playwright_before_zenrows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    _fresh_settings(monkeypatch)
    calls: list[str] = []

    async def fake_pw(url: str) -> str:
        calls.append("pw")
        return _inventory_html()

    monkeypatch.setattr(
        "app.services.playwright_fetch.fetch_html_via_playwright",
        fake_pw,
    )

    respx.get("https://blocked.example/inv").mock(return_value=Response(403, text="denied"))

    def zenrows_route(request: object) -> Response:
        calls.append("zenrows")
        return Response(200, text=_inventory_html())

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html("https://blocked.example/inv", page_kind="inventory")
    assert method == "playwright"
    assert "vehicle-card" in html
    assert calls == ["pw"], "ZenRows should not run when Playwright succeeds"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_all_fail_raises(zenrows_key: None) -> None:
    respx.get("https://fail.example/").mock(return_value=Response(403, text="denied"))
    respx.get("https://api.zenrows.com/v1/").mock(return_value=Response(422, text="no"))

    with pytest.raises(RuntimeError, match="All fetch methods failed"):
        await fetch_page_html("https://fail.example/", page_kind="homepage")
