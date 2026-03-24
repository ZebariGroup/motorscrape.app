"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { getApiBaseUrl } from "@/lib/config";
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

export function SearchExperience() {
  const [location, setLocation] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [dealers, setDealers] = useState<Record<string, DealershipProgress>>({});
  const [listings, setListings] = useState<AggregatedListing[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const dealerList = useMemo(
    () => Object.values(dealers).sort((a, b) => a.index - b.index),
    [dealers],
  );

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

    const base = getApiBaseUrl();
    const params = new URLSearchParams({
      location: location.trim(),
      make: make.trim(),
      model: model.trim(),
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
        setDealers((prev) => ({ ...prev, [key]: { ...prev[key], ...d } }));
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

    const onDone = () => {
      stopStream();
      setStatus((s) => s ?? "Search finished.");
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
  }, [location, make, model, stopStream]);

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

      <section className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
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
            <input
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              placeholder="e.g. Toyota"
              value={make}
              onChange={(e) => setMake(e.target.value)}
              disabled={running}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">Model</span>
            <input
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              placeholder="e.g. Camry"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={running}
            />
          </label>
          <div className="flex flex-col justify-end gap-2 sm:flex-row">
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
        </div>
        {status ? (
          <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">{status}</p>
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
          <h2 className="mb-3 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Dealerships
          </h2>
          <ul className="space-y-3">
            {dealerList.length === 0 ? (
              <li className="text-sm text-zinc-500">No dealerships yet — run a search.</li>
            ) : (
              dealerList.map((d) => (
                <li
                  key={d.website + d.index}
                  className="rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-950"
                >
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
                            : "rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-100"
                      }
                    >
                      {d.status}
                    </span>
                    {d.fetch_method ? (
                      <span className="text-zinc-500">via {d.fetch_method}</span>
                    ) : null}
                    {d.listings_found != null ? (
                      <span className="text-zinc-500">{d.listings_found} listings</span>
                    ) : null}
                  </div>
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
              ))
            )}
          </ul>
        </section>

        <section className="lg:col-span-2">
          <div className="mb-3 flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Inventory</h2>
            <span className="text-sm text-zinc-500">{listings.length} vehicles</span>
          </div>
          {listings.length === 0 ? (
            <p className="text-sm text-zinc-500">
              Results stream in as each dealership is scraped. Large dealer sites may take longer.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {listings.map((v, idx) => (
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
                      <dt className="font-medium text-zinc-500">VIN</dt>
                      <dd className="truncate">{v.vin ?? "—"}</dd>
                      <dt className="font-medium text-zinc-500">Dealer</dt>
                      <dd className="truncate">{v.dealership}</dd>
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
