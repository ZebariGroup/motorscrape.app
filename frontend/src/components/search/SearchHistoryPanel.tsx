"use client";

import { useCallback, useEffect, useImperativeHandle, forwardRef, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { defaultVehicleCategory } from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { SearchHistoryDetailResponse, SearchHistoryRunRow } from "@/types/searchHistory";

export type SearchHistoryPanelHandle = {
  refresh: () => void;
};

type Props = {
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
};

const INITIAL_LIMIT = 5;
const FULL_LIMIT = 25;

function formatRunWhen(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(d);
  } catch {
    return "";
  }
}

function runTitle(run: SearchHistoryRunRow): string {
  const parts: string[] = [];
  const loc = run.location?.trim();
  if (loc) parts.push(loc);
  const make = run.make?.trim();
  const model = run.model?.trim();
  if (make) parts.push(model ? `${make} ${model}` : make);
  return parts.join(" · ") || "Search";
}

function parseCategory(raw: string): VehicleCategory {
  const v = raw.trim().toLowerCase();
  if (v === "car" || v === "motorcycle" || v === "boat" || v === "other") return v;
  return defaultVehicleCategory();
}

/** Body content for {@link SearchHistoryModal} (no outer dialog chrome). */
export const SearchHistoryPanel = forwardRef<SearchHistoryPanelHandle, Props>(function SearchHistoryPanel(
  { applySavedSearchFromHistory, applyHistoryCriteriaOnly },
  ref,
) {
  const [runs, setRuns] = useState<SearchHistoryRunRow[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadError(null);
    setLoadingList(true);
    try {
      // Fetch one extra to detect whether more exist
      const r = await fetch(resolveApiUrl(`/search/logs?limit=${INITIAL_LIMIT + 1}`), { credentials: "include" });
      if (!r.ok) {
        setRuns([]);
        setHasMore(false);
        setLoadError(r.status === 401 ? "Sign in to view history." : "Could not load history.");
        return;
      }
      const j = (await r.json()) as { runs?: SearchHistoryRunRow[] };
      const all = Array.isArray(j.runs) ? j.runs : [];
      if (all.length > INITIAL_LIMIT) {
        setRuns(all.slice(0, INITIAL_LIMIT));
        setHasMore(true);
      } else {
        setRuns(all);
        setHasMore(false);
      }
    } catch {
      setRuns([]);
      setHasMore(false);
      setLoadError("Could not load history.");
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadMore = async () => {
    setLoadingMore(true);
    setLoadError(null);
    try {
      const r = await fetch(resolveApiUrl(`/search/logs?limit=${FULL_LIMIT}`), { credentials: "include" });
      if (!r.ok) {
        setLoadError("Could not load more.");
        return;
      }
      const j = (await r.json()) as { runs?: SearchHistoryRunRow[] };
      const all = Array.isArray(j.runs) ? j.runs : [];
      setRuns(all);
      setHasMore(false);
    } catch {
      setLoadError("Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  };

  useImperativeHandle(ref, () => ({ refresh }), [refresh]);

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
    return <p className="text-xs text-zinc-500 dark:text-zinc-400">Loading…</p>;
  }

  if (runs.length === 0) {
    return (
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        {loadError ?? "Past searches appear here after you run one."}
      </p>
    );
  }

  return (
    <div>
      {loadError ? <p className="mb-2 text-xs text-amber-700 dark:text-amber-300">{loadError}</p> : null}
      <ul className="space-y-px">
        {runs.map((run) => {
          const busy = busyId === run.correlation_id;
          const saved = Boolean(run.has_saved_results && (run.saved_listings_count ?? 0) > 0);
          const when = formatRunWhen(run.started_at);
          const count = run.result_count > 0 ? `${run.result_count} vehicles` : null;
          const meta = [when, count].filter(Boolean).join(" · ");
          void parseCategory(run.vehicle_category);

          return (
            <li
              key={run.correlation_id}
              className="group rounded-lg px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-900"
            >
              <p className="truncate text-xs font-medium text-zinc-800 dark:text-zinc-200" title={runTitle(run)}>
                {runTitle(run)}
              </p>
              {meta ? (
                <p className="truncate text-[11px] text-zinc-400 dark:text-zinc-500">{meta}</p>
              ) : null}
              <div className="mt-1 flex items-center gap-2">
                {saved ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onViewSaved(run)}
                    className="text-[11px] font-medium text-emerald-600 hover:text-emerald-500 disabled:opacity-50 dark:text-emerald-400"
                  >
                    {busy ? "Loading…" : "Load results"}
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onUseFilters(run)}
                  className={`text-[11px] font-medium disabled:opacity-50 ${saved ? "text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300" : "text-emerald-600 hover:text-emerald-500 dark:text-emerald-400"}`}
                >
                  {busy && !saved ? "Loading…" : "Rerun"}
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {hasMore ? (
        <button
          type="button"
          onClick={() => void loadMore()}
          disabled={loadingMore}
          className="mt-2 w-full rounded-lg px-2 py-1.5 text-[11px] font-medium text-zinc-500 hover:bg-zinc-50 hover:text-zinc-700 disabled:opacity-50 dark:text-zinc-500 dark:hover:bg-zinc-900 dark:hover:text-zinc-300"
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
});
