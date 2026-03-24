"""LLM-assisted extraction of vehicle listings from arbitrary HTML."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ExtractionResult, VehicleListing

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert at extracting vehicle inventory from messy dealership webpage HTML.
Rules:
- Extract EVERY SINGLE vehicle you can find on the page. Do not stop early.
- Extract only real vehicles for sale (cars, trucks, SUVs). Skip service specials, parts, disclaimers, navigation.
- Prefer listing-specific URLs and images when present in the snippet.
- Do not invent VINs, prices, or stock numbers; use null if not clearly present.
- If there is a clear "Next Page" or "->" pagination link, extract its absolute URL into `next_page_url`.
"""


def _truncate_html(html: str, max_chars: int) -> str:
    if len(html) <= max_chars:
        return html
    return html[: max_chars // 2] + "\n\n<!-- truncated middle -->\n\n" + html[-max_chars // 2 :]


def _clean_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    
    # Remove useless tags to save tokens
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "meta", "link", "head", "footer", "header", "nav", "form"]):
        tag.decompose()

    # Resolve relative URLs
    for tag in soup.find_all(href=True):
        tag["href"] = urljoin(base_url, tag["href"])
    for tag in soup.find_all(src=True):
        tag["src"] = urljoin(base_url, tag["src"])

    # Remove all attributes except the ones we care about
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr not in ["href", "src", "alt", "class"]:
                del tag[attr]

    return str(soup)


async def extract_vehicles_from_html(
    *,
    page_url: str,
    html: str,
    make_filter: str,
    model_filter: str,
) -> ExtractionResult:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    cleaned = _clean_html(html, page_url)
    snippet = _truncate_html(cleaned, settings.max_html_chars)

    user_msg = (
        f"Page URL: {page_url}\n"
        f"User filters (include only vehicles that plausibly match both when non-empty; "
        f"if filter is empty, do not filter on that dimension):\n"
        f"  make: {make_filter or '(any)'}\n"
        f"  model: {model_filter or '(any)'}\n\n"
        f"HTML (possibly truncated):\n{snippet}"
    )

    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=3)
    response = await client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format=ExtractionResult,
        temperature=0.1,
        max_tokens=8192,
    )

    parsed = response.choices[0].message.parsed
    if not parsed:
        return ExtractionResult(vehicles=[], next_page_url=None)
    return parsed
