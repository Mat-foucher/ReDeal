# ReDealer v0.4 — public web Scout + mock offers

The existing PayPal sandbox workflow is unchanged. New **Web Scout (Mock)** tab:

1. Run backend and frontend as in V03_SETUP.md (copy your old backend/.env; do not share credentials).
2. Open http://localhost:3000, choose **Web Scout (Mock)**.
3. Add your current subscription's provider, plan name, and actual monthly amount. No target deal or target price is needed. Providers in this prototype: Spotify, Netflix, Dropbox.
4. Click **Scan public pricing pages**. The backend fetches the official URLs in `backend/scout_sources.json`, extracts explicit USD/month prices, compares them with the entered current monthly price, and returns mock deal cards with source links.
5. **Simulate approval** never calls PayPal or any provider. It reports projected savings and zero realized savings.

**Important limitations**: Public provider pages often use JavaScript, bot protection, promotional prices, annual pricing, or no reliable structured data. This prototype deliberately returns **no deal** if it cannot extract a defensible monthly price. Extracted prices are *not* proof of eligibility, equivalent features, or an available switch. Public offers may not be accessible to existing subscribers. This is a first functional discovery engine, not production-grade price intelligence. The current-subscription list and scanned deals are local prototype state, not user-isolated production data. Scan results are in-memory and reset on restart. Only scan sites you have permission to access; obey website terms and robots guidance. Never supply third-party credentials.

To extend providers, edit `backend/scout_sources.json`. Only HTTPS public pages. This is a developer-controlled config; do not expose arbitrary URL input to end users. For production, use approved provider APIs or affiliate catalogs, user authentication, per-user storage, background tasks, evidence snapshots, eligibility rules, and a real verified billing ledger.
