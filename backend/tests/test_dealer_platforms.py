import json

from app.services.dealer_platforms import zenrows_inventory_js_instructions_for_url

_ZENROWS_JS_INSTRUCTIONS_WAIT_LIMIT_MS = 30_000


def test_oneaudi_js_instructions_match_audi_birmingham_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.audibirminghammi.com/en/inventory/new/"
    )
    assert instructions is not None
    steps = json.loads(instructions)

    total_wait_ms = sum(step.get("wait", 0) for step in steps if isinstance(step.get("wait"), int))
    assert total_wait_ms < _ZENROWS_JS_INSTRUCTIONS_WAIT_LIMIT_MS, (
        f"Total js_instructions wait {total_wait_ms}ms exceeds ZenRows 30s cap (REQS004)"
    )

    assert len(steps) >= 30
    assert len(instructions) < 2500
    assert steps[0]["evaluate"].startswith("window.__zrClickMore=()=>")
    assert sum(1 for step in steps if step.get("evaluate") == "window.__zrClickMore&&window.__zrClickMore()") >= 6


def test_oneaudi_js_instructions_do_not_match_non_audi_inventory_url() -> None:
    instructions = zenrows_inventory_js_instructions_for_url(
        "https://www.example-subaru.com/inventory/new/"
    )
    assert instructions is None
