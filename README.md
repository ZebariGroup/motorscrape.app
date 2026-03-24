# Motorscrape

Next.js + FastAPI platform to discover nearby car dealerships (Google Places), fetch their websites through managed scrapers when configured, and extract inventory with an LLM. Results stream to the browser via **Server-Sent Events (SSE)**.

## Deploy on Vercel (Git)

This repo is set up for **[Vercel Services](https://vercel.com/docs/services)**: one project builds the **Next.js** app at `/` and the **FastAPI** app under **`/server`**, on the same deployment URL.

1. Push this repository to GitHub (for example [ZebariGroup/motorscrape.app](https://github.com/ZebariGroup/motorscrape.app.git)).
2. In [Vercel](https://vercel.com/new), **Import** the repo.
3. **Framework preset:** choose **Services** (required when `experimentalServices` is present in [`vercel.json`](vercel.json)). If the UI does not offer it yet, follow [Vercel’s Services docs](https://vercel.com/docs/services) for your account tier.
4. **Environment variables** (Production and Preview — add to **Sensitive** where applicable). **Your repo `.env` is not deployed** (it is gitignored); Vercel only sees variables you add in the dashboard.

   | Name | Required | Notes |
   |------|----------|--------|
   | `GOOGLE_PLACES_API_KEY` | Yes | Same key as in Google Cloud; you can also use `GOOGLE_MAPS_API_KEY`. Enable Places **Text Search** + **Place Details** (legacy APIs) |
   | `OPENAI_API_KEY` | Yes | Used for `gpt-4o-mini` extraction |
   | `ZENROWS_API_KEY` | No | Managed fetch / anti-bot ([ZenRows](https://docs.zenrows.com/)) |
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

### Google `REQUEST_DENIED` (Places Text Search)

This app calls the **legacy** Places Web Service (`/maps/api/place/textsearch/json` and `details/json`) from **your backend on Vercel** (not the user’s browser). `REQUEST_DENIED` is almost always configuration on the Google side:

1. **Billing** — [Enable billing](https://console.cloud.google.com/billing) on the Google Cloud project that owns the key.
2. **Enable the right APIs** — In [APIs & Services → Library](https://console.cloud.google.com/apis/library), enable **Places API** (and ensure **Places API (New)** does not replace what you need; legacy Text Search still uses the classic web service). If unsure, enable **Places API** and **Geocoding API** as needed for your console prompts.
3. **API key application restrictions** — A key restricted to **HTTP referrers (websites)** is for browser/JavaScript use only. **Server-side requests from Vercel will be denied.** For backend use you typically need **Application restrictions: None** (tighten with **API restrictions** only, limiting the key to Places-related APIs), or a separate **server** key without referrer locking.
4. **API restrictions** — Under the key, set **API restrictions** to restrict to Places (and related) APIs only; do not leave the key unrestricted in production if you can avoid it.

After changes in Google Cloud, update `GOOGLE_PLACES_API_KEY` / `GOOGLE_MAPS_API_KEY` in Vercel if you created a new key, then redeploy or push a commit.

The API error stream now includes Google’s `error_message` text when present, which often states the exact restriction (e.g. referrer not allowed).

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

## Legal & ethics

Respect each site’s terms of service and robots rules; use managed scraping only where you have a lawful basis. This project is a technical scaffold—you are responsible for compliance.
