"use client";

import type { MarketRegion } from "@/lib/marketRegion";

type Props = {
  value: MarketRegion;
  onChange: (region: MarketRegion) => void;
  disabled?: boolean;
};

export function MarketRegionToggle({ value, onChange, disabled = false }: Props) {
  return (
    <div
      className="inline-flex items-center rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 dark:border-zinc-700 dark:bg-zinc-900"
      role="group"
      aria-label="Market region"
    >
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange("us")}
        className={`rounded-md px-2 py-1 text-xs font-medium transition sm:px-2.5 ${
          value === "us"
            ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-50"
            : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
        }`}
        title="United States — miles, US-focused model names"
      >
        <span className="sr-only">United States</span>
        <span aria-hidden className="text-base leading-none">
          🇺🇸
        </span>
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange("eu")}
        className={`rounded-md px-2 py-1 text-xs font-medium transition sm:px-2.5 ${
          value === "eu"
            ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-50"
            : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
        }`}
        title="European Union & UK — kilometres, EU model lines"
      >
        <span className="sr-only">European Union</span>
        <span aria-hidden className="text-base leading-none">
          🇪🇺
        </span>
      </button>
    </div>
  );
}
