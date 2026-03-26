"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { resolveApiUrl } from "@/lib/apiBase";
import { clampNumber, clampPercent, dealerSiteKey } from "@/lib/inventoryFormat";
import type { AggregatedListing } from "@/lib/inventoryFormat";
import { getModelsForMake } from "@/lib/vehicleCatalog";
import type { DealershipProgress, VehicleListing } from "@/types/inventory";

/** Client-side result ordering (applied after filters). */
export type ListingSortOrder = "price_asc" | "price_desc" | "mileage_asc" | "year_desc";

function listingSortTieBreak(a: AggregatedListing, b: AggregatedListing) {
  const ka = `${a.vin ?? ""}|${a.listing_url ?? ""}|${a.raw_title ?? ""}|${a.dealership ?? ""}`;
  const kb = `${b.vin ?? ""}|${b.listing_url ?? ""}|${b.raw_title ?? ""}|${b.dealership ?? ""}`;
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
          a.mileage != null && !Number.isNaN(a.mileage) ? a.mileage : Number.POSITIVE_INFINITY;
        const bv =
          b.mileage != null && !Number.isNaN(b.mileage) ? b.mileage : Number.POSITIVE_INFINITY;
        if (av !== bv) return av - bv;
        return listingSortTieBreak(a, b);
      }
      case "year_desc": {
        const av = a.year != null && !Number.isNaN(a.year) ? a.year : Number.NEGATIVE_INFINITY;
        const bv = b.year != null && !Number.isNaN(b.year) ? b.year : Number.NEGATIVE_INFINITY;
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

export function useSearchStream(options?: UseSearchStreamOptions) {
  const onFinishedRef = useRef<(() => void) | undefined>(undefined);
  useEffect(() => {
    onFinishedRef.current = options?.onStreamFinished;
  }, [options?.onStreamFinished]);
  const [location, setLocation] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [vehicleCondition, setVehicleCondition] = useState("all");
  const [radiusMiles, setRadiusMiles] = useState("25");
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
  const [nowMs, setNowMs] = useState(() => Date.now());
  const esRef = useRef<EventSource | null>(null);
  const streamSessionRef = useRef(0);

  const dealerList = useMemo(
    () => Object.values(dealers).sort((a, b) => a.index - b.index),
    [dealers],
  );

  const doneDealerCount = useMemo(
    () => dealerList.filter((d) => d.status === "done" || d.status === "error").length,
    [dealerList],
  );

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

  const modelOptions = useMemo(() => getModelsForMake(make), [make]);

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

  const effectivePriceMin = useMemo(() => {
    if (!priceBounds) return null;
    return clampNumber(
      priceFilterMin ?? priceBounds.min,
      priceBounds.min,
      priceFilterMax ?? priceBounds.max,
    );
  }, [priceBounds, priceFilterMax, priceFilterMin]);

  const effectivePriceMax = useMemo(() => {
    if (!priceBounds) return null;
    return clampNumber(
      priceFilterMax ?? priceBounds.max,
      effectivePriceMin ?? priceBounds.min,
      priceBounds.max,
    );
  }, [effectivePriceMin, priceBounds, priceFilterMax]);

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
      if (effectivePriceMin != null && (listing.price == null || listing.price < effectivePriceMin)) {
        return false;
      }
      if (effectivePriceMax != null && (listing.price == null || listing.price > effectivePriceMax)) {
        return false;
      }
      return true;
    });
    return listingsWithPinnedDealerFirst(sortAggregatedListings(filtered, sortOrder), pinnedDealerWebsite);
  }, [
    bodyStyleFilter,
    colorFilter,
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
    priceBounds,
    yearFilter,
  ]);

  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 1024) {
      // Collapse filters on small viewports on first mount (UX preference).
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional initial UI state from viewport
      setFiltersExpanded(false);
    }
  }, []);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const stopStream = useCallback(() => {
    streamSessionRef.current += 1;
    esRef.current?.close();
    esRef.current = null;
    setRunning(false);
  }, []);

  const startSearch = useCallback(() => {
    stopStream();
    setErrors([]);
    setListings([]);
    setDealers({});
    setPinnedDealerWebsite(null);
    setStatus(null);
    const startedAt = Date.now();
    setNowMs(startedAt);

    const streamUrl = resolveApiUrl("/search/stream");
    const params = new URLSearchParams({
      location: location.trim(),
      make: make.trim(),
      model: model.trim(),
      vehicle_condition: vehicleCondition,
      radius_miles: radiusMiles,
      inventory_scope: inventoryScope,
      max_dealerships: maxDealerships,
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
        setListings((prev) => [
          ...prev,
          ...batch.map((v) => ({
            ...v,
            dealership: dealerName,
            dealership_website: dealerSite,
          })),
        ]);
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
      stopStream();
      onFinishedRef.current?.();
    };

    es.addEventListener("status", onStatus);
    es.addEventListener("dealership", onDealership);
    es.addEventListener("vehicles", onVehicles);
    es.addEventListener("search_error", onError);
    es.addEventListener("done", onDone);

    es.onerror = () => {
      if (isStaleSession()) return;
      setErrors((e) => [...e, "Connection to search stream lost or failed."]);
      stopStream();
    };
  }, [
    inventoryScope,
    location,
    make,
    maxDealerships,
    model,
    radiusMiles,
    stopStream,
    vehicleCondition,
  ]);

  return {
    form: {
      location,
      setLocation,
      make,
      setMake,
      model,
      setModel,
      vehicleCondition,
      setVehicleCondition,
      radiusMiles,
      setRadiusMiles,
      inventoryScope,
      setInventoryScope,
      maxDealerships,
      setMaxDealerships,
      modelOptions,
    },
    search: {
      running,
      startSearch,
      stopStream,
      status,
      errors,
    },
    dealers: {
      dealerList,
      loadingDealerCards,
      targetDealerCount,
      discoveredDealerPercent,
      completedDealerPercent,
      doneDealerCount,
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
