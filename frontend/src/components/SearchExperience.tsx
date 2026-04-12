"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAccessSummary } from "@/hooks/useAccessSummary";
import { SearchTabBar } from "@/components/search/SearchTabBar";
import type { SearchTab } from "@/components/search/SearchTabBar";
import { SearchTabPanel } from "@/components/SearchTabPanel";

/** Maximum UI tabs for paid users (backend limits concurrent searches per tier). */
const MAX_PAID_TABS = 3;

/** Tiers that unlock multi-tab searching. */
const PAID_TIERS = new Set(["standard", "premium", "max_pro", "enterprise", "custom"]);

function makeTabId(): string {
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function makeInitialTab(): SearchTab {
  return { id: makeTabId(), label: "", running: false, listingCount: 0 };
}

export function SearchExperience({
  initialCriteria,
}: {
  initialCriteria?: {
    make?: string;
    model?: string;
    location?: string;
  };
} = {}) {
  const { access, loading: accessLoading, refresh: refreshAccess } = useAccessSummary();

  const isPaidUser = access ? PAID_TIERS.has(access.tier) : false;

  // Cap to backend's concurrent search limit (max 3 in the UI regardless of tier)
  const maxTabs = isPaidUser
    ? Math.min(MAX_PAID_TABS, access?.limits?.max_concurrent_searches ?? MAX_PAID_TABS)
    : 1;

  const [tabs, setTabs] = useState<SearchTab[]>(() => [makeInitialTab()]);
  const [activeTabId, setActiveTabId] = useState<string>(() => tabs[0].id);

  // Sync active tab if it was closed
  useEffect(() => {
    if (!tabs.find((t) => t.id === activeTabId)) {
      setActiveTabId(tabs[tabs.length - 1]?.id ?? "");
    }
  }, [tabs, activeTabId]);

  const addTab = useCallback(() => {
    if (tabs.length >= maxTabs) return;
    const newTab = makeInitialTab();
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, [tabs.length, maxTabs]);

  const closeTab = useCallback(
    (id: string) => {
      setTabs((prev) => {
        if (prev.length <= 1) return prev;
        return prev.filter((t) => t.id !== id);
      });
      setActiveTabId((prev) => {
        if (prev !== id) return prev;
        const remaining = tabs.filter((t) => t.id !== id);
        return remaining[remaining.length - 1]?.id ?? "";
      });
    },
    [tabs],
  );

  const updateTabLabel = useCallback((id: string, label: string) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === id ? { ...t, label } : t)),
    );
  }, []);

  const updateTabStatus = useCallback((id: string, running: boolean, listingCount: number) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === id ? { ...t, running, listingCount } : t)),
    );
  }, []);

  // Stable callback refs per tab to avoid prop-change churn
  const labelCallbacksRef = useRef<Map<string, (label: string) => void>>(new Map());
  const statusCallbacksRef = useRef<Map<string, (running: boolean, listingCount: number) => void>>(new Map());

  const getLabelCallback = useCallback(
    (id: string) => {
      if (!labelCallbacksRef.current.has(id)) {
        labelCallbacksRef.current.set(id, (label: string) => updateTabLabel(id, label));
      }
      return labelCallbacksRef.current.get(id)!;
    },
    [updateTabLabel],
  );

  const getStatusCallback = useCallback(
    (id: string) => {
      if (!statusCallbacksRef.current.has(id)) {
        statusCallbacksRef.current.set(id, (running: boolean, listingCount: number) =>
          updateTabStatus(id, running, listingCount),
        );
      }
      return statusCallbacksRef.current.get(id)!;
    },
    [updateTabStatus],
  );

  // Clean up stale callback refs when tabs are removed
  useEffect(() => {
    const tabIds = new Set(tabs.map((t) => t.id));
    for (const id of labelCallbacksRef.current.keys()) {
      if (!tabIds.has(id)) labelCallbacksRef.current.delete(id);
    }
    for (const id of statusCallbacksRef.current.keys()) {
      if (!tabIds.has(id)) statusCallbacksRef.current.delete(id);
    }
  }, [tabs]);

  // Show tab bar only for paid users
  const showTabBar = isPaidUser && !accessLoading;

  return (
    <div className="flex min-h-screen flex-col">
      {showTabBar && (
        <SearchTabBar
          tabs={tabs}
          activeTabId={activeTabId}
          onTabSelect={setActiveTabId}
          onTabClose={closeTab}
          onAddTab={addTab}
          maxTabs={maxTabs}
          isPaidUser={isPaidUser}
        />
      )}

      {/* Render all tab panels; hide inactive ones via CSS so streams keep running */}
      {tabs.map((tab) => (
        <div
          key={tab.id}
          className={tab.id !== activeTabId ? "hidden" : undefined}
          aria-hidden={tab.id !== activeTabId}
        >
          <SearchTabPanel
            isActive={tab.id === activeTabId}
            access={access}
            onRefreshAccess={refreshAccess}
            initialCriteria={tab.id === tabs[0].id ? initialCriteria : undefined}
            onLabelChange={getLabelCallback(tab.id)}
            onStatusChange={getStatusCallback(tab.id)}
          />
        </div>
      ))}
    </div>
  );
}
