"use client";

import type { Dispatch, SetStateAction } from "react";

import { formatMoney, sliderStep } from "@/lib/inventoryFormat";

type Props = {
  filtersExpanded: boolean;
  setFiltersExpanded: Dispatch<SetStateAction<boolean>>;
  activeResultFilterCount: number;
  yearFilter: string;
  setYearFilter: (v: string) => void;
  yearOptions: number[];
  bodyStyleFilter: string;
  setBodyStyleFilter: (v: string) => void;
  bodyStyleOptions: string[];
  colorFilter: string;
  setColorFilter: (v: string) => void;
  colorOptions: string[];
  priceBounds: { min: number; max: number } | null;
  effectivePriceMin: number | null;
  effectivePriceMax: number | null;
  setPriceFilterMin: (v: number) => void;
  setPriceFilterMax: (v: number) => void;
  onClearFilters: () => void;
};

export function ResultFiltersPanel({
  filtersExpanded,
  setFiltersExpanded,
  activeResultFilterCount,
  yearFilter,
  setYearFilter,
  yearOptions,
  bodyStyleFilter,
  setBodyStyleFilter,
  bodyStyleOptions,
  colorFilter,
  setColorFilter,
  colorOptions,
  priceBounds,
  effectivePriceMin,
  effectivePriceMax,
  setPriceFilterMin,
  setPriceFilterMax,
  onClearFilters,
}: Props) {
  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setFiltersExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Result filters</h2>
            {activeResultFilterCount > 0 ? (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                {activeResultFilterCount} active
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            Narrow the streamed inventory by year, style, color, and price.
          </p>
        </div>
        <span className="text-lg text-zinc-400">{filtersExpanded ? "−" : "+"}</span>
      </button>
      {filtersExpanded ? (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">Year</span>
                <select
                  value={yearFilter}
                  onChange={(e) => setYearFilter(e.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="">All years</option>
                  {yearOptions.map((year) => (
                    <option key={year} value={String(year)}>
                      {year}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">Style</span>
                <select
                  value={bodyStyleFilter}
                  onChange={(e) => setBodyStyleFilter(e.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="">All styles</option>
                  {bodyStyleOptions.map((bodyStyle) => (
                    <option key={bodyStyle} value={bodyStyle}>
                      {bodyStyle}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">Color</span>
                <select
                  value={colorFilter}
                  onChange={(e) => setColorFilter(e.target.value)}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="">All colors</option>
                  {colorOptions.map((color) => (
                    <option key={color} value={color}>
                      {color}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-zinc-700 dark:text-zinc-300">Price</span>
                <span className="text-zinc-500 dark:text-zinc-400">
                  {priceBounds && effectivePriceMin != null && effectivePriceMax != null
                    ? `${formatMoney(effectivePriceMin)} to ${formatMoney(effectivePriceMax)}`
                    : "No priced vehicles yet"}
                </span>
              </div>
              {priceBounds && effectivePriceMin != null && effectivePriceMax != null ? (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      aria-label="Minimum price"
                      min={priceBounds.min}
                      max={priceBounds.max}
                      step={sliderStep(priceBounds.min, priceBounds.max, 500)}
                      value={effectivePriceMin}
                      onChange={(e) =>
                        setPriceFilterMin(Math.min(Number(e.target.value), effectivePriceMax))
                      }
                      className="min-w-0 flex-1 accent-emerald-600"
                    />
                    <input
                      type="range"
                      aria-label="Maximum price"
                      min={priceBounds.min}
                      max={priceBounds.max}
                      step={sliderStep(priceBounds.min, priceBounds.max, 500)}
                      value={effectivePriceMax}
                      onChange={(e) =>
                        setPriceFilterMax(Math.max(Number(e.target.value), effectivePriceMin))
                      }
                      className="min-w-0 flex-1 accent-emerald-600"
                    />
                  </div>
                  <div className="flex justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span>{formatMoney(priceBounds.min)}</span>
                    <span>{formatMoney(priceBounds.max)}</span>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/70 dark:text-zinc-400">
                  Drag bars appear once priced inventory is loaded.
                </div>
              )}
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClearFilters}
                className="text-xs font-medium text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
              >
                Clear filters
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
