import json

from app.services.dealer_platforms import zenrows_inventory_js_instructions_for_url


def test_oneaudi_js_instructions_match_audi_birmingham_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.audibirminghammi.com/en/inventory/new/"
    )
    assert instructions is not None
    steps = json.loads(instructions)
    evaluate_steps = [step["evaluate"] for step in steps if "evaluate" in step]
    assert len(steps) >= 40
    assert any("load more" in script.lower() for script in evaluate_steps)


def test_oneaudi_js_instructions_do_not_match_non_audi_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.example-subaru.com/inventory/new/"
    )
    assert instructions is None
