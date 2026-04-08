import Link from "next/link";
import { Metadata } from "next";

import { DirectoryHeader } from "@/components/DirectoryHeader";
import { getMakesForCategory, getModelsForMake } from "@/lib/vehicleCatalog";
import { TOP_STATES, getCitiesByState } from "@/lib/locations";

export const metadata: Metadata = {
  title: "Directory | Browse by Make and Location",
  description: "Browse Motorscrape's directory of local dealership inventory by vehicle make, model, state, and city.",
  alternates: {
    canonical: "/directory",
  },
};

export default function DirectoryPage() {
  const makes = getMakesForCategory("car", "us");

  return (
    <>
      <DirectoryHeader />
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-12">
        <header>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            Browse Inventory Directory
          </h1>
          <p className="mt-2 text-zinc-600 dark:text-zinc-400">
            Find local dealership inventory by vehicle make, model, or location.
          </p>
        </header>

        <div className="grid gap-12 md:grid-cols-2">
          {/* Browse by Location */}
          <section>
            <h2 className="mb-6 text-2xl font-semibold text-zinc-900 dark:text-zinc-50 border-b border-zinc-200 pb-2 dark:border-zinc-800">
              Browse by Location
            </h2>
            <div className="space-y-6">
              {TOP_STATES.map((state) => {
                const cities = getCitiesByState(state.abbr);
                return (
                  <div key={state.abbr}>
                    <h3 className="mb-2 text-lg font-medium text-zinc-800 dark:text-zinc-200">
                      <Link href={`/locations/${state.slug}`} className="hover:text-emerald-600 hover:underline">
                        {state.name}
                      </Link>
                    </h3>
                    {cities.length > 0 && (
                      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {cities.map((city) => (
                          <li key={city.slug}>
                            <Link
                              href={`/locations/${state.slug}/${city.slug}`}
                              className="text-sm text-zinc-600 hover:text-emerald-600 hover:underline dark:text-zinc-400 dark:hover:text-emerald-400"
                            >
                              {city.name}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          {/* Browse by Make */}
          <section>
            <h2 className="mb-6 text-2xl font-semibold text-zinc-900 dark:text-zinc-50 border-b border-zinc-200 pb-2 dark:border-zinc-800">
              Browse by Make
            </h2>
            <div className="space-y-6">
              {makes.map((make) => {
                const models = getModelsForMake("car", make, "us");
                const makeSlug = encodeURIComponent(make.toLowerCase());
                return (
                  <div key={make}>
                    <h3 className="mb-2 text-lg font-medium text-zinc-800 dark:text-zinc-200">
                      <Link href={`/cars/${makeSlug}`} className="hover:text-emerald-600 hover:underline">
                        {make}
                      </Link>
                    </h3>
                    {models.length > 0 && (
                      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {models.map((model) => {
                          const modelSlug = encodeURIComponent(model.toLowerCase());
                          return (
                            <li key={model}>
                              <Link
                                href={`/cars/${makeSlug}/${modelSlug}`}
                                className="text-sm text-zinc-600 hover:text-emerald-600 hover:underline dark:text-zinc-400 dark:hover:text-emerald-400"
                              >
                                {model}
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </main>
    </>
  );
}
