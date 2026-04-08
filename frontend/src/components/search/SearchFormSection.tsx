"use client";

import { useMemo, useState, useEffect, useRef, startTransition } from "react";
import type { MarketRegion } from "@/lib/marketRegion";
import { kmToMiles, milesToKm } from "@/lib/marketRegion";
import { getMakeGroupsForCategory, vehicleCategoryLabel } from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { SearchHistoryRunRow } from "@/types/searchHistory";

import { MultiModelSelect } from "./MultiModelSelect";
import { PlowTruck } from "./PlowTruck";
import { ScrapeMiniGame } from "./ScrapeMiniGame";
import { SearchWaitFactsRotator } from "./SearchWaitFactsRotator";
import { SearchHistoryModal } from "./SearchHistoryModal";

const RADIUS_CHOICES = [10, 25, 30, 50, 75, 100, 150, 250] as const;
const DEALER_STEPS = [4, 6, 8, 10, 12, 16, 18, 24, 30] as const;

function dealerChoices(cap: number): number[] {
  const xs = DEALER_STEPS.filter((n) => n <= cap);
  if (xs.length > 0) return [...xs];
  return [Math.max(1, Math.min(cap, 30))];
}

type Props = {
  running: boolean;
  reconnecting: boolean;
  location: string;
  setLocation: (v: string) => void;
  vehicleCategory: VehicleCategory;
  make: string;
  setMake: (v: string) => void;
  model: string;
  setModel: (v: string) => void;
  modelOptions: readonly string[] | { current: readonly string[]; discontinued: readonly string[] };
  usesCatalog: boolean;
  vehicleCondition: string;
  setVehicleCondition: (v: string) => void;
  radiusMiles: string;
  setRadiusMiles: (v: string) => void;
  inventoryScope: string;
  setInventoryScope: (v: string) => void;
  maxDealerships: string;
  setMaxDealerships: (v: string) => void;
  onSearch: () => void;
  onStop: () => void;
  canSearch: boolean;
  searchReadinessHint?: string | null;
  status: string | null;
  errors: string[];
  discoveredDealerPercent: number;
  completedDealerPercent: number;
  dealerListLength: number;
  targetDealerCount: number;
  doneDealerCount: number;
  activeDealerSummary: string | null;
  listingsCount: number;
  /** When set, caps advanced options for the current account tier. */
  maxDealersCap?: number;
  maxRadiusMilesCap?: number;
  inventoryScopePremium?: boolean;
  allowAnyModel?: boolean;
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
  marketRegion: MarketRegion;
};

export function SearchFormSection({
  running,
  reconnecting,
  location,
  setLocation,
  vehicleCategory,
  make,
  setMake,
  model,
  setModel,
  modelOptions,
  usesCatalog,
  vehicleCondition,
  setVehicleCondition,
  radiusMiles,
  setRadiusMiles,
  inventoryScope,
  setInventoryScope,
  maxDealerships,
  setMaxDealerships,
  onSearch,
  onStop,
  canSearch,
  searchReadinessHint,
  status,
  errors,
  discoveredDealerPercent,
  completedDealerPercent,
  dealerListLength,
  targetDealerCount,
  doneDealerCount,
  activeDealerSummary,
  listingsCount,
  maxDealersCap = 30,
  maxRadiusMilesCap = 250,
  inventoryScopePremium = true,
  allowAnyModel = true,
  applySavedSearchFromHistory,
  applyHistoryCriteriaOnly,
  marketRegion,
}: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [isFormExpanded, setIsFormExpanded] = useState(true);
  const [isGameActive, setIsGameActive] = useState(false);
  const [searchCompletedTick, setSearchCompletedTick] = useState(0);
  const [preferTapPlayHint, setPreferTapPlayHint] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const prevRunningRef = useRef(running);

  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 639px)");
    const coarse = window.matchMedia("(pointer: coarse)");
    const sync = () => setPreferTapPlayHint(narrow.matches || coarse.matches);
    sync();
    narrow.addEventListener("change", sync);
    coarse.addEventListener("change", sync);
    return () => {
      narrow.removeEventListener("change", sync);
      coarse.removeEventListener("change", sync);
    };
  }, []);

  useEffect(() => {
    if (prevRunningRef.current && !running) {
      startTransition(() => {
        setSearchCompletedTick((n) => n + 1);
      });
    }
    prevRunningRef.current = running;
  }, [running]);

  const radiusOptions = useMemo(
    () => RADIUS_CHOICES.filter((m) => m <= maxRadiusMilesCap),
    [maxRadiusMilesCap],
  );
  const radiusKmOptions = useMemo(() => {
    const capKm = milesToKm(maxRadiusMilesCap);
    return [10, 25, 40, 50, 80, 100, 150, 200].filter((k) => k <= capKm);
  }, [maxRadiusMilesCap]);
  const dealerOptions = useMemo(() => dealerChoices(maxDealersCap), [maxDealersCap]);
  const makeOptions = useMemo(
    () => getMakeGroupsForCategory(vehicleCategory, marketRegion),
    [vehicleCategory, marketRegion],
  );
  const radiusSummary = useMemo(() => {
    const mi = Number.parseInt(radiusMiles, 10);
    if (!Number.isFinite(mi)) return "";
    if (marketRegion === "eu") {
      return `${milesToKm(mi)} km`;
    }
    return `${mi} mi`;
  }, [radiusMiles, marketRegion]);

  useEffect(() => {
    if (marketRegion !== "eu") return;
    const mi = Number.parseInt(radiusMiles, 10);
    if (!Number.isFinite(mi)) return;
    const validMiles = new Set(radiusKmOptions.map((km) => kmToMiles(km)));
    if (validMiles.has(mi)) return;
    const nearest = [...validMiles].reduce((a, b) => (Math.abs(b - mi) < Math.abs(a - mi) ? b : a));
    setRadiusMiles(String(nearest));
  }, [marketRegion, radiusKmOptions, radiusMiles, setRadiusMiles]);

  const handleSearch = () => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setIsFormExpanded(false);
    }
    onSearch();
  };

  const isCollapsedSummary = !isGameActive && !isFormExpanded;
  const showWaitFactsRotator = running && isFormExpanded;

  return (
    <section
      className={`rounded-2xl border bg-white p-4 shadow-sm transition-all dark:bg-zinc-950 sm:p-6 ${
        running
          ? "border-emerald-300/80 ring-2 ring-emerald-500/15 dark:border-emerald-800/60"
          : "border-zinc-200 dark:border-zinc-800"
      } ${isCollapsedSummary ? "p-3 sm:p-6" : ""}`}
    >
      {isGameActive ? (
        <ScrapeMiniGame
          onClose={() => setIsGameActive(false)}
          searchCompletedTick={searchCompletedTick}
        />
      ) : isCollapsedSummary ? (
        <>
          <div className="sticky top-[calc(0.5rem+env(safe-area-inset-top))] z-40 mb-3 rounded-xl border border-zinc-200 bg-white/95 px-3 py-2 shadow-md backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  {vehicleCategoryLabel(vehicleCategory)} {location ? `· ${location}` : ""}
                  {make ? ` · ${make}` : ""}
                  {model ? ` · ${model}` : ""}
                </span>
                <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400">
                  {radiusSummary} · {vehicleCondition} · {maxDealerships} dealers
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIsFormExpanded(true)}
                className="shrink-0 rounded-lg bg-zinc-100 px-3 py-1.5 text-xs font-semibold text-zinc-900 transition hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-50 dark:hover:bg-zinc-700"
              >
                Edit scrape
              </button>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="grid gap-3 sm:gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="col-span-full sm:col-span-1 lg:col-span-1 flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Location</span>
              <div className="relative">
                <input
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 pr-10 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  placeholder="City, ZIP, or multiple separated by |"
                  value={location}
                  onChange={(e) => {
                    setLocationError(null);
                    setLocation(e.target.value);
                  }}
                  disabled={running}
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-400 hover:text-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 dark:hover:text-emerald-400"
                  title="Use my current location"
                  onClick={async () => {
                    if (navigator.geolocation) {
                      try {
                        // Show a temporary loading state in the input if possible, or just wait
                        navigator.geolocation.getCurrentPosition(
                          async (pos) => {
                            const lat = pos.coords.latitude;
                            const lng = pos.coords.longitude;
                            setLocationError(null);
                            try {
                              // Reverse geocode using a free public API (Nominatim) to get a readable city/zip
                              const res = await fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`);
                              const data = await res.json();
                              if (data && data.address) {
                                const city = data.address.city || data.address.town || data.address.village || data.address.suburb;
                                const state = data.address.state;
                                const zip = data.address.postcode;
                                
                                if (zip) {
                                  setLocation(zip);
                                } else if (city && state) {
                                  setLocation(`${city}, ${state}`);
                                } else {
                                  // Fallback to coordinates if reverse geocoding fails to yield a good string
                                  setLocation(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
                                }
                              } else {
                                setLocation(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
                              }
                            } catch {
                              // Fallback to coordinates if the fetch fails
                              setLocation(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
                            }
                          },
                          () => setLocationError("Unable to retrieve your location. Check browser permissions and try again."),
                        );
                      } catch {
                        setLocationError("Geolocation is not supported by your browser.");
                      }
                    } else {
                      setLocationError("Geolocation is not supported by your browser.");
                    }
                  }}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-5 w-5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
                  </svg>
                </button>
              </div>
              {locationError ? (
                <span className="mt-1 text-xs text-red-600 dark:text-red-400">{locationError}</span>
              ) : null}
            </label>
            <div className="col-span-full sm:col-span-1 lg:col-span-2 grid grid-cols-2 gap-3 sm:gap-4">
              <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Make</span>
              {usesCatalog ? (
                <select
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  value={make}
                  onChange={(e) => {
                    setMake(e.target.value);
                    setModel("");
                  }}
                  disabled={running}
                >
                  {allowAnyModel && <option value="">Any make</option>}
                  {!allowAnyModel && !make && <option value="" disabled>Select make</option>}
                  {makeOptions.current.length > 0 && (
                    <optgroup label="Current Makes">
                      {makeOptions.current.map((makeOption) => (
                        <option key={makeOption} value={makeOption}>
                          {makeOption}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {makeOptions.discontinued.length > 0 && (
                    <optgroup label="Discontinued Makes">
                      {makeOptions.discontinued.map((makeOption) => (
                        <option key={makeOption} value={makeOption}>
                          {makeOption} (Discontinued)
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              ) : (
                <input
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  placeholder={`${vehicleCategoryLabel(vehicleCategory)} make`}
                  value={make}
                  onChange={(e) => setMake(e.target.value)}
                  disabled={running}
                />
              )}
              </label>
              <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Model</span>
              {usesCatalog ? (
                <MultiModelSelect
                  models={modelOptions}
                  selectedModels={model ? model.split(",").filter(Boolean) : []}
                  onChange={(models) => setModel(models.join(","))}
                  disabled={running}
                  allowAnyModel={allowAnyModel}
                />
              ) : (
                <input
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  placeholder="Model or comma-separated models"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={running}
                />
              )}
            </label>
            </div>
            <div className="col-span-full sm:col-span-2 lg:col-span-1 grid grid-cols-2 gap-3 sm:gap-4">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">
                  Radius ({marketRegion === "eu" ? "km" : "miles"})
                </span>
                <select
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  value={radiusMiles}
                  onChange={(e) => setRadiusMiles(e.target.value)}
                  disabled={running}
                >
                  {marketRegion === "eu"
                    ? radiusKmOptions.map((km) => (
                        <option key={km} value={String(kmToMiles(km))}>
                          {km} km
                        </option>
                      ))
                    : radiusOptions.map((m) => (
                        <option key={m} value={String(m)}>
                          {m} miles
                        </option>
                      ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Condition</span>
                <select
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  value={vehicleCondition}
                  onChange={(e) => setVehicleCondition(e.target.value)}
                  disabled={running}
                >
                  <option value="all">All</option>
                  <option value="new">New only</option>
                  <option value="used">Used only</option>
                </select>
              </label>
            </div>
            {showAdvanced && (
              <>
                <label className="col-span-full sm:col-span-1 lg:col-span-2 flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Inventory scope</span>
                  <select
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    value={inventoryScope}
                    onChange={(e) => setInventoryScope(e.target.value)}
                    disabled={running || !inventoryScopePremium}
                  >
                    <option value="all">All listed</option>
                    <option value="on_lot_only" disabled={!inventoryScopePremium}>
                      On lot only
                    </option>
                    <option value="exclude_shared" disabled={!inventoryScopePremium}>
                      Exclude shared/off-site
                    </option>
                    <option value="include_transit" disabled={!inventoryScopePremium}>
                      Include in transit
                    </option>
                  </select>
                  {!inventoryScopePremium ? (
                    <span className="text-xs text-zinc-500 dark:text-zinc-400">
                      Advanced inventory scope is available on Standard and above.
                    </span>
                  ) : null}
                </label>
                <label className="col-span-full sm:col-span-1 lg:col-span-2 flex flex-col gap-1 text-sm">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">Max dealerships</span>
                  <select
                    className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                    value={maxDealerships}
                    onChange={(e) => setMaxDealerships(e.target.value)}
                    disabled={running}
                  >
                    {dealerOptions.map((n) => (
                      <option key={n} value={String(n)}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>
          <div className="mt-3 flex items-center justify-end">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-xs font-medium text-zinc-500 underline-offset-2 hover:text-zinc-800 hover:underline dark:text-zinc-400 dark:hover:text-zinc-200"
            >
              {showAdvanced ? "Hide advanced options" : "Show advanced options"}
            </button>
          </div>
          <div className="mt-4 flex flex-col justify-end gap-2 sm:flex-row sm:items-stretch">
            <button
              type="button"
              className={`relative inline-flex min-h-[2.75rem] flex-1 flex-col items-center justify-center overflow-hidden rounded-lg bg-emerald-600 px-4 py-2.5 text-base font-bold text-white shadow-sm transition hover:bg-emerald-500 hover:text-white ${
                !running && !canSearch ? "cursor-not-allowed opacity-50" : ""
              }`}
              disabled={!running && !canSearch}
              onClick={running ? undefined : handleSearch}
              onDoubleClick={() => {
                if (running) setIsGameActive(true);
              }}
            >
              {running ? (
                <>
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-px" aria-hidden>
                    <div className="h-0.5 w-full bg-black/15 dark:bg-black/30">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-300 via-emerald-200 to-teal-300 transition-[width] duration-700 ease-out"
                        style={{ width: `${discoveredDealerPercent}%` }}
                      />
                    </div>
                    <div className="h-0.5 w-full bg-black/15 dark:bg-black/30">
                      <div
                        className="h-full bg-gradient-to-r from-amber-400 via-amber-300 to-yellow-200 transition-[width] duration-700 ease-out"
                        style={{ width: `${completedDealerPercent}%` }}
                      />
                    </div>
                  </div>
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 px-2" aria-hidden>
                    <div className="scrape-truck-track">
                      <div className="scrape-truck-floor" />
                      <div className="scrape-truck-ruts" />
                      <span className="scrape-truck">
                        <PlowTruck />
                      </span>
                    </div>
                  </div>
                  <span className="relative z-10 flex flex-col items-center gap-0.5 pb-1.5 leading-tight">
                    <span>{reconnecting ? "Reconnecting…" : "Scraping…"}</span>
                    <span className="max-w-full truncate px-1 text-center text-xs font-medium text-white/95">
                      {`${dealerListLength}/${targetDealerCount} found · ${doneDealerCount}/${targetDealerCount} done · ${listingsCount} vehicles`}
                    </span>
                    {!isGameActive && (
                      <span className="mt-0.5 text-[11px] font-semibold uppercase tracking-wider text-white/80 animate-pulse">
                        {preferTapPlayHint ? "Tap Play to pass time" : "Double-click to play"}
                      </span>
                    )}
                    {!isGameActive && preferTapPlayHint && running ? (
                      <button
                        type="button"
                        className="relative z-20 mt-1 rounded-md bg-white/20 px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-white backdrop-blur-sm transition hover:bg-white/30"
                        onClick={(e) => {
                          e.stopPropagation();
                          setIsGameActive(true);
                        }}
                      >
                        Play
                      </button>
                    ) : null}
                  </span>
                </>
              ) : (
                "Scrape inventory"
              )}
            </button>
            <div className="flex flex-1 gap-2 sm:max-w-none sm:flex-initial sm:shrink-0">
              <button
                type="button"
                className="inline-flex min-h-[2.75rem] flex-1 items-center justify-center rounded-lg border border-zinc-300 px-3 py-2 text-xs font-semibold text-zinc-800 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900 sm:flex-initial sm:min-w-[4.5rem]"
                disabled={!running}
                onClick={onStop}
              >
                Stop
              </button>
              <button
                type="button"
                onClick={() => setHistoryModalOpen(true)}
                className="inline-flex min-h-[2.75rem] min-w-[2.75rem] shrink-0 items-center justify-center rounded-lg border border-zinc-300 text-zinc-700 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900"
                aria-label="Recent searches"
                title="Recent searches"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  className="h-5 w-5"
                  aria-hidden
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </button>
            </div>
          </div>
          {!running && searchReadinessHint ? (
            <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">{searchReadinessHint}</p>
          ) : null}
        </>
      )}
      {status || running ? (
        <div
          className={`space-y-2 ${
            isFormExpanded
              ? "mt-4"
              : "rounded-xl border border-zinc-200/80 bg-zinc-50/85 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-900/40"
          }`}
        >
          {status ? (
            <p className={`flex flex-wrap items-center gap-2 text-zinc-600 dark:text-zinc-400 ${isFormExpanded ? "text-sm" : "text-xs"}`}>
              {running ? (
                <span
                  className="inline-flex h-2 w-2 shrink-0 rounded-full bg-emerald-500 animate-pulse"
                  aria-hidden
                />
              ) : null}
              <span>{status}</span>
            </p>
          ) : null}
          {running && activeDealerSummary ? (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{activeDealerSummary}</p>
          ) : null}
          {showWaitFactsRotator ? (
            <SearchWaitFactsRotator
              running={running}
              make={make}
              model={model}
              vehicleCategory={vehicleCategory}
              vehicleCondition={vehicleCondition}
            />
          ) : null}
        </div>
      ) : null}
      {errors.length > 0 ? (
        <ul className={`list-disc space-y-1 pl-5 text-sm text-red-600 dark:text-red-400 ${isFormExpanded ? "mt-4" : "mt-3"}`}>
          {errors.map((err, i) => (
            <li key={`${i}-${err}`}>{err}</li>
          ))}
        </ul>
      ) : null}
      <SearchHistoryModal
        open={historyModalOpen}
        onOpenChange={setHistoryModalOpen}
        applySavedSearchFromHistory={applySavedSearchFromHistory}
        applyHistoryCriteriaOnly={applyHistoryCriteriaOnly}
      />
    </section>
  );
}
