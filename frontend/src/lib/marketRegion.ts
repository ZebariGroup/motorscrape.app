/** US vs EU/UK market: catalog labels, radius units, and backend inventory hints. */

export type MarketRegion = "us" | "eu";

export const MARKET_REGION_STORAGE_KEY = "motorscrape_market_region";

/** Statute miles per kilometre (exact). */
export const MILES_PER_KM = 1 / 1.609344;

export const DEFAULT_RADIUS_MILES_US = 25;
/** ~25 mi — common default for EU searches. */
export const DEFAULT_RADIUS_KM_EU = 40;

export function kmToMiles(km: number): number {
  if (!Number.isFinite(km) || km <= 0) return DEFAULT_RADIUS_MILES_US;
  return Math.round(km * MILES_PER_KM);
}

export function milesToKm(miles: number): number {
  if (!Number.isFinite(miles) || miles <= 0) return DEFAULT_RADIUS_KM_EU;
  return Math.max(1, Math.round(miles / MILES_PER_KM));
}

export function parseMarketRegion(raw: string | null | undefined): MarketRegion {
  const v = (raw ?? "").trim().toLowerCase();
  return v === "eu" ? "eu" : "us";
}
