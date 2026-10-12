"""TradeHub API — the backend for the new web app (Phase 1: order processing).

This is a thin FastAPI layer over the EXISTING TradeHub Python (order_routing, data_sources,
order_docs). It does not reimplement any business logic — it reuses it and exposes it over HTTP so
a fast React front-end can call it. The live Streamlit app is untouched and keeps running.

Run locally:   uvicorn api.main:app --reload --port 8000   (needs the same env vars as the app)
Deploy:        a SEPARATE Render service, rootDir = repo root,
               start = uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

# Make the repo root importable so we reuse the existing TradeHub modules as-is.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, Header, HTTPException   # noqa: E402
from fastapi.middleware.cors import CORSMiddleware            # noqa: E402
from pydantic import BaseModel                                # noqa: E402

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

# ---- Shared access-code lock ---------------------------------------------------------------------
# Set TRADEHUB_ACCESS_KEY on the host to a shared code. The front-end sends it as the
# X-TradeHub-Key header on every request; the API rejects anything else. `/health` and `/` stay open
# (the host's health check needs /health). If the env var is UNSET the API stays open — so it MUST be
# set on the deployed service. Interim gate until per-person Supabase logins land.
_ACCESS_KEY = (os.environ.get("TRADEHUB_ACCESS_KEY") or "").strip()


def require_key(x_tradehub_key: str | None = Header(default=None)):
    if not _ACCESS_KEY:
        return  # no code configured → open (set TRADEHUB_ACCESS_KEY on the host to lock it)
    if not x_tradehub_key or not hmac.compare_digest(x_tradehub_key, _ACCESS_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing access code")


@app.get("/")
def root():
    return {"service": "tradehub-api", "status": "ok", "locked": bool(_ACCESS_KEY), "docs": "/docs"}


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


@app.get("/orders", dependencies=[Depends(require_key)])
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


@app.get("/meta", dependencies=[Depends(require_key)])
def meta():
    """Dropdown options for the board: the live Monday Supplier labels + the Stage options.
    Mirrors how the Streamlit board builds its selectors so writes always match a real label."""
    try:
        suppliers = [s for s in ds.op_board_supplier_labels() if s]
    except Exception:  # noqa: BLE001
        suppliers = sorted(set(routing.CANON.values()))
    return {"suppliers": suppliers, "stages": list(ds.OP_STAGES)}


class SupplierIn(BaseModel):
    supplier: str = ""   # "" clears the Monday dropdown


class StageIn(BaseModel):
    stage: str = ""      # "" clears the status


@app.post("/orders/{item_id}/supplier", dependencies=[Depends(require_key)])
def set_supplier(item_id: str, body: SupplierIn):
    """Set (or clear) the Supplier on the Monday order — reuses data_sources.op_set_supplier.
    Monday stays the source of truth; this is the same write the Streamlit board does."""
    try:
        ds.op_set_supplier(item_id, (body.supplier or "").strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't set supplier: {e}")
    return {"ok": True, "item_id": item_id, "supplier": (body.supplier or "").strip() or None}


@app.post("/orders/{item_id}/stage", dependencies=[Depends(require_key)])
def set_stage(item_id: str, body: StageIn):
    """Set (or clear) the Stage/status on the Monday order — reuses data_sources.op_set_status."""
    try:
        ds.op_set_status(item_id, (body.stage or "").strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't set stage: {e}")
    return {"ok": True, "item_id": item_id, "stage": (body.stage or "").strip() or None}
