/**
 * Marketing bullets aligned with backend tier limits in `backend/app/tiers.py`.
 * Update both when limits change.
 */

export const STANDARD_BULLETS = [
  "25 included searches / month",
  "Up to 10 dealerships per run · up to 6 listing pages per dealer",
  "Focused local radius: up to 30 miles",
  "2 concurrent searches · CSV export · advanced inventory scope options",
] as const;

/** Pro tier — backend id is `premium`. */
export const PRO_BULLETS = [
  "120 included searches / month",
  "Up to 20 dealerships per run · up to 10 listing pages per dealer",
  "Wide radius: up to 100 miles",
  "4 concurrent searches · CSV export · advanced inventory scope options",
] as const;

export const MAX_PRO_BULLETS = [
  "250 included searches / month",
  "Up to 20 dealerships per run · up to 10 listing pages per dealer",
  "Wide radius: up to 250 miles",
  "6 concurrent searches · CSV export · advanced inventory scope options",
] as const;

/** Shorter lists for compact UI (e.g. modal). */
export const STANDARD_BULLETS_SHORT = [
  "25 included searches / month",
  "Up to 10 dealerships · up to 30 mi radius",
  "CSV export · 2 concurrent searches · advanced inventory scope",
] as const;

export const PRO_BULLETS_SHORT = [
  "120 included searches / month",
  "Up to 20 dealerships · up to 100 mi radius",
  "CSV export · 4 concurrent searches · advanced inventory scope",
] as const;

export const MAX_PRO_BULLETS_SHORT = [
  "250 included searches / month",
  "Up to 20 dealerships · up to 250 mi radius",
  "CSV export · 6 concurrent searches · advanced inventory scope",
] as const;

export const QUOTA_MODAL_BODY_STANDARD_USER =
  "You've used your included monthly searches. Upgrade to Pro or Max Pro for a larger monthly pool, wider radius, and higher concurrency.";

export const QUOTA_MODAL_BODY_PRO_USER =
  "You've used your included monthly searches. Upgrade to Max Pro for a larger monthly pool and higher concurrency, or contact us for Enterprise.";

export const QUOTA_MODAL_BODY_MAX_PRO_USER =
  "You've used your included monthly searches. Contact us for Enterprise or custom volume.";

export const QUOTA_MODAL_BODY_DEFAULT =
  "You've used your included monthly searches for this period. Subscribe to Standard, Pro, or Max Pro for higher monthly pools, CSV export, and advanced limits — see plans below.";
