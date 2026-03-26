import type { VehicleListing } from "@/types/inventory";

export type AggregatedListing = VehicleListing & {
  dealership: string;
  dealership_website: string;
};

export function formatMoney(n: number | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

export function locationBadge(v: AggregatedListing) {
  if (v.is_in_transit) return "In transit";
  if (v.is_offsite || v.is_shared_inventory) return "Shared / off-site";
  if (v.is_in_stock) return "On lot";
  return v.availability_status ?? null;
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
  if (span <= 0) return fallback;
  return Math.max(fallback, Math.round(span / 100));
}
