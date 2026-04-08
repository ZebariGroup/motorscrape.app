import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { getStateBySlug } from "@/lib/locations";

type Props = {
  params: Promise<{ state: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { state } = await params;
  const decodedState = decodeURIComponent(state);
  
  const stateObj = getStateBySlug(decodedState.toLowerCase());
  
  if (!stateObj) {
    return { title: "Not Found" };
  }

  return {
    title: `Cars for Sale in ${stateObj.name} | Local Dealership Inventory`,
    description: `Search local dealership websites for new and used car inventory in ${stateObj.name}. Find the best deals near you.`,
    alternates: {
      canonical: `/locations/${stateObj.slug}`,
    },
  };
}

export default async function StatePage({ params }: Props) {
  const { state } = await params;
  const decodedState = decodeURIComponent(state);
  
  const stateObj = getStateBySlug(decodedState.toLowerCase());
  
  if (!stateObj) {
    notFound();
  }

  return (
    <Suspense>
      <SearchExperience initialCriteria={{ location: stateObj.name }} />
    </Suspense>
  );
}
