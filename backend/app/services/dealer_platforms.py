"""Lightweight fingerprinting for common dealership website vendors + extra JSON-LD harvest."""

from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PLATFORM_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("dealer_dot_com", ("dealer.com", "coxautoinc", "dealerdotcom")),
    ("dealer_on", ("dealeron.com", "dealeron", "cdn.dealeron")),
    ("dealer_inspire", ("dealerinspire.com", "dealer-inspire", "dealerinspire")),
]


def detect_platform(html: str) -> str | None:
    lower = html.lower()
    for pid, needles in _PLATFORM_MARKERS:
        if any(n in lower for n in needles):
            return pid
    return None


def _walk_ld_json_vehicle_objects(obj: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        types = obj.get("@type")
        type_list: list[str] = []
        if isinstance(types, str):
            type_list = [types.lower()]
        elif isinstance(types, list):
            type_list = [str(t).lower() for t in types if t]
        if any(t in ("vehicle", "car", "product") for t in type_list):
            if obj.get("vehicleIdentificationNumber") or obj.get("model") or obj.get("name"):
                out.append(obj)
        for v in obj.values():
            _walk_ld_json_vehicle_objects(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_ld_json_vehicle_objects(item, out, depth + 1)


def extract_json_ld_vehicle_dicts(html: str) -> list[dict]:
    """Collect schema.org-style vehicle/product objects from application/ld+json scripts."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for script in soup.find_all("script"):
        st = (script.get("type") or "").lower()
        if "ld+json" not in st:
            continue
        raw = script.string or ""
        if len(raw) < 50:
            continue
        try:
            blob = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        _walk_ld_json_vehicle_objects(blob, out)
    return out


def provider_enriched_vehicle_dicts(html: str, page_url: str) -> list[dict] | None:
    """
    If a known platform is detected, return extra vehicle-shaped dicts from JSON-LD.
    Returns None if no known platform (caller uses generic extraction).
    """
    pid = detect_platform(html)
    if not pid:
        return None
    records = extract_json_ld_vehicle_dicts(html)
    if not records:
        logger.debug("Platform %s detected for %s but no JSON-LD vehicles found", pid, page_url)
        return []
    logger.info("Platform %s: %d JSON-LD vehicle record(s) for %s", pid, len(records), page_url)
    return records
