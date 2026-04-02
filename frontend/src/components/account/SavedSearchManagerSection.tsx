"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { buildSearchCriteriaQuery } from "@/lib/searchCriteriaUrl";
import type { SavedSearch, SavedSearchListResponse } from "@/types/savedSearch";

type Props = {
  authenticated: boolean;
  tier: string;
};

function isPaidTier(tier: string): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier || "").toLowerCase());
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

function summarize(entry: SavedSearch): string {
  const criteria = entry.criteria;
  return [criteria.location, criteria.make || "Any make", criteria.model || "Any model"].join(" · ");
}

export function SavedSearchManagerSection({ authenticated, tier }: Props) {
  const paid = isPaidTier(tier);
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!authenticated || !paid) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(resolveApiUrl("/saved-searches"), { credentials: "include" });
      const payload = (await response.json().catch(() => ({}))) as SavedSearchListResponse & { detail?: string };
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to load saved searches.");
        return;
      }
      setSavedSearches(Array.isArray(payload.saved_searches) ? payload.saved_searches : []);
    } catch {
      setError("Unable to load saved searches.");
    } finally {
      setLoading(false);
    }
  }, [authenticated, paid]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (savedSearchId: string) => {
    setBusyId(savedSearchId);
    setError(null);
    try {
      const response = await fetch(resolveApiUrl(`/saved-searches/${savedSearchId}`), {
        method: "DELETE",
        credentials: "include",
      });
      const payload = (await response.json().catch(() => ({}))) as { detail?: string };
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to delete the saved search.");
        return;
      }
      setSavedSearches((prev) => prev.filter((entry) => entry.id !== savedSearchId));
    } catch {
      setError("Unable to delete the saved search.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Saved Searches
      </h2>
      {!authenticated ? (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">Log in to manage saved searches.</p>
      ) : !paid ? (
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Saved searches are available on Standard and above.
        </p>
      ) : loading ? (
        <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
      ) : (
        <div className="mt-3 space-y-3">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Keep your favorite local market searches ready, then reopen them on the home page for a fresh scrape.
          </p>
          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
          {savedSearches.length ? (
            savedSearches.map((entry) => (
              <article key={entry.id} className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-1">
                    <p className="font-medium text-zinc-900 dark:text-zinc-50">{entry.name}</p>
                    <p className="text-sm text-zinc-600 dark:text-zinc-400">{summarize(entry)}</p>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">Updated {formatWhen(entry.updated_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      href={`/?${buildSearchCriteriaQuery(entry.criteria)}`}
                      className="rounded-lg border border-emerald-300 px-3 py-1.5 text-sm font-medium text-emerald-800 dark:border-emerald-800 dark:text-emerald-300"
                    >
                      Open search
                    </Link>
                    <button
                      type="button"
                      disabled={busyId === entry.id}
                      onClick={() => void remove(entry.id)}
                      className="rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 dark:border-red-900 dark:text-red-300 disabled:opacity-50"
                    >
                      {busyId === entry.id ? "Deleting..." : "Delete"}
                    </button>
                  </div>
                </div>
              </article>
            ))
          ) : (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">No saved searches yet.</p>
          )}
        </div>
      )}
    </section>
  );
}
