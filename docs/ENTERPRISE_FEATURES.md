# Enterprise, dealer/broker, and custom licensing

This document scopes **contract-governed** tiers (`enterprise`, `custom`) that justify higher pricing than self-serve Standard/Premium.

**Relationship to self-serve:** Standard and Premium are sold via Stripe Checkout with limits in [`backend/app/tiers.py`](../backend/app/tiers.py). The next product priority for paid differentiation is **workflow automation** — saved searches, history, alerts, and scheduled runs — see [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md). Enterprise/custom builds on similar themes with **team workspace**, **contracted volume**, **SLAs**, and **integrations** (API, webhooks, white-label) under separate terms.

## Enterprise / dealer / broker (monthly contract)

**Buyer:** dealership groups, independent stores running daily acquisition, brokers sourcing regionally.

**Typical packaging:**

- **Pooled search volume** aligned to contract (not literal “unlimited” until unit economics are proven).
- **Seat-based access** (sales managers, buyers, BDC) with audit-friendly usage summaries.
- **Team workspace:** shared saved searches (see also roadmap for self-serve saved-search direction), territory presets, export policies.
- **Operational guarantees:** prioritized error handling, agreed support response times, optional private Slack/email channel.
- **Integration hooks:** CSV export scheduling, outbound webhooks to CRM/DMS (roadmap), IP allowlisting for API keys.
- **Compliance posture:** data processing terms, logging/retention options, regional deployment discussions.

**Pricing anchor:** custom MRR from roughly **\$750–\$1,500+/month** for a single rooftop or small group, scaling with seats, markets, and contracted monthly search pool. Negotiate overages explicitly in the contract.

## Custom / white-label / API (annual or multi-year)

**Buyer:** large groups, marketplaces, or vendors embedding inventory discovery in their own product.

**Capability themes:**

- **White-label UI** (your brand, your domain) with Motorscrape search and progress UX as a module.
- **REST or streaming API access** with stable auth (API keys, OAuth2 roadmap), documented rate limits, and SLAs.
- **Dedicated or VPC-style deployment** for customers who cannot share multi-tenant scraping egress.
- **Custom extractors and provider routes** for franchisor/OEM programs under a signed SOW.
- **Legal & terms:** DPA, BAA if applicable, indemnity carve-outs for target sites, and explicit acceptable-use policy.

**Pricing anchor:** annual contracts often **\$3k–\$10k+** for mid-size embeds, and **meaningfully higher** for OEM-scale API + SLA + dedicated infra. Always tie price to committed volume, branding depth, and support load.

## Implementation notes (this repo)

- Tiers `enterprise` and `custom` are enforced in [`backend/app/tiers.py`](../backend/app/tiers.py) with high technical ceilings; **commercial limits** should still be mirrored in a CRM or contract record.
- Stripe Checkout is aimed at **Standard/Premium** self-serve. Enterprise/custom should use **manual tier flags** in the accounts database (or a future admin tool) once billing is finalized offline. Example (SQLite):  
  `UPDATE users SET tier = 'enterprise' WHERE email = 'buyer@dealership.example';`
- For hybrid overages, Standard/Premium can attach a **metered Stripe price**; enterprise contracts may instead invoice net-30 without metered SKUs.
