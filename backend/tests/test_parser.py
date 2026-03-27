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
