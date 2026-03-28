"""Parser extraction tests (no OpenAI)."""

from __future__ import annotations

from app.services.parser import find_next_page_url, try_extract_vehicles_without_llm


def test_try_extract_dom_vehicle_card() -> None:
    html = """
    <html><body>
      <div class="vehicle-card" data-year="2024" data-make="Toyota" data-model="Camry" data-price="28000">
        <a href="/inventory/v1">2024 Toyota Camry LE</a>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/inventory",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2024
    assert v.make == "Toyota"
    assert v.model == "Camry"
    assert v.price == 28000
    assert v.listing_url == "https://dealer.example/inventory/v1"


def test_try_extract_dom_msrp_and_discount_from_attributes() -> None:
    html = """
    <html><body>
      <div class="vehicle-card" data-year="2024" data-make="Jeep" data-model="Wrangler"
           data-price="42000" data-msrp="45000" data-days-on-lot="18">
        <a href="/inventory/j1">2024 Jeep Wrangler</a>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/inventory",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    v = result.vehicles[0]
    assert v.price == 42000
    assert v.msrp == 45000
    assert v.dealer_discount == 3000
    assert v.days_on_lot == 18


def test_try_extract_team_velocity_vehicle_card() -> None:
    html = """
    <html><body>
      <li class="v7list-results__item" data-unit-condition="NEW" data-unit-id="17858891" data-unit-make="Can-Am" data-unit-year="2025">
        <article class="v7list-vehicle">
          <a class="vehicle__image" data-src="https://cdn.example.com/unit.jpg|https://cdn.example.com/unit-large.jpg"
             href="/NEW-Inventory-2025-Can-Am-Utility-Vehicle-Defender-DPS-HD9-Compass-Green-17858891?ref=list"></a>
          <h3 class="v7list-vehicle__heading">
            <a class="vehicle-heading__link" href="/NEW-Inventory-2025-Can-Am-Utility-Vehicle-Defender-DPS-HD9-Compass-Green-17858891?ref=list">
              <span class="vehicle-heading__year">2025</span>
              <span class="vehicle-heading__name">Can-Am</span>
              <span class="vehicle-heading__model">Defender DPS HD9 Compass Green</span>
            </a>
          </h3>
          <span class="vehicle-price vehicle-price--old">
            <span class="vehicle-price__price">$16,699</span>
          </span>
          <span class="vehicle-price vehicle-price--current">
            <span class="vehicle-price__price">$12,699</span>
          </span>
          <span class="vehicle-price vehicle-price--savings">
            <span class="vehicle-price__price">$4,000</span>
          </span>
          <ul class="vehicle-specs__list">
            <li class="vehicle-specs__item vehicle-specs__item--condition">
              <span class="vehicle-specs__value">NEW</span>
            </li>
            <li class="vehicle-specs__item vehicle-specs__item--location">
              <span class="vehicle-specs__value">Powersports of Greenville</span>
            </li>
            <li class="vehicle-specs__item vehicle-specs__item--stock-number">
              <span class="vehicle-specs__value">002341</span>
            </li>
            <li class="vehicle-specs__item vehicle-specs__item--vin">
              <span class="vehicle-specs__value">3JBUGAP49SK002341</span>
            </li>
          </ul>
        </article>
      </li>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/--inventory",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="motorcycle",
        platform_id="team_velocity",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2025
    assert v.make == "Can-Am"
    assert v.model == "Defender"
    assert v.trim == "DPS HD9 Compass Green"
    assert v.price == 12699
    assert v.msrp == 16699
    assert v.dealer_discount == 4000
    assert v.vehicle_condition == "new"
    assert v.vin == "3JBUGAP49SK002341"
    assert v.vehicle_identifier == "3JBUGAP49SK002341"
    assert v.inventory_location == "Powersports of Greenville"
    assert v.image_url == "https://cdn.example.com/unit.jpg"


def test_try_extract_brand_inventory_boat_card() -> None:
    html = """
    <html><body>
      <div class="brandInventoryCard">
        <div class="brandInventoryImageContainer">
          <a href="/used-pre-owned-boats-for-sale-detail/2023-robalo-r317-dual-console">
            <img alt="2023 Robalo R317 Dual Console" src="https://images.example.com/robalo.jpg" />
          </a>
          <div class="promotionalBanner">
            <p class="promotionBannerText">In Stock</p>
          </div>
        </div>
        <div class="brandCardContent">
          <a href="/used-pre-owned-boats-for-sale-detail/2023-robalo-r317-dual-console">
            <h4 class="featuredCardHeading">2023 Robalo R317 Dual Console</h4>
          </a>
          <p class="featuredCardPrice">$269,900</p>
          <p class="fearuredCardLocation">
            <span class="textAfterLine">Used</span>
            <span class="textAfterLine">31ft</span>
            <span>In Stock</span>
          </p>
        </div>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats-for-sale",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.vehicle_category == "boat"
    assert v.year == 2023
    assert v.make == "Robalo"
    assert v.model == "R317"
    assert v.trim == "Dual Console"
    assert v.price == 269900
    assert v.vehicle_condition == "used"
    assert v.image_url == "https://images.example.com/robalo.jpg"
    assert v.listing_url == "https://dealer.example/used-pre-owned-boats-for-sale-detail/2023-robalo-r317-dual-console"
    assert v.availability_status is not None


def test_try_extract_wilson_unit_row_boat_card() -> None:
    html = """
    <html><body>
      <div class="unit-row row">
        <div class="col-xs-12 col-sm-4 t-mb-30">
          <a href="/inventory/2024-bayliner-dx2200-54716">
            <img alt="2024 Bayliner DX2200" class="unit-img" src="https://images.example.com/bayliner.jpg" />
          </a>
        </div>
        <div class="col-xs-12 col-sm-4">
          <p class="unit-status">Available</p>
          <a href="/inventory/2024-bayliner-dx2200-54716"><h3 class="unit-name-vlp">2024 Bayliner DX2200</h3></a>
          <div class="vlp-spec-row">
            <div class="d-flex"><p class="fw-bold">Stock Number</p><p>54716</p></div>
            <div class="d-flex"><p class="fw-bold">Condition</p><p class="unit-condition">NEW</p></div>
            <div class="d-flex"><p class="fw-bold">Location</p><p class="unit-condition">Wixom</p></div>
          </div>
          <p class="sales-price unit-sale m0">$60,226</p>
        </div>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/bayliner-boats-for-sale",
        html=html,
        make_filter="Bayliner",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2024
    assert v.make == "Bayliner"
    assert v.model == "DX2200"
    assert v.price == 60226
    assert v.vehicle_condition == "new"
    assert v.vehicle_identifier == "54716"
    assert v.inventory_location == "Wixom"
    assert v.image_url == "https://images.example.com/bayliner.jpg"


def test_try_extract_grand_pointe_inv_card() -> None:
    html = """
    <html><body>
      <article class="inv-card">
        <a href="https://dealer.example/boat/bayliner-element-m17-123/">
          <div class="inv-thumb">
            <img src="https://images.example.com/element.jpg" />
          </div>
          <div class="inv-content">
            <div class="inv-content-top">
              <span class="inv-stock">STOCK #: 123</span>
              <h3>2024 Bayliner Element M17</h3>
            </div>
            <div class="inv-content-bottom">
              <span class="inv-price">$24,999</span>
              <div class="inv-location">Detroit, MI</div>
            </div>
          </div>
        </a>
      </article>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats/",
        html=html,
        make_filter="Bayliner",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2024
    assert v.make == "Bayliner"
    assert v.model == "Element"
    assert v.trim == "M17"
    assert v.price == 24999
    assert v.inventory_location == "Detroit, MI"
    assert v.listing_url == "https://dealer.example/boat/bayliner-element-m17-123/"


def test_try_extract_grand_pointe_inv_card_prefers_lazyload_image_over_placeholder() -> None:
    html = """
    <html><body>
      <article class="inv-card">
        <a href="https://dealer.example/boat/lund-1650-angler-ss-123/">
          <div class="inv-thumb">
            <img
              class="lazyload"
              src="data:image/png;base64,placeholder"
              data-src="https://images.example.com/lund.jpg"
              data-srcset="https://images.example.com/lund.jpg 1024w, https://images.example.com/lund-small.jpg 300w"
            />
          </div>
          <div class="inv-content">
            <div class="inv-content-top">
              <span class="inv-stock">STOCK #: lund16</span>
              <h3>2022 Lund 1650 Angler SS</h3>
            </div>
            <div class="inv-content-bottom">
              <span class="inv-price">$24,500</span>
              <div class="inv-location">Lansing, MI</div>
            </div>
          </div>
        </a>
      </article>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats/",
        html=html,
        make_filter="Lund",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.image_url == "https://images.example.com/lund.jpg"


def test_try_extract_inventory_model_single_boat_card() -> None:
    html = """
    <html><body>
      <div class="inventory-model-single"
           data-boat-hin="SERP12345678"
           data-boat-id="10040001"
           data-boat-make="Sea Ray"
           data-boat-model="SLX 280"
           data-boat-stock-number=""
           data-boat-year="2022">
        <a href="https://dealer.example/boats-for-sale/2022-sea-ray-slx-280/">
          <div class="boat-make">
            <h5>Sea Ray <span>SLX 280</span></h5>
          </div>
          <div class="boat-image">
            <div class="boat-image-container" style="background-image:url('https://images.example.com/searay.jpg');"></div>
            <div class="listing-title">Available now</div>
          </div>
        </a>
        <div class="boat-details">
          <div class="top-boat">
            <div class="boat-location col-xs-12">St. Clair Shores, Michigan</div>
          </div>
          <div class="bottom-boat">
            <div class="col-xs-3 boat-year"><span>Year</span>2022</div>
            <div class="col-xs-5 boat-price no-js">
              <div class="main-boat-price no-js">$189,900</div>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats-for-sale/",
        html=html,
        make_filter="Sea Ray",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2022
    assert v.make == "Sea Ray"
    assert v.model == "SLX 280"
    assert v.price == 189900
    assert v.vehicle_identifier == "SERP12345678"
    assert v.inventory_location == "St. Clair Shores, Michigan"
    assert v.image_url == "https://images.example.com/searay.jpg"
    assert v.availability_status is not None


def test_try_extract_colony_hit_boat_card() -> None:
    html = """
    <html><body>
      <div class="hit">
        <div class="relative w-full lg:w-72">
          <img src="https://images.example.com/colony-searay.jpg" />
          <a class="absolute inset-0 z-10" href="https://dealer.example/new-boats-for-sale/sea-ray/2026-sea-ray-slx-310-outboard-1"></a>
        </div>
        <div class="flex-1 min-w-0">
          <a href="https://dealer.example/new-boats-for-sale/sea-ray/2026-sea-ray-slx-310-outboard-1">
            <h2>2026 Sea Ray SLX 310 Outboard</h2>
          </a>
          <div class="hit-content">
            <div class="flex divide-x mt-2 overflow-auto">
              <div><span class="block uppercase">Status</span><span class="block text-sm font-medium">Available</span></div>
              <div><span class="block uppercase">Location</span><span class="block text-sm font-medium">St. Clair Shores, MI</span></div>
              <div><span class="block uppercase">Manufacturer</span><span class="block text-sm font-medium">Sea Ray</span></div>
              <div><span class="block uppercase">Stock #</span><span class="block text-sm font-medium">14430</span></div>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/michigan-new-sea-ray-boats-for-sale/",
        html=html,
        make_filter="Sea Ray",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.year == 2026
    assert v.make == "Sea Ray"
    assert v.model == "SLX"
    assert v.trim == "310 Outboard"
    assert v.vehicle_identifier == "14430"
    assert v.inventory_location == "St. Clair Shores, MI"
    assert v.image_url == "https://images.example.com/colony-searay.jpg"


def test_try_extract_boat_usage_and_identifier() -> None:
    html = """
    <html><body>
      <div class="vehicle-card" data-year="2022" data-make="Sea Ray" data-model="SLX" data-price="95000">
        <a href="/inventory/b1">2022 Sea Ray SLX</a>
        <div>125 hours</div>
        <div>Stock # BR240</div>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.vehicle_category == "boat"
    assert v.usage_value == 125
    assert v.usage_unit == "hours"
    assert v.vehicle_identifier == "BR240"
    assert v.mileage is None


def test_try_extract_boat_multiword_make_from_title_card() -> None:
    html = """
    <html><body>
      <a class="c-widget--vehicle" href="/inventory/sea-ray-1">
        2024 Sea Ray SLX 280
      </a>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="Sea Ray",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Sea Ray"
    assert v.model == "SLX"


def test_try_extract_boat_key_west_multiword_make_from_title_card() -> None:
    html = """
    <html><body>
      <a class="c-widget--vehicle" href="/inventory/key-west-1">
        2024 Key West Boats 203FS
      </a>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="Key West Boats",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Key West Boats"
    assert v.model == "203FS"


def test_try_extract_boat_axis_make_from_title_card() -> None:
    html = """
    <html><body>
      <a class="c-widget--vehicle" href="/inventory/axis-1">
        2024 Axis A225
      </a>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="Axis",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Axis"
    assert v.model == "A225"


def test_try_extract_boat_sea_pro_multiword_make_from_title_card() -> None:
    html = """
    <html><body>
      <a class="c-widget--vehicle" href="/inventory/sea-pro-1">
        2025 Sea Pro 245FLX
      </a>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="Sea Pro",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Sea Pro"
    assert v.model == "245FLX"


def test_try_extract_boat_key_west_without_boats_suffix() -> None:
    html = """
    <html><body>
      <a class="c-widget--vehicle" href="/inventory/key-west-2">
        2024 Key West 203FS
      </a>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/boats",
        html=html,
        make_filter="Key West",
        model_filter="",
        vehicle_category="boat",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Key West"
    assert v.model == "203FS"


def test_try_extract_applies_page_make_scope_for_make_filtered_inventory_pages() -> None:
    html = """
    <html><body>
      <div class="vehicle-card" data-year="2024" data-model="Envista" data-price="28000">
        <a href="/inventory/v1">2024 Envista Preferred</a>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/new-inventory/index.htm?make=Buick",
        html=html,
        make_filter="Buick",
        model_filter="",
    )
    assert result is not None
    assert len(result.vehicles) == 1
    v = result.vehicles[0]
    assert v.make == "Buick"
    assert v.model == "Envista"


def test_find_next_page_dealer_on_pt_query() -> None:
    html = '<html><body><a href="searchnew.aspx?pt=2" class="pagination__next">Next</a></body></html>'
    base = "https://dealer.example/searchnew.aspx?pt=1"
    nxt = find_next_page_url(html, base)
    assert nxt is not None
    assert "pt=2" in nxt


def test_find_next_page_inspire_p_param() -> None:
    html = '<html><body><a href="/new-vehicles?_p=2" class="pagination__next">Next</a></body></html>'
    base = "https://dealer.example/new-vehicles?_p=1"
    nxt = find_next_page_url(html, base)
    assert nxt is not None
    assert "_p=2" in nxt


def test_find_next_page_numbered_pn() -> None:
    html = (
        '<html><body>'
        '<a href="/inventory?pn=2">2</a>'
        "</body></html>"
    )
    base = "https://dealer.example/inventory?pn=1"
    nxt = find_next_page_url(html, base)
    assert nxt is not None
    assert "pn=2" in nxt


def test_try_extract_synthesizes_next_from_inventory_api_json() -> None:
    html = """
    <html><body>
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalPages":4,"pageSize":12,"vehicles":[]}
    </script>
    <div class="vehicle-card" data-year="2024" data-make="Ford" data-model="F-150" data-price="45000">
      <a href="/inventory/v1">2024 Ford F-150</a>
    </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/new-inventory/index.htm?page=1",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    assert result.next_page_url is not None
    assert "page=2" in result.next_page_url
    assert result.pagination is not None
    assert result.pagination.total_pages == 4
    assert result.pagination.page_size == 12


def test_try_extract_synthesizes_next_from_inventory_api_json_after_page_two() -> None:
    html = """
    <html><body>
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalPages":4,"pageSize":18,"vehicles":[]}
    </script>
    <div class="vehicle-card" data-year="2024" data-make="Subaru" data-model="Outback" data-price="38000">
      <a href="/inventory/v1">2024 Subaru Outback</a>
    </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/new-inventory/index.htm?page=2",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    assert result.next_page_url is not None
    assert "page=3" in result.next_page_url


def test_try_extract_synthesizes_next_from_inventory_api_total_without_page_size() -> None:
    html = """
    <html><body>
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalCount":18,"vehicles":[]}
    </script>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Envista" data-price="26000">
      <a href="/inventory/v1">2024 Buick Envista Preferred</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Envista" data-price="26100">
      <a href="/inventory/v2">2024 Buick Envista Sport Touring</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Encore GX" data-price="28000">
      <a href="/inventory/v3">2024 Buick Encore GX Preferred</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Encore GX" data-price="28100">
      <a href="/inventory/v4">2024 Buick Encore GX Sport Touring</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Enclave" data-price="42000">
      <a href="/inventory/v5">2024 Buick Enclave Essence</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Enclave" data-price="42100">
      <a href="/inventory/v6">2024 Buick Enclave Avenir</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Envision" data-price="39000">
      <a href="/inventory/v7">2024 Buick Envision Preferred</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Envision" data-price="39100">
      <a href="/inventory/v8">2024 Buick Envision Essence</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="Buick" data-model="Envista" data-price="26200">
      <a href="/inventory/v9">2024 Buick Envista Avenir</a>
    </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/new-inventory/index.htm?make=Buick",
        html=html,
        make_filter="Buick",
        model_filter="",
    )
    assert result is not None
    assert len(result.vehicles) == 9
    assert result.next_page_url is not None
    assert "page=2" in result.next_page_url
    assert result.pagination is not None
    assert result.pagination.total_results == 18
    assert result.pagination.page_size == 9
    assert result.pagination.total_pages == 2


def test_try_extract_synthesizes_pt_for_dealer_on_path() -> None:
    html = """
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalPages":3,"pageSize":12}
    </script>
    <div class="vehicle-card" data-make="Ford" data-model="Mustang" data-price="40000">
      <a href="/v/M1">2024 Ford Mustang</a>
    </div>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/searchnew.aspx?Make=Ford",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    assert result.next_page_url is not None
    assert "pt=2" in result.next_page_url


def test_try_extract_synthesizes_next_from_dom_summary_counts() -> None:
    html = """
    <html><body>
      <div>Showing 1-24 of 137 Results</div>
      <div class="vehicle-card" data-year="2024" data-make="Toyota" data-model="Camry" data-price="28000">
        <a href="/inventory/v1">2024 Toyota Camry LE</a>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/inventory?page=1",
        html=html,
        make_filter="",
        model_filter="",
    )
    assert result is not None
    assert result.next_page_url is not None
    assert "page=2" in result.next_page_url
    assert result.pagination is not None
    assert result.pagination.total_results == 137
    assert result.pagination.page_size == 24
    assert result.pagination.total_pages == 6


def test_try_extract_inventory_anchor_cards_for_harley_style_srp() -> None:
    html = """
    <html><body>
      <div>Showing 1 - 12 of 263 results</div>
      <section class="inventory-item">
        <h2>Used 2025 Harley-Davidson Tri Glide Ultra</h2>
        <a href="/inventory/959629/used-2025-harley-davidson-tri-glide-ultra/9307/form/3871">CLICK FOR PRICE</a>
        <div>U850174 4515 mi Mystic Shift - Black Finish</div>
        <div>$44,480 Now $34,877</div>
        <p>The Harley-Davidson Tri Glide Ultra is made for long-distance touring.</p>
        <a href="/inventory/959629/used-2025-harley-davidson-tri-glide-ultra">MORE INFO</a>
      </section>
      <section class="inventory-item">
        <h2>Used 2024 Harley-Davidson Road Glide 3</h2>
        <div>U850258 6793 mi Vivid Black</div>
        <div>$39,790 Now $28,977</div>
        <a href="/inventory/959636/used-2024-harley-davidson-road-glide-3">MORE INFO</a>
      </section>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/used-inventory",
        html=html,
        make_filter="Harley-Davidson",
        model_filter="",
        vehicle_category="motorcycle",
    )
    assert result is not None
    assert len(result.vehicles) == 2
    assert result.pagination is not None
    assert result.pagination.total_results == 263
    assert result.next_page_url is not None
    first = result.vehicles[0]
    assert first.year == 2025
    assert first.make == "Harley-Davidson"
    assert first.model is not None
    assert first.price == 34877
    assert first.mileage == 4515
    assert first.listing_url == "https://dealer.example/inventory/959629/used-2025-harley-davidson-tri-glide-ultra"


def test_try_extract_returns_empty_result_when_filters_miss_but_more_pages_exist() -> None:
    html = """
    <html><body>
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalPages":3,"pageSize":12,"vehicles":[]}
    </script>
    <div class="vehicle-card" data-year="2024" data-make="Honda" data-model="Civic" data-price="24000">
      <a href="/inventory/h1">2024 Honda Civic</a>
    </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/inventory?page=1",
        html=html,
        make_filter="Toyota",
        model_filter="Camry",
    )
    assert result is not None
    assert result.vehicles == []
    assert result.next_page_url is not None
    assert "page=2" in result.next_page_url
    assert result.pagination is not None
    assert result.pagination.total_pages == 3


def test_try_extract_uses_raw_page_vehicle_count_for_empty_filtered_page() -> None:
    html = """
    <html><body>
    <script type="application/json" data-ms-source="inventory-api">
    {"page":1,"totalCount":18,"vehicles":[]}
    </script>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Acadia" data-price="41000">
      <a href="/inventory/g1">2024 GMC Acadia Elevation</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Terrain" data-price="33000">
      <a href="/inventory/g2">2024 GMC Terrain SLE</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Terrain" data-price="33100">
      <a href="/inventory/g3">2024 GMC Terrain SLT</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Yukon" data-price="72000">
      <a href="/inventory/g4">2024 GMC Yukon Denali</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Canyon" data-price="47000">
      <a href="/inventory/g5">2024 GMC Canyon AT4</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Sierra 1500" data-price="61000">
      <a href="/inventory/g6">2024 GMC Sierra 1500 Elevation</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Sierra 1500" data-price="61100">
      <a href="/inventory/g7">2024 GMC Sierra 1500 AT4</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Hummer EV" data-price="98000">
      <a href="/inventory/g8">2024 GMC Hummer EV 2X</a>
    </div>
    <div class="vehicle-card" data-year="2024" data-make="GMC" data-model="Acadia" data-price="41100">
      <a href="/inventory/g9">2024 GMC Acadia Denali</a>
    </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/new-inventory/index.htm?make=Buick",
        html=html,
        make_filter="Buick",
        model_filter="",
    )
    assert result is not None
    assert result.vehicles == []
    assert result.next_page_url is not None
    assert "page=2" in result.next_page_url
    assert result.pagination is not None
    assert result.pagination.total_results == 18
    assert result.pagination.page_size == 9
    assert result.pagination.total_pages == 2


def test_try_extract_respects_make_filter() -> None:
    html = """
    <html><body>
      <div class="vehicle-card" data-year="2024" data-make="Honda" data-model="Civic" data-price="24000">
        <a href="/inventory/h1">2024 Honda Civic</a>
      </div>
    </body></html>
    """
    result = try_extract_vehicles_without_llm(
        page_url="https://dealer.example/inventory",
        html=html,
        make_filter="Toyota",
        model_filter="",
    )
    assert result is None
