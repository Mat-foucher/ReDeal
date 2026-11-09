# ReDealer — AI Deal Scout + Swipe Pile

A local-first proof of concept for AI-assisted subscription deal discovery. The FastAPI backend calls OpenAI's Responses API with web search, performs a separate review pass, validates savings using Python, and stores eligible research candidates in SQLite. The Next.js frontend displays those candidates in a Swipe Pile. **All AI Scout swipes are simulations.** The separate optional PayPal sandbox demo remains available.

## Architecture

```
frontend/ Next.js  ->  backend/ FastAPI
                          |-- /subscriptions -> SQLite
                          |-- /agent/scan -> OpenAI web search research
                          |                 -> independent AI review
                          |                 -> deterministic price checks
                          |                 -> persistent scout_deals table
                          |-- /agent/pile -> Swipe Pile
                          |-- /agent/pile/{id}/swipe -> mock approval / pass
                          |-- /demo/* -> optional PayPal sandbox
```

## Setup

Requirements: Python 3.11+, Node.js 20+, OpenAI API key with API billing and web-search access. **API calls and web searches incur charges.**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env`, set `OPENAI_API_KEY=...`. PayPal fields are optional for AI scouting. **Never commit `.env` or API keys.**

```bash
python -m uvicorn app.main:app --reload --port 8000
```

The backend also serves the UI (`frontend/`, plain HTML/CSS/JS with no build step or Node.js).

Open http://localhost:8000. To try it on a phone on the same Wi-Fi, add `--host 0.0.0.0` and open `http://<your-computer-ip>:8000` (the API has no authentication, so only do this on a network you trust). Add a subscription with its actual monthly price, select **Swipe Pile**, click **Scan for deals with AI**, and approve/pass the mock cards. Swagger API docs: http://localhost:8000/docs.

## Deploy to Render

The repository includes a `render.yaml` Blueprint: one web service that serves both the API and the UI, plus a Postgres database.

1. In Render choose **New > Blueprint** and select this repository.
2. Fill in the secrets it asks for. `OPENAI_API_KEY` enables the AI scan; the `PAYPAL_*` values are only needed for the sandbox demo in Labs and can be left blank.
3. After the deploy, open the service's **Environment** tab and copy `APP_PASSWORD` (Render generates it). The site asks for it on first visit; the username is `redeal`.

Notes: the hosted site uses Postgres through `DATABASE_URL`, so it starts empty and does not use `backend/redealer.db`. Free web services sleep when idle and wake on the next visit, and a scan that is running when the service restarts is lost. Free Postgres databases are time-limited; check Render's current terms. Anyone with the password can run scans that spend your OpenAI credit.

## Behavior and limitations

- **Scan is manual by default** to prevent surprise web-search API charges. A scan processes all active subscriptions, with up to five candidates and a separate verification call per candidate. The request may take minutes; keep the backend running.
- Only candidates with model-reported evidence of current price, billing period, comparability, and availability enter the Swipe Pile. These are **AI-assisted checks, not independently proven facts**. Always inspect source and eligibility.
- Student, family, bundle and promotional offers are flagged **conditional**. Historical or unverified offers are rejected. Household/per-person pricing is never compared against an individual plan unless the total plan price is actually lower.
- Annual plans use total annual payment for savings calculations and show the upfront cost.
- Approvals and passes are stored in SQLite. A repeated scan does not re-add a previously swiped identical offer. Changed offer prices may generate a new card.
- **No account changes, purchases, cancellations, or realized savings** occur from AI Scout actions. The PayPal sandbox is separate and optional.
- Local prototype only: no accounts, authentication, job queue, production rate limiting, or robust per-user isolation. Do not deploy publicly without adding these.
- Existing `scout_sources.json` and `/scout/*` endpoints remain for legacy demos but do not populate the AI Swipe Pile.

## Tests

```bash
cd backend
python -m pytest -q
```

The tests exercise savings arithmetic, eligibility flags, and rejection of higher prices. Live API calls require a configured key and are not covered by unit tests.

## GitHub

From the `redealer-mvp` directory:

```bash
git init
git add .
git commit -m "Integrate AI deal scout with persistent mock swipe pile"
```

The `.gitignore` excludes `.env`, SQLite databases, Python caches, and `node_modules`. Inspect `git status` before pushing.


## AI Scout JSON reliability update
The **Swipe Pile** uses `backend/app/agent_scout.py`, not the legacy
`backend/app/scout.py` HTML scraper. The agent uses the same OpenAI
Responses API + `web_search` approach as the working Colab prototype,
with two passes (research and independent review), strict JSON schemas,
and Python-only monetary calculations. The frontend calls `POST /agent/scan`
and loads `GET /agent/pile`. The legacy `/scout/*` endpoints remain for
backward compatibility, but they are not the AI Swipe Pile.

If you previously saw `JSONDecodeError` during Spotify research, this
release adds structured output and checks for incomplete responses.
Restart the FastAPI server after updating. No merchant accounts are
modified by an AI swipe; all deals are simulations.
