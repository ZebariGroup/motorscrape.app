import type { VehicleListing } from "@/types/inventory";

export type AggregatedListing = VehicleListing & {
  dealership: string;
  dealership_website: string;
};

export function formatMoney(n: number | null | undefined, emptyLabel = "—") {
  if (n == null || Number.isNaN(n)) return emptyLabel;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

/**
 * Format `observed_at` from the API for display. Backend stores Unix **seconds** (`time.time()`)
 * in `price_history`, but `new Date(n)` expects milliseconds — raw seconds look like dates in 1970.
 * Values ≥ 1e12 are treated as epoch milliseconds (e.g. `Date.now()`); smaller positive values as seconds.
 * ISO date strings pass through `Date` parsing.
 */
export function formatObservedAtForDisplay(value: string | number | undefined | null): string {
  if (value == null) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return "—";
    const ms = value < 1e12 ? value * 1000 : value;
    const date = new Date(ms);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
  }
  const s = String(value).trim();
  if (!s) return "—";
  if (/^-?\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    if (!Number.isFinite(n) || n <= 0) return "—";
    const ms = n < 1e12 ? n * 1000 : n;
    const date = new Date(ms);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
  }
  const date = new Date(s);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
}

export function locationBadge(v: AggregatedListing) {
  if (v.is_in_transit) return "In transit";
  if (v.is_offsite || v.is_shared_inventory) return "Shared / off-site";
  if (v.is_in_stock) return "On lot";
  return v.availability_status ?? null;
}

export function usageLabel(v: Partial<AggregatedListing>) {
  if (v.usage_value == null || v.usage_unit == null) return "—";
  return v.usage_unit === "hours"
    ? `${v.usage_value.toLocaleString()} hrs`
    : `${v.usage_value.toLocaleString()} mi`;
}

export function usageFieldLabel(v: Partial<AggregatedListing>) {
  return v.usage_unit === "hours" ? "Engine hours" : "Mileage";
}

export function identifierLabel(v: Partial<AggregatedListing>) {
  return v.vehicle_category === "boat" ? "Identifier" : "VIN";
}

export function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

export function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

/** Normalize dealer site URL for matching listing.dealership_website to DealershipProgress.website. */
export function dealerSiteKey(site: string): string {
  const t = (site || "").trim();
  if (!t) return "";
  try {
    const u = new URL(t.includes("://") ? t : `https://${t}`);
    return u.hostname.replace(/^www\./i, "").toLowerCase();
  } catch {
    return t
      .replace(/^https?:\/\//i, "")
      .replace(/^www\./i, "")
      .replace(/\/+$/, "")
      .split("/")[0]
      ?.toLowerCase() ?? "";
  }
}

export function listingIdentityKey(v: Partial<AggregatedListing>, fallback = ""): string {
  const keyParts = [
    dealerSiteKey(v.dealership_website ?? ""),
    (v.dealership ?? "").trim().toLowerCase(),
    (v.vehicle_identifier ?? "").trim().toLowerCase(),
    (v.vin ?? "").trim().toLowerCase(),
    (v.listing_url ?? "").trim().toLowerCase(),
    (v.raw_title ?? "").trim().toLowerCase(),
    v.year != null ? String(v.year) : "",
    (v.make ?? "").trim().toLowerCase(),
    (v.model ?? "").trim().toLowerCase(),
    (v.trim ?? "").trim().toLowerCase(),
    v.price != null ? String(v.price) : "",
    v.mileage != null ? String(v.mileage) : "",
  ].filter(Boolean);
  return keyParts.join("|") || fallback;
}

export function sliderStep(min: number, max: number, fallback: number) {
  const span = Math.max(0, max - min);
  if (span <= 0) return Math.max(1, fallback);
  return Math.max(1, Math.round(span / 120));
}
