"use client";

import { useMemo, useState } from "react";

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
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Saved searches &amp; email alerts</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {access?.authenticated
              ? "Save this search, rerun it later, or get emailed when inventory changes."
              : "Sign in to save this search and get inventory alerts by email."}
          </p>
        </div>
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
