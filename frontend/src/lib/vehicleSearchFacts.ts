import type { VehicleCategory } from "@/lib/vehicleCatalog";

export type SearchFactsInput = {
  make: string;
  model: string;
  vehicleCategory: VehicleCategory;
  vehicleCondition: string;
};

/** Primary model when user entered comma-separated models (first entry). */
function primaryModelToken(model: string): string {
  const first = model.split(",")[0]?.trim() ?? "";
  return first;
}

/**
 * Human phrase for the vehicle being searched, e.g. "Buick Enclave" or "Honda".
 * Avoids claiming specifics we don't know; used only for generic shopping tips.
 */
export function describeVehiclePhrase(make: string, model: string): string {
  const m = make.trim();
  const mod = primaryModelToken(model);
  if (m && mod) return `${m} ${mod}`;
  if (m) return m;
  return "the vehicles you're searching for";
}

function pushUnique(out: string[], line: string) {
  const t = line.trim();
  if (!t) return;
  if (!out.includes(t)) out.push(t);
}

/**
 * Rotating tips tied to the user's search criteria — general shopping guidance,
 * not inventory or specs (those come from scrape results).
 */
export function buildSearchWaitFacts(input: SearchFactsInput): string[] {
  const { make, model, vehicleCategory, vehicleCondition } = input;
  const phrase = describeVehiclePhrase(make, model);
  const out: string[] = [];

  if (vehicleCategory === "motorcycle") {
    pushUnique(out, `Helmet laws, insurance, and registration rules for motorcycles vary by state—worth confirming before you buy.`);
    pushUnique(out, `For ${phrase}, check service intervals and recall campaigns; dealers often list open campaigns on listings.`);
    pushUnique(out, `Compare out-the-door pricing on ${phrase}—dealer doc fees and freight vary widely.`);
    pushUnique(out, `If you're new to riding, a skills course and gear budget belong in the plan alongside the bike price.`);
  } else if (vehicleCategory === "boat") {
    pushUnique(out, `Trailering, storage, and winterization matter as much as the sticker on ${phrase}—factor them into your budget.`);
    pushUnique(out, `For ${phrase}, survey or sea trial when possible; hull and drivetrain condition beat glossy photos.`);
    pushUnique(out, `Title and registration rules for boats differ by state—verify paperwork before you commit.`);
    pushUnique(out, `Compare out-the-door pricing on ${phrase}—prep, freight, and dealer fees vary by seller.`);
  } else if (vehicleCategory === "other") {
    pushUnique(out, `Compare out-the-door quotes for ${phrase}—fees and add-ons vary by seller.`);
    pushUnique(out, `When listings for ${phrase} include options or packages, confirm they match what you want before visiting.`);
    pushUnique(out, `If you're financing ${phrase}, compare APR offers from your bank and the seller.`);
  } else {
    // car (catalog label: cars and trucks)
    pushUnique(
      out,
      `Compare out-the-door quotes on ${phrase}—taxes, fees, and incentives land differently at each dealership.`,
    );
    pushUnique(
      out,
      `When listings mention trim or packages for ${phrase}, confirm the equipment matches what you expect before you go in person.`,
    );
    pushUnique(
      out,
      `A test drive on the roads you use every day tells you more about ${phrase} than photos and spec sheets alone.`,
    );
    pushUnique(out, `If you're financing ${phrase}, compare APR offers from your bank or credit union with the dealer's rate.`);
    pushUnique(
      out,
      `Certified and warranty terms differ by brand—if a listing calls out CPO or coverage, verify what it includes for ${phrase}.`,
    );
  }

  if (vehicleCondition === "used") {
    pushUnique(
      out,
      `On used listings for ${phrase}, a vehicle history report helps explain title brands, accidents, and odometer patterns.`,
    );
    pushUnique(
      out,
      `For used ${phrase}, compare asking price to typical listings in your area so you recognize a strong deal when you see it.`,
    );
  } else if (vehicleCondition === "new") {
    pushUnique(
      out,
      `Factory incentives and dealer discounts on new ${phrase} often change month to month—confirm what's available now.`,
    );
    pushUnique(out, `On new ${phrase}, watch for add-ons in the finance office—you can decline products you don't want.`);
  } else {
    pushUnique(
      out,
      `Whether new or used, ${phrase} listings may omit fees—ask for an out-the-door number, not just the advertised price.`,
    );
  }

  pushUnique(
    out,
    `When you compare ${phrase}, weigh total cost of ownership—not just the monthly payment.`,
  );
  pushUnique(out, `Dealers update inventory frequently—if ${phrase} doesn't appear yet, similar stock may still be arriving.`);

  return out;
}
