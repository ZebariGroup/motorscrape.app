import { Suspense } from "react";

import { SearchExperience } from "@/components/SearchExperience";

export default function Home() {
  return (
    <Suspense>
      <SearchExperience />
    </Suspense>
  );
}
