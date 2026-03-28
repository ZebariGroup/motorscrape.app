"""Unit tests for Google Places client (mocked HTTP)."""

from __future__ import annotations

import json

import pytest
import respx
from app.schemas import DealershipFound
from app.services import places
from httpx import Response


@pytest.fixture
def places_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-google-key"
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", key)
    # Reload settings so tests pick up env
    from app.config import Settings

    monkeypatch.setattr("app.services.places.settings", Settings())
    return key


@pytest.mark.asyncio
async def test_find_car_dealerships_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid constructing Settings() — repo `.env` may still supply a key via env_file.
    from types import SimpleNamespace

    monkeypatch.setattr("app.services.places.settings", SimpleNamespace(google_places_api_key=""))
    with pytest.raises(ValueError, match="Google Places API key"):
        await places.find_car_dealerships("Detroit MI")


@respx.mock
@pytest.mark.asyncio
async def test_search_places_text_http_error(places_api_key: str) -> None:
    import httpx

    respx.post(places.SEARCH_TEXT_URL).mock(
        return_value=Response(403, json={"error": {"message": "PERMISSION_DENIED", "status": "PERMISSION_DENIED"}})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="PERMISSION_DENIED|HTTP 403"):
            await places._search_places_text(
                client,
                places_api_key,
                text_query="car dealership near x",
                limit=5,
            )


def test_api_error_message_dict() -> None:
    msg = places._api_error_message({"error": {"message": "Billing not enabled"}})
    assert "Billing" in msg


def test_api_error_message_fallback() -> None:
    msg = places._api_error_message("plain")
    assert "plain" in msg


def test_display_name() -> None:
    assert places._display_name({"displayName": {"text": "Dealer A"}}) == "Dealer A"
    assert places._display_name({}) == "Unknown"


def test_name_matches_make() -> None:
    assert places._name_matches_make("Ford of Detroit", "Ford")
    assert places._name_matches_make("McDonald Ford", "Ford")
    assert not places._name_matches_make("Toyota Town", "Ford")
    assert places._name_matches_make("Any", "")


def test_false_positive_boat_retailer_filter_excludes_supply_and_service() -> None:
    assert places._looks_like_false_positive_category_match(
        "Michigan Marine Gear",
        "https://www.michiganmarinegear.com/",
        vehicle_category="boat",
    )
    assert places._looks_like_false_positive_category_match(
        "Mike's Marine Supply",
        "https://www.mikesmarine.com/",
        vehicle_category="boat",
    )
    assert not places._looks_like_false_positive_category_match(
        "Temptation Yacht Sales",
        "https://www.temptationyachtsales.com/",
        vehicle_category="boat",
    )
    assert not places._looks_like_false_positive_category_match(
        "Grand Pointe Marina",
        "https://www.grandpointemarina.com/",
        vehicle_category="boat",
    )


def test_normalize_dealer_website_url_strips_tracking() -> None:
    u = places._normalize_dealer_website_url("https://dealer.com/?gclid=1&utm_source=email")
    assert "gclid" not in u
    assert "utm_source" not in u
    assert "dealer.com" in u


def test_normalize_dealer_website_url_rejects_javascript_void() -> None:
    assert places._normalize_dealer_website_url("javascript:void(0)") == ""
    assert places._normalize_dealer_website_url("javascript:void(0);") == ""
    assert places._normalize_dealer_website_url("tel:+13135551234") == ""
    assert places._normalize_dealer_website_url("mailto:info@dealer.com") == ""
    assert places._normalize_dealer_website_url("https://dealer.com/") != ""


@respx.mock
@pytest.mark.asyncio
async def test_place_details_website_ok(places_api_key: str) -> None:
    import httpx

    respx.get("https://places.googleapis.com/v1/places/ChIJ123").mock(
        return_value=Response(200, json={"websiteUri": "https://example.com/?fbclid=abc"})
    )
    async with httpx.AsyncClient() as client:
        uri = await places._place_details_website(client, "places/ChIJ123", places_api_key)
    assert uri == "https://example.com/"


@respx.mock
@pytest.mark.asyncio
async def test_place_details_website_non_200(places_api_key: str) -> None:
    import httpx

    respx.get("https://places.googleapis.com/v1/places/ChIJbad").mock(return_value=Response(404))
    async with httpx.AsyncClient() as client:
        uri = await places._place_details_website(client, "places/ChIJbad", places_api_key)
    assert uri is None


@respx.mock
@pytest.mark.asyncio
async def test_find_car_dealerships_happy_path(places_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Location bias + text search return places with website; no details call needed."""
    loc_response = {
        "places": [
            {
                "location": {"latitude": 42.33, "longitude": -83.04},
            }
        ]
    }
    search_response = {
        "places": [
            {
                "id": "ChIJabc",
                "name": "places/ChIJabc",
                "displayName": {"text": "Ford of Testville"},
                "formattedAddress": "123 Main",
                "websiteUri": "https://ford-test.example/",
            }
        ]
    }

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        # Bias request has no car_dealer filter
        if "includedType" not in body:
            return Response(200, json=loc_response)
        return Response(200, json=search_response)

    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_car_dealerships("Detroit MI", make="Ford", model="", limit=5, radius_miles=25)
    assert len(out) >= 1
    assert isinstance(out[0], DealershipFound)
    assert out[0].website.startswith("https://ford-test.example")


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_boats_uses_untyped_query(places_api_key: str) -> None:
    """Boat discovery should rely on text query matching instead of car_dealer filtering."""
    loc_response = {"places": [{"location": {"latitude": 42.33, "longitude": -83.04}}]}
    search_response = {
        "places": [
            {
                "id": "ChIJboat",
                "name": "places/ChIJboat",
                "displayName": {"text": "Great Lakes Marine"},
                "formattedAddress": "456 Harbor",
                "websiteUri": "https://greatlakesmarine.example/",
            }
        ]
    }
    seen_queries: list[dict] = []

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        if body.get("textQuery") == "Traverse City MI":
            return Response(200, json=loc_response)
        seen_queries.append(body)
        return Response(200, json=search_response)

    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Traverse City MI",
        vehicle_category="boat",
        make="Sea Ray",
        limit=5,
        radius_miles=25,
    )
    assert len(out) == 1
    assert out[0].website == "https://greatlakesmarine.example/"
    assert seen_queries
    assert all("includedType" not in body for body in seen_queries)
    assert any("boat dealer" in str(body.get("textQuery", "")).lower() for body in seen_queries)


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_motorcycles_prefers_category_context(places_api_key: str) -> None:
    loc_response = {"places": [{"location": {"latitude": 42.33, "longitude": -83.04}}]}
    search_response = {
        "places": [
            {
                "id": "ChIJauto",
                "name": "places/ChIJauto",
                "displayName": {"text": "Honda of Testville"},
                "formattedAddress": "123 Main",
                "websiteUri": "https://hondaoftestville.example/",
            },
            {
                "id": "ChIJmoto",
                "name": "places/ChIJmoto",
                "displayName": {"text": "Honda Powersports of Testville"},
                "formattedAddress": "456 Main",
                "websiteUri": "https://hondapowersports.example/",
            },
        ]
    }

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        if body.get("textQuery") == "Detroit MI":
            return Response(200, json=loc_response)
        return Response(200, json=search_response)

    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="motorcycle",
        make="Honda",
        limit=5,
        radius_miles=25,
    )
    assert len(out) == 1
    assert out[0].name == "Honda Powersports of Testville"


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_boats_skips_false_positive_retailers(places_api_key: str) -> None:
    loc_response = {"places": [{"location": {"latitude": 42.33, "longitude": -83.04}}]}
    search_response = {
        "places": [
            {
                "id": "ChIJgear",
                "name": "places/ChIJgear",
                "displayName": {"text": "Michigan Marine Gear"},
                "formattedAddress": "123 Harbor",
                "websiteUri": "https://www.michiganmarinegear.com/",
            },
            {
                "id": "ChIJsales",
                "name": "places/ChIJsales",
                "displayName": {"text": "Temptation Yacht Sales"},
                "formattedAddress": "456 Harbor",
                "websiteUri": "https://www.temptationyachtsales.com/",
            },
        ]
    }

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        if body.get("textQuery") == "Detroit MI":
            return Response(200, json=loc_response)
        return Response(200, json=search_response)

    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="boat",
        make="Sea Ray",
        limit=5,
        radius_miles=25,
    )
    assert len(out) == 1
    assert out[0].name == "Temptation Yacht Sales"


@respx.mock
@pytest.mark.asyncio
async def test_resolve_location_bias_returns_none_on_http_error(places_api_key: str) -> None:
    import httpx

    respx.post(places.SEARCH_TEXT_URL).mock(return_value=Response(500))
    async with httpx.AsyncClient() as client:
        bias = await places._resolve_location_bias(
            client, places_api_key, location="Nowhere", radius_miles=10
        )
    assert bias is None
