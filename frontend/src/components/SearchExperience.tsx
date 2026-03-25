"use client";

import { useSearchStream } from "@/hooks/useSearchStream";
import { DealerProgressList } from "@/components/search/DealerProgressList";
import { InventoryResultsSection } from "@/components/search/InventoryResultsSection";
import { ResultFiltersPanel } from "@/components/search/ResultFiltersPanel";
import { SearchFormSection } from "@/components/search/SearchFormSection";

export function SearchExperience() {
  const { form, search, dealers, listings, filters } = useSearchStream();

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-4 py-10 pb-24 sm:px-6 sm:pb-10">
      <header className="space-y-2">
        <p className="text-sm font-medium tracking-wide text-emerald-700 uppercase">Motorscrape</p>
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
          Local dealership inventory, one place
        </h1>
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">We crawl so you can drive.</p>
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
        />
      </div>

      {search.running && (
        <div className="fixed inset-x-0 bottom-0 z-50 border-t border-zinc-200 bg-white/90 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] backdrop-blur-md sm:hidden dark:border-zinc-800 dark:bg-zinc-950/90 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.1)]">
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-1 flex-col gap-1.5">
              <div className="flex items-center justify-between text-xs font-medium">
                <span className="text-zinc-900 dark:text-zinc-50">Searching...</span>
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
  );
}
