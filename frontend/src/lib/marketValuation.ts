import type { AggregatedListing } from "@/lib/inventoryFormat";
import { listingIdentityKey } from "@/lib/inventoryFormat";

export type MarketValuationBand = "great_deal" | "good_value" | "fair_price" | "above_market" | "overpriced";

export type MarketValuation = {
  band: MarketValuationBand;
  label: string;
  comparableCount: number;
  historicalComparableCount: number;
  externalComparableCount: number;
  baselinePrice: number;
  deltaAmount: number;
  deltaPercent: number;
  comparables: AggregatedListing[];
  trimPackageConfidenceScore: number;
  trimPackageConfidenceLabel: "Low" | "Medium" | "High";
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

function weightedMedian(values: Array<{ value: number; weight: number }>): number | null {
  const filtered = values
    .filter((entry) => Number.isFinite(entry.value) && entry.value > 0 && Number.isFinite(entry.weight) && entry.weight > 0)
    .sort((a, b) => a.value - b.value);
  if (filtered.length === 0) return null;
  const totalWeight = filtered.reduce((sum, entry) => sum + entry.weight, 0);
  if (!Number.isFinite(totalWeight) || totalWeight <= 0) return null;
  const halfway = totalWeight / 2;
  let running = 0;
  for (const entry of filtered) {
    running += entry.weight;
    if (running >= halfway) return entry.value;
  }
  return filtered[filtered.length - 1]?.value ?? null;
}

function recencyWeight(observedAt: number | undefined, nowMs: number): number {
  if (!observedAt || !Number.isFinite(observedAt) || observedAt <= 0) return 0.45;
  const ageDays = Math.max(0, (nowMs - observedAt * 1000) / (1000 * 60 * 60 * 24));
  const halfLifeDays = 45;
  const weight = Math.pow(0.5, ageDays / halfLifeDays);
  return Math.max(0.2, Math.min(1, weight));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function mileageInMiles(listing: AggregatedListing): number | null {
  if (listing.usage_unit === "miles" && listing.usage_value != null && Number.isFinite(listing.usage_value)) {
    return listing.usage_value;
  }
  if (listing.mileage != null && Number.isFinite(listing.mileage)) return listing.mileage;
  return null;
}

function normalizedComparablePrice(base: AggregatedListing, candidate: AggregatedListing): number {
  if (candidate.price == null || !Number.isFinite(candidate.price) || candidate.price <= 0) return NaN;
  let adjusted = candidate.price;

  // Normalize cross-year comps to the base listing's model year.
  if (base.year != null && candidate.year != null && Number.isFinite(base.year) && Number.isFinite(candidate.year)) {
    const yearDelta = base.year - candidate.year;
    const yearAdjustmentPct = clamp(yearDelta * 0.025, -0.18, 0.18);
    adjusted = adjusted * (1 + yearAdjustmentPct);
  }

  // For used cars, normalize for mileage differences.
  const baseUsed = base.vehicle_condition === "used";
  const candidateUsed = candidate.vehicle_condition === "used";
  if (baseUsed && candidateUsed) {
    const baseMiles = mileageInMiles(base);
    const candidateMiles = mileageInMiles(candidate);
    if (baseMiles != null && candidateMiles != null) {
      // Positive delta means candidate has more miles and should be adjusted up.
      const mileageDelta = candidateMiles - baseMiles;
      const perMileRate = clamp(adjusted * 0.000004, 0.05, 0.35);
      const rawAdjustment = mileageDelta * perMileRate;
      const maxAdjustment = adjusted * 0.18;
      adjusted += clamp(rawAdjustment, -maxAdjustment, maxAdjustment);
    }
  }

  return adjusted;
}

function trimPackageConfidence(
  listing: AggregatedListing,
  currentComparableCount: number,
  historicalComparableCount: number,
  externalComparableCount: number,
): { score: number; label: "Low" | "Medium" | "High" } {
  const sampleScore = Math.min(1, (currentComparableCount + historicalComparableCount + externalComparableCount) / 20);
  const currentScore = Math.min(1, currentComparableCount / 8);
  const historicalScore = Math.min(1, historicalComparableCount / 10);
  const externalScore = Math.min(1, externalComparableCount / 3);
  const specFields = [listing.trim, listing.body_style, listing.drivetrain, listing.engine, listing.transmission, listing.fuel_type];
  const specCompleteness = specFields.filter((value) => normalizedText(value).length > 0).length / specFields.length;
  const featureSignal = Math.min(1, (listing.feature_highlights?.length ?? 0) / 3);
  const score = Math.round((sampleScore * 0.3 + currentScore * 0.2 + historicalScore * 0.15 + externalScore * 0.1 + specCompleteness * 0.15 + featureSignal * 0.1) * 100);
  if (score >= 75) return { score, label: "High" };
  if (score >= 50) return { score, label: "Medium" };
  return { score, label: "Low" };
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
  const nowMs = Date.now();
  for (const listing of listings) {
    if (listing.price == null || Number.isNaN(listing.price)) continue;
    if (!listing.make || !listing.model) continue;
    const comparables = findComparables(listing, listings);
    const normalizedComparablePrices = comparables
      .map((c) => normalizedComparablePrice(listing, c))
      .filter((value) => Number.isFinite(value) && value > 0);
    const historicalPrices = (listing.historical_market_prices ?? []).filter(
      (value) => Number.isFinite(value) && value > 0,
    );
    const historicalPoints = (listing.historical_market_price_points ?? [])
      .map((point) => ({ price: point.price, observedAt: point.observed_at }))
      .filter((point) => point.price != null && Number.isFinite(point.price) && point.price > 0);
    const externalValues = [
      listing.external_retail_value,
      listing.external_valuation_range_low,
      listing.external_valuation_range_high,
    ].filter((value) => value != null && Number.isFinite(value) && value > 0) as number[];
    const weightedSamples: Array<{ value: number; weight: number }> = [
      ...normalizedComparablePrices.map((value) => ({ value, weight: 1 })),
      ...historicalPoints.map((point) => ({ value: point.price!, weight: recencyWeight(point.observedAt, nowMs) })),
      ...externalValues.map((value, idx) => ({ value, weight: idx === 0 ? 0.7 : 0.45 })),
    ];
    if (historicalPoints.length === 0 && historicalPrices.length > 0) {
      weightedSamples.push(...historicalPrices.map((value) => ({ value, weight: 0.45 })));
    }
    const combinedPrices = [...normalizedComparablePrices, ...historicalPrices, ...externalValues];
    if (combinedPrices.length < 3) continue;
    const baselinePrice = weightedMedian(weightedSamples) ?? median(combinedPrices);
    if (!Number.isFinite(baselinePrice) || baselinePrice <= 0) continue;
    const deltaAmount = listing.price - baselinePrice;
    const deltaPercent = deltaAmount / baselinePrice;
    const confidence = trimPackageConfidence(
      listing,
      normalizedComparablePrices.length,
      historicalPrices.length,
      externalValues.length,
    );
    valuations.set(listingIdentityKey(listing), {
      ...valuationBand(deltaPercent),
      comparableCount: combinedPrices.length,
      historicalComparableCount: historicalPrices.length,
      externalComparableCount: externalValues.length,
      baselinePrice,
      deltaAmount,
      deltaPercent,
      comparables,
      trimPackageConfidenceScore: confidence.score,
      trimPackageConfidenceLabel: confidence.label,
    });
  }
  return valuations;
}
