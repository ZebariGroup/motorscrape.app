"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { DealerProgressList } from "@/components/search/DealerProgressList";
import { SavesAndAlertsPanel } from "@/components/search/SavesAndAlertsPanel";
import { SearchHistoryPanel } from "@/components/search/SearchHistoryPanel";
import type { SearchHistoryPanelHandle } from "@/components/search/SearchHistoryPanel";
import { MarketRegionToggle } from "@/components/MarketRegionToggle";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { MarketRegion } from "@/lib/marketRegion";
import type { AccessSummary } from "@/types/access";
import type { AlertCriteria } from "@/types/alerts";
import type { DealershipProgress } from "@/types/inventory";
import type { SavedSearchCriteria } from "@/types/savedSearch";
import type { SearchHistoryRunRow } from "@/types/searchHistory";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import { vehicleCategoryLabel } from "@/lib/vehicleCatalog";

const CATEGORY_BUTTONS: { value: VehicleCategory; label: string; icon: React.JSX.Element }[] = [
  {
    value: "car",
    label: "Cars",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5 5.4 8.8A2.5 2.5 0 0 1 7.64 7.5h8.72a2.5 2.5 0 0 1 2.24 1.3L21 13.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 13.5h16a1 1 0 0 1 1 1V17a1 1 0 0 1-1 1h-1.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 13.5a1 1 0 0 0-1 1V17a1 1 0 0 0 1 1h1.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 18H16.5" />
        <circle cx="7.5" cy="18" r="1.5" />
        <circle cx="16.5" cy="18" r="1.5" />
      </svg>
    ),
  },
  {
    value: "motorcycle",
    label: "Motorcycles",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
        <circle cx="6" cy="17" r="3" />
        <circle cx="18" cy="17" r="3" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17h3.5l2.5-5h-4l-2 2" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 7h2l2 3" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M10 9h4" />
      </svg>
    ),
  },
  {
    value: "boat",
    label: "Boats",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 14h16l-2.5 3.5a2 2 0 0 1-1.63.85H8.13a2 2 0 0 1-1.63-.85L4 14Z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v9" />
        <path strokeLinecap="round" strokeLinejoin="round" d="m12 6 4 2.5-4 2.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 20c1.2 0 1.2-.8 2.4-.8s1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8" />
      </svg>
    ),
  },
];

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
  vehicleCategory: VehicleCategory;
  onVehicleCategoryChange: (c: VehicleCategory) => void;
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
  alertCriteria: AlertCriteria;
  canSearch: boolean;
  onApplySavedSearch: (criteria: SavedSearchCriteria) => Promise<void>;
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
  vehicleCategory,
  onVehicleCategoryChange,
  applySavedSearchFromHistory,
  applyHistoryCriteriaOnly,
  alertCriteria,
  canSearch,
  onApplySavedSearch,
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
          <Link href="/" className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            Motorscrape
          </Link>
          <MarketRegionToggle value={marketRegion} onChange={onMarketRegionChange} />
        </div>
        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">We crawl so you can drive.</p>

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

      {/* Vehicle category */}
      <div className="border-t border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
        <div className="flex gap-1" role="group" aria-label="Vehicle type">
          {CATEGORY_BUTTONS.map((cat) => {
            const selected = vehicleCategory === cat.value;
            return (
              <button
                key={cat.value}
                type="button"
                onClick={() => onVehicleCategoryChange(cat.value)}
                aria-pressed={selected}
                title={vehicleCategoryLabel(cat.value)}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium transition ${
                  selected
                    ? "bg-emerald-600 text-white shadow-sm"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
                }`}
              >
                {cat.icon}
                <span className="truncate">{cat.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Scrape history */}
      <SidebarSection label="Search history" defaultOpen={false}>
        <SearchHistoryPanel
          ref={historyPanelRef}
          applySavedSearchFromHistory={applySavedSearchFromHistory}
          applyHistoryCriteriaOnly={applyHistoryCriteriaOnly}
        />
      </SidebarSection>

      {/* Saves & Alerts — panel has its own collapse UI, render it directly */}
      <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <SavesAndAlertsPanel
          access={access}
          criteria={alertCriteria}
          canSearch={canSearch}
          onApplySavedSearch={onApplySavedSearch}
        />
      </div>

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
