"use client";

import type { Dispatch, SetStateAction } from "react";

import { formatMileage, formatMoney, sliderStep } from "@/lib/inventoryFormat";
import type { VehicleCategory } from "@/lib/vehicleCatalog";

type Props = {
  /** When true the panel content is always shown (no collapse toggle). Used inside the sidebar. */
  alwaysExpanded?: boolean;
  filtersExpanded: boolean;
  setFiltersExpanded: Dispatch<SetStateAction<boolean>>;
  activeResultFilterCount: number;
  yearFilter: string;
  setYearFilter: (v: string) => void;
  yearOptions: number[];
  bodyStyleFilter: string;
  setBodyStyleFilter: (v: string) => void;
  bodyStyleOptions: string[];
  vehicleCategory: VehicleCategory;
  colorFilter: string;
  setColorFilter: (v: string) => void;
  colorOptions: string[];
  priceBounds: { min: number; max: number } | null;
  effectivePriceMin: number | null;
  effectivePriceMax: number | null;
  isPriceFilterActive: boolean;
  setPriceFilterMin: (v: number) => void;
  setPriceFilterMax: (v: number) => void;
  mileageBounds: { min: number; max: number } | null;
  effectiveMileageMin: number | null;
  effectiveMileageMax: number | null;
  isMileageFilterActive: boolean;
  setMileageFilterMin: (v: number) => void;
  setMileageFilterMax: (v: number) => void;
  transmissionFilter: string;
  setTransmissionFilter: (v: string) => void;
  transmissionOptions: string[];
  drivetrainFilter: string;
  setDrivetrainFilter: (v: string) => void;
  drivetrainOptions: string[];
  fuelTypeFilter: string;
  setFuelTypeFilter: (v: string) => void;
  fuelTypeOptions: string[];
  onClearFilters: () => void;
};

const selectClass =
  "rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-emerald-500/40 focus:ring-2 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50";

export function ResultFiltersPanel({
  alwaysExpanded = false,
  filtersExpanded,
  setFiltersExpanded,
  activeResultFilterCount,
  yearFilter,
  setYearFilter,
  yearOptions,
  bodyStyleFilter,
  setBodyStyleFilter,
  bodyStyleOptions,
  vehicleCategory,
  colorFilter,
  setColorFilter,
  colorOptions,
  priceBounds,
  effectivePriceMin,
  effectivePriceMax,
  isPriceFilterActive,
  setPriceFilterMin,
  setPriceFilterMax,
  mileageBounds,
  effectiveMileageMin,
  effectiveMileageMax,
  isMileageFilterActive,
  setMileageFilterMin,
  setMileageFilterMax,
  transmissionFilter,
  setTransmissionFilter,
  transmissionOptions,
  drivetrainFilter,
  setDrivetrainFilter,
  drivetrainOptions,
  fuelTypeFilter,
  setFuelTypeFilter,
  fuelTypeOptions,
  onClearFilters,
}: Props) {
  const bodyStyleLabel = vehicleCategory === "car" ? "Style" : "Type / class";
  const bodyStyleAnyLabel = vehicleCategory === "car" ? "All styles" : "All types";

  const priceStep = priceBounds ? sliderStep(priceBounds.min, priceBounds.max, 1) : 1;
  const priceSliderMin = priceBounds ? effectivePriceMin ?? priceBounds.min : 0;
  const priceSliderMax = priceBounds ? effectivePriceMax ?? priceBounds.max : 0;
  const priceSpan = priceBounds ? Math.max(priceBounds.max - priceBounds.min, 1) : 1;
  const priceLeftPct = priceBounds ? ((priceSliderMin - priceBounds.min) / priceSpan) * 100 : 0;
  const priceRightPct = priceBounds ? ((priceSliderMax - priceBounds.min) / priceSpan) * 100 : 100;

  const mileageStep = mileageBounds ? sliderStep(mileageBounds.min, mileageBounds.max, 1) : 1;
  const mileageSliderMin = mileageBounds ? effectiveMileageMin ?? mileageBounds.min : 0;
  const mileageSliderMax = mileageBounds ? effectiveMileageMax ?? mileageBounds.max : 0;
  const mileageSpan = mileageBounds ? Math.max(mileageBounds.max - mileageBounds.min, 1) : 1;
  const mileageLeftPct = mileageBounds ? ((mileageSliderMin - mileageBounds.min) / mileageSpan) * 100 : 0;
  const mileageRightPct = mileageBounds ? ((mileageSliderMax - mileageBounds.min) / mileageSpan) * 100 : 100;

  const isOpen = alwaysExpanded || filtersExpanded;

  const content = (
    <div className="space-y-5">
      {/* Year / Body Style / Color */}
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Year</span>
          <select value={yearFilter} onChange={(e) => setYearFilter(e.target.value)} className={selectClass}>
            <option value="">All years</option>
            {yearOptions.map((year) => (
              <option key={year} value={String(year)}>
                {year}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">{bodyStyleLabel}</span>
          <select value={bodyStyleFilter} onChange={(e) => setBodyStyleFilter(e.target.value)} className={selectClass}>
            <option value="">{bodyStyleAnyLabel}</option>
            {bodyStyleOptions.map((bodyStyle) => (
              <option key={bodyStyle} value={bodyStyle}>
                {bodyStyle}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Color</span>
          <select value={colorFilter} onChange={(e) => setColorFilter(e.target.value)} className={selectClass}>
            <option value="">All colors</option>
            {colorOptions.map((color) => (
              <option key={color} value={color}>
                {color}
              </option>
            ))}
          </select>
        </label>
        {transmissionOptions.length > 0 && (
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Transmission</span>
            <select
              value={transmissionFilter}
              onChange={(e) => setTransmissionFilter(e.target.value)}
              className={selectClass}
            >
              <option value="">All</option>
              {transmissionOptions.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
        {drivetrainOptions.length > 0 && (
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Drivetrain</span>
            <select
              value={drivetrainFilter}
              onChange={(e) => setDrivetrainFilter(e.target.value)}
              className={selectClass}
            >
              <option value="">All</option>
              {drivetrainOptions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        {fuelTypeOptions.length > 0 && (
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Fuel type</span>
            <select
              value={fuelTypeFilter}
              onChange={(e) => setFuelTypeFilter(e.target.value)}
              className={selectClass}
            >
              <option value="">All</option>
              {fuelTypeOptions.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {/* Price range */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Price</span>
          <span className="text-zinc-500 dark:text-zinc-400">
            {priceBounds
              ? isPriceFilterActive
                ? `${formatMoney(priceSliderMin)} – ${formatMoney(priceSliderMax)}`
                : "All prices"
              : "No priced vehicles yet"}
          </span>
        </div>
        {priceBounds ? (
          <div className="relative flex items-center gap-2">
            <div className="pointer-events-none absolute inset-x-0 h-1 rounded-full bg-zinc-200 dark:bg-zinc-700">
              <div
                className="absolute h-full rounded-full bg-emerald-400"
                style={{ left: `${priceLeftPct}%`, width: `${Math.max(0, priceRightPct - priceLeftPct)}%` }}
              />
            </div>
            <input
              type="range"
              aria-label="Minimum price"
              min={priceBounds.min}
              max={priceBounds.max}
              step={priceStep}
              value={priceSliderMin}
              onChange={(e) => setPriceFilterMin(Math.min(Number(e.target.value), priceSliderMax))}
              className="relative z-10 min-w-0 flex-1 appearance-none accent-emerald-600"
            />
            <input
              type="range"
              aria-label="Maximum price"
              min={priceBounds.min}
              max={priceBounds.max}
              step={priceStep}
              value={priceSliderMax}
              onChange={(e) => setPriceFilterMax(Math.max(Number(e.target.value), priceSliderMin))}
              className="relative z-10 min-w-0 flex-1 appearance-none accent-emerald-600"
            />
          </div>
        ) : (
          <div className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/70 dark:text-zinc-400">
            Bars appear once priced inventory loads.
          </div>
        )}
      </div>

      {/* Mileage range */}
      {vehicleCategory !== "boat" && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-zinc-700 dark:text-zinc-300">Mileage</span>
            <span className="text-zinc-500 dark:text-zinc-400">
              {mileageBounds
                ? isMileageFilterActive
                  ? `${formatMileage(mileageSliderMin)} – ${formatMileage(mileageSliderMax)}`
                  : "All mileages"
                : "No mileage data yet"}
            </span>
          </div>
          {mileageBounds ? (
            <div className="relative flex items-center gap-2">
              <div className="pointer-events-none absolute inset-x-0 h-1 rounded-full bg-zinc-200 dark:bg-zinc-700">
                <div
                  className="absolute h-full rounded-full bg-emerald-400"
                  style={{ left: `${mileageLeftPct}%`, width: `${Math.max(0, mileageRightPct - mileageLeftPct)}%` }}
                />
              </div>
              <input
                type="range"
                aria-label="Minimum mileage"
                min={mileageBounds.min}
                max={mileageBounds.max}
                step={mileageStep}
                value={mileageSliderMin}
                onChange={(e) => setMileageFilterMin(Math.min(Number(e.target.value), mileageSliderMax))}
                className="relative z-10 min-w-0 flex-1 appearance-none accent-emerald-600"
              />
              <input
                type="range"
                aria-label="Maximum mileage"
                min={mileageBounds.min}
                max={mileageBounds.max}
                step={mileageStep}
                value={mileageSliderMax}
                onChange={(e) => setMileageFilterMax(Math.max(Number(e.target.value), mileageSliderMin))}
                className="relative z-10 min-w-0 flex-1 appearance-none accent-emerald-600"
              />
            </div>
          ) : (
            <div className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900/70 dark:text-zinc-400">
              Bars appear once mileage data loads.
            </div>
          )}
        </div>
      )}

      {activeResultFilterCount > 0 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClearFilters}
            className="text-xs font-medium text-zinc-600 underline-offset-2 hover:underline dark:text-zinc-400"
          >
            Clear all filters
          </button>
        </div>
      )}
    </div>
  );

  if (alwaysExpanded) {
    return content;
  }

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <button
        type="button"
        onClick={() => setFiltersExpanded((open) => !open)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Result filters</h2>
          {activeResultFilterCount > 0 ? (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[12px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
              {activeResultFilterCount} active
            </span>
          ) : null}
        </div>
        <span className="text-lg text-zinc-400">{filtersExpanded ? "−" : "+"}</span>
      </button>
      {filtersExpanded ? (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">{content}</div>
      ) : null}
    </div>
  );
}
