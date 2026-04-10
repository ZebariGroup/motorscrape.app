"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { DealerProgressList } from "@/components/search/DealerProgressList";
import { SearchHistoryPanel } from "@/components/search/SearchHistoryPanel";
import type { SearchHistoryPanelHandle } from "@/components/search/SearchHistoryPanel";
import { MarketRegionToggle } from "@/components/MarketRegionToggle";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { MarketRegion } from "@/lib/marketRegion";
import type { AccessSummary } from "@/types/access";
import type { DealershipProgress } from "@/types/inventory";
import type { SearchHistoryRunRow } from "@/types/searchHistory";
type DealerProps = {
  dealerList: DealershipProgress[];
  running: boolean;
  loadingDealerCards: unknown[];
  targetDealerCount: number;
  listingCountsByDealerKey: Record<string, number>;
  nowMs: number;
  pinnedDealerWebsite: string | null;
  onTogglePinnedDealer: (website: string) => void;
};

type Props = {
  access: AccessSummary | null;
  marketRegion: MarketRegion;
  onMarketRegionChange: (r: MarketRegion) => void;
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
  dealers: DealerProps;
};

function SidebarSection({
  label,
  badge,
  collapsible = true,
  defaultOpen = true,
  children,
}: {
  label: string;
  badge?: number | null;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = !collapsible || open;

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800">
      <button
        type="button"
        onClick={collapsible ? () => setOpen((v) => !v) : undefined}
        className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left ${collapsible ? "cursor-pointer" : "cursor-default"}`}
        aria-expanded={collapsible ? isOpen : undefined}
      >
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
          {label}
          {badge != null && badge > 0 ? (
            <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
              {badge}
            </span>
          ) : null}
        </span>
        {collapsible ? (
          <span className="text-zinc-400 dark:text-zinc-600" aria-hidden>
            {isOpen ? (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 8l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </span>
        ) : null}
      </button>
      {isOpen ? <div className="px-4 pb-4">{children}</div> : null}
    </div>
  );
}

export function AppSidebar({
  access,
  marketRegion,
  onMarketRegionChange,
  applySavedSearchFromHistory,
  applyHistoryCriteriaOnly,
  dealers,
}: Props) {
  const historyPanelRef = useRef<SearchHistoryPanelHandle>(null);

  const anonHint =
    access && !access.authenticated && access.anonymous
      ? `${access.anonymous.searches_remaining} of ${access.anonymous.signup_required_after} free scrapes left`
      : null;

  const usageHint =
    access?.authenticated && access.usage
      ? `${access.usage.included_used} / ${access.usage.included_limit} scrapes · ${access.tier}`
      : null;

  return (
    <aside className="sidebar-scroll hidden lg:flex lg:flex-col lg:w-64 xl:w-72 shrink-0 h-screen sticky top-0 overflow-y-auto border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      {/* Brand */}
      <div className="px-4 py-4">
        <div className="flex items-center justify-between gap-2">
          <Link href="/" className="group flex items-center gap-2" aria-label="Motorscrape home">
            {/* Icon mark */}
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-600 shadow-sm">
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path
                  d="M1.5 10.5 4 6a1 1 0 0 1 .87-.5h6.26A1 1 0 0 1 12 6l2.5 4.5"
                  stroke="white"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M1 10.5h14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5H1a.5.5 0 0 1-.5-.5V11a.5.5 0 0 1 .5-.5Z"
                  stroke="white"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
                <circle cx="4" cy="13" r="1" fill="white" />
                <circle cx="12" cy="13" r="1" fill="white" />
              </svg>
            </span>
            {/* Wordmark */}
            <span className="text-sm font-bold tracking-tight">
              <span className="text-zinc-900 dark:text-zinc-50">Motor</span><span className="text-emerald-600 dark:text-emerald-400">scrape</span>
            </span>
          </Link>
          <MarketRegionToggle value={marketRegion} onChange={onMarketRegionChange} />
        </div>
        <p className="mt-1.5 text-[11px] font-medium uppercase tracking-widest text-zinc-400 dark:text-zinc-500">We crawl so you can drive.</p>

        {/* Usage hint */}
        {anonHint ? (
          <p className="mt-2 rounded-lg bg-amber-50 px-2 py-1.5 text-xs font-medium text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
            {anonHint}
          </p>
        ) : usageHint ? (
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">{usageHint}</p>
        ) : null}
      </div>

      {/* Navigation */}
      <div className="border-t border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
        <nav className="flex flex-wrap items-center gap-1">
          {[
            { href: "/directory", label: "Directory" },
            { href: "/guides", label: "Guides" },
            ...(access?.is_admin ? [{ href: "/admin", label: "Admin" }] : []),
          ].map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="rounded-md px-2.5 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
            >
              {label}
            </Link>
          ))}
          {access?.authenticated ? (
            <Link
              href="/account"
              className="rounded-md px-2.5 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800 dark:text-emerald-400 dark:hover:bg-emerald-950/60 dark:hover:text-emerald-300"
            >
              Account
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="rounded-md px-2.5 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-500"
              >
                Sign up
              </Link>
            </>
          )}
        </nav>
      </div>

      {/* Scrape history */}
      <SidebarSection label="Search history" defaultOpen={false}>
        <SearchHistoryPanel
          ref={historyPanelRef}
          applySavedSearchFromHistory={applySavedSearchFromHistory}
          applyHistoryCriteriaOnly={applyHistoryCriteriaOnly}
        />
      </SidebarSection>

      {/* Dealer progress */}
      <SidebarSection label="Dealers" defaultOpen={true}>
        <DealerProgressList
          dealerList={dealers.dealerList}
          running={dealers.running}
          loadingDealerCards={dealers.loadingDealerCards}
          targetDealerCount={dealers.targetDealerCount}
          listingCountsByDealerKey={dealers.listingCountsByDealerKey}
          nowMs={dealers.nowMs}
          pinnedDealerWebsite={dealers.pinnedDealerWebsite}
          onTogglePinnedDealer={dealers.onTogglePinnedDealer}
        />
      </SidebarSection>
    </aside>
  );
}
