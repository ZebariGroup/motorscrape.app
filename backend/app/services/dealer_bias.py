"""Heuristics for biasing dealer discovery toward smaller dealers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_MAJOR_GROUP_HINTS: tuple[str, ...] = (
    "autonation",
    "lithia",
    "group 1 automotive",
    "penske",
    "asbury",
    "hendrick",
    "sonic automotive",
    "carmax",
    "carvana",
    "driveway",
)

_CORPORATE_DEALER_HINTS: tuple[str, ...] = (
    "automotive group",
    "dealer group",
    "auto group",
    "auto mall",
    "motor group",
    "superstore",
    "super center",
    "supercenter",
)

_INDEPENDENT_DEALER_HINTS: tuple[str, ...] = (
    "auto sales",
    "used cars",
    "pre owned",
    "pre-owned",
    "motorcars",
    "motors",
    "imports",
    "cars ltd",
    "cars llc",
)

_OEM_BRAND_TOKENS: tuple[str, ...] = (
    "acura",
    "audi",
    "bmw",
    "buick",
    "cadillac",
    "chevrolet",
    "chrysler",
    "dodge",
    "fiat",
    "ford",
    "gmc",
    "honda",
    "hyundai",
    "infiniti",
    "jeep",
    "kia",
    "lexus",
    "lincoln",
    "mazda",
    "mercedes",
    "mini",
    "mitsubishi",
    "nissan",
    "ram",
    "smart",
    "subaru",
    "toyota",
    "volkswagen",
    "volvo",
)


def _normalized_host(url: str) -> str:
    host = urlsplit(url or "").netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _contains_token(text: str, token: str) -> bool:
    token = token.strip().lower()
    if not token:
        return False
    if " " in token or "." in token:
        return token in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text))


def dealer_preference_bias(name: str, website: str | None, *, search_make: str = "") -> int:
    """
    Positive values favor likely independents. Negative values penalize obvious
    franchise groups and major chains when smaller-dealer bias is enabled.
    """

    hay = " ".join(filter(None, [name, website or ""])).strip().lower()
    if not hay:
        return 0

    score = 0
    if any(_contains_token(hay, token) for token in _MAJOR_GROUP_HINTS):
        score -= 8
    if any(_contains_token(hay, token) for token in _CORPORATE_DEALER_HINTS):
        score -= 4

    host = _normalized_host(website or "")
    brand_hits = sum(1 for token in _OEM_BRAND_TOKENS if _contains_token(hay, token))
    search_make_norm = (search_make or "").strip().lower()
    if brand_hits >= 2:
        score -= 5
    elif brand_hits == 1:
        score -= 3 if search_make_norm and not _contains_token(hay, search_make_norm) else 1

    if host.count("-") >= 3 and brand_hits > 0:
        score -= 2

    if any(_contains_token(hay, token) for token in _INDEPENDENT_DEALER_HINTS):
        score += 3
    if "independent" in hay:
        score += 2
    if brand_hits == 0 and host and not any(_contains_token(host, token) for token in _MAJOR_GROUP_HINTS):
        score += 1

    return max(-10, min(6, score))
