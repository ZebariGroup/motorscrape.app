from __future__ import annotations

from unittest.mock import patch

from app.services.providers.autohausen_ahp6 import extract_inventory as extract_autohausen_ahp6
from app.services.providers.carzilla_search import extract_inventory as extract_carzilla_search


class _FakeResponse:
    def __init__(self, *, json_data=None, text: str = "", status_code: int = 200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_data is None:
            raise RuntimeError("No JSON payload configured")
        return self._json_data


def test_autohausen_ahp6_extract_inventory_maps_api_rows_and_paginates() -> None:
    html = """
    <html><body>
      <script>
        ahp6.renderSearch('ahp6-search', {
          publicKey: 'pk-test',
          searchPageUri: '/gebrauchtwagen/fahrzeugsuche/',
          detailPageUri: '/gebrauchtwagen/fahrzeugsuche/:vehicleId',
          defaultFilter: {
            typeextendedcode: [2, 4]
          }
        })
      </script>
    </body></html>
    """

    def _fake_post(url: str, *, json=None, headers=None, timeout=None):  # type: ignore[override]
        assert headers is not None
        if url.endswith("/form"):
            return _FakeResponse(
                json_data={
                    "make": [{"value": "52", "label": "Volkswagen"}],
                    "model": {"52": [{"value": "5200734", "label": "Golf"}]},
                }
            )
        if url.endswith("/count"):
            assert json == {"filter": {"typeextendedcode": [2, 4], "make": [52]}, "publicKey": "pk-test"}
            return _FakeResponse(json_data={"meta": {"total": 75}})
        if url.endswith("/list"):
            assert json == {
                "filter": {"typeextendedcode": [2, 4], "make": [52]},
                "orderBy": "priceAsc",
                "offset": 0,
                "limit": 50,
                "publicKey": "pk-test",
            }
            return _FakeResponse(
                json_data={
                    "data": [
                        {
                            "vehicleid": 8520311,
                            "make": 52,
                            "model": 5200734,
                            "typeextendedcode": 2,
                            "registrationdate": "2024-02-01",
                            "shortdescription": "Golf Style 1.5 eTSI DSG",
                            "customerprice": "24990.00",
                            "listprice": "27990.00",
                            "images": [{"m": "https://images.example.com/golf.jpg"}],
                        }
                    ]
                }
            )
        raise AssertionError(url)

    with patch("app.services.providers.autohausen_ahp6.requests.post", side_effect=_fake_post):
        result = extract_autohausen_ahp6(
            page_url="https://www.volkswagen-automobile-berlin.de/gebrauchtwagen/fahrzeugsuche/",
            html=html,
            make_filter="Volkswagen",
            model_filter="",
            vehicle_category="car",
        )

    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Volkswagen"
    assert vehicle.model == "Golf"
    assert vehicle.price == 24990
    assert vehicle.msrp == 27990
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.volkswagen-automobile-berlin.de/gebrauchtwagen/fahrzeugsuche/8520311"
    assert vehicle.image_url == "https://images.example.com/golf.jpg"
    assert result.next_page_url == (
        "https://www.volkswagen-automobile-berlin.de/gebrauchtwagen/fahrzeugsuche/?ahp6_offset=50"
    )
    assert result.pagination is not None
    assert result.pagination.total_results == 75
    assert result.pagination.page_size == 50


def test_autohausen_ahp6_extract_inventory_accepts_public_key_used_vehicles_only() -> None:
    html = """
    <html><body>
      <script src="https://vgrdapps.autohausen.ag/ahp6/snippet/main.js"></script>
      <script>
        ahp6.renderQuickSearch('ahp6-quick-search', {
          publicKeyUsedVehicles: 'pk-used',
          publicKeyNewVehicles: 'pk-used',
        })
      </script>
    </body></html>
    """

    def _fake_post(url: str, *, json=None, headers=None, timeout=None):  # type: ignore[override]
        assert headers is not None
        if url.endswith("/form"):
            return _FakeResponse(
                json_data={
                    "make": [{"value": "52", "label": "Volkswagen"}],
                    "model": {},
                }
            )
        if url.endswith("/count"):
            return _FakeResponse(json_data={"meta": {"total": 1}})
        if url.endswith("/list"):
            assert json is not None and json.get("publicKey") == "pk-used"
            return _FakeResponse(
                json_data={
                    "data": [
                        {
                            "vehicleid": 1,
                            "make": 52,
                            "model": None,
                            "typeextendedcode": 2,
                            "shortdescription": "Golf",
                            "customerprice": "20000",
                            "images": [],
                        }
                    ]
                }
            )
        raise AssertionError(url)

    with patch("app.services.providers.autohausen_ahp6.requests.post", side_effect=_fake_post):
        result = extract_autohausen_ahp6(
            page_url="https://www.volkswagen-frankfurt.de/",
            html=html,
            make_filter="Volkswagen",
            model_filter="",
            vehicle_category="car",
        )

    assert result is not None
    assert len(result.vehicles) == 1
    assert result.vehicles[0].make == "Volkswagen"


def test_autohausen_ahp6_keeps_rows_when_count_endpoint_fails() -> None:
    html = """
    <html><body>
      <script>
        ahp6.renderSearch('ahp6-search', {
          publicKey: 'pk-test',
          detailPageUri: '/gebrauchtwagen/fahrzeugsuche/:vehicleId'
        })
      </script>
    </body></html>
    """

    def _fake_post(url: str, *, json=None, headers=None, timeout=None):  # type: ignore[override]
        assert headers is not None
        if url.endswith("/form"):
            return _FakeResponse(
                json_data={
                    "make": [{"value": "52", "label": "Volkswagen"}],
                    "model": {},
                }
            )
        if url.endswith("/list"):
            return _FakeResponse(
                json_data={
                    "data": [
                        {
                            "vehicleid": 77,
                            "make": 52,
                            "shortdescription": "Golf",
                            "typeextendedcode": 2,
                            "customerprice": "19900",
                            "images": [],
                        }
                    ]
                }
            )
        if url.endswith("/count"):
            return _FakeResponse(status_code=500, json_data={"error": "boom"})
        raise AssertionError(url)

    with patch("app.services.providers.autohausen_ahp6.requests.post", side_effect=_fake_post):
        result = extract_autohausen_ahp6(
            page_url="https://www.volkswagen-automobile-berlin.de/gebrauchtwagen/fahrzeugsuche/",
            html=html,
            make_filter="Volkswagen",
            model_filter="",
            vehicle_category="car",
        )

    assert result is not None
    assert len(result.vehicles) == 1
    assert result.pagination is not None
    assert result.pagination.total_results is None


def test_carzilla_search_extract_inventory_fetches_trefferliste_results() -> None:
    shell_html = """
    <html><body>
      <script>
        var carzillaSearchInstance1 = {};
        carzillaSearchInstance1.RestServiceUrl = "/?type=17911";
      </script>
      <div class="vehicle--counter" data-params="of=SalePrice"></div>
    </body></html>
    """
    results_html = """
    <html><body>
      <div class="cc-vehicle card mb-4">
        <div class="vehicle-image">
          <a class="cc-link-vehicle-detail cc-vehicle__image"
             href="/fahrzeuge/fahrzeugsuche/detailansicht/fahrzeug/volkswagen/e-up/gebrauchtfahrzeug/8861640/?ma=69&of=SalePrice">
            <img data-src="https://images.example.com/eup.jpg" />
          </a>
        </div>
        <div class="card-body">
          <div class="vehicle-headline">
            <h5 class="card-title mb-3">
              <a class="cc-link-vehicle-detail"
                 href="/fahrzeuge/fahrzeugsuche/detailansicht/fahrzeug/volkswagen/e-up/gebrauchtfahrzeug/8861640/?ma=69&of=SalePrice">
                Volkswagen e-up! move up
              </a>
            </h5>
          </div>
          <div class="vehicle-price-wrap">
            <div class="vehicle-price__price mb-0 text-gs h5">11.100,- €</div>
          </div>
        </div>
      </div>
      <nav aria-label="Pagination">
        <a href="?ma=69&of=SalePrice&cp=2" aria-label="Page 2">2</a>
      </nav>
    </body></html>
    """

    def _fake_get(url: str, *, headers=None, timeout=None):  # type: ignore[override]
        assert headers is not None
        if "GetInitialData" in url:
            return _FakeResponse(
                json_data={
                    "d": {
                        "SearchCatalog": {
                            "Makes": [
                                {"Name": "Volkswagen", "Identifier": "69"},
                            ]
                        }
                    }
                }
            )
        if "/fahrzeuge/fahrzeugsuche/trefferliste/" in url:
            assert "ma=69" in url
            return _FakeResponse(text=results_html)
        raise AssertionError(url)

    with patch("app.services.providers.carzilla_search.requests.get", side_effect=_fake_get):
        result = extract_carzilla_search(
            page_url="https://www.gottfried-schultz.de/fahrzeuge/fahrzeugsuche/",
            html=shell_html,
            make_filter="Volkswagen",
            model_filter="",
            vehicle_category="car",
        )

    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.raw_title == "Volkswagen e-up! move up"
    assert vehicle.price == 11100
    assert vehicle.listing_url == (
        "https://www.gottfried-schultz.de/fahrzeuge/fahrzeugsuche/detailansicht/fahrzeug/"
        "volkswagen/e-up/gebrauchtfahrzeug/8861640/?ma=69&of=SalePrice"
    )


def test_carzilla_search_accepts_single_quoted_rest_service_url() -> None:
    shell_html = """
    <html><body>
      <script>
        var carzillaSearchInstance1 = {};
        carzillaSearchInstance1.RestServiceUrl = '/?type=17911';
      </script>
      <div class="vehicle--counter" data-params="of=SalePrice"></div>
    </body></html>
    """
    results_html = """
    <html><body>
      <div class="cc-vehicle card mb-4">
        <div class="vehicle-image">
          <a class="cc-link-vehicle-detail" href="/fahrzeuge/fahrzeugsuche/detailansicht/fahrzeug/volkswagen/golf/gebrauchtfahrzeug/1/?ma=69&of=SalePrice">
            <img data-src="https://images.example.com/golf.jpg" />
          </a>
        </div>
        <div class="card-body">
          <h5 class="card-title mb-3">
            <a class="cc-link-vehicle-detail" href="/fahrzeuge/fahrzeugsuche/detailansicht/fahrzeug/volkswagen/golf/gebrauchtfahrzeug/1/?ma=69&of=SalePrice">
              Volkswagen Golf
            </a>
          </h5>
          <div class="vehicle-price__price">18.000,- €</div>
        </div>
      </div>
    </body></html>
    """

    def _fake_get(url: str, *, headers=None, timeout=None):  # type: ignore[override]
        assert headers is not None
        if "GetInitialData" in url:
            return _FakeResponse(
                json_data={
                    "d": {
                        "SearchCatalog": {
                            "Makes": [
                                {"Name": "Volkswagen", "Identifier": "69"},
                            ]
                        }
                    }
                }
            )
        if "/fahrzeuge/fahrzeugsuche/trefferliste/" in url:
            return _FakeResponse(text=results_html)
        raise AssertionError(url)

    with patch("app.services.providers.carzilla_search.requests.get", side_effect=_fake_get):
        result = extract_carzilla_search(
            page_url="https://www.gottfried-schultz.de/fahrzeuge/fahrzeugsuche/",
            html=shell_html,
            make_filter="Volkswagen",
            model_filter="",
            vehicle_category="car",
        )

    assert result is not None
    assert len(result.vehicles) == 1
