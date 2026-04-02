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
  comparables: AggregatedListing[];
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

function tokenize(value: string | undefined): string[] {
  const normalized = normalizedText(value);
  if (!normalized) return [];
  return normalized
    .split(/[^a-z0-9]+/g)
    .map((token) => token.trim())
    .filter((token) => token.length >= 2);
}

function listingFeatureTokenSet(listing: AggregatedListing): Set<string> {
  const tokens = new Set<string>();
  const sources = [
    listing.trim,
    listing.body_style,
    listing.drivetrain,
    listing.engine,
    listing.transmission,
    listing.fuel_type,
    ...(listing.feature_highlights ?? []),
  ];
  for (const source of sources) {
    for (const token of tokenize(source)) tokens.add(token);
  }
  return tokens;
}

function tokenOverlapRatio(base: Set<string>, candidate: Set<string>): number {
  if (base.size === 0 || candidate.size === 0) return 0;
  let overlap = 0;
  for (const token of base) {
    if (candidate.has(token)) overlap += 1;
  }
  return overlap / base.size;
}

function listingSimilarity(base: AggregatedListing, candidate: AggregatedListing): number {
  const baseTokens = listingFeatureTokenSet(base);
  const candidateTokens = listingFeatureTokenSet(candidate);
  const tokenSimilarity = tokenOverlapRatio(baseTokens, candidateTokens);

  const exactTrimMatch =
    !!base.trim && !!candidate.trim && normalizedText(base.trim) === normalizedText(candidate.trim) ? 0.2 : 0;
  const sameBodyStyle =
    !!base.body_style &&
    !!candidate.body_style &&
    normalizedText(base.body_style) === normalizedText(candidate.body_style)
      ? 0.1
      : 0;
  const sameDrivetrain =
    !!base.drivetrain &&
    !!candidate.drivetrain &&
    normalizedText(base.drivetrain) === normalizedText(candidate.drivetrain)
      ? 0.1
      : 0;

  return tokenSimilarity + exactTrimMatch + sameBodyStyle + sameDrivetrain;
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
  {
    strictYear,
    strictTrim,
    strictSpecs,
    minFeatureSimilarity,
  }: {
    strictYear: boolean;
    strictTrim?: boolean;
    strictSpecs?: boolean;
    minFeatureSimilarity?: number;
  },
): boolean {
  if (normalizedText(base.vehicle_category) !== normalizedText(candidate.vehicle_category)) return false;
  if (normalizedText(base.make) !== normalizedText(candidate.make)) return false;
  if (normalizedText(base.model) !== normalizedText(candidate.model)) return false;
  if (strictYear && base.year != null && candidate.year != null && base.year !== candidate.year) return false;
  if (base.vehicle_condition && candidate.vehicle_condition && base.vehicle_condition !== candidate.vehicle_condition) return false;

  if (strictTrim && base.trim) {
    if (normalizedText(base.trim) !== normalizedText(candidate.trim)) return false;
  }

  if (strictSpecs) {
    const specFields: Array<keyof AggregatedListing> = [
      "body_style",
      "drivetrain",
      "engine",
      "transmission",
      "fuel_type",
    ];
    for (const specField of specFields) {
      const baseValue = normalizedText(base[specField] as string | undefined);
      const candidateValue = normalizedText(candidate[specField] as string | undefined);
      if (baseValue && candidateValue && baseValue !== candidateValue) return false;
    }
  }

  if (minFeatureSimilarity != null && minFeatureSimilarity > 0) {
    const baseTokens = listingFeatureTokenSet(base);
    if (baseTokens.size > 0) {
      const similarity = tokenOverlapRatio(baseTokens, listingFeatureTokenSet(candidate));
      if (similarity < minFeatureSimilarity) return false;
    }
  }

  return true;
}

function findComparables(base: AggregatedListing, listings: AggregatedListing[]): AggregatedListing[] {
  const withPrice = listings.filter((candidate) => candidate.price != null && !Number.isNaN(candidate.price));

  const strictYearTrimFeature = withPrice.filter(
    (candidate) =>
      isComparable(base, candidate, {
        strictYear: true,
        strictTrim: true,
        strictSpecs: true,
        minFeatureSimilarity: 0.35,
      }),
  );
  if (strictYearTrimFeature.length >= 3) {
    return strictYearTrimFeature
      .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
      .slice(0, 25);
  }

  const strictYearTrim = withPrice.filter(
    (candidate) =>
      isComparable(base, candidate, {
        strictYear: true,
        strictTrim: true,
        minFeatureSimilarity: 0.2,
      }),
  );
  if (strictYearTrim.length >= 3) {
    return strictYearTrim
      .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
      .slice(0, 25);
  }

  const strictYearSpecs = withPrice.filter(
    (candidate) =>
      isComparable(base, candidate, {
        strictYear: true,
        strictSpecs: true,
        minFeatureSimilarity: 0.25,
      }),
  );
  if (strictYearSpecs.length >= 3) {
    return strictYearSpecs
      .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
      .slice(0, 25);
  }

  const strictYear = withPrice.filter(
    (candidate) =>
      isComparable(base, candidate, { strictYear: true }),
  );
  if (strictYear.length >= 3) {
    return strictYear
      .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
      .slice(0, 25);
  }

  const relaxedYear = withPrice.filter(
    (candidate) =>
      isComparable(base, candidate, { strictYear: false, strictSpecs: true, minFeatureSimilarity: 0.2 }) &&
      (base.year == null || candidate.year == null || Math.abs(candidate.year - base.year) <= 1),
  );
  if (relaxedYear.length >= 3) {
    return relaxedYear
      .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
      .slice(0, 25);
  }

  return withPrice
    .filter((candidate) => isComparable(base, candidate, { strictYear: false }))
    .sort((a, b) => listingSimilarity(base, b) - listingSimilarity(base, a))
    .slice(0, 25);
}

export function buildMarketValuationMap(listings: AggregatedListing[]): Map<string, MarketValuation> {
  const valuations = new Map<string, MarketValuation>();
  for (const listing of listings) {
    if (listing.price == null || Number.isNaN(listing.price)) continue;
    if (!listing.make || !listing.model) continue;
    const comparables = findComparables(listing, listings);
    if (comparables.length < 3) continue;
    const prices = comparables.map((c) => c.price!);
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
      comparables,
    });
  }
  return valuations;
}
