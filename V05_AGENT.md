# ReDealer v0.5 — Automatic Mock Deal Scout

The backend runs a background scouting loop on startup (default every 30 minutes), querying developer-maintained public pricing URLs in `backend/scout_sources.json`. It compares explicitly identified USD monthly prices with active subscriptions in the local database and generates **simulation-only** deal cards. It does not purchase anything or claim verified eligibility.

## Run

Backend: `cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python -m uvicorn app.main:app --reload --port 8000`

Frontend (separate terminal): `cd frontend && npm install && npm run dev`

Go to http://localhost:3000, Web Scout tab. Add a subscription once with its **current** monthly price. The agent will scan automatically in the background, or use Scan now to refresh immediately. No target price is entered.

Endpoints: `GET /scout/deals`, `POST /scout/scan`, `POST /scout/mock-decision`. Set `SCOUT_INTERVAL_SECONDS=1800` in `backend/.env` to change cadence (minimum 300 seconds). PayPal env vars are **not required** for Web Scout.

## Limitations

- This is an autonomous *scheduled research workflow*, not a general web-browsing LLM agent. It only searches configured sources (Spotify, Netflix, Dropbox). Sites may block scraping or expose ambiguous prices; no deal is invented in that case.
- Detected prices are **unverified candidates**, not proven equivalent/eligible plans. Some pricing may be promotional or depend on billing frequency. The card links the source and clearly marks simulation.
- The local SQLite database stores subscriptions. Scout cache and mock decisions are in-memory and are reset on restart. Background loop runs once per FastAPI worker; use one worker for the prototype.
- Do not deploy this multi-user without authentication, tenant isolation, persistent job storage, rate limiting and provider-specific eligibility checks.
- `.env.example` is a template; real values belong in `.env`, which should never be committed.
