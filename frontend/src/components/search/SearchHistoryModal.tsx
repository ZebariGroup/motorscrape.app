"use client";

import { useEffect, useRef } from "react";

import type { AggregatedListing } from "@/lib/inventoryFormat";
import type { SearchHistoryRunRow } from "@/types/searchHistory";

import { SearchHistoryPanel, type SearchHistoryPanelHandle } from "./SearchHistoryPanel";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applySavedSearchFromHistory: (run: SearchHistoryRunRow, listings: AggregatedListing[]) => Promise<void>;
  applyHistoryCriteriaOnly: (run: SearchHistoryRunRow) => Promise<void>;
};

export function SearchHistoryModal({
  open,
  onOpenChange,
  applySavedSearchFromHistory,
  applyHistoryCriteriaOnly,
}: Props) {
  const panelRef = useRef<SearchHistoryPanelHandle>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-zinc-900/60 p-4"
      role="presentation"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="flex max-h-[min(90vh,640px)] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-950"
        role="dialog"
        aria-modal="true"
        aria-labelledby="search-history-heading"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h2 id="search-history-heading" className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
            Recent searches
          </h2>
          <div className="flex items-center gap-1 sm:gap-2">
            <button
              type="button"
              onClick={() => panelRef.current?.refresh()}
              className="rounded-lg px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800 dark:text-emerald-400 dark:hover:bg-emerald-950/50 dark:hover:text-emerald-300"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
              aria-label="Close"
            >
              <span className="text-xl leading-none" aria-hidden>
                ×
              </span>
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <SearchHistoryPanel
            ref={panelRef}
            applySavedSearchFromHistory={applySavedSearchFromHistory}
            applyHistoryCriteriaOnly={applyHistoryCriteriaOnly}
          />
        </div>
      </div>
    </div>
  );
}
