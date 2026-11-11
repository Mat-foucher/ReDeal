# ReDeal: an AI agent that finds cheaper subscription plans and switches them through PayPal

People overpay for subscriptions because finding and switching to a cheaper plan is tedious. ReDeal does both:

1. **You list what you pay.** Add subscriptions by hand, or bring in a plan you're billed for through PayPal.
2. **The AI agent finds cheaper plans.**
   - For a **plan billed through PayPal**, the agent reads the subscription and the merchant's plan catalog straight from PayPal (Subscriptions and Catalog APIs). OpenAI then compares each cheaper plan with yours: eligibility, trade-offs, and whether it's really comparable.
   - For **any other plan**, the agent researches current offers with OpenAI web search. A second AI pass reviews each candidate independently, and Python (not the AI) calculates the savings.
3. **You swipe.** Each deal is a card in the Swipe Pile. Swipe left to pass, right to approve.
4. **ReDeal acts on your approval.** For a plan billed through PayPal, approving asks PayPal to switch the subscription to the cheaper plan (`POST /v1/billing/subscriptions/{id}/revise`). You confirm on PayPal's own page, so nothing changes without your consent. **Undo** switches it back the same way. For other plans, ReDeal records the switch and you finish it on the provider's site.

Savings shown are *projected*. "Realized savings" stay at $0 until a lower charge is verified, so ReDeal never claims money it didn't save.

All PayPal calls use the **PayPal sandbox**. The app refuses any other PayPal environment.

## Built with

- **PayPal Developer Platform (sandbox):** OAuth 2.0, Catalog Products API, Subscriptions Plans API (list and read plans), Subscriptions API (read, create, revise), and buyer approval with return and cancel URLs.
- **OpenAI Responses API** (`gpt-5.1` by default): web search, structured JSON output, and a separate review pass.
- **FastAPI** with SQLAlchemy: SQLite locally, Postgres on Render.
- **Frontend:** plain HTML, CSS and JavaScript with no build step, served by the backend.
- **Render** Blueprint (`render.yaml`) for one-click hosting.

```
frontend/ (HTML/CSS/JS)  ->  backend/ FastAPI
                               |-- /subscriptions            your plans (SQLite / Postgres)
                               |-- /paypal/link-demo         bring a PayPal sandbox subscription into Plans
                               |-- /paypal/sync              re-read plan and price from PayPal
                               |-- /agent/scan               PayPal catalog check + AI comparison,
                               |                             OpenAI web research + independent AI review
                               |-- /agent/pile               Swipe Pile
                               |-- /agent/pile/{id}/swipe    approve -> PayPal revise (PayPal plans)
                               |-- /subscriptions/{id}/undo-switch   -> PayPal revise back
```

## Run it locally

You need **Python 3.11 or newer**, an **OpenAI API key** with billing enabled (scans cost a few cents), and a free **PayPal Developer** account for the sandbox.

### 1. Install

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows (PowerShell):

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 2. Add your keys to `backend/.env`

| Setting | Where to get it |
|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys → **Create new secret key**. Copy it right away; it's shown only once. |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | https://developer.paypal.com/dashboard/applications/sandbox → **Create App** (or open the default app) → copy the sandbox Client ID and Secret. |

Never commit `.env`; `.gitignore` already excludes it.

### 3. Create the sandbox merchant plans (once)

```bash
python setup_paypal_plans.py
```

This creates a fictional product with two monthly plans in your sandbox: **Standard ($25)** and **Saver ($15)**. Copy the two printed `PAYPAL_..._PLAN_ID` lines into `.env`. Run it only once; running it again creates duplicates.

### 4. Start ReDeal

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. API docs are at http://localhost:8000/docs.

### 5. Subscribe as a sandbox buyer

1. In ReDeal open **Labs** → **Start a sandbox subscription** → **Standard**, then **Continue in PayPal Sandbox**.
2. Sign in with your **sandbox personal account**, not your real PayPal account. Find its email and password at https://developer.paypal.com/dashboard/accounts → the *Personal* account → **View/Edit account**.
3. Approve the subscription. Copy the subscription ID PayPal shows (`I-…`) into `PAYPAL_DEMO_SUBSCRIPTION_ID` in `.env`, then restart the server.

## Try the full flow (about 2 minutes)

1. **Plans** → **Add a Plan Billed via PayPal**. The PayPal subscription appears as *ReDealer Demo Membership · Standard · $25.00*.
2. Optionally add an ordinary subscription too (for example *Spotify · Individual · $11.99*) so the agent also researches the web.
3. **Pile** → **Scan for Deals with AI** → **Start Scan**. The agent reads your PayPal subscription and the merchant's catalog, and OpenAI reviews the cheaper Saver plan. Web deals for other subscriptions arrive after a minute or two.
4. The Saver card carries a **Switches via PayPal** badge and shows $120 per year in projected savings. Swipe it right, or press ✓.
5. ReDeal asks PayPal to revise the subscription. **Continue to PayPal**, sign in as the sandbox buyer, and confirm. PayPal sends you back to ReDeal, which re-reads the plan from PayPal: **Plans** now shows *Saver · $15.00*.
6. Open the plan → **Undo Switch** to ask PayPal to move it back to Standard. The deal returns to the pile, so you can run the demo again.

PayPal's sandbox approval page sometimes shows a generic error even though the change went through. Reload ReDeal: it re-reads the plan from PayPal on every load.

## For judges

- **Source:** this repository. Setup takes about 5 minutes using the steps above.
- **Hosted demo:** if the submission lists a hosted URL, its sign-in and the sandbox buyer login are in the Devpost testing instructions, not in this public repository.
- **Tests:** `cd backend` then `python -m pytest -q`. The tests use a mocked PayPal and need no keys.

## Deploy to Render

`render.yaml` defines one web service (API and UI) plus a Postgres database.

1. In Render choose **New → Blueprint** and select this repository.
2. Fill in the secrets it asks for: `OPENAI_API_KEY` and the `PAYPAL_*` values from your `.env`.
3. After the deploy, open the service's **Environment** tab and copy `APP_PASSWORD`, which Render generates. The site asks for it, with username `redeal`.

The hosted site uses Postgres, so it starts empty. Free Render services sleep when idle and take a few seconds to wake. Anyone with the password can run scans that spend your OpenAI credit.

## How the agent stays honest

- **PayPal plans:** prices come from PayPal's catalog, not from the AI. The AI only judges comparability and explains trade-offs. Before switching, ReDeal re-checks that the subscription is active and on a different plan.
- **Web deals:** a deal needs model-reported evidence of current price, billing period, comparability and availability. Student, family, bundle and promotional offers are flagged **conditional**. Per-person prices are never compared with an individual plan.
- **Savings math:** savings are calculated in integer cents in Python, comparing yearly totals.
- **No surprise charges:** scans run only when you press Scan, because web search costs money.
- **Your secrets stay on the server:** PayPal and OpenAI credentials never reach the browser, and PayPal error payloads aren't passed through.

## Limits

- Sandbox only. A production version needs per-user accounts, PayPal webhooks to confirm revisions, and billing reconciliation before reporting realized savings.
- ReDeal can switch plans only for subscriptions billed through PayPal. For other providers it finds the deal and you switch on their site.
- The single-user sign-in (`APP_PASSWORD`) is meant for demos, not multi-tenant use.

## License

[MIT](LICENSE)
