# PayPal sandbox setup

The full walkthrough is in [README.md](README.md#run-it-locally). In short:

1. Put your sandbox **Client ID** and **Secret** in `backend/.env` (from https://developer.paypal.com/dashboard/applications/sandbox).
2. From `backend/`, run `python setup_paypal_plans.py` **once**. It creates a fictional product with a Standard ($25/mo) and a Saver ($15/mo) plan. Copy the printed plan IDs into `.env`.
3. Start the server, open **Labs** → **Start a sandbox subscription** → **Standard**, and approve it with your **sandbox personal account** (from https://developer.paypal.com/dashboard/accounts). Put the `I-…` subscription ID in `PAYPAL_DEMO_SUBSCRIPTION_ID` and restart.
4. **Plans** → **Add a Plan Billed via PayPal**, then scan in the **Swipe Pile**.

## PayPal APIs used

| API | Used for |
|---|---|
| `POST /v1/oauth2/token` | Server-side client-credentials token |
| `POST /v1/catalogs/products`, `POST /v1/billing/plans` | Creating the demo merchant catalog (`setup_paypal_plans.py`) |
| `GET /v1/catalogs/products/{id}` | Merchant name shown on the plan |
| `GET /v1/billing/plans?product_id=…`, `GET /v1/billing/plans/{id}` | The agent reads every active plan and its price |
| `POST /v1/billing/subscriptions` | Starting a sandbox subscription |
| `GET /v1/billing/subscriptions/{id}` | Live status, current plan, and next billing date |
| `POST /v1/billing/subscriptions/{id}/revise` | Switching plans when you approve a deal, and switching back on undo; the buyer confirms on PayPal |

## Safety

- `PAYPAL_ENVIRONMENT` must be `sandbox`; the app refuses anything else.
- Credentials stay on the server, and PayPal error payloads are never forwarded to the browser.
- Every switch needs your approval in ReDeal **and** the buyer's confirmation on PayPal.
- Realized savings stay at $0 until a lower charge is verified. Webhook-based verification is the next step for production.
