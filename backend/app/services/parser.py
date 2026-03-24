"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.schemas import VehicleListing

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert at extracting vehicle inventory from messy dealership webpage HTML or text.
Return ONLY valid JSON (no markdown fences) with this exact shape:
{
  "vehicles": [
    {
      "year": <integer or null>,
      "make": <string or null>,
      "model": <string or null>,
      "trim": <string or null>,
      "price": <number or null, USD, no symbols>,
      "mileage": <integer or null>,
      "vin": <string or null>,
      "image_url": <absolute URL string or null>,
      "listing_url": <absolute URL string or null if unknown>,
      "raw_title": <short string summarizing the listing or null>
    }
  ]
}
Rules:
- Extract only real vehicles for sale (cars, trucks, SUVs). Skip service specials, parts, disclaimers, navigation.
- If the page is not inventory (e.g. contact page), return {"vehicles": []}.
- Prefer listing-specific URLs and images when present in the snippet.
- Do not invent VINs, prices, or stock numbers; use null if not clearly present.
"""


def _truncate_html(html: str, max_chars: int) -> str:
    if len(html) <= max_chars:
        return html
    return html[: max_chars // 2] + "\n\n<!-- truncated middle -->\n\n" + html[-max_chars // 2 :]


def _strip_scripts_styles(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    return html


async def extract_vehicles_from_html(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
) -> list[VehicleListing]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    cleaned = _strip_scripts_styles(html)
    snippet = _truncate_html(cleaned, settings.max_html_chars)

    user_msg = (
        f"Page URL: {page_url}\n"
        f"User filters (include only vehicles that plausibly match both when non-empty; "
        f"if filter is empty, do not filter on that dimension):\n"
        f"  make: {make_filter or '(any)'}\n"
        f"  model: {model_filter or '(any)'}\n\n"
        f"HTML (possibly truncated):\n{snippet}"
    )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    try:
        data: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON; raw=%s", content[:500])
        return []

    raw_list = data.get("vehicles")
    if not isinstance(raw_list, list):
        return []

    out: list[VehicleListing] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                VehicleListing(
                    year=_int_or_none(item.get("year")),
                    make=_str_or_none(item.get("make")),
                    model=_str_or_none(item.get("model")),
                    trim=_str_or_none(item.get("trim")),
                    price=_float_or_none(item.get("price")),
                    mileage=_int_or_none(item.get("mileage")),
                    vin=_str_or_none(item.get("vin")),
                    image_url=_str_or_none(item.get("image_url")),
                    listing_url=_str_or_none(item.get("listing_url")),
                    raw_title=_str_or_none(item.get("raw_title")),
                )
            )
        except Exception as e:
            logger.debug("Skip bad vehicle row: %s", e)
            continue

    return out


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
