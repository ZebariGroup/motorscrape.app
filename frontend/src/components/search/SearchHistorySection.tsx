"use client";

import { useCallback, useEffect, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { defaultVehicleCategory, vehicleCategoryLabel } from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { SearchHistoryDetailResponse, SearchHistoryRunRow } from "@/types/searchHistory";

type Props = {
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
};

function formatRunWhen(iso: string | null): string {
  if (!iso) return "Unknown time";
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(d);
  } catch {
    return iso;
  }
}

function summarizeRun(run: SearchHistoryRunRow): string {
  const parts = [run.location?.trim() || "—"];
  const mm = [run.make?.trim(), run.model?.trim()].filter(Boolean).join(" ");
  if (mm) parts.push(mm);
  parts.push(vehicleCategoryLabel(parseCategory(run.vehicle_category)));
  return parts.join(" · ");
}

function parseCategory(raw: string): VehicleCategory {
  const v = raw.trim().toLowerCase();
  if (v === "car" || v === "motorcycle" || v === "boat" || v === "other") return v;
  return defaultVehicleCategory();
}

export function SearchHistorySection({ applySavedSearchFromHistory, applyHistoryCriteriaOnly }: Props) {
  const [runs, setRuns] = useState<SearchHistoryRunRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadError(null);
    setLoadingList(true);
    try {
      const r = await fetch(resolveApiUrl("/search/logs?limit=25"), { credentials: "include" });
      if (!r.ok) {
        setRuns([]);
        setLoadError(r.status === 401 ? "Sign in to see search history." : "Could not load history.");
        return;
      }
      const j = (await r.json()) as { runs?: SearchHistoryRunRow[] };
      setRuns(Array.isArray(j.runs) ? j.runs : []);
    } catch {
      setRuns([]);
      setLoadError("Could not load history.");
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onViewSaved = async (run: SearchHistoryRunRow) => {
    setBusyId(run.correlation_id);
    try {
      const r = await fetch(
        resolveApiUrl(`/search/logs/${encodeURIComponent(run.correlation_id)}?include_events=false`),
        { credentials: "include" },
      );
      if (!r.ok) {
        setLoadError("Could not load saved results.");
        return;
      }
      const j = (await r.json()) as SearchHistoryDetailResponse;
      const raw = Array.isArray(j.listings) ? j.listings : [];
      const listings = raw.filter((x): x is AggregatedListing => x != null && typeof x === "object");
      await applySavedSearchFromHistory(j.run, listings);
    } catch {
      setLoadError("Could not load saved results.");
    } finally {
      setBusyId(null);
    }
  };

  const onUseFilters = async (run: SearchHistoryRunRow) => {
    setBusyId(run.correlation_id);
    try {
      await applyHistoryCriteriaOnly(run);
    } finally {
      setBusyId(null);
    }
  };

  if (loadingList && runs.length === 0 && !loadError) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Recent searches</h2>
        <p className="mt-2 text-sm text-zinc-500">Loading…</p>
      </section>
    );
  }

  if (runs.length === 0) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Recent searches</h2>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          {loadError ??
            "After you run a search, it appears here so you can reopen saved results or reuse the same filters without retyping."}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Recent searches</h2>
        <button
          type="button"
          onClick={() => void refresh()}
          className="self-start text-xs font-medium text-emerald-700 hover:text-emerald-800 dark:text-emerald-400 dark:hover:text-emerald-300"
        >
          Refresh
        </button>
      </div>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Open a past run to see vehicles as of that search. Dealers change inventory often—run a new search when you need
        the latest stock.
      </p>
      {loadError ? <p className="mt-2 text-sm text-amber-800 dark:text-amber-200">{loadError}</p> : null}
      <ul className="mt-4 divide-y divide-zinc-200 dark:divide-zinc-800">
        {runs.map((run) => {
          const busy = busyId === run.correlation_id;
          const saved = Boolean(run.has_saved_results && (run.saved_listings_count ?? 0) > 0);
          return (
            <li key={run.correlation_id} className="flex flex-col gap-2 py-3 first:pt-0 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{summarizeRun(run)}</p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {formatRunWhen(run.started_at)}
                  {run.result_count > 0 ? ` · ${run.result_count} vehicles found` : null}
                  {run.status !== "success" ? ` · ${run.status.replace(/_/g, " ")}` : null}
                </p>
              </div>
              <div className="flex flex-shrink-0 flex-wrap gap-2">
                {saved ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onViewSaved(run)}
                    className="rounded-lg border border-emerald-600 bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {busy ? "Loading…" : "View saved results"}
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onUseFilters(run)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 shadow-sm transition hover:border-zinc-400 disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100"
                >
                  Use these filters
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
