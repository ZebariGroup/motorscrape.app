"use client";

import { useEffect, useState } from "react";
import { dealerSiteKey } from "@/lib/inventoryFormat";
import type { DealershipProgress } from "@/types/inventory";

type Props = {
  dealerList: DealershipProgress[];
  running: boolean;
  loadingDealerCards: unknown[];
  listingCountsByDealerKey: Record<string, number>;
  nowMs: number;
  pinnedDealerWebsite: string | null;
  onTogglePinnedDealer: (website: string) => void;
};

export function DealerProgressList({
  dealerList,
  running,
  loadingDealerCards,
  listingCountsByDealerKey,
  nowMs,
  pinnedDealerWebsite,
  onTogglePinnedDealer,
}: Props) {
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (window.innerWidth < 1024) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExpanded(false);
    }
  }, []);

  const doneCount = dealerList.filter((d) => d.status === "done" || d.status === "error").length;

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Dealerships</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {dealerList.length === 0 && !running
              ? "No dealerships yet."
              : `${doneCount} of ${dealerList.length} processed`}
            {dealerList.length > 0 ? (
              <span className="mt-1 block text-[11px] text-zinc-400 dark:text-zinc-500">
                Tap a dealer to show their vehicles first in inventory.
              </span>
            ) : null}
          </p>
        </div>
        <span className="text-lg text-zinc-400">{expanded ? "−" : "+"}</span>
      </button>
      {expanded ? (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <ul className="space-y-3">
        {dealerList.length === 0 ? (
          running ? (
            <>
              {loadingDealerCards.map((_, idx) => (
                <li
                  key={`dealer-loading-${idx}`}
                  className="relative overflow-hidden rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-4 dark:border-emerald-900/50 dark:bg-emerald-950/20"
                >
                  <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/60 to-transparent motion-safe:animate-[shimmer_2s_infinite] dark:via-white/10" />
                  <div className="relative space-y-3">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500 motion-safe:animate-pulse" />
                      <div className="h-4 w-40 rounded bg-emerald-200/80 dark:bg-emerald-900/70" />
                    </div>
                    <div className="h-3 w-56 rounded bg-zinc-200/80 dark:bg-zinc-800" />
                    <div className="flex gap-2">
                      <div className="h-5 w-20 rounded-full bg-amber-200/80 dark:bg-amber-900/60" />
                      <div className="h-5 w-28 rounded-full bg-zinc-200/80 dark:bg-zinc-800" />
                    </div>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">
                      Searching nearby dealerships and building the queue…
                    </p>
                  </div>
                </li>
              ))}
            </>
          ) : (
            <li className="text-sm text-zinc-500">No dealerships yet — run a scrape.</li>
          )
        ) : (
          <>
            {dealerList.map((d) => {
              const phaseSec =
                d.phaseSince != null ? Math.max(0, Math.floor((nowMs - d.phaseSince) / 1000)) : 0;
              const isBusy = d.status === "scraping" || d.status === "parsing";
              const streamedListingCount = listingCountsByDealerKey[dealerSiteKey(d.website)] ?? 0;
              const visibleListingsFound = Math.max(d.listings_found ?? 0, streamedListingCount);
              const loadedSummary =
                d.reported_total_results != null && visibleListingsFound > 0 && visibleListingsFound < d.reported_total_results
                  ? `${visibleListingsFound.toLocaleString()} loaded`
                  : visibleListingsFound > 0
                    ? `${visibleListingsFound.toLocaleString()} listings`
                    : null;
              const reportedSummary =
                d.reported_total_results != null
                  ? `${d.reported_total_results.toLocaleString()} site-reported`
                  : null;
              const canPin = Boolean(d.website?.trim());
              const isPinned = Boolean(
                canPin &&
                  pinnedDealerWebsite &&
                  dealerSiteKey(d.website!) === dealerSiteKey(pinnedDealerWebsite),
              );
              return (
                <li key={d.website + d.index}>
                  <div
                    role={canPin ? "button" : undefined}
                    tabIndex={canPin ? 0 : undefined}
                    aria-pressed={canPin ? isPinned : undefined}
                    onClick={
                      canPin
                        ? () => {
                            onTogglePinnedDealer(d.website!);
                          }
                        : undefined
                    }
                    onKeyDown={
                      canPin
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onTogglePinnedDealer(d.website!);
                            }
                          }
                        : undefined
                    }
                    className={`relative overflow-hidden rounded-xl border bg-white p-4 text-sm transition-all dark:bg-zinc-950 ${
                      canPin ? "cursor-pointer hover:border-emerald-300/80 dark:hover:border-emerald-700/50" : ""
                    } ${
                      isPinned
                        ? "border-emerald-500 ring-2 ring-emerald-500/35 dark:border-emerald-500"
                        : isBusy
                          ? "border-amber-200 shadow-sm shadow-amber-100/50 dark:border-amber-900/50 dark:shadow-none"
                          : "border-zinc-200 dark:border-zinc-800"
                    }`}
                  >
                    {isBusy ? (
                      <>
                        <div
                          className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent animate-pulse"
                          aria-hidden
                        />
                        <div
                          className="pointer-events-none absolute inset-y-0 left-0 w-20 -translate-x-full bg-gradient-to-r from-transparent via-emerald-200/40 to-transparent motion-safe:animate-[shimmer_2.4s_infinite] dark:via-emerald-400/10"
                          aria-hidden
                        />
                      </>
                    ) : null}
                    {isPinned ? (
                      <p className="mb-2 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
                        Showing this dealer first — tap again to clear
                      </p>
                    ) : null}
                    <div className="font-medium text-zinc-900 dark:text-zinc-50">{d.name}</div>
                    {d.address ? <div className="mt-1 text-xs text-zinc-500">{d.address}</div> : null}
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      <span
                        className={
                          d.status === "done"
                            ? "rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                            : d.status === "error"
                              ? "rounded-full bg-red-50 px-2 py-0.5 font-medium text-red-800 dark:bg-red-950 dark:text-red-200"
                              : "rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-900 motion-safe:animate-pulse dark:bg-amber-950 dark:text-amber-100"
                        }
                      >
                        {d.status}
                      </span>
                      {d.status === "scraping" && d.fetch_method ? (
                        <span className="text-zinc-500">via {d.fetch_method}</span>
                      ) : null}
                      {d.status === "parsing" ? (
                        <span className="text-zinc-500">
                          AI extraction… {phaseSec}s
                          {d.fetch_method ? (
                            <span className="text-zinc-400"> (page via {d.fetch_method})</span>
                          ) : null}
                        </span>
                      ) : null}
                      {d.status === "scraping" ? (
                        <span className="text-zinc-500">Fetching… {phaseSec}s</span>
                      ) : null}
                      {loadedSummary ? (
                        <span className="text-zinc-500">{loadedSummary}</span>
                      ) : null}
                    </div>
                    {reportedSummary ? (
                      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">{reportedSummary}</p>
                    ) : null}
                    {d.info ? (
                      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">{d.info}</p>
                    ) : null}
                    {d.error ? <p className="mt-2 text-xs text-red-600">{d.error}</p> : null}
                    {d.website ? (
                      <a
                        href={d.website}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="mt-2 inline-block text-xs font-medium text-emerald-700 underline-offset-2 hover:underline dark:text-emerald-400"
                      >
                        Open site
                      </a>
                    ) : null}
                  </div>
                </li>
              );
            })}
            {loadingDealerCards.map((_, idx) => (
              <li
                key={`dealer-pending-${idx}`}
                className="relative overflow-hidden rounded-xl border border-dashed border-zinc-200 bg-zinc-50/70 p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900/60"
              >
                <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/70 to-transparent motion-safe:animate-[shimmer_2.2s_infinite] dark:via-white/10" />
                <div className="relative space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex h-2.5 w-2.5 rounded-full bg-amber-500 motion-safe:animate-pulse" />
                    <div className="h-4 w-36 rounded bg-zinc-200 dark:bg-zinc-800" />
                  </div>
                  <div className="h-3 w-52 rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="flex gap-2">
                    <div className="h-5 w-24 rounded-full bg-zinc-200 dark:bg-zinc-800" />
                    <div className="h-5 w-20 rounded-full bg-zinc-200 dark:bg-zinc-800" />
                  </div>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Discovering another dealership in range…
                  </p>
                </div>
              </li>
            ))}
          </>
        )}
          </ul>
        </div>
      ) : null}
      <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">
        Disclaimer: Prices, availability, and vehicle details are extracted directly from dealership websites and may not always be accurate or up to date. Please verify all information with the dealer.
      </p>
    </div>
  );
}
