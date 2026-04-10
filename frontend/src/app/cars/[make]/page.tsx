import { Suspense } from "react";
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { DirectoryHeader } from "@/components/DirectoryHeader";
import { getMakesForCategory, getModelGroupsForMake } from "@/lib/vehicleCatalog";
import {
  fetchVehicleSightings,
  fetchVehicleSightingsSummary,
  formatPrice,
  type VehicleSightingsSummary,
} from "@/lib/vehicleApi";

type Props = {
  params: Promise<{ make: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { make } = await params;
  const decodedMake = decodeURIComponent(make);

  const makes = getMakesForCategory("car", "us");
  const isValid = makes.some((m) => m.toLowerCase() === decodedMake.toLowerCase());
  if (!isValid) return { title: "Not Found" };

  const formattedMake = makes.find((m) => m.toLowerCase() === decodedMake.toLowerCase()) || decodedMake;

  return {
    title: `${formattedMake} Inventory | National Sightings & Local Dealership Search`,
    description: `Browse national ${formattedMake} sightings from real dealership scrapes across the US. Search local ${formattedMake} inventory near you.`,
    alternates: {
      canonical: `/cars/${encodeURIComponent(formattedMake.toLowerCase())}`,
    },
  };
}

// ─── Small atoms ──────────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/60">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{value}</p>
    </div>
  );
}

function ModelCard({
  make,
  model,
  sightingCount,
  isDiscontinued,
}: {
  make: string;
  model: string;
  sightingCount: number | null;
  isDiscontinued: boolean;
}) {
  const href = `/cars/${encodeURIComponent(make.toLowerCase())}/${encodeURIComponent(model.toLowerCase())}`;
  return (
    <Link
      href={href}
      className="group flex flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-blue-700"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium text-zinc-900 group-hover:text-blue-700 dark:text-zinc-100 dark:group-hover:text-blue-400">
          {model}
        </span>
        {isDiscontinued && (
          <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            Discontinued
          </span>
        )}
      </div>
      {sightingCount != null && sightingCount > 0 ? (
        <span className="text-xs text-blue-600 dark:text-blue-400">
          {sightingCount.toLocaleString()} {sightingCount === 1 ? "sighting" : "sightings"} in DB
        </span>
      ) : (
        <span className="text-xs text-zinc-400 dark:text-zinc-600">Not yet in national DB</span>
      )}
    </Link>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function MakePage({ params }: Props) {
  const { make } = await params;
  const decodedMake = decodeURIComponent(make);

  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find((m) => m.toLowerCase() === decodedMake.toLowerCase());
  if (!formattedMake) notFound();

  const { current: currentModels, discontinued: discontinuedModels } = getModelGroupsForMake(
    "car",
    formattedMake,
    "us",
  );

  // Fetch national sightings summary for this make (all models)
  const summary: VehicleSightingsSummary = await fetchVehicleSightingsSummary(formattedMake);

  // Build a per-model sighting count map from recent sightings
  const recentSightings = await fetchVehicleSightings(formattedMake, undefined, { limit: 200 });
  const modelSightingCounts: Record<string, number> = {};
  for (const s of recentSightings) {
    const key = (s.model || "").toLowerCase();
    if (key) modelSightingCounts[key] = (modelSightingCounts[key] ?? 0) + 1;
  }

  const statesCount = summary.states.filter((s) => s.state !== "Other").length;
  const hasData = summary.total_sightings > 0;

  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">

        {/* Brand header */}
        <div className="mb-8">
          <div className="mb-1 flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            <Link href="/dealers" className="hover:underline">Directory</Link>
            <span>/</span>
            <span>Cars</span>
            <span>/</span>
            <span className="text-zinc-900 dark:text-zinc-100">{formattedMake}</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            {formattedMake}
          </h1>
          {hasData && (
            <p className="mt-2 text-zinc-500 dark:text-zinc-400">
              Spotted {summary.total_results.toLocaleString()} listings across{" "}
              {summary.total_sightings.toLocaleString()} searches
              {statesCount > 0 && <> in {statesCount} state{statesCount !== 1 ? "s" : ""}</>}
            </p>
          )}
        </div>

        {/* Stats row */}
        {hasData && (
          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Total searches in DB" value={summary.total_sightings.toLocaleString()} />
            <StatCard label="Total listings found" value={summary.total_results.toLocaleString()} />
            <StatCard label="States covered" value={statesCount > 0 ? String(statesCount) : "—"} />
            <StatCard
              label="Avg price seen"
              value={summary.price_avg != null ? formatPrice(summary.price_avg) : "—"}
            />
          </div>
        )}

        {/* Price range */}
        {hasData && (summary.price_min != null || summary.price_max != null) && (
          <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Price range from real scrapes
            </h2>
            <div className="flex flex-wrap items-center gap-6">
              {summary.price_min != null && (
                <div>
                  <p className="text-xs text-zinc-500">Lowest seen</p>
                  <p className="text-2xl font-bold text-green-600 dark:text-green-400">{formatPrice(summary.price_min)}</p>
                </div>
              )}
              {summary.price_avg != null && (
                <div>
                  <p className="text-xs text-zinc-500">Average</p>
                  <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{formatPrice(summary.price_avg)}</p>
                </div>
              )}
              {summary.price_max != null && (
                <div>
                  <p className="text-xs text-zinc-500">Highest seen</p>
                  <p className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">{formatPrice(summary.price_max)}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* States breakdown */}
        {hasData && summary.states.length > 0 && (
          <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Where it&apos;s been found
            </h2>
            <div className="flex flex-wrap gap-2">
              {summary.states.slice(0, 20).map((bucket) => (
                <div
                  key={bucket.state}
                  className="flex items-center gap-1.5 rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-800"
                >
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100">{bucket.state}</span>
                  <span className="text-zinc-500 dark:text-zinc-400">
                    {bucket.total_results.toLocaleString()} listings
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Current models grid */}
        {currentModels.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-4 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Current Models
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {currentModels.map((model) => (
                <ModelCard
                  key={model}
                  make={formattedMake}
                  model={model}
                  sightingCount={modelSightingCounts[model.toLowerCase()] ?? null}
                  isDiscontinued={false}
                />
              ))}
            </div>
          </section>
        )}

        {/* Discontinued models grid */}
        {discontinuedModels.length > 0 && (
          <section className="mb-8">
            <h2 className="mb-4 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Discontinued Models
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {discontinuedModels.map((model) => (
                <ModelCard
                  key={model}
                  make={formattedMake}
                  model={model}
                  sightingCount={modelSightingCounts[model.toLowerCase()] ?? null}
                  isDiscontinued={true}
                />
              ))}
            </div>
          </section>
        )}

        {/* Divider before search */}
        <div className="mb-6 border-t border-zinc-200 dark:border-zinc-800" />
        <h2 className="mb-4 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
          Search {formattedMake} Inventory Near You
        </h2>

        <Suspense>
          <SearchExperience initialCriteria={{ make: formattedMake }} />
        </Suspense>
      </main>
    </>
  );
}
