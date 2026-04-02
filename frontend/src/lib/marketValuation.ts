import type { AggregatedListing } from "@/lib/inventoryFormat";
import { listingIdentityKey } from "@/lib/inventoryFormat";

export type MarketValuationBand = "great_deal" | "good_value" | "fair_price" | "above_market" | "overpriced";

export type MarketValuation = {
  band: MarketValuationBand;
  label: string;
  comparableCount: number;
  baselinePrice: number;
  deltaAmount: number;
  deltaPercent: number;
};

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2;
  }
  return sorted[middle];
}

function normalizedText(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function valuationBand(deltaPercent: number): Pick<MarketValuation, "band" | "label"> {
  if (deltaPercent <= -0.12) return { band: "great_deal", label: "Great deal" };
  if (deltaPercent <= -0.05) return { band: "good_value", label: "Good value" };
  if (deltaPercent < 0.05) return { band: "fair_price", label: "Fair price" };
  if (deltaPercent < 0.12) return { band: "above_market", label: "Above market" };
  return { band: "overpriced", label: "Overpriced" };
}

function isComparable(
  base: AggregatedListing,
  candidate: AggregatedListing,
  { strictYear }: { strictYear: boolean },
): boolean {
  if (normalizedText(base.vehicle_category) !== normalizedText(candidate.vehicle_category)) return false;
  if (normalizedText(base.make) !== normalizedText(candidate.make)) return false;
  if (normalizedText(base.model) !== normalizedText(candidate.model)) return false;
  if (strictYear && base.year != null && candidate.year != null && base.year !== candidate.year) return false;
  if (base.vehicle_condition && candidate.vehicle_condition && base.vehicle_condition !== candidate.vehicle_condition) return false;
  return true;
}

function comparablePrices(base: AggregatedListing, listings: AggregatedListing[]): number[] {
  const strict = listings.filter(
    (candidate) =>
      candidate.price != null &&
      !Number.isNaN(candidate.price) &&
      isComparable(base, candidate, { strictYear: true }),
  );
  if (strict.length >= 3) return strict.map((candidate) => candidate.price!);

  const relaxedYear = listings.filter(
    (candidate) =>
      candidate.price != null &&
      !Number.isNaN(candidate.price) &&
      isComparable(base, candidate, { strictYear: false }) &&
      (base.year == null || candidate.year == null || Math.abs(candidate.year - base.year) <= 1),
  );
  if (relaxedYear.length >= 3) return relaxedYear.map((candidate) => candidate.price!);

  return listings
    .filter(
      (candidate) =>
        candidate.price != null &&
        !Number.isNaN(candidate.price) &&
        isComparable(base, candidate, { strictYear: false }),
    )
    .map((candidate) => candidate.price!);
}

export function buildMarketValuationMap(listings: AggregatedListing[]): Map<string, MarketValuation> {
  const valuations = new Map<string, MarketValuation>();
  for (const listing of listings) {
    if (listing.price == null || Number.isNaN(listing.price)) continue;
    if (!listing.make || !listing.model) continue;
    const prices = comparablePrices(listing, listings);
    if (prices.length < 3) continue;
    const baselinePrice = median(prices);
    if (!Number.isFinite(baselinePrice) || baselinePrice <= 0) continue;
    const deltaAmount = listing.price - baselinePrice;
    const deltaPercent = deltaAmount / baselinePrice;
    valuations.set(listingIdentityKey(listing), {
      ...valuationBand(deltaPercent),
      comparableCount: prices.length,
      baselinePrice,
      deltaAmount,
      deltaPercent,
    });
  }
  return valuations;
}
