# PayPal sandbox integration (v0.2)

This increment adds real PayPal sandbox product/plan creation and a buyer approval flow. It does **not** yet implement switching, buyer ownership, webhooks or verified savings. Do not expose the API publicly without authentication, authorization, rate limits, and abuse controls.

1. From `backend/`, activate `.venv` and run `pip install -r requirements.txt`.
2. Put your sandbox client ID and secret in `backend/.env` (see `.env.example`). Never commit this file.
3. Run `python setup_paypal_plans.py` **once**. This creates one fictional product and two plans ($25 and $15 per month). Re-running creates duplicates.
4. Copy `PAYPAL_STANDARD_PLAN_ID` and `PAYPAL_SAVER_PLAN_ID` output lines into `backend/.env`.
5. Start backend: `uvicorn app.main:app --reload --port 8000`.
6. Visit `http://127.0.0.1:8000/docs`, use `GET /paypal/demo-plans` to verify IDs.
7. Use `POST /paypal/subscriptions/create` with `{"plan":"standard"}`; open the returned `approval_url` in your browser and log in with a **sandbox personal buyer** account (not your real PayPal account).
8. Use `GET /paypal/subscriptions/{subscription_id}` to check state. Buyer approval and activation can be asynchronous.

## Next milestone

Add authenticated per-user PayPal subscription ownership, buyer-consented plan revision, return URL handling, verified PayPal webhooks, and billing reconciliation. Only then connect a right swipe to a switch request. Do not increment actual savings based on an unverified approval or simulated subscription.

## Render note

Keep the existing Next.js UI while building the payment integration. Consider Python-first Streamlit migration only after testing swipe interaction quality. On Render use environment variables for secrets and a managed database for persistence; never rely on ephemeral SQLite storage. Free services can spin down, making always-on scouting unreliable.
