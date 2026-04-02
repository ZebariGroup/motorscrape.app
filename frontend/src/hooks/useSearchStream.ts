"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { clampNumber, clampPercent, dealerSiteKey } from "@/lib/inventoryFormat";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import {
  DEFAULT_RADIUS_MILES_US,
  MARKET_REGION_STORAGE_KEY,
  parseMarketRegion,
  type MarketRegion,
} from "@/lib/marketRegion";
import { categoryUsesCatalog, defaultVehicleCategory, getMakesForCategory, getModelsForMake } from "@/lib/vehicleCatalog";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import type { DealershipProgress, VehicleListing } from "@/types/inventory";
import type { SavedSearchCriteria } from "@/types/savedSearch";
import type { SearchHistoryRunRow } from "@/types/searchHistory";

export type SearchHistoryView = {
  asOfIso: string;
  savedCount: number;
  correlationId: string;
};

type SearchLogRun = SearchHistoryRunRow & {
  dealer_discovery_count?: number | null;
  dealer_deduped_count?: number | null;
  error_message?: string | null;
};

const TERMINAL_SEARCH_LOG_STATUSES = new Set([
  "success",
  "partial_failure",
  "failed",
  "quota_blocked",
  "canceled",
]);

/**
 * Persisted run rows can lag the SSE close by a few seconds in production, so
 * keep checking after the browser reports a stream error before surfacing a
 * generic failure banner to the user.
 */
const STREAM_RECOVERY_POLL_SCHEDULE_MS = [0, 300, 300, 500, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000] as const;

function appendUniqueError(list: string[], message: string): string[] {
  return list.includes(message) ? list : [...list, message];
}

function isTerminalDealerStatus(status: DealershipProgress["status"] | undefined): boolean {
  return status === "done" || status === "error";
}

function buildRecoveredSearchStatus(run: SearchLogRun): string {
  if (run.status === "canceled") {
    return "Search canceled.";
  }
  if (run.status === "quota_blocked") {
    return run.error_message?.trim() || "Search blocked by quota.";
  }
  if (run.status === "failed") {
    return run.error_message?.trim() || "Search failed.";
  }
  const dealerPart =
    run.dealer_discovery_count != null && run.dealer_deduped_count != null
      ? `${run.dealer_deduped_count} dealerships searched`
      : run.requested_max_dealerships != null
        ? `${run.requested_max_dealerships} dealerships searched`
        : null;
  return dealerPart ? `Search finished · ${dealerPart}` : "Search finished.";
}

function parseVehicleCategory(raw: string | undefined): VehicleCategory {
  const v = (raw ?? "").trim().toLowerCase();
  if (v === "car" || v === "motorcycle" || v === "boat" || v === "other") return v;
  return defaultVehicleCategory();
}

/** Client-side result ordering (applied after filters). */
export type ListingSortOrder =
  | "price_asc"
  | "price_desc"
  | "mileage_asc"
  | "year_desc"
  | "days_on_lot_asc"
  | "days_on_lot_desc";

function buildClientSearchId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `srch-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
  }
  return `srch-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function listingSortTieBreak(a: AggregatedListing, b: AggregatedListing) {
  const ka = `${a.vehicle_identifier ?? ""}|${a.vin ?? ""}|${a.listing_url ?? ""}|${a.raw_title ?? ""}|${a.dealership ?? ""}`;
  const kb = `${b.vehicle_identifier ?? ""}|${b.vin ?? ""}|${b.listing_url ?? ""}|${b.raw_title ?? ""}|${b.dealership ?? ""}`;
  return ka.localeCompare(kb);
}

function sortAggregatedListings(list: AggregatedListing[], order: ListingSortOrder): AggregatedListing[] {
  const out = [...list];
  out.sort((a, b) => {
    switch (order) {
      case "price_asc": {
        const av = a.price != null && !Number.isNaN(a.price) ? a.price : Number.POSITIVE_INFINITY;
        const bv = b.price != null && !Number.isNaN(b.price) ? b.price : Number.POSITIVE_INFINITY;
        if (av !== bv) return av - bv;
        return listingSortTieBreak(a, b);
      }
      case "price_desc": {
        const av = a.price != null && !Number.isNaN(a.price) ? a.price : Number.NEGATIVE_INFINITY;
        const bv = b.price != null && !Number.isNaN(b.price) ? b.price : Number.NEGATIVE_INFINITY;
        if (av !== bv) return bv - av;
        return listingSortTieBreak(a, b);
      }
      case "mileage_asc": {
        const av =
          a.usage_value != null && !Number.isNaN(a.usage_value)
            ? a.usage_value
            : a.mileage != null && !Number.isNaN(a.mileage)
              ? a.mileage
              : Number.POSITIVE_INFINITY;
        const bv =
          b.usage_value != null && !Number.isNaN(b.usage_value)
            ? b.usage_value
            : b.mileage != null && !Number.isNaN(b.mileage)
              ? b.mileage
              : Number.POSITIVE_INFINITY;
        if (av !== bv) return av - bv;
        return listingSortTieBreak(a, b);
      }
      case "year_desc": {
        const av = a.year != null && !Number.isNaN(a.year) ? a.year : Number.NEGATIVE_INFINITY;
        const bv = b.year != null && !Number.isNaN(b.year) ? b.year : Number.NEGATIVE_INFINITY;
        if (av !== bv) return bv - av;
        return listingSortTieBreak(a, b);
      }
      case "days_on_lot_asc": {
        const av =
          a.days_on_lot != null && !Number.isNaN(a.days_on_lot) ? a.days_on_lot : Number.POSITIVE_INFINITY;
        const bv =
          b.days_on_lot != null && !Number.isNaN(b.days_on_lot) ? b.days_on_lot : Number.POSITIVE_INFINITY;
        if (av !== bv) return av - bv;
        return listingSortTieBreak(a, b);
      }
      case "days_on_lot_desc": {
        const av =
          a.days_on_lot != null && !Number.isNaN(a.days_on_lot) ? a.days_on_lot : Number.NEGATIVE_INFINITY;
        const bv =
          b.days_on_lot != null && !Number.isNaN(b.days_on_lot) ? b.days_on_lot : Number.NEGATIVE_INFINITY;
        if (av !== bv) return bv - av;
        return listingSortTieBreak(a, b);
      }
      default:
        return listingSortTieBreak(a, b);
    }
  });
  return out;
}

/** Keep global sort order, but move all vehicles from the pinned dealership to the top. */
function listingsWithPinnedDealerFirst(list: AggregatedListing[], pinnedSite: string | null): AggregatedListing[] {
  const key = pinnedSite ? dealerSiteKey(pinnedSite) : "";
  if (!key) return list;
  const fromPinned: AggregatedListing[] = [];
  const rest: AggregatedListing[] = [];
  for (const item of list) {
    if (dealerSiteKey(item.dealership_website) === key) {
      fromPinned.push(item);
    } else {
      rest.push(item);
    }
  }
  return [...fromPinned, ...rest];
}

export type UseSearchStreamOptions = {
  /** Called after the terminal `done` SSE event (e.g. refresh usage counters). */
  onStreamFinished?: () => void;
};

function scheduleNextPaint(callback: FrameRequestCallback): number {
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(callback);
  }
  return window.setTimeout(() => callback(Date.now()), 16);
}

function cancelScheduledPaint(handle: number | null) {
  if (handle == null) return;
  if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(handle);
    return;
  }
  window.clearTimeout(handle);
}

export function useSearchStream(options?: UseSearchStreamOptions) {
  const onFinishedRef = useRef<(() => void) | undefined>(undefined);
  useEffect(() => {
    onFinishedRef.current = options?.onStreamFinished;
  }, [options?.onStreamFinished]);
  const [location, setLocation] = useState("");
  const [vehicleCategory, setVehicleCategory] = useState<VehicleCategory>(() => defaultVehicleCategory());
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [vehicleCondition, setVehicleCondition] = useState("all");
  const [radiusMiles, setRadiusMiles] = useState(String(DEFAULT_RADIUS_MILES_US));
  const [marketRegion, setMarketRegion] = useState<MarketRegion>(() => {
    if (typeof window === "undefined") return "us";
    return parseMarketRegion(localStorage.getItem(MARKET_REGION_STORAGE_KEY));
  });
  const [inventoryScope, setInventoryScope] = useState("all");
  const [maxDealerships, setMaxDealerships] = useState("8");
  const [status, setStatus] = useState<string | null>(null);
  const [dealers, setDealers] = useState<Record<string, DealershipProgress>>({});
  const [listings, setListings] = useState<AggregatedListing[]>([]);
  const [priceFilterMin, setPriceFilterMin] = useState<number | null>(null);
  const [priceFilterMax, setPriceFilterMax] = useState<number | null>(null);
  const [yearFilter, setYearFilter] = useState("");
  const [bodyStyleFilter, setBodyStyleFilter] = useState("");
  const [colorFilter, setColorFilter] = useState("");
  const [filtersExpanded, setFiltersExpanded] = useState(true);
  const [sortOrder, setSortOrder] = useState<ListingSortOrder>("year_desc");
  const [pinnedDealerWebsite, setPinnedDealerWebsite] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [historyView, setHistoryView] = useState<SearchHistoryView | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const esRef = useRef<EventSource | null>(null);
  const streamSessionRef = useRef(0);
  /** Set when the terminal `done` SSE event is handled — avoids false errors from EventSource close/reconnect. */
  const streamDoneReceivedRef = useRef(false);
  const correlationIdRef = useRef<string | null>(null);
  const pendingListingsRef = useRef<AggregatedListing[]>([]);
  const listingFlushHandleRef = useRef<number | null>(null);
  const sawFirstVehicleBatchRef = useRef(false);
  const streamErrorTimerRef = useRef<number | null>(null);
  const dealerStatusesRef = useRef(new Map<string, DealershipProgress["status"]>());
  const expectedDealerTotalRef = useRef<number | null>(null);
  const streamErrorGraceMs = 2000;

  const dealerList = useMemo(
    () => Object.values(dealers).sort((a, b) => a.index - b.index),
    [dealers],
  );

  const doneDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "done" || d.status === "error").length,
    [dealerList],
  );

  const queuedDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "queued").length,
    [dealerList],
  );

  const activeDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "scraping" || d.status === "parsing").length,
    [dealerList],
  );

  const activeDealerSummary = useMemo(() => {
    const active = dealerList.filter((d) => d.status === "scraping" || d.status === "parsing");
    if (active.length === 0) {
      if (queuedDealerCount > 0) {
        return `${queuedDealerCount} dealer${queuedDealerCount === 1 ? "" : "s"} queued`;
      }
      return null;
    }
    const names = active.slice(0, 2).map((dealer) => dealer.name);
    const label = names.join(" and ");
    const remaining = active.length - names.length;
    return remaining > 0
      ? `${label} +${remaining} more active`
      : `${label} active now`;
  }, [dealerList, queuedDealerCount]);

  const listingCountsByDealerKey = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const listing of listings) {
      const key = dealerSiteKey(listing.dealership_website);
      if (!key) continue;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [listings]);

  const targetDealerCount = useMemo(() => {
    const parsed = Number.parseInt(maxDealerships, 10);
    return Number.isFinite(parsed) ? parsed : 8;
  }, [maxDealerships]);

  const usesCatalog = useMemo(() => categoryUsesCatalog(vehicleCategory), [vehicleCategory]);
  const modelOptions = useMemo(
    () => getModelsForMake(vehicleCategory, make, marketRegion),
    [make, vehicleCategory, marketRegion],
  );

  useEffect(() => {
    try {
      localStorage.setItem(MARKET_REGION_STORAGE_KEY, marketRegion);
    } catch {
      /* ignore */
    }
  }, [marketRegion]);

  useEffect(() => {
    const makes = getMakesForCategory(vehicleCategory, marketRegion);
    if (make && !makes.includes(make)) {
      setMake("");
      setModel("");
      return;
    }
    if (!make) return;
    const models = getModelsForMake(vehicleCategory, make, marketRegion);
    setModel((prev) => {
      const parts = prev.split(",").map((s) => s.trim()).filter(Boolean);
      const filtered = parts.filter((p) => models.includes(p));
      return filtered.join(",");
    });
  }, [marketRegion, vehicleCategory, make]);

  const discoveredDealerPercent = useMemo(
    () => clampPercent((dealerList.length / Math.max(targetDealerCount, 1)) * 100),
    [dealerList.length, targetDealerCount],
  );

  const completedDealerPercent = useMemo(
    () => clampPercent((doneDealerCount / Math.max(targetDealerCount, 1)) * 100),
    [doneDealerCount, targetDealerCount],
  );

  const pendingDealerSlots = useMemo(() => {
    if (!running) return 0;
    return Math.max(0, targetDealerCount - dealerList.length);
  }, [dealerList.length, running, targetDealerCount]);

  const loadingDealerCards = useMemo(
    () =>
      Array.from({
        length: Math.min(
          Math.max(pendingDealerSlots, dealerList.length === 0 && running ? 3 : 0),
          4,
        ),
      }),
    [dealerList.length, pendingDealerSlots, running],
  );

  const loadingInventoryCards = useMemo(
    () => Array.from({ length: listings.length === 0 && running ? 4 : 0 }),
    [listings.length, running],
  );

  const priceBounds = useMemo(() => {
    const values = listings
      .map((listing) => listing.price)
      .filter((value): value is number => value != null && !Number.isNaN(value));
    if (values.length === 0) return null;
    return {
      min: Math.min(...values),
      max: Math.max(...values),
    };
  }, [listings]);

  const yearOptions = useMemo(
    () =>
      Array.from(
        new Set(listings.map((listing) => listing.year).filter((year): year is number => year != null)),
      ).sort((a, b) => b - a),
    [listings],
  );

  const bodyStyleOptions = useMemo(
    () =>
      Array.from(
        new Set(
          listings
            .map((listing) => listing.body_style?.trim())
            .filter((bodyStyle): bodyStyle is string => Boolean(bodyStyle)),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [listings],
  );

  const colorOptions = useMemo(
    () =>
      Array.from(
        new Set(
          listings
            .map((listing) => listing.exterior_color?.trim())
            .filter((color): color is string => Boolean(color)),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [listings],
  );

  const isPriceFilterActive = useMemo(() => {
    if (!priceBounds) return false;
    if (priceFilterMin != null && priceFilterMin > priceBounds.min) return true;
    if (priceFilterMax != null && priceFilterMax < priceBounds.max) return true;
    return false;
  }, [priceBounds, priceFilterMin, priceFilterMax]);

  const effectivePriceMin = useMemo(() => {
    if (!priceBounds || !isPriceFilterActive) return null;
    return clampNumber(
      priceFilterMin ?? priceBounds.min,
      priceBounds.min,
      priceFilterMax ?? priceBounds.max,
    );
  }, [isPriceFilterActive, priceBounds, priceFilterMax, priceFilterMin]);

  const effectivePriceMax = useMemo(() => {
    if (!priceBounds || !isPriceFilterActive) return null;
    return clampNumber(
      priceFilterMax ?? priceBounds.max,
      effectivePriceMin ?? priceBounds.min,
      priceBounds.max,
    );
  }, [effectivePriceMin, isPriceFilterActive, priceBounds, priceFilterMax]);

  const filteredListings = useMemo(() => {
    const filtered = listings.filter((listing) => {
      if (yearFilter && String(listing.year ?? "") !== yearFilter) {
        return false;
      }
      if (bodyStyleFilter && listing.body_style !== bodyStyleFilter) {
        return false;
      }
      if (colorFilter && listing.exterior_color !== colorFilter) {
        return false;
      }
      if (
        isPriceFilterActive &&
        effectivePriceMin != null &&
        (listing.price == null || listing.price < effectivePriceMin)
      ) {
        return false;
      }
      if (
        isPriceFilterActive &&
        effectivePriceMax != null &&
        (listing.price == null || listing.price > effectivePriceMax)
      ) {
        return false;
      }
      return true;
    });
    return listingsWithPinnedDealerFirst(sortAggregatedListings(filtered, sortOrder), pinnedDealerWebsite);
  }, [
    bodyStyleFilter,
    colorFilter,
    isPriceFilterActive,
    effectivePriceMax,
    effectivePriceMin,
    listings,
    pinnedDealerWebsite,
    sortOrder,
    yearFilter,
  ]);

  const togglePinnedDealer = useCallback((website: string) => {
    if (!website.trim()) return;
    setPinnedDealerWebsite((prev) => (dealerSiteKey(prev ?? "") === dealerSiteKey(website) ? null : website));
  }, []);

  const activeResultFilterCount = useMemo(() => {
    let count = 0;
    if (
      isPriceFilterActive &&
      priceBounds &&
      effectivePriceMin != null &&
      effectivePriceMax != null &&
      (effectivePriceMin > priceBounds.min || effectivePriceMax < priceBounds.max)
    ) {
      count += 1;
    }
    if (yearFilter) {
      count += 1;
    }
    if (bodyStyleFilter) {
      count += 1;
    }
    if (colorFilter) {
      count += 1;
    }
    return count;
  }, [
    bodyStyleFilter,
    colorFilter,
    effectivePriceMax,
    effectivePriceMin,
    isPriceFilterActive,
    priceBounds,
    yearFilter,
  ]);

  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      // Collapse filters on small viewports on first mount (UX preference).
      setFiltersExpanded(false);
    }
  }, []);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const flushPendingListings = useCallback(() => {
    cancelScheduledPaint(listingFlushHandleRef.current);
    listingFlushHandleRef.current = null;
    if (pendingListingsRef.current.length === 0) return;
    const pending = pendingListingsRef.current;
    pendingListingsRef.current = [];
    setListings((prev) => [...prev, ...pending]);
  }, []);

  const scheduleListingFlush = useCallback(() => {
    if (listingFlushHandleRef.current != null) return;
    listingFlushHandleRef.current = scheduleNextPaint(() => {
      listingFlushHandleRef.current = null;
      flushPendingListings();
    });
  }, [flushPendingListings]);

  useEffect(() => {
    return () => {
      pendingListingsRef.current = [];
      if (streamErrorTimerRef.current != null) {
        window.clearTimeout(streamErrorTimerRef.current);
        streamErrorTimerRef.current = null;
      }
      cancelScheduledPaint(listingFlushHandleRef.current);
      listingFlushHandleRef.current = null;
    };
  }, []);

  const closeStream = useCallback(() => {
    if (streamErrorTimerRef.current != null) {
      window.clearTimeout(streamErrorTimerRef.current);
      streamErrorTimerRef.current = null;
    }
    flushPendingListings();
    streamSessionRef.current += 1;
    esRef.current?.close();
    esRef.current = null;
    correlationIdRef.current = null;
    dealerStatusesRef.current.clear();
    expectedDealerTotalRef.current = null;
    setRunning(false);
    setReconnecting(false);
  }, [flushPendingListings]);

  const recoverCompletedStream = useCallback(
    async (correlationId: string, isStaleSession: () => boolean): Promise<boolean> => {
      const logsUrl = resolveApiUrl(`/search/logs/${encodeURIComponent(correlationId)}?include_events=false`);

      for (const delayMs of STREAM_RECOVERY_POLL_SCHEDULE_MS) {
        if (isStaleSession()) return false;
        if (delayMs > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, delayMs));
        }
        if (isStaleSession()) return false;
        try {
          const response = await fetch(logsUrl, {
            credentials: "include",
          });
          const payload = (await response.json()) as { run?: SearchLogRun };
          const run = payload.run;
          if (isStaleSession()) return false;

          if (response.ok && run && TERMINAL_SEARCH_LOG_STATUSES.has(run.status)) {
            setStatus(buildRecoveredSearchStatus(run));
            if (run.error_message?.trim()) {
              setErrors((e) => appendUniqueError(e, run.error_message!.trim()));
            }
            closeStream();
            onFinishedRef.current?.();
            return true;
          }

          if (
            response.ok &&
            run &&
            run.status !== "running" &&
            !TERMINAL_SEARCH_LOG_STATUSES.has(run.status)
          ) {
            return false;
          }
        } catch {
          /* retry until the poll schedule is exhausted */
        }
      }
      return false;
    },
    [closeStream],
  );

  const stopStream = useCallback(async () => {
    flushPendingListings();
    if (streamErrorTimerRef.current != null) {
      window.clearTimeout(streamErrorTimerRef.current);
      streamErrorTimerRef.current = null;
    }
    const es = esRef.current;
    const correlationId = correlationIdRef.current;
    streamSessionRef.current += 1;
    setRunning(false);
    setReconnecting(false);
    dealerStatusesRef.current.clear();
    expectedDealerTotalRef.current = null;
    if (correlationId) {
      try {
        await fetch(resolveApiUrl(`/search/stop/${correlationId}`), {
          method: "POST",
          credentials: "include",
        });
      } catch {
        /* best-effort stop request */
      }
    }
    if (esRef.current === es) {
      es?.close();
      esRef.current = null;
    }
    if (correlationIdRef.current === correlationId) {
      correlationIdRef.current = null;
    }
  }, [flushPendingListings]);

  const applySavedSearchCriteria = useCallback(
    async (criteria: SavedSearchCriteria) => {
      await stopStream();
      pendingListingsRef.current = [];
      cancelScheduledPaint(listingFlushHandleRef.current);
      listingFlushHandleRef.current = null;
      sawFirstVehicleBatchRef.current = false;
      setErrors([]);
      setDealers({});
      setPinnedDealerWebsite(null);
      setStatus(null);
      setListings([]);
      setHistoryView(null);
      setPriceFilterMin(null);
      setPriceFilterMax(null);
      setYearFilter("");
      setBodyStyleFilter("");
      setColorFilter("");
      setLocation(criteria.location.trim());
      setVehicleCategory(parseVehicleCategory(criteria.vehicle_category));
      setMake(criteria.make.trim());
      setModel(criteria.model.trim());
      setVehicleCondition(criteria.vehicle_condition);
      setRadiusMiles(String(criteria.radius_miles || 25));
      setInventoryScope(criteria.inventory_scope || "all");
      if (criteria.max_dealerships != null) {
        setMaxDealerships(String(criteria.max_dealerships));
      }
      if (criteria.market_region) {
        setMarketRegion(criteria.market_region);
      }
    },
    [stopStream],
  );

  const applyFormFromHistoryRun = useCallback((run: SearchHistoryRunRow) => {
    setLocation(run.location ?? "");
    setVehicleCategory(parseVehicleCategory(run.vehicle_category));
    setMake((run.make ?? "").trim());
    setModel((run.model ?? "").trim());
    setVehicleCondition(run.vehicle_condition || "all");
    setRadiusMiles(String(run.radius_miles ?? 25));
    setInventoryScope(run.inventory_scope || "all");
    if (run.requested_max_dealerships != null) {
      setMaxDealerships(String(run.requested_max_dealerships));
    }
  }, []);

  const applySavedSearchFromHistory = useCallback(
    async (run: SearchHistoryRunRow, listings: AggregatedListing[]) => {
      await stopStream();
      pendingListingsRef.current = [];
      cancelScheduledPaint(listingFlushHandleRef.current);
      listingFlushHandleRef.current = null;
      sawFirstVehicleBatchRef.current = false;
      setErrors([]);
      setDealers({});
      setPinnedDealerWebsite(null);
      setStatus(null);
      setPriceFilterMin(null);
      setPriceFilterMax(null);
      setYearFilter("");
      setBodyStyleFilter("");
      setColorFilter("");
      applyFormFromHistoryRun(run);
      setListings(listings);
      const asOf = run.started_at || run.completed_at || new Date().toISOString();
      setHistoryView({
        asOfIso: asOf,
        savedCount: listings.length,
        correlationId: run.correlation_id,
      });
    },
    [applyFormFromHistoryRun, stopStream],
  );

  const applyHistoryCriteriaOnly = useCallback(
    async (run: SearchHistoryRunRow) => {
      await stopStream();
      pendingListingsRef.current = [];
      cancelScheduledPaint(listingFlushHandleRef.current);
      listingFlushHandleRef.current = null;
      sawFirstVehicleBatchRef.current = false;
      setErrors([]);
      setDealers({});
      setPinnedDealerWebsite(null);
      setStatus(null);
      setListings([]);
      setHistoryView(null);
      setPriceFilterMin(null);
      setPriceFilterMax(null);
      setYearFilter("");
      setBodyStyleFilter("");
      setColorFilter("");
      applyFormFromHistoryRun(run);
    },
    [applyFormFromHistoryRun, stopStream],
  );

  const clearHistoryView = useCallback(() => {
    setHistoryView(null);
  }, []);

  const startSearch = useCallback(() => {
    if (running) return; // Prevent double-submit
    void stopStream();
    if (streamErrorTimerRef.current != null) {
      window.clearTimeout(streamErrorTimerRef.current);
      streamErrorTimerRef.current = null;
    }
    setHistoryView(null);
    pendingListingsRef.current = [];
    cancelScheduledPaint(listingFlushHandleRef.current);
    listingFlushHandleRef.current = null;
    sawFirstVehicleBatchRef.current = false;
    setErrors([]);
    setListings([]);
    setDealers({});
    setPinnedDealerWebsite(null);
    setStatus(null);
    setReconnecting(false);
    streamDoneReceivedRef.current = false;
    dealerStatusesRef.current.clear();
    expectedDealerTotalRef.current = null;
    const startedAt = Date.now();
    setNowMs(startedAt);

    const streamUrl = resolveApiUrl("/search/stream");
    const correlationId = buildClientSearchId();
    correlationIdRef.current = correlationId;
    const params = new URLSearchParams({
      location: location.trim(),
      make: make.trim(),
      model: model.trim(),
      correlation_id: correlationId,
      vehicle_category: vehicleCategory,
      vehicle_condition: vehicleCondition,
      radius_miles: radiusMiles,
      inventory_scope: inventoryScope,
      max_dealerships: maxDealerships,
      market_region: marketRegion,
    });
    const url = `${streamUrl}?${params.toString()}`;

    const streamSessionId = streamSessionRef.current + 1;
    streamSessionRef.current = streamSessionId;
    setRunning(true);
    const es = new EventSource(url);
    esRef.current = es;
    const isStaleSession = () => streamSessionRef.current !== streamSessionId;

    const onStatus = (ev: MessageEvent) => {
      if (isStaleSession()) return;
      try {
        const data = JSON.parse(ev.data) as { message?: string };
        if (data.message) setStatus(data.message);
      } catch {
        /* ignore */
      }
    };

    const onDealership = (ev: MessageEvent) => {
      if (isStaleSession()) return;
      try {
        const d = JSON.parse(ev.data) as DealershipProgress;
        const key = d.website || `${d.name}-${d.index}`;
        if (Number.isFinite(d.total) && d.total > 0) {
          expectedDealerTotalRef.current = d.total;
        }
        dealerStatusesRef.current.set(key, d.status);
        setDealers((prev) => {
          const prevRow = prev[key];
          const statusChanged = prevRow?.status !== d.status;
          const phaseSince = statusChanged ? Date.now() : (prevRow?.phaseSince ?? Date.now());
          return { ...prev, [key]: { ...prevRow, ...d, phaseSince } };
        });
      } catch {
        /* ignore */
      }
    };

    const onVehicles = (ev: MessageEvent) => {
      if (isStaleSession()) return;
      try {
        const data = JSON.parse(ev.data) as {
          dealership?: string;
          website?: string;
          listings?: VehicleListing[];
        };
        const dealerName = data.dealership ?? "Unknown";
        const dealerSite = data.website ?? "";
        const batch = data.listings ?? [];
        pendingListingsRef.current.push(
          ...batch.map((v) => ({
            ...v,
            dealership: dealerName,
            dealership_website: dealerSite,
          })),
        );
        if (!sawFirstVehicleBatchRef.current && batch.length > 0) {
          sawFirstVehicleBatchRef.current = true;
          flushPendingListings();
        } else {
          scheduleListingFlush();
        }
      } catch {
        /* ignore */
      }
    };

    const onError = (ev: MessageEvent) => {
      if (isStaleSession()) return;
      try {
        const data = JSON.parse(ev.data) as { message?: string };
        if (data.message) setErrors((e) => [...e, data.message!]);
      } catch {
        /* ignore */
      }
    };

    const onDone = (ev: Event) => {
      if (isStaleSession()) return;
      streamDoneReceivedRef.current = true;
      if (streamErrorTimerRef.current != null) {
        window.clearTimeout(streamErrorTimerRef.current);
        streamErrorTimerRef.current = null;
      }
      const me = ev as MessageEvent;
      try {
        const data = JSON.parse(me.data) as {
          ok?: boolean;
          dealer_discovery_count?: number;
          dealer_deduped_count?: number;
          max_dealerships?: number;
        };
        const dealerPart =
          data.dealer_discovery_count != null && data.dealer_deduped_count != null
            ? `${data.dealer_deduped_count} dealerships searched`
            : data.max_dealerships != null
              ? `${data.max_dealerships} dealerships searched`
              : null;
        if (dealerPart) {
          setStatus(`Search finished · ${dealerPart}`);
        } else {
          setStatus((s) => s ?? "Search finished.");
        }
      } catch {
        setStatus((s) => s ?? "Search finished.");
      }
      flushPendingListings();
      closeStream();
      onFinishedRef.current?.();
    };

    es.addEventListener("status", onStatus);
    es.addEventListener("dealership", onDealership);
    es.addEventListener("vehicles", onVehicles);
    es.addEventListener("search_error", onError);
    es.addEventListener("done", onDone);

    es.onopen = () => {
      if (isStaleSession()) return;
      if (streamErrorTimerRef.current != null) {
        window.clearTimeout(streamErrorTimerRef.current);
        streamErrorTimerRef.current = null;
      }
      setReconnecting(false);
    };

    es.onerror = () => {
      if (isStaleSession()) return;
      // EventSource fires `error` when the server closes after `done` and on network/proxy drops.
      // The browser would auto-reconnect the same URL, but this stream is one-shot — reconnect does
      // not resume progress and can hit duplicate correlation_id handling. Defer briefly so `onDone` can arrive.
      queueMicrotask(() => {
        if (isStaleSession() || streamDoneReceivedRef.current) return;
        if (streamErrorTimerRef.current != null) {
          window.clearTimeout(streamErrorTimerRef.current);
        }
        const timerId = window.setTimeout(() => {
          void (async () => {
            try {
              const correlationId = correlationIdRef.current;
              if (isStaleSession() || streamDoneReceivedRef.current || correlationId == null) {
                return;
              }
              // After the grace window, stop the browser's automatic reconnect loop.
              // Recovery happens by polling the persisted search run instead.
              if (esRef.current === es) {
                es.close();
              }
              setReconnecting(true);
              if (await recoverCompletedStream(correlationId, isStaleSession)) {
                return;
              }
              if (
                isStaleSession() ||
                streamDoneReceivedRef.current ||
                correlationIdRef.current == null
              ) {
                return;
              }
              const expectedDealerTotal = expectedDealerTotalRef.current;
              const dealerStatuses = dealerStatusesRef.current;
              const dealersAllTerminal =
                expectedDealerTotal != null &&
                expectedDealerTotal > 0 &&
                dealerStatuses.size >= expectedDealerTotal &&
                Array.from(dealerStatuses.values()).every((status) => isTerminalDealerStatus(status));
              if (dealersAllTerminal) {
                streamDoneReceivedRef.current = true;
                setReconnecting(false);
                setStatus(`Search finished · ${expectedDealerTotal} dealerships searched`);
                closeStream();
                onFinishedRef.current?.();
                return;
              }
              setReconnecting(false);
              setErrors((e) => appendUniqueError(e, "Connection to search stream lost or failed."));
              closeStream();
            } finally {
              if (streamErrorTimerRef.current === timerId) {
                streamErrorTimerRef.current = null;
              }
            }
          })();
        }, streamErrorGraceMs);
        streamErrorTimerRef.current = timerId;
      });
    };
  }, [
    closeStream,
    inventoryScope,
    location,
    make,
    maxDealerships,
    model,
    radiusMiles,
    recoverCompletedStream,
    stopStream,
    vehicleCategory,
    vehicleCondition,
    marketRegion,
    flushPendingListings,
    running,
    scheduleListingFlush,
  ]);

  return {
    form: {
      location,
      setLocation,
      vehicleCategory,
      setVehicleCategory,
      make,
      setMake,
      model,
      setModel,
      usesCatalog,
      vehicleCondition,
      setVehicleCondition,
      radiusMiles,
      setRadiusMiles,
      inventoryScope,
      setInventoryScope,
      maxDealerships,
      setMaxDealerships,
      modelOptions,
      marketRegion,
      setMarketRegion,
    },
    search: {
      running,
      reconnecting,
      startSearch,
      stopStream,
      status,
      errors,
      historyView,
      applySavedSearchCriteria,
      applySavedSearchFromHistory,
      applyHistoryCriteriaOnly,
      clearHistoryView,
    },
    dealers: {
      dealerList,
      loadingDealerCards,
      targetDealerCount,
      discoveredDealerPercent,
      completedDealerPercent,
      doneDealerCount,
      queuedDealerCount,
      activeDealerCount,
      activeDealerSummary,
      listingCountsByDealerKey,
      nowMs,
      pinnedDealerWebsite,
      togglePinnedDealer,
    },
    listings: {
      listings,
      filteredListings,
      loadingInventoryCards,
      sortOrder,
      setSortOrder,
    },
    filters: {
      filtersExpanded,
      setFiltersExpanded,
      yearFilter,
      setYearFilter,
      bodyStyleFilter,
      setBodyStyleFilter,
      colorFilter,
      setColorFilter,
      priceFilterMin,
      setPriceFilterMin,
      priceFilterMax,
      setPriceFilterMax,
      isPriceFilterActive,
      priceBounds,
      yearOptions,
      bodyStyleOptions,
      colorOptions,
      effectivePriceMin,
      effectivePriceMax,
      activeResultFilterCount,
      clearFilters: () => {
        setPriceFilterMin(null);
        setPriceFilterMax(null);
        setYearFilter("");
        setBodyStyleFilter("");
        setColorFilter("");
      },
    },
  };
}
