/**
 * Marketing bullets aligned with backend tier limits in `backend/app/tiers.py`.
 * Update both when limits change.
 */

export const STANDARD_BULLETS = [
  "350 included searches / month (metered overage available)",
  "Up to 10 dealerships per run · up to 6 listing pages per dealer",
  "Focused local radius: up to 30 miles (vs 100 mi on Free — Standard trades radius for volume, CSV, and concurrency)",
  "2 concurrent searches · CSV export · advanced inventory scope options",
] as const;

export const PREMIUM_BULLETS = [
  "750 included searches / month (metered overage available)",
  "Up to 20 dealerships per run · up to 10 listing pages per dealer",
  "Wide radius: up to 250 miles",
  "3 concurrent searches · CSV export · advanced inventory scope options",
] as const;

/** Shorter lists for compact UI (e.g. modal). */
export const STANDARD_BULLETS_SHORT = [
  "350 included searches / month",
  "Up to 10 dealerships · up to 30 mi radius (focused local runs)",
  "CSV export · 2 concurrent searches · advanced inventory scope",
] as const;

export const PREMIUM_BULLETS_SHORT = [
  "750 included searches / month",
  "Up to 20 dealerships · up to 250 mi radius",
  "CSV export · 3 concurrent searches · advanced inventory scope",
] as const;

export const QUOTA_MODAL_BODY_STANDARD_USER =
  "You've used your included monthly searches. Upgrade to Premium for a larger monthly pool, wider radius (up to 250 mi), more dealerships per run, and higher concurrency.";

export const QUOTA_MODAL_BODY_DEFAULT =
  "You've used your included monthly searches for this period. Subscribe to Standard or Premium for higher monthly pools, CSV export, and advanced limits — see plans below.";
