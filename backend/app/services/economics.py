"""Unit-economics signals for pricing and margin analysis.

These are *indicative* weighted units, not dollar costs — pair with your own
billing data (Places, ZenRows, OpenAI) for true unit economics.
"""

from __future__ import annotations

from typing import Any


def build_search_economics(
    *,
    fetch_metrics: dict[str, int],
    extraction_metrics: dict[str, int],
    requested_dealerships: int,
    requested_pages: int,
    radius_miles: int,
    duration_ms: int,
    vehicle_condition: str,
    inventory_scope: str,
    ok: bool,
) -> dict[str, Any]:
    """Derive a simple intensity score from observable search parameters and metrics."""
    fetch = dict(fetch_metrics)
    extract = dict(extraction_metrics)

    managed_hits = 0
    for k, v in fetch.items():
        kl = k.lower()
        if "zenrows" in kl or "scrapingbee" in kl or "playwright" in kl:
            managed_hits += int(v)

    llm_pages = int(extract.get("pages_llm", 0) or 0)
    llm_failed = int(extract.get("pages_llm_failed", 0) or 0)
    structured_pages = int(extract.get("pages_structured", 0) or 0)
    provider_pages = int(extract.get("pages_provider", 0) or 0)

    # Weights tuned to emphasize third-party fetch + LLM (typical cost drivers).
    cost_driver_units = (
        float(requested_dealerships) * 1.0
        + float(requested_pages) * 0.25
        + float(radius_miles) / 250.0
        + float(managed_hits) * 2.0
        + float(llm_pages) * 1.5
        + float(llm_failed) * 0.5
        + float(structured_pages) * 0.15
        + float(provider_pages) * 0.1
    )

    return {
        "cost_driver_units": round(cost_driver_units, 3),
        "duration_ms": int(duration_ms),
        "ok": bool(ok),
        "drivers": {
            "requested_dealerships": int(requested_dealerships),
            "requested_pages_per_dealer": int(requested_pages),
            "radius_miles": int(radius_miles),
            "vehicle_condition": vehicle_condition,
            "inventory_scope": inventory_scope,
            "managed_fetch_events": int(managed_hits),
            "pages_llm": llm_pages,
            "pages_llm_failed": llm_failed,
            "pages_structured": structured_pages,
            "pages_provider": provider_pages,
            "fetch_metrics": fetch,
            "extraction_metrics": extract,
        },
    }


def log_economics_line(logger: Any, economics: dict[str, Any], *, user_hint: str = "") -> None:
    """Structured log line for aggregation in your logging stack."""
    units = economics.get("cost_driver_units")
    dur = economics.get("duration_ms")
    logger.info(
        "search_economics cost=%s duration_ms=%s ok=%s %s",
        units,
        dur,
        economics.get("ok"),
        user_hint,
        extra={"economics": economics},
    )
