import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { getMakesForCategory } from "@/lib/vehicleCatalog";

type Props = {
  params: Promise<{ make: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { make } = await params;
  const decodedMake = decodeURIComponent(make);
  
  // Basic validation
  const makes = getMakesForCategory("car", "us");
  const isValid = makes.some(m => m.toLowerCase() === decodedMake.toLowerCase());
  
  if (!isValid) {
    return { title: "Not Found" };
  }

  const formattedMake = makes.find(m => m.toLowerCase() === decodedMake.toLowerCase()) || decodedMake;

  return {
    title: `${formattedMake} Inventory | Local Dealership Search`,
    description: `Search local dealership websites for new and used ${formattedMake} inventory. Find the best deals on ${formattedMake} vehicles near you.`,
    alternates: {
      canonical: `/cars/${encodeURIComponent(formattedMake.toLowerCase())}`,
    },
  };
}

export default async function MakePage({ params }: Props) {
  const { make } = await params;
  const decodedMake = decodeURIComponent(make);
  
  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find(m => m.toLowerCase() === decodedMake.toLowerCase());
  
  if (!formattedMake) {
    notFound();
  }

  return (
    <Suspense>
      <SearchExperience initialCriteria={{ make: formattedMake }} />
    </Suspense>
  );
}
