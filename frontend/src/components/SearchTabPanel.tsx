"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSearchStream } from "@/hooks/useSearchStream";
import { AppSidebar } from "@/components/AppSidebar";
import { AlertsIconButton } from "@/components/search/AlertsIconButton";
import { DealerProgressList } from "@/components/search/DealerProgressList";
import { InventoryResultsSection } from "@/components/search/InventoryResultsSection";
import { SearchFormSection } from "@/components/search/SearchFormSection";
import { SiteHeader } from "@/components/SiteHeader";
import { resolveApiUrl } from "@/lib/apiBase";
import { buildSearchCriteriaQuery, parseSearchCriteriaQuery } from "@/lib/searchCriteriaUrl";
import { vehicleCategoryLabel } from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import {
  MAX_PRO_BULLETS_SHORT,
  PRO_BULLETS_SHORT,
  QUOTA_MODAL_BODY_DEFAULT,
  QUOTA_MODAL_BODY_MAX_PRO_USER,
  QUOTA_MODAL_BODY_PRO_USER,
  QUOTA_MODAL_BODY_STANDARD_USER,
  STANDARD_BULLETS_SHORT,
} from "@/lib/tierMarketingCopy";
import type { AccessSummary } from "@/types/access";

const CATEGORY_BUTTONS: {
  value: VehicleCategory;
  label: string;
  icon: React.JSX.Element;
}[] = [
  {
    value: "car",
    label: "Cars",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
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
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
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
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 14h16l-2.5 3.5a2 2 0 0 1-1.63.85H8.13a2 2 0 0 1-1.63-.85L4 14Z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v9" />
        <path strokeLinecap="round" strokeLinejoin="round" d="m12 6 4 2.5-4 2.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 20c1.2 0 1.2-.8 2.4-.8s1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8" />
      </svg>
    ),
  },
];

type SearchTabPanelProps = {
  /** Whether this panel is the currently visible tab */
  isActive: boolean;
  /** Access summary from the parent (shared, single fetch) */
  access: AccessSummary | null;
  /** Called when access should be re-fetched (e.g. after a search finishes) */
  onRefreshAccess: () => void;
  /** Optional initial criteria to pre-populate on first render */
  initialCriteria?: {
    make?: string;
    model?: string;
    location?: string;
  };
  /** Called whenever the tab's label changes (make · model or location) */
  onLabelChange: (label: string) => void;
  /** Called whenever running state or listing count changes (for the tab bar) */
  onStatusChange: (running: boolean, listingCount: number) => void;
  /**
   * Whether this panel owns the URL (reads searchParams on mount, writes
   * criteria to the URL while active). Only the first tab should do this;
   * secondary tabs are purely in-memory so switching tabs never clobbers
   * each other's form state.
   */
  syncWithUrl?: boolean;
};

export function SearchTabPanel({
  isActive,
  access,
  onRefreshAccess,
  initialCriteria,
  onLabelChange,
  onStatusChange,
  syncWithUrl = true,
}: SearchTabPanelProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [upgradeModalOpen, setUpgradeModalOpen] = useState(false);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [isStartingCheckout, setIsStartingCheckout] = useState(false);
  const [dismissedQuotaCode, setDismissedQuotaCode] = useState<string | null>(null);
  const [signupModalOpen, setSignupModalOpen] = useState(false);

  const appliedCriteriaQueryRef = useRef<string | null>(null);
  const pendingUrlWriteQueryRef = useRef<string | null>(null);

  const { form, search, dealers, listings, filters } = useSearchStream({
    onStreamFinished: onRefreshAccess,
  });
  const applySavedSearchCriteria = search.applySavedSearchCriteria;

  const isAnonymous = access ? !access.authenticated : false;

  // Limits derived from shared access
  const lim = access?.limits;
  const maxDealersCap = lim?.max_dealerships ?? 30;
  const maxRadiusCap = lim?.max_radius_miles ?? 250;
  const scopePremium = lim?.inventory_scope_premium ?? true;
  const csvOk = lim?.csv_export ?? true;
  const allowAnyModel =
    access?.tier === "premium" ||
    access?.tier === "max_pro" ||
    access?.tier === "enterprise" ||
    access?.tier === "custom";
  const canSearch =
    form.location.trim().length >= 2 && (allowAnyModel || form.model.trim().length > 0);

  // Report running/listingCount to parent for tab bar
  useEffect(() => {
    onStatusChange(search.running, listings.listings.length);
  }, [search.running, listings.listings.length, onStatusChange]);

  // Build the tab label from form fields
  useEffect(() => {
    const parts: string[] = [];
    const make = form.make.trim();
    const model = form.model.trim();
    const location = form.location.trim();
    if (make || model) parts.push([make, model].filter(Boolean).join(" "));
    if (location) parts.push(location);
    onLabelChange(parts.join(" · "));
  }, [form.make, form.model, form.location, onLabelChange]);

  // Signup modal for anonymous users starting a search
  useEffect(() => {
    if (isAnonymous && search.running && !signupModalOpen) {
      setSignupModalOpen(true);
    }
  }, [isAnonymous, search.running, signupModalOpen]);

  // Upgrade modal on quota errors
  useEffect(() => {
    const hits = search.errorEvents.find(
      (error) =>
        Boolean(error.upgrade_required) ||
        error.code === "quota.monthly_limit_free" ||
        error.code === "quota.monthly_limit_standard" ||
        error.code === "quota.monthly_limit_premium" ||
        error.code === "quota.monthly_limit_max_pro",
    );
    if (hits && !upgradeModalOpen && dismissedQuotaCode !== (hits.code ?? null)) {
      setUpgradeModalOpen(true);
      setUpgradeError(null);
    }
  }, [dismissedQuotaCode, search.errorEvents, upgradeModalOpen]);

  useEffect(() => {
    const anonQuotaHit = search.errorEvents.find(
      (error) => error.code === "quota.anonymous_limit_reached"
    );
    if (anonQuotaHit && !signupModalOpen) {
      setSignupModalOpen(true);
    }
  }, [search.errorEvents, signupModalOpen]);

  // URL sync — only when this panel is the active tab AND owns the URL
  useEffect(() => {
    if (!syncWithUrl) return;
    if (!isActive) return;
    const qs = searchParams.toString();
    if (pendingUrlWriteQueryRef.current === qs) {
      pendingUrlWriteQueryRef.current = null;
      appliedCriteriaQueryRef.current = qs;
      return;
    }
    if (!qs) {
      appliedCriteriaQueryRef.current = "";
      if (initialCriteria) {
        const params = new URLSearchParams();
        if (initialCriteria.location) params.set("location", initialCriteria.location);
        else params.set("location", "US");
        if (initialCriteria.make) params.set("make", initialCriteria.make);
        if (initialCriteria.model) params.set("model", initialCriteria.model);

        const parsed = parseSearchCriteriaQuery(params);
        if (parsed) {
          if (!initialCriteria.location) parsed.location = "";
          void applySavedSearchCriteria(parsed);
        }
      }
      return;
    }
    if (qs === appliedCriteriaQueryRef.current) return;
    const parsed = parseSearchCriteriaQuery(new URLSearchParams(qs));
    if (!parsed) return;
    void applySavedSearchCriteria(parsed);
    appliedCriteriaQueryRef.current = qs;
  }, [applySavedSearchCriteria, searchParams, initialCriteria, isActive, syncWithUrl]);

  const alertCriteria = useMemo(
    () => ({
      location: form.location.trim(),
      make: form.make.trim(),
      model: form.model.trim(),
      vehicle_category: form.vehicleCategory,
      vehicle_condition: form.vehicleCondition as "all" | "new" | "used",
      radius_miles: Number.parseInt(form.radiusMiles, 10) || 25,
      inventory_scope: form.inventoryScope as "all" | "on_lot_only" | "exclude_shared" | "include_transit",
      prefer_small_dealers: form.preferSmallDealers,
      max_dealerships: Number.parseInt(form.maxDealerships, 10) || null,
      max_pages_per_dealer: null,
      market_region: form.marketRegion,
    }),
    [
      form.inventoryScope,
      form.location,
      form.make,
      form.marketRegion,
      form.maxDealerships,
      form.model,
      form.preferSmallDealers,
      form.radiusMiles,
      form.vehicleCategory,
      form.vehicleCondition,
    ],
  );

  const currentCriteriaQuery = useMemo(() => buildSearchCriteriaQuery(alertCriteria), [alertCriteria]);

  const searchReadinessHint = useMemo(() => {
    if (form.location.trim().length < 2) return "Enter a city, ZIP, or coordinates to start a search.";
    if (!allowAnyModel && form.model.trim().length === 0) {
      return access?.authenticated
        ? "Choose at least one model on your current plan before scraping inventory."
        : "Choose at least one model on the free plan before scraping inventory.";
    }
    return null;
  }, [access?.authenticated, allowAnyModel, form.location, form.model]);

  // Write criteria to URL when active and form changes — only for the URL-owning tab
  useEffect(() => {
    if (!syncWithUrl) return;
    if (!isActive) return;
    const qs = searchParams.toString();
    if (qs && appliedCriteriaQueryRef.current === null) return;
    const nextQuery = form.location.trim().length >= 2 ? currentCriteriaQuery : "";
    if (qs === nextQuery) {
      appliedCriteriaQueryRef.current = nextQuery;
      return;
    }
    pendingUrlWriteQueryRef.current = nextQuery;
    appliedCriteriaQueryRef.current = nextQuery;
    router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false });
  }, [syncWithUrl, currentCriteriaQuery, form.location, pathname, router, searchParams, isActive]);

  // Tier cap sync
  useEffect(() => {
    const cap = maxDealersCap;
    const parsed = Number.parseInt(form.maxDealerships, 10);
    const next = Number.isFinite(parsed) ? Math.min(parsed, cap) : Math.min(8, cap);
    if (String(next) !== form.maxDealerships) {
      form.setMaxDealerships(String(next));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxDealersCap, form.maxDealerships, form.setMaxDealerships]);

  useEffect(() => {
    const rm = Number.parseInt(form.radiusMiles, 10);
    if (Number.isFinite(rm) && rm > maxRadiusCap) {
      form.setRadiusMiles(String(maxRadiusCap));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxRadiusCap, form.radiusMiles, form.setRadiusMiles]);

  useEffect(() => {
    if (!scopePremium && form.inventoryScope !== "all") {
      form.setInventoryScope("all");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopePremium, form.inventoryScope, form.setInventoryScope]);

  const handleVehicleCategoryChange = (category: VehicleCategory) => {
    if (category === form.vehicleCategory) return;
    form.setVehicleCategory(category);
    form.setMake("");
    form.setModel("");
  };

  const savedResultsNotice = useMemo(() => {
    const hv = search.historyView;
    if (!hv) return null;
    const when = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
      new Date(hv.asOfIso),
    );
    return {
      title: "Saved search results",
      body: `Showing ${hv.savedCount} vehicles from a search on ${when}. Dealers change inventory frequently—run a new search when you need the latest listings.`,
      onDismiss: search.clearHistoryView,
    };
  }, [search.historyView, search.clearHistoryView]);

  const hiddenUpgradeMessages = new Set(
    search.errorEvents.filter((error) => error.upgrade_required).map((error) => error.message),
  );
  const visibleErrors = search.errors.filter((e) => !hiddenUpgradeMessages.has(e));

  const startCheckout = async (tier: "standard" | "premium" | "max_pro") => {
    setUpgradeError(null);
    setIsStartingCheckout(true);
    try {
      const r = await fetch(resolveApiUrl("/billing/checkout"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        setUpgradeError(typeof j.detail === "string" ? j.detail : "Checkout unavailable.");
        return;
      }
      const { url } = j as { url?: string };
      if (url) window.location.href = url;
      else setUpgradeError("Checkout did not return a URL. Please try again.");
    } catch {
      setUpgradeError("Network error. Please try again.");
    } finally {
      setIsStartingCheckout(false);
    }
  };

  return (
    <>
      {/* Mobile-only top bar */}
      <SiteHeader
        access={access}
        marketRegion={form.marketRegion}
        onMarketRegionChange={form.setMarketRegion}
        className="lg:hidden"
      />

      <div className="flex min-h-screen w-full">
        {/* Desktop sidebar */}
        <AppSidebar
          access={access}
          marketRegion={form.marketRegion}
          onMarketRegionChange={form.setMarketRegion}
          applySavedSearchFromHistory={search.applySavedSearchFromHistory}
          applyHistoryCriteriaOnly={search.applyHistoryCriteriaOnly}
          dealers={{
            dealerList: dealers.dealerList,
            running: search.running,
            loadingDealerCards: dealers.loadingDealerCards,
            targetDealerCount: dealers.targetDealerCount,
            listingCountsByDealerKey: dealers.listingCountsByDealerKey,
            nowMs: dealers.nowMs,
            pinnedDealerWebsite: dealers.pinnedDealerWebsite,
            onTogglePinnedDealer: dealers.togglePinnedDealer,
          }}
        />

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-4 px-4 py-4 pb-20 sm:gap-6 sm:px-6 sm:py-6 sm:pb-10">
            {/* Page header */}
            <header>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h1 className="text-xl font-semibold tracking-tight text-zinc-900 sm:text-2xl dark:text-zinc-50">
                    Local motor vehicle inventory
                  </h1>
                  <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400 hidden sm:block">
                    We crawl dealership sites so you don&apos;t have to.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {/* Category chips */}
                  <div className="flex items-center gap-0.5 rounded-xl border border-zinc-200 bg-white p-1 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
                    {CATEGORY_BUTTONS.map((category) => {
                      const selected = form.vehicleCategory === category.value;
                      return (
                        <button
                          key={category.value}
                          type="button"
                          onClick={() => handleVehicleCategoryChange(category.value)}
                          className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition ${
                            selected
                              ? "bg-emerald-600 text-white shadow-sm"
                              : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-900 dark:hover:text-zinc-50"
                          }`}
                          aria-pressed={selected}
                          title={vehicleCategoryLabel(category.value)}
                        >
                          {category.icon}
                          <span className="hidden sm:inline">{category.label}</span>
                        </button>
                      );
                    })}
                  </div>
                  {/* Mail alerts icon */}
                  <AlertsIconButton
                    access={access}
                    criteria={alertCriteria}
                    canSearch={canSearch}
                  />
                </div>
              </div>
            </header>

            <SearchFormSection
              running={search.running}
              reconnecting={search.reconnecting}
              location={form.location}
              setLocation={form.setLocation}
              vehicleCategory={form.vehicleCategory}
              make={form.make}
              setMake={form.setMake}
              model={form.model}
              setModel={form.setModel}
              modelOptions={form.modelOptions}
              usesCatalog={form.usesCatalog}
              vehicleCondition={form.vehicleCondition}
              setVehicleCondition={form.setVehicleCondition}
              radiusMiles={form.radiusMiles}
              setRadiusMiles={form.setRadiusMiles}
              inventoryScope={form.inventoryScope}
              setInventoryScope={form.setInventoryScope}
              preferSmallDealers={form.preferSmallDealers}
              setPreferSmallDealers={form.setPreferSmallDealers}
              maxDealerships={form.maxDealerships}
              setMaxDealerships={form.setMaxDealerships}
              onSearch={search.startSearch}
              onStop={search.stopStream}
              canSearch={canSearch}
              searchReadinessHint={searchReadinessHint}
              errors={visibleErrors}
              discoveredDealerPercent={dealers.discoveredDealerPercent}
              completedDealerPercent={dealers.completedDealerPercent}
              dealerListLength={dealers.dealerList.length}
              targetDealerCount={dealers.targetDealerCount}
              doneDealerCount={dealers.doneDealerCount}
              listingsCount={listings.listings.length}
              maxDealersCap={maxDealersCap}
              maxRadiusMilesCap={maxRadiusCap}
              inventoryScopePremium={scopePremium}
              allowAnyModel={allowAnyModel}
              applySavedSearchFromHistory={search.applySavedSearchFromHistory}
              applyHistoryCriteriaOnly={search.applyHistoryCriteriaOnly}
              marketRegion={form.marketRegion}
              access={access}
              savedSearchCriteria={alertCriteria}
              onApplySavedSearch={applySavedSearchCriteria}
            />

            {/* Mobile-only: dealer progress */}
            <div className="lg:hidden">
              <DealerProgressList
                dealerList={dealers.dealerList}
                running={search.running}
                loadingDealerCards={dealers.loadingDealerCards}
                targetDealerCount={dealers.targetDealerCount}
                listingCountsByDealerKey={dealers.listingCountsByDealerKey}
                nowMs={dealers.nowMs}
                pinnedDealerWebsite={dealers.pinnedDealerWebsite}
                onTogglePinnedDealer={dealers.togglePinnedDealer}
              />
            </div>

            <InventoryResultsSection
              listings={listings.listings}
              filteredListings={listings.filteredListings}
              running={search.running}
              loadingInventoryCards={listings.loadingInventoryCards}
              sortOrder={listings.sortOrder}
              onSortOrderChange={listings.setSortOrder}
              vehicleCategory={form.vehicleCategory}
              allowCsvExport={csvOk}
              activeDealerSummary={dealers.activeDealerSummary}
              activeDealerCount={dealers.activeDealerCount}
              queuedDealerCount={dealers.queuedDealerCount}
              savedResultsNotice={savedResultsNotice}
              isAnonymous={isAnonymous}
              onSignupClick={() => router.push("/signup")}
              filters={filters}
            />
          </div>

          {/* Mobile sticky progress + stop bar */}
          {search.running && (
            <div className="fixed inset-x-0 bottom-0 z-50 border-t border-zinc-200 bg-white/92 px-3 py-2.5 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur-md sm:hidden dark:border-zinc-800 dark:bg-zinc-950/92 shadow-[0_-4px_18px_-12px_rgba(0,0,0,0.18)]">
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-1 flex-col gap-1.5">
                  <div className="flex items-center justify-between text-xs font-medium">
                    <span className="text-zinc-900 dark:text-zinc-50">
                      {search.reconnecting ? "Reconnecting..." : "Scraping..."}
                    </span>
                    <span className="text-zinc-500">
                      {dealers.doneDealerCount} / {dealers.targetDealerCount}
                    </span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className={`h-full transition-all duration-500 ${search.reconnecting ? "bg-amber-500" : "bg-emerald-500"}`}
                      style={{ width: `${dealers.completedDealerPercent}%` }}
                    />
                  </div>
                </div>
                <button
                  onClick={search.stopStream}
                  className="rounded-lg bg-zinc-100 px-3 py-1.5 text-[11px] font-semibold text-zinc-900 transition hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-50 dark:hover:bg-zinc-700"
                >
                  Stop
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Signup modal */}
      {signupModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-2xl dark:border-zinc-800 dark:bg-zinc-950 text-center">
            <h2 className="text-xl font-bold text-zinc-900 dark:text-zinc-50 mb-3">
              Create a free account to see results
            </h2>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
              Sign up now to get <strong>15 free searches</strong> and save your best runs.
              It takes less than 30 seconds.
            </p>
            <div className="flex flex-col gap-3">
              <button
                type="button"
                onClick={() => router.push("/signup")}
                className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-500"
              >
                Create Free Account
              </button>
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="w-full rounded-lg bg-zinc-100 px-4 py-2.5 text-sm font-semibold text-zinc-900 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-50 dark:hover:bg-zinc-800"
              >
                Log in
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upgrade modal */}
      {upgradeModalOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
          <div className="w-full max-w-xl rounded-2xl border border-zinc-200 bg-white p-5 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-2">
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Subscribe to keep searching</h2>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {access?.tier === "standard"
                    ? QUOTA_MODAL_BODY_STANDARD_USER
                    : access?.tier === "premium"
                      ? QUOTA_MODAL_BODY_PRO_USER
                      : access?.tier === "max_pro"
                        ? QUOTA_MODAL_BODY_MAX_PRO_USER
                        : QUOTA_MODAL_BODY_DEFAULT}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  const hits = search.errorEvents.find((error) => error.upgrade_required);
                  if (hits?.code) setDismissedQuotaCode(hits.code);
                  setUpgradeModalOpen(false);
                }}
                className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <span className="text-2xl leading-none">×</span>
              </button>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
                <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Standard — $20/mo</h3>
                <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                  {STANDARD_BULLETS_SHORT.map((line) => (
                    <li key={line}>• {line}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  disabled={isStartingCheckout}
                  onClick={() => void startCheckout("standard")}
                  className="mt-3 w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isStartingCheckout ? "Starting..." : "Subscribe Standard"}
                </button>
              </div>

              <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
                <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Pro — $60/mo</h3>
                <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                  {PRO_BULLETS_SHORT.map((line) => (
                    <li key={line}>• {line}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  disabled={isStartingCheckout}
                  onClick={() => void startCheckout("premium")}
                  className="mt-3 w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isStartingCheckout ? "Starting..." : "Subscribe Pro"}
                </button>
              </div>

              <div className="rounded-xl border border-emerald-300 p-4 dark:border-emerald-800">
                <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Max Pro — $200/mo</h3>
                <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                  {MAX_PRO_BULLETS_SHORT.map((line) => (
                    <li key={line}>• {line}</li>
                  ))}
                </ul>
                <button
                  type="button"
                  disabled={isStartingCheckout}
                  onClick={() => void startCheckout("max_pro")}
                  className="mt-3 w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isStartingCheckout ? "Starting..." : "Subscribe Max Pro"}
                </button>
              </div>
            </div>

            {upgradeError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{upgradeError}</p> : null}
          </div>
        </div>
      )}
    </>
  );
}
