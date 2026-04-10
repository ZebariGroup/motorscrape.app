"use client";

import { useMemo, useState } from "react";

import { SavedSearchQuickPanel } from "@/components/search/SavedSearchQuickPanel";
import type { AccessSummary } from "@/types/access";
import type { AlertCriteria } from "@/types/alerts";
import type { SavedSearchCriteria } from "@/types/savedSearch";

type Props = {
  access: AccessSummary | null;
  criteria: AlertCriteria;
  canSearch: boolean;
  onApplySavedSearch: (criteria: SavedSearchCriteria) => Promise<void>;
};

export function SavesAndAlertsPanel({ access, criteria, canSearch, onApplySavedSearch }: Props) {
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null);
  const expanded = useMemo(() => userExpanded ?? Boolean(access?.authenticated), [access?.authenticated, userExpanded]);

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setUserExpanded((current) => !(current ?? Boolean(access?.authenticated)))}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Saved searches</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {access?.authenticated
              ? "Save this search and rerun it later from any device."
              : "Sign in to save searches and rerun them later."}
          </p>
        </div>
        <span className="text-lg text-zinc-400" aria-hidden>
          {expanded ? "−" : "+"}
        </span>
      </button>
      {expanded ? (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <SavedSearchQuickPanel
            access={access}
            criteria={criteria}
            canSearch={canSearch}
            onApplySavedSearch={onApplySavedSearch}
            embedded
          />
        </div>
      ) : null}
    </div>
  );
}
