from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.schemas import SearchRequest, VehicleListing
from app.services.orchestrator import stream_search


@dataclass(slots=True)
class SearchRunResult:
    listings: list[dict[str, Any]]
    status_messages: list[str]
    errors: list[str]
    outcome: dict[str, Any]


def _parse_sse_chunk(chunk: str) -> tuple[str | None, dict[str, Any] | None]:
    event_type: str | None = None
    payload: dict[str, Any] | None = None
    for raw_line in chunk.splitlines():
        if raw_line.startswith("event: "):
            event_type = raw_line[len("event: ") :].strip()
        elif raw_line.startswith("data: "):
            try:
                parsed = json.loads(raw_line[len("data: ") :])
                payload = dict(parsed) if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                payload = None
    return event_type, payload


async def run_search_once(request: SearchRequest, *, correlation_id: str | None = None) -> SearchRunResult:
    listings: list[dict[str, Any]] = []
    status_messages: list[str] = []
    errors: list[str] = []
    outcome: dict[str, Any] = {}

    async for chunk in stream_search(
        location=request.location,
        make=request.make,
        model=request.model,
        vehicle_category=request.vehicle_category,
        vehicle_condition=request.vehicle_condition,
        radius_miles=request.radius_miles,
        inventory_scope=request.inventory_scope,
        max_dealerships=request.max_dealerships,
        max_pages_per_dealer=request.max_pages_per_dealer,
        outcome_holder=outcome,
        correlation_id=correlation_id,
    ):
        event_type, payload = _parse_sse_chunk(chunk)
        if event_type == "status" and payload and payload.get("message"):
            status_messages.append(str(payload["message"]))
        elif event_type == "search_error" and payload and payload.get("message"):
            errors.append(str(payload["message"]))
        elif event_type == "vehicles" and payload:
            dealership = str(payload.get("dealership") or "Unknown")
            website = str(payload.get("website") or "")
            batch = payload.get("listings") or []
            if not isinstance(batch, list):
                continue
            for item in batch:
                try:
                    listing = VehicleListing.model_validate(item).model_dump(mode="json")
                except Exception:
                    continue
                listing["dealership"] = dealership
                listing["dealership_website"] = website
                listings.append(listing)

    return SearchRunResult(
        listings=listings,
        status_messages=status_messages,
        errors=errors,
        outcome=dict(outcome),
    )
