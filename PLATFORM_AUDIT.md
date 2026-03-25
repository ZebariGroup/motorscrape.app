# Platform Audit

## Goal

Move from one-off dealer fixes to reusable inventory stack support across major dealer platform families and OEM-adjacent site families.

This audit is based on a mix of:

- live backend fetch and extraction traces run inside `backend/.venv`
- direct page inspection against real dealer inventory URLs
- recurring URL, pagination, and markup patterns

## Current Code Entities

The app already recognizes these website-platform entities:

- `dealer_dot_com`
- `dealer_on`
- `dealer_inspire`
- `cdk_dealerfire`
- `team_velocity`
- `fusionzone`
- `shift_digital`
- `purecars`
- `jazel`

Those are useful, but they are not enough by themselves. Some dealer families need deeper stack support at the inventory behavior level, not just the homepage platform-fingerprint level.

## Current Support Matrix

| Stack / Entity | Type | Current status | Sample dealers | Core routing rule | Pagination behavior | Primary extraction source | Common failure signature |
|---|---|---|---|---|---|---|---|
| `dealer_dot_com` | Website platform | Active | BMW of Farmington Hills, Golling Toyota, Crestview Cadillac | Prefer exact model pages when exposed; otherwise normalize to clean `?model=...` routes | Currently strong on page 1; deeper API pagination still a gap on some sites | embedded inventory JSON, widget APIs, JSON-LD | broad `index.htm` routes undercount; widget APIs 403 without the right shape |
| `dealer_on` | Website platform | Active | Avis Ford, Folsom Chevrolet, K&S Acura | Keep generic `searchnew.aspx` / `searchused.aspx` when no model is specified; avoid promo/query hijacks | HTML page links like `?pt=2` exist; can follow page-based pagination | rendered DOM cards, text extraction, VDP links | wrong route picked from promo links like `?q=` or `ModelAndTrim=` |
| `dealer_inspire` | Website platform | Partial | Bill Brown Ford, Moore Cadillac | Often needs exact inventory entrypoint or rendered page | Mixed; weak where pages are blocked or app-shell only | DOM card payloads or thin JSON | direct/ZenRows blocking or thin rendered shells |
| `nissan_infiniti_inventory` | Family inventory stack | Active | INFINITI of Naperville | Stay on model-family SRP like `new-infiniti-qx-60-for-sale-*` | Explicit `?page=2/3/4`; forced deeper crawl | direct HTML card text + VDP links | undercounts if pagination is not followed |
| `honda_acura_inventory` | Family inventory stack | Active | Honda of Downtown Chicago, K&S Acura, Hudson Honda | Synthesize `/inventory/new/{make}/{model}` when broad `/inventory/new` undercounts | Explicit `?page=2`; deeper crawl enabled | `viewdetails` cards + visible price/VIN text | broad inventory hint returns only a few model-family rows |
| `hyundai_inventory_search` | Family inventory stack | Active | Chapman Hyundai | Use `/search/new/...` result pages and `/detail/new/...` VDP links | Page behavior still to be expanded if needed | anchor text in search result cards + detail links | no extraction under generic parser despite obvious inline data |
| `kia_inventory` | Family inventory stack | Active | Emich Kia, Kia of Puyallup, Serra Kia | Use `viewdetails` style inventory, but keep brand-gated detection | Some sites expose `?page=2`; crawl override enabled | `si-vehicle-box` card text + VDP links | malformed homepage inventory URLs and cross-family misclassification without host gating |

## Implemented Family / Vendor Rules

### Route preference rules already in code

- Prefer exact BMW model inventory pages on `dealer_dot_com` when exposed.
- Normalize malformed dealer homepage links like `index.htm&make=...` to `index.htm?make=...`.
- Strip stale `gvBodyStyle`, `make`, and `search` query keys from dealer.com model routes before rebuilding the final query.
- For Honda / Acura, synthesize model-specific paths like `/inventory/new/honda/civic` when the generic inventory root undercounts results.
- For DealerOn, keep the generic `searchnew.aspx` page when the user did not ask for a specific model and penalize promo/query links such as:
  - `?q=...`
  - `Model=...`
  - `ModelAndTrim=...`
  - `year=...`

### Detection rules already in code

- Brand-family stacks are host- and URL-gated so used inventory pages mentioning many brands do not drift into the wrong family stack.
- Inventory pages can re-fingerprint after homepage fetch so a vague homepage platform guess can be replaced by a stronger inventory-page stack match.

## Current Confidence Levels

| Area | Confidence | Why |
|---|---|---|
| `dealer_dot_com` page 1 extraction | High | Multiple brands and dealers already working with structured JSON and route cleanup |
| `dealer_dot_com` deep pagination | Medium | API shape is known, but some dealers still expose only the first slice unless we synthesize deeper requests |
| `dealer_on` generic new-inventory routing | Medium-high | Major route hijack bugs are understood; still needs more GM-family hardening |
| `dealer_inspire` broad reliability | Medium-low | Some sites work well, but blocking and thin shells still show up on important dealers |
| Nissan / INFINITI family | High | Direct HTML and explicit pagination pattern already verified |
| Honda / Acura family | Medium-high | Shared card pattern is strong, but some dealers still need broad-vs-model route tuning |
| Hyundai family | Medium | First stack works on Chapman-style pages, but family breadth is not yet measured |
| Kia family | Medium | Detection is cleaner now, but should be validated across more dealer groups |

## Failure Signature Matrix

| Failure signature | Likely category | Typical fix direction |
|---|---|---|
| `0 results` but dealer site clearly shows inventory | wrong inventory route | prefer exact model page, strip stale query keys, avoid promo paths |
| First few listings appear but not full site count | pagination gap | follow `?page=2` or synthesize deeper API/stateful requests |
| Listings have VIN and image but no price or mileage | thin card / partial DOM | parse alternate card payloads or enrich from structured API fields |
| Site homepage works, inventory page 403/404s | bad route shape or bot-sensitive route | normalize route format, prefer another exposed inventory entrypoint |
| Site only works on a direct model page, not broad inventory | family path issue | synthesize model-specific family path |
| Correct platform guessed, wrong inventory still chosen | route selection issue | add platform-level scoring/routing rules before parser changes |
| Dealer results vary wildly inside same metro | dealer discovery fine, routing mixed | inspect homepage links and inventory hints for that metro cluster |

## Priority Queue

1. Finish `dealer_dot_com` deeper pagination for first-page-only sites, especially Cadillac-like inventory counts.
2. Continue hardening `dealer_on` route selection and pagination for GM-family stores.
3. Improve `dealer_inspire` reliability where direct and managed fetches split badly on VDP/SRP pages.
4. Expand validation of `hyundai_inventory_search` and `kia_inventory` across additional dealer groups.
5. Decide whether VW belongs in the shared `viewdetails / inventory_listing` family alias set or deserves its own named stack.

## Family Findings

### Ford / Lincoln

#### Observed examples

- `Avis Ford`
- `Bill Brown Ford`
- `Westfield Ford`
- `Pat Milliken Ford`

#### Repeating patterns

- DealerOn-style SRPs can require rendered fetches and model-path-aware routing.
- Some Ford-family sites expose rich data in alternate card markup instead of classic `.vehicle-card` layouts.
- Some sites have exact model pages and adjacent variant pages that compete with each other:
  - `f-150`
  - `f-150-lightning`
- Some dealers expose thin list data on the SRP but full pricing/details in rendered card payloads or VDP pages.

#### Stack-level needs

- exact model-path routing
- richer card payload extraction
- rendered fetch preference for thin or partial direct HTML
- variant disambiguation for models with closely named EV or specialty versions

#### Candidate entity

- `ford_family_inventory`

This is not a replacement for platform detection. It is a higher-level inventory behavior entity that can sit on top of `dealer_on`, `dealer_inspire`, and similar stacks when Ford-specific routing ambiguity exists.

### Toyota / Lexus

#### Observed examples

- `Golling Toyota`
- `Lexus of Maplewood`
- `Gateway Toyota`
- `Toyota.com` dealer locality inventory pages

#### Repeating patterns

- Dealer.com is very common in Toyota / Lexus franchise inventory.
- Some Dealer.com pages return thin SSR shells unless you call the widget inventory API correctly.
- The widget API often requires `params=...` from page config, not just a bare `getInventory` URL.
- Some Toyota pages are OEM-first and route into Toyota.com inventory flows instead of classic dealer DMS listings.

#### Stack-level needs

- Dealer.com widget config extraction
- widget-param-aware inventory API enrichment
- merging richer duplicate records instead of keeping the first thin one
- support for OEM inventory hub pages as a distinct family from dealer SRPs

#### Candidate entities

- `dealer_dot_com_widget_inventory`
- `toyota_lexus_oem_inventory`

### Nissan / INFINITI

#### Observed examples

- `INFINITI of Naperville`

#### Repeating patterns

- The inventory pages are very parseable from direct HTML.
- Prices, VINs, stock numbers, and titles are present in plain page content.
- Pagination is explicit and URL-driven:
  - `?page=1`
  - `?page=2`
  - `?page=3`
  - `?page=4`
- The generic platform fingerprint is not enough to explain the inventory behavior.
- This feels more like an OEM-adjacent inventory family than one of the major dealer website platforms.

#### Stack-level needs

- deterministic pagination support
- preserving page-level filters across pagination
- better family-level classification than current generic fallback buckets
- model and trim family routing for URLs like `new-infiniti-qx-60-for-sale-*`

#### Candidate entity

- `nissan_infiniti_inventory`

### Honda / Acura

#### Observed examples

- `Hudson Honda`
- `Bell Honda Express`
- `Acura of Pleasanton`
- `Schaller Acura`

#### Repeating patterns

- There are at least two distinct stack classes:
  - classic dealer SRPs
  - `express.*` digital retail sites
- Dealer.com is still common for Acura.
- Some Honda-family flows push users toward digital retail or finance-first experiences that are heavier on client-side rendering.
- VIN may live in VDP URLs or linked assets rather than a plainly labeled SRP field.

#### Stack-level needs

- separate handling for `express.*` digital retail properties
- support for mixed used / certified branches
- URL-derived VIN recovery
- fallback from thin SRP markup to richer VDP routing when needed

#### Candidate entities

- `honda_acura_express_inventory`
- `dealer_dot_com_vin_from_url`

## Immediate Conclusions

### What is working

- platform fingerprinting is already paying off
- dealer.com support is materially better after widget-param and merge fixes
- DealerOn and alternate card layouts can be hardened incrementally

### What is still missing

- family-level stack entities above plain homepage platform detection
- pagination for OEM-adjacent inventory families
- better variant routing for closely named models
- support for alternate card payloads across more dealer families

## Recommended Next Implementation Order

1. Build `nissan_infiniti_inventory` as the next dedicated family stack.
   It has clear pagination and strong direct HTML extraction.

2. Add multi-page crawling for paginated family SRPs.
   This should preserve existing filters and avoid re-routing to a broader unfiltered page.

3. Expand family routing rules for exact model slugs.
   Keep exact model pages ahead of related EV or specialty variants.

4. Audit GM and Hyundai / Kia / Genesis next.
   These are large enough to justify dedicated stack entities if repeated patterns emerge.

5. Keep dealer-specific fixes only as a last resort.
   If two or more dealers on the same family behave similarly, promote the logic into a reusable stack.

## How Manual Testing Should Work

Manual testing is still valuable, but only as targeted input.

Good user-provided test cases:

- exact dealer inventory URLs
- screenshots showing the website count vs app count
- examples where the wrong model family is selected
- examples where page 1 is correct but later pages are missing
- examples where VDP has price/details but SRP output is thin

What should not be manual:

- reverse-engineering every platform family
- deciding which parser entities to create
- classifying vendor behavior across multiple dealers

That part should come from this audit and from repeated backend traces.

## Proposed New Entities

- `ford_family_inventory`
- `dealer_dot_com_widget_inventory`
- `toyota_lexus_oem_inventory`
- `nissan_infiniti_inventory`
- `honda_acura_express_inventory`
- `dealer_dot_com_vin_from_url`

These are candidate behavior-level entities, not necessarily one-to-one replacements for the current platform registry.
