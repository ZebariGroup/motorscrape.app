"use client";

import { useCallback, useEffect, useState } from "react";

import { useSearchStream } from "@/hooks/useSearchStream";
import { resolveApiUrl } from "@/lib/apiBase";
import { DealerProgressList } from "@/components/search/DealerProgressList";
import { InventoryResultsSection } from "@/components/search/InventoryResultsSection";
import { ResultFiltersPanel } from "@/components/search/ResultFiltersPanel";
import { SearchFormSection } from "@/components/search/SearchFormSection";
import { SiteHeader } from "@/components/SiteHeader";
import type { AccessSummary } from "@/types/access";

export function SearchExperience() {
  const [access, setAccess] = useState<AccessSummary | null>(null);

  const refreshAccess = useCallback(() => {
    fetch(resolveApiUrl("/auth/access-summary"), { credentials: "include" })
      .then((r) => r.json())
      .then(setAccess)
      .catch(() => setAccess(null));
  }, []);

  useEffect(() => {
    refreshAccess();
  }, [refreshAccess]);

  const { form, search, dealers, listings, filters } = useSearchStream({
    onStreamFinished: refreshAccess,
  });

  const lim = access?.limits;
  const maxDealersCap = lim?.max_dealerships ?? 30;
  const maxRadiusCap = lim?.max_radius_miles ?? 250;
  const scopePremium = lim?.inventory_scope_premium ?? true;
  const csvOk = lim?.csv_export ?? true;

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
          canSearch={form.location.trim().length >= 2}
          status={search.status}
          errors={search.errors}
          discoveredDealerPercent={dealers.discoveredDealerPercent}
          completedDealerPercent={dealers.completedDealerPercent}
          dealerListLength={dealers.dealerList.length}
          targetDealerCount={dealers.targetDealerCount}
          doneDealerCount={dealers.doneDealerCount}
          listingsCount={listings.listings.length}
          maxDealersCap={maxDealersCap}
          maxRadiusMilesCap={maxRadiusCap}
          inventoryScopePremium={scopePremium}
        />

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
                  <span className="text-zinc-900 dark:text-zinc-50">Scraping...</span>
                  <span className="text-zinc-500">
                    {dealers.doneDealerCount} / {dealers.targetDealerCount}
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                  <div
                    className="h-full bg-emerald-500 transition-all duration-500"
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
      </div>
    </>
  );
}
