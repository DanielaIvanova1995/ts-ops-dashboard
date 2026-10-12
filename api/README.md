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
- **Start:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- **Env vars:** the same Monday/Shopify secrets as the Streamlit service, plus
  `WEB_ORIGINS` = the front-end's URL(s), comma-separated (e.g. the Vercel domain).
- **Health check path:** `/health`
- Instance: **Starter** is fine to begin (it's just an API); bump later if needed.

This service ships **nothing** to the live Streamlit app — Render runs them as two separate services
from the same repo.

## Endpoints (Phase 1, growing)
- `GET /health` — liveness
- `GET /orders` — the live NEW ORDERS group from Monday
- *(coming: `/orders/{id}/lines`, `/route`, `/supplier`, `/stage`, `/po`, `/process`, `/merge`)*
