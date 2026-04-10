import { Suspense } from "react";
import { notFound } from "next/navigation";
import Link from "next/link";
import type { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { DirectoryHeader } from "@/components/DirectoryHeader";
import { getMakesForCategory, getModelsForMake } from "@/lib/vehicleCatalog";
import {
  fetchVehicleSightings,
  fetchVehicleSightingsSummary,
  formatPrice,
  formatSightingDate,
  type VehicleSighting,
  type VehicleSightingsSummary,
} from "@/lib/vehicleApi";

type Props = {
  params: Promise<{ make: string; model: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { make, model } = await params;
  const decodedMake = decodeURIComponent(make);
  const decodedModel = decodeURIComponent(model);

  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find((m) => m.toLowerCase() === decodedMake.toLowerCase());
  if (!formattedMake) return { title: "Not Found" };

  const models = getModelsForMake("car", formattedMake, "us");
  const formattedModel = models.find((m) => m.toLowerCase() === decodedModel.toLowerCase());
  if (!formattedModel) return { title: "Not Found" };

  return {
    title: `${formattedMake} ${formattedModel} | National Inventory Sightings`,
    description: `See where ${formattedMake} ${formattedModel} has been found at dealerships across the US. Real scrape data: prices, locations, and dealers. Search near you.`,
    alternates: {
      canonical: `/cars/${encodeURIComponent(formattedMake.toLowerCase())}/${encodeURIComponent(formattedModel.toLowerCase())}`,
    },
  };
}

// ─── Small atoms ──────────────────────────────────────────────────────────────

function StatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/60">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p
        className={`mt-1 text-lg font-semibold ${
          accent ? "text-blue-700 dark:text-blue-400" : "text-zinc-900 dark:text-zinc-50"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function SightingRow({ sighting }: { sighting: VehicleSighting }) {
  const dealers = sighting.top_dealerships?.slice(0, 2) ?? [];
  return (
    <tr className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
      <td className="py-3 pr-4 text-sm text-zinc-900 dark:text-zinc-100">
        {sighting.search_location}
      </td>
      <td className="py-3 pr-4 text-sm text-zinc-500 dark:text-zinc-400">
        {formatSightingDate(sighting.scraped_at)}
      </td>
      <td className="py-3 pr-4 text-right text-sm font-medium text-zinc-900 dark:text-zinc-100">
        {sighting.result_count.toLocaleString()}
      </td>
      <td className="py-3 pr-4 text-right text-sm text-zinc-700 dark:text-zinc-300">
        {sighting.price_avg != null ? formatPrice(sighting.price_avg) : "—"}
      </td>
      <td className="py-3 text-sm text-zinc-500 dark:text-zinc-400">
        {dealers.length > 0
          ? dealers.map((d) => d.name || d.domain).join(", ")
          : "—"}
      </td>
    </tr>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function MakeModelPage({ params }: Props) {
  const { make, model } = await params;
  const decodedMake = decodeURIComponent(make);
  const decodedModel = decodeURIComponent(model);

  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find((m) => m.toLowerCase() === decodedMake.toLowerCase());
  if (!formattedMake) notFound();

  const models = getModelsForMake("car", formattedMake, "us");
  const formattedModel = models.find((m) => m.toLowerCase() === decodedModel.toLowerCase());
  if (!formattedModel) notFound();

  // Fetch in parallel: summary stats + recent individual sightings
  const [summary, recentSightings]: [VehicleSightingsSummary, VehicleSighting[]] =
    await Promise.all([
      fetchVehicleSightingsSummary(formattedMake, formattedModel),
      fetchVehicleSightings(formattedMake, formattedModel, { limit: 50 }),
    ]);

  const hasData = summary.total_sightings > 0;
  const statesCount = summary.states.filter((s) => s.state !== "Other").length;
  const makeHref = `/cars/${encodeURIComponent(formattedMake.toLowerCase())}`;

  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">

        {/* Breadcrumb */}
        <div className="mb-4 flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
          <Link href="/dealers" className="hover:underline">Directory</Link>
          <span>/</span>
          <span>Cars</span>
          <span>/</span>
          <Link href={makeHref} className="hover:underline">{formattedMake}</Link>
          <span>/</span>
          <span className="text-zinc-900 dark:text-zinc-100">{formattedModel}</span>
        </div>

        {/* Vehicle header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            {formattedMake} {formattedModel}
          </h1>
          {hasData ? (
            <p className="mt-2 text-zinc-500 dark:text-zinc-400">
              Found in{" "}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {summary.total_results.toLocaleString()} listings
              </span>{" "}
              across{" "}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {summary.total_sightings.toLocaleString()} searches
              </span>
              {statesCount > 0 && (
                <>
                  {" "}in{" "}
                  <span className="font-medium text-zinc-700 dark:text-zinc-300">
                    {statesCount} state{statesCount !== 1 ? "s" : ""}
                  </span>
                </>
              )}
            </p>
          ) : (
            <p className="mt-2 text-zinc-500 dark:text-zinc-400">
              No sightings yet. Be the first to search for this vehicle — results will appear here.
            </p>
          )}
        </div>

        {/* Stats row */}
        {hasData && (
          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Searches in DB" value={summary.total_sightings.toLocaleString()} />
            <StatCard label="Total listings seen" value={summary.total_results.toLocaleString()} />
            <StatCard label="States covered" value={statesCount > 0 ? String(statesCount) : "—"} />
            <StatCard
              label="Avg price"
              value={summary.price_avg != null ? formatPrice(summary.price_avg) : "—"}
              accent
            />
          </div>
        )}

        {/* Price insights */}
        {hasData && (summary.price_min != null || summary.price_max != null) && (
          <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Price insights from real dealership scrapes
            </h2>
            <div className="flex flex-wrap items-end gap-8">
              {summary.price_min != null && (
                <div>
                  <p className="mb-0.5 text-xs text-zinc-500 dark:text-zinc-400">Lowest seen</p>
                  <p className="text-3xl font-bold text-green-600 dark:text-green-400">
                    {formatPrice(summary.price_min)}
                  </p>
                </div>
              )}
              {summary.price_avg != null && (
                <div>
                  <p className="mb-0.5 text-xs text-zinc-500 dark:text-zinc-400">Average</p>
                  <p className="text-3xl font-bold text-zinc-900 dark:text-zinc-50">
                    {formatPrice(summary.price_avg)}
                  </p>
                </div>
              )}
              {summary.price_max != null && (
                <div>
                  <p className="mb-0.5 text-xs text-zinc-500 dark:text-zinc-400">Highest seen</p>
                  <p className="text-3xl font-bold text-zinc-700 dark:text-zinc-300">
                    {formatPrice(summary.price_max)}
                  </p>
                </div>
              )}
            </div>
            <p className="mt-3 text-xs text-zinc-400 dark:text-zinc-600">
              Prices reflect actual dealer listings captured during searches by Motorscrape users.
            </p>
          </div>
        )}

        {/* Where it&apos;s been found */}
        {hasData && summary.states.length > 0 && (
          <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Where it&apos;s been found
            </h2>
            <div className="flex flex-wrap gap-2">
              {summary.states.slice(0, 30).map((bucket) => (
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
            {summary.states.some((s) => s.sample_locations.length > 0) && (
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
                {summary.states
                  .slice(0, 8)
                  .flatMap((b) => b.sample_locations)
                  .slice(0, 12)
                  .map((loc) => (
                    <span key={loc} className="text-xs text-zinc-400 dark:text-zinc-600">
                      {loc}
                    </span>
                  ))}
              </div>
            )}
          </div>
        )}

        {/* National sightings table */}
        {recentSightings.length > 0 && (
          <div className="mb-8 rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Recent sightings across the country
              </h2>
            </div>
            <div className="overflow-x-auto px-5">
              <table className="w-full min-w-[560px]">
                <thead>
                  <tr className="border-b border-zinc-100 dark:border-zinc-800">
                    <th className="py-2 pr-4 text-left text-xs font-medium text-zinc-400">Location</th>
                    <th className="py-2 pr-4 text-left text-xs font-medium text-zinc-400">Date</th>
                    <th className="py-2 pr-4 text-right text-xs font-medium text-zinc-400"># Listings</th>
                    <th className="py-2 pr-4 text-right text-xs font-medium text-zinc-400">Avg Price</th>
                    <th className="py-2 text-left text-xs font-medium text-zinc-400">Dealers</th>
                  </tr>
                </thead>
                <tbody>
                  {recentSightings.map((s, i) => (
                    <SightingRow key={i} sighting={s} />
                  ))}
                </tbody>
              </table>
            </div>
            {recentSightings.length === 50 && (
              <p className="px-5 py-3 text-xs text-zinc-400 dark:text-zinc-600">
                Showing 50 most recent. More sightings are added each time a user searches.
              </p>
            )}
          </div>
        )}

        {/* CTA to search */}
        <div className="mb-6 border-t border-zinc-200 dark:border-zinc-800" />
        <h2 className="mb-4 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
          Search {formattedMake} {formattedModel} Near You
        </h2>
        <p className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
          Live-scrape local dealership websites for real {formattedMake} {formattedModel} inventory.
          Your search results will contribute to the national sightings database above.
        </p>

        <Suspense>
          <SearchExperience initialCriteria={{ make: formattedMake, model: formattedModel }} />
        </Suspense>
      </main>
    </>
  );
}
