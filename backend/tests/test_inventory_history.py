from __future__ import annotations

from app.config import settings
from app.db.account_store import get_account_store
from app.schemas import VehicleListing
from app.services.inventory_tracking import build_listing_history_fields


def test_inventory_history_tracks_seen_count_and_price_changes() -> None:
    store = get_account_store(settings.accounts_db_path)
    user = store.create_user("history@example.com", "hunter22!!", tier="standard")

    first_listing = {
        "dealership": "Seattle BMW",
        "dealership_website": "https://www.example-bmw.com",
        "vin": "3VVVC7B25SM037020",
        "vehicle_identifier": "3VVVC7B25SM037020",
        "listing_url": "https://www.example-bmw.com/inventory/3VVVC7B25SM037020",
        "raw_title": "2025 Volkswagen Taos SEL",
        "price": 32000,
        "days_on_lot": 7,
    }
    second_listing = {
        **first_listing,
        "price": 31500,
        "days_on_lot": 12,
    }

    store.record_inventory_history(user.id, scrape_run_id="run-1", listings=[first_listing], observed_at=1_700_000_000.0)
    store.record_inventory_history(user.id, scrape_run_id="run-2", listings=[second_listing], observed_at=1_700_000_000.0 + 86400 * 5)

    history_map = store.get_inventory_history_map(
        user.id,
        [
            VehicleListing(
                vehicle_category="car",
                vin="3VVVC7B25SM037020",
                vehicle_identifier="3VVVC7B25SM037020",
                listing_url="https://www.example-bmw.com/inventory/3VVVC7B25SM037020",
            )
        ],
    )
    assert len(history_map) == 1
    history = next(iter(history_map.values()))
    assert history.seen_count == 2
    assert history.latest_price == 31500
    assert history.previous_price == 32000
    assert history.lowest_price == 31500
    assert history.highest_price == 32000
    assert history.latest_days_on_lot == 12
    assert len(history.price_history) == 2

    fields = build_listing_history_fields(
        history,
        current_price=31500,
        observed_at=1_700_000_000.0 + 86400 * 5,
        include_current_observation=False,
    )
    assert fields["history_seen_count"] == 2
    assert fields["history_days_tracked"] == 5
    assert fields["history_price_change"] == -500
    assert fields["history_price_change_since_first"] == -500
