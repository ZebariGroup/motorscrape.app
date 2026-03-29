from __future__ import annotations

from app.db.account_store import ScrapeEventRecord
from app.services.search_log_summary import build_dealer_outcomes, summarize_dealer_outcomes


def test_build_dealer_outcomes_flags_ford_zero_result_warning() -> None:
    events = [
        ScrapeEventRecord(
            id="1",
            scrape_run_id="run-1",
            correlation_id="srch-ford1",
            sequence_no=1,
            event_type="dealer_done",
            phase="scrape",
            level="warning",
            message="Finished dealership scrape for Chula Vista Ford.",
            dealership_name="Chula Vista Ford",
            dealership_website="https://www.chulavistaford.com/",
            payload={
                "listings_found": 0,
                "platform_id": "ford_family_inventory",
                "platform_source": "detected",
                "strategy_used": "structured_html",
                "current_url": "https://www.chulavistaford.com/inventory/new/ford-bronco",
                "fetch_methods": ["direct", "playwright"],
                "ford_recovery_urls": ["https://www.chulavistaford.com/inventory/new/ford/bronco"],
                "zero_results_warning": "ford_family_scoped_url_empty",
            },
            created_at=0.0,
        )
    ]

    outcomes = build_dealer_outcomes(events)

    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "warning"
    assert outcomes[0]["classification"] == "scoped_url_empty"
    assert outcomes[0]["platform_id"] == "ford_family_inventory"
    assert outcomes[0]["ford_recovery_urls"] == ["https://www.chulavistaford.com/inventory/new/ford/bronco"]


def test_summarize_dealer_outcomes_counts_success_and_failures() -> None:
    events = [
        ScrapeEventRecord(
            id="1",
            scrape_run_id="run-1",
            correlation_id="srch-ford2",
            sequence_no=1,
            event_type="dealer_done",
            phase="scrape",
            level="info",
            message="Finished dealership scrape for Perry Ford.",
            dealership_name="Perry Ford",
            dealership_website="https://www.perryfordonline.com/",
            payload={
                "listings_found": 41,
                "platform_id": "ford_family_inventory",
                "current_url": "https://www.perryfordonline.com/inventory/new/ford-bronco",
            },
            created_at=0.0,
        ),
        ScrapeEventRecord(
            id="2",
            scrape_run_id="run-1",
            correlation_id="srch-ford2",
            sequence_no=2,
            event_type="dealer_error",
            phase="scrape",
            level="warning",
            message="All fetch methods failed for https://www.mossyford.com/inventory/new/ford-bronco: direct: 403",
            dealership_name="Mossy Ford",
            dealership_website="https://www.mossyford.com/",
            payload={"current_url": "https://www.mossyford.com/inventory/new/ford-bronco"},
            created_at=0.0,
        ),
    ]

    summary = summarize_dealer_outcomes(build_dealer_outcomes(events))

    assert summary["total_dealers"] == 2
    assert summary["status_counts"]["success"] == 1
    assert summary["status_counts"]["failed"] == 1
    assert summary["classification_counts"]["fetch_failure"] == 1
    assert summary["ford_family_dealers"] == 1
