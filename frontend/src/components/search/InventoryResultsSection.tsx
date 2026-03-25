"use client";

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
              className="flex flex-row sm:flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950"
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
                    >
                      View listing
                    </a>
                  ) : null}
                  <a
                    href={v.dealership_website}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-semibold text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
                  >
                    Dealer site
                  </a>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
