from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Query parameters for streaming search (also used for POST body if needed)."""

    location: str = Field(..., min_length=2, description="City, ZIP, or address")
    make: str = Field(default="", description="Vehicle make filter, e.g. Toyota")
    model: str = Field(default="", description="Vehicle model filter, e.g. Camry")
    vehicle_condition: Literal["all", "new", "used"] = Field(
        default="all",
        description="Whether to include all inventory, only new vehicles, or only used vehicles.",
    )
    coverage_mode: Literal["standard", "expanded", "deep"] = Field(
        default="standard",
        description="How broadly to search for dealerships before scraping.",
    )
    inventory_scope: Literal["all", "on_lot_only", "exclude_shared", "include_transit"] = Field(
        default="all",
        description="Inventory availability scope to include in results.",
    )
    max_dealerships: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description="Optional per-search override for number of dealerships to scrape.",
    )
    max_pages_per_dealer: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Optional per-search override for pagination depth per dealership.",
    )


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
    vehicle_condition: Literal["new", "used"] | None = Field(
        default=None,
        description="Whether the listing is new or used when the page clearly indicates it.",
    )
    vin: str | None = Field(default=None, description="17-character Vehicle Identification Number.")
    image_url: str | None = Field(default=None, description="Absolute URL to the main image of the vehicle.")
    listing_url: str | None = Field(default=None, description="Absolute URL to the vehicle's detail page.")
    raw_title: str | None = Field(default=None, description="The raw title text of the listing.")
    inventory_location: str | None = Field(default=None, description="Reported vehicle location or source lot, if available.")
    availability_status: str | None = Field(default=None, description="Human-readable inventory availability such as in stock, in transit, or transfer.")
    is_offsite: bool | None = Field(default=None, description="Whether the vehicle appears to be off-site or shared inventory.")
    is_in_transit: bool | None = Field(default=None, description="Whether the vehicle is marked in transit.")
    is_in_stock: bool | None = Field(default=None, description="Whether the vehicle is marked in stock/on lot.")
    is_shared_inventory: bool | None = Field(default=None, description="Whether the vehicle is shared from another store/group inventory.")


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
