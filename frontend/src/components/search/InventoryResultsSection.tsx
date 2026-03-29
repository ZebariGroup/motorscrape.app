"use client";

import { useEffect, useState } from "react";
import { downloadCsv, listingsToCsv } from "@/lib/csvExport";
import {
  formatMoney,
  identifierLabel,
  listingIdentityKey,
  locationBadge,
  usageFieldLabel,
  usageLabel,
} from "@/lib/inventoryFormat";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { ListingSortOrder } from "@/hooks/useSearchStream";
import type { VehicleCategory } from "@/lib/vehicleCatalog";

function featureChip(text: string, key: string) {
  const short =
    text.length > 36 ? `${text.slice(0, 34)}…` : text;
  return (
    <span
      key={key}
      className="max-w-full truncate rounded-md border border-white/25 bg-black/35 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-white/95 shadow-sm backdrop-blur-sm sm:text-[10px]"
      title={text}
    >
      {short}
    </span>
  );
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
  className = "",
  savedResultsNotice = null,
}: Props) {
  const [selectedListingIndex, setSelectedListingIndex] = useState<number | null>(null);
  const usageSortLabel = vehicleCategory === "boat" ? "Usage (low to high)" : "Mileage (low to high)";
  const effectiveSelectedListingIndex =
    selectedListingIndex == null || filteredListings.length === 0
      ? null
      : Math.min(selectedListingIndex, filteredListings.length - 1);
  const selectedListing =
    effectiveSelectedListingIndex != null ? (filteredListings[effectiveSelectedListingIndex] ?? null) : null;
  const canViewPrevious = effectiveSelectedListingIndex != null && effectiveSelectedListingIndex > 0;
  const canViewNext =
    effectiveSelectedListingIndex != null && effectiveSelectedListingIndex < filteredListings.length - 1;

  useEffect(() => {
    if (effectiveSelectedListingIndex == null) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" && canViewPrevious) {
        event.preventDefault();
        setSelectedListingIndex((current) => (current == null ? current : current - 1));
      }
      if (event.key === "ArrowRight" && canViewNext) {
        event.preventDefault();
        setSelectedListingIndex((current) => (current == null ? current : current + 1));
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canViewNext, canViewPrevious, effectiveSelectedListingIndex]);

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
              title={!allowCsvExport ? "CSV export is included with Standard and Premium." : undefined}
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
              Still scanning dealers… New cards appear as each site is contacted. Matches show here
              as soon as AI finishes a page.
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
        <div className="grid gap-4 sm:grid-cols-2">
          {filteredListings.map((v, idx) => (
            <article
              key={`inventory-${listingIdentityKey(v, `${idx}`)}`}
              className="flex flex-row sm:flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950 cursor-pointer hover:border-emerald-300 hover:ring-1 hover:ring-emerald-500/20 transition-all"
              onClick={() => setSelectedListingIndex(idx)}
            >
              <div className="relative w-2/5 shrink-0 sm:w-full sm:aspect-[16/10] min-h-[128px] bg-zinc-100 dark:bg-zinc-900">
                {v.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={v.image_url}
                    alt={v.raw_title ?? "Listing"}
                    className="absolute inset-0 h-full w-full object-cover"
                    loading="lazy"
                    referrerPolicy="no-referrer"
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
                    {v.dealer_discount != null && v.dealer_discount > 0 ? (
                      <div className="absolute left-1.5 top-1.5 sm:left-2 sm:top-2 rounded-full bg-emerald-500/95 px-2 py-0.5 text-[10px] font-bold tracking-tight text-white shadow-lg ring-1 ring-white/20 sm:text-xs">
                        Save {formatMoney(v.dealer_discount)}
                      </div>
                    ) : null}
                    {v.days_on_lot != null ? (
                      <div className="absolute right-1.5 top-1.5 sm:right-2 sm:top-2 rounded-full bg-zinc-900/80 px-2 py-0.5 text-[10px] font-semibold text-white shadow-md ring-1 ring-white/15 backdrop-blur-sm sm:text-xs">
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
                      <div className="text-base font-bold leading-none drop-shadow sm:text-xl">
                        {formatMoney(v.price, "Visit site for price")}
                      </div>
                      {v.msrp != null &&
                      v.price != null &&
                      v.msrp > v.price + 1 ? (
                        <div className="mt-0.5 text-[10px] text-white/80 line-through sm:text-xs">
                          {formatMoney(v.msrp)} MSRP
                        </div>
                      ) : null}
                    </div>
                  </>
                ) : null}
              </div>
              <div className="flex flex-1 flex-col p-3 sm:p-4">
                <h3 className="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-50 line-clamp-2 sm:line-clamp-none">
                  {v.raw_title ??
                    ([v.year, v.make, v.model, v.trim].filter(Boolean).join(" ") || "Vehicle")}
                </h3>
                <dl className="mt-2 flex flex-col gap-1 text-[11px] sm:grid sm:grid-cols-2 sm:gap-x-2 sm:text-xs text-zinc-600 dark:text-zinc-400">
                  {!v.image_url ? (
                    <div className="flex justify-between sm:contents">
                      <dt className="font-medium text-zinc-500">Price</dt>
                      <dd className="font-semibold text-zinc-900 dark:text-zinc-50 sm:font-normal sm:text-zinc-600 sm:dark:text-zinc-400">
                        {formatMoney(v.price, "Visit site for price")}
                      </dd>
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
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Availability</dt>
                    <dd>{locationBadge(v) ?? "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Location</dt>
                    <dd className="truncate">{v.inventory_location ?? "—"}</dd>
                  </div>
                </dl>
                <div className="mt-auto flex flex-wrap gap-2 pt-3">
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
          ))}
        </div>
      )}

      {selectedListing && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:p-6 sm:pt-[max(1.5rem,env(safe-area-inset-top))] sm:pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:pl-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
            onClick={() => setSelectedListingIndex(null)}
          />
          <button
            type="button"
            onClick={() => setSelectedListingIndex((current) => (current == null ? current : current - 1))}
            disabled={!canViewPrevious}
            className="absolute left-[max(0.5rem,env(safe-area-inset-left))] top-1/2 z-[101] -translate-y-1/2 rounded-full bg-white/95 p-3 text-zinc-900 shadow-lg transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-950/95 dark:text-zinc-50 dark:hover:bg-zinc-950 sm:left-[max(1rem,env(safe-area-inset-left))]"
            aria-label="View previous listing"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => setSelectedListingIndex((current) => (current == null ? current : current + 1))}
            disabled={!canViewNext}
            className="absolute right-[max(0.5rem,env(safe-area-inset-right))] top-1/2 z-[101] -translate-y-1/2 rounded-full bg-white/95 p-3 text-zinc-900 shadow-lg transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 dark:bg-zinc-950/95 dark:text-zinc-50 dark:hover:bg-zinc-950 sm:right-[max(1rem,env(safe-area-inset-right))]"
            aria-label="View next listing"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m9 18 6-6-6-6" />
            </svg>
          </button>
          <div className="relative flex max-h-[min(100dvh,calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-2rem))] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-zinc-200 dark:bg-zinc-950 dark:ring-zinc-800 sm:max-h-[min(100dvh,calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-3rem))]">
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
                <div className="w-full bg-zinc-100 dark:bg-zinc-900">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={selectedListing.image_url}
                    alt={selectedListing.raw_title ?? "Listing"}
                    className="w-full h-auto max-h-[40vh] object-contain"
                    loading="lazy"
                    referrerPolicy="no-referrer"
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
                  </div>
                </div>

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
                      {selectedListing.feature_highlights!.map((line, i) => (
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
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Trim</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{selectedListing.trim ?? "—"}</dd>
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
      )}
    </section>
  );
}
