export type State = {
  abbr: string;
  name: string;
  slug: string;
};

export type City = {
  name: string;
  slug: string;
  stateAbbr: string;
};

// Top 10 US States by population for initial programmatic SEO rollout
export const TOP_STATES: State[] = [
  { abbr: "CA", name: "California", slug: "california" },
  { abbr: "TX", name: "Texas", slug: "texas" },
  { abbr: "FL", name: "Florida", slug: "florida" },
  { abbr: "NY", name: "New York", slug: "new-york" },
  { abbr: "PA", name: "Pennsylvania", slug: "pennsylvania" },
  { abbr: "IL", name: "Illinois", slug: "illinois" },
  { abbr: "OH", name: "Ohio", slug: "ohio" },
  { abbr: "GA", name: "Georgia", slug: "georgia" },
  { abbr: "NC", name: "North Carolina", slug: "north-carolina" },
  { abbr: "MI", name: "Michigan", slug: "michigan" },
];

// Top cities in those states
export const TOP_CITIES: City[] = [
  // California
  { name: "Los Angeles", slug: "los-angeles", stateAbbr: "CA" },
  { name: "San Diego", slug: "san-diego", stateAbbr: "CA" },
  { name: "San Jose", slug: "san-jose", stateAbbr: "CA" },
  { name: "San Francisco", slug: "san-francisco", stateAbbr: "CA" },
  // Texas
  { name: "Houston", slug: "houston", stateAbbr: "TX" },
  { name: "San Antonio", slug: "san-antonio", stateAbbr: "TX" },
  { name: "Dallas", slug: "dallas", stateAbbr: "TX" },
  { name: "Austin", slug: "austin", stateAbbr: "TX" },
  // Florida
  { name: "Jacksonville", slug: "jacksonville", stateAbbr: "FL" },
  { name: "Miami", slug: "miami", stateAbbr: "FL" },
  { name: "Tampa", slug: "tampa", stateAbbr: "FL" },
  { name: "Orlando", slug: "orlando", stateAbbr: "FL" },
  // New York
  { name: "New York", slug: "new-york", stateAbbr: "NY" },
  { name: "Buffalo", slug: "buffalo", stateAbbr: "NY" },
  // Pennsylvania
  { name: "Philadelphia", slug: "philadelphia", stateAbbr: "PA" },
  { name: "Pittsburgh", slug: "pittsburgh", stateAbbr: "PA" },
  // Illinois
  { name: "Chicago", slug: "chicago", stateAbbr: "IL" },
  // Ohio
  { name: "Columbus", slug: "columbus", stateAbbr: "OH" },
  { name: "Cleveland", slug: "cleveland", stateAbbr: "OH" },
  { name: "Cincinnati", slug: "cincinnati", stateAbbr: "OH" },
  // Georgia
  { name: "Atlanta", slug: "atlanta", stateAbbr: "GA" },
  // North Carolina
  { name: "Charlotte", slug: "charlotte", stateAbbr: "NC" },
  { name: "Raleigh", slug: "raleigh", stateAbbr: "NC" },
  // Michigan
  { name: "Detroit", slug: "detroit", stateAbbr: "MI" },
  { name: "Grand Rapids", slug: "grand-rapids", stateAbbr: "MI" },
];

export function getStateBySlug(slug: string): State | undefined {
  return TOP_STATES.find(s => s.slug === slug);
}

export function getCitiesByState(stateAbbr: string): City[] {
  return TOP_CITIES.filter(c => c.stateAbbr === stateAbbr);
}

export function getCityBySlug(stateAbbr: string, citySlug: string): City | undefined {
  return TOP_CITIES.find(c => c.stateAbbr === stateAbbr && c.slug === citySlug);
}
