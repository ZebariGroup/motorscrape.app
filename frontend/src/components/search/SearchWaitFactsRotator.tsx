"use client";

import { useEffect, useMemo, useState } from "react";
import type { VehicleCategory } from "@/lib/vehicleCatalog";
import { buildSearchWaitFacts } from "@/lib/vehicleSearchFacts";

type Props = {
  running: boolean;
  make: string;
  model: string;
  vehicleCategory: VehicleCategory;
  vehicleCondition: string;
};

const ROTATE_MS = 6500;

export function SearchWaitFactsRotator({
  running,
  make,
  model,
  vehicleCategory,
  vehicleCondition,
}: Props) {
  const facts = useMemo(
    () =>
      buildSearchWaitFacts({
        make,
        model,
        vehicleCategory,
        vehicleCondition,
      }),
    [make, model, vehicleCategory, vehicleCondition],
  );

  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!running) return;
    setIndex(0);
  }, [running, make, model, vehicleCategory, vehicleCondition]);

  useEffect(() => {
    if (!running || facts.length <= 1) return;
    const id = window.setInterval(() => {
      setIndex((i) => (i + 1) % facts.length);
    }, ROTATE_MS);
    return () => window.clearInterval(id);
  }, [running, facts.length]);

  if (!running || facts.length === 0) return null;

  const line = facts[index] ?? facts[0];

  return (
    <div
      className="rounded-lg border border-zinc-200/80 bg-zinc-50/80 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/50"
      aria-live="polite"
      aria-atomic="true"
    >
      <p className="text-[12px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
        While you wait
      </p>
      <p className="mt-1 text-sm leading-snug text-zinc-700 dark:text-zinc-300">{line}</p>
    </div>
  );
}
