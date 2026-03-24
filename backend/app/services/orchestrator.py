"""Coordinates Places → scrape → LLM parse with async iteration for SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.schemas import DealershipFound
from app.services.parser import extract_vehicles_from_html
from app.services.places import find_car_dealerships
from app.services.scraper import fetch_page_html

logger = logging.getLogger(__name__)


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

    sem = asyncio.Semaphore(4)

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
            try:
                html, method = await fetch_page_html(website)
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

            chunks.append(
                _sse_pack(
                    "dealership",
                    {
                        "index": index,
                        "total": len(dealers),
                        "name": d.name,
                        "website": website,
                        "status": "parsing",
                        "fetch_method": method,
                    },
                )
            )

            try:
                vehicles = await extract_vehicles_from_html(
                    page_url=website,
                    html=html,
                    make_filter=make,
                    model_filter=model,
                )
            except Exception as e:
                logger.warning("Parse failed for %s: %s", website, e)
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

            vdicts = [v.model_dump(exclude_none=True) for v in vehicles]
            chunks.append(
                _sse_pack(
                    "vehicles",
                    {
                        "dealership": d.name,
                        "website": website,
                        "count": len(vdicts),
                        "listings": vdicts,
                    },
                )
            )
            chunks.append(
                _sse_pack(
                    "dealership",
                    {
                        "index": index,
                        "total": len(dealers),
                        "name": d.name,
                        "website": website,
                        "status": "done",
                        "listings_found": len(vdicts),
                    },
                )
            )
        return chunks

    tasks = [asyncio.create_task(process_one(i, d)) for i, d in enumerate(dealers, start=1)]
    for t in asyncio.as_completed(tasks):
        try:
            parts = await t
            for part in parts:
                yield part
        except Exception as e:
            logger.exception("Worker failed")
            yield _sse_pack("search_error", {"message": str(e), "phase": "worker"})

    yield _sse_pack("done", {"ok": True, "dealerships": len(dealers)})
