import type { SavedSearchCriteria } from "@/types/savedSearch";

export function buildSearchCriteriaQuery(criteria: SavedSearchCriteria): string {
  const params = new URLSearchParams();
  params.set("location", criteria.location);
  if (criteria.make) params.set("make", criteria.make);
  if (criteria.model) params.set("model", criteria.model);
  params.set("vehicle_category", criteria.vehicle_category);
  params.set("vehicle_condition", criteria.vehicle_condition);
  params.set("radius_miles", String(criteria.radius_miles));
  params.set("inventory_scope", criteria.inventory_scope);
  if (criteria.max_dealerships != null) {
    params.set("max_dealerships", String(criteria.max_dealerships));
  }
  if (criteria.max_pages_per_dealer != null) {
    params.set("max_pages_per_dealer", String(criteria.max_pages_per_dealer));
  }
  if (criteria.market_region) {
    params.set("market_region", criteria.market_region);
  }
  return params.toString();
}

export function parseSearchCriteriaQuery(searchParams: URLSearchParams): SavedSearchCriteria | null {
  const location = searchParams.get("location")?.trim() ?? "";
  if (location.length < 2) return null;

  const vehicleCategory = searchParams.get("vehicle_category");
  const vehicleCondition = searchParams.get("vehicle_condition");
  const inventoryScope = searchParams.get("inventory_scope");
  const marketRegion = searchParams.get("market_region");

  const radiusMilesRaw = Number.parseInt(searchParams.get("radius_miles") ?? "", 10);
  const maxDealershipsRaw = Number.parseInt(searchParams.get("max_dealerships") ?? "", 10);
  const maxPagesRaw = Number.parseInt(searchParams.get("max_pages_per_dealer") ?? "", 10);

  return {
    location,
    make: searchParams.get("make")?.trim() ?? "",
    model: searchParams.get("model")?.trim() ?? "",
    vehicle_category:
      vehicleCategory === "motorcycle" || vehicleCategory === "boat" || vehicleCategory === "other" ? vehicleCategory : "car",
    vehicle_condition: vehicleCondition === "new" || vehicleCondition === "used" ? vehicleCondition : "all",
    radius_miles: Number.isFinite(radiusMilesRaw) ? radiusMilesRaw : 25,
    inventory_scope:
      inventoryScope === "on_lot_only" || inventoryScope === "exclude_shared" || inventoryScope === "include_transit"
        ? inventoryScope
        : "all",
    max_dealerships: Number.isFinite(maxDealershipsRaw) ? maxDealershipsRaw : null,
    max_pages_per_dealer: Number.isFinite(maxPagesRaw) ? maxPagesRaw : null,
    market_region: marketRegion === "eu" ? "eu" : "us",
  };
}
