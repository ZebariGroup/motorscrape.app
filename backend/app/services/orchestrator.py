"""Coordinates Places → scrape → LLM parse with async iteration for SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.config import settings
from app.schemas import DealershipFound
from app.services.parser import extract_vehicles_from_html
from app.services.places import find_car_dealerships
from app.services.scraper import fetch_page_html

logger = logging.getLogger(__name__)

def _find_inventory_url(html: str, base_url: str) -> str:
    """Heuristic to find the best 'inventory' link on a dealership homepage."""
    try:
        soup = BeautifulSoup(html, "lxml")
        best_url = base_url
        best_score = -1

        for a in soup.find_all("a", href=True):
            href = a['href'].lower()
            text = a.get_text(strip=True).lower()
            score = 0

            if "inventory" in href or "inventory" in text:
                score += 10
            if "used" in href or "pre-owned" in text or "used" in text:
                score += 5
            if "search" in href:
                score += 5
            if "new" in href:
                score += 3

            # Penalize non-inventory links
            if any(x in href for x in ["service", "parts", "finance", "contact", "about", "specials", "privacy"]):
                score -= 20

            if score > best_score and score > 0:
                best_score = score
                best_url = urljoin(base_url, a['href'])

        return best_url
    except Exception as e:
        logger.warning("Failed to parse inventory URL: %s", e)
        return base_url


def _sse_pack(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_search(location: str, make: str, model: str) -> AsyncIterator[str]:
    """
    Yield SSE-formatted strings: status, dealership, vehicles, error, done.
    """
    yield _sse_pack("status", {"message": "Finding local dealerships…", "phase": "places"})

    try:
        dealers = await find_car_dealerships(location, limit=settings.max_dealerships * 2)
    except Exception as e:
        logger.exception("Places search failed")
        yield _sse_pack("search_error", {"message": str(e), "phase": "places"})
        yield _sse_pack("done", {"ok": False})
        return

    # Cap to max_dealerships with websites
    dealers = dealers[: settings.max_dealerships]
    if not dealers:
        yield _sse_pack("status", {"message": "No dealerships with websites found.", "phase": "places"})
        yield _sse_pack("done", {"ok": True, "dealerships": 0})
        return

    yield _sse_pack(
        "status",
        {"message": f"Found {len(dealers)} dealerships. Scraping inventory…", "phase": "scrape"},
    )

    sem = asyncio.Semaphore(max(1, settings.search_concurrency))
    fetch_timeout = settings.scrape_timeout * 3 + 5.0
    parse_timeout = settings.openai_timeout + 5.0

    async def process_one(index: int, d: DealershipFound) -> list[str]:
        chunks: list[str] = []
        website = d.website or ""
        chunks.append(
            _sse_pack(
                "dealership",
                {
                    "index": index,
                    "total": len(dealers),
                    "name": d.name,
                    "website": website,
                    "address": d.address,
                    "status": "scraping",
                },
            )
        )
        async with sem:
            # 1. Fetch homepage to find inventory link
            try:
                html, method = await asyncio.wait_for(
                    fetch_page_html(website),
                    timeout=fetch_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Scrape timed out for %s", website)
                chunks.append(
                    _sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "status": "error",
                            "error": (
                                f"Timed out while fetching pages after ~{int(fetch_timeout)}s."
                            ),
                        },
                    )
                )
                return chunks
            except Exception as e:
                logger.warning("Scrape failed for %s: %s", website, e)
                chunks.append(
                    _sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": website,
                            "status": "error",
                            "error": str(e),
                        },
                    )
                )
                return chunks

            inv_url = _find_inventory_url(html, website)
            
            # 2. Pagination loop
            current_url = inv_url
            pages_scraped = 0
            max_pages = max(1, settings.max_pages_per_dealer)
            total_vehicles = 0

            while current_url and pages_scraped < max_pages:
                if pages_scraped > 0:
                    chunks.append(
                        _sse_pack(
                            "dealership",
                            {
                                "index": index,
                                "total": len(dealers),
                                "name": d.name,
                                "website": current_url,
                                "status": "scraping",
                            },
                        )
                    )
                    try:
                        html, method = await asyncio.wait_for(
                            fetch_page_html(current_url),
                            timeout=fetch_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Pagination scrape timed out for %s", current_url)
                        break
                    except Exception as e:
                        logger.warning("Pagination scrape failed for %s: %s", current_url, e)
                        break

                chunks.append(
                    _sse_pack(
                        "dealership",
                        {
                            "index": index,
                            "total": len(dealers),
                            "name": d.name,
                            "website": current_url,
                            "status": "parsing",
                            "fetch_method": method,
                        },
                    )
                )

                try:
                    ext_result = await asyncio.wait_for(
                        extract_vehicles_from_html(
                            page_url=current_url,
                            html=html,
                            make_filter=make,
                            model_filter=model,
                        ),
                        timeout=parse_timeout,
                    )
                except asyncio.TimeoutError:
                    msg = f"Timed out during AI extraction after ~{int(parse_timeout)}s."
                    logger.warning("Parse timed out for %s", current_url)
                    if pages_scraped == 0:
                        chunks.append(
                            _sse_pack(
                                "dealership",
                                {
                                    "index": index,
                                    "total": len(dealers),
                                    "name": d.name,
                                    "website": current_url,
                                    "status": "error",
                                    "error": msg,
                                },
                            )
                        )
                    break
                except Exception as e:
                    logger.warning("Parse failed for %s: %s", current_url, e)
                    if pages_scraped == 0:
                        chunks.append(
                            _sse_pack(
                                "dealership",
                                {
                                    "index": index,
                                    "total": len(dealers),
                                    "name": d.name,
                                    "website": current_url,
                                    "status": "error",
                                    "error": str(e),
                                },
                            )
                        )
                    break

                vdicts = [v.model_dump(exclude_none=True) for v in ext_result.vehicles]
                if vdicts:
                    total_vehicles += len(vdicts)
                    chunks.append(
                        _sse_pack(
                            "vehicles",
                            {
                                "dealership": d.name,
                                "website": current_url,
                                "count": len(vdicts),
                                "listings": vdicts,
                            },
                        )
                    )

                current_url = ext_result.next_page_url
                pages_scraped += 1

                if not vdicts:
                    break  # Stop pagination if no vehicles found

            chunks.append(
                _sse_pack(
                    "dealership",
                    {
                        "index": index,
                        "total": len(dealers),
                        "name": d.name,
                        "website": website,
                        "status": "done",
                        "listings_found": total_vehicles,
                    },
                )
            )
        return chunks

    async def process_one_with_timeout(index: int, d: DealershipFound) -> list[str]:
        try:
            return await asyncio.wait_for(
                process_one(index, d),
                timeout=settings.dealership_timeout,
            )
        except asyncio.TimeoutError:
            website = d.website or ""
            logger.warning("Dealership worker timed out for %s", website)
            return [
                _sse_pack(
                    "dealership",
                    {
                        "index": index,
                        "total": len(dealers),
                        "name": d.name,
                        "website": website,
                        "address": d.address,
                        "status": "error",
                        "error": (
                            "Timed out while processing this dealership. "
                            "Skipping to keep search moving."
                        ),
                    },
                )
            ]

    tasks = [
        asyncio.create_task(process_one_with_timeout(i, d))
        for i, d in enumerate(dealers, start=1)
    ]
    for t in asyncio.as_completed(tasks):
        try:
            parts = await t
            for part in parts:
                yield part
        except Exception as e:
            logger.exception("Worker failed")
            yield _sse_pack("search_error", {"message": str(e), "phase": "worker"})

    yield _sse_pack("done", {"ok": True, "dealerships": len(dealers)})
