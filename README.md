# Motorscrape

Next.js + FastAPI platform to discover nearby car dealerships (Google Places), fetch their websites through managed scrapers when configured, and extract inventory with an LLM. Results stream to the browser via **Server-Sent Events (SSE)**.

## Deploy on Vercel (Git)

This repo is set up for **[Vercel Services](https://vercel.com/docs/services)**: one project builds the **Next.js** app at `/` and the **FastAPI** app under **`/server`**, on the same deployment URL.

1. Push this repository to GitHub (for example [ZebariGroup/motorscrape.app](https://github.com/ZebariGroup/motorscrape.app.git)).
2. In [Vercel](https://vercel.com/new), **Import** the repo.
3. **Framework preset:** choose **Services** (required when `experimentalServices` is present in [`vercel.json`](vercel.json)). If the UI does not offer it yet, follow [Vercel’s Services docs](https://vercel.com/docs/services) for your account tier.
4. **Environment variables** (Production and Preview — add to **Sensitive** where applicable):

   | Name | Required | Notes |
   |------|----------|--------|
   | `GOOGLE_PLACES_API_KEY` | Yes | Places **Text Search** + **Place Details** (legacy APIs enabled in Google Cloud) |
   | `OPENAI_API_KEY` | Yes | Used for `gpt-4o-mini` extraction |
   | `ZENROWS_API_KEY` | No | Managed fetch / anti-bot ([ZenRows](https://docs.zenrows.com/)) |
   | `SCRAPINGBEE_API_KEY` | No | Alternative managed fetch ([ScrapingBee](https://www.scrapingbee.com/documentation/)) |

   Optional overrides:

   - `MOTORSCRAPE_API_PREFIX` — must match the API service `routePrefix` in [`vercel.json`](vercel.json) (default there is `/server`).
   - `NEXT_PUBLIC_API_URL` — normally set in `vercel.json` to `/server` so the browser calls the collocated API; override only if you split frontends/backends.

5. **Redeploy** after changing env vars.

**URLs**

- App: `https://<project>.vercel.app/`
- API health: `https://<project>.vercel.app/server/health`
- SSE search: `GET /server/search/stream?location=...&make=...&model=...`

**Limits**

- Scraping + LLM can run longer than default function limits. The API service sets [`maxDuration`: 300](vercel.json) seconds; your Vercel plan must allow that duration ([functions limits](https://vercel.com/docs/functions/limitations)).
- If previews hit timeouts, reduce concurrency or `max_dealerships` in [`backend/app/config.py`](backend/app/config.py) later.

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
