from app.services.inventory_filters import infer_vehicle_condition_from_page


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
