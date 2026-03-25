"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getApiBaseUrl } from "@/lib/config";
import { getModelsForMake, VEHICLE_MAKES } from "@/lib/vehicleCatalog";
import type { DealershipProgress, VehicleListing } from "@/types/inventory";

type AggregatedListing = VehicleListing & {
  dealership: string;
  dealership_website: string;
};

function formatMoney(n: number | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

function locationBadge(v: AggregatedListing) {
  if (v.is_in_transit) return "In transit";
  if (v.is_offsite || v.is_shared_inventory) return "Shared / off-site";
  if (v.is_in_stock) return "On lot";
  return v.availability_status ?? null;
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function sliderStep(min: number, max: number, fallback: number) {
  const span = Math.max(0, max - min);
  if (span <= 0) return fallback;
  return Math.max(fallback, Math.round(span / 100));
}

export function SearchExperience() {
  const [location, setLocation] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [vehicleCondition, setVehicleCondition] = useState("all");
  const [radiusMiles, setRadiusMiles] = useState("25");
  const [inventoryScope, setInventoryScope] = useState("all");
  const [maxDealerships, setMaxDealerships] = useState("8");
  const [status, setStatus] = useState<string | null>(null);
  const [dealers, setDealers] = useState<Record<string, DealershipProgress>>({});
  const [listings, setListings] = useState<AggregatedListing[]>([]);
  const [priceFilterMin, setPriceFilterMin] = useState<number | null>(null);
  const [priceFilterMax, setPriceFilterMax] = useState<number | null>(null);
  const [yearFilter, setYearFilter] = useState("");
  const [bodyStyleFilter, setBodyStyleFilter] = useState("");
  const [colorFilter, setColorFilter] = useState("");
  const [filtersExpanded, setFiltersExpanded] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const esRef = useRef<EventSource | null>(null);

  const dealerList = useMemo(
    () => Object.values(dealers).sort((a, b) => a.index - b.index),
    [dealers],
  );

  const doneDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "done" || d.status === "error").length,
    [dealerList],
  );

  const targetDealerCount = useMemo(() => {
    const parsed = Number.parseInt(maxDealerships, 10);
    return Number.isFinite(parsed) ? parsed : 8;
  }, [maxDealerships]);

  const modelOptions = useMemo(() => getModelsForMake(make), [make]);

  const discoveredDealerPercent = useMemo(
    () => clampPercent((dealerList.length / Math.max(targetDealerCount, 1)) * 100),
    [dealerList.length, targetDealerCount],
  );

  const completedDealerPercent = useMemo(
    () => clampPercent((doneDealerCount / Math.max(targetDealerCount, 1)) * 100),
    [doneDealerCount, targetDealerCount],
  );

  const pendingDealerSlots = useMemo(() => {
    if (!running) return 0;
    return Math.max(0, targetDealerCount - dealerList.length);
  }, [dealerList.length, running, targetDealerCount]);

  const loadingDealerCards = useMemo(
    () =>
      Array.from({
        length: Math.min(
          Math.max(pendingDealerSlots, dealerList.length === 0 && running ? 3 : 0),
          4,
        ),
      }),
    [dealerList.length, pendingDealerSlots, running],
  );

  const loadingInventoryCards = useMemo(
    () => Array.from({ length: listings.length === 0 && running ? 4 : 0 }),
    [listings.length, running],
  );

  const priceBounds = useMemo(() => {
    const values = listings
      .map((listing) => listing.price)
      .filter((value): value is number => value != null && !Number.isNaN(value));
    if (values.length === 0) return null;
    return {
      min: Math.min(...values),
      max: Math.max(...values),
    };
  }, [listings]);

  const yearOptions = useMemo(
    () =>
      Array.from(
        new Set(listings.map((listing) => listing.year).filter((year): year is number => year != null)),
      ).sort((a, b) => b - a),
    [listings],
  );

  const bodyStyleOptions = useMemo(
    () =>
      Array.from(
        new Set(
          listings
            .map((listing) => listing.body_style?.trim())
            .filter((bodyStyle): bodyStyle is string => Boolean(bodyStyle)),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [listings],
  );

  const colorOptions = useMemo(
    () =>
      Array.from(
        new Set(
          listings
            .map((listing) => listing.exterior_color?.trim())
            .filter((color): color is string => Boolean(color)),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [listings],
  );

  const effectivePriceMin = useMemo(() => {
    if (!priceBounds) return null;
    return clampNumber(
      priceFilterMin ?? priceBounds.min,
      priceBounds.min,
      priceFilterMax ?? priceBounds.max,
    );
  }, [priceBounds, priceFilterMax, priceFilterMin]);

  const effectivePriceMax = useMemo(() => {
    if (!priceBounds) return null;
    return clampNumber(
      priceFilterMax ?? priceBounds.max,
      effectivePriceMin ?? priceBounds.min,
      priceBounds.max,
    );
  }, [effectivePriceMin, priceBounds, priceFilterMax]);

  const filteredListings = useMemo(() => {
    return listings.filter((listing) => {
      if (yearFilter && String(listing.year ?? "") !== yearFilter) {
        return false;
      }
      if (bodyStyleFilter && listing.body_style !== bodyStyleFilter) {
        return false;
      }
      if (colorFilter && listing.exterior_color !== colorFilter) {
        return false;
      }
      if (effectivePriceMin != null && (listing.price == null || listing.price < effectivePriceMin)) {
        return false;
      }
      if (effectivePriceMax != null && (listing.price == null || listing.price > effectivePriceMax)) {
        return false;
      }
      return true;
    });
  }, [
    bodyStyleFilter,
    colorFilter,
    effectivePriceMax,
    effectivePriceMin,
    listings,
    yearFilter,
  ]);

  const activeResultFilterCount = useMemo(() => {
    let count = 0;
    if (
      priceBounds &&
      effectivePriceMin != null &&
      effectivePriceMax != null &&
      (effectivePriceMin > priceBounds.min || effectivePriceMax < priceBounds.max)
    ) {
      count += 1;
    }
    if (
      yearFilter
    ) {
      count += 1;
    }
    if (bodyStyleFilter) {
      count += 1;
    }
    if (colorFilter) {
      count += 1;
    }
    return count;
  }, [
    bodyStyleFilter,
    colorFilter,
    effectivePriceMax,
    effectivePriceMin,
    priceBounds,
    yearFilter,
  ]);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const stopStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
  }, []);

  const startSearch = useCallback(() => {
    stopStream();
    setErrors([]);
    setListings([]);
    setDealers({});
    setStatus(null);
    const startedAt = Date.now();
    setNowMs(startedAt);

    const base = getApiBaseUrl();
    const params = new URLSearchParams({
      location: location.trim(),
      make: make.trim(),
      model: model.trim(),
      vehicle_condition: vehicleCondition,
      radius_miles: radiusMiles,
      inventory_scope: inventoryScope,
      max_dealerships: maxDealerships,
    });
    const url = `${base}/search/stream?${params.toString()}`;

    setRunning(true);
    const es = new EventSource(url);
    esRef.current = es;

    const onStatus = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as { message?: string };
        if (data.message) setStatus(data.message);
      } catch {
        /* ignore */
      }
    };

    const onDealership = (ev: MessageEvent) => {
      try {
        const d = JSON.parse(ev.data) as DealershipProgress;
        const key = d.website || `${d.name}-${d.index}`;
        setDealers((prev) => {
          const prevRow = prev[key];
          const statusChanged = prevRow?.status !== d.status;
          const phaseSince = statusChanged ? Date.now() : (prevRow?.phaseSince ?? Date.now());
          return { ...prev, [key]: { ...prevRow, ...d, phaseSince } };
        });
      } catch {
        /* ignore */
      }
    };

    const onVehicles = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as {
          dealership?: string;
          website?: string;
          listings?: VehicleListing[];
        };
        const dealerName = data.dealership ?? "Unknown";
        const dealerSite = data.website ?? "";
        const batch = data.listings ?? [];
        setListings((prev) => [
          ...prev,
          ...batch.map((v) => ({
            ...v,
            dealership: dealerName,
            dealership_website: dealerSite,
          })),
        ]);
      } catch {
        /* ignore */
      }
    };

    const onError = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as { message?: string };
        if (data.message) setErrors((e) => [...e, data.message!]);
      } catch {
        /* ignore */
      }
    };

    const onDone = (ev: Event) => {
      const me = ev as MessageEvent;
      try {
        const data = JSON.parse(me.data) as {
          ok?: boolean;
          dealer_discovery_count?: number;
          dealer_deduped_count?: number;
          max_dealerships?: number;
        };
        const dealerPart =
          data.dealer_discovery_count != null && data.dealer_deduped_count != null
            ? `${data.dealer_deduped_count} dealerships searched`
            : data.max_dealerships != null
              ? `${data.max_dealerships} dealerships searched`
              : null;
        if (dealerPart) {
          setStatus(`Search finished · ${dealerPart}`);
        } else {
          setStatus((s) => s ?? "Search finished.");
        }
      } catch {
        setStatus((s) => s ?? "Search finished.");
      }
      stopStream();
    };

    es.addEventListener("status", onStatus);
    es.addEventListener("dealership", onDealership);
    es.addEventListener("vehicles", onVehicles);
    es.addEventListener("search_error", onError);
    es.addEventListener("done", onDone);

    es.onerror = () => {
      setErrors((e) => [...e, "Connection to search stream lost or failed."]);
      stopStream();
    };
  }, [
    inventoryScope,
    location,
    make,
    maxDealerships,
    model,
    radiusMiles,
    stopStream,
    vehicleCondition,
  ]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-4 py-10 sm:px-6">
      <header className="space-y-2">
        <p className="text-sm font-medium tracking-wide text-emerald-700 uppercase">
          Motorscrape
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
          Local dealership inventory, one place
        </h1>
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">
          We crawl so you can drive.
        </p>
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">
          Enter where you are shopping and what you want. We discover nearby dealerships, fetch
          their sites, and extract listings in real time.
        </p>
      </header>

      <section
        className={`rounded-2xl border bg-white p-6 shadow-sm dark:bg-zinc-950 ${
          running
            ? "border-emerald-300/80 ring-2 ring-emerald-500/15 dark:border-emerald-800/60"
            : "border-zinc-200 dark:border-zinc-800"
        }`}
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Location</span>
            <input
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              placeholder="City or ZIP"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              disabled={running}
            />
          </label>
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
              <option value="">Any make</option>
              {VEHICLE_MAKES.map((makeOption) => (
                <option key={makeOption} value={makeOption}>
                  {makeOption}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Model</span>
            <select
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={running || modelOptions.length === 0}
            >
              <option value="">{make ? "Any model" : "Select make first"}</option>
              {modelOptions.map((modelOption) => (
                <option key={modelOption} value={modelOption}>
                  {modelOption}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">
              Dealership radius
            </span>
            <select
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              value={radiusMiles}
              onChange={(e) => setRadiusMiles(e.target.value)}
              disabled={running}
            >
              <option value="10">10 miles</option>
              <option value="25">25 miles</option>
              <option value="30">30 miles</option>
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
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Inventory scope</span>
            <select
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              value={inventoryScope}
              onChange={(e) => setInventoryScope(e.target.value)}
              disabled={running}
            >
              <option value="all">All listed</option>
              <option value="on_lot_only">On lot only</option>
              <option value="exclude_shared">Exclude shared/off-site</option>
              <option value="include_transit">Include in transit</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Max dealerships</span>
            <select
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              value={maxDealerships}
              onChange={(e) => setMaxDealerships(e.target.value)}
              disabled={running}
            >
              <option value="8">8</option>
              <option value="12">12</option>
              <option value="16">16</option>
              <option value="24">24</option>
            </select>
          </label>
        </div>
        <div className="mt-4 flex flex-col justify-end gap-2 sm:flex-row">
            <button
              type="button"
              className="relative inline-flex min-h-[2.75rem] flex-1 flex-col items-center justify-center overflow-hidden rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={running || location.trim().length < 2}
              onClick={startSearch}
            >
              {running ? (
                <>
                  <div
                    className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-px"
                    aria-hidden
                  >
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
                    <span>Searching…</span>
                    <span className="max-w-full truncate px-1 text-center text-[11px] font-normal text-white/90">
                      {`${dealerList.length}/${targetDealerCount} found · ${doneDealerCount}/${targetDealerCount} done · ${listings.length} vehicles`}
                    </span>
                  </span>
                </>
              ) : (
                "Search inventory"
              )}
            </button>
            <button
              type="button"
              className="inline-flex flex-1 items-center justify-center rounded-lg border border-zinc-300 px-4 py-2.5 text-sm font-semibold text-zinc-800 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900"
              disabled={!running}
              onClick={stopStream}
            >
              Stop
            </button>
        </div>
        {status ? (
          <div className="mt-4 space-y-1">
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
          <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-red-600 dark:text-red-400">
            {errors.map((err, i) => (
              <li key={`${i}-${err}`}>{err}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <div className="grid gap-8 lg:grid-cols-3">
        <section className="lg:col-span-1">
          <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <button
              type="button"
              onClick={() => setFiltersExpanded((open) => !open)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
            >
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                    Result filters
                  </h2>
                  {activeResultFilterCount > 0 ? (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                      {activeResultFilterCount} active
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                  Narrow the streamed inventory by year, style, color, and price.
                </p>
              </div>
              <span className="text-lg text-zinc-400">{filtersExpanded ? "−" : "+"}</span>
            </button>
            {filtersExpanded ? (
              <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
                <div className="space-y-5">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="font-medium text-zinc-700 dark:text-zinc-300">Year</span>
                      <select
                        value={yearFilter}
                        onChange={(e) => setYearFilter(e.target.value)}
                        className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      >
                        <option value="">All years</option>
                        {yearOptions.map((year) => (
                          <option key={year} value={String(year)}>
                            {year}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="font-medium text-zinc-700 dark:text-zinc-300">Style</span>
                      <select
                        value={bodyStyleFilter}
                        onChange={(e) => setBodyStyleFilter(e.target.value)}
                        className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      >
                        <option value="">All styles</option>
                        {bodyStyleOptions.map((bodyStyle) => (
                          <option key={bodyStyle} value={bodyStyle}>
                            {bodyStyle}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-xs">
                      <span className="font-medium text-zinc-700 dark:text-zinc-300">Color</span>
                      <select
                        value={colorFilter}
                        onChange={(e) => setColorFilter(e.target.value)}
                        className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      >
                        <option value="">All colors</option>
                        {colorOptions.map((color) => (
                          <option key={color} value={color}>
                            {color}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium text-zinc-700 dark:text-zinc-300">Price</span>
                      <span className="text-zinc-500 dark:text-zinc-400">
                        {priceBounds && effectivePriceMin != null && effectivePriceMax != null
                          ? `${formatMoney(effectivePriceMin)} to ${formatMoney(effectivePriceMax)}`
                          : "No priced vehicles yet"}
                      </span>
                    </div>
                    {priceBounds && effectivePriceMin != null && effectivePriceMax != null ? (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <input
                            type="range"
                            aria-label="Minimum price"
                            min={priceBounds.min}
                            max={priceBounds.max}
                            step={sliderStep(priceBounds.min, priceBounds.max, 500)}
                            value={effectivePriceMin}
                            onChange={(e) =>
                              setPriceFilterMin(
                                Math.min(Number(e.target.value), effectivePriceMax),
                              )
                            }
                            className="min-w-0 flex-1 accent-emerald-600"
                          />
                          <input
                            type="range"
                            aria-label="Maximum price"
                            min={priceBounds.min}
                            max={priceBounds.max}
                            step={sliderStep(priceBounds.min, priceBounds.max, 500)}
                            value={effectivePriceMax}
                            onChange={(e) =>
                              setPriceFilterMax(
                                Math.max(Number(e.target.value), effectivePriceMin),
                              )
                            }
                            className="min-w-0 flex-1 accent-emerald-600"
                          />
                        </div>
                        <div className="flex justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                          <span>{formatMoney(priceBounds.min)}</span>
                          <span>{formatMoney(priceBounds.max)}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/70 dark:text-zinc-400">
                        Drag bars appear once priced inventory is loaded.
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        setPriceFilterMin(null);
                        setPriceFilterMax(null);
                        setYearFilter("");
                        setBodyStyleFilter("");
                        setColorFilter("");
                      }}
                      className="text-xs font-medium text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
                    >
                      Clear filters
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
          <h2 className="mb-3 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Dealerships
          </h2>
          <ul className="space-y-3">
            {dealerList.length === 0 ? (
              running ? (
                <>
                  {loadingDealerCards.map((_, idx) => (
                    <li
                      key={`dealer-loading-${idx}`}
                      className="relative overflow-hidden rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 p-4 dark:border-emerald-900/50 dark:bg-emerald-950/20"
                    >
                      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/60 to-transparent motion-safe:animate-[shimmer_2s_infinite] dark:via-white/10" />
                      <div className="relative space-y-3">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500 motion-safe:animate-pulse" />
                          <div className="h-4 w-40 rounded bg-emerald-200/80 dark:bg-emerald-900/70" />
                        </div>
                        <div className="h-3 w-56 rounded bg-zinc-200/80 dark:bg-zinc-800" />
                        <div className="flex gap-2">
                          <div className="h-5 w-20 rounded-full bg-amber-200/80 dark:bg-amber-900/60" />
                          <div className="h-5 w-28 rounded-full bg-zinc-200/80 dark:bg-zinc-800" />
                        </div>
                        <p className="text-xs text-zinc-500 dark:text-zinc-400">
                          Searching nearby dealerships and building the queue…
                        </p>
                      </div>
                    </li>
                  ))}
                </>
              ) : (
                <li className="text-sm text-zinc-500">No dealerships yet — run a search.</li>
              )
            ) : (
              <>
                {dealerList.map((d) => {
                  const phaseSec =
                    d.phaseSince != null
                      ? Math.max(0, Math.floor((nowMs - d.phaseSince) / 1000))
                      : 0;
                  const isBusy = d.status === "scraping" || d.status === "parsing";
                  return (
                    <li
                      key={d.website + d.index}
                      className={`relative overflow-hidden rounded-xl border bg-white p-4 text-sm transition-all dark:bg-zinc-950 ${
                        isBusy
                          ? "border-amber-200 shadow-sm shadow-amber-100/50 dark:border-amber-900/50 dark:shadow-none"
                          : "border-zinc-200 dark:border-zinc-800"
                      }`}
                    >
                      {isBusy ? (
                        <>
                          <div
                            className="pointer-events-none absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent animate-pulse"
                            aria-hidden
                          />
                          <div
                            className="pointer-events-none absolute inset-y-0 left-0 w-20 -translate-x-full bg-gradient-to-r from-transparent via-emerald-200/40 to-transparent motion-safe:animate-[shimmer_2.4s_infinite] dark:via-emerald-400/10"
                            aria-hidden
                          />
                        </>
                      ) : null}
                      <div className="font-medium text-zinc-900 dark:text-zinc-50">{d.name}</div>
                      {d.address ? (
                        <div className="mt-1 text-xs text-zinc-500">{d.address}</div>
                      ) : null}
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                        <span
                          className={
                            d.status === "done"
                              ? "rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                              : d.status === "error"
                                ? "rounded-full bg-red-50 px-2 py-0.5 font-medium text-red-800 dark:bg-red-950 dark:text-red-200"
                                : "rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-900 motion-safe:animate-pulse dark:bg-amber-950 dark:text-amber-100"
                          }
                        >
                          {d.status}
                        </span>
                        {d.status === "scraping" && d.fetch_method ? (
                          <span className="text-zinc-500">via {d.fetch_method}</span>
                        ) : null}
                        {d.status === "parsing" ? (
                          <span className="text-zinc-500">
                            AI extraction… {phaseSec}s
                            {d.fetch_method ? (
                              <span className="text-zinc-400"> (page via {d.fetch_method})</span>
                            ) : null}
                          </span>
                        ) : null}
                        {d.status === "scraping" ? (
                          <span className="text-zinc-500">Fetching… {phaseSec}s</span>
                        ) : null}
                        {d.listings_found != null ? (
                          <span className="text-zinc-500">{d.listings_found} listings</span>
                        ) : null}
                      </div>
                      {d.info ? (
                        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">{d.info}</p>
                      ) : null}
                      {d.error ? <p className="mt-2 text-xs text-red-600">{d.error}</p> : null}
                      {d.website ? (
                        <a
                          href={d.website}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-2 inline-block text-xs font-medium text-emerald-700 underline-offset-2 hover:underline dark:text-emerald-400"
                        >
                          Open site
                        </a>
                      ) : null}
                    </li>
                  );
                })}
                {loadingDealerCards.map((_, idx) => (
                  <li
                    key={`dealer-pending-${idx}`}
                    className="relative overflow-hidden rounded-xl border border-dashed border-zinc-200 bg-zinc-50/70 p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900/60"
                  >
                    <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/70 to-transparent motion-safe:animate-[shimmer_2.2s_infinite] dark:via-white/10" />
                    <div className="relative space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-2.5 w-2.5 rounded-full bg-amber-500 motion-safe:animate-pulse" />
                        <div className="h-4 w-36 rounded bg-zinc-200 dark:bg-zinc-800" />
                      </div>
                      <div className="h-3 w-52 rounded bg-zinc-200 dark:bg-zinc-800" />
                      <div className="flex gap-2">
                        <div className="h-5 w-24 rounded-full bg-zinc-200 dark:bg-zinc-800" />
                        <div className="h-5 w-20 rounded-full bg-zinc-200 dark:bg-zinc-800" />
                      </div>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        Discovering another dealership in range…
                      </p>
                    </div>
                  </li>
                ))}
              </>
            )}
          </ul>
        </section>

        <section className="lg:col-span-2">
          <div className="mb-3 flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Inventory</h2>
            <span className="text-sm text-zinc-500">
              {filteredListings.length}
              {filteredListings.length !== listings.length ? ` of ${listings.length}` : ""} vehicles
            </span>
          </div>
          {listings.length === 0 ? (
            running ? (
              <div className="space-y-4">
                <p className="text-sm text-zinc-500">
                  Still scanning dealers… New cards appear as each site is contacted. Matches show
                  here as soon as AI finishes a page.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                  {loadingInventoryCards.map((_, idx) => (
                    <article
                      key={`inventory-loading-${idx}`}
                      className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950"
                    >
                      <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-zinc-100/90 to-transparent motion-safe:animate-[shimmer_2.1s_infinite] dark:via-white/5" />
                      <div className="relative">
                        <div className="aspect-[16/10] w-full bg-zinc-100 dark:bg-zinc-900" />
                        <div className="space-y-3 p-4">
                          <div className="h-5 w-3/4 rounded bg-zinc-200 dark:bg-zinc-800" />
                          <div className="grid grid-cols-2 gap-2">
                            <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                            <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                            <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                            <div className="h-3 rounded bg-zinc-200 dark:bg-zinc-800" />
                          </div>
                          <div className="h-3 w-1/2 rounded bg-zinc-200 dark:bg-zinc-800" />
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-zinc-500">
                Results stream in as each dealership is scraped. Large dealer sites may take
                longer.
              </p>
            )
          ) : filteredListings.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 px-4 py-6 text-sm text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-300">
              No vehicles match the current result filters.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {filteredListings.map((v, idx) => (
                <article
                  key={`${v.dealership}-${v.vin ?? v.listing_url ?? v.raw_title ?? idx}`}
                  className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950"
                >
                  <div className="aspect-[16/10] w-full bg-zinc-100 dark:bg-zinc-900">
                    {v.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={v.image_url}
                        alt={v.raw_title ?? "Vehicle"}
                        className="h-full w-full object-cover"
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-zinc-400">
                        No image
                      </div>
                    )}
                  </div>
                  <div className="space-y-2 p-4">
                    <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                      {v.raw_title ??
                        ([v.year, v.make, v.model, v.trim].filter(Boolean).join(" ") || "Vehicle")}
                    </h3>
                    <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
                      <dt className="font-medium text-zinc-500">Price</dt>
                      <dd>{formatMoney(v.price)}</dd>
                      <dt className="font-medium text-zinc-500">Mileage</dt>
                      <dd>{v.mileage != null ? `${v.mileage.toLocaleString()} mi` : "—"}</dd>
                      <dt className="font-medium text-zinc-500">Condition</dt>
                      <dd>{v.vehicle_condition ?? "—"}</dd>
                      <dt className="font-medium text-zinc-500">VIN</dt>
                      <dd className="truncate">{v.vin ?? "—"}</dd>
                      <dt className="font-medium text-zinc-500">Dealer</dt>
                      <dd className="truncate">{v.dealership}</dd>
                      <dt className="font-medium text-zinc-500">Availability</dt>
                      <dd>{locationBadge(v) ?? "—"}</dd>
                      <dt className="font-medium text-zinc-500">Location</dt>
                      <dd className="truncate">{v.inventory_location ?? "—"}</dd>
                    </dl>
                    <div className="flex flex-wrap gap-2 pt-1">
                      {v.listing_url ? (
                        <a
                          href={v.listing_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs font-semibold text-emerald-700 underline-offset-2 hover:underline dark:text-emerald-400"
                        >
                          View listing
                        </a>
                      ) : null}
                      <a
                        href={v.dealership_website}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-semibold text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
                      >
                        Dealer site
                      </a>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
