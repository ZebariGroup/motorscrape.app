"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getApiBaseUrl } from "@/lib/config";
import { getModelsForMake, VEHICLE_MAKES } from "@/lib/vehicleCatalog";
import type { DealershipProgress, VehicleListing } from "@/types/inventory";

type AggregatedListing = VehicleListing & {
  dealership: string;
  dealership_website: string;
};

/** Matches backend default parse cap: openai_timeout (75) + orchestrator margin (~5). */
const PARSING_HINT_MAX_SEC = 80;

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

function parseOptionalNumber(value: string) {
  const normalized = value.replaceAll(",", "").trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
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
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minMileage, setMinMileage] = useState("");
  const [maxMileage, setMaxMileage] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [searchStartedAtMs, setSearchStartedAtMs] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const dealerList = useMemo(
    () => Object.values(dealers).sort((a, b) => a.index - b.index),
    [dealers],
  );

  const activeDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "scraping" || d.status === "parsing").length,
    [dealerList],
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

  const parsedMinPrice = useMemo(() => parseOptionalNumber(minPrice), [minPrice]);
  const parsedMaxPrice = useMemo(() => parseOptionalNumber(maxPrice), [maxPrice]);
  const parsedMinMileage = useMemo(() => parseOptionalNumber(minMileage), [minMileage]);
  const parsedMaxMileage = useMemo(() => parseOptionalNumber(maxMileage), [maxMileage]);

  const filteredListings = useMemo(() => {
    return listings.filter((listing) => {
      if (parsedMinPrice != null && (listing.price == null || listing.price < parsedMinPrice)) {
        return false;
      }
      if (parsedMaxPrice != null && (listing.price == null || listing.price > parsedMaxPrice)) {
        return false;
      }
      if (
        parsedMinMileage != null &&
        (listing.mileage == null || listing.mileage < parsedMinMileage)
      ) {
        return false;
      }
      if (
        parsedMaxMileage != null &&
        (listing.mileage == null || listing.mileage > parsedMaxMileage)
      ) {
        return false;
      }
      return true;
    });
  }, [listings, parsedMaxMileage, parsedMaxPrice, parsedMinMileage, parsedMinPrice]);

  const activeResultFilterCount = useMemo(
    () =>
      [parsedMinPrice, parsedMaxPrice, parsedMinMileage, parsedMaxMileage].filter(
        (value) => value != null,
      ).length,
    [parsedMaxMileage, parsedMaxPrice, parsedMinMileage, parsedMinPrice],
  );

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const searchElapsedSec = useMemo(() => {
    if (!running || searchStartedAtMs == null) return 0;
    return Math.max(0, Math.floor((nowMs - searchStartedAtMs) / 1000));
  }, [nowMs, running, searchStartedAtMs]);

  const stopStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
    setSearchStartedAtMs(null);
  }, []);

  const startSearch = useCallback(() => {
    stopStream();
    setErrors([]);
    setListings([]);
    setDealers({});
    setStatus(null);
    const startedAt = Date.now();
    setNowMs(startedAt);
    setSearchStartedAtMs(startedAt);

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
          Local dealership inventory, one search
        </h1>
        <p className="max-w-2xl text-zinc-600 dark:text-zinc-400">
          Enter where you are shopping and what you want. We discover nearby dealerships, fetch
          their sites (with managed anti-bot when configured), and extract listings in real time.
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
              className="inline-flex flex-1 items-center justify-center rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={running || location.trim().length < 2}
              onClick={startSearch}
            >
              {running ? "Searching…" : "Search inventory"}
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
            {running ? (
              <>
                <div className="grid gap-2 pt-2 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-xl border border-emerald-200/70 bg-emerald-50/70 px-3 py-2 dark:border-emerald-900/60 dark:bg-emerald-950/40">
                    <div className="text-[11px] font-medium tracking-wide text-emerald-700 uppercase dark:text-emerald-300">
                      Dealerships found
                    </div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="text-lg font-semibold text-emerald-900 dark:text-emerald-100">
                        {dealerList.length}
                      </span>
                      <span className="text-xs text-emerald-700/80 dark:text-emerald-300/80">
                        / {targetDealerCount} target
                      </span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-amber-200/70 bg-amber-50/70 px-3 py-2 dark:border-amber-900/60 dark:bg-amber-950/40">
                    <div className="text-[11px] font-medium tracking-wide text-amber-700 uppercase dark:text-amber-300">
                      Active now
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className="inline-flex h-2.5 w-2.5 rounded-full bg-amber-500 motion-safe:animate-pulse" />
                      <span className="text-lg font-semibold text-amber-900 dark:text-amber-100">
                        {activeDealerCount}
                      </span>
                    </div>
                  </div>
                  <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/70">
                    <div className="text-[11px] font-medium tracking-wide text-zinc-600 uppercase dark:text-zinc-400">
                      Vehicles loaded
                    </div>
                    <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                      {listings.length}
                    </div>
                  </div>
                  <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/70">
                    <div className="text-[11px] font-medium tracking-wide text-zinc-600 uppercase dark:text-zinc-400">
                      Elapsed
                    </div>
                    <div className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                      {searchElapsedSec}s
                    </div>
                  </div>
                </div>
                <div className="space-y-2 pt-2">
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span>Dealership discovery</span>
                    <span>{dealerList.length}/{targetDealerCount}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-emerald-400 to-teal-400 transition-[width] duration-700 ease-out"
                      style={{ width: `${discoveredDealerPercent}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span>Dealership completion</span>
                    <span>{doneDealerCount}/{targetDealerCount}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-amber-500 via-amber-400 to-yellow-300 transition-[width] duration-700 ease-out"
                      style={{ width: `${completedDealerPercent}%` }}
                    />
                  </div>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {pendingDealerSlots > 0
                    ? `Still looking for ${pendingDealerSlots} more dealerships in range. `
                    : ""}
                  AI parsing is often ~10–40s per page when matches are found; it can run up to
                  about {PARSING_HINT_MAX_SEC}s on a slow or large page.
                </p>
              </>
            ) : null}
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

      <section className="rounded-2xl border border-zinc-200 bg-white px-4 py-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-1">
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
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Narrow the streamed inventory by price and miles without rerunning the search.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">Min price</span>
              <input
                inputMode="numeric"
                placeholder="Any"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">Max price</span>
              <input
                inputMode="numeric"
                placeholder="Any"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">Min miles</span>
              <input
                inputMode="numeric"
                placeholder="Any"
                value={minMileage}
                onChange={(e) => setMinMileage(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              <span className="font-medium text-zinc-700 dark:text-zinc-300">Max miles</span>
              <input
                inputMode="numeric"
                placeholder="Any"
                value={maxMileage}
                onChange={(e) => setMaxMileage(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
          </div>
        </div>
        {activeResultFilterCount > 0 ? (
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => {
                setMinPrice("");
                setMaxPrice("");
                setMinMileage("");
                setMaxMileage("");
              }}
              className="text-xs font-medium text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
            >
              Clear filters
            </button>
          </div>
        ) : null}
      </section>

      <div className="grid gap-8 lg:grid-cols-3">
        <section className="lg:col-span-1">
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
              No vehicles match the current price and miles filters.
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
