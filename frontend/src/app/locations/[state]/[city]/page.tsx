import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { getStateBySlug, getCityBySlug } from "@/lib/locations";

type Props = {
  params: Promise<{ state: string; city: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { state, city } = await params;
  const decodedState = decodeURIComponent(state);
  const decodedCity = decodeURIComponent(city);
  
  const stateObj = getStateBySlug(decodedState.toLowerCase());
  if (!stateObj) {
    return { title: "Not Found" };
  }

  const cityObj = getCityBySlug(stateObj.abbr, decodedCity.toLowerCase());
  if (!cityObj) {
    return { title: "Not Found" };
  }

  return {
    title: `Cars for Sale in ${cityObj.name}, ${stateObj.abbr} | Local Dealership Inventory`,
    description: `Search local dealership websites for new and used car inventory in ${cityObj.name}, ${stateObj.abbr}. Find the best deals near you.`,
    alternates: {
      canonical: `/locations/${stateObj.slug}/${cityObj.slug}`,
    },
  };
}

export default async function CityPage({ params }: Props) {
  const { state, city } = await params;
  const decodedState = decodeURIComponent(state);
  const decodedCity = decodeURIComponent(city);
  
  const stateObj = getStateBySlug(decodedState.toLowerCase());
  if (!stateObj) {
    notFound();
  }

  const cityObj = getCityBySlug(stateObj.abbr, decodedCity.toLowerCase());
  if (!cityObj) {
    notFound();
  }

  return (
    <Suspense>
      <SearchExperience initialCriteria={{ location: `${cityObj.name}, ${stateObj.abbr}` }} />
    </Suspense>
  );
}
