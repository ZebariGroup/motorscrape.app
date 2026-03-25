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


def test_find_next_page_dealer_on_pt_query() -> None:
    html = '<html><body><a href="searchnew.aspx?pt=2" class="pagination__next">Next</a></body></html>'
    base = "https://dealer.example/searchnew.aspx?pt=1"
    nxt = find_next_page_url(html, base)
    assert nxt is not None
    assert "pt=2" in nxt


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
