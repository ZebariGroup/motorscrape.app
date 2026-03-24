"""Shared make/model matching for listings (used by orchestrator and structured extraction)."""

from __future__ import annotations

import re

from app.schemas import VehicleListing


def model_filter_variants(model: str) -> list[str]:
    """Substrings to match user model input (F-150 / F150 / F 150)."""
    raw = model.strip().lower()
    if not raw:
        return []
    variants: set[str] = {raw}
    alnum = re.sub(r"[^a-z0-9]", "", raw)
    if alnum:
        variants.add(alnum)
    m = re.match(r"^([a-z]+)(\d[\w]*)$", alnum)
    if m:
        prefix, rest = m.group(1), m.group(2)
        variants.add(f"{prefix}-{rest}")
        variants.add(f"{prefix} {rest}")
    return sorted(variants, key=len, reverse=True)


def listing_matches_filters(v: VehicleListing, make_f: str, model_f: str) -> bool:
    make_f = make_f.strip().lower()
    model_f = model_f.strip()
    if not make_f and not model_f:
        return True
    blob = " ".join(
        filter(None, [v.make or "", v.model or "", v.trim or "", v.raw_title or ""])
    ).lower()
    if make_f and make_f not in blob:
        return False
    if model_f:
        vars_ = model_filter_variants(model_f)
        if vars_ and not any(x in blob for x in vars_):
            return False
    return True
