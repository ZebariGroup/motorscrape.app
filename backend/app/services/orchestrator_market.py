"""Market valuation helpers used by the search orchestrator."""

from __future__ import annotations

import re
from typing import Any

from app.schemas import VehicleListing


def _mv_norm(value: Any) -> str:
    return str(value or "").strip().lower()


_MV_TRIM_SIGNATURE_STOPWORDS: frozenset[str] = frozenset(
    {
        "package",
        "packages",
        "pkg",
        "edition",
        "series",
        "trim",
        "style",
        "styles",
        "door",
        "doors",
        "sedan",
        "coupe",
        "convertible",
        "hatchback",
        "wagon",
        "suv",
        "truck",
        "van",
        "automatic",
        "manual",
        "auto",
        "speed",
        "speeds",
        "awd",
        "fwd",
        "rwd",
        "4wd",
        "4x4",
        "2wd",
        "xdrive",
        "quattro",
        "4matic",
        "cvt",
        "dct",
    }
)


def _mv_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = _mv_norm(value)
        if not text:
            continue
        for token in re.split(r"[^a-z0-9]+", text):
            token = token.strip()
            if len(token) >= 2:
                tokens.add(token)
    return tokens


def _mv_overlap_ratio(base: set[str], candidate: set[str]) -> float:
    if not base or not candidate:
        return 0.0
    overlap = sum(1 for token in base if token in candidate)
    return overlap / float(len(base))


def _mv_trim_signature_tokens(*, make: Any, model: Any, trim: Any, raw_title: Any) -> set[str]:
    make_tokens = _mv_tokens(make)
    model_tokens = _mv_tokens(model)
    tokens: set[str] = set()
    for token in _mv_tokens(trim, raw_title):
        if token in make_tokens or token in model_tokens or token in _MV_TRIM_SIGNATURE_STOPWORDS:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        tokens.add(token)
    return tokens


def _mv_has_trim_package_conflict(base: VehicleListing, candidate: dict[str, Any]) -> bool:
    base_trim = _mv_norm(base.trim)
    candidate_trim = _mv_norm(candidate.get("trim"))
    if base_trim and candidate_trim and base_trim == candidate_trim:
        return False
    base_signature = _mv_trim_signature_tokens(
        make=base.make,
        model=base.model,
        trim=base.trim,
        raw_title=base.raw_title,
    )
    candidate_signature = _mv_trim_signature_tokens(
        make=candidate.get("make"),
        model=candidate.get("model"),
        trim=candidate.get("trim"),
        raw_title=candidate.get("raw_title"),
    )
    if not base_signature and not candidate_signature:
        return False
    if not base_signature or not candidate_signature:
        return True
    return base_signature != candidate_signature


def _mv_similarity(base: VehicleListing, candidate: dict[str, Any]) -> float:
    candidate_features = candidate.get("feature_highlights")
    if not isinstance(candidate_features, list):
        candidate_features = [candidate_features] if candidate_features else []
    base_tokens = _mv_tokens(
        base.trim,
        base.body_style,
        base.drivetrain,
        base.engine,
        base.transmission,
        base.fuel_type,
        *(base.feature_highlights or []),
    )
    candidate_tokens = _mv_tokens(
        candidate.get("trim"),
        candidate.get("body_style"),
        candidate.get("drivetrain"),
        candidate.get("engine"),
        candidate.get("transmission"),
        candidate.get("fuel_type"),
        *candidate_features,
    )
    score = _mv_overlap_ratio(base_tokens, candidate_tokens)
    if _mv_norm(base.trim) and _mv_norm(base.trim) == _mv_norm(candidate.get("trim")):
        score += 0.2
    if _mv_norm(base.drivetrain) and _mv_norm(base.drivetrain) == _mv_norm(candidate.get("drivetrain")):
        score += 0.1
    if _mv_norm(base.body_style) and _mv_norm(base.body_style) == _mv_norm(candidate.get("body_style")):
        score += 0.1
    return score


def _listing_market_identity_tokens(listing: VehicleListing) -> tuple[str, str, str]:
    vin = str(listing.vin or "").strip().upper()
    vehicle_identifier = str(listing.vehicle_identifier or "").strip().upper()
    listing_url = str(listing.listing_url or "").strip().lower()
    return vin, vehicle_identifier, listing_url


def market_valuation_enabled_for_listing(listing: VehicleListing) -> bool:
    return _mv_norm(listing.vehicle_condition) == "new"


def historical_market_points_for_listing(
    listing: VehicleListing,
    historical_pool: list[dict[str, Any]],
    *,
    max_prices: int = 40,
) -> list[dict[str, float]]:
    if not market_valuation_enabled_for_listing(listing):
        return []
    base_make = _mv_norm(listing.make)
    base_model = _mv_norm(listing.model)
    base_category = _mv_norm(listing.vehicle_category)
    if not base_make or not base_model:
        return []
    base_condition = _mv_norm(listing.vehicle_condition)
    base_vin, base_identifier, base_url = _listing_market_identity_tokens(listing)
    ranked: list[tuple[float, float, float | None]] = []
    for candidate in historical_pool:
        try:
            price_value = float(candidate.get("price"))
        except (TypeError, ValueError):
            continue
        if price_value <= 0:
            continue
        if _mv_norm(candidate.get("make")) != base_make:
            continue
        if _mv_norm(candidate.get("model")) != base_model:
            continue
        candidate_category = _mv_norm(candidate.get("vehicle_category"))
        if base_category and candidate_category and candidate_category != base_category:
            continue
        candidate_condition = _mv_norm(candidate.get("vehicle_condition"))
        if base_condition and candidate_condition and candidate_condition != base_condition:
            continue
        if listing.year is not None and candidate.get("year") is not None:
            try:
                if abs(int(candidate.get("year")) - int(listing.year)) > 1:
                    continue
            except (TypeError, ValueError):
                pass

        candidate_vin = str(candidate.get("vin") or "").strip().upper()
        candidate_identifier = str(candidate.get("vehicle_identifier") or "").strip().upper()
        candidate_url = str(candidate.get("listing_url") or "").strip().lower()
        if (base_vin and candidate_vin and base_vin == candidate_vin) or (
            base_identifier and candidate_identifier and base_identifier == candidate_identifier
        ):
            continue
        if base_url and candidate_url and base_url == candidate_url:
            continue
        if _mv_has_trim_package_conflict(listing, candidate):
            continue

        score = _mv_similarity(listing, candidate)
        if score < 0.15:
            continue
        observed_at: float | None = None
        observed_raw = candidate.get("_market_observed_at")
        try:
            if observed_raw is not None:
                observed_at = float(observed_raw)
        except (TypeError, ValueError):
            observed_at = None
        ranked.append((score, price_value, observed_at))

    if not ranked:
        return []
    ranked.sort(key=lambda item: item[0], reverse=True)
    points: list[dict[str, float]] = []
    for _, price, observed_at in ranked[:max_prices]:
        point: dict[str, float] = {"price": float(price)}
        if observed_at is not None and observed_at > 0:
            point["observed_at"] = observed_at
        points.append(point)
    return points
