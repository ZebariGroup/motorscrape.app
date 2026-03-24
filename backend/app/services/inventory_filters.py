"""Shared make/model matching for listings (used by orchestrator and structured extraction)."""

from __future__ import annotations

import re

from app.schemas import VehicleListing


_USED_CONDITION_RE = re.compile(r"\b(used|pre[\s-]?owned|cpo|certified)\b", re.I)
_NEW_CONDITION_RE = re.compile(r"\bnew\b", re.I)


def normalize_model_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.strip().lower())


def normalize_vehicle_condition(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if "usedcondition" in text:
        return "used"
    if "newcondition" in text:
        return "new"
    if _USED_CONDITION_RE.search(text):
        return "used"
    if _NEW_CONDITION_RE.search(text):
        return "new"
    return None


def infer_vehicle_condition_from_page(page_url: str, html: str) -> str | None:
    hay = f"{page_url}\n{html[:8000]}".lower()
    if any(token in hay for token in ("used-inventory", "used-vehicles", "searchused", "pre-owned", "preowned")):
        return "used"
    if any(token in hay for token in ("new-inventory", "new-vehicles", "searchnew")):
        return "new"
    return None


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
        norm_vars = {normalize_model_text(x) for x in vars_ if x}
        if v.model:
            model_norm = normalize_model_text(v.model)
            # Treat shorter model queries as family searches:
            # "F-150" should include "F-150 Lightning", but
            # "F-150 Lightning" should not include plain "F-150".
            if (
                model_norm
                and norm_vars
                and not any(model_norm == q or model_norm.startswith(q) for q in norm_vars)
            ):
                return False
        elif vars_ and not any(x in blob for x in vars_):
            return False
    return True


def listing_matches_inventory_scope(
    v: VehicleListing,
    inventory_scope: str,
) -> bool:
    scope = (inventory_scope or "all").strip().lower()
    if scope == "all":
        return True
    if scope == "on_lot_only":
        return v.is_in_stock is True and not bool(v.is_offsite) and not bool(v.is_shared_inventory)
    if scope == "exclude_shared":
        return not bool(v.is_offsite) and not bool(v.is_shared_inventory)
    if scope == "include_transit":
        return not bool(v.is_offsite) and not bool(v.is_shared_inventory)
    return True


def listing_matches_vehicle_condition(
    v: VehicleListing,
    vehicle_condition: str,
) -> bool:
    condition = (vehicle_condition or "all").strip().lower()
    if condition == "all":
        return True
    return v.vehicle_condition == condition
