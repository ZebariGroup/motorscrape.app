"use client";

import { useState } from "react";

import { dealerSiteKey } from "@/lib/inventoryFormat";
import type { DealershipProgress } from "@/types/inventory";

type Props = {
  dealerList: DealershipProgress[];
  running: boolean;
  loadingDealerCards: unknown[];
  targetDealerCount: number;
  listingCountsByDealerKey: Record<string, number>;
  nowMs: number;
  pinnedDealerWebsite: string | null;
  onTogglePinnedDealer: (website: string) => void;
};

function IconCheck() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
      <circle cx="6.5" cy="6.5" r="6.5" className="fill-emerald-100 dark:fill-emerald-900/60" />
      <path
        d="M3.5 6.5l2 2 4-4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-emerald-700 dark:text-emerald-300"
      />
    </svg>
  );
}

function IconX() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
      <circle cx="6.5" cy="6.5" r="6.5" className="fill-red-100 dark:fill-red-900/60" />
      <path
        d="M4.5 4.5l4 4M8.5 4.5l-4 4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        className="text-red-600 dark:text-red-400"
      />
    </svg>
  );
}

function IconExternalLink() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden>
      <path
        d="M4.5 2.5H2a1 1 0 00-1 1v6a1 1 0 001 1h6a1 1 0 001-1V7M7 1h3m0 0v3M10 1L5.5 5.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconPin() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden>
      <path
        d="M5.5 1L7 4.5H10L7.5 7l1 3L5.5 8.5 3 10l1-3L1.5 4.5 4 4.5z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ProgressBar({
  status,
  pagesScraped,
  totalPages,
}: {
  status: DealershipProgress["status"];
  pagesScraped?: number;
  totalPages?: number;
}) {
  const isDone = status === "done";
  const isError = status === "error";
  const isBusy = status === "scraping" || status === "parsing";

  let pct = 0;
  if (isDone) {
    pct = 100;
  } else if (isError) {
    pct = 30;
  } else if (isBusy && totalPages && totalPages > 0) {
    pct = Math.min(95, Math.round(((pagesScraped ?? 1) / totalPages) * 100));
  } else if (isBusy) {
    pct = 40;
  }

  return (
    <div className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
      <div
        className={`h-full rounded-full transition-all duration-700 ${
          isDone
            ? "bg-emerald-500"
            : isError
              ? "bg-red-400"
              : isBusy
                ? "bg-amber-400 motion-safe:animate-pulse"
                : "bg-sky-300"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function DealerProgressList({
  dealerList,
  running,
  loadingDealerCards,
  targetDealerCount,
  listingCountsByDealerKey,
  nowMs,
  pinnedDealerWebsite,
  onTogglePinnedDealer,
}: Props) {
  const [expanded, setExpanded] = useState(() => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      return false;
    }
    return true;
  });

  const doneCount = dealerList.filter((d) => d.status === "done" || d.status === "error").length;
  const activeCount = dealerList.filter((d) => d.status === "scraping" || d.status === "parsing").length;
  const queuedCount = dealerList.filter((d) => d.status === "queued").length;
  const visibleCount = dealerList.length;
  const progressTotal = Math.max(targetDealerCount, visibleCount, 1);
  const undiscoveredCount = Math.max(0, targetDealerCount - visibleCount);

  const headerSummary =
    visibleCount === 0
      ? running
        ? "Building the dealership lineup..."
        : "No dealerships yet."
      : running
        ? visibleCount >= targetDealerCount
          ? `All ${visibleCount} dealerships are lined up`
          : `Showing ${visibleCount} of ${targetDealerCount} dealerships`
        : `${doneCount} of ${visibleCount} processed`;

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Dealership lineup</h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{headerSummary}</p>
        </div>
        <span className="text-zinc-400">{expanded ? "−" : "+"}</span>
      </button>

      {expanded ? (
        <div className="border-t border-zinc-200 px-3 py-3 dark:border-zinc-800">
          {running || dealerList.length > 0 ? (
            <div className="mb-3 space-y-3 rounded-xl border border-zinc-200/80 bg-zinc-50/70 p-3 dark:border-zinc-800 dark:bg-zinc-900/40">
              <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                <div className="rounded-lg bg-white px-2.5 py-2 dark:bg-zinc-950">
                  <p className="text-zinc-500 dark:text-zinc-400">Visible</p>
                  <p className="mt-0.5 font-semibold text-zinc-900 dark:text-zinc-50">
                    {visibleCount}
                    {targetDealerCount > 0 ? ` / ${targetDealerCount}` : ""}
                  </p>
                </div>
                <div className="rounded-lg bg-white px-2.5 py-2 dark:bg-zinc-950">
                  <p className="text-zinc-500 dark:text-zinc-400">Live</p>
                  <p className="mt-0.5 font-semibold text-amber-700 dark:text-amber-300">{activeCount}</p>
                </div>
                <div className="rounded-lg bg-white px-2.5 py-2 dark:bg-zinc-950">
                  <p className="text-zinc-500 dark:text-zinc-400">Queued</p>
                  <p className="mt-0.5 font-semibold text-sky-700 dark:text-sky-300">{queuedCount}</p>
                </div>
                <div className="rounded-lg bg-white px-2.5 py-2 dark:bg-zinc-950">
                  <p className="text-zinc-500 dark:text-zinc-400">Finished</p>
                  <p className="mt-0.5 font-semibold text-emerald-700 dark:text-emerald-300">{doneCount}</p>
                </div>
              </div>

              <div>
                <div className="mb-1.5 flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                  <span>Dealer flow</span>
                  <span>
                    {doneCount} done
                    {activeCount > 0 ? ` · ${activeCount} live` : ""}
                    {queuedCount > 0 ? ` · ${queuedCount} queued` : ""}
                  </span>
                </div>
                <div className="flex h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                  {doneCount > 0 ? (
                    <div className="bg-emerald-500" style={{ width: `${(doneCount / progressTotal) * 100}%` }} />
                  ) : null}
                  {activeCount > 0 ? (
                    <div className="bg-amber-400" style={{ width: `${(activeCount / progressTotal) * 100}%` }} />
                  ) : null}
                  {queuedCount > 0 ? (
                    <div className="bg-sky-400" style={{ width: `${(queuedCount / progressTotal) * 100}%` }} />
                  ) : null}
                  {undiscoveredCount > 0 ? (
                    <div
                      className="bg-zinc-300 dark:bg-zinc-700"
                      style={{ width: `${(undiscoveredCount / progressTotal) * 100}%` }}
                    />
                  ) : null}
                </div>
              </div>

              {running ? (
                <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                  Dealers stay visible in the lineup while scrape workers free up and results stream in.
                </p>
              ) : null}
            </div>
          ) : null}

          <ul className="space-y-2">
            {dealerList.length === 0 ? (
              running ? (
                <>
                  {loadingDealerCards.map((_, idx) => (
                    <li
                      key={`dealer-loading-${idx}`}
                      className="relative overflow-hidden rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-3 dark:border-emerald-900/50 dark:bg-emerald-950/20"
                    >
                      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/60 to-transparent motion-safe:animate-[shimmer_2s_infinite] dark:via-white/10" />
                      <div className="relative space-y-2">
                        <div className="h-4 w-40 rounded bg-emerald-200/80 dark:bg-emerald-900/70" />
                        <div className="h-3 w-32 rounded bg-zinc-200/80 dark:bg-zinc-800" />
                        <div className="h-1 w-full rounded-full bg-emerald-200/60 dark:bg-emerald-900/40" />
                      </div>
                    </li>
                  ))}
                </>
              ) : (
                <li className="text-sm text-zinc-500 dark:text-zinc-400">No dealerships yet - run a scrape.</li>
              )
            ) : (
              <>
                {dealerList.map((d) => {
                  const phaseSec =
                    d.phaseSince != null ? Math.max(0, Math.floor((nowMs - d.phaseSince) / 1000)) : 0;
                  const isQueued = d.status === "queued";
                  const isBusy = d.status === "scraping" || d.status === "parsing";
                  const isDone = d.status === "done";
                  const isError = d.status === "error";
                  const streamedCount = listingCountsByDealerKey[dealerSiteKey(d.website)] ?? 0;
                  const listingCount = Math.max(d.listings_found ?? 0, streamedCount);
                  const canPin = Boolean(d.website?.trim());
                  const isPinned = Boolean(
                    canPin &&
                      pinnedDealerWebsite &&
                      dealerSiteKey(d.website!) === dealerSiteKey(pinnedDealerWebsite),
                  );

                  const dotClass = isDone
                    ? "bg-emerald-500"
                    : isError
                      ? "bg-red-500"
                      : isQueued
                        ? "bg-sky-400"
                        : "bg-amber-400 motion-safe:animate-pulse";

                  const statusText = isDone
                    ? listingCount > 0
                      ? `${listingCount} found`
                      : "Done - no listings"
                    : isError
                      ? "Couldn't reach site"
                      : isQueued
                        ? "Waiting..."
                        : d.status === "parsing"
                          ? `Reading... ${phaseSec}s`
                          : `Scanning... ${phaseSec}s`;

                  const pageLabel = (() => {
                    if (isDone || isError || isQueued) return null;
                    if (d.reported_total_pages && d.reported_total_pages > 1) {
                      const cur = Math.max(1, d.current_page_number ?? d.pages_scraped ?? 1);
                      return `pg ${cur}/${d.reported_total_pages}`;
                    }
                    if (listingCount > 0 && isBusy) return `${listingCount} so far`;
                    return null;
                  })();

                  const stageBadgeClass = isDone
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300"
                    : isError
                      ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300"
                      : isQueued
                        ? "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-300"
                        : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300";

                  const stageBadgeText = isDone
                    ? "Done"
                    : isError
                      ? "Issue"
                      : d.status === "parsing"
                        ? "Parsing"
                        : isBusy
                          ? "Scraping"
                          : "Queued";

                  return (
                    <li key={d.website + d.index}>
                      <div
                        role={canPin ? "button" : undefined}
                        tabIndex={canPin ? 0 : undefined}
                        aria-pressed={canPin ? isPinned : undefined}
                        onClick={canPin ? () => onTogglePinnedDealer(d.website!) : undefined}
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
                        className={`relative overflow-hidden rounded-xl border p-3 text-sm transition-all dark:bg-zinc-950 ${
                          canPin ? "cursor-pointer hover:border-emerald-300/80 dark:hover:border-emerald-700/50" : ""
                        } ${
                          isPinned
                            ? "border-emerald-500 bg-emerald-50/30 ring-1 ring-emerald-500/30 dark:border-emerald-600 dark:bg-emerald-950/30"
                            : isQueued
                              ? "border-sky-200 bg-sky-50/30 dark:border-sky-900/50 dark:bg-sky-950/20"
                              : isBusy
                                ? "border-amber-200 bg-white shadow-sm dark:border-amber-900/50 dark:bg-zinc-950"
                                : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950"
                        }`}
                      >
                        {isBusy ? (
                          <div
                            className="pointer-events-none absolute inset-y-0 left-0 w-24 -translate-x-full bg-gradient-to-r from-transparent via-amber-100/50 to-transparent motion-safe:animate-[shimmer_2.4s_infinite] dark:via-amber-400/10"
                            aria-hidden
                          />
                        ) : null}

                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                            #{d.index}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${stageBadgeClass}`}>
                              {stageBadgeText}
                            </span>
                            {isDone ? <IconCheck /> : isError ? <IconX /> : null}
                          </div>
                        </div>

                        <div className="flex min-w-0 items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">{d.name}</p>
                            {d.address ? (
                              <p className="mt-0.5 truncate text-[12px] text-zinc-400 dark:text-zinc-500">{d.address}</p>
                            ) : null}
                          </div>
                        </div>

                        <ProgressBar
                          status={d.status}
                          pagesScraped={d.pages_scraped ?? d.current_page_number}
                          totalPages={d.reported_total_pages}
                        />

                        <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
                            <span
                              className={`truncate ${
                                isDone && listingCount > 0
                                  ? "font-medium text-zinc-700 dark:text-zinc-200"
                                  : "text-zinc-500 dark:text-zinc-400"
                              }`}
                            >
                              {statusText}
                            </span>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            {pageLabel ? (
                              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                                {pageLabel}
                              </span>
                            ) : null}
                            {isPinned ? (
                              <span className="text-emerald-600 dark:text-emerald-400" title="Pinned to top">
                                <IconPin />
                              </span>
                            ) : null}
                            {d.website ? (
                              <a
                                href={d.website}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-zinc-400 hover:text-emerald-600 dark:hover:text-emerald-400"
                                title="Open dealer website"
                              >
                                <IconExternalLink />
                              </a>
                            ) : null}
                          </div>
                        </div>

                        {isError && d.error ? (
                          <p className="mt-1.5 line-clamp-2 text-[12px] text-red-500 dark:text-red-400">{d.error}</p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}

                {loadingDealerCards.map((_, idx) => (
                  <li
                    key={`dealer-pending-${idx}`}
                    className="relative overflow-hidden rounded-xl border border-dashed border-zinc-200 bg-zinc-50/70 p-3 dark:border-zinc-800 dark:bg-zinc-900/60"
                  >
                    <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/70 to-transparent motion-safe:animate-[shimmer_2.2s_infinite] dark:via-white/10" />
                    <div className="relative space-y-2">
                      <div className="h-4 w-36 rounded bg-zinc-200 dark:bg-zinc-800" />
                      <div className="h-3 w-24 rounded bg-zinc-200 dark:bg-zinc-800" />
                      <div className="h-1 w-full rounded-full bg-zinc-200 dark:bg-zinc-800" />
                    </div>
                  </li>
                ))}
              </>
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
