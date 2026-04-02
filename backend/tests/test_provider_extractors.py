from __future__ import annotations

from unittest.mock import patch

from app.services.providers.autohausen_ahp6 import extract_inventory as extract_autohausen_ahp6
from app.services.providers.carzilla_search import extract_inventory as extract_carzilla_search
from app.services.providers.cdk_dealerfire import extract_inventory as extract_cdk_dealerfire
from app.services.providers.dealer_spike import extract_inventory as extract_dealer_spike
from app.services.providers.foxdealer import extract_inventory as extract_foxdealer
from app.services.providers.fusionzone import extract_inventory as extract_fusionzone
from app.services.providers.jazel import extract_inventory as extract_jazel
from app.services.providers.purecars import extract_inventory as extract_purecars
from app.services.providers.shift_digital import extract_inventory as extract_shift_digital
from app.services.providers.sincro_digital import extract_inventory as extract_sincro_digital
from app.services.providers.tesla_inventory import extract_inventory as extract_tesla_inventory
from app.services.providers.team_velocity import extract_inventory as extract_team_velocity


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


def test_shift_digital_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "vehicleTitle": "2024 Harley-Davidson Road Glide",
              "vehicleMake": "Harley-Davidson",
              "vehicleModel": "Road Glide",
              "vehicleTrim": "FLTRX",
              "vehicleYear": 2024,
              "currentPrice": "21999",
              "listPrice": "24999",
              "detailUrl": "/inventory/road-glide",
              "stockNumber": "RG123",
              "vin": "1HD1KTC10RB000111"
            }
          ]
        }
      </script>
    </body></html>
    """

    result = extract_shift_digital(
        page_url="https://www.exampleharley.com/new-inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="motorcycle",
    )

    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Harley-Davidson"
    assert vehicle.model == "Road Glide"
    assert vehicle.trim == "FLTRX"
    assert vehicle.price == 21999
    assert vehicle.msrp == 24999
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.exampleharley.com/inventory/road-glide"
    assert vehicle.vehicle_identifier == "1HD1KTC10RB000111"


def test_team_velocity_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "vehicleTitle": "2025 Can-Am Defender DPS HD9",
              "vehicleMake": "Can-Am",
              "vehicleModel": "Defender",
              "vehicleTrim": "DPS HD9",
              "vehicleYear": 2025,
              "priceCurrent": "12699",
              "priceOld": "16699",
              "vehicleLink": "/new-2025-can-am-defender",
              "stocknumber": "TV2341",
              "vin": "3JBUGAP49SK002341"
            }
          ]
        }
      </script>
    </body></html>
    """

    result = extract_team_velocity(
        page_url="https://www.examplepowersports.com/inventory/new",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="other",
    )

    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Can-Am"
    assert vehicle.model == "Defender"
    assert vehicle.trim == "DPS HD9"
    assert vehicle.price == 12699
    assert vehicle.msrp == 16699
    assert vehicle.dealer_discount == 4000
    assert vehicle.listing_url == "https://www.examplepowersports.com/new-2025-can-am-defender"
    assert vehicle.vehicle_identifier == "3JBUGAP49SK002341"


def test_purecars_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "vehicleTitle": "2024 BMW X3 xDrive30i",
              "makeName": "BMW",
              "modelName": "X3",
              "seriesName": "xDrive30i",
              "modelYear": 2024,
              "ourPrice": "46995",
              "retailPrice": "49995",
              "detailPageUrl": "/inventory/2024-bmw-x3",
              "unitNumber": "BX3001",
              "vin": "5UX53DP02R9D00011"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_purecars(
        page_url="https://www.examplebmw.com/inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "BMW"
    assert vehicle.model == "X3"
    assert vehicle.trim == "xDrive30i"
    assert vehicle.price == 46995
    assert vehicle.msrp == 49995
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.examplebmw.com/inventory/2024-bmw-x3"
    assert vehicle.vehicle_identifier == "5UX53DP02R9D00011"


def test_jazel_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "inventory": [
            {
              "vehicleTitle": "2023 Jeep Grand Cherokee Limited",
              "brandName": "Jeep",
              "vehicleModel": "Grand Cherokee",
              "trimName": "Limited",
              "vehicleYear": 2023,
              "salePrice": "38995",
              "listPrice": "41995",
              "detailUrl": "/used/2023-jeep-grand-cherokee",
              "stockNo": "JGC123",
              "vin": "1C4RJHBG7PC000222"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_jazel(
        page_url="https://www.examplejeep.com/used-inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Jeep"
    assert vehicle.model == "Grand Cherokee"
    assert vehicle.trim == "Limited"
    assert vehicle.price == 38995
    assert vehicle.msrp == 41995
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.examplejeep.com/used/2023-jeep-grand-cherokee"
    assert vehicle.vehicle_identifier == "1C4RJHBG7PC000222"


def test_foxdealer_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "vehicleTitle": "2024 Ford F-150 XLT",
              "manufacturerName": "Ford",
              "modelName": "F-150",
              "trimName": "XLT",
              "vehicleYear": 2024,
              "currentPrice": "55995",
              "msrpPrice": "58995",
              "permalink": "/new/2024-ford-f150-xlt",
              "stockNumber": "F15024",
              "vin": "1FTFW3L50RFA00233"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_foxdealer(
        page_url="https://www.exampleford.com/new-inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Ford"
    assert vehicle.model == "F-150"
    assert vehicle.trim == "XLT"
    assert vehicle.price == 55995
    assert vehicle.msrp == 58995
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.exampleford.com/new/2024-ford-f150-xlt"


def test_sincro_digital_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "results": [
            {
              "vehicleTitle": "2024 GMC Sierra 1500 AT4",
              "vehicleMake": "GMC",
              "vehicleModel": "Sierra 1500",
              "vehicleTrim": "AT4",
              "yearModel": 2024,
              "sellingPrice": "62995",
              "listPrice": "65995",
              "vehicleUrl": "/inventory/2024-gmc-sierra-at4",
              "unitNumber": "GMCAT4",
              "vin": "3GTUUEEL2RG000444"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_sincro_digital(
        page_url="https://www.examplegmc.com/inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "GMC"
    assert vehicle.model == "Sierra 1500"
    assert vehicle.trim == "AT4"
    assert vehicle.price == 62995
    assert vehicle.msrp == 65995
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.examplegmc.com/inventory/2024-gmc-sierra-at4"


def test_cdk_dealerfire_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "vehicleTitle": "2024 Honda Accord EX",
              "makeName": "Honda",
              "modelName": "Accord",
              "trimName": "EX",
              "modelYear": 2024,
              "internetPrice": "29995",
              "msrpPrice": "31995",
              "vehicleUrl": "/inventory/2024-honda-accord",
              "stockNo": "HA24001",
              "vin": "1HGCV1F30MA000001"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_cdk_dealerfire(
        page_url="https://www.examplehonda.com/inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Honda"
    assert vehicle.model == "Accord"
    assert vehicle.trim == "EX"
    assert vehicle.year == 2024
    assert vehicle.price == 29995
    assert vehicle.msrp == 31995
    assert vehicle.dealer_discount == 2000
    assert vehicle.listing_url == "https://www.examplehonda.com/inventory/2024-honda-accord"
    assert vehicle.vehicle_identifier == "1HGCV1F30MA000001"


def test_fusionzone_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "vehicles": [
            {
              "name": "2024 Subaru Outback Limited",
              "brandName": "Subaru",
              "modelName": "Outback",
              "trimName": "Limited",
              "vehicleYear": 2024,
              "ourPrice": "38995",
              "retailPrice": "41995",
              "detailPageUrl": "/inventory/2024-subaru-outback",
              "stockNumber": "SO24001",
              "vin": "4S4BTCCC1R3000001"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_fusionzone(
        page_url="https://www.examplesubaru.com/inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Subaru"
    assert vehicle.model == "Outback"
    assert vehicle.trim == "Limited"
    assert vehicle.year == 2024
    assert vehicle.price == 38995
    assert vehicle.msrp == 41995
    assert vehicle.dealer_discount == 3000
    assert vehicle.listing_url == "https://www.examplesubaru.com/inventory/2024-subaru-outback"
    assert vehicle.vehicle_identifier == "4S4BTCCC1R3000001"


def test_dealer_spike_extract_inventory_normalizes_structured_payload_fields() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "inventory": [
            {
              "name": "2025 Sea-Doo Spark",
              "manuf": "Sea-Doo",
              "itemModel": "Spark",
              "itemYear": 2025,
              "itemPrice": "7999",
              "itemUrl": "/inventory/2025-sea-doo-spark",
              "stockNo": "SD001",
              "vin": "YDV12345A125"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_dealer_spike(
        page_url="https://www.examplemarine.com/inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Sea-Doo"
    assert vehicle.model == "Spark"
    assert vehicle.year == 2025
    assert vehicle.price == 7999
    assert vehicle.listing_url == "https://www.examplemarine.com/inventory/2025-sea-doo-spark"
    assert vehicle.vin == "YDV12345A125"
    assert vehicle.vehicle_identifier == "YDV12345A125"



def test_tesla_inventory_extract_inventory_parses_inline_vehicle_records() -> None:
    html = """
    <html><body>
      <script type="application/json">
        {
          "results": [
            {
              "VIN": "5YJ3E1EA9NF123456",
              "Year": 2022,
              "Model": "Model 3",
              "TrimName": "Long Range AWD",
              "Price": 31990,
              "Odometer": 12450,
              "ExteriorColor": "Pearl White Multi-Coat",
              "URL": "/inventory/used/m3/5YJ3E1EA9NF123456"
            }
          ]
        }
      </script>
    </body></html>
    """
    result = extract_tesla_inventory(
        page_url="https://www.tesla.com/inventory/used/m3?zip=90067",
        html=html,
        make_filter="Tesla",
        model_filter="Model 3",
        vehicle_category="car",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    vehicle = result.vehicles[0]
    assert vehicle.make == "Tesla"
    assert vehicle.model == "Model 3"
    assert vehicle.trim == "Long Range AWD"
    assert vehicle.year == 2022
    assert vehicle.price == 31990
    assert vehicle.mileage == 12450
    assert vehicle.vin == "5YJ3E1EA9NF123456"
    assert vehicle.vehicle_identifier == "5YJ3E1EA9NF123456"
    assert vehicle.vehicle_condition == "used"
    assert vehicle.listing_url == "https://www.tesla.com/inventory/used/m3/5YJ3E1EA9NF123456"


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


def test_autohausen_ahp6_applies_make_fallback_when_form_mapping_is_missing() -> None:
    html = """
    <html><body>
      <title>Volkswagen Automobile Berlin</title>
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
            return _FakeResponse(json_data={"make": [], "model": {}})
        if url.endswith("/list"):
            return _FakeResponse(
                json_data={
                    "data": [
                        {
                            "vehicleid": 91,
                            "make": 52,
                            "shortdescription": "Golf Life",
                            "typeextendedcode": 2,
                            "customerprice": "21900",
                            "images": [],
                        }
                    ]
                }
            )
        if url.endswith("/count"):
            return _FakeResponse(json_data={"meta": {"total": 1}})
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
    assert result.vehicles[0].make == "Volkswagen"


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
