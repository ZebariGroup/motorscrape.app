"use client";

import { useEffect, useState } from "react";

import { useSearchStream } from "@/hooks/useSearchStream";
import { useAccessSummary } from "@/hooks/useAccessSummary";
import { DealerProgressList } from "@/components/search/DealerProgressList";
import { EmailAlertPanel } from "@/components/search/EmailAlertPanel";
import { InventoryResultsSection } from "@/components/search/InventoryResultsSection";
import { ResultFiltersPanel } from "@/components/search/ResultFiltersPanel";
import { SearchFormSection } from "@/components/search/SearchFormSection";
import { SiteHeader } from "@/components/SiteHeader";
import { resolveApiUrl } from "@/lib/apiBase";
import {
  PREMIUM_BULLETS_SHORT,
  QUOTA_MODAL_BODY_DEFAULT,
  QUOTA_MODAL_BODY_STANDARD_USER,
  STANDARD_BULLETS_SHORT,
} from "@/lib/tierMarketingCopy";

export function SearchExperience() {
  const { access, refresh } = useAccessSummary();
  const [upgradeModalOpen, setUpgradeModalOpen] = useState(false);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [isStartingCheckout, setIsStartingCheckout] = useState(false);
  const [dismissedQuotaMessage, setDismissedQuotaMessage] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const { form, search, dealers, listings, filters } = useSearchStream({
    onStreamFinished: refresh,
  });

  useEffect(() => {
    const hits = search.errors.find(
      (e) => e.includes("Monthly free search limit reached") || e.includes("Monthly included searches are used up"),
    );
    if (hits && !upgradeModalOpen && dismissedQuotaMessage !== hits) {
      setUpgradeModalOpen(true);
      setUpgradeError(null);
    }
  }, [search.errors, upgradeModalOpen, dismissedQuotaMessage]);

  const startCheckout = async (tier: "standard" | "premium") => {
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

  const lim = access?.limits;
  const maxDealersCap = lim?.max_dealerships ?? 30;
  const maxRadiusCap = lim?.max_radius_miles ?? 250;
  const scopePremium = lim?.inventory_scope_premium ?? true;
  const csvOk = lim?.csv_export ?? true;
  const canSearch =
    form.location.trim().length >= 2 &&
    (access?.tier === "premium" ||
      access?.tier === "enterprise" ||
      access?.tier === "custom" ||
      form.model.trim().length > 0);
  const alertCriteria = {
    location: form.location.trim(),
    make: form.make.trim(),
    model: form.model.trim(),
    vehicle_condition: form.vehicleCondition as "all" | "new" | "used",
    radius_miles: Number.parseInt(form.radiusMiles, 10) || 25,
    inventory_scope: form.inventoryScope as "all" | "on_lot_only" | "exclude_shared" | "include_transit",
    max_dealerships: Number.parseInt(form.maxDealerships, 10) || null,
    max_pages_per_dealer: null,
  };

  // Avoid duplicating the same "quota reached" message: we show it via the modal instead.
  const visibleErrors = search.errors.filter(
    (e) =>
      !e.includes("Monthly free search limit reached") &&
      !e.includes("Monthly included searches are used up"),
  );

  useEffect(
    () => {
      const cap = maxDealersCap;
      const parsed = Number.parseInt(form.maxDealerships, 10);
      const next = Number.isFinite(parsed) ? Math.min(parsed, cap) : Math.min(8, cap);
      if (String(next) !== form.maxDealerships) {
        form.setMaxDealerships(String(next));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tier cap sync; `form` object identity changes each render
    [maxDealersCap, form.maxDealerships, form.setMaxDealerships],
  );

  useEffect(
    () => {
      const rm = Number.parseInt(form.radiusMiles, 10);
      if (Number.isFinite(rm) && rm > maxRadiusCap) {
        form.setRadiusMiles(String(maxRadiusCap));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tier cap sync
    [maxRadiusCap, form.radiusMiles, form.setRadiusMiles],
  );

  useEffect(
    () => {
      if (!scopePremium && form.inventoryScope !== "all") {
        form.setInventoryScope("all");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tier feature gate
    [scopePremium, form.inventoryScope, form.setInventoryScope],
  );

  return (
    <>
      <SiteHeader access={access} />
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-4 py-10 pb-24 sm:px-6 sm:pb-10">
        <header className="space-y-2">
          <p className="text-sm font-medium tracking-wide text-emerald-700 uppercase">Motorscrape</p>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
            Local dealership inventory, one place
          </h1>
        </header>

            <SearchFormSection
              running={search.running}
              reconnecting={search.reconnecting}
              location={form.location}
          setLocation={form.setLocation}
          make={form.make}
          setMake={form.setMake}
          model={form.model}
          setModel={form.setModel}
          modelOptions={form.modelOptions}
          vehicleCondition={form.vehicleCondition}
          setVehicleCondition={form.setVehicleCondition}
          radiusMiles={form.radiusMiles}
          setRadiusMiles={form.setRadiusMiles}
          inventoryScope={form.inventoryScope}
          setInventoryScope={form.setInventoryScope}
          maxDealerships={form.maxDealerships}
          setMaxDealerships={form.setMaxDealerships}
          onSearch={search.startSearch}
          onStop={search.stopStream}
          canSearch={canSearch}
          status={search.status}
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
          allowAnyModel={access?.tier === "premium" || access?.tier === "enterprise" || access?.tier === "custom"}
        />
        <EmailAlertPanel access={access} criteria={alertCriteria} canSearch={canSearch} dismissible />

        <div className="grid gap-8 lg:grid-cols-3">
          <section className="lg:col-span-1">
            <ResultFiltersPanel
              filtersExpanded={filters.filtersExpanded}
              setFiltersExpanded={filters.setFiltersExpanded}
              activeResultFilterCount={filters.activeResultFilterCount}
              yearFilter={filters.yearFilter}
              setYearFilter={filters.setYearFilter}
              yearOptions={filters.yearOptions}
              bodyStyleFilter={filters.bodyStyleFilter}
              setBodyStyleFilter={filters.setBodyStyleFilter}
              bodyStyleOptions={filters.bodyStyleOptions}
              colorFilter={filters.colorFilter}
              setColorFilter={filters.setColorFilter}
              colorOptions={filters.colorOptions}
              priceBounds={filters.priceBounds}
              effectivePriceMin={filters.effectivePriceMin}
              effectivePriceMax={filters.effectivePriceMax}
              setPriceFilterMin={filters.setPriceFilterMin}
              setPriceFilterMax={filters.setPriceFilterMax}
              onClearFilters={filters.clearFilters}
            />
            <DealerProgressList
              dealerList={dealers.dealerList}
              running={search.running}
              loadingDealerCards={dealers.loadingDealerCards}
              listingCountsByDealerKey={dealers.listingCountsByDealerKey}
              nowMs={dealers.nowMs}
              pinnedDealerWebsite={dealers.pinnedDealerWebsite}
              onTogglePinnedDealer={dealers.togglePinnedDealer}
            />
          </section>

          <InventoryResultsSection
            listings={listings.listings}
            filteredListings={listings.filteredListings}
            running={search.running}
            loadingInventoryCards={listings.loadingInventoryCards}
            sortOrder={listings.sortOrder}
            onSortOrderChange={listings.setSortOrder}
            allowCsvExport={csvOk}
          />
        </div>

        {search.running && (
          <div className="fixed inset-x-0 bottom-0 z-50 border-t border-zinc-200 bg-white/90 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] backdrop-blur-md sm:hidden dark:border-zinc-800 dark:bg-zinc-950/90 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.1)]">
            <div className="flex items-center justify-between gap-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <div className="flex items-center justify-between text-xs font-medium">
                  <span className="text-zinc-900 dark:text-zinc-50">
                    {search.reconnecting ? "Reconnecting..." : "Scraping..."}
                  </span>
                  <span className="text-zinc-500">
                    {dealers.doneDealerCount} / {dealers.targetDealerCount}
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                  <div
                    className={`h-full transition-all duration-500 ${search.reconnecting ? "bg-amber-500" : "bg-emerald-500"}`}
                    style={{ width: `${dealers.completedDealerPercent}%` }}
                  />
                </div>
              </div>
              <button
                onClick={search.stopStream}
                className="rounded-lg bg-zinc-100 px-3 py-1.5 text-xs font-semibold text-zinc-900 transition hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-50 dark:hover:bg-zinc-700"
              >
                Stop
              </button>
            </div>
          </div>
        )}

        {upgradeModalOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
            <div className="w-full max-w-xl rounded-2xl border border-zinc-200 bg-white p-5 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-2">
                  <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Subscribe to keep searching</h2>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {access?.tier === "standard" ? QUOTA_MODAL_BODY_STANDARD_USER : QUOTA_MODAL_BODY_DEFAULT}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    const hits = search.errors.find(
                      (e) =>
                        e.includes("Monthly free search limit reached") || e.includes("Monthly included searches are used up"),
                    );
                    if (hits) setDismissedQuotaMessage(hits);
                    setUpgradeModalOpen(false);
                  }}
                  className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                  aria-label="Close"
                >
                  <span className="text-2xl leading-none">×</span>
                </button>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
                  <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Standard</h3>
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

                <div className="rounded-xl border border-emerald-300 p-4 dark:border-emerald-800">
                  <h3 className="font-medium text-zinc-900 dark:text-zinc-50">Premium</h3>
                  <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                    {PREMIUM_BULLETS_SHORT.map((line) => (
                      <li key={line}>• {line}</li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    disabled={isStartingCheckout}
                    onClick={() => void startCheckout("premium")}
                    className="mt-3 w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isStartingCheckout ? "Starting..." : "Subscribe Premium"}
                  </button>
                </div>
              </div>

              {upgradeError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{upgradeError}</p> : null}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
