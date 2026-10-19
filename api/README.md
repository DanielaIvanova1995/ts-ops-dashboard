# TradeHub API (new web-app backend)

A thin **FastAPI** layer over the existing TradeHub Python. It **reuses** `order_routing.py`,
`data_sources.py`, `order_docs.py` — no business logic is reimplemented. The live Streamlit app
(`app.py`) is untouched and keeps running on its own Render service.

## Run locally
From the repo root (so the imports resolve), with the same env vars the app uses
(`MONDAY_API_TOKEN`, `SHOPIFY_*`, etc.):

```bash
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000
```

Then: `http://localhost:8000/health` and `http://localhost:8000/orders`, interactive docs at
`http://localhost:8000/docs`.

## Deploy (its OWN Render service — separate from the Streamlit app)
- **New Web Service** on the Pro workspace, same repo, **branch `main`**.
- **Root Directory:** repo root (leave blank) — the app imports modules from the root.
- **Build:** `pip install -r api/requirements.txt`
- **Start:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT --workers 3`
  - `--workers 3` runs three processes so several people/batches process **in parallel** without
    queueing behind one worker (the cause of the "colleague can't process while I am" 502s).
    uvicorn has no per-request timeout, so long PO/split/upload requests are never cut off.
  - **Safe under multiple workers:** the background scheduler is lease-coordinated
    (`scheduler.hold_lease()` via Supabase) — every worker starts it but only the lease owner runs
    the jobs, so nothing double-runs. All durable state is external (Monday / Shopify / Supabase),
    so there's no shared in-memory state to corrupt.
  - Each worker loads the full app, so RAM ≈ (single-worker footprint) × workers — run **3 workers
    on a 1 GB+ instance** (bump off Starter if it restarts/OOMs).
- **Env vars:** the same Monday/Shopify secrets as the Streamlit service, plus
  `WEB_ORIGINS` = the front-end's URL(s), comma-separated (e.g. the Vercel domain).
- **Health check path:** `/health`
- Instance: **Starter** works for one worker; use **1 GB+** for `--workers 3`.

This service ships **nothing** to the live Streamlit app — Render runs them as two separate services
from the same repo.

## Endpoints (Phase 1, growing)
- `GET /health` — liveness
- `GET /orders` — the live NEW ORDERS group from Monday
- *(coming: `/orders/{id}/lines`, `/route`, `/supplier`, `/stage`, `/po`, `/process`, `/merge`)*
