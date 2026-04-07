from __future__ import annotations

from collections import Counter
from typing import Any

from app.db.account_store import ScrapeEventRecord


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _dealership_key(record: ScrapeEventRecord) -> str | None:
    website = _norm_text(record.dealership_website)
    if website:
        return website.lower()
    name = _norm_text(record.dealership_name)
    if name:
        return name.lower()
    return None


def _classify_error(record: ScrapeEventRecord) -> str:
    message = _norm_text(record.message).lower()
    phase = _norm_text(record.phase).lower()
    payload = record.payload if isinstance(record.payload, dict) else {}
    payload_blob = " ".join(str(value) for value in payload.values()).lower()
    haystack = f"{message} {payload_blob}".strip()
    if record.event_type == "dealer_timeout" or "timed out" in haystack:
        return "timeout"
    if phase == "parse":
        return "parse_failure"
    if any(token in haystack for token in ("all fetch methods failed", "403", "blocked", "captcha", "cloudflare", "akamai", "denied")):
        return "fetch_failure"
    return "scrape_failure"


def _error_code_from_payload(payload: dict[str, Any]) -> str | None:
    nested = payload.get("error")
    if isinstance(nested, dict):
        code = _norm_text(nested.get("code"))
        if code:
            return code
    return _norm_text(payload.get("error_code")) or None


def _counted_fetch_methods(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        normalized = _norm_text(item)
        if normalized:
            out.append(normalized)
    return out


def build_dealer_outcomes(events: list[ScrapeEventRecord]) -> list[dict[str, Any]]:
    outcomes: dict[str, dict[str, Any]] = {}
    for record in events:
        key = _dealership_key(record)
        if not key:
            continue
        payload = record.payload if isinstance(record.payload, dict) else {}
        outcome = outcomes.setdefault(
            key,
            {
                "dealership_name": record.dealership_name,
                "dealership_website": record.dealership_website,
                "status": "in_progress",
                "classification": "in_progress",
                "platform_id": None,
                "platform_source": None,
                "strategy_used": None,
                "listings_found": 0,
                "final_url": None,
                "fetch_methods": [],
                "ford_recovery_urls": [],
                "zero_results_warning": None,
                "error_phase": None,
                "error_message": None,
                "error_code": None,
            },
        )
        if record.dealership_name and not outcome["dealership_name"]:
            outcome["dealership_name"] = record.dealership_name
        if record.dealership_website and not outcome["dealership_website"]:
            outcome["dealership_website"] = record.dealership_website
        if payload.get("platform_id"):
            outcome["platform_id"] = payload.get("platform_id")
        if payload.get("platform_source"):
            outcome["platform_source"] = payload.get("platform_source")
        if payload.get("strategy_used"):
            outcome["strategy_used"] = payload.get("strategy_used")
        if payload.get("fetch_method") and not outcome["fetch_methods"]:
            outcome["fetch_methods"] = [_norm_text(payload.get("fetch_method"))]
        if payload.get("current_url"):
            outcome["final_url"] = payload.get("current_url")
        fetch_methods = _counted_fetch_methods(payload.get("fetch_methods"))
        if fetch_methods:
            outcome["fetch_methods"] = fetch_methods
        recovery_urls = payload.get("ford_recovery_urls")
        if isinstance(recovery_urls, list) and recovery_urls:
            deduped: list[str] = []
            seen: set[str] = set()
            for url in recovery_urls:
                value = _norm_text(url)
                if value and value not in seen:
                    seen.add(value)
                    deduped.append(value)
            outcome["ford_recovery_urls"] = deduped
        if payload.get("zero_results_warning"):
            outcome["zero_results_warning"] = payload.get("zero_results_warning")

        if record.event_type == "dealer_done":
            listings_found = int(payload.get("listings_found") or 0)
            outcome["listings_found"] = listings_found
            if payload.get("zero_results_warning"):
                outcome["status"] = "warning"
                outcome["classification"] = "scoped_url_empty"
                outcome["error_code"] = _norm_text(payload.get("zero_results_warning")) or "warning.scoped_url_empty"
            elif listings_found <= 0:
                outcome["status"] = "warning"
                outcome["classification"] = "zero_results"
                outcome["error_code"] = "warning.zero_results"
            else:
                outcome["status"] = "success"
                outcome["classification"] = "success"
                outcome["error_phase"] = None
                outcome["error_message"] = None
                outcome["error_code"] = None
            continue

        if record.event_type in {"dealer_error", "dealer_timeout"}:
            outcome["status"] = "failed"
            outcome["classification"] = _classify_error(record)
            outcome["error_phase"] = record.phase
            outcome["error_message"] = record.message
            outcome["error_code"] = _error_code_from_payload(payload) or outcome["classification"]

    ordered = sorted(
        outcomes.values(),
        key=lambda item: (
            str(item.get("dealership_name") or item.get("dealership_website") or "").lower(),
            str(item.get("dealership_website") or ""),
        ),
    )
    return ordered


def summarize_dealer_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(item.get("status") or "unknown") for item in outcomes)
    classification_counts = Counter(str(item.get("classification") or "unknown") for item in outcomes)
    error_code_counts = Counter(str(item.get("error_code") or "unknown") for item in outcomes if item.get("error_code"))
    failed_platform_counts = Counter(
        str(item.get("platform_id") or "unknown") for item in outcomes if str(item.get("status") or "") == "failed"
    )
    failed_fetch_method_counts: Counter[str] = Counter()
    for item in outcomes:
        if str(item.get("status") or "") != "failed":
            continue
        methods = item.get("fetch_methods")
        if not isinstance(methods, list):
            continue
        for method in methods:
            normalized = _norm_text(method)
            if normalized:
                failed_fetch_method_counts[normalized] += 1
    return {
        "total_dealers": len(outcomes),
        "status_counts": dict(status_counts),
        "classification_counts": dict(classification_counts),
        "error_code_counts": dict(error_code_counts),
        "failed_platform_counts": dict(failed_platform_counts),
        "failed_fetch_method_counts": dict(failed_fetch_method_counts),
        "zero_results_warnings": sum(1 for item in outcomes if item.get("zero_results_warning")),
        "ford_family_dealers": sum(1 for item in outcomes if item.get("platform_id") == "ford_family_inventory"),
    }
