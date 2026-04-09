"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { resolveApiUrl } from "@/lib/apiBase";
import { formatMoney } from "@/lib/inventoryFormat";
import type { MarketcheckDetails, MarketcheckDetailsResponse, PremiumReport } from "@/types/inventory";

type AsyncState<T> = {
  loading: boolean;
  data: T | null;
  error: string | null;
};

function parsePositiveNumber(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

async function readErrorMessage(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" && payload.detail.trim() ? payload.detail.trim() : fallback;
  } catch {
    return fallback;
  }
}

export default function VehicleReportPage() {
  const params = useParams<{ vin: string }>();
  const searchParams = useSearchParams();
  const vin = useMemo(() => String(params?.vin ?? "").trim().toUpperCase(), [params]);
  const title = searchParams.get("title")?.trim() || `Vehicle report for ${vin}`;
  const dealer = searchParams.get("dealer")?.trim() || null;
  const price = parsePositiveNumber(searchParams.get("price"));
  const miles = parsePositiveNumber(searchParams.get("miles"));

  const [detailsState, setDetailsState] = useState<AsyncState<MarketcheckDetails>>({
    loading: true,
    data: null,
    error: null,
  });
  const [reportState, setReportState] = useState<AsyncState<PremiumReport>>({
    loading: true,
    data: null,
    error: null,
  });

  useEffect(() => {
    if (!vin) return;
    let cancelled = false;

    const load = async () => {
      setDetailsState({ loading: true, data: null, error: null });
      setReportState({ loading: true, data: null, error: null });

      const detailParams = new URLSearchParams({ vin });
      if (miles != null) {
        detailParams.set("miles", String(miles));
      }

      const [detailsResult, reportResult] = await Promise.allSettled([
        fetch(`/server/vehicles/marketcheck-details?${detailParams.toString()}`, {
          credentials: "include",
        }),
        fetch(`${resolveApiUrl(`/vehicles/premium-report?vin=${encodeURIComponent(vin)}`)}`, {
          credentials: "include",
        }),
      ]);

      if (cancelled) return;

      if (detailsResult.status === "fulfilled") {
        if (detailsResult.value.ok) {
          const payload = (await detailsResult.value.json()) as MarketcheckDetailsResponse;
          if (!cancelled) {
            setDetailsState({ loading: false, data: payload.details, error: null });
          }
        } else {
          const message = await readErrorMessage(detailsResult.value, "MarketCheck details are unavailable for this VIN.");
          if (!cancelled) {
            setDetailsState({ loading: false, data: null, error: message });
          }
        }
      } else if (!cancelled) {
        setDetailsState({ loading: false, data: null, error: "Failed to load MarketCheck details." });
      }

      if (reportResult.status === "fulfilled") {
        if (reportResult.value.ok) {
          const payload = (await reportResult.value.json()) as PremiumReport;
          if (!cancelled) {
            setReportState({ loading: false, data: payload, error: null });
          }
        } else {
          const message = await readErrorMessage(
            reportResult.value,
            "The premium MarketCheck report is unavailable for this VIN.",
          );
          if (!cancelled) {
            setReportState({ loading: false, data: null, error: message });
          }
        }
      } else if (!cancelled) {
        setReportState({ loading: false, data: null, error: "Failed to load the premium report." });
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [miles, vin]);

  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-8 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50 print:bg-white print:px-0 print:py-0">
      <div className="mx-auto max-w-5xl space-y-6 print:max-w-none">
        <header className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 print:rounded-none print:border-none print:shadow-none">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700 dark:text-amber-300">
                Premium MarketCheck Report
              </p>
              <h1 className="mt-2 text-3xl font-bold">{title}</h1>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-sm text-zinc-600 dark:text-zinc-400">
                <span>VIN: {vin}</span>
                {dealer ? <span>Dealer: {dealer}</span> : null}
                {price != null ? <span>Listed price: {formatMoney(price)}</span> : null}
                {miles != null ? <span>Mileage: {miles.toLocaleString()} mi</span> : null}
              </div>
            </div>
            <div className="flex flex-wrap gap-2 print:hidden">
              <button
                type="button"
                onClick={() => window.print()}
                className="rounded-full bg-amber-500 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-600"
              >
                Download PDF / Print
              </button>
              <button
                type="button"
                onClick={() => window.close()}
                className="rounded-full border border-zinc-300 bg-white px-4 py-2 text-sm font-semibold text-zinc-800 transition hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
              >
                Close
              </button>
            </div>
          </div>
        </header>

        <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr] print:grid-cols-1">
          <article className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 print:rounded-none print:border print:border-zinc-300 print:shadow-none">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Decoded vehicle details
            </h2>
            {detailsState.loading ? (
              <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">Loading MarketCheck details…</p>
            ) : detailsState.error ? (
              <p className="mt-4 text-sm text-rose-600 dark:text-rose-400">{detailsState.error}</p>
            ) : detailsState.data ? (
              <>
                <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
                  {detailsState.data.marketcheck_trim ? (
                    <p>Decoded trim: <span className="font-semibold">{detailsState.data.marketcheck_trim}</span></p>
                  ) : null}
                  {detailsState.data.year != null ? (
                    <p>Decoded year: <span className="font-semibold">{detailsState.data.year}</span></p>
                  ) : null}
                  {detailsState.data.make || detailsState.data.model ? (
                    <p>
                      Vehicle:{" "}
                      <span className="font-semibold">
                        {[detailsState.data.make, detailsState.data.model].filter(Boolean).join(" ")}
                      </span>
                    </p>
                  ) : null}
                  {detailsState.data.body_style ? (
                    <p>Body style: <span className="font-semibold">{detailsState.data.body_style}</span></p>
                  ) : null}
                  {detailsState.data.drivetrain ? (
                    <p>Drivetrain: <span className="font-semibold">{detailsState.data.drivetrain}</span></p>
                  ) : null}
                  {detailsState.data.transmission ? (
                    <p>Transmission: <span className="font-semibold">{detailsState.data.transmission}</span></p>
                  ) : null}
                  {detailsState.data.fuel_type ? (
                    <p>Fuel type: <span className="font-semibold">{detailsState.data.fuel_type}</span></p>
                  ) : null}
                  {detailsState.data.engine ? (
                    <p>Engine: <span className="font-semibold">{detailsState.data.engine}</span></p>
                  ) : null}
                </div>

                {detailsState.data.estimated_market_value != null ? (
                  <div className="mt-6 rounded-xl border border-indigo-200 bg-indigo-50/70 p-4 text-sm dark:border-indigo-900 dark:bg-indigo-950/20">
                    <p>
                      Estimated market value:{" "}
                      <span className="font-semibold">{formatMoney(detailsState.data.estimated_market_value)}</span>
                    </p>
                    {price != null ? (
                      <p className="mt-2">
                        Current listing is{" "}
                        <span className="font-semibold">
                          {price < detailsState.data.estimated_market_value
                            ? `${formatMoney(detailsState.data.estimated_market_value - price)} below`
                            : `${formatMoney(price - detailsState.data.estimated_market_value)} above`}
                        </span>{" "}
                        the MarketCheck estimate.
                      </p>
                    ) : null}
                  </div>
                ) : null}

                {(detailsState.data.marketcheck_features?.length ?? 0) > 0 ? (
                  <div className="mt-6">
                    <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Decoded features</h3>
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {detailsState.data.marketcheck_features!.map((feature, index) => (
                        <li
                          key={`${feature}-${index}`}
                          className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950"
                        >
                          {feature}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : null}
          </article>

          <aside className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 print:rounded-none print:border print:border-zinc-300 print:shadow-none">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Report summary
            </h2>
            <ul className="mt-4 space-y-3 text-sm text-zinc-700 dark:text-zinc-300">
              <li>VIN-specific MarketCheck history report</li>
              <li>Printable page for PDF export</li>
              <li>Includes decoded details and pricing context when available</li>
            </ul>
          </aside>
        </section>

        <section className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 print:rounded-none print:border print:border-zinc-300 print:shadow-none">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Historical listings
          </h2>
          {reportState.loading ? (
            <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">Loading premium report…</p>
          ) : reportState.error ? (
            <p className="mt-4 text-sm text-rose-600 dark:text-rose-400">{reportState.error}</p>
          ) : reportState.data ? (
            <>
              <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
                Found <span className="font-semibold text-zinc-900 dark:text-zinc-100">{reportState.data.history.length}</span> historical listing records for this VIN.
              </p>
              <div className="mt-6 space-y-4">
                {reportState.data.history.map((entry, index) => (
                  <article
                    key={`${entry.id}-${index}`}
                    className="rounded-xl border border-zinc-200 bg-zinc-50/80 p-4 dark:border-zinc-700 dark:bg-zinc-950/50"
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">
                          {entry.seller_name || "Unknown dealer"}
                        </h3>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                          {entry.first_seen_at_date ? <span>First seen: {new Date(entry.first_seen_at_date).toLocaleDateString()}</span> : null}
                          {entry.last_seen_at_date ? <span>Last seen: {new Date(entry.last_seen_at_date).toLocaleDateString()}</span> : null}
                          {entry.miles ? <span>Mileage: {entry.miles.toLocaleString()} mi</span> : null}
                          {entry.city && entry.state ? <span>Location: {entry.city}, {entry.state}</span> : null}
                        </div>
                      </div>
                      <div className="text-left sm:text-right">
                        <p className="text-lg font-bold text-emerald-700 dark:text-emerald-400">
                          {entry.price ? formatMoney(entry.price) : "Price not listed"}
                        </p>
                        {entry.inventory_type ? (
                          <p className="text-sm text-zinc-500 dark:text-zinc-400">{entry.inventory_type}</p>
                        ) : null}
                      </div>
                    </div>
                    {entry.vdp_url ? (
                      <a
                        href={entry.vdp_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-block text-sm font-medium text-emerald-700 underline-offset-2 hover:underline dark:text-emerald-400 print:hidden"
                      >
                        Open historical listing
                      </a>
                    ) : null}
                  </article>
                ))}
              </div>
            </>
          ) : null}
        </section>
      </div>
    </main>
  );
}
