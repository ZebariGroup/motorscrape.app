"use client";

import Link from "next/link";

import { MarketRegionToggle } from "@/components/MarketRegionToggle";
import type { MarketRegion } from "@/lib/marketRegion";
import type { AccessSummary } from "@/types/access";

type Props = {
  access: AccessSummary | null;
  marketRegion?: MarketRegion;
  onMarketRegionChange?: (region: MarketRegion) => void;
  className?: string;
};

const headerPad =
  "px-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:px-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]";

export function SiteHeader({ access, marketRegion, onMarketRegionChange, className = "" }: Props) {
  if (access === null) {
    return (
      <header className={`border-b border-zinc-200 bg-white/80 pt-[env(safe-area-inset-top,0px)] backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80 ${className}`}>
        <div
          className={`mx-auto flex max-w-6xl flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between ${headerPad}`}
        >
          <div className="flex min-w-0 items-center gap-4">
            <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Motorscrape home">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-600 shadow-sm">
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
                  <path d="M1.5 10.5 4 6a1 1 0 0 1 .87-.5h6.26A1 1 0 0 1 12 6l2.5 4.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M1 10.5h14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5H1a.5.5 0 0 1-.5-.5V11a.5.5 0 0 1 .5-.5Z" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
                  <circle cx="4" cy="13" r="1" fill="white" />
                  <circle cx="12" cy="13" r="1" fill="white" />
                </svg>
              </span>
              <span className="text-sm font-bold tracking-tight">
                <span className="text-zinc-900 dark:text-zinc-50">Motor</span><span className="text-emerald-600 dark:text-emerald-400">scrape</span>
              </span>
            </Link>
            <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">
              We crawl so you can drive.
            </span>
          </div>
          <nav className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs sm:justify-end sm:gap-x-4 sm:text-sm">
            {marketRegion != null && onMarketRegionChange ? (
              <MarketRegionToggle value={marketRegion} onChange={onMarketRegionChange} disabled />
            ) : null}
            <div className="h-6 w-28 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
          </nav>
        </div>
      </header>
    );
  }

  const anonHint =
    !access.authenticated && access.anonymous
      ? `${access.anonymous.searches_remaining} of ${access.anonymous.signup_required_after} free scrapes left`
      : null;

  const usageHint =
    access?.authenticated && access.usage
      ? `Plan ${access.tier} · ${access.usage.included_used}/${access.usage.included_limit} scrapes this month` +
        (access.usage.overage_used ? ` · ${access.usage.overage_used} overage` : "")
      : null;

  return (
    <header className={`border-b border-zinc-200 bg-white/80 pt-[env(safe-area-inset-top,0px)] backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80 ${className}`}>
      <div
        className={`mx-auto flex max-w-6xl flex-col gap-2 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:py-3 ${headerPad}`}
      >
        <div className="flex min-w-0 flex-row items-center gap-2 sm:gap-4">
          <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Motorscrape home">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-600 shadow-sm">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path d="M1.5 10.5 4 6a1 1 0 0 1 .87-.5h6.26A1 1 0 0 1 12 6l2.5 4.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 10.5h14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5H1a.5.5 0 0 1-.5-.5V11a.5.5 0 0 1 .5-.5Z" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
                <circle cx="4" cy="13" r="1" fill="white" />
                <circle cx="12" cy="13" r="1" fill="white" />
              </svg>
            </span>
            <span className="text-sm font-bold tracking-tight">
              <span className="text-zinc-900 dark:text-zinc-50">Motor</span><span className="text-emerald-600 dark:text-emerald-400">scrape</span>
            </span>
          </Link>
          <span className="hidden text-xs text-zinc-500 sm:inline dark:text-zinc-400">
            We crawl so you can drive.
          </span>
          {(anonHint || usageHint) ? (
            <div className="flex min-w-0 flex-col gap-0 text-[11px] leading-tight sm:hidden">
              {anonHint ? (
                <span
                  title={anonHint}
                  className="truncate font-medium text-amber-800 dark:text-amber-200"
                >
                  {anonHint}
                </span>
              ) : null}
              {usageHint ? (
                <span title={usageHint} className="truncate text-zinc-600 dark:text-zinc-400">
                  {usageHint}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <nav className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs sm:justify-end sm:gap-x-4 sm:text-sm">
          <div className="hidden min-w-0 max-w-[20rem] flex-col items-end gap-0.5 text-xs leading-snug sm:flex">
            {anonHint ? (
              <span
                title={anonHint}
                className="truncate font-medium text-amber-800 dark:text-amber-200"
              >
                {anonHint}
              </span>
            ) : null}
            {usageHint ? (
              <span title={usageHint} className="truncate text-zinc-600 dark:text-zinc-400">
                {usageHint}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-3 border-r border-zinc-200 pr-3 dark:border-zinc-800">
            <Link
              href="/directory"
              className="shrink-0 font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
            >
              Directory
            </Link>
            <Link
              href="/guides"
              className="shrink-0 font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
            >
              Guides
            </Link>
          </div>
          {access.authenticated ? (
            <div className="flex items-center gap-2 sm:gap-3">
              {access.is_admin ? (
                <Link
                  href="/admin"
                  className="shrink-0 font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
                >
                  Admin
                </Link>
              ) : null}
              <Link
                href="/account"
                className="shrink-0 font-medium text-emerald-700 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
              >
                Account
              </Link>
            </div>
          ) : (
            <div className="flex items-center gap-2 sm:gap-3">
              <Link
                href="/login"
                className="shrink-0 font-medium text-zinc-700 hover:text-zinc-900 dark:text-zinc-300 dark:hover:text-zinc-50"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="shrink-0 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 sm:text-sm"
              >
                Sign up
              </Link>
            </div>
          )}
          {marketRegion != null && onMarketRegionChange ? (
            <MarketRegionToggle value={marketRegion} onChange={onMarketRegionChange} />
          ) : null}
        </nav>
      </div>
    </header>
  );
}
