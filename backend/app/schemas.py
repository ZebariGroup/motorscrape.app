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
    year: int | None = Field(default=None, description="Year of the vehicle.")
    make: str | None = Field(default=None, description="Make of the vehicle, e.g. Toyota.")
    model: str | None = Field(default=None, description="Model of the vehicle, e.g. Camry.")
    trim: str | None = Field(default=None, description="Trim level of the vehicle.")
    price: float | None = Field(default=None, description="Price in USD as a number, no symbols.")
    mileage: int | None = Field(default=None, description="Mileage as an integer, no commas.")
    vin: str | None = Field(default=None, description="17-character Vehicle Identification Number.")
    image_url: str | None = Field(default=None, description="Absolute URL to the main image of the vehicle.")
    listing_url: str | None = Field(default=None, description="Absolute URL to the vehicle's detail page.")
    raw_title: str | None = Field(default=None, description="The raw title text of the listing.")


class ExtractionResult(BaseModel):
    vehicles: list[VehicleListing] = Field(description="List of vehicles found on the page.")
    next_page_url: str | None = Field(
        default=None,
        description="Absolute URL to the NEXT page of inventory results, if pagination exists. Must be a valid URL or null."
    )


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
