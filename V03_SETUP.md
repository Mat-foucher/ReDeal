# ReDealer v0.3 — local PayPal sandbox demo

This demo discovers the configured $15 Saver plan automatically for an ACTIVE $25 Standard subscription. No user-entered target prices. It does **not** scan the open web, manage unrelated providers, or claim savings before verified billing. Do not deploy the revision route publicly: it uses a local demo action key rather than user accounts/ownership controls.

## Configure

1. Copy your existing `backend/.env` PayPal credentials and `PAYPAL_STANDARD_PLAN_ID` / `PAYPAL_SAVER_PLAN_ID` to this fresh project's `backend/.env` (do not share or commit this file).
2. Add your active Standard sandbox subscription ID, e.g. `PAYPAL_DEMO_SUBSCRIPTION_ID=I-...`.
3. Generate a fresh local demo key: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Add `PAYPAL_DEMO_ACTION_KEY=<generated-value>` to `.env`.
4. Confirm `PAYPAL_ENVIRONMENT=sandbox`.

## Run

Terminal 1 (from project root):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Terminal 2 (from project root):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The Deals tab fetches `/demo/deals`, which reads the configured subscription from PayPal and automatically compares the sandbox catalog plans. It only presents a Saver deal when the subscription is ACTIVE on Standard.

## Switch demo

Click **Approve switch** on the deal, review the terms, enter the local demo key from `.env`, and confirm. The backend calls `POST /v1/billing/subscriptions/{id}/revise` with the Saver plan ID. If PayPal returns an approval URL, the browser navigates to sandbox checkout. After approving, return to the app and click Refresh. If PayPal doesn't return an approval URL, still refresh and verify via `GET /paypal/subscriptions/{id}` in Swagger.

A successful revision may change the plan without proving a lower payment has been collected. The realized savings counter intentionally stays at $0 until a billing-verification ledger is implemented. Avoid repeated revision requests when uncertain about the response; check the PayPal subscription state first.

## Security limitations

- This is a **single-subscription, sandbox-only local demo**. No authenticated user identities or ownership binding. Keep it on localhost; don't deploy the `/demo/revise` route publicly.
- The local action key is entered at confirmation time and is not stored by the frontend. Never use a real production PayPal secret as the action key.
- Before production: add authenticated user accounts, subscription ownership checks, idempotency, webhook signature verification, billing ledger, verified plan pricing and eligibility, persistence, and rate limits.
