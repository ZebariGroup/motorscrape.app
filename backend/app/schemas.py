from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Query parameters for streaming search (also used for POST body if needed)."""

    location: str = Field(..., min_length=2, description="City, ZIP, or address")
    make: str = Field(default="", description="Vehicle make filter, e.g. Toyota")
    model: str = Field(default="", description="Vehicle model filter, e.g. Camry")


class DealershipFound(BaseModel):
    name: str
    place_id: str
    address: str
    website: str | None = None


class VehicleListing(BaseModel):
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    price: float | None = None
    mileage: int | None = None
    vin: str | None = None
    image_url: str | None = None
    listing_url: str | None = None
    raw_title: str | None = None


class SSEEvent(BaseModel):
    """Normalized event for Server-Sent Events."""

    type: Literal[
        "status",
        "dealership",
        "vehicles",
        "search_error",
        "done",
    ]
    data: dict[str, Any]
