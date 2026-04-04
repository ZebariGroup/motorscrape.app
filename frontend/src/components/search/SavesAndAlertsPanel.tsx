"use client";

import { useState } from "react";

import { EmailAlertPanel } from "@/components/search/EmailAlertPanel";
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
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
        aria-expanded={expanded}
      >
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Saved searches &amp; email alerts</h2>
        <span className="text-lg text-zinc-400" aria-hidden>
          {expanded ? "−" : "+"}
        </span>
      </button>
      {expanded ? (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <EmailAlertPanel access={access} criteria={criteria} canSearch={canSearch} compact embedded />
          <div className="mt-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
            <SavedSearchQuickPanel
              access={access}
              criteria={criteria}
              canSearch={canSearch}
              onApplySavedSearch={onApplySavedSearch}
              embedded
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
