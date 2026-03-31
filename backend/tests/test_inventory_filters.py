from app.schemas import VehicleListing
from app.services.inventory_filters import (
    apply_eu_make_default_from_dealer_context,
    infer_vehicle_condition_from_page,
    listing_matches_filters,
    make_filter_variants,
    text_mentions_make,
)


def test_infer_vehicle_condition_from_inventory_new_path() -> None:
    assert (
        infer_vehicle_condition_from_page(
            "https://www.audirochesterhills.com/en/inventory/new/",
            "",
        )
        == "new"
    )


def test_infer_vehicle_condition_from_inventory_used_path() -> None:
    assert (
        infer_vehicle_condition_from_page(
            "https://www.exampledealer.com/en/inventory/used/",
            "",
        )
        == "used"
    )


def test_infer_vehicle_condition_from_query_params() -> None:
    assert (
        infer_vehicle_condition_from_page(
            "https://www.carteracura.com/search/new-acura-lynnwood-wa/?s:df=1&cy=98036&tp=new",
            "",
        )
        == "new"
    )


def test_make_filter_variants_include_common_aliases() -> None:
    assert "BMW" in make_filter_variants("BMW Motorrad")
    assert "Indian" in make_filter_variants("Indian Motorcycle")
    assert "Yamaha" in make_filter_variants("Yamaha Boats")


def test_text_mentions_make_matches_aliases() -> None:
    assert text_mentions_make("Factory authorized BMW dealer", "BMW Motorrad")
    assert text_mentions_make("Shop Indian bikes", "Indian Motorcycle")
    assert text_mentions_make("Yamaha jet boats in stock", "Yamaha Boats")
    assert text_mentions_make("2026 Can-Am® Outlander", "canham")


def test_listing_matches_filters_uses_make_aliases() -> None:
    listing = VehicleListing(
        year=2024,
        make="BMW",
        model="R 1300 GS",
        raw_title="2024 BMW R 1300 GS",
        listing_url="https://example.test/listing/1",
    )
    assert listing_matches_filters(listing, "BMW Motorrad", "")


def test_apply_eu_make_default_from_dealer_context_uses_domain() -> None:
    listing = VehicleListing(
        year=2024,
        make=None,
        model="Golf",
        raw_title="Golf 2.0 TDI",
        listing_url="https://example.test/vdp/1",
    )
    out = apply_eu_make_default_from_dealer_context(
        listing,
        requested_make="Volkswagen",
        dealer_domain="mahag-volkswagen.de",
        dealer_name="MAHAG Group",
        market_region="eu",
    )
    assert out.make == "Volkswagen"


def test_apply_eu_make_default_from_dealer_context_uses_dealer_name_when_domain_missing_make() -> None:
    listing = VehicleListing(
        year=2024,
        make=None,
        model="Tiguan",
        raw_title="Tiguan Life",
        listing_url="https://example.test/vdp/2",
    )
    out = apply_eu_make_default_from_dealer_context(
        listing,
        requested_make="Volkswagen",
        dealer_domain="loehrgruppe.de",
        dealer_name="Volkswagen Zentrum Mainz Auto-Kraft GmbH",
        market_region="eu",
    )
    assert out.make == "Volkswagen"
