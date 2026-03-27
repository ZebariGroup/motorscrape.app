import type { AggregatedListing } from "@/lib/inventoryFormat";

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
  "exterior_color",
  "price",
  "msrp",
  "dealer_discount",
  "mileage",
  "usage_value",
  "usage_unit",
  "days_on_lot",
  "stock_date",
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
  for (const v of listings) {
    const row = [
      v.dealership ?? "",
      v.dealership_website ?? "",
      v.vehicle_category ?? "",
      v.year != null ? String(v.year) : "",
      v.make ?? "",
      v.model ?? "",
      v.trim ?? "",
      v.body_style ?? "",
      v.exterior_color ?? "",
      v.price != null ? String(v.price) : "",
      v.msrp != null ? String(v.msrp) : "",
      v.dealer_discount != null ? String(v.dealer_discount) : "",
      v.mileage != null ? String(v.mileage) : "",
      v.usage_value != null ? String(v.usage_value) : "",
      v.usage_unit ?? "",
      v.days_on_lot != null ? String(v.days_on_lot) : "",
      v.stock_date ?? "",
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

export function downloadCsv(filename: string, contents: string): void {
  const blob = new Blob([contents], { type: "text/csv;charset=utf-8" });
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
