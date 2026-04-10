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
};

function isPaidTier(tier: string | null | undefined): boolean {
  return ["standard", "premium", "max_pro", "enterprise", "custom"].includes((tier ?? "").toLowerCase());
}

function summarizeCriteria(criteria: SavedSearchCriteria): string {
  return [
    criteria.location,
    criteria.make || "Any make",
    criteria.model || "Any model",
    criteria.market_region === "eu" ? `${milesToKm(criteria.radius_miles)} km` : `${criteria.radius_miles} mi`,
  ]
    .filter(Boolean)
    .join(" · ");
}

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return "";
  }
}

type View = "list" | "save";

export function SavedSearchIconButton({ access, criteria, canSearch, onApplySavedSearch }: Props) {
  const paid = isPaidTier(access?.tier);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("list");
  const [name, setName] = useState("");
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const defaultName = useMemo(
    () => [criteria.location, criteria.make, criteria.model].filter(Boolean).join(" · ") || "Saved search",
    [criteria.location, criteria.make, criteria.model],
  );

  const loadList = async () => {
    if (!access?.authenticated || !paid) return;
    setLoadingList(true);
    setError(null);
    try {
      const r = await fetch(resolveApiUrl("/saved-searches"), { credentials: "include" });
      const payload = (await r.json().catch(() => ({}))) as SavedSearchListResponse & { detail?: string };
      if (!r.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Could not load saved searches.");
        return;
      }
      setSavedSearches(Array.isArray(payload.saved_searches) ? payload.saved_searches : []);
    } catch {
      setError("Network error.");
    } finally {
      setLoadingList(false);
    }
  };

  const openModal = async () => {
    setView("list");
    setError(null);
    setSuccessMsg(null);
    setOpen(true);
    await loadList();
  };

  const openSave = () => {
    setName((prev) => prev || defaultName);
    setError(null);
    setSuccessMsg(null);
    setView("save");
  };

  const submitSave = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch(resolveApiUrl("/saved-searches"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: (name || defaultName).trim(), criteria }),
      });
      const payload = (await r.json().catch(() => ({}))) as { detail?: string };
      if (!r.ok) {
        setError(typeof payload.detail === "string" ? payload.detail : "Could not save search.");
        return;
      }
      setName("");
      setSuccessMsg("Search saved.");
      setView("list");
      await loadList();
    } catch {
      setError("Network error.");
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      const r = await fetch(resolveApiUrl(`/saved-searches/${id}`), { method: "DELETE", credentials: "include" });
      if (!r.ok) {
        const payload = (await r.json().catch(() => ({}))) as { detail?: string };
        setError(typeof payload.detail === "string" ? payload.detail : "Could not delete.");
        return;
      }
      setSavedSearches((prev) => prev.filter((s) => s.id !== id));
    } catch {
      setError("Network error.");
    } finally {
      setBusyId(null);
    }
  };

  const inputClass =
    "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

  return (
    <>
      {/* Bookmark icon button */}
      <button
        type="button"
        onClick={() => void openModal()}
        title="Saved searches"
        aria-label="Saved searches"
        className="inline-flex min-h-[2.75rem] min-w-[2.75rem] shrink-0 items-center justify-center rounded-lg border border-zinc-300 text-zinc-700 transition hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900"
      >
        <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
          <path
            d="M5 3h10a1 1 0 0 1 1 1v13l-6-3.5L4 17V4a1 1 0 0 1 1-1z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {/* Modal */}
      {open ? (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-zinc-900/60 p-4 backdrop-blur-sm"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-950">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-100 dark:bg-zinc-800">
                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                    <path
                      d="M5 3h10a1 1 0 0 1 1 1v13l-6-3.5L4 17V4a1 1 0 0 1 1-1z"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="stroke-zinc-600 dark:stroke-zinc-300"
                    />
                  </svg>
                </div>
                <div>
                  <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                    {view === "save" ? "Save current search" : "Saved searches"}
                  </h2>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {view === "save" ? "Name and store your current filters" : "Load or manage stored searches"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                aria-label="Close"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            {/* Body */}
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {!access?.authenticated ? (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    Sign in to save and reuse searches across sessions.
                  </p>
                  <Link
                    href="/login"
                    className="mt-3 inline-block rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                  >
                    Log in
                  </Link>
                </div>
              ) : !paid ? (
                <div className="rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Saved searches require a paid plan</p>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    Standard and above let you bookmark searches for one-click reuse.
                  </p>
                  <Link
                    href="/account"
                    className="mt-3 inline-block rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                  >
                    Upgrade plan
                  </Link>
                </div>
              ) : view === "save" ? (
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      Name
                    </label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder={defaultName}
                      className={`mt-1.5 ${inputClass}`}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void submitSave();
                      }}
                    />
                  </div>
                  <div className="rounded-xl bg-zinc-50 px-4 py-3 text-sm text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
                    {summarizeCriteria(criteria)}
                  </div>
                  {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
                </div>
              ) : (
                <div>
                  {successMsg ? (
                    <p className="mb-3 text-sm text-emerald-600 dark:text-emerald-400">{successMsg}</p>
                  ) : null}
                  {error ? <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
                  {loadingList ? (
                    <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading…</p>
                  ) : savedSearches.length === 0 ? (
                    <p className="text-sm text-zinc-500 dark:text-zinc-400">No saved searches yet.</p>
                  ) : (
                    <ul className="space-y-2">
                      {savedSearches.map((entry) => (
                        <li
                          key={entry.id}
                          className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-800"
                        >
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                            <div className="min-w-0">
                              <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">{entry.name}</p>
                              <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                                {summarizeCriteria(entry.criteria)}
                                {entry.updated_at ? ` · ${formatWhen(entry.updated_at)}` : ""}
                              </p>
                            </div>
                            <div className="flex shrink-0 flex-wrap gap-2">
                              <button
                                type="button"
                                disabled={busyId === entry.id}
                                onClick={() => {
                                  setOpen(false);
                                  void onApplySavedSearch(entry.criteria);
                                }}
                                className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-800 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-900"
                              >
                                Apply
                              </button>
                              <Link
                                href={`/?${buildSearchCriteriaQuery(entry.criteria)}`}
                                className="rounded-lg border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/40"
                                onClick={() => setOpen(false)}
                              >
                                Open
                              </Link>
                              <button
                                type="button"
                                disabled={busyId === entry.id}
                                onClick={() => void remove(entry.id)}
                                className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/30"
                              >
                                {busyId === entry.id ? "…" : "Delete"}
                              </button>
                            </div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between border-t border-zinc-200 px-5 py-3 dark:border-zinc-800">
              {view === "save" ? (
                <>
                  <button
                    type="button"
                    onClick={() => setView("list")}
                    className="text-sm text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
                  >
                    ← Back
                  </button>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setOpen(false)}
                      className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => void submitSave()}
                      disabled={submitting}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      {submitting ? "Saving…" : "Save search"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <span />
                  {paid && canSearch ? (
                    <button
                      type="button"
                      onClick={openSave}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
                    >
                      + Save current search
                    </button>
                  ) : null}
                </>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
