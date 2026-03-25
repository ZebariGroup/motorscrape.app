/**
 * Build a short location string for search from a Nominatim `address` object.
 * @see https://nominatim.org/release-docs/latest/api/Output/
 */
export function buildLocationLabelFromNominatimAddress(
  address: Record<string, string | undefined> | null | undefined,
): string | null {
  if (!address || typeof address !== "object") return null;

  const city =
    address.city ||
    address.town ||
    address.village ||
    address.hamlet ||
    address.municipality ||
    address.county;

  const state = address.state?.trim();
  const postcode = address.postcode?.trim();
  const country = (address.country_code || "").toLowerCase();

  if (country === "us" || country === "ca" || country === "au") {
    if (city && state) return `${city}, ${state}`;
    if (postcode && state) return `${postcode}, ${state}`;
    if (postcode) return postcode;
  }

  if (city && state) return `${city}, ${state}`;
  if (city) return city;
  if (postcode) return postcode;
  if (state) return state;

  return null;
}
