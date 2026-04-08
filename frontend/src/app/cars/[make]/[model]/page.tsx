import { Suspense } from "react";
import { notFound } from "next/navigation";
import { Metadata } from "next";

import { SearchExperience } from "@/components/SearchExperience";
import { getMakesForCategory, getModelsForMake } from "@/lib/vehicleCatalog";

type Props = {
  params: Promise<{ make: string; model: string }>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { make, model } = await params;
  const decodedMake = decodeURIComponent(make);
  const decodedModel = decodeURIComponent(model);
  
  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find(m => m.toLowerCase() === decodedMake.toLowerCase());
  
  if (!formattedMake) {
    return { title: "Not Found" };
  }

  const models = getModelsForMake("car", formattedMake, "us");
  const formattedModel = models.find(m => m.toLowerCase() === decodedModel.toLowerCase());

  if (!formattedModel) {
    return { title: "Not Found" };
  }

  return {
    title: `${formattedMake} ${formattedModel} Inventory | Local Dealership Search`,
    description: `Search local dealership websites for new and used ${formattedMake} ${formattedModel} inventory. Find the best deals on ${formattedMake} ${formattedModel} vehicles near you.`,
    alternates: {
      canonical: `/cars/${encodeURIComponent(formattedMake.toLowerCase())}/${encodeURIComponent(formattedModel.toLowerCase())}`,
    },
  };
}

export default async function MakeModelPage({ params }: Props) {
  const { make, model } = await params;
  const decodedMake = decodeURIComponent(make);
  const decodedModel = decodeURIComponent(model);
  
  const makes = getMakesForCategory("car", "us");
  const formattedMake = makes.find(m => m.toLowerCase() === decodedMake.toLowerCase());
  
  if (!formattedMake) {
    notFound();
  }

  const models = getModelsForMake("car", formattedMake, "us");
  const formattedModel = models.find(m => m.toLowerCase() === decodedModel.toLowerCase());

  if (!formattedModel) {
    notFound();
  }

  return (
    <Suspense>
      <SearchExperience initialCriteria={{ make: formattedMake, model: formattedModel }} />
    </Suspense>
  );
}
