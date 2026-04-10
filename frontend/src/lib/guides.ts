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
  {
    slug: "best-time-to-buy-a-car",
    title: "The Best Time to Buy a Car: Month-End, Quarter-End, and Year-End Strategies",
    description: "Dealership salespeople have quotas. Learn exactly when to walk in the door to get the lowest price, and how to use inventory data to confirm whether timing is actually working in your favor.",
    publishedAt: "2026-04-09T00:00:00Z",
    author: "Motorscrape Team",
    content: `
Timing is one of the most underrated levers in car buying. Dealerships operate on monthly, quarterly, and annual sales quotas, and those deadlines create predictable windows where buyers hold considerably more power than usual. Here is how to identify and take advantage of them.

## Why Quotas Create Deals

Manufacturers reward dealerships with significant bonuses — sometimes thousands of dollars per vehicle — for hitting volume targets. When a dealer is a few sales short of their monthly or quarterly goal, they will often cut into their own profit margin to close the deal. That cost savings gets passed to you.

The end of the month is the most reliable window. The last two to three business days of any month are historically when dealers are most aggressive. Quarter-end months — March, June, September, and December — are even stronger because two quotas (monthly and quarterly) expire simultaneously. December is the single best month of the year because monthly, quarterly, and annual incentives all converge.

## How to Confirm Timing Is Working

Knowing the calendar is only half the battle. You also need to confirm that the specific inventory you want has been sitting long enough for the dealer to feel the pressure. A car that arrived on the lot three days ago is unlikely to move much on price regardless of what month it is.

Use Motorscrape to check days-on-lot for any vehicle you are considering. If the car has been sitting for 45 days or more and you are also shopping during the last week of a quota month, you have two independent pressure points working in your favor at the same time.

## Weekday vs. Weekend

Walk in on a Tuesday, Wednesday, or Thursday afternoon if you can. Weekends are high-traffic and salespeople have little incentive to work harder for your business when the showroom is full. A slow weekday afternoon gives you far more of a salesperson's undivided attention, and a quieter sales floor means managers are more likely to approve an aggressive counter-offer just to move a unit.

## Model-Year Changeovers

When a new model year begins arriving at the lot — typically late summer through fall for most brands — outgoing-year vehicles become a liability for the dealer. They cannot be sold as "new" for full price once the new year hits. Watch Motorscrape for older model-year vehicles that are suddenly appearing in large numbers across multiple dealerships in your area. This pattern almost always signals that regional inventory is being cleared, and prices follow shortly after.

## New Model Launches

The inverse also applies. If a highly anticipated new model or redesign is dropping soon, dealers may have pre-sold allocations and are less motivated to discount the current version. Avoid buying a model in its final few months before a confirmed redesign unless you are specifically searching for value on the outgoing version.

## Putting It Together

The most effective approach is to combine calendar timing with live inventory data. Identify the car you want, check its days-on-lot through Motorscrape to verify it has been sitting long enough to create urgency for the dealer, and then schedule your visit during the last three business days of a quarter-end month. Showing up with a competing price from another dealership in the same metro area — also visible through Motorscrape — gives you one more data point to anchor the negotiation.
    `,
  },
  {
    slug: "how-to-negotiate-a-car-price",
    title: "How to Negotiate a Car Price: A Data-Driven Playbook",
    description: "Most buyers leave thousands of dollars on the table. This step-by-step negotiation guide shows you how to use real inventory data, market medians, and competing offers to pay less for your next car.",
    publishedAt: "2026-04-09T00:00:00Z",
    author: "Motorscrape Team",
    content: `
Negotiating a car price is uncomfortable for most people — and dealerships know it. The good news is that data almost entirely removes the emotional friction. When you walk in with concrete numbers pulled from live inventory, you are no longer guessing. Here is a repeatable process that works.

## Step 1: Know the Market Median Before You Call Anyone

Before you contact a single dealership, run a Motorscrape search for the exact year, make, model, and trim you want across your metro area. Note the price distribution. If five dealerships are asking between $32,000 and $34,500 for the same trim, that range is your real market. Any single dealer's sticker price is just their opening position within that range, not a fixed fact.

Your target should be at or below the median of the live local market — not the MSRP, not the sticker, not what a dealer's website displays as a "sale" price. Real-time inventory data anchors the conversation in fact.

## Step 2: Identify Motivated Sellers Using Days-on-Lot

A dealer asking $33,800 for a car that arrived last week is very different from a dealer asking $33,800 for the same car that has been on the lot for 72 days. The second dealer is paying floor plan interest every day that vehicle sits unsold. That carrying cost is your leverage.

Filter your Motorscrape search to surface vehicles with 60 or more days on the lot. When you contact that dealership, you already know they have reason to negotiate. You do not need to mention the days-on-lot figure directly — simply asking "what's the best price you can do today?" is often enough to surface a motivated response.

## Step 3: Get Competing Quotes in Writing

Email three to five dealerships with identical inventory for the vehicle you want. Ask each one: "I'm ready to purchase this week. What is your out-the-door price?" You are not negotiating yet — you are collecting data points.

Once you have responses, you have a real competing offer. At that point, you can go back to your preferred dealership and say: "I have a written quote for $31,200 out the door from another dealer 30 miles away for the same vehicle. Can you match or beat it?" Most dealers would rather close the sale than let you drive to a competitor.

## Step 4: Negotiate the Out-the-Door Price, Not the Monthly Payment

One of the most common negotiation mistakes is focusing on monthly payment instead of total price. A dealership can make almost any monthly payment work by adjusting the loan term — stretching your loan to 84 months, for example, makes a $35,000 car feel like $450 per month. But you are paying for that car for seven years.

Always negotiate the out-the-door price first. That number includes the vehicle price, all dealer fees, and taxes. Once you agree on that total, then discuss financing. If you have already been pre-approved by your bank or credit union, you have a second point of leverage because you can walk away from dealer financing entirely.

## Step 5: Be Willing to Walk Away

The single most powerful thing you can do in any negotiation is leave. If a dealership will not move to a price that reflects the market data you have gathered, thank them for their time and walk out. In most cases, you will receive a follow-up call within 24 to 48 hours with a better number. Dealers rarely let a serious, prepared buyer leave permanently.

Motorscrape makes it easy to monitor whether the same vehicle drops in price over the following days or whether a competing dealership has restocked with a better option. You do not have to accept any single offer — the data shows you exactly what the market will bear.

## What Not to Do

* Do not reveal your maximum budget before agreeing on a price.
* Do not accept add-ons like paint protection, nitrogen tire fills, or extended warranties at the finance desk without researching their value independently.
* Do not assume a "dealer discount" off MSRP is a good deal — compare to the live market, not to the manufacturer's suggested retail price.
* Do not let urgency pressure you. "This car will be gone tomorrow" is almost never true when you can see the same trim available at four other dealerships in your search results.
    `,
  },
];

export function getGuideBySlug(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}
