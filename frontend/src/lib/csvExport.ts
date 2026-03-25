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
  "year",
  "make",
  "model",
  "trim",
  "price",
  "msrp",
  "dealer_discount",
  "mileage",
  "days_on_lot",
  "stock_date",
  "incentive_labels",
  "feature_highlights",
  "vin",
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
      v.year != null ? String(v.year) : "",
      v.make ?? "",
      v.model ?? "",
      v.trim ?? "",
      v.price != null ? String(v.price) : "",
      v.msrp != null ? String(v.msrp) : "",
      v.dealer_discount != null ? String(v.dealer_discount) : "",
      v.mileage != null ? String(v.mileage) : "",
      v.days_on_lot != null ? String(v.days_on_lot) : "",
      v.stock_date ?? "",
      (v.incentive_labels ?? []).join(" | "),
      (v.feature_highlights ?? []).join(" | "),
      v.vin ?? "",
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
