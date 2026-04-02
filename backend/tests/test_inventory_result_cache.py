"""Tests for SQLite-backed inventory listings cache."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app.services.inventory_result_cache as inventory_cache
import pytest


def test_inventory_listings_cache_key_stable() -> None:
    k1 = inventory_cache.inventory_listings_cache_key(
        website="https://Dealer.Example/Inventory/",
        domain="dealer.example",
        make="Honda",
        model="Accord",
        vehicle_category="car",
        vehicle_condition="new",
        inventory_scope="all",
        max_pages=3,
    )
    k2 = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="honda",
        model="ACCORD",
        vehicle_category="car",
        vehicle_condition="new",
        inventory_scope="all",
        max_pages=3,
    )
    assert k1 == k2


def test_inventory_listings_cache_key_bumps_harley_namespace() -> None:
    generic = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Honda",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=3,
    )
    harley = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Harley-Davidson",
        model="",
        vehicle_category="motorcycle",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=3,
    )
    assert generic != harley


def test_inventory_listings_cache_key_varies_by_vehicle_category() -> None:
    motorcycle = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Honda",
        model="Rebel 500",
        vehicle_category="motorcycle",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=3,
    )
    boat = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Honda",
        model="Rebel 500",
        vehicle_category="boat",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=3,
    )
    assert motorcycle != boat


def test_inventory_cache_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "inv.sqlite3"
    monkeypatch.setattr(
        inventory_cache,
        "settings",
        SimpleNamespace(
            inventory_cache_enabled=True,
            inventory_cache_path=str(db),
            inventory_cache_ttl_seconds=3600,
        ),
    )
    key = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Honda",
        model="Accord",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=3,
    )
    assert inventory_cache.get_cached_inventory_listings(key) is None
    payload = {"listings": [{"vin": "VIN1"}], "platform_id": "dealer_com"}
    inventory_cache.set_cached_inventory_listings(key, payload)
    assert inventory_cache.get_cached_inventory_listings(key) == payload


def test_family_inventory_cache_ignores_partial_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "inv.sqlite3"
    monkeypatch.setattr(
        inventory_cache,
        "settings",
        SimpleNamespace(
            inventory_cache_enabled=True,
            inventory_cache_path=str(db),
            inventory_cache_ttl_seconds=3600,
        ),
    )
    key = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Acura",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=10,
    )
    payload = {
        "listings": [{"vin": f"VIN{i}"} for i in range(5)],
        "platform_id": "honda_acura_inventory",
    }
    inventory_cache.set_cached_inventory_listings(key, payload)
    assert inventory_cache.get_cached_inventory_listings(key) is None


def test_non_family_inventory_cache_keeps_small_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = tmp_path / "inv.sqlite3"
    monkeypatch.setattr(
        inventory_cache,
        "settings",
        SimpleNamespace(
            inventory_cache_enabled=True,
            inventory_cache_path=str(db),
            inventory_cache_ttl_seconds=3600,
        ),
    )
    key = inventory_cache.inventory_listings_cache_key(
        website="https://dealer.example/inventory",
        domain="dealer.example",
        make="Mazda",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=10,
    )
    payload = {"listings": [{"vin": "VIN1"}], "platform_id": "dealer_com"}
    inventory_cache.set_cached_inventory_listings(key, payload)
    assert inventory_cache.get_cached_inventory_listings(key) == payload


def test_inventory_cache_expires(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "inv.sqlite3"
    monkeypatch.setattr(
        inventory_cache,
        "settings",
        SimpleNamespace(
            inventory_cache_enabled=True,
            inventory_cache_path=str(db),
            inventory_cache_ttl_seconds=60,
        ),
    )

    class Clock:
        t = 0.0

    monkeypatch.setattr(inventory_cache.time, "time", lambda: Clock.t)

    key = inventory_cache.inventory_listings_cache_key(
        website="https://x.example/",
        domain="x.example",
        make="",
        model="",
        vehicle_category="car",
        vehicle_condition="all",
        inventory_scope="all",
        max_pages=1,
    )
    Clock.t = 0.0
    inventory_cache.set_cached_inventory_listings(key, {"listings": [], "platform_id": None})
    Clock.t = 30.0
    assert inventory_cache.get_cached_inventory_listings(key) is not None
    Clock.t = 61.0
    assert inventory_cache.get_cached_inventory_listings(key) is None
