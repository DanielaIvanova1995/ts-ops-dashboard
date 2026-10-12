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

import requests                                        # noqa: E402 (reused — Shopify/Monday HTTP)

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
    assets = o.get("po_assets") or []
    po = assets[0] if assets else {}
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
        "has_po": bool(assets),
        "po_url": (po.get("public_url") or po.get("url")) if po else None,
        "po_name": po.get("name") if po else None,
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


# ---- Order detail (summary box) + Monday updates --------------------------------------------------
_SHOPIFY_API = "2024-10"


def _sm(node, key):
    """Pull a float out of a Shopify `<key>Set { shopMoney { amount } }` block, or None."""
    try:
        return float((((node or {}).get(key) or {}).get("shopMoney") or {}).get("amount"))
    except (TypeError, ValueError):
        return None


def _addr_lines(a):
    if not a:
        return []
    parts = [a.get("name"), a.get("company"), a.get("address1"), a.get("address2"),
             " ".join(x for x in [a.get("city"), a.get("province")] if x),
             a.get("zip"), a.get("country")]
    return [str(x).strip() for x in parts if x and str(x).strip()]


def _shopify_order_detail(shopify_id: str) -> dict:
    store = ds.get_secret("SHOPIFY_STORE")
    token = ds.shopify_products_token()
    gid = f"gid://shopify/Order/{str(shopify_id).strip()}"
    query = (
        "query($id: ID!) { order(id: $id) { name createdAt updatedAt displayFinancialStatus "
        "customer { firstName lastName email phone } "
        "shippingAddress { name company address1 address2 city province zip country phone } "
        "billingAddress { name company address1 address2 city province zip country phone } "
        "totalPriceSet { shopMoney { amount currencyCode } } "
        "subtotalPriceSet { shopMoney { amount } } totalShippingPriceSet { shopMoney { amount } } "
        "totalTaxSet { shopMoney { amount } } "
        "lineItems(first: 100) { edges { node { title variantTitle quantity sku "
        "originalUnitPriceSet { shopMoney { amount } } discountedTotalSet { shopMoney { amount } } "
        "} } } } }")
    r = requests.post(f"https://{store}/admin/api/{_SHOPIFY_API}/graphql.json",
                      json={"query": query, "variables": {"id": gid}},
                      headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                      timeout=25)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify error: {payload['errors']}")
    return (payload.get("data") or {}).get("order") or {}


def _monday_item_updates(item_id: str) -> dict:
    """The Monday item's last-changed time + its updates feed (the 'updates bubble' content)."""
    q = ("query($i:[ID!]){items(ids:$i){ name updated_at "
         "updates(limit:50){ id body created_at creator{ name } } }}")
    data = ds._monday_gql(q, {"i": [str(item_id)]}, ds.get_token())
    items = data.get("items") or []
    it = items[0] if items else {}
    ups = [{"id": u.get("id"), "body": u.get("body"), "created_at": u.get("created_at"),
            "creator": (u.get("creator") or {}).get("name")} for u in (it.get("updates") or [])]
    return {"monday_name": it.get("name"), "monday_updated_at": it.get("updated_at"), "updates": ups}


@app.get("/orders/{item_id}/detail", dependencies=[Depends(require_key)])
def order_detail(item_id: str, shopify_id: str | None = None):
    """Everything for the summary box: customer, BOTH addresses, line items, live totals, when the
    order last changed (Shopify + Monday), and the Monday updates thread. `shopify_id` is passed by
    the board (it already has it); Monday updates come from item_id."""
    out: dict = {"item_id": item_id}
    try:
        out.update(_monday_item_updates(item_id))
    except Exception as e:  # noqa: BLE001
        out["updates"], out["updates_error"] = [], str(e)[:150]
    if shopify_id:
        try:
            o = _shopify_order_detail(shopify_id)
            cust = o.get("customer") or {}
            name = " ".join(x for x in [cust.get("firstName"), cust.get("lastName")] if x)
            items = []
            for e in ((o.get("lineItems") or {}).get("edges") or []):
                n = e.get("node") or {}
                vt = (n.get("variantTitle") or "").strip()
                if vt.lower() == "default title":
                    vt = ""
                items.append({"title": n.get("title"), "variant": vt,
                              "sku": (n.get("sku") or "").strip() or None, "qty": n.get("quantity"),
                              "unit": _sm(n, "originalUnitPriceSet"),
                              "line_total": _sm(n, "discountedTotalSet")})
            sa, ba = o.get("shippingAddress") or {}, o.get("billingAddress") or {}
            out["shopify"] = {
                "order_name": o.get("name"), "created_at": o.get("createdAt"),
                "updated_at": o.get("updatedAt"), "financial_status": o.get("displayFinancialStatus"),
                "customer": {"name": name, "email": cust.get("email"), "phone": cust.get("phone")},
                "shipping": {"lines": _addr_lines(sa), "phone": sa.get("phone")},
                "billing": {"lines": _addr_lines(ba), "phone": ba.get("phone")},
                "totals": {"total": _sm(o, "totalPriceSet"), "subtotal": _sm(o, "subtotalPriceSet"),
                           "shipping": _sm(o, "totalShippingPriceSet"), "tax": _sm(o, "totalTaxSet"),
                           "currency": (((o.get("totalPriceSet") or {}).get("shopMoney") or {})
                                        .get("currencyCode"))},
                "items": items,
            }
        except Exception as e:  # noqa: BLE001
            out["shopify_error"] = str(e)[:150]
    return out


@app.get("/updates-counts", dependencies=[Depends(require_key)])
def updates_counts():
    """Update count per order in the NEW ORDERS group — one Monday call, for the row bubbles."""
    q = ("query($b:[ID!],$g:[String!]){boards(ids:$b){groups(ids:$g){"
         "items_page(limit:200){items{ id updates{ id } }}}}}")
    try:
        data = ds._monday_gql(q, {"b": [str(ds.ORDERS_BOARD_ID)], "g": [ds.ORDERS_NEW_GROUP]},
                              ds.get_token())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read updates: {e}")
    boards = data.get("boards") or []
    groups = (boards[0].get("groups") if boards else []) or []
    items = ((groups[0].get("items_page") or {}).get("items") if groups else []) or []
    return {"counts": {it["id"]: len(it.get("updates") or []) for it in items}}
