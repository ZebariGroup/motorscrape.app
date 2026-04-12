/**
 * Shared constants for the dealer directory: states and makes with URL slugs.
 */

export type StateEntry = {
  abbr: string;
  name: string;
  slug: string;
};

export type MakeEntry = {
  name: string;
  slug: string;
};

export const ALL_STATES: StateEntry[] = [
  { abbr: "AL", name: "Alabama", slug: "alabama" },
  { abbr: "AK", name: "Alaska", slug: "alaska" },
  { abbr: "AZ", name: "Arizona", slug: "arizona" },
  { abbr: "AR", name: "Arkansas", slug: "arkansas" },
  { abbr: "CA", name: "California", slug: "california" },
  { abbr: "CO", name: "Colorado", slug: "colorado" },
  { abbr: "CT", name: "Connecticut", slug: "connecticut" },
  { abbr: "DE", name: "Delaware", slug: "delaware" },
  { abbr: "FL", name: "Florida", slug: "florida" },
  { abbr: "GA", name: "Georgia", slug: "georgia" },
  { abbr: "HI", name: "Hawaii", slug: "hawaii" },
  { abbr: "ID", name: "Idaho", slug: "idaho" },
  { abbr: "IL", name: "Illinois", slug: "illinois" },
  { abbr: "IN", name: "Indiana", slug: "indiana" },
  { abbr: "IA", name: "Iowa", slug: "iowa" },
  { abbr: "KS", name: "Kansas", slug: "kansas" },
  { abbr: "KY", name: "Kentucky", slug: "kentucky" },
  { abbr: "LA", name: "Louisiana", slug: "louisiana" },
  { abbr: "ME", name: "Maine", slug: "maine" },
  { abbr: "MD", name: "Maryland", slug: "maryland" },
  { abbr: "MA", name: "Massachusetts", slug: "massachusetts" },
  { abbr: "MI", name: "Michigan", slug: "michigan" },
  { abbr: "MN", name: "Minnesota", slug: "minnesota" },
  { abbr: "MS", name: "Mississippi", slug: "mississippi" },
  { abbr: "MO", name: "Missouri", slug: "missouri" },
  { abbr: "MT", name: "Montana", slug: "montana" },
  { abbr: "NE", name: "Nebraska", slug: "nebraska" },
  { abbr: "NV", name: "Nevada", slug: "nevada" },
  { abbr: "NH", name: "New Hampshire", slug: "new-hampshire" },
  { abbr: "NJ", name: "New Jersey", slug: "new-jersey" },
  { abbr: "NM", name: "New Mexico", slug: "new-mexico" },
  { abbr: "NY", name: "New York", slug: "new-york" },
  { abbr: "NC", name: "North Carolina", slug: "north-carolina" },
  { abbr: "ND", name: "North Dakota", slug: "north-dakota" },
  { abbr: "OH", name: "Ohio", slug: "ohio" },
  { abbr: "OK", name: "Oklahoma", slug: "oklahoma" },
  { abbr: "OR", name: "Oregon", slug: "oregon" },
  { abbr: "PA", name: "Pennsylvania", slug: "pennsylvania" },
  { abbr: "RI", name: "Rhode Island", slug: "rhode-island" },
  { abbr: "SC", name: "South Carolina", slug: "south-carolina" },
  { abbr: "SD", name: "South Dakota", slug: "south-dakota" },
  { abbr: "TN", name: "Tennessee", slug: "tennessee" },
  { abbr: "TX", name: "Texas", slug: "texas" },
  { abbr: "UT", name: "Utah", slug: "utah" },
  { abbr: "VT", name: "Vermont", slug: "vermont" },
  { abbr: "VA", name: "Virginia", slug: "virginia" },
  { abbr: "WA", name: "Washington", slug: "washington" },
  { abbr: "WV", name: "West Virginia", slug: "west-virginia" },
  { abbr: "WI", name: "Wisconsin", slug: "wisconsin" },
  { abbr: "WY", name: "Wyoming", slug: "wyoming" },
];

export const POPULAR_MAKES: MakeEntry[] = [
  { name: "Acura", slug: "acura" },
  { name: "Alfa Romeo", slug: "alfa-romeo" },
  { name: "Audi", slug: "audi" },
  { name: "BMW", slug: "bmw" },
  { name: "Buick", slug: "buick" },
  { name: "Cadillac", slug: "cadillac" },
  { name: "Chevrolet", slug: "chevrolet" },
  { name: "Chrysler", slug: "chrysler" },
  { name: "Dodge", slug: "dodge" },
  { name: "Ford", slug: "ford" },
  { name: "Genesis", slug: "genesis" },
  { name: "GMC", slug: "gmc" },
  { name: "Honda", slug: "honda" },
  { name: "Hyundai", slug: "hyundai" },
  { name: "Infiniti", slug: "infiniti" },
  { name: "Jeep", slug: "jeep" },
  { name: "Kia", slug: "kia" },
  { name: "Land Rover", slug: "land-rover" },
  { name: "Lexus", slug: "lexus" },
  { name: "Lincoln", slug: "lincoln" },
  { name: "Mazda", slug: "mazda" },
  { name: "Mercedes-Benz", slug: "mercedes-benz" },
  { name: "Mitsubishi", slug: "mitsubishi" },
  { name: "Nissan", slug: "nissan" },
  { name: "Porsche", slug: "porsche" },
  { name: "RAM", slug: "ram" },
  { name: "Subaru", slug: "subaru" },
  { name: "Tesla", slug: "tesla" },
  { name: "Toyota", slug: "toyota" },
  { name: "Volkswagen", slug: "volkswagen" },
  { name: "Volvo", slug: "volvo" },
];

export function stateBySlug(slug: string): StateEntry | undefined {
  return ALL_STATES.find((s) => s.slug === slug);
}

export function makeBySlug(slug: string): MakeEntry | undefined {
  return POPULAR_MAKES.find((m) => m.slug === slug);
}
