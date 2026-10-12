"""TradeHub API — the backend for the new web app (Phase 1: order processing).

This is a thin FastAPI layer over the EXISTING TradeHub Python (order_routing, data_sources,
order_docs). It does not reimplement any business logic — it reuses it and exposes it over HTTP so
a fast React front-end can call it. The live Streamlit app is untouched and keeps running.

Run locally:   uvicorn api.main:app --reload --port 8000   (needs the same env vars as the app)
Deploy:        a SEPARATE Render service, rootDir = repo root,
               start = uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo root importable so we reuse the existing TradeHub modules as-is.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException            # noqa: E402
from fastapi.middleware.cors import CORSMiddleware    # noqa: E402

import data_sources as ds                             # noqa: E402  (reused — Monday/Shopify calls)
import order_routing as routing                       # noqa: E402  (reused — routing rules)

app = FastAPI(title="TradeHub API", version="0.1.0")

# Allow the Next.js front-end (local dev + its deployed origin) to call this API. Set WEB_ORIGINS on
# the host to the front-end's URL(s), comma-separated. Defaults to local Next.js dev.
_origins = [o.strip() for o in (os.environ.get("WEB_ORIGINS")
                                or "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "tradehub-api", "status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    """Liveness probe for the host's health check."""
    return {"ok": True, "service": "tradehub-api"}


def _order_out(o: dict) -> dict:
    """Trim a Monday order row to the fields the board needs (UI-friendly, stable shape)."""
    return {
        "item_id": o.get("item_id"),
        "order_no": o.get("order_no") or o.get("name"),
        "customer": o.get("customer") or "",
        "supplier": (o.get("supplier") or "") or None,
        "stage": (o.get("stage") or "") or None,
        "branch_email": (o.get("branch_email") or "") or None,
        "sell": o.get("sell") or None,
        "cost_supplier": o.get("cost_supplier") or None,
        "shopify_id": (o.get("shopify_id") or "").strip() or None,
        "has_po": bool(o.get("po_assets")),
    }


@app.get("/orders")
def orders():
    """The live NEW ORDERS group from Monday — reuses data_sources.fetch_new_orders().

    Proves the whole point of Phase 1: the existing Python brain, served over HTTP from live data,
    with no Streamlit. The front-end renders this fast and lets you act on it.
    """
    try:
        rows = ds.fetch_new_orders()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the orders board: {e}")
    return {"count": len(rows), "orders": [_order_out(o) for o in rows]}
