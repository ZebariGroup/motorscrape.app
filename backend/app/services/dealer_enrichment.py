"""
Dealer enrichment: populate rich profile fields for newly discovered dealerships.

Called asynchronously (fire-and-forget) when a dealer is first inserted into
the Supabase dealerships table so it never blocks a live search.

Sources:
  1. Google Places Details API (phone, hours, rating, photos, description)
  2. Dealer homepage scan (social links, OEM brands, services, phone fallback)
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Google Places Details field mask for enrichment (extended beyond websiteUri)
# ----------------------------------------------------------------------------
ENRICH_FIELD_MASK = (
    "nationalPhoneNumber,regularOpeningHours,rating,"
    "userRatingCount,photos,editorialSummary,websiteUri"
)
PLACES_BASE = "https://places.googleapis.com/v1"

# Maximum number of Google photo references to store
MAX_PHOTOS = 5

# Known social / review domains to extract links for
_SOCIAL_PATTERNS: list[tuple[str, str]] = [
    ("facebook", r"facebook\.com/(?!sharer|share|dialog)[\w.@/-]+"),
    ("instagram", r"instagram\.com/[\w.@/-]+"),
    ("twitter", r"(?:twitter|x)\.com/[\w@-]+"),
    ("youtube", r"youtube\.com/(?:channel|c|user|@)[\w/-]+"),
    ("yelp", r"yelp\.com/biz/[\w-]+"),
    ("dealerrater", r"dealerrater\.com/dealer-reviews/[\w-]+"),
    ("carscom", r"cars\.com/dealers/[\w-]+"),
]

# OEM brand keywords searched in page text (title, meta, logo alts)
_OEM_BRANDS = [
    "Acura", "Alfa Romeo", "Audi", "BMW", "Buick", "Cadillac", "Chevrolet",
    "Chevy", "Chrysler", "Dodge", "Ferrari", "Fiat", "Ford", "Genesis",
    "GMC", "Honda", "Hyundai", "Infiniti", "Jaguar", "Jeep", "Kia",
    "Lamborghini", "Land Rover", "Lexus", "Lincoln", "Maserati", "Mazda",
    "Mercedes-Benz", "Mercedes", "MINI", "Mitsubishi", "Nissan", "Porsche",
    "Ram", "Rivian", "Rolls-Royce", "Subaru", "Tesla", "Toyota", "Volkswagen",
    "Volvo", "Harley-Davidson", "Harley", "Indian Motorcycle", "Kawasaki",
    "Suzuki", "Yamaha", "Sea-Doo", "Polaris", "Can-Am", "BRP",
]
_OEM_BRAND_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in _OEM_BRANDS) + r")\b",
    re.IGNORECASE,
)

# Service keywords
_SERVICE_KEYWORDS: dict[str, list[str]] = {
    "new": ["new vehicles", "new cars", "new inventory", "new truck", "new suv", "shop new"],
    "used": ["used vehicles", "used cars", "pre-owned", "preowned", "certified used", "shop used"],
    "cpo": ["certified pre-owned", "certified preowned", "cpo"],
    "finance": ["financing", "finance center", "apply for financing", "auto loan", "get financed"],
    "service_center": ["service center", "service department", "schedule service", "auto repair", "oil change"],
    "parts": ["parts department", "auto parts", "oem parts", "genuine parts"],
}


# ----------------------------------------------------------------------------
# Slug helpers
# ----------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert arbitrary text to a lowercase URL slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def _parse_city_state(address: str) -> tuple[str, str]:
    """
    Best-effort parse of city and state abbreviation from a formatted address.
    Handles 'City, ST 12345, USA' and 'City, State, Country'.
    Returns (city, state_abbr) — may be empty strings if not parseable.
    """
    parts = [p.strip() for p in address.split(",")]
    city = ""
    state = ""
    if len(parts) >= 2:
        city = parts[-3] if len(parts) >= 3 else parts[0]
        state_part = parts[-2].strip()
        # Take the first token (state abbreviation or full name)
        state = state_part.split()[0] if state_part else ""
    return city, state


def generate_slug(name: str, address: str) -> str:
    """Generate a URL slug from dealer name + city + state."""
    city, state = _parse_city_state(address)
    parts = [name]
    if city:
        parts.append(city)
    if state and len(state) <= 3:
        parts.append(state)
    return _slugify(" ".join(parts))


# ----------------------------------------------------------------------------
# Google Places Details fetch
# ----------------------------------------------------------------------------

async def _fetch_places_details(
    place_id: str,
    api_key: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Call Google Places Details API and return the raw JSON response."""
    url = f"{PLACES_BASE}/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ENRICH_FIELD_MASK,
    }
    try:
        r = await client.get(url, headers=headers, timeout=10.0)
        if r.status_code == 200:
            return r.json()
        logger.warning("Places Details HTTP %s for place_id=%s", r.status_code, place_id)
    except Exception as exc:
        logger.warning("Places Details request failed for %s: %s", place_id, exc)
    return {}


def _parse_places_details(data: dict[str, Any]) -> dict[str, Any]:
    """Extract structured fields from a Places Details response."""
    out: dict[str, Any] = {}

    phone = data.get("nationalPhoneNumber") or data.get("internationalPhoneNumber")
    if phone:
        out["phone"] = phone.strip()

    rating = data.get("rating")
    if rating is not None:
        try:
            out["rating"] = round(float(rating), 1)
        except (TypeError, ValueError):
            pass

    review_count = data.get("userRatingCount")
    if review_count is not None:
        try:
            out["review_count"] = int(review_count)
        except (TypeError, ValueError):
            pass

    editorial = data.get("editorialSummary", {})
    description = editorial.get("text") if isinstance(editorial, dict) else None
    if description:
        out["description"] = description.strip()

    hours = data.get("regularOpeningHours")
    if hours:
        out["hours_json"] = hours

    photos = data.get("photos", [])
    if photos:
        refs = []
        for p in photos[:MAX_PHOTOS]:
            name = p.get("name")
            if name:
                refs.append({"name": name, "widthPx": p.get("widthPx"), "heightPx": p.get("heightPx")})
        if refs:
            out["photo_refs"] = refs

    return out


# ----------------------------------------------------------------------------
# Dealer homepage scan
# ----------------------------------------------------------------------------

async def _fetch_homepage(url: str, client: httpx.AsyncClient) -> str:
    """Lightweight homepage fetch — no JS rendering, just raw HTML."""
    try:
        r = await client.get(
            url,
            timeout=12.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; MotorscrapeBot/1.0; "
                    "+https://www.motorscrape.com)"
                )
            },
        )
        if r.status_code == 200:
            return r.text
    except Exception as exc:
        logger.debug("Homepage fetch failed for %s: %s", url, exc)
    return ""


def _extract_social_links(html: str) -> dict[str, str]:
    """Return {platform: url} for the first matched link per platform."""
    links: dict[str, str] = {}
    for platform, pattern in _SOCIAL_PATTERNS:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 10)
            raw = html[start : m.end() + 5]
            href_m = re.search(r'https?://' + pattern, html, re.IGNORECASE)
            if href_m:
                links[platform] = href_m.group(0).rstrip("\"'> \n/")
    return links


def _extract_phone_from_html(html: str) -> str | None:
    """Extract phone number from <a href="tel:..."> tags."""
    m = re.search(r'href=["\']tel:([+\d\s\(\)\-\.]{7,20})["\']', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _extract_oem_brands(html: str) -> list[str]:
    """Find OEM brand names mentioned in page text, returning unique sorted list."""
    # Focus on title, meta description, h1/h2, nav — lightweight heuristic
    target_sections = re.findall(
        r'<(?:title|h[12]|nav|header)[^>]*>(.*?)</(?:title|h[12]|nav|header)>',
        html[:50_000],
        re.IGNORECASE | re.DOTALL,
    )
    text = " ".join(target_sections)
    # Also include alt text for images (OEM logos)
    alts = re.findall(r'alt=["\']([^"\']{1,80})["\']', html[:80_000], re.IGNORECASE)
    text += " " + " ".join(alts)

    found: set[str] = set()
    for m in _OEM_BRAND_PATTERN.finditer(text):
        brand = m.group(1)
        # Normalize abbreviations
        if brand.lower() in ("chevy",):
            brand = "Chevrolet"
        if brand.lower() in ("mercedes",):
            brand = "Mercedes-Benz"
        if brand.lower() in ("harley",):
            brand = "Harley-Davidson"
        found.add(brand)
    return sorted(found)


def _extract_services(html: str) -> list[str]:
    """Detect offered services from page text."""
    text_lower = html[:100_000].lower()
    found: list[str] = []
    for service, keywords in _SERVICE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(service)
    return found


def _parse_homepage(html: str) -> dict[str, Any]:
    """Extract social links, OEM brands, services, phone from dealer homepage HTML."""
    out: dict[str, Any] = {}

    social = _extract_social_links(html)
    if social:
        out["social_links"] = social

    phone = _extract_phone_from_html(html)
    if phone:
        out["phone_from_site"] = phone

    brands = _extract_oem_brands(html)
    if brands:
        out["oem_brands"] = brands

    services = _extract_services(html)
    if services:
        out["services"] = services

    return out


# ----------------------------------------------------------------------------
# Slug collision resolution via Supabase
# ----------------------------------------------------------------------------

def _resolve_slug(client_sb: Any, base_slug: str, dealership_id: str) -> str:
    """
    Check if the slug is already taken by another dealership.
    Append a numeric suffix until unique.
    """
    candidate = base_slug
    for attempt in range(1, 20):
        try:
            res = (
                client_sb.table("dealerships")
                .select("id")
                .eq("slug", candidate)
                .neq("id", dealership_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                return candidate
        except Exception:
            return candidate
        candidate = f"{base_slug}-{attempt}"
    return f"{base_slug}-{dealership_id[:8]}"


# ----------------------------------------------------------------------------
# Main enrichment entry point
# ----------------------------------------------------------------------------

async def enrich_dealer(
    dealership_id: str,
    place_id: str,
    name: str,
    address: str,
    website: str | None,
) -> None:
    """
    Async enrichment job. Fetches Places Details + dealer homepage,
    generates a slug, and upserts all data into the dealerships table.

    Designed to be called as asyncio.create_task(); failures are logged but
    do not propagate.
    """
    api_key = settings.google_places_api_key
    if not api_key:
        logger.debug("Skipping dealer enrichment: no GOOGLE_PLACES_API_KEY")
        return

    try:
        from app.db.supabase_store import get_supabase_store
        sb = get_supabase_store()
        client_sb = sb.client
    except Exception as exc:
        logger.warning("Dealer enrichment: cannot get Supabase client: %s", exc)
        return

    logger.info("Enriching dealer %s (place_id=%s)", name, place_id)

    update: dict[str, Any] = {}

    async with httpx.AsyncClient() as http:
        # Step 1: Google Places Details
        details_data = await _fetch_places_details(place_id, api_key, http)
        if details_data:
            update.update(_parse_places_details(details_data))
            update["google_details_json"] = details_data

        # Step 2: Dealer homepage scan
        if website:
            html = await _fetch_homepage(website, http)
            if html:
                site_data = _parse_homepage(html)
                # Phone from site is fallback only (Places phone takes priority)
                if "phone" not in update and site_data.get("phone_from_site"):
                    update["phone"] = site_data["phone_from_site"]
                if site_data.get("social_links"):
                    update["social_links"] = site_data["social_links"]
                if site_data.get("oem_brands"):
                    update["oem_brands"] = site_data["oem_brands"]
                if site_data.get("services"):
                    update["services"] = site_data["services"]

    # Step 3: Generate and resolve slug
    base_slug = generate_slug(name, address)
    slug = await asyncio.to_thread(_resolve_slug, client_sb, base_slug, dealership_id)
    update["slug"] = slug

    # Step 4: Mark enriched
    from datetime import datetime, timezone
    update["enriched_at"] = datetime.now(timezone.utc).isoformat()
    update["enrichment_version"] = 1

    # Step 5: Upsert to Supabase
    try:
        client_sb.table("dealerships").update(update).eq("id", dealership_id).execute()
        logger.info(
            "Enrichment complete for %s (slug=%s, brands=%s)",
            name,
            slug,
            update.get("oem_brands", []),
        )
    except Exception as exc:
        logger.error("Failed to save enrichment for %s: %s", name, exc)
