"""Shared make/model matching for listings (used by orchestrator and structured extraction)."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from app.schemas import VehicleListing

_USED_CONDITION_RE = re.compile(r"\b(used|pre[\s-]?owned|cpo|certified)\b", re.I)
_NEW_CONDITION_RE = re.compile(r"\bnew\b", re.I)
_MAKE_ALIAS_VARIANTS: dict[str, tuple[str, ...]] = {
    "bmwmotorrad": ("BMW Motorrad", "BMW"),
    "indianmotorcycle": ("Indian Motorcycle", "Indian"),
    "yamahaboats": ("Yamaha Boats", "Yamaha"),
    "harleydavidson": ("Harley-Davidson", "Harley Davidson"),
    "canam": ("Can-Am", "Can Am"),
    # Common typo / voice-to-text for Can-Am
    "canham": ("Can-Am", "Can Am"),
    "chriscraft": ("Chris Craft",),
    "fourwinns": ("Four Winns",),
    "keywestboats": ("Key West Boats", "Key West"),
    "rangerboats": ("Ranger Boats", "Ranger"),
    "searay": ("Sea Ray",),
}
_MAKE_SUFFIX_TOKENS = frozenset({"boat", "boats", "motorcycle", "motorcycles", "motorrad"})


def normalize_model_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.strip().lower())


def make_filter_variants(make: str) -> list[str]:
    raw = make.strip()
    if not raw:
        return []

    variants: set[str] = {raw}
    norm = normalize_model_text(raw)
    for alias in _MAKE_ALIAS_VARIANTS.get(norm, ()):
        variants.add(alias)

    tokenized = re.sub(r"[-/]+", " ", raw).strip()
    if tokenized:
        variants.add(tokenized)

    tokens = [token for token in tokenized.lower().split() if token]
    while tokens and tokens[-1] in _MAKE_SUFFIX_TOKENS:
        tokens.pop()
    if tokens:
        variants.add(" ".join(tokens))

    expanded: set[str] = set()
    for variant in variants:
        cleaned = re.sub(r"\s+", " ", variant).strip()
        if not cleaned:
            continue
        expanded.add(cleaned)
        if "-" in cleaned:
            expanded.add(cleaned.replace("-", " "))
        if " " in cleaned:
            expanded.add(cleaned.replace(" ", "-"))

    return sorted(expanded, key=len, reverse=True)


def make_filter_normalized_variants(make: str) -> set[str]:
    variants = {normalize_model_text(variant) for variant in make_filter_variants(make)}
    return {variant for variant in variants if variant}


def text_mentions_make(text: str, make: str) -> bool:
    if not make.strip():
        return True

    hay_lower = (text or "").lower()
    hay_norm = normalize_model_text(text)
    for variant in make_filter_variants(make):
        if variant.lower() in hay_lower:
            return True
    for variant_norm in make_filter_normalized_variants(make):
        if variant_norm in hay_norm:
            return True
    return False


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
    lower_url = (page_url or "").strip().lower()
    if not lower_url:
        return None
    parts = urlsplit(lower_url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    query_blob = " ".join(f"{k}={v}" for k, v in query_pairs)
    hay = f"{parts.path} {query_blob}"
    query = {k.lower(): v.lower() for k, v in query_pairs}
    if any(
        token in hay
        for token in (
            "used-inventory",
            "used-vehicles",
            "searchused",
            "inventory/used",
            "search/used",
            "detail/used",
            "cars/used",
            "pre-owned",
            "preowned",
        )
    ):
        return "used"
    if any(
        token in hay
        for token in (
            "new-inventory",
            "new-vehicles",
            "searchnew",
            "inventory/new",
            "search/new",
            "detail/new",
            "cars/new",
        )
    ):
        return "new"
    if query.get("tp") == "used" or query.get("condition") == "used":
        return "used"
    if query.get("tp") == "new" or query.get("condition") == "new":
        return "new"
    return None


def infer_make_from_page_scope(page_url: str, requested_make: str) -> str | None:
    make = requested_make.strip()
    make_norms = make_filter_normalized_variants(make)
    if not make_norms:
        return None
    parts = urlsplit((page_url or "").strip())
    if not parts.path and not parts.query:
        return None
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in query_pairs:
        if key.lower() not in {"make", "manufacturer", "brand"}:
            continue
        if normalize_model_text(value) in make_norms:
            return make
    path_norm = normalize_model_text(parts.path)
    path_lower = parts.path.lower()
    if any(make_norm in path_norm for make_norm in make_norms) and any(
        token in path_lower for token in ("inventory", "vehicles", "search")
    ):
        return make
    return None


def apply_page_make_scope(v: VehicleListing, page_url: str, requested_make: str) -> VehicleListing:
    scoped_make = infer_make_from_page_scope(page_url, requested_make)
    if not scoped_make:
        return v
    current_make_norm = normalize_model_text(v.make or "")
    current_model_norm = normalize_model_text(v.model or "")
    if current_make_norm and current_make_norm != current_model_norm:
        return v
    return v.model_copy(update={"make": scoped_make})


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
    make_f = make_f.strip()
    model_f = model_f.strip()
    if not make_f and not model_f:
        return True
    blob = " ".join(
        filter(None, [v.make or "", v.model or "", v.trim or "", v.raw_title or ""])
    )
    if make_f and not text_mentions_make(blob, make_f):
        return False
    if model_f:
        models = [m.strip() for m in model_f.split(",") if m.strip()]
        if not models:
            return True

        matched_any_model = False
        for m_str in models:
            vars_ = model_filter_variants(m_str)
            norm_vars = {normalize_model_text(x) for x in vars_ if x}
            if v.model:
                model_norm = normalize_model_text(v.model)
                if model_norm and norm_vars and any(model_norm == q or model_norm.startswith(q) for q in norm_vars):
                    matched_any_model = True
                    break
            elif vars_ and any(x in blob for x in vars_):
                matched_any_model = True
                break

        if not matched_any_model:
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
