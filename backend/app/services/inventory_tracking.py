from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_host(url: str) -> str:
    raw = _clean_text(url)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return raw.lower().removeprefix("www.")


def _normalized_url(url: str) -> str:
    raw = _clean_text(url)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
        return urlunsplit(
            (
                parsed.scheme.lower() or "https",
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                parsed.query,
                "",
            )
        )
    except Exception:
        return raw.rstrip("/").lower()


def inventory_history_key(listing: Any) -> str:
    website = _normalized_host(getattr(listing, "dealership_website", None) or getattr(listing, "website", None) or "")
    vin = _clean_text(getattr(listing, "vin", None)).upper()
    vehicle_identifier = _clean_text(getattr(listing, "vehicle_identifier", None)).upper()
    listing_url = _normalized_url(_clean_text(getattr(listing, "listing_url", None)))
    year = _clean_text(getattr(listing, "year", None))
    make = _clean_text(getattr(listing, "make", None)).lower()
    model = _clean_text(getattr(listing, "model", None)).lower()
    trim = _clean_text(getattr(listing, "trim", None)).lower()
    raw_title = _clean_text(getattr(listing, "raw_title", None)).lower()

    prefix = website or "unknown-dealer"
    if vin:
        return f"vin:{vin}"
    if vehicle_identifier:
        return f"{prefix}|id:{vehicle_identifier}"
    if listing_url:
        return f"{prefix}|url:{listing_url}"
    fallback = "|".join(part for part in (year, make, model, trim, raw_title) if part)
    return f"{prefix}|fallback:{fallback or 'unknown-vehicle'}"


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_listing_history_fields(
    record: Any,
    *,
    current_price: Any,
    observed_at: float | None = None,
    include_current_observation: bool = True,
) -> dict[str, Any]:
    current_price_value = _safe_float(current_price)
    previous_price = _safe_float(getattr(record, "previous_price", None))
    first_price = _safe_float(getattr(record, "first_price", None))
    latest_price = _safe_float(getattr(record, "latest_price", None))
    current_reference = current_price_value if current_price_value is not None else latest_price
    first_seen_at = getattr(record, "first_seen_at", None)
    last_seen_at = (
        float(observed_at)
        if include_current_observation and observed_at is not None
        else getattr(record, "last_seen_at", None)
    )

    days_tracked: int | None = None
    if first_seen_at is not None and last_seen_at is not None:
        days_tracked = max(0, int((float(last_seen_at) - float(first_seen_at)) // 86400))

    price_change = None
    if current_reference is not None and previous_price is not None:
        price_change = current_reference - previous_price

    price_change_since_first = None
    if current_reference is not None and first_price is not None:
        price_change_since_first = current_reference - first_price

    return {
        "history_seen_count": int(getattr(record, "seen_count", 0) or 0) + (1 if include_current_observation else 0),
        "history_first_seen_at": _iso(first_seen_at),
        "history_last_seen_at": _iso(last_seen_at),
        "history_days_tracked": days_tracked,
        "history_previous_price": previous_price,
        "history_lowest_price": _safe_float(getattr(record, "lowest_price", None)),
        "history_highest_price": _safe_float(getattr(record, "highest_price", None)),
        "history_price_change": price_change,
        "history_price_change_since_first": price_change_since_first,
        "price_history": list(getattr(record, "price_history", []) or []),
    }
