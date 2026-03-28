"""Integration-style tests for fetch_page_html with mocked HTTP."""

from __future__ import annotations

import httpx
import pytest
import respx
from app.services.scraper import _zenrows_fetch, fetch_page_html
from httpx import Response


def _inventory_html() -> str:
    return """<!DOCTYPE html><html><body>
    <div class="vehicle-card" data-vin="1HGCV1F30MA000001" data-make="Honda" data-model="Accord">
      <span class="price">$28,000</span>
    </div>
    <script type="application/json">{"inventory":[{"make":"Honda","model":"Accord","vin":"1HGCV1F30MA000001"}]}</script>
    </body></html>"""


def _generic_ld_json_html() -> str:
    return """<!DOCTYPE html><html><head>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"AutoDealer","name":"Dealer Example"}</script>
    </head><body><h1>Dealer Homepage Shell</h1></body></html>"""


def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    s = Settings()
    monkeypatch.setattr("app.services.scraper.settings", s)
    monkeypatch.setattr("app.services.scraper_strategies.settings", s)
    monkeypatch.setattr("app.services.playwright_fetch.settings", s)
    monkeypatch.setattr("app.services.scraper._zenrows_semaphore", None)
    monkeypatch.setattr("app.services.scraper._scrapingbee_semaphore", None)
    monkeypatch.setattr("app.services.scraper._managed_scraper_semaphore", None)
    monkeypatch.setattr("app.services.scraper._zenrows_cooldown_until_monotonic", 0.0)


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
async def test_fetch_page_html_generic_ld_json_not_treated_as_inventory_ready(clear_scraper_keys: None) -> None:
    shell = _generic_ld_json_html()
    respx.get("https://dealer.example/new-inventory/index.htm").mock(return_value=Response(200, text=shell))
    html, method = await fetch_page_html("https://dealer.example/new-inventory/index.htm", page_kind="inventory")
    assert method == "direct_fallback"
    assert html == shell


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
async def test_fetch_page_html_direct_403_retries_with_fallback_headers(clear_scraper_keys: None) -> None:
    url = "https://www.bassproboatingcenters.example/brands/tracker-boats.html"
    seen_user_agents: list[str] = []

    def route(request: httpx.Request) -> Response:
        seen_user_agents.append(request.headers.get("User-Agent", ""))
        if request.headers.get("User-Agent") == "Mozilla/5.0":
            return Response(200, text=_inventory_html())
        return Response(403, text="denied")

    respx.get(url).mock(side_effect=route)

    html, method = await fetch_page_html(url, page_kind="homepage")
    assert method == "direct"
    assert "vehicle-card" in html
    assert seen_user_agents[0] != "Mozilla/5.0"
    assert seen_user_agents[-1] == "Mozilla/5.0"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_inventory_strips_dfr_query_on_direct_retry(clear_scraper_keys: None) -> None:
    noisy = (
        "https://dealer.example/new-vehicles/"
        "?_dFR%5Bfueltype%5D%5B0%5D=Electric&_dFR%5Btype%5D%5B0%5D=New&page=1"
    )
    sanitized = "https://dealer.example/new-vehicles/?page=1"
    respx.get(noisy).mock(return_value=Response(403, text="denied"))
    respx.get(sanitized).mock(return_value=Response(200, text=_inventory_html()))

    html, method = await fetch_page_html(noisy, page_kind="inventory")
    assert method == "direct"
    assert "vehicle-card" in html


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_inventory_reports_sanitized_url_and_cloudflare_hint_on_full_block(
    clear_scraper_keys: None,
) -> None:
    noisy = (
        "https://dealer.example/new-vehicles/"
        "?_dFR%5Bfueltype%5D%5B0%5D=Electric&_dFR%5Btype%5D%5B0%5D=New&page=1"
    )
    sanitized = "https://dealer.example/new-vehicles/?page=1"
    cf_html = "<html><head><title>Attention Required! | Cloudflare</title></head><body>cf-ray</body></html>"
    respx.get(noisy).mock(return_value=Response(403, text=cf_html, headers={"cf-ray": "test"}))
    respx.get(sanitized).mock(return_value=Response(403, text=cf_html, headers={"cf-ray": "test"}))

    with pytest.raises(RuntimeError) as exc:
        await fetch_page_html(noisy, page_kind="inventory")

    msg = str(exc.value)
    assert sanitized in msg
    assert "cloudflare_blocked_no_fallback" in msg


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
async def test_fetch_page_html_homepage_zenrows_resp001_escalates_to_rendered(
    zenrows_key: None,
) -> None:
    respx.get("https://blocked.example/").mock(return_value=Response(403, text="denied"))
    calls: list[str] = []

    def zenrows_route(request: httpx.Request) -> Response:
        js_render = request.url.params.get("js_render") == "true"
        calls.append("rendered" if js_render else "static")
        if not js_render:
            return Response(
                422,
                json={
                    "code": "RESP001",
                    "detail": "Could not get content. try enabling javascript rendering for a higher success rate",
                },
            )
        body = "<html><body><a href='/inventory'>Inventory</a>" + ("x" * 2200) + "</body></html>"
        return Response(200, text=body)

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html("https://blocked.example/", page_kind="homepage")
    assert method == "zenrows_rendered"
    assert "Inventory" in html
    assert calls.count("rendered") == 1
    assert calls.count("static") >= 1
    assert calls[-1] == "rendered"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_homepage_skips_managed_js_render_by_default(zenrows_key: None) -> None:
    respx.get("https://blocked.example/").mock(return_value=Response(403, text="denied"))
    seen_js_render: list[str] = []

    def zenrows_route(request: httpx.Request) -> Response:
        seen_js_render.append(request.url.params.get("js_render", ""))
        body = "<html><body><a href='/inventory'>Inventory</a>" + ("x" * 2200) + "</body></html>"
        return Response(200, text=body)

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html("https://blocked.example/", page_kind="homepage")
    assert method == "zenrows_static"
    assert "Inventory" in html
    assert seen_js_render
    assert all(flag == "false" for flag in seen_js_render)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_oneaudi_uses_compact_zenrows_instructions(
    zenrows_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZENROWS_PREMIUM_PROXY", "false")
    _fresh_settings(monkeypatch)
    url = "https://www.audibirminghammi.com/en/inventory/new/"
    respx.get(url).mock(return_value=Response(403, text="denied"))
    captured: dict[str, str | None] = {}

    def zenrows_route(request: httpx.Request) -> Response:
        captured["js_instructions"] = request.url.params.get("js_instructions")
        captured["wait"] = request.url.params.get("wait")
        return Response(200, text="<html><body>" + _inventory_html() + "</body></html>")

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html(
        url,
        page_kind="inventory",
        prefer_render=True,
        platform_id="oneaudi_falcon",
    )

    assert method == "zenrows_rendered"
    assert "vehicle-card" in html
    instructions = captured["js_instructions"]
    assert instructions is not None
    assert len(instructions) < 2500
    assert instructions.count("window.__zrClickMore=()=>") == 1
    assert captured.get("wait") in (None, "")


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_does_not_premium_retry_on_zenrows_concurrency_limit(
    zenrows_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZENROWS_PREMIUM_PROXY", "false")
    _fresh_settings(monkeypatch)
    respx.get("https://blocked.example/").mock(return_value=Response(403, text="denied"))
    calls: list[str] = []

    def zenrows_route(request: httpx.Request) -> Response:
        premium = request.url.params.get("premium_proxy") == "true"
        calls.append("premium" if premium else "standard")
        return Response(
            429,
            json={
                "code": "AUTH006",
                "detail": "Too many concurrent requests",
            },
        )

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    with pytest.raises(RuntimeError, match="All fetch methods failed"):
        await fetch_page_html("https://blocked.example/", page_kind="homepage")

    assert calls
    assert all(call == "standard" for call in calls)


@respx.mock
@pytest.mark.asyncio
async def test_zenrows_fetch_waits_for_active_cooldown(
    zenrows_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_settings(monkeypatch)
    monkeypatch.setattr("app.services.scraper._zenrows_cooldown_until_monotonic", 1.0)
    monotonic_values = [0.0, 1.2, 1.2]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_monotonic() -> float:
        if monotonic_values:
            return monotonic_values.pop(0)
        return 1.2

    monkeypatch.setattr("app.services.scraper.time.monotonic", fake_monotonic)
    monkeypatch.setattr("app.services.scraper.asyncio.sleep", fake_sleep)

    respx.get("https://api.zenrows.com/v1/").mock(
        return_value=Response(200, text="<html><body>" + _inventory_html() + "</body></html>")
    )

    html = await _zenrows_fetch(
        "https://blocked.example/",
        httpx.Timeout(5.0),
        js_render=False,
    )

    assert "vehicle-card" in html
    assert sleeps == [1.0]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_zenrows_static_retries_with_premium_on_disconnect(
    zenrows_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZENROWS_PREMIUM_PROXY", "false")
    _fresh_settings(monkeypatch)
    respx.get("https://blocked.example/").mock(return_value=Response(403, text="denied"))
    calls: list[str] = []

    def zenrows_route(request: httpx.Request) -> Response:
        premium = request.url.params.get("premium_proxy") == "true"
        calls.append("premium" if premium else "standard")
        if not premium:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return Response(200, text="<html><body>" + _inventory_html() + "</body></html>")

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html("https://blocked.example/", page_kind="homepage")

    assert method == "zenrows_static"
    assert "vehicle-card" in html or "inventory" in html
    assert calls.count("premium") == 1
    assert calls.count("standard") >= 1


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_playwright_before_zenrows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    _fresh_settings(monkeypatch)
    calls: list[str] = []

    async def fake_pw(url: str, js_instructions: str | None = None) -> str:
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
async def test_fetch_page_html_prefer_render_still_uses_direct_when_inventory_is_ready(
    zenrows_key: None,
) -> None:
    respx.get("https://dealer.example/searchnew.aspx?Make=Chevrolet").mock(
        return_value=Response(200, text=_inventory_html())
    )
    respx.get("https://api.zenrows.com/v1/").mock(return_value=Response(500, text="unused"))

    html, method = await fetch_page_html(
        "https://dealer.example/searchnew.aspx?Make=Chevrolet",
        page_kind="inventory",
        prefer_render=True,
        platform_id="dealer_on",
    )

    assert method == "direct"
    assert "vehicle-card" in html


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_passes_platform_playwright_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    _fresh_settings(monkeypatch)
    captured: dict[str, str | None] = {}

    async def fake_pw(url: str, js_instructions: str | None = None) -> str:
        captured["url"] = url
        captured["js_instructions"] = js_instructions
        return _inventory_html()

    monkeypatch.setattr(
        "app.services.playwright_fetch.fetch_html_via_playwright",
        fake_pw,
    )

    respx.get("https://dealer.example/searchnew.aspx").mock(return_value=Response(403, text="denied"))
    respx.get("https://api.zenrows.com/v1/").mock(return_value=Response(500, text="unused"))

    html, method = await fetch_page_html(
        "https://dealer.example/searchnew.aspx",
        page_kind="inventory",
        prefer_render=True,
        platform_id="dealer_on",
    )

    assert method == "playwright"
    assert "vehicle-card" in html
    assert captured["url"] == "https://dealer.example/searchnew.aspx"
    assert captured["js_instructions"] is not None
    assert "wait_for_selector" in captured["js_instructions"]
    assert "/api/vhcliaa/" in captured["js_instructions"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_passes_dealer_inspire_playwright_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    _fresh_settings(monkeypatch)
    captured: dict[str, str | None] = {}

    async def fake_pw(url: str, js_instructions: str | None = None) -> str:
        captured["url"] = url
        captured["js_instructions"] = js_instructions
        return _inventory_html()

    monkeypatch.setattr(
        "app.services.playwright_fetch.fetch_html_via_playwright",
        fake_pw,
    )

    respx.get("https://dealer.example/new-vehicles/").mock(return_value=Response(403, text="denied"))
    respx.get("https://api.zenrows.com/v1/").mock(return_value=Response(500, text="unused"))

    html, method = await fetch_page_html(
        "https://dealer.example/new-vehicles/",
        page_kind="inventory",
        prefer_render=True,
        platform_id="dealer_inspire",
    )

    assert method == "playwright"
    assert "vehicle-card" in html
    assert captured["url"] == "https://dealer.example/new-vehicles/"
    assert captured["js_instructions"] is not None
    assert "/api/v1/facets/" in captured["js_instructions"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_playwright_insufficient_then_zenrows_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    _fresh_settings(monkeypatch)
    calls: list[str] = []

    async def fake_pw(url: str, js_instructions: str | None = None) -> str:
        calls.append("pw")
        return "<html><body><div>loading inventory...</div></body></html>"

    monkeypatch.setattr(
        "app.services.playwright_fetch.fetch_html_via_playwright",
        fake_pw,
    )

    respx.get("https://blocked.example/inv").mock(return_value=Response(403, text="denied"))

    def zenrows_route(request: httpx.Request) -> Response:
        calls.append("zenrows")
        assert request.url.params.get("js_render") == "true"
        return Response(200, text=_inventory_html())

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=zenrows_route)

    html, method = await fetch_page_html(
        "https://blocked.example/inv",
        page_kind="inventory",
        prefer_render=True,
        platform_id="dealer_on",
    )

    assert method == "zenrows_rendered"
    assert "vehicle-card" in html
    assert calls == ["pw", "zenrows"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_page_html_all_fail_raises(zenrows_key: None) -> None:
    respx.get("https://fail.example/").mock(return_value=Response(403, text="denied"))
    respx.get("https://api.zenrows.com/v1/").mock(return_value=Response(422, text="no"))

    with pytest.raises(RuntimeError, match="All fetch methods failed"):
        await fetch_page_html("https://fail.example/", page_kind="homepage")


@respx.mock
@pytest.mark.asyncio
async def test_zenrows_concurrency_gate_limits_parallel_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setenv("ZENROWS_API_KEY", "zr-test-key")
    monkeypatch.setenv("ZENROWS_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "false")
    _fresh_settings(monkeypatch)

    peak = 0
    inflight = 0
    lock = asyncio.Lock()

    async def slow_zenrows(request: httpx.Request) -> Response:
        nonlocal peak, inflight
        async with lock:
            inflight += 1
            peak = max(peak, inflight)
        await asyncio.sleep(0.05)
        async with lock:
            inflight -= 1
        return Response(200, text="<html><body>" + _inventory_html() + "</body></html>")

    respx.get("https://api.zenrows.com/v1/").mock(side_effect=slow_zenrows)
    for i in range(4):
        respx.get(f"https://dealer{i}.example/").mock(return_value=Response(403, text="denied"))

    results = await asyncio.gather(
        *[fetch_page_html(f"https://dealer{i}.example/", page_kind="homepage") for i in range(4)],
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) >= 1
    assert peak <= 2, f"Peak concurrency {peak} exceeded limit of 2"
