from app.services.inventory_discovery import _is_inventory_like_url


def test_is_inventory_like_url_accepts_real_inventory_paths() -> None:
    assert _is_inventory_like_url("https://dealer.example/new-vehicles/")
    assert _is_inventory_like_url("https://dealer.example/inventory/new/chevrolet-blazer")


def test_is_inventory_like_url_rejects_promo_preowned_landings() -> None:
    assert not _is_inventory_like_url("https://www.chevrolettijuana.com.mx/promociones/landing-pre-owned")
    assert not _is_inventory_like_url("https://dealer.example/offers/pre-owned-specials")
