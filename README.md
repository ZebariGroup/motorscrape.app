# Motorscrape

Next.js + FastAPI platform to discover nearby car dealerships (Google Places), detect the dealer website **platform** on first contact, route through a provider-specific extraction strategy when possible, fetch with **direct HTTP first**, optional **self-hosted Playwright**, then managed scrapers (ZenRows / ScrapingBee) when still needed, and extract inventory from structured data when possible (otherwise an LLM). Results stream to the browser via **Server-Sent Events (SSE)**.

## Deploy on Vercel (Git)

This repo is set up for **[Vercel Services](https://vercel.com/docs/services)**: one project builds the **Next.js** app at `/` and the **FastAPI** app under **`/server`**, on the same deployment URL.

1. Push this repository to GitHub (for example [ZebariGroup/motorscrape.app](https://github.com/ZebariGroup/motorscrape.app.git)).
2. In [Vercel](https://vercel.com/new), **Import** the repo.
3. **Framework preset:** choose **Services** (required when `experimentalServices` is present in [`vercel.json`](vercel.json)). If the UI does not offer it yet, follow [Vercel’s Services docs](https://vercel.com/docs/services) for your account tier.
4. **Environment variables** (Production and Preview — add to **Sensitive** where applicable). **Your repo `.env` is not deployed** (it is gitignored); Vercel only sees variables you add in the dashboard.

   | Name | Required | Notes |
   |------|----------|--------|
   | `GOOGLE_PLACES_API_KEY` | Yes | Same key as in Google Cloud; you can also use `GOOGLE_MAPS_API_KEY`. Enable **[Places API](https://console.cloud.google.com/apis/library/places.googleapis.com)** (New) for Text Search + Place Details ([docs](https://developers.google.com/maps/documentation/places/web-service/text-search)) |
   | `OPENAI_API_KEY` | Yes | Used for `gpt-4o-mini` extraction |
   | `ZENROWS_API_KEY` | No | Managed fetch / anti-bot ([ZenRows](https://docs.zenrows.com/)); used after direct fetch fails or HTML lacks inventory signals |
   | `SCRAPINGBEE_API_KEY` | No | Alternative managed fetch ([ScrapingBee](https://www.scrapingbee.com/documentation/)) |

   Optional overrides:

   - `NEXT_PUBLIC_API_URL` — set in [`vercel.json`](vercel.json) to `/server` so the browser hits the FastAPI service; override only if you change `routePrefix` or split deployments.

5. **Redeploy** after changing env vars (or push an empty commit) so new env values are picked up if needed.

### Recommended: GitHub → Vercel (no CLI deploy)

Once the Vercel project is **connected to this GitHub repo** ([Project → Settings → Git](https://vercel.com/docs/git)), **every `git push` triggers a deployment**. That is the workflow you want for version control: commit on a branch, push to GitHub, let Vercel build **Production** (usually from `main`) and **Preview** (other branches / PRs).

```bash
git add -A && git commit -m "Your message" && git push origin main
```

Avoid routine **`vercel deploy`** from your laptop; it uploads a local tree and can diverge from what’s on GitHub. Use the CLI only for one-off tasks (e.g. `vercel link`, `vercel env add`, or `vercel curl` to test [deployment protection](https://vercel.com/docs/deployment-protection)):

```bash
vercel curl /server/health --scope <your-team-slug> --yes
```

**URLs**

- App: `https://<project>.vercel.app/`
- API health: `https://<project>.vercel.app/server/health`
- SSE search: `GET /server/search/stream?location=...&make=...&model=...`

**Limits**

- Scraping + LLM can run longer than default function limits. The API service sets [`maxDuration`: 300](vercel.json) seconds; your Vercel plan must allow that duration ([functions limits](https://vercel.com/docs/functions/limitations)).
- If previews hit timeouts, reduce concurrency or `max_dealerships` in [`backend/app/config.py`](backend/app/config.py) later.

### Google Places errors (`PERMISSION_DENIED`, `REQUEST_DENIED`, etc.)

Discovery uses **[Places API (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)** (`places:searchText` and Place Details `GET`) from **your backend on Vercel**, not the browser.

1. **Billing** — [Enable billing](https://console.cloud.google.com/billing) on the Google Cloud project that owns the key.
2. **Enable Places API (New)** — In [APIs & Services → Library](https://console.cloud.google.com/apis/library), enable **[Places API](https://console.cloud.google.com/apis/library/places.googleapis.com)** (`places.googleapis.com`). Legacy-only projects will see errors like [legacy API not activated](https://developers.google.com/maps/legacy#LegacyApiNotActivatedMapError).
3. **API key application restrictions** — A key restricted to **HTTP referrers (websites)** is for browser use only; **server-side calls from Vercel will fail.** Use **Application restrictions: None** for the backend key (or IP where feasible), and scope with **API restrictions** to Places only.
4. **SKU / field mask** — Text Search requests `websiteUri`, which maps to an **Enterprise** Text Search SKU in Google’s pricing tables; ensure your project is allowed to use those fields or trim the field mask in [`backend/app/services/places.py`](backend/app/services/places.py) and rely on the follow-up Place Details call only.

After changes in Google Cloud, update the key in Vercel if needed, then redeploy or push a commit. Error responses from Google are surfaced in the search stream when possible.

## Optional: run without Vercel

See [`.env.example`](.env.example). Backend: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000`.

Frontend: `cd frontend && npm install && npm run dev`.

**Recommended (accounts + cookies):** set `NEXT_PUBLIC_API_URL=/server` and `SESSION_SECRET` (see [`.env.example`](.env.example)). Next.js rewrites proxy `/server/*` to FastAPI on `127.0.0.1:8000` so the browser stays **same-origin** with the UI; session cookies and `EventSource` search streams then work without cross-site cookie issues.

**Alternative:** point the UI directly at FastAPI with `NEXT_PUBLIC_API_URL=http://localhost:8000` — search still works, but **login/session cookies will not** be sent on that origin from `localhost:3000`.

### Accounts and tiers

- **Anonymous:** 4 completed searches, then the stream returns a quota error until the user signs up.
- **Free / Standard / Premium:** enforced in [`backend/app/tiers.py`](backend/app/tiers.py); Standard and Premium can attach a **metered** Stripe price for search overages after the included monthly allotment.
- **Enterprise / custom:** documented for sales scoping in [`docs/ENTERPRISE_FEATURES.md`](docs/ENTERPRISE_FEATURES.md); set tier manually in the accounts DB or via a future admin flow (not Stripe Checkout).
- **Product priorities (paid differentiation):** see [`docs/PRODUCT_ROADMAP.md`](docs/PRODUCT_ROADMAP.md).

Auth API: `/server/auth/*`, billing: `/server/billing/*` (same paths without `/server` when running uvicorn on port 8000 alone).

### Search economics

The terminal SSE `done` event includes **`duration_ms`** and **`economics`** (`cost_driver_units` plus driver breakdown: dealerships, pages, managed fetch events, LLM pages, etc.) for margin analysis — see [`backend/app/services/economics.py`](backend/app/services/economics.py).

**Tests / lint (local):** use a venv in `backend/`, then `pip install -r requirements-dev.txt && ruff check app tests && pytest`. Frontend: `npm run lint && npm run test && npm run build`.

## SSE event types

| Event           | Purpose                                      |
|----------------|----------------------------------------------|
| `status`       | High-level progress message                  |
| `dealership`   | Per-dealer scrape/parse status               |
| `vehicles`     | Batch of extracted listings for one dealer   |
| `search_error` | Recoverable or fatal application error       |
| `done`         | Stream complete (includes `duration_ms`, `economics`) |

## Scraping cost (ZenRows / ScrapingBee)

- The backend **tries a normal browser-like HTTP GET first** for each URL, then optional **Playwright** if enabled, then **ZenRows / ScrapingBee** only if the response still looks blocked, empty, or missing inventory signals.
- Dealer **express.** inventory subdomains (digital retail) often return **403** or a Cloudflare challenge to plain HTTP clients. When **`ZENROWS_API_KEY`** or **`SCRAPINGBEE_API_KEY`** is set, **`express.*` inventory URLs** are fetched with **JS rendering first** (same path as other render-first pages). Without a managed scraper key, the backend may still try **`www.`** after a 403 on **`express.`** for the same path.
- ZenRows is called **without JS rendering first**, then with **`js_render` + `wait`** only if the static pass is still insufficient. Tune `ZENROWS_WAIT_MS` / `SCRAPINGBEE_WAIT_MS` in env or [`backend/app/config.py`](backend/app/config.py).
- **Structured inventory** (embedded JSON, `inventoryApiURL`-style endpoints, JSON-LD, and sitemap-discovered inventory URLs) is preferred so listings can be parsed **without** calling the LLM when possible.
- The search stream’s final **`done`** event includes **`fetch_metrics`** (counts per fetch mode, e.g. `fetch_direct`, `fetch_zenrows_rendered`) and **`extraction_metrics`** (pages extracted via provider vs structured JSON vs LLM, plus LLM failures). Each dealership **`done`** payload may include **`fetch_methods`** (sequence used for that dealer), plus **`platform_id`**, **`platform_source`**, and **`strategy_used`**.

## Platform-aware routing

- The backend fingerprints dealer websites and routes them through a provider-specific strategy before generic parsing.
- Known platforms currently include **Dealer.com**, **DealerOn**, **Dealer Inspire**, **CDK / DealerFire**, **Team Velocity**, **D2C Media / AutoAubaine**, **fusionZONE**, **Shift Digital**, **PureCars**, and **Jazel**.
- Platform detection is cached by normalized dealer domain using the path configured by **`PLATFORM_CACHE_PATH`**.
- The cache stores the detected platform, extraction mode, whether render is usually required, and the last successful inventory URL hint.
- On repeated searches, cached platform hits let the backend skip rediscovering the extraction path for the same dealer.
- The cache is implemented with a small SQLite store: **local dev** defaults to `backend/data/platform-cache.sqlite3`; **Vercel** defaults to `/tmp` (ephemeral). Set **`PLATFORM_CACHE_PATH`** to a persistent writable path if you need durability across cold starts.

## Self-hosted browser fallback (Playwright)

When **`PLAYWRIGHT_ENABLED=true`**, the API loads each URL in **headless Chromium** (after direct HTTP fails or returns HTML without inventory signals, and **before** ZenRows / ScrapingBee). That cuts paid API usage on many dealer SPAs that only need client-side rendering, not commercial anti-bot bypass.

The Playwright path now supports **platform-aware interaction recipes** before falling back to managed renderers. For inventory pages this can include targeted waits for result tiles, local scroll passes, and platform-specific load-more logic, which helps recover more listings without paying for ZenRows JS rendering.

To keep slow dealerships from bottlenecking the rest of a search, the backend also runs multiple dealership workers concurrently and now defaults to a faster-fail tuning profile (`ZENROWS_MAX_CONCURRENCY=50`, `MANAGED_SCRAPER_MAX_CONCURRENCY=50`, `SEARCH_CONCURRENCY=16`, `PLAYWRIGHT_MAX_WORKERS=4`, `DEALERSHIP_TIMEOUT=150`, `SCRAPE_TIMEOUT=30`). If your host has more CPU and RAM, you can tune higher; if it is resource-constrained, scale these down conservatively.

**Setup (own server / Docker / local):**

1. Install base Python deps: `cd backend && pip install -r requirements.txt`.
2. (Optional local Playwright mode) install browsers:
   `cd backend && pip install playwright && playwright install chromium`
3. Set env: `PLAYWRIGHT_ENABLED=true` (optional: `PLAYWRIGHT_MAX_WORKERS`, `PLAYWRIGHT_TIMEOUT_MS`, `PLAYWRIGHT_POST_LOAD_WAIT_MS` — see [`.env.example`](.env.example)).
4. Watch **`fetch_metrics`** after rollout. A healthy change should increase `playwright_ok` and reduce `zenrows_rendered` without reducing listing completeness.

**Vercel:** leave Playwright **disabled** (no bundled Chromium on typical serverless runtimes). Use ZenRows/ScrapingBee there, or run the FastAPI worker on a VM with Playwright enabled.

Hard **WAF / CAPTCHA** sites may still require managed scrapers or proxies; Playwright alone is not a drop-in replacement for every dealer.

## Legal & ethics

Respect each site’s terms of service and robots rules; use managed scraping only where you have a lawful basis. This project is a technical scaffold—you are responsible for compliance.
