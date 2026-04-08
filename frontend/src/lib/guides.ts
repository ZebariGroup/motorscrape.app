export type Guide = {
  slug: string;
  title: string;
  description: string;
  content: string; // Markdown or HTML string
  publishedAt: string;
  author: string;
};

export const GUIDES: Guide[] = [
  {
    slug: "how-to-find-local-car-deals",
    title: "How to Find the Best Local Car Deals in 2026",
    description: "A comprehensive guide on tracking dealership inventory, spotting price drops, and negotiating the best deal on your next vehicle.",
    publishedAt: "2026-04-08T00:00:00Z",
    author: "Motorscrape Team",
    content: `
Finding a great deal on a car requires patience, research, and the right tools. Dealerships constantly adjust their prices based on time on the lot, market demand, and end-of-month quotas.

## 1. Track Days on Lot
The longer a vehicle sits on a dealer's lot, the more motivated they are to sell it. Floor plan financing costs dealerships money for every day a car goes unsold. By using tools like Motorscrape to track the "Days on Lot" metric, you can identify vehicles that have been sitting for 60+ days. These are prime candidates for negotiation.

## 2. Monitor Price Drops
Dealerships often systematically reduce prices on aging inventory. If you find a vehicle you like, don't buy it immediately. Save the search and monitor the price history. If you see a pattern of price drops, you might be able to negotiate an even lower price by making an offer just below the current asking price.

## 3. Look for "In-Transit" Inventory
Many buyers only look at what's currently sitting on the lot. However, dealerships often have vehicles "In-Transit" from the factory. If you're willing to wait a few weeks, you can sometimes secure a better deal on an incoming vehicle, especially if it helps the dealer hit a future sales target.

## 4. Expand Your Search Radius
Don't limit yourself to the dealership down the street. Expanding your search radius by just 50 miles can reveal significantly better deals or more inventory options. Motorscrape allows you to search across multiple dealerships simultaneously, making it easy to compare prices across a wider geographic area.

## 5. Understand Market Valuation
Always compare the asking price to the local market median. If a car is priced 5% above the market average, you have strong leverage to negotiate it down. Conversely, if a car is already priced 5% below market, it might be a "Great Deal" that won't last long.
    `,
  },
  {
    slug: "understanding-dealership-inventory-status",
    title: "Understanding Dealership Inventory: In-Transit vs. On-Lot",
    description: "What does it mean when a car is listed as 'In-Transit' or 'Built'? Learn how to decode dealership inventory statuses.",
    publishedAt: "2026-04-05T00:00:00Z",
    author: "Motorscrape Team",
    content: `
When browsing dealership websites, you'll often encounter various inventory statuses. Understanding what these mean can give you an edge in your car buying journey.

## On-Lot (Available Now)
These vehicles are physically present at the dealership and ready for a test drive. They are the most straightforward to purchase, but they also incur holding costs for the dealer. If an "On-Lot" vehicle has been there for a long time, the dealer may be highly motivated to negotiate.

## In-Transit
An "In-Transit" vehicle has been built by the manufacturer and is currently being shipped to the dealership. This process can take anywhere from a few days to several weeks. 
*   **Why it matters:** You can often reserve or put a deposit on an in-transit vehicle before it arrives. This is a great way to secure a specific trim or color without having to compromise on what's currently available on the lot.

## Built (Awaiting Shipment)
The vehicle has rolled off the assembly line but hasn't yet been loaded onto a train or truck for delivery. The wait time here is longer than "In-Transit" and can be unpredictable due to logistics delays.

## Dealer Ordered
The dealership has placed an order for this vehicle, but it hasn't been built yet. These listings are often used to gauge customer interest or to pre-sell high-demand models.

## How Motorscrape Helps
Motorscrape allows you to filter your search by inventory scope. You can choose to see "All" inventory, or restrict your search to "On-Lot Only" if you need a car immediately. If you're planning ahead, including "In-Transit" vehicles gives you the widest selection of options.
    `,
  },
];

export function getGuideBySlug(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}
