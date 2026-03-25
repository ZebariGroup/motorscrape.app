"use client";

import { useMemo, useState } from "react";
import { VEHICLE_MAKES } from "@/lib/vehicleCatalog";

import { MultiModelSelect } from "./MultiModelSelect";

const RADIUS_CHOICES = [10, 25, 30, 50, 75, 100, 150, 250] as const;
const DEALER_STEPS = [4, 6, 8, 10, 12, 16, 18, 24, 30] as const;

function dealerChoices(cap: number): number[] {
  const xs = DEALER_STEPS.filter((n) => n <= cap);
  if (xs.length > 0) return [...xs];
  return [Math.max(1, Math.min(cap, 30))];
}

type Props = {
  running: boolean;
  location: string;
  setLocation: (v: string) => void;
  make: string;
  setMake: (v: string) => void;
  model: string;
  setModel: (v: string) => void;
  modelOptions: readonly string[];
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
  status: string | null;
  errors: string[];
  discoveredDealerPercent: number;
  completedDealerPercent: number;
  dealerListLength: number;
  targetDealerCount: number;
  doneDealerCount: number;
  listingsCount: number;
  /** When set, caps advanced options for the current account tier. */
  maxDealersCap?: number;
  maxRadiusMilesCap?: number;
  inventoryScopePremium?: boolean;
  allowAnyModel?: boolean;
};

export function SearchFormSection({
  running,
  location,
  setLocation,
  make,
  setMake,
  model,
  setModel,
  modelOptions,
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
  status,
  errors,
  discoveredDealerPercent,
  completedDealerPercent,
  dealerListLength,
  targetDealerCount,
  doneDealerCount,
  listingsCount,
  maxDealersCap = 30,
  maxRadiusMilesCap = 250,
  inventoryScopePremium = true,
  allowAnyModel = true,
}: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isFormExpanded, setIsFormExpanded] = useState(true);

  const radiusOptions = useMemo(
    () => RADIUS_CHOICES.filter((m) => m <= maxRadiusMilesCap),
    [maxRadiusMilesCap],
  );
  const dealerOptions = useMemo(() => dealerChoices(maxDealersCap), [maxDealersCap]);

  const handleSearch = () => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      setIsFormExpanded(false);
    }
    onSearch();
  };

  return (
    <section
      className={`rounded-2xl border bg-white p-5 sm:p-6 shadow-sm dark:bg-zinc-950 ${
        running
          ? "border-emerald-300/80 ring-2 ring-emerald-500/15 dark:border-emerald-800/60"
          : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      {!isFormExpanded ? (
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
              {location} {make ? `· ${make}` : ""} {model ? `· ${model}` : ""}
            </span>
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {radiusMiles} mi · {vehicleCondition} · {maxDealerships} dealers
            </span>
          </div>
          <button
            type="button"
            onClick={() => setIsFormExpanded(true)}
            className="rounded-lg bg-zinc-100 px-3 py-1.5 text-xs font-semibold text-zinc-900 transition hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-50 dark:hover:bg-zinc-700"
          >
            Edit scrape
          </button>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="col-span-full sm:col-span-1 lg:col-span-1 flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Location</span>
              <div className="relative">
                <input
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 pr-10 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  placeholder="City or ZIP"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  disabled={running}
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-400 hover:text-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 dark:hover:text-emerald-400"
                  title="Use my current location"
                  onClick={() => {
                    if (navigator.geolocation) {
                      navigator.geolocation.getCurrentPosition(
                        (pos) => setLocation(`${pos.coords.latitude}, ${pos.coords.longitude}`),
                        () => alert("Unable to retrieve your location. Please check your browser permissions.")
                      );
                    }
                  }}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-5 w-5">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
                  </svg>
                </button>
              </div>
            </label>
            <div className="col-span-full sm:col-span-1 lg:col-span-2 grid grid-cols-2 gap-4">
              <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Make</span>
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
                {VEHICLE_MAKES.map((makeOption) => (
                  <option key={makeOption} value={makeOption}>
                    {makeOption}
                  </option>
                ))}
              </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Model</span>
              <MultiModelSelect
                models={modelOptions}
                selectedModels={model ? model.split(",").filter(Boolean) : []}
                onChange={(models) => setModel(models.join(","))}
                disabled={running}
                allowAnyModel={allowAnyModel}
              />
            </label>
            </div>
            <div className="col-span-full sm:col-span-2 lg:col-span-1 grid grid-cols-2 gap-4">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Radius</span>
                <select
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  value={radiusMiles}
                  onChange={(e) => setRadiusMiles(e.target.value)}
                  disabled={running}
                >
                  {radiusOptions.map((m) => (
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
          <div className="mt-4 flex flex-col justify-end gap-2 sm:flex-row">
            <button
              type="button"
              className="relative inline-flex min-h-[2.75rem] flex-1 flex-col items-center justify-center overflow-hidden rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={running || !canSearch}
              onClick={handleSearch}
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
                  <span className="relative z-10 flex flex-col items-center gap-0.5 pb-1.5">
                    <span>Scraping…</span>
                    <span className="max-w-full truncate px-1 text-center text-[11px] font-normal text-white/90">
                      {`${dealerListLength}/${targetDealerCount} found · ${doneDealerCount}/${targetDealerCount} done · ${listingsCount} vehicles`}
                    </span>
                  </span>
                </>
              ) : (
                "Scrape inventory"
              )}
            </button>
            <button
              type="button"
              className="inline-flex flex-1 items-center justify-center rounded-lg border border-zinc-300 px-4 py-2.5 text-sm font-semibold text-zinc-800 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900"
              disabled={!running}
              onClick={onStop}
            >
              Stop
            </button>
          </div>
        </>
      )}
      {status ? (
        <div className={`space-y-1 ${isFormExpanded ? "mt-4" : "mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800/50"}`}>
          <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
            {running ? (
              <span
                className="inline-flex h-2 w-2 shrink-0 rounded-full bg-emerald-500 animate-pulse"
                aria-hidden
              />
            ) : null}
            <span>{status}</span>
          </p>
        </div>
      ) : null}
      {errors.length > 0 ? (
        <ul className={`list-disc space-y-1 pl-5 text-sm text-red-600 dark:text-red-400 ${isFormExpanded ? "mt-4" : "mt-3"}`}>
          {errors.map((err, i) => (
            <li key={`${i}-${err}`}>{err}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
