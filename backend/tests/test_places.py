"""Unit tests for Google Places client (mocked HTTP)."""

from __future__ import annotations

import json

import pytest
import respx
from app.schemas import DealershipFound
from app.services import places
from httpx import Response


def _geocode_response(lat: float, lng: float) -> dict[str, object]:
    return {"results": [{"geometry": {"location": {"lat": lat, "lng": lng}}}]}


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
    assert places._name_matches_make("BMW Motorcycles of Detroit", "BMW Motorrad")
    assert places._name_matches_make("Factory authorized BMW dealer", "BMW Motorrad")
    assert not places._name_matches_make("Toyota Town", "Ford")
    assert places._name_matches_make("Any", "")


def test_effective_places_search_category_powersports_oem_under_car() -> None:
    """Car + Can-Am should use motorcycle Places profile (no strict car_dealer type)."""
    assert places._effective_places_search_category("car", "Can-Am") == "motorcycle"
    assert places._effective_places_search_category("car", "can am") == "motorcycle"
    assert places._effective_places_search_category("car", "Toyota") == "car"
    assert places._effective_places_search_category("motorcycle", "Can-Am") == "motorcycle"


def test_name_matches_make_includes_can_am_in_combined_name_and_website() -> None:
    hay = "River Raisin Powersports https://www.riverraisinpowersports.com/shop-brp/can-am"
    assert places._name_matches_make(hay, "Can-Am")


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


def test_trusted_national_boat_retailer_is_not_treated_as_false_positive() -> None:
    assert places._is_trusted_national_retailer_match(
        "Bass Pro Shops Boating Center Auburn Hills",
        "https://www.bassproboatingcenters.com/boats-for-sale.html",
        vehicle_category="boat",
    )
    assert not places._looks_like_false_positive_category_match(
        "Bass Pro Shops Boating Center Auburn Hills",
        "https://www.bassproboatingcenters.com/boats-for-sale.html",
        vehicle_category="boat",
    )
    assert places._is_trusted_national_retailer_match(
        "MarineMax Clearwater",
        "https://www.marinemax.com/boats-for-sale/stores/clearwater",
        vehicle_category="boat",
    )


def test_false_positive_genesis_make_match_excludes_other_oems_and_generic_groups() -> None:
    assert places._looks_like_false_positive_make_match(
        "Genesis Chevrolet",
        "https://www.genesischevrolet.com/",
        make="Genesis",
        vehicle_category="car",
    )
    assert places._looks_like_false_positive_make_match(
        "Genesis Automotive Group",
        "https://www.genesisautomotivegroup.com/",
        make="Genesis",
        vehicle_category="car",
    )
    assert not places._looks_like_false_positive_make_match(
        "Genesis of Southfield",
        "https://www.genesisofsouthfield.com/",
        make="Genesis",
        vehicle_category="car",
    )


def test_corporate_non_dealer_filter_detects_main_office_keywords() -> None:
    assert places._looks_like_corporate_non_dealer("Bennington Pontoon Boats Main Office")
    assert places._looks_like_corporate_non_dealer("ACME Marine Corporate Office")
    assert not places._looks_like_corporate_non_dealer("White's Marine Center")


def test_normalize_dealer_website_url_strips_tracking() -> None:
    u = places._normalize_dealer_website_url("https://dealer.com/?gclid=1&utm_source=email")
    assert "gclid" not in u
    assert "utm_source" not in u
    assert "dealer.com" in u


def test_normalize_dealer_website_url_collapses_buy_subdomain_to_homepage() -> None:
    u = places._normalize_dealer_website_url(
        "https://buy.jamesmartindetroit.com/carbravo?evar109=115100&evar120=dealeron"
    )
    assert u == "https://www.jamesmartindetroit.com/"


def test_normalize_dealer_website_url_rejects_javascript_void() -> None:
    assert places._normalize_dealer_website_url("javascript:void(0)") == ""
    assert places._normalize_dealer_website_url("javascript:void(0);") == ""
    assert places._normalize_dealer_website_url("tel:+13135551234") == ""
    assert places._normalize_dealer_website_url("mailto:info@dealer.com") == ""
    assert places._normalize_dealer_website_url("https://dealer.com/") != ""


def test_normalize_dealer_website_url_rejects_aggregator_profiles() -> None:
    assert places._normalize_dealer_website_url("http://www.boats.com/sites/activemarine") == ""
    assert places._normalize_dealer_website_url("https://www.cars.com/dealers/12345/") == ""
    assert places._normalize_dealer_website_url("https://www.boattrader.com/dealers/some-marina") == ""
    assert places._normalize_dealer_website_url("https://www.cycletrader.com/dealer/ABC") == ""
    assert places._normalize_dealer_website_url("https://www.mydealer.com/inventory") != ""


def test_normalize_dealer_website_url_rejects_social_profiles() -> None:
    assert places._normalize_dealer_website_url("https://www.facebook.com/complex.powersports/") == ""
    assert places._normalize_dealer_website_url("https://instagram.com/somepowersportsdealer") == ""
    assert places._normalize_dealer_website_url("https://www.linkedin.com/company/dealer-group") == ""
    assert places._normalize_dealer_website_url("https://www.realdealer.com/") != ""


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
    """Geocoding + text search return places with website; no details call needed."""
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_car_dealerships("Detroit MI", make="Ford", model="", limit=5, radius_miles=25)
    assert len(out) >= 1
    assert isinstance(out[0], DealershipFound)
    assert out[0].website.startswith("https://ford-test.example")


@respx.mock
@pytest.mark.asyncio
async def test_find_car_dealerships_filters_results_outside_requested_radius(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJnear",
                "name": "places/ChIJnear",
                "displayName": {"text": "Nearby Ford"},
                "formattedAddress": "123 Main",
                "websiteUri": "https://nearby-ford.example/",
                "location": {"latitude": 42.359, "longitude": -83.05},
            },
            {
                "id": "ChIJfar",
                "name": "places/ChIJfar",
                "displayName": {"text": "Far Ford"},
                "formattedAddress": "456 Main",
                "websiteUri": "https://far-ford.example/",
                "location": {"latitude": 42.75, "longitude": -83.05},
            },
        ]
    }
    search_bodies: list[dict] = []

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        search_bodies.append(body)
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.3314, -83.0458)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_car_dealerships("Detroit MI", make="Ford", limit=5, radius_miles=25)
    assert [dealer.name for dealer in out] == ["Nearby Ford"]
    assert search_bodies
    assert "locationRestriction" in search_bodies[0]


@respx.mock
@pytest.mark.asyncio
async def test_find_car_dealerships_applies_radius_filter_for_ten_mile_searches(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJnear10",
                "name": "places/ChIJnear10",
                "displayName": {"text": "Nearby Volvo"},
                "formattedAddress": "123 Main",
                "websiteUri": "https://nearby-volvo.example/",
                "location": {"latitude": 42.359, "longitude": -83.05},
            },
            {
                "id": "ChIJfar10",
                "name": "places/ChIJfar10",
                "displayName": {"text": "Far Volvo"},
                "formattedAddress": "456 Main",
                "websiteUri": "https://far-volvo.example/",
                "location": {"latitude": 42.48, "longitude": -83.05},
            },
        ]
    }
    search_bodies: list[dict] = []

    def _route(request: object) -> Response:
        try:
            raw = request.content.decode() if getattr(request, "content", None) else "{}"  # type: ignore[union-attr]
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return Response(200, json={"places": []})
        search_bodies.append(body)
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.3314, -83.0458)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_car_dealerships("Detroit MI", make="Volvo", limit=5, radius_miles=10)
    assert [dealer.name for dealer in out] == ["Nearby Volvo"]
    assert search_bodies
    assert "locationRestriction" in search_bodies[0]


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_boats_uses_untyped_query(places_api_key: str) -> None:
    """Boat discovery should rely on text query matching instead of car_dealer filtering."""
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
        seen_queries.append(body)
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
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
async def test_find_dealerships_motorcycles_keeps_multibrand_fallbacks_when_brand_match_exists(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJhonda",
                "name": "places/ChIJhonda",
                "displayName": {"text": "Honda Powersports of Testville"},
                "formattedAddress": "123 Main",
                "websiteUri": "https://hondapowersports.example/",
            },
            {
                "id": "ChIJmulti1",
                "name": "places/ChIJmulti1",
                "displayName": {"text": "River Raisin Powersports"},
                "formattedAddress": "456 Main",
                "websiteUri": "https://riverraisinpowersports.example/shop/honda",
            },
            {
                "id": "ChIJmulti2",
                "name": "places/ChIJmulti2",
                "displayName": {"text": "Generic Powersports"},
                "formattedAddress": "789 Main",
                "websiteUri": "https://genericpowersports.example/",
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="motorcycle",
        make="Honda",
        limit=10,
        radius_miles=25,
    )
    assert [d.name for d in out] == [
        "Honda Powersports of Testville",
        "River Raisin Powersports",
        "Generic Powersports",
    ]


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_boats_skips_false_positive_retailers(places_api_key: str) -> None:
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
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
async def test_find_dealerships_boats_keeps_trusted_national_retailers_with_local_results(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJbasspro",
                "name": "places/ChIJbasspro",
                "displayName": {"text": "Bass Pro Shops Boating Center Auburn Hills"},
                "formattedAddress": "Auburn Hills, MI",
                "websiteUri": "https://www.bassproboatingcenters.com/boats-for-sale.html",
            },
            {
                "id": "ChIJgear",
                "name": "places/ChIJgear",
                "displayName": {"text": "Michigan Marine Gear"},
                "formattedAddress": "123 Harbor",
                "websiteUri": "https://www.michiganmarinegear.com/",
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="boat",
        make="Tracker",
        limit=5,
        radius_miles=25,
    )
    assert len(out) == 1
    assert out[0].name == "Bass Pro Shops Boating Center Auburn Hills"


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_boats_make_search_requires_place_coordinates_when_radius_filtered(
    places_api_key: str,
) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJmissing",
                "name": "places/ChIJmissing",
                "displayName": {"text": "Unknown Location Marina"},
                "formattedAddress": "Anywhere, MI",
                "websiteUri": "https://unknown-location-marina.example/",
            },
            {
                "id": "ChIJnear",
                "name": "places/ChIJnear",
                "displayName": {"text": "Local Harbor Marine"},
                "formattedAddress": "Detroit, MI",
                "websiteUri": "https://local-harbor-marine.example/",
                "location": {"latitude": 42.355, "longitude": -83.05},
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.3314, -83.0458)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "48234",
        vehicle_category="boat",
        make="Bennington",
        limit=10,
        radius_miles=25,
    )
    assert [dealer.name for dealer in out] == ["Local Harbor Marine"]


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_skips_corporate_main_office_candidates(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJcorp",
                "name": "places/ChIJcorp",
                "displayName": {"text": "Bennington Pontoon Boats Main Office"},
                "formattedAddress": "Elkhart, IN",
                "websiteUri": "https://www.benningtonmarine.com/",
                "location": {"latitude": 41.68, "longitude": -85.98},
            },
            {
                "id": "ChIJdealer",
                "name": "places/ChIJdealer",
                "displayName": {"text": "White's Marine Center"},
                "formattedAddress": "Harrison Township, MI",
                "websiteUri": "https://www.whitesmarinecenter.com/",
                "location": {"latitude": 42.58, "longitude": -82.83},
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.3314, -83.0458)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="boat",
        make="Bennington",
        limit=10,
        radius_miles=250,
    )
    assert [dealer.name for dealer in out] == ["White's Marine Center"]


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_cars_genesis_skips_false_positive_named_businesses(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": "ChIJgenchevy",
                "name": "places/ChIJgenchevy",
                "displayName": {"text": "Genesis Chevrolet"},
                "formattedAddress": "21800 Gratiot Ave, Eastpointe, MI",
                "websiteUri": "https://www.genesischevrolet.com/",
            },
            {
                "id": "ChIJgengroup",
                "name": "places/ChIJgengroup",
                "displayName": {"text": "Genesis Automotive Group"},
                "formattedAddress": "23001 W Industrial Dr, St Clair Shores, MI",
                "websiteUri": "https://www.genesisautomotivegroup.com/",
            },
            {
                "id": "ChIJgensouthfield",
                "name": "places/ChIJgensouthfield",
                "displayName": {"text": "Genesis of Southfield"},
                "formattedAddress": "Southfield, MI",
                "websiteUri": "https://www.genesisofsouthfield.com/",
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="car",
        make="Genesis",
        limit=10,
        radius_miles=25,
    )
    assert len(out) == 1
    assert out[0].name == "Genesis of Southfield"


@respx.mock
@pytest.mark.asyncio
async def test_find_dealerships_motorcycles_caps_generic_fallback_candidates(places_api_key: str) -> None:
    search_response = {
        "places": [
            {
                "id": f"ChIJ{i}",
                "name": f"places/ChIJ{i}",
                "displayName": {"text": f"Generic Powersports {i}"},
                "formattedAddress": f"{i} Main",
                "websiteUri": f"https://generic-powersports-{i}.example/",
            }
            for i in range(6)
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
        return Response(200, json=search_response)

    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))
    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)

    out = await places.find_dealerships(
        "Detroit MI",
        vehicle_category="motorcycle",
        make="Triumph",
        limit=20,
        radius_miles=25,
    )
    assert len(out) == 3


@respx.mock
@pytest.mark.asyncio
async def test_resolve_location_center_returns_none_on_http_error(places_api_key: str) -> None:
    import httpx

    respx.get(places.GEOCODE_URL).mock(return_value=Response(500))
    async with httpx.AsyncClient() as client:
        center = await places._resolve_location_center(client, places_api_key, location="Nowhere")
    assert center is None


@respx.mock
@pytest.mark.asyncio
async def test_find_car_dealerships_uses_search_cache(places_api_key: str) -> None:
    search_calls = 0
    respx.get(places.GEOCODE_URL).mock(return_value=Response(200, json=_geocode_response(42.33, -83.04)))

    def _route(_request: object) -> Response:
        nonlocal search_calls
        search_calls += 1
        return Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJcache",
                        "name": "places/ChIJcache",
                        "displayName": {"text": "Cached Dealer"},
                        "formattedAddress": "123 Main",
                        "websiteUri": "https://cached-dealer.example/",
                    }
                ]
            },
        )

    respx.post(places.SEARCH_TEXT_URL).mock(side_effect=_route)
    metrics_one = places.PlacesSearchMetrics()
    metrics_two = places.PlacesSearchMetrics()

    first = await places.find_car_dealerships("Detroit MI", make="Ford", limit=5, radius_miles=25, metrics=metrics_one)
    second = await places.find_car_dealerships("Detroit MI", make="Ford", limit=5, radius_miles=25, metrics=metrics_two)

    assert len(first) == 1
    assert len(second) == 1
    assert search_calls == metrics_one.search_calls
    assert metrics_one.search_calls >= 1
    assert metrics_two.search_calls == 0
    assert metrics_two.search_cache_hits == 1
