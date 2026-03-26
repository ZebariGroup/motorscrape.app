# Product roadmap (priorities)

This document tracks **prioritized** product direction. Limits and tier semantics remain the source of truth in [`backend/app/tiers.py`](../backend/app/tiers.py).

## Next: paid workflow differentiation (self-serve Standard / Premium)

**Priority:** Ship **saved searches**, **search history**, **email alerts**, and **scheduled or recurring runs** as the main paid upgrade story beyond raw search volume.

These features differentiate Motorscrape for repeat buyers and operators who need persistence and automation, not one-off scrapes. They align with the team-oriented themes in [`ENTERPRISE_FEATURES.md`](ENTERPRISE_FEATURES.md) (shared saved searches, scheduling) at a lighter self-serve scope first.

**Dependencies (implementation):** durable account storage (SQLite / Supabase), authenticated APIs, a scheduler or cron trigger for recurring runs, and transactional email (e.g. Resend or similar). See repository issues or internal task tracking for delivery status.

## Messaging alignment

Upgrade copy in the app should stay aligned with `tiers.py`:

- **Standard** emphasizes **CSV export**, **concurrent searches**, **higher monthly pool**, and a **tighter max radius (30 mi)** vs Free — intentional “focused local runs” positioning.
- **Premium** adds **wider radius (up to 250 mi)**, **more dealerships per run**, **higher concurrency**, and a **larger monthly pool**.
- Both Standard and Premium include **advanced inventory scope** (`inventory_scope_premium`); do not describe that as Premium-only.

## Enterprise / custom

Contract tiers (`enterprise`, `custom`) remain scoped in [`ENTERPRISE_FEATURES.md`](ENTERPRISE_FEATURES.md). When adding integrations (webhooks, API, white-label), update that document so sales narrative and technical ceilings stay consistent.
