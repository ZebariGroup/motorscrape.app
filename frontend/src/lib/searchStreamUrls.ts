import { resolveApiUrl } from "@/lib/apiBase";

type BuildSearchStreamUrlArgs = {
  location: string;
  make: string;
  model: string;
  correlationId: string;
  vehicleCategory: string;
  vehicleCondition: string;
  radiusMiles: string;
  inventoryScope: string;
  maxDealerships: string;
  marketRegion: string;
  preferSmallDealers: boolean;
};

export function searchLogUrl(correlationId: string): string {
  return resolveApiUrl(`/search/logs/${encodeURIComponent(correlationId)}?include_events=false`);
}

export function stopSearchUrl(correlationId: string): string {
  return resolveApiUrl(`/search/stop/${encodeURIComponent(correlationId)}`);
}

export function buildSearchStreamUrl(args: BuildSearchStreamUrlArgs): string {
  const params = new URLSearchParams({
    location: args.location.trim(),
    make: args.make.trim(),
    model: args.model.trim(),
    correlation_id: args.correlationId,
    vehicle_category: args.vehicleCategory,
    vehicle_condition: args.vehicleCondition,
    radius_miles: args.radiusMiles,
    inventory_scope: args.inventoryScope,
    max_dealerships: args.maxDealerships,
    market_region: args.marketRegion,
  });
  if (args.preferSmallDealers) {
    params.set("prefer_small_dealers", "true");
  }
  return `${resolveApiUrl("/search/stream")}?${params.toString()}`;
}
