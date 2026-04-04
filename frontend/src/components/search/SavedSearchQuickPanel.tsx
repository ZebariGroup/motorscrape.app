"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { milesToKm } from "@/lib/marketRegion";
import { buildSearchCriteriaQuery } from "@/lib/searchCriteriaUrl";
import type { AccessSummary } from "@/types/access";
import type { SavedSearch, SavedSearchCriteria, SavedSearchListResponse } from "@/types/savedSearch";

type Props = {
  access: AccessSummary | null;
  criteria: SavedSearchCriteria;
  canSearch: boolean;
  onApplySavedSearch: (criteria: SavedSearchCriteria) => Promise<void>;
  /** Omit top margin when nested (e.g. inside SavesAndAlertsPanel). */
  embedded?: boolean;
};

function isPaidTier(tier: string | null | undefined): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier ?? "").toLowerCase());
}

function formatWhen(iso: string | null): string {
  if (!iso) return "just now";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "just now";
  return date.toLocaleString();
}

function summarizeCriteria(criteria: SavedSearchCriteria): string {
  return [
    criteria.location,
    criteria.make || "Any make",
    criteria.model || "Any model",
    criteria.market_region === "eu" ? `${milesToKm(criteria.radius_miles)} km` : `${criteria.radius_miles} mi`,
  ].join(" · ");
}

export function SavedSearchQuickPanel({ access, criteria, canSearch, onApplySavedSearch, embedded = false }: Props) {
  const paid = isPaidTier(access?.tier);
  const [saveOpen, setSaveOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [name, setName] = useState("");
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const defaultName = useMemo(() => {
    return [criteria.location, criteria.make, criteria.model].filter(Boolean).join(" · ") || "Saved search";
  }, [criteria.location, criteria.make, criteria.model]);

  const loadSavedSearches = async () => {
    if (!access?.authenticated || !paid) return;
    setLoadingList(true);
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
      setLoadingList(false);
    }
  };

  const openSave = () => {
    if (!access?.authenticated || !paid || !canSearch) return;
    setName((prev) => prev || defaultName);
    setMessage(null);
    setError(null);
    setSaveOpen(true);
  };

  const openManage = async () => {
    if (!access?.authenticated || !paid) return;
    setManageOpen(true);
    await loadSavedSearches();
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(resolveApiUrl("/saved-searches"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: (name || defaultName).trim(),
          criteria,
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as { detail?: string };
      if (!response.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Unable to save the search.");
        return;
      }
      setSaveOpen(false);
      setMessage("Saved search created.");
      setName("");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const removeSavedSearch = async (savedSearchId: string) => {
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
    <>
      <div className={`flex flex-col gap-2${embedded ? "" : " mt-3"}`}>
        {paid ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => void openManage()}
              className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-800 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900"
            >
              Saved searches
            </button>
            <button
              type="button"
              onClick={openSave}
              disabled={!canSearch || !access?.authenticated}
              className="rounded-lg border border-emerald-300 px-4 py-2 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/50"
            >
              Save this search
            </button>
          </div>
        ) : (
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/70 dark:text-zinc-400">
            <span>Saved searches are included with Standard and above. </span>
            {access?.authenticated ? (
              <Link href="/account" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                Upgrade your plan
              </Link>
            ) : (
              <Link href="/signup" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                Create an account to upgrade
              </Link>
            )}
          </div>
        )}
        {!canSearch ? (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Pick a valid search first, then save it for one-click reuse later.
          </p>
        ) : null}
        {message ? <p className="text-sm text-emerald-700 dark:text-emerald-400">{message}</p> : null}
        {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      </div>

      {saveOpen ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-5 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Save current search</h3>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Store these filters so you can reopen them from the search page or your account later.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSaveOpen(false)}
                className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <span className="text-2xl leading-none">×</span>
              </button>
            </div>
            <label className="mt-4 flex flex-col gap-1 text-sm">
              <span className="font-medium text-zinc-800 dark:text-zinc-200">Saved search name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
              />
            </label>
            <div className="mt-4 rounded-xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
              {summarizeCriteria(criteria)}
            </div>
            <div className="mt-4 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setSaveOpen(false)}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold text-zinc-800 dark:border-zinc-700 dark:text-zinc-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={submitting}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Saving..." : "Save search"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {manageOpen ? (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-zinc-900/60 p-4">
          <div className="flex max-h-[min(90vh,720px)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex items-start justify-between gap-4 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <div>
                <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Saved searches</h3>
                <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                  Reuse a saved criteria set, or open it on the home page to run a fresh scrape.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setManageOpen(false)}
                className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <span className="text-2xl leading-none">×</span>
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {loadingList ? <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p> : null}
              {!loadingList && savedSearches.length === 0 ? (
                <p className="text-sm text-zinc-600 dark:text-zinc-400">No saved searches yet.</p>
              ) : null}
              <div className="space-y-3">
                {savedSearches.map((entry) => (
                  <article key={entry.id} className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="space-y-1">
                        <p className="font-medium text-zinc-900 dark:text-zinc-50">{entry.name}</p>
                        <p className="text-sm text-zinc-600 dark:text-zinc-400">{summarizeCriteria(entry.criteria)}</p>
                        <p className="text-xs text-zinc-500 dark:text-zinc-400">Updated {formatWhen(entry.updated_at)}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={busyId === entry.id}
                          onClick={() => {
                            setManageOpen(false);
                            void onApplySavedSearch(entry.criteria);
                          }}
                          className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-800 dark:border-zinc-700 dark:text-zinc-100 disabled:opacity-50"
                        >
                          Use filters
                        </button>
                        <Link
                          href={`/?${buildSearchCriteriaQuery(entry.criteria)}`}
                          className="rounded-lg border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-800 dark:border-emerald-800 dark:text-emerald-300"
                        >
                          Open search
                        </Link>
                        <button
                          type="button"
                          disabled={busyId === entry.id}
                          onClick={() => void removeSavedSearch(entry.id)}
                          className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 dark:border-red-900 dark:text-red-300 disabled:opacity-50"
                        >
                          {busyId === entry.id ? "Deleting..." : "Delete"}
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
