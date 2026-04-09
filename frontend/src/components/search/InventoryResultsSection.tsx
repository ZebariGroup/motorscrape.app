"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { resolveApiUrl } from "@/lib/apiBase";
import { downloadCsv, listingsToCsv } from "@/lib/csvExport";
import {
  formatMoney,
  formatObservedAtForDisplay,
  identifierLabel,
  listingIdentityKey,
  locationBadge,
  usageFieldLabel,
  usageLabel,
} from "@/lib/inventoryFormat";
import { buildMarketValuationMap } from "@/lib/marketValuation";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { ListingSortOrder } from "@/hooks/useSearchStream";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { MarketcheckDetails, MarketcheckDetailsResponse } from "@/types/inventory";

function featureChip(text: string, key: string) {
  const short =
    text.length > 36 ? `${text.slice(0, 34)}…` : text;
  return (
    <span
      key={key}
      className="max-w-full truncate rounded-md border border-white/25 bg-black/35 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white/95 shadow-sm backdrop-blur-sm sm:text-[11px]"
      title={text}
    >
      {short}
    </span>
  );
}

function leaseLabel(listing: AggregatedListing) {
  if (listing.lease_monthly_payment == null || Number.isNaN(listing.lease_monthly_payment)) return null;
  const payment = formatMoney(listing.lease_monthly_payment);
  if (listing.lease_term_months != null && listing.lease_term_months > 0) {
    return `${payment}/mo · ${listing.lease_term_months} mo lease`;
  }
  return `${payment}/mo lease`;
}

function historyPriceDeltaLabel(value: number | undefined) {
  if (value == null || Number.isNaN(value) || value === 0) return null;
  const prefix = value < 0 ? "Down" : "Up";
  return `${prefix} ${formatMoney(Math.abs(value))}`;
}

function listingMiles(listing: AggregatedListing) {
  if (listing.usage_unit === "miles" && listing.usage_value != null && !Number.isNaN(listing.usage_value)) {
    return listing.usage_value;
  }
  if (listing.mileage != null && !Number.isNaN(listing.mileage)) {
    return listing.mileage;
  }
  return null;
}

function buildPremiumReportHref(listing: AggregatedListing) {
  const vin = listing.vin ?? "";
  const params = new URLSearchParams();
  if (listing.raw_title) params.set("title", listing.raw_title);
  if (listing.dealership) params.set("dealer", listing.dealership);
  if (listing.price != null) params.set("price", String(listing.price));
  const miles = listingMiles(listing);
  if (miles != null) params.set("miles", String(miles));
  return `/reports/vehicle/${encodeURIComponent(vin)}${params.size > 0 ? `?${params.toString()}` : ""}`;
}

function valuationBadgeClasses(label: string) {
  switch (label) {
    case "Great deal":
      return "border-emerald-300/90 bg-emerald-500/95 text-white ring-white/20";
    case "Good value":
      return "border-teal-300/90 bg-teal-500/95 text-white ring-white/20";
    case "Fair price":
      return "border-zinc-300/90 bg-zinc-900/80 text-white ring-white/15";
    case "Above market":
      return "border-amber-300/90 bg-amber-500/95 text-white ring-white/20";
    default:
      return "border-rose-300/90 bg-rose-500/95 text-white ring-white/20";
  }
}

type Props = {
  listings: AggregatedListing[];
  filteredListings: AggregatedListing[];
  running: boolean;
  loadingInventoryCards: unknown[];
  sortOrder: ListingSortOrder;
  onSortOrderChange: (order: ListingSortOrder) => void;
  vehicleCategory: VehicleCategory;
  allowCsvExport?: boolean;
  activeDealerSummary?: string | null;
  activeDealerCount?: number;
  queuedDealerCount?: number;
  isAnonymous?: boolean;
  onSignupClick?: () => void;
  /** Merged onto the root section (e.g. grid order utilities). */
  className?: string;
  /** Shown when the grid is populated from a past search snapshot (not a live stream). */
  savedResultsNotice?: {
    title: string;
    body: string;
    onDismiss: () => void;
  } | null;
};

export function InventoryResultsSection({
  listings,
  filteredListings,
  running,
  loadingInventoryCards,
  sortOrder,
  onSortOrderChange,
  vehicleCategory,
  allowCsvExport = true,
  activeDealerSummary = null,
  activeDealerCount = 0,
  queuedDealerCount = 0,
  isAnonymous = false,
  onSignupClick,
  className = "",
  savedResultsNotice = null,
}: Props) {
  const [selectedListingIndex, setSelectedListingIndex] = useState<number | null>(null);
  const [marketcheckDetails, setMarketcheckDetails] = useState<Record<string, MarketcheckDetails | "loading" | "error">>({});
  const usageSortLabel = vehicleCategory === "boat" ? "Usage (low to high)" : "Mileage (low to high)";
  const effectiveSelectedListingIndex =
    selectedListingIndex == null || filteredListings.length === 0
      ? null
      : Math.min(selectedListingIndex, filteredListings.length - 1);
  const selectedListing =
    effectiveSelectedListingIndex != null ? (filteredListings[effectiveSelectedListingIndex] ?? null) : null;
  const valuationMap = useMemo(() => buildMarketValuationMap(listings), [listings]);
  const selectedValuation = selectedListing ? valuationMap.get(listingIdentityKey(selectedListing)) : undefined;
  const selectedMarketcheckDetails = selectedListing?.vin ? marketcheckDetails[selectedListing.vin] : undefined;
  const selectedLoadedMarketcheckDetails =
    selectedMarketcheckDetails &&
    selectedMarketcheckDetails !== "loading" &&
    selectedMarketcheckDetails !== "error"
      ? selectedMarketcheckDetails
      : null;
  const selectedMarketcheckSource = selectedLoadedMarketcheckDetails?.source ?? null;
  const selectedMarketcheckFeatureCount = selectedLoadedMarketcheckDetails?.marketcheck_features?.length ?? 0;
  const canViewPrevious = effectiveSelectedListingIndex != null && effectiveSelectedListingIndex > 0;
  const canViewNext =
    effectiveSelectedListingIndex != null && effectiveSelectedListingIndex < filteredListings.length - 1;

  const goToPreviousListing = useCallback(() => {
    setSelectedListingIndex((current) => (current != null && current > 0 ? current - 1 : current));
  }, []);

  const goToNextListing = useCallback(() => {
    setSelectedListingIndex((current) =>
      current != null && current < filteredListings.length - 1 ? current + 1 : current,
    );
  }, [filteredListings.length]);

  const handleLoadMarketcheckDetails = useCallback(async (listing: AggregatedListing, options?: { force?: boolean }) => {
    const vin = listing.vin?.trim();
    if (!vin) return;

    let shouldFetch = false;
    setMarketcheckDetails((prev) => {
      const current = prev[vin];
      if (!options?.force && current && current !== "error") return prev;
      shouldFetch = true;
      return { ...prev, [vin]: "loading" };
    });
    if (!shouldFetch) return;

    try {
      const params = new URLSearchParams({ vin });
      const miles = listingMiles(listing);
      if (miles != null) {
        params.set("miles", String(miles));
      }
      const res = await fetch(resolveApiUrl(`/vehicles/marketcheck-details?${params.toString()}`), {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to fetch details");
      const data = (await res.json()) as MarketcheckDetailsResponse;
      setMarketcheckDetails((prev) => ({
        ...prev,
        [vin]: {
          ...data.details,
          source: data.source ?? data.details.source ?? "marketcheck",
          message: data.message ?? data.details.message,
        },
      }));
    } catch {
      setMarketcheckDetails((prev) => ({ ...prev, [vin]: "error" }));
    }
  }, []);

  const openListingDetails = useCallback(
    (idx: number, options?: { loadMarketcheck?: boolean }) => {
      const listing = filteredListings[idx];
      if (!listing) return;
      setSelectedListingIndex(idx);
      if (options?.loadMarketcheck) {
        void handleLoadMarketcheckDetails(listing);
      }
    },
    [filteredListings, handleLoadMarketcheckDetails],
  );

  const listingModalTouchRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    if (effectiveSelectedListingIndex == null) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) {
        return;
      }
      if (event.key === "ArrowLeft" && canViewPrevious) {
        event.preventDefault();
        goToPreviousListing();
      } else if (event.key === "ArrowRight" && canViewNext) {
        event.preventDefault();
        goToNextListing();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canViewNext, canViewPrevious, effectiveSelectedListingIndex, goToNextListing, goToPreviousListing]);

  return (
    <section className={`lg:col-span-2 ${className}`.trim()}>
      {savedResultsNotice ? (
        <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-900/50 dark:bg-amber-950/35 dark:text-amber-100">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-medium">{savedResultsNotice.title}</p>
              <p className="mt-1 text-amber-900/90 dark:text-amber-200/90">{savedResultsNotice.body}</p>
            </div>
            <button
              type="button"
              onClick={savedResultsNotice.onDismiss}
              className="shrink-0 rounded-lg border border-amber-300/80 bg-white/80 px-3 py-1.5 text-xs font-medium text-amber-950 hover:bg-white dark:border-amber-800 dark:bg-zinc-900 dark:text-amber-100 dark:hover:bg-zinc-800"
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-baseline justify-between gap-4 sm:justify-start sm:gap-6">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Inventory</h2>
          <span className="text-sm text-zinc-500">
            {filteredListings.length}
            {filteredListings.length !== listings.length ? ` of ${listings.length}` : ""} vehicles
          </span>
        </div>
        {listings.length > 0 ? (
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
              <span className="shrink-0 font-medium text-zinc-700 dark:text-zinc-300">Sort by</span>
              <select
                value={sortOrder}
                onChange={(e) => onSortOrderChange(e.target.value as ListingSortOrder)}
                className="min-w-[11rem] rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900 shadow-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100"
              >
                <option value="year_desc">Year (newest)</option>
                <option value="price_asc">Price (low to high)</option>
                <option value="price_desc">Price (high to low)</option>
                <option value="mileage_asc">{usageSortLabel}</option>
                <option value="days_on_lot_desc">Days on lot (longest)</option>
                <option value="days_on_lot_asc">Days on lot (shortest)</option>
              </select>
            </label>
            <button
              type="button"
              disabled={filteredListings.length === 0 || !allowCsvExport}
              title={!allowCsvExport ? "CSV export is included with Standard, Pro, and Max Pro." : undefined}
              onClick={() => {
                const csv = listingsToCsv(filteredListings);
                const day = new Date().toISOString().slice(0, 10);
                downloadCsv(`motorscrape-inventory-${day}.csv`, csv);
              }}
              className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-800 shadow-sm transition hover:border-emerald-400 hover:text-emerald-800 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-emerald-600"
            >
              Download CSV
            </button>
          </div>
        ) : null}
      </div>
      {listings.length === 0 ? (
        running ? (
          <div className="space-y-4">
            <p className="text-sm text-zinc-500">
              Still scanning dealers... The full lineup stays visible while vehicle cards appear
              here as soon as each site yields a page of matches.
            </p>
            {activeDealerSummary ? (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {activeDealerSummary}
                {queuedDealerCount > 0 ? ` · ${queuedDealerCount} waiting for a worker` : ""}
                {activeDealerCount > 0 ? ` · ${activeDealerCount} scraping live` : ""}
              </p>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              {loadingInventoryCards.map((_, idx) => (
                <article
                  key={`inventory-loading-${idx}`}
                  className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950"
                >
                  <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-zinc-100/90 to-transparent motion-safe:animate-[shimmer_2.1s_infinite] dark:via-white/5" />
                  <div className="relative">
                    <div className="aspect-[16/10] w-full bg-zinc-100 dark:bg-zinc-900" />
                    <div className="space-y-3 p-4">
                      <div className="h-5 w-3/4 rounded bg-zinc-200 dark:bg-zinc-800" />
                      <div className="grid grid-cols-2 gap-2">
                        <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                        <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                        <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                        <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                      </div>
                      <div className="h-3 w-1/2 rounded bg-zinc-200 dark:bg-zinc-800" />
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm text-zinc-500">
            Results stream in as each dealership is scraped. Large dealer sites may take longer.
          </p>
        )
      ) : filteredListings.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 px-4 py-6 text-sm text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-300">
          No vehicles match the current result filters.
        </div>
      ) : (
        <div className="relative">
          <div className={`grid gap-4 sm:grid-cols-2 transition-all duration-500 ${isAnonymous ? "opacity-40 blur-[4px] pointer-events-none select-none" : ""}`}>
          {filteredListings.map((v, idx) => (
            (() => {
              const listingKey = listingIdentityKey(v, `${idx}`);
              const valuation = valuationMap.get(listingKey);
              return (
            <article
              key={`inventory-${listingKey}`}
              className="flex flex-row sm:flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950 cursor-pointer hover:border-emerald-300 hover:ring-1 hover:ring-emerald-500/20 transition-all"
              onClick={() => openListingDetails(idx)}
            >
              <div className="relative w-2/5 shrink-0 sm:w-full sm:aspect-[16/10] min-h-[128px] bg-zinc-100 dark:bg-zinc-900">
                {v.image_url ? (
                  <Image
                    src={v.image_url}
                    alt={v.raw_title ?? "Listing"}
                    className="absolute inset-0 h-full w-full object-cover"
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    unoptimized
                    fill
                  />
                ) : (
                  <div className="flex h-full min-h-[128px] items-center justify-center text-xs text-zinc-400">
                    No image
                  </div>
                )}
                {v.image_url ? (
                  <>
                    <div
                      className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/88 via-black/20 to-black/15"
                      aria-hidden
                    />
                    <div className="absolute left-1.5 top-1.5 sm:left-2 sm:top-2 flex flex-col items-start gap-1.5 sm:gap-2">
                      {valuation ? (
                        <div
                          className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold shadow-md ring-1 backdrop-blur-sm sm:text-xs ${valuationBadgeClasses(valuation.label)}`}
                        >
                          {valuation.label}
                        </div>
                      ) : null}
                      {v.dealer_discount != null && v.dealer_discount > 0 ? (
                        <div className="rounded-full bg-emerald-500/95 px-2 py-0.5 text-[11px] font-bold tracking-tight text-white shadow-lg ring-1 ring-white/20 sm:text-xs">
                          Save {formatMoney(v.dealer_discount)}
                        </div>
                      ) : null}
                      {v.history_days_tracked != null && v.history_days_tracked > 0 ? (
                        <div className="rounded-full bg-sky-600/90 px-2 py-0.5 text-[11px] font-semibold text-white shadow-md ring-1 ring-white/15 backdrop-blur-sm sm:text-xs">
                          Tracked {v.history_days_tracked}d
                        </div>
                      ) : null}
                    </div>
                    {v.days_on_lot != null ? (
                      <div className="absolute right-1.5 top-1.5 sm:right-2 sm:top-2 rounded-full bg-zinc-900/80 px-2 py-0.5 text-[11px] font-semibold text-white shadow-md ring-1 ring-white/15 backdrop-blur-sm sm:text-xs">
                        {v.days_on_lot}d on lot
                      </div>
                    ) : null}
                    {(v.feature_highlights?.length ?? 0) > 0 ? (
                      <div className="absolute right-1.5 top-[38%] flex max-w-[48%] -translate-y-1/2 flex-col items-end gap-1 sm:right-2">
                        {v.feature_highlights!.slice(0, 2).map((t, i) =>
                          featureChip(t, `feat-${i}`)
                        )}
                      </div>
                    ) : null}
                    <div className="absolute bottom-0 left-0 right-0 px-2 pb-1.5 pt-8 text-white sm:px-3 sm:pb-2">
                      <div className="flex items-end justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-base font-bold leading-none drop-shadow sm:text-xl">
                            {formatMoney(v.price, "Visit site for price")}
                          </div>
                          {v.msrp != null &&
                          v.price != null &&
                          v.msrp > v.price + 1 ? (
                            <div className="mt-0.5 text-[11px] text-white/80 line-through sm:text-xs">
                              {formatMoney(v.msrp)} MSRP
                            </div>
                          ) : null}
                        </div>
                        {leaseLabel(v) ? (
                          <div className="max-w-[48%] text-right text-[11px] font-semibold text-white/95 drop-shadow sm:text-xs">
                            {leaseLabel(v)}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </>
                ) : null}
              </div>
              <div className="flex flex-1 flex-col p-3 sm:p-4">
                <h3 className="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-50 line-clamp-2 sm:line-clamp-none">
                  {v.raw_title ??
                    ([v.year, v.make, v.model, v.trim].filter(Boolean).join(" ") || "Vehicle")}
                </h3>
                <dl className="mt-2 flex flex-col gap-1 text-[12px] sm:grid sm:grid-cols-2 sm:gap-x-2 sm:text-xs text-zinc-600 dark:text-zinc-400">
                  {!v.image_url ? (
                    <div className="flex justify-between sm:contents">
                      <dt className="font-medium text-zinc-500">Price</dt>
                      <dd className="font-semibold text-zinc-900 dark:text-zinc-50 sm:font-normal sm:text-zinc-600 sm:dark:text-zinc-400">
                        {formatMoney(v.price, "Visit site for price")}
                      </dd>
                    </div>
                  ) : null}
                  {!v.image_url && leaseLabel(v) ? (
                    <div className="flex justify-between sm:contents">
                      <dt className="font-medium text-zinc-500">Lease</dt>
                      <dd>{leaseLabel(v)}</dd>
                    </div>
                  ) : null}
                  <div className="flex justify-between sm:contents">
                    <dt className="font-medium text-zinc-500">{usageFieldLabel(v)}</dt>
                    <dd>{usageLabel(v)}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Condition</dt>
                    <dd>{v.vehicle_condition ?? "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">{identifierLabel(v)}</dt>
                    <dd className="truncate">{v.vehicle_identifier ?? v.vin ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between sm:contents">
                    <dt className="font-medium text-zinc-500">Dealer</dt>
                    <dd className="truncate text-right max-w-[120px] sm:max-w-none sm:text-left">{v.dealership}</dd>
                  </div>
                  {valuation ? (
                    <div className="hidden sm:contents">
                      <dt className="font-medium text-zinc-500">Market</dt>
                      <dd>{valuation.label}</dd>
                    </div>
                  ) : null}
                  {historyPriceDeltaLabel(v.history_price_change) ? (
                    <div className="hidden sm:contents">
                      <dt className="font-medium text-zinc-500">Price trend</dt>
                      <dd>{historyPriceDeltaLabel(v.history_price_change)}</dd>
                    </div>
                  ) : null}
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Availability</dt>
                    <dd>{locationBadge(v) ?? "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Engine</dt>
                    <dd className="truncate">{v.engine ?? "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Location</dt>
                    <dd className="truncate">{v.inventory_location ?? "—"}</dd>
                  </div>
                </dl>
                <div className="mt-auto flex flex-wrap gap-2 pt-3">
                  <button
                    type="button"
                    className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-900 transition hover:border-indigo-300 hover:bg-indigo-100 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100 dark:hover:bg-indigo-950/60"
                    onClick={(e) => {
                      e.stopPropagation();
                      openListingDetails(idx, { loadMarketcheck: Boolean(v.vin) });
                    }}
                  >
                    More details
                  </button>
                  {v.listing_url ? (
                    <a
                      href={v.listing_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-semibold text-emerald-700 underline-offset-2 hover:underline dark:text-emerald-400"
                      onClick={(e) => e.stopPropagation()}
                    >
                      View listing
                    </a>
                  ) : null}
                  <a
                    href={v.dealership_website}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-semibold text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Dealer site
                  </a>
                </div>
              </div>
            </article>
              );
            })()
          ))}
          </div>
          {isAnonymous && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-6 text-center">
              <div className="rounded-2xl border border-zinc-200 bg-white/95 p-6 shadow-xl backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-950/95 max-w-md">
                <h3 className="mb-2 text-lg font-bold text-zinc-900 dark:text-zinc-50">
                  Sign up to see results
                </h3>
                <p className="mb-5 text-sm text-zinc-600 dark:text-zinc-400">
                  Create a free account to get 15 free searches and 5 premium vehicle reports.
                </p>
                <button
                  onClick={onSignupClick}
                  className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-500"
                >
                  Create Free Account
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {selectedListing && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:p-6 sm:pt-[max(1.5rem,env(safe-area-inset-top))] sm:pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:pl-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
            onClick={() => setSelectedListingIndex(null)}
          />
          <div
            className="relative z-[101] w-full max-w-2xl touch-pan-y"
            onTouchStart={(e) => {
              if (e.touches.length !== 1) return;
              listingModalTouchRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
            }}
            onTouchEnd={(e) => {
              const start = listingModalTouchRef.current;
              listingModalTouchRef.current = null;
              if (!start || e.changedTouches.length !== 1) return;
              const t = e.changedTouches[0];
              const dx = t.clientX - start.x;
              const dy = t.clientY - start.y;
              const threshold = 56;
              if (Math.abs(dx) < threshold || Math.abs(dx) <= Math.abs(dy)) return;
              if (dx > 0) {
                goToPreviousListing();
              } else {
                goToNextListing();
              }
            }}
          >
            <button
              type="button"
              onClick={goToPreviousListing}
              disabled={!canViewPrevious}
              className="absolute left-1 top-[42%] z-[102] -translate-y-1/2 rounded-full bg-white/95 p-3 text-zinc-900 shadow-lg transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-950/95 dark:text-zinc-50 dark:hover:bg-zinc-950 sm:left-2 sm:top-1/2 md:left-3"
              aria-label="View previous listing"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
            <button
              type="button"
              onClick={goToNextListing}
              disabled={!canViewNext}
              className="absolute right-1 top-[42%] z-[102] -translate-y-1/2 rounded-full bg-white/95 p-3 text-zinc-900 shadow-lg transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-950/95 dark:text-zinc-50 dark:hover:bg-zinc-950 sm:right-2 sm:top-1/2 md:right-3"
              aria-label="View next listing"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
            <div className="relative flex max-h-[min(100dvh,calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-2rem))] w-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-zinc-200 dark:bg-zinc-950 dark:ring-zinc-800 sm:max-h-[min(100dvh,calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-3rem))]">
            <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 truncate pr-4">
                {selectedListing.raw_title ??
                  ([selectedListing.year, selectedListing.make, selectedListing.model, selectedListing.trim].filter(Boolean).join(" ") || "Vehicle Details")}
              </h2>
              <button
                onClick={() => setSelectedListingIndex(null)}
                className="rounded-full p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50 transition-colors"
                aria-label="Close details"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            
            <div className="modal-card-scroll flex-1 min-h-0 overflow-y-auto">
              {selectedListing.image_url ? (
                  <div className="relative w-full h-[40vh] bg-zinc-100 dark:bg-zinc-900">
                    <Image
                      src={selectedListing.image_url}
                      alt={selectedListing.raw_title ?? "Listing"}
                      className="object-contain"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      unoptimized
                      fill
                    />
                  </div>
              ) : (
                <div className="flex h-48 w-full items-center justify-center bg-zinc-100 text-sm text-zinc-400 dark:bg-zinc-900">
                  No image available
                </div>
              )}
              
              <div className="p-5 sm:p-6 space-y-6">
                <div className="flex flex-wrap items-baseline justify-between gap-4 border-b border-zinc-100 pb-4 dark:border-zinc-800/50">
                  <div>
                    <div className="text-3xl font-bold text-zinc-900 dark:text-zinc-50">
                      {formatMoney(selectedListing.price, "Visit site for price")}
                    </div>
                    {selectedListing.msrp != null &&
                    selectedListing.price != null &&
                    selectedListing.msrp > selectedListing.price + 1 ? (
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
                        <span className="line-through">
                          MSRP {formatMoney(selectedListing.msrp)}
                        </span>
                        {selectedListing.dealer_discount != null &&
                        selectedListing.dealer_discount > 0 ? (
                          <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                            Dealer savings {formatMoney(selectedListing.dealer_discount)}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                    {leaseLabel(selectedListing) ? (
                      <div className="mt-2 text-sm font-semibold text-sky-700 dark:text-sky-400">
                        Lease from {leaseLabel(selectedListing)}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {selectedListing.vehicle_condition && (
                      <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200 capitalize">
                        {selectedListing.vehicle_condition}
                      </span>
                    )}
                    {selectedListing.usage_value != null && (
                      <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
                        {usageLabel(selectedListing)}
                      </span>
                    )}
                    {selectedListing.days_on_lot != null ? (
                      <span className="rounded-full border border-amber-200/80 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-100">
                        {selectedListing.days_on_lot} days on lot
                      </span>
                    ) : null}
                    {selectedListing.history_days_tracked != null ? (
                      <span className="rounded-full border border-sky-200/80 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-900 dark:border-sky-800 dark:bg-sky-950/60 dark:text-sky-100">
                        Tracked {selectedListing.history_days_tracked} days
                      </span>
                    ) : null}
                    {selectedValuation ? (
                      <span
                        className={`rounded-full border px-2.5 py-1 text-xs font-medium ${selectedValuation.band === "great_deal" ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-100" : selectedValuation.band === "good_value" ? "border-teal-200 bg-teal-50 text-teal-900 dark:border-teal-800 dark:bg-teal-950/60 dark:text-teal-100" : selectedValuation.band === "fair_price" ? "border-zinc-200 bg-zinc-50 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100" : selectedValuation.band === "above_market" ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-100" : "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-100"}`}
                      >
                        {selectedValuation.label}
                      </span>
                    ) : null}
                  </div>
                </div>

                {selectedListing.vin ? (
                  <div className="rounded-xl border border-indigo-200 bg-indigo-50/70 p-4 dark:border-indigo-900 dark:bg-indigo-950/30">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <h3 className="text-xs font-semibold uppercase tracking-wider text-indigo-800 dark:text-indigo-200">
                          Vehicle details
                        </h3>
                        <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">
                          Load VIN-based trim, specs, and pricing comparisons on demand after the scrape finishes.
                          MarketCheck is used when available, with VIN decoding as a fallback.
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            void handleLoadMarketcheckDetails(selectedListing, {
                              force: Boolean(selectedLoadedMarketcheckDetails),
                            })
                          }
                          className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500"
                        >
                          {selectedMarketcheckDetails === "loading"
                            ? "Loading MarketCheck details..."
                            : selectedLoadedMarketcheckDetails
                              ? selectedMarketcheckSource === "marketcheck"
                                ? "Refresh MarketCheck details"
                                : "Refresh vehicle details"
                              : "Load vehicle details"}
                        </button>
                        <a
                          href={buildPremiumReportHref(selectedListing)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 transition hover:border-amber-400 hover:bg-amber-50 dark:border-amber-800 dark:bg-zinc-950 dark:text-amber-100 dark:hover:bg-amber-950/40"
                        >
                          Open premium report
                        </a>
                      </div>
                    </div>

                    {selectedMarketcheckDetails === "error" ? (
                      <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
                        MarketCheck details could not be loaded for this VIN right now. You can try again.
                      </div>
                    ) : null}

                    {selectedLoadedMarketcheckDetails ? (
                      <>
                        {selectedLoadedMarketcheckDetails.message &&
                        selectedMarketcheckSource !== "marketcheck" ? (
                          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                            {selectedLoadedMarketcheckDetails.message}
                          </div>
                        ) : null}

                        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                          {selectedLoadedMarketcheckDetails.marketcheck_trim ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Decoded trim <span className="font-semibold">{selectedLoadedMarketcheckDetails.marketcheck_trim}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.year != null ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Decoded year <span className="font-semibold">{selectedLoadedMarketcheckDetails.year}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.make || selectedLoadedMarketcheckDetails.model ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Decoded vehicle{" "}
                              <span className="font-semibold">
                                {[selectedLoadedMarketcheckDetails.make, selectedLoadedMarketcheckDetails.model].filter(Boolean).join(" ")}
                              </span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.body_style ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Body style <span className="font-semibold">{selectedLoadedMarketcheckDetails.body_style}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.drivetrain ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Drivetrain <span className="font-semibold">{selectedLoadedMarketcheckDetails.drivetrain}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.transmission ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Transmission <span className="font-semibold">{selectedLoadedMarketcheckDetails.transmission}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.fuel_type ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Fuel type <span className="font-semibold">{selectedLoadedMarketcheckDetails.fuel_type}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.engine ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Engine <span className="font-semibold">{selectedLoadedMarketcheckDetails.engine}</span>
                            </p>
                          ) : null}
                          {selectedLoadedMarketcheckDetails.estimated_market_value != null ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              MarketCheck value{" "}
                              <span className="font-semibold">{formatMoney(selectedLoadedMarketcheckDetails.estimated_market_value)}</span>
                            </p>
                          ) : null}
                          {selectedMarketcheckFeatureCount > 0 ? (
                            <p className="text-zinc-700 dark:text-zinc-300">
                              Decoded features <span className="font-semibold">{selectedMarketcheckFeatureCount}</span>
                            </p>
                          ) : null}
                        </div>

                        {selectedLoadedMarketcheckDetails.estimated_market_value != null && selectedListing.price != null ? (
                          <div className="mt-4 rounded-lg border border-indigo-200/70 bg-white/80 px-4 py-3 text-sm text-zinc-700 shadow-sm dark:border-indigo-900/40 dark:bg-zinc-950/60 dark:text-zinc-300">
                            MarketCheck valuation:{" "}
                            <span className="font-semibold">
                              {selectedListing.price < selectedLoadedMarketcheckDetails.estimated_market_value
                                ? `${formatMoney(selectedLoadedMarketcheckDetails.estimated_market_value - selectedListing.price)} below`
                                : `${formatMoney(selectedListing.price - selectedLoadedMarketcheckDetails.estimated_market_value)} above`}
                            </span>{" "}
                            the estimated market value of{" "}
                            <span className="font-semibold">
                              {formatMoney(selectedLoadedMarketcheckDetails.estimated_market_value)}
                            </span>
                            .
                          </div>
                        ) : null}

                        {selectedMarketcheckFeatureCount > 0 ? (
                          <div className="mt-4">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-indigo-800 dark:text-indigo-200">
                              Decoded features
                            </h4>
                            <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                              {selectedLoadedMarketcheckDetails.marketcheck_features?.map((feat, i) => (
                                <li
                                  key={`marketcheck-detail-${i}`}
                                  className="rounded-lg border border-indigo-200/70 bg-white/80 px-3 py-2 text-xs text-zinc-800 dark:border-indigo-900/40 dark:bg-zinc-950/60 dark:text-zinc-200"
                                >
                                  {feat}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <div className="mt-4 rounded-lg border border-dashed border-indigo-300/80 bg-white/70 px-4 py-3 text-sm text-zinc-700 dark:border-indigo-900 dark:bg-zinc-950/40 dark:text-zinc-300">
                        Use <span className="font-semibold">Load vehicle details</span> to pull VIN-based trim, specs, features, and a pricing comparison for this vehicle.
                      </div>
                    )}

                    <div className="mt-4 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <h4 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                            Premium MarketCheck report
                          </h4>
                          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                            Open a printable report page with historical listings and a PDF-friendly layout.
                          </p>
                        </div>
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                          Premium
                        </span>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2">
                        <a
                          href={buildPremiumReportHref(selectedListing)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full bg-amber-500 px-5 py-2 text-sm font-bold text-white shadow-md transition-colors hover:bg-amber-600"
                        >
                          Open premium report
                        </a>
                        <p className="self-center text-xs text-zinc-500 dark:text-zinc-400">
                          The report page includes a Download PDF / Print action.
                        </p>
                      </div>
                    </div>
                  </div>
                ) : null}

                {selectedValuation ? (
                  <div className="rounded-xl border border-zinc-200 bg-zinc-50/70 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Local market valuation
                    </h3>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Market position <span className="font-semibold">{selectedValuation.label}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Comparable listings <span className="font-semibold">{selectedValuation.comparableCount}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Trim/Package confidence{" "}
                        <span className="font-semibold">
                          {selectedValuation.trimPackageConfidenceLabel} ({selectedValuation.trimPackageConfidenceScore}/100)
                        </span>
                      </p>
                      {selectedValuation.historicalComparableCount > 0 ? (
                        <p className="text-zinc-700 dark:text-zinc-300">
                          Historical comps{" "}
                          <span className="font-semibold">{selectedValuation.historicalComparableCount}</span>
                        </p>
                      ) : null}
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Local median <span className="font-semibold">{formatMoney(selectedValuation.baselinePrice)}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Difference{" "}
                        <span className="font-semibold">
                          {selectedValuation.deltaAmount < 0 ? "-" : "+"}
                          {formatMoney(Math.abs(selectedValuation.deltaAmount))}
                        </span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300 sm:col-span-2">
                        Relative to local median{" "}
                        <span className="font-semibold">
                          {(selectedValuation.deltaPercent * 100).toFixed(1)}%
                        </span>
                      </p>
                    </div>
                    {selectedValuation.comparables && selectedValuation.comparables.length > 0 && (
                      <div className="mt-4 border-t border-zinc-200/60 pt-4 dark:border-zinc-700/60">
                        <p className="text-xs text-zinc-600 dark:text-zinc-400 mb-3 leading-relaxed">
                          This vehicle is priced <strong>{Math.abs(selectedValuation.deltaPercent * 100).toFixed(1)}% {selectedValuation.deltaAmount < 0 ? "below" : "above"}</strong> the local median price of <strong>{formatMoney(selectedValuation.baselinePrice)}</strong>. 
                          We compared it against <strong>{selectedValuation.comparableCount}</strong> similar vehicles from current and prior tracked searches, with newer observations weighted more heavily.
                        </p>
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-2">
                          Comparable Vehicles
                        </h4>
                        {(() => {
                          const sortedComparables = [...selectedValuation.comparables].sort(
                            (a, b) => (a.price ?? Number.POSITIVE_INFINITY) - (b.price ?? Number.POSITIVE_INFINITY),
                          );
                          return (
                        <ul className="grid gap-2 max-h-[200px] overflow-y-auto pr-2 custom-scrollbar">
                          {sortedComparables.slice(0, 10).map((comp, idx) => {
                            const compIdx = filteredListings.findIndex(l => listingIdentityKey(l) === listingIdentityKey(comp));
                            const isClickable = compIdx !== -1;
                            return (
                              <li 
                                key={`comp-${idx}`} 
                                className={`rounded-lg border border-zinc-200/70 bg-white/80 px-3 py-2 text-xs text-zinc-800 dark:border-zinc-700/50 dark:bg-zinc-950/40 dark:text-zinc-200 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-1 ${isClickable ? 'cursor-pointer hover:border-emerald-300 hover:ring-1 hover:ring-emerald-500/20 transition-all' : ''}`}
                                onClick={isClickable ? () => setSelectedListingIndex(compIdx) : undefined}
                              >
                                <div className="truncate pr-2">
                                  <span className="font-medium">{comp.year} {comp.make} {comp.model}</span>
                                  {comp.trim && <span className="text-zinc-500 dark:text-zinc-400 ml-1">{comp.trim}</span>}
                                </div>
                                <div className="flex items-center justify-between sm:justify-end gap-2 shrink-0">
                                  {comp.dealership && (
                                    <span className="text-[11px] text-zinc-400 dark:text-zinc-500 truncate max-w-[100px]">
                                      {comp.dealership}
                                    </span>
                                  )}
                                  <span className="font-semibold">{formatMoney(comp.price)}</span>
                                </div>
                              </li>
                            );
                          })}
                          {sortedComparables.length > 10 && (
                            <li className="text-xs text-center text-zinc-500 dark:text-zinc-400 py-1">
                              + {sortedComparables.length - 10} more
                            </li>
                          )}
                        </ul>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                ) : null}

                {selectedListing.history_seen_count != null && selectedListing.history_seen_count > 0 ? (
                  <div className="rounded-xl border border-sky-200 bg-sky-50/70 p-4 dark:border-sky-900 dark:bg-sky-950/30">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-sky-800 dark:text-sky-200">
                      Cross-run tracking
                    </h3>
                    <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Seen in <span className="font-semibold">{selectedListing.history_seen_count}</span> completed searches
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        First seen{" "}
                        <span className="font-semibold">{formatObservedAtForDisplay(selectedListing.history_first_seen_at)}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Last seen{" "}
                        <span className="font-semibold">{formatObservedAtForDisplay(selectedListing.history_last_seen_at)}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Previous price{" "}
                        <span className="font-semibold">{formatMoney(selectedListing.history_previous_price)}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Lowest tracked{" "}
                        <span className="font-semibold">{formatMoney(selectedListing.history_lowest_price)}</span>
                      </p>
                      <p className="text-zinc-700 dark:text-zinc-300">
                        Highest tracked{" "}
                        <span className="font-semibold">{formatMoney(selectedListing.history_highest_price)}</span>
                      </p>
                      {historyPriceDeltaLabel(selectedListing.history_price_change) ? (
                        <p className="text-zinc-700 dark:text-zinc-300">
                          Since previous run{" "}
                          <span className="font-semibold">{historyPriceDeltaLabel(selectedListing.history_price_change)}</span>
                        </p>
                      ) : null}
                      {historyPriceDeltaLabel(selectedListing.history_price_change_since_first) ? (
                        <p className="text-zinc-700 dark:text-zinc-300">
                          Since first seen{" "}
                          <span className="font-semibold">
                            {historyPriceDeltaLabel(selectedListing.history_price_change_since_first)}
                          </span>
                        </p>
                      ) : null}
                    </div>
                    {(selectedListing.price_history?.length ?? 0) > 0 ? (
                      <div className="mt-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-sky-800 dark:text-sky-200">
                          Recent observed prices
                        </h4>
                        <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                          {selectedListing.price_history!.slice(-6).reverse().map((point, index) => (
                            <li
                              key={`${point.observed_at ?? "point"}-${index}`}
                              className="rounded-lg border border-sky-200/70 bg-white/80 px-3 py-2 text-xs text-zinc-800 dark:border-sky-900 dark:bg-zinc-950/40 dark:text-zinc-100"
                            >
                              <span className="font-medium">{formatObservedAtForDisplay(point.observed_at)}</span>
                              {" · "}
                              <span>{formatMoney(point.price)}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {(selectedListing.incentive_labels?.length ?? 0) > 0 ? (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Incentives &amp; rebates
                    </h3>
                    <ul className="flex flex-wrap gap-2">
                      {selectedListing.incentive_labels!.map((label, i) => (
                        <li
                          key={`inc-${i}`}
                          className="rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-100"
                        >
                          {label}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {(selectedListing.feature_highlights?.length ?? 0) > 0 ? (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Packages &amp; features
                    </h3>
                    <ul className="grid gap-2 sm:grid-cols-2">
                      {selectedListing.feature_highlights?.map((line, i) => (
                        <li
                          key={`feat-${i}`}
                          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                        >
                          {line}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {selectedListing.stock_date ? (
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Stock date (as listed):{" "}
                    <span className="font-medium text-zinc-700 dark:text-zinc-300">
                      {selectedListing.stock_date}
                    </span>
                  </p>
                ) : null}

                <div className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                      {identifierLabel(selectedListing)}
                    </dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100 break-all">
                      {selectedListing.vehicle_identifier ?? selectedListing.vin ?? "—"}
                    </dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Body Style</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.body_style ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Exterior Color</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.exterior_color ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Engine</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.engine ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Trim</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.trim || "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Drivetrain</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.drivetrain ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Transmission</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.transmission ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Fuel Type</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.fuel_type ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Availability</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{locationBadge(selectedListing) ?? "—"}</dd>
                  </div>
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Location</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.inventory_location ?? "—"}</dd>
                  </div>
                </div>

                <div className="rounded-xl bg-zinc-50 p-4 dark:bg-zinc-900/50 space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Dealership</h3>
                  <p className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.dealership}</p>
                  <a
                    href={selectedListing.dealership_website}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block text-sm text-emerald-600 hover:text-emerald-700 hover:underline dark:text-emerald-400 dark:hover:text-emerald-300"
                  >
                    Visit dealer website &rarr;
                  </a>
                </div>

              </div>
            </div>
            
            {selectedListing.listing_url && (
              <div className="border-t border-zinc-200 bg-zinc-50 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] dark:border-zinc-800 dark:bg-zinc-900/30 sm:pb-4">
                <a
                  href={selectedListing.listing_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex w-full items-center justify-center rounded-lg bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 dark:focus:ring-offset-zinc-950"
                >
                  View Full Listing on Dealer Site
                </a>
              </div>
            )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
