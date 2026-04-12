import type { AggregatedListing } from "@/lib/inventoryFormat";
import { buildMarketValuationMap } from "@/lib/marketValuation";
import { listingIdentityKey } from "@/lib/inventoryFormat";

/** Escape a value for RFC 4180-style CSV (comma-separated). */
export function escapeCsvField(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

const CSV_HEADERS = [
  "dealership",
  "dealership_website",
  "vehicle_category",
  "year",
  "make",
  "model",
  "trim",
  "body_style",
  "drivetrain",
  "engine",
  "transmission",
  "fuel_type",
  "exterior_color",
  "price",
  "msrp",
  "dealer_discount",
  "mileage",
  "usage_value",
  "usage_unit",
  "days_on_lot",
  "stock_date",
  "history_seen_count",
  "history_days_tracked",
  "history_previous_price",
  "history_lowest_price",
  "history_highest_price",
  "history_price_change",
  "history_price_change_since_first",
  "market_valuation",
  "market_comparable_count",
  "market_median_price",
  "market_price_delta",
  "market_price_delta_percent",
  "incentive_labels",
  "feature_highlights",
  "vin",
  "vehicle_identifier",
  "vehicle_condition",
  "listing_url",
  "raw_title",
] as const;

/** Build CSV text from currently visible listings (e.g. filtered + sorted). */
export function listingsToCsv(listings: AggregatedListing[]): string {
  const lines: string[] = [CSV_HEADERS.join(",")];
  const valuationMap = buildMarketValuationMap(listings);
  for (const v of listings) {
    const valuation = valuationMap.get(listingIdentityKey(v));
    const row = [
      v.dealership ?? "",
      v.dealership_website ?? "",
      v.vehicle_category ?? "",
      v.year != null ? String(v.year) : "",
      v.make ?? "",
      v.model ?? "",
      v.trim ?? "",
      v.body_style ?? "",
      v.drivetrain ?? "",
      v.engine ?? "",
      v.transmission ?? "",
      v.fuel_type ?? "",
      v.exterior_color ?? "",
      v.price != null ? String(v.price) : "",
      v.msrp != null ? String(v.msrp) : "",
      v.dealer_discount != null ? String(v.dealer_discount) : "",
      v.mileage != null ? String(v.mileage) : "",
      v.usage_value != null ? String(v.usage_value) : "",
      v.usage_unit ?? "",
      v.days_on_lot != null ? String(v.days_on_lot) : "",
      v.stock_date ?? "",
      v.history_seen_count != null ? String(v.history_seen_count) : "",
      v.history_days_tracked != null ? String(v.history_days_tracked) : "",
      v.history_previous_price != null ? String(v.history_previous_price) : "",
      v.history_lowest_price != null ? String(v.history_lowest_price) : "",
      v.history_highest_price != null ? String(v.history_highest_price) : "",
      v.history_price_change != null ? String(v.history_price_change) : "",
      v.history_price_change_since_first != null ? String(v.history_price_change_since_first) : "",
      valuation?.label ?? "",
      valuation != null ? String(valuation.comparableCount) : "",
      valuation != null ? String(valuation.baselinePrice) : "",
      valuation != null ? String(valuation.deltaAmount) : "",
      valuation != null ? String(valuation.deltaPercent) : "",
      (v.incentive_labels ?? []).join(" | "),
      (v.feature_highlights ?? []).join(" | "),
      v.vin ?? "",
      v.vehicle_identifier ?? "",
      v.vehicle_condition ?? "",
      v.listing_url ?? "",
      v.raw_title ?? "",
    ].map(escapeCsvField);
    lines.push(row.join(","));
  }
  return lines.join("\n");
}

/** Build TSV text (tab-separated values) from listings. */
export function listingsToTsv(listings: AggregatedListing[]): string {
  const valuationMap = buildMarketValuationMap(listings);
  const lines: string[] = [CSV_HEADERS.join("\t")];
  for (const v of listings) {
    const valuation = valuationMap.get(listingIdentityKey(v));
    const row = [
      v.dealership ?? "",
      v.dealership_website ?? "",
      v.vehicle_category ?? "",
      v.year != null ? String(v.year) : "",
      v.make ?? "",
      v.model ?? "",
      v.trim ?? "",
      v.body_style ?? "",
      v.drivetrain ?? "",
      v.engine ?? "",
      v.transmission ?? "",
      v.fuel_type ?? "",
      v.exterior_color ?? "",
      v.price != null ? String(v.price) : "",
      v.msrp != null ? String(v.msrp) : "",
      v.dealer_discount != null ? String(v.dealer_discount) : "",
      v.mileage != null ? String(v.mileage) : "",
      v.usage_value != null ? String(v.usage_value) : "",
      v.usage_unit ?? "",
      v.days_on_lot != null ? String(v.days_on_lot) : "",
      v.stock_date ?? "",
      v.history_seen_count != null ? String(v.history_seen_count) : "",
      v.history_days_tracked != null ? String(v.history_days_tracked) : "",
      v.history_previous_price != null ? String(v.history_previous_price) : "",
      v.history_lowest_price != null ? String(v.history_lowest_price) : "",
      v.history_highest_price != null ? String(v.history_highest_price) : "",
      v.history_price_change != null ? String(v.history_price_change) : "",
      v.history_price_change_since_first != null ? String(v.history_price_change_since_first) : "",
      valuation?.label ?? "",
      valuation != null ? String(valuation.comparableCount) : "",
      valuation != null ? String(valuation.baselinePrice) : "",
      valuation != null ? String(valuation.deltaAmount) : "",
      valuation != null ? String(valuation.deltaPercent) : "",
      (v.incentive_labels ?? []).join(" | "),
      (v.feature_highlights ?? []).join(" | "),
      v.vin ?? "",
      v.vehicle_identifier ?? "",
      v.vehicle_condition ?? "",
      v.listing_url ?? "",
      v.raw_title ?? "",
    ].map((field) => field.replace(/\t/g, " "));
    lines.push(row.join("\t"));
  }
  return lines.join("\n");
}

/** Build a JSON array of plain objects from listings (same fields as CSV). */
export function listingsToJson(listings: AggregatedListing[]): string {
  const valuationMap = buildMarketValuationMap(listings);
  const rows = listings.map((v) => {
    const valuation = valuationMap.get(listingIdentityKey(v));
    return {
      dealership: v.dealership ?? null,
      dealership_website: v.dealership_website ?? null,
      vehicle_category: v.vehicle_category ?? null,
      year: v.year ?? null,
      make: v.make ?? null,
      model: v.model ?? null,
      trim: v.trim ?? null,
      body_style: v.body_style ?? null,
      drivetrain: v.drivetrain ?? null,
      engine: v.engine ?? null,
      transmission: v.transmission ?? null,
      fuel_type: v.fuel_type ?? null,
      exterior_color: v.exterior_color ?? null,
      price: v.price ?? null,
      msrp: v.msrp ?? null,
      dealer_discount: v.dealer_discount ?? null,
      mileage: v.mileage ?? null,
      usage_value: v.usage_value ?? null,
      usage_unit: v.usage_unit ?? null,
      days_on_lot: v.days_on_lot ?? null,
      stock_date: v.stock_date ?? null,
      history_seen_count: v.history_seen_count ?? null,
      history_days_tracked: v.history_days_tracked ?? null,
      history_previous_price: v.history_previous_price ?? null,
      history_lowest_price: v.history_lowest_price ?? null,
      history_highest_price: v.history_highest_price ?? null,
      history_price_change: v.history_price_change ?? null,
      history_price_change_since_first: v.history_price_change_since_first ?? null,
      market_valuation: valuation?.label ?? null,
      market_comparable_count: valuation?.comparableCount ?? null,
      market_median_price: valuation?.baselinePrice ?? null,
      market_price_delta: valuation?.deltaAmount ?? null,
      market_price_delta_percent: valuation?.deltaPercent ?? null,
      incentive_labels: v.incentive_labels ?? [],
      feature_highlights: v.feature_highlights ?? [],
      vin: v.vin ?? null,
      vehicle_identifier: v.vehicle_identifier ?? null,
      vehicle_condition: v.vehicle_condition ?? null,
      listing_url: v.listing_url ?? null,
      raw_title: v.raw_title ?? null,
    };
  });
  return JSON.stringify(rows, null, 2);
}

export function downloadFile(filename: string, contents: string, mimeType: string): void {
  // Prepend UTF-8 BOM for CSV/TSV so Excel/Numbers open them correctly without encoding issues.
  const bom = mimeType.startsWith("text/") ? "\uFEFF" : "";
  const blob = new Blob([bom + contents], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadCsv(filename: string, contents: string): void {
  downloadFile(filename, contents, "text/csv");
}
