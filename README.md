# Motorscrape

Next.js + FastAPI platform to discover nearby car dealerships (Google Places), fetch their websites with **direct HTTP first** and managed scrapers (ZenRows / ScrapingBee) only when needed, and extract inventory from structured data when possible (otherwise an LLM). Results stream to the browser via **Server-Sent Events (SSE)**.

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

See [`.env.example`](.env.example). Backend: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000`. Frontend: `cd frontend && npm install && npm run dev` (unset `NEXT_PUBLIC_API_URL` so the UI targets `http://localhost:8000`).

## SSE event types

| Event           | Purpose                                      |
|----------------|----------------------------------------------|
| `status`       | High-level progress message                  |
| `dealership`   | Per-dealer scrape/parse status               |
| `vehicles`     | Batch of extracted listings for one dealer   |
| `search_error` | Recoverable or fatal application error       |
| `done`         | Stream complete                              |

## Scraping cost (ZenRows / ScrapingBee)

- The backend **tries a normal browser-like HTTP GET first** for each URL. Managed scrapers run only if the response looks blocked, empty, or missing inventory signals.
- ZenRows is called **without JS rendering first**, then with **`js_render` + `wait`** only if the static pass is still insufficient. Tune `ZENROWS_WAIT_MS` / `SCRAPINGBEE_WAIT_MS` in env or [`backend/app/config.py`](backend/app/config.py).
- **Structured inventory** (embedded JSON, `inventoryApiURL`-style endpoints, JSON-LD, and sitemap-discovered inventory URLs) is preferred so listings can be parsed **without** calling the LLM when possible.
- The search stream’s final **`done`** event includes **`fetch_metrics`** (counts per fetch mode, e.g. `fetch_direct`, `fetch_zenrows_rendered`). Each dealership **`done`** payload may include **`fetch_methods`** (sequence used for that dealer).

## Self-hosted browser fallback (evaluation)

If you want to avoid recurring managed-scraper fees, the typical pattern is **self-hosted headless browsers** (e.g. Playwright) plus **residential/datacenter proxies** and your own block detection—**not** “raw Playwright alone” on hard anti-bot sites. Expect higher ops burden than ZenRows. Optional directions: stealth browser builds, a small worker pool, and using that path **only** when direct + static managed fetches fail.

## Legal & ethics

Respect each site’s terms of service and robots rules; use managed scraping only where you have a lawful basis. This project is a technical scaffold—you are responsible for compliance.
