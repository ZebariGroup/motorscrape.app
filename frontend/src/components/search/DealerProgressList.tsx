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

/* ── tiny inline icons (no icon-library dep) ─────────────────────────── */
function IconCheck() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
      <circle cx="6.5" cy="6.5" r="6.5" className="fill-emerald-100 dark:fill-emerald-900/60" />
      <path d="M3.5 6.5l2 2 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-700 dark:text-emerald-300" />
    </svg>
  );
}
function IconX() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
      <circle cx="6.5" cy="6.5" r="6.5" className="fill-red-100 dark:fill-red-900/60" />
      <path d="M4.5 4.5l4 4M8.5 4.5l-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" className="text-red-600 dark:text-red-400" />
    </svg>
  );
}
function IconExternalLink() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden>
      <path d="M4.5 2.5H2a1 1 0 00-1 1v6a1 1 0 001 1h6a1 1 0 001-1V7M7 1h3m0 0v3M10 1L5.5 5.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IconPin() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden>
      <path d="M5.5 1L7 4.5H10L7.5 7l1 3L5.5 8.5 3 10l1-3L1.5 4.5 4 4.5z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Thin animated progress track inside each dealer card */
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
    pct = 40; // indeterminate-ish placeholder
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

      {/* ── header / collapse toggle ─────────────────────────── */}
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Dealerships</h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {dealerList.length === 0
              ? running ? "Finding nearby dealers…" : "No dealerships yet."
              : `${doneCount} of ${dealerList.length} processed`}
          </p>
        </div>
        <span className="text-zinc-400">{expanded ? "−" : "+"}</span>
      </button>

      {/* ── list ─────────────────────────────────────────────── */}
      {expanded ? (
        <div className="border-t border-zinc-200 px-3 py-3 dark:border-zinc-800">
          <ul className="space-y-2">
            {dealerList.length === 0 ? (
              running ? (
                /* skeleton cards while discovering */
                <>
                  {loadingDealerCards.map((_, idx) => (
                    <li key={`dealer-loading-${idx}`} className="relative overflow-hidden rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-3 dark:border-emerald-900/50 dark:bg-emerald-950/20">
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
                <li className="text-sm text-zinc-500 dark:text-zinc-400">No dealerships yet — run a scrape.</li>
              )
            ) : (
              <>
                {dealerList.map((d) => {
                  const phaseSec = d.phaseSince != null ? Math.max(0, Math.floor((nowMs - d.phaseSince) / 1000)) : 0;
                  const isQueued = d.status === "queued";
                  const isBusy = d.status === "scraping" || d.status === "parsing";
                  const isDone = d.status === "done";
                  const isError = d.status === "error";
                  const streamedCount = listingCountsByDealerKey[dealerSiteKey(d.website)] ?? 0;
                  const listingCount = Math.max(d.listings_found ?? 0, streamedCount);
                  const canPin = Boolean(d.website?.trim());
                  const isPinned = Boolean(canPin && pinnedDealerWebsite && dealerSiteKey(d.website!) === dealerSiteKey(pinnedDealerWebsite));

                  /* status dot color */
                  const dotClass = isDone
                    ? "bg-emerald-500"
                    : isError
                      ? "bg-red-500"
                      : isQueued
                        ? "bg-sky-400"
                        : "bg-amber-400 motion-safe:animate-pulse";

                  /* brief human status label (no tech jargon) */
                  const statusText = isDone
                    ? listingCount > 0 ? `${listingCount} found` : "Done — no listings"
                    : isError
                      ? "Couldn't reach site"
                      : isQueued
                        ? "Waiting…"
                        : d.status === "parsing"
                          ? `Reading… ${phaseSec}s`
                          : `Scanning… ${phaseSec}s`;

                  /* compact page progress, user-friendly */
                  const pageLabel = (() => {
                    if (isDone || isError || isQueued) return null;
                    if (d.reported_total_pages && d.reported_total_pages > 1) {
                      const cur = Math.max(1, d.current_page_number ?? d.pages_scraped ?? 1);
                      return `pg ${cur}/${d.reported_total_pages}`;
                    }
                    if (listingCount > 0 && isBusy) return `${listingCount} so far`;
                    return null;
                  })();

                  return (
                    <li key={d.website + d.index}>
                      <div
                        role={canPin ? "button" : undefined}
                        tabIndex={canPin ? 0 : undefined}
                        aria-pressed={canPin ? isPinned : undefined}
                        onClick={canPin ? () => onTogglePinnedDealer(d.website!) : undefined}
                        onKeyDown={canPin ? (e) => {
                          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTogglePinnedDealer(d.website!); }
                        } : undefined}
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
                        {/* shimmer while busy */}
                        {isBusy ? (
                          <div className="pointer-events-none absolute inset-y-0 left-0 w-24 -translate-x-full bg-gradient-to-r from-transparent via-amber-100/50 to-transparent motion-safe:animate-[shimmer_2.4s_infinite] dark:via-amber-400/10" aria-hidden />
                        ) : null}

                        {/* ── row 1: name + icon ── */}
                        <div className="flex min-w-0 items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">{d.name}</p>
                            {d.address ? (
                              <p className="mt-0.5 truncate text-[11px] text-zinc-400 dark:text-zinc-500">{d.address}</p>
                            ) : null}
                          </div>
                          <div className="mt-0.5 shrink-0">
                            {isDone ? <IconCheck /> : isError ? <IconX /> : null}
                          </div>
                        </div>

                        {/* ── progress bar ── */}
                        <ProgressBar
                          status={d.status}
                          pagesScraped={d.pages_scraped ?? d.current_page_number}
                          totalPages={d.reported_total_pages}
                        />

                        {/* ── row 2: status text + page/count + dot ── */}
                        <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
                            <span className={`truncate ${isDone && listingCount > 0 ? "font-medium text-zinc-700 dark:text-zinc-200" : "text-zinc-500 dark:text-zinc-400"}`}>
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
                              <span className="text-emerald-600 dark:text-emerald-400" title="Pinned to top"><IconPin /></span>
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

                        {/* error message — brief, non-technical */}
                        {isError && d.error ? (
                          <p className="mt-1.5 text-[11px] text-red-500 dark:text-red-400 line-clamp-2">{d.error}</p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}

                {/* pending skeleton cards while more dealers are being discovered */}
                {loadingDealerCards.map((_, idx) => (
                  <li key={`dealer-pending-${idx}`} className="relative overflow-hidden rounded-xl border border-dashed border-zinc-200 bg-zinc-50/70 p-3 dark:border-zinc-800 dark:bg-zinc-900/60">
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
