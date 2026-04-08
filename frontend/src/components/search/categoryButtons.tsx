import type { JSX } from "react";

import type { VehicleCategory } from "@/lib/vehicleCatalog";

export const CATEGORY_BUTTONS: {
  value: VehicleCategory;
  label: string;
  icon: JSX.Element;
}[] = [
  {
    value: "car",
    label: "Cars",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5 5.4 8.8A2.5 2.5 0 0 1 7.64 7.5h8.72a2.5 2.5 0 0 1 2.24 1.3L21 13.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 13.5h16a1 1 0 0 1 1 1V17a1 1 0 0 1-1 1h-1.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 13.5a1 1 0 0 0-1 1V17a1 1 0 0 0 1 1h1.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 18H16.5" />
        <circle cx="7.5" cy="18" r="1.5" />
        <circle cx="16.5" cy="18" r="1.5" />
      </svg>
    ),
  },
  {
    value: "motorcycle",
    label: "Motorcycles",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
        <circle cx="6" cy="17" r="3" />
        <circle cx="18" cy="17" r="3" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17h3.5l2.5-5h-4l-2 2" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 7h2l2 3" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M10 9h4" />
      </svg>
    ),
  },
  {
    value: "boat",
    label: "Boats",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 14h16l-2.5 3.5a2 2 0 0 1-1.63.85H8.13a2 2 0 0 1-1.63-.85L4 14Z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v9" />
        <path strokeLinecap="round" strokeLinejoin="round" d="m12 6 4 2.5-4 2.5" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 20c1.2 0 1.2-.8 2.4-.8s1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8 1.2.8 2.4.8 1.2-.8 2.4-.8" />
      </svg>
    ),
  },
];
