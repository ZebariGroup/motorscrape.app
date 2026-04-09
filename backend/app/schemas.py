from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

VehicleCategory = Literal["car", "motorcycle", "boat", "other"]
VehicleCondition = Literal["all", "new", "used"]
ListingCondition = Literal["new", "used"]
UsageUnit = Literal["miles", "hours"]
DealershipDiscoverySource = Literal["google_places", "system_db"]


class SearchRequest(BaseModel):
    """Query parameters for streaming search (also used for POST body if needed)."""

    location: str = Field(..., min_length=2, description="City, ZIP, or address")
    make: str = Field(default="", description="Vehicle make filter, e.g. Toyota")
    model: str = Field(default="", description="Vehicle model filter, e.g. Camry")
    vehicle_category: VehicleCategory = Field(
        default="car",
        description="Vehicle category to search for, such as car, motorcycle, boat, or other.",
    )
    vehicle_condition: VehicleCondition = Field(
        default="all",
        description="Whether to include all inventory, only new vehicles, or only used vehicles.",
    )
    radius_miles: int = Field(
        default=25,
        ge=5,
        le=250,
        description="How far from the search location to look for dealerships.",
    )
    inventory_scope: Literal["all", "on_lot_only", "exclude_shared", "include_transit"] = Field(
        default="all",
        description="Inventory availability scope to include in results.",
    )
    prefer_small_dealers: bool = Field(
        default=False,
        description="When true, bias dealership discovery toward smaller dealers instead of obvious major groups.",
    )
    max_dealerships: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="Optional per-search override for number of dealerships to scrape.",
    )
    max_pages_per_dealer: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description=(
            "Optional per-search override for the initial pagination depth per dealership. "
            "The scraper may continue deeper when the site exposes more result pages, "
            "subject to server safety caps."
        ),
    )
    market_region: Literal["us", "eu"] = Field(
        default="us",
        description="Search market profile used for radius display and region-specific discovery phrasing.",
    )


class DealershipFound(BaseModel):
    name: str
    place_id: str
    address: str
    website: str | None = None
    lat: float | None = None
    lng: float | None = None
    discovery_source: DealershipDiscoverySource = Field(
        default="google_places",
        description="Where this dealership row came from: Google Places API or the system dealership database.",
    )


class VehicleListing(BaseModel):
    vehicle_category: VehicleCategory = Field(
        default="car",
        description="Vehicle category inferred from the search or listing context.",
    )
    year: int | None = Field(default=None, description="Year of the vehicle.")
    make: str | None = Field(default=None, description="Make of the vehicle, e.g. Toyota.")
    model: str | None = Field(default=None, description="Model of the vehicle, e.g. Camry.")
    trim: str | None = Field(default=None, description="Trim level of the vehicle.")
    body_style: str | None = Field(default=None, description="Body style such as SUV, Sedan, or Truck.")
    drivetrain: str | None = Field(default=None, description="Drive type such as AWD, FWD, or 4x4.")
    engine: str | None = Field(default=None, description="Engine summary such as 2.0L 4-cyl.")
    transmission: str | None = Field(default=None, description="Transmission summary when decoded or listed.")
    fuel_type: str | None = Field(default=None, description="Primary fuel type such as Gasoline, Diesel, or Electric.")
    exterior_color: str | None = Field(default=None, description="Exterior color of the vehicle when available.")
    price: float | None = Field(default=None, description="Price in USD as a number, no symbols.")
    mileage: int | None = Field(default=None, description="Mileage as an integer, no commas.")
    usage_value: int | None = Field(
        default=None,
        description="Normalized usage/odometer reading such as mileage or engine hours.",
    )
    usage_unit: UsageUnit | None = Field(
        default=None,
        description="Unit for usage_value, such as miles or hours.",
    )
    vehicle_condition: ListingCondition | None = Field(
        default=None,
        description="Whether the listing is new or used when the page clearly indicates it.",
    )
    vin: str | None = Field(default=None, description="17-character Vehicle Identification Number.")
    vehicle_identifier: str | None = Field(
        default=None,
        description="Best available unit identifier such as VIN, HIN, or stock number.",
    )
    image_url: str | None = Field(default=None, description="Absolute URL to the main image of the vehicle.")
    listing_url: str | None = Field(default=None, description="Absolute URL to the vehicle's detail page.")
    raw_title: str | None = Field(default=None, description="The raw title text of the listing.")
    inventory_location: str | None = Field(default=None, description="Reported vehicle location or source lot, if available.")
    availability_status: str | None = Field(default=None, description="Human-readable inventory availability such as in stock, in transit, or transfer.")
    is_offsite: bool | None = Field(default=None, description="Whether the vehicle appears to be off-site or shared inventory.")
    is_in_transit: bool | None = Field(default=None, description="Whether the vehicle is marked in transit.")
    is_in_stock: bool | None = Field(default=None, description="Whether the vehicle is marked in stock/on lot.")
    is_shared_inventory: bool | None = Field(default=None, description="Whether the vehicle is shared from another store/group inventory.")
    msrp: float | None = Field(default=None, description="Manufacturer suggested retail price in USD when listed separately from sale price.")
    lease_monthly_payment: float | None = Field(
        default=None,
        description="Advertised monthly lease payment in USD when a listing exposes it.",
    )
    lease_term_months: int | None = Field(
        default=None,
        description="Lease term in months when paired with an advertised monthly lease payment.",
    )
    dealer_discount: float | None = Field(
        default=None,
        description="Total dealer discount or savings below MSRP in USD (non-negative number).",
    )
    incentive_labels: list[str] = Field(
        default_factory=list,
        description="Human-readable incentive or rebate lines (e.g. rebate names with amounts).",
    )
    feature_highlights: list[str] = Field(
        default_factory=list,
        description="Notable packages, options, or equipment lines suitable for display.",
    )
    stock_date: str | None = Field(
        default=None,
        description="Inventory/stock date as YYYY-MM-DD when the site provides it.",
    )
    days_on_lot: int | None = Field(
        default=None,
        description="Approximate days the unit has been in inventory when stated or derived from stock_date.",
    )
    history_seen_count: int | None = Field(
        default=None,
        description="How many prior completed runs from this account have observed the same unit.",
    )
    history_first_seen_at: str | None = Field(
        default=None,
        description="ISO timestamp when this account first observed the same vehicle across runs.",
    )
    history_last_seen_at: str | None = Field(
        default=None,
        description="ISO timestamp when this account most recently observed the same vehicle across runs.",
    )
    history_days_tracked: int | None = Field(
        default=None,
        description="Approximate days between the first and latest tracked observations for this account.",
    )
    history_previous_price: float | None = Field(
        default=None,
        description="Previous observed price before the current/latest tracked observation.",
    )
    history_lowest_price: float | None = Field(
        default=None,
        description="Lowest observed price for this unit across tracked runs.",
    )
    history_highest_price: float | None = Field(
        default=None,
        description="Highest observed price for this unit across tracked runs.",
    )
    history_price_change: float | None = Field(
        default=None,
        description="Difference between the current/latest tracked price and the immediately previous tracked price.",
    )
    history_price_change_since_first: float | None = Field(
        default=None,
        description="Difference between the current/latest tracked price and the first tracked price.",
    )
    price_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent observed price points for this unit across tracked runs.",
    )
    historical_market_prices: list[float] = Field(
        default_factory=list,
        description=(
            "Historical comparable prices from prior account scrape runs, excluding the current listing identity, "
            "used to stabilize market valuation when current-run inventory is sparse."
        ),
    )
    historical_market_price_points: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Historical comparable price points with observed_at timestamps used for recency-weighted market valuation."
        ),
    )
    historical_market_sample_count: int | None = Field(
        default=None,
        description="Count of matched historical comparable listings used to build historical_market_prices.",
    )
    historical_market_median: float | None = Field(
        default=None,
        description="Median of historical_market_prices for this listing's comparable bucket.",
    )
    @field_validator("incentive_labels", "feature_highlights", mode="before")
    @classmethod
    def _coerce_str_lists(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    @field_validator("price_history", mode="before")
    @classmethod
    def _coerce_price_history(cls, v: Any) -> list[dict[str, Any]]:
        if v is None:
            return []
        if isinstance(v, list):
            return [dict(item) for item in v if isinstance(item, dict)]
        return []

    @field_validator("historical_market_prices", mode="before")
    @classmethod
    def _coerce_historical_market_prices(cls, v: Any) -> list[float]:
        if v is None:
            return []
        if isinstance(v, list):
            out: list[float] = []
            for item in v:
                try:
                    out.append(float(item))
                except (TypeError, ValueError):
                    continue
            return out
        return []

    @field_validator("historical_market_price_points", mode="before")
    @classmethod
    def _coerce_historical_market_price_points(cls, v: Any) -> list[dict[str, Any]]:
        if v is None:
            return []
        if isinstance(v, list):
            out: list[dict[str, Any]] = []
            for item in v:
                if not isinstance(item, dict):
                    continue
                price_raw = item.get("price")
                observed_at_raw = item.get("observed_at")
                try:
                    price_value = float(price_raw)
                except (TypeError, ValueError):
                    continue
                point: dict[str, Any] = {"price": price_value}
                try:
                    if observed_at_raw is not None:
                        point["observed_at"] = float(observed_at_raw)
                except (TypeError, ValueError):
                    pass
                out.append(point)
            return out
        return []


class PaginationInfo(BaseModel):
    current_page: int | None = Field(
        default=None,
        description="Current page number when it can be inferred from the SRP URL or page metadata.",
    )
    page_size: int | None = Field(
        default=None,
        description="Expected number of results per page when the site exposes a page size.",
    )
    total_pages: int | None = Field(
        default=None,
        description="Total number of inventory result pages when the site exposes it.",
    )
    total_results: int | None = Field(
        default=None,
        description="Total matching inventory results reported by the site for this search.",
    )
    source: str | None = Field(
        default=None,
        description="Where pagination metadata came from, such as inventory_api, dom_summary, or page_links.",
    )


class ExtractionResult(BaseModel):
    vehicles: list[VehicleListing] = Field(description="List of vehicles found on the page.")
    next_page_url: str | None = Field(
        default=None,
        description="Absolute URL to the NEXT page of inventory results, if pagination exists. Must be a valid URL or null."
    )
    pagination: PaginationInfo | None = Field(
        default=None,
        description="Normalized pagination metadata inferred from the page or embedded inventory APIs.",
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
