"use client";

import { useState } from "react";
import { formatMoney, locationBadge } from "@/lib/inventoryFormat";
import type { AggregatedListing } from "@/lib/inventoryFormat";

type Props = {
  listings: AggregatedListing[];
  filteredListings: AggregatedListing[];
  running: boolean;
  loadingInventoryCards: unknown[];
};

export function InventoryResultsSection({
  listings,
  filteredListings,
  running,
  loadingInventoryCards,
}: Props) {
  const [selectedListing, setSelectedListing] = useState<AggregatedListing | null>(null);

  return (
    <section className="lg:col-span-2">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Inventory</h2>
        <span className="text-sm text-zinc-500">
          {filteredListings.length}
          {filteredListings.length !== listings.length ? ` of ${listings.length}` : ""} vehicles
        </span>
      </div>
      {listings.length === 0 ? (
        running ? (
          <div className="space-y-4">
            <p className="text-sm text-zinc-500">
              Still scanning dealers… New cards appear as each site is contacted. Matches show here
              as soon as AI finishes a page.
            </p>
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
              key={`${v.dealership}-${v.vin ?? v.listing_url ?? v.raw_title ?? idx}`}
              className="flex flex-row sm:flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950 cursor-pointer hover:border-emerald-300 hover:ring-1 hover:ring-emerald-500/20 transition-all"
              onClick={() => setSelectedListing(v)}
            >
              <div className="relative w-2/5 shrink-0 sm:w-full sm:aspect-[16/10] bg-zinc-100 dark:bg-zinc-900">
                {v.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={v.image_url}
                    alt={v.raw_title ?? "Vehicle"}
                    className="absolute inset-0 h-full w-full object-cover"
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-zinc-400">
                    No image
                  </div>
                )}
              </div>
              <div className="flex flex-1 flex-col p-3 sm:p-4">
                <h3 className="text-sm sm:text-base font-semibold text-zinc-900 dark:text-zinc-50 line-clamp-2 sm:line-clamp-none">
                  {v.raw_title ??
                    ([v.year, v.make, v.model, v.trim].filter(Boolean).join(" ") || "Vehicle")}
                </h3>
                <dl className="mt-2 flex flex-col gap-1 text-[11px] sm:grid sm:grid-cols-2 sm:gap-x-2 sm:text-xs text-zinc-600 dark:text-zinc-400">
                  <div className="flex justify-between sm:contents">
                    <dt className="font-medium text-zinc-500">Price</dt>
                    <dd className="font-semibold text-zinc-900 dark:text-zinc-50 sm:font-normal sm:text-zinc-600 sm:dark:text-zinc-400">{formatMoney(v.price)}</dd>
                  </div>
                  <div className="flex justify-between sm:contents">
                    <dt className="font-medium text-zinc-500">Mileage</dt>
                    <dd>{v.mileage != null ? `${v.mileage.toLocaleString()} mi` : "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">Condition</dt>
                    <dd>{v.vehicle_condition ?? "—"}</dd>
                  </div>
                  <div className="hidden sm:contents">
                    <dt className="font-medium text-zinc-500">VIN</dt>
                    <dd className="truncate">{v.vin ?? "—"}</dd>
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
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
          <div 
            className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity" 
            onClick={() => setSelectedListing(null)} 
          />
          <div className="relative flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-zinc-950 ring-1 ring-zinc-200 dark:ring-zinc-800">
            <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 truncate pr-4">
                {selectedListing.raw_title ??
                  ([selectedListing.year, selectedListing.make, selectedListing.model, selectedListing.trim].filter(Boolean).join(" ") || "Vehicle Details")}
              </h2>
              <button
                onClick={() => setSelectedListing(null)}
                className="rounded-full p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50 transition-colors"
                aria-label="Close details"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto">
              {selectedListing.image_url ? (
                <div className="w-full bg-zinc-100 dark:bg-zinc-900">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={selectedListing.image_url}
                    alt={selectedListing.raw_title ?? "Vehicle"}
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
                  <div className="text-3xl font-bold text-zinc-900 dark:text-zinc-50">
                    {formatMoney(selectedListing.price)}
                  </div>
                  <div className="flex items-center gap-2">
                    {selectedListing.vehicle_condition && (
                      <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200 capitalize">
                        {selectedListing.vehicle_condition}
                      </span>
                    )}
                    {selectedListing.mileage != null && (
                      <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
                        {selectedListing.mileage.toLocaleString()} mi
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
                  <div className="space-y-1">
                    <dt className="text-xs font-medium text-zinc-500 dark:text-zinc-400">VIN</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100 break-all">{selectedListing.vin ?? "—"}</dd>
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
              <div className="border-t border-zinc-200 p-4 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/30">
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
