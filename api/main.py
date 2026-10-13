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

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile  # noqa: E402
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
_SHOP_STORE = (ds.get_secret("SHOPIFY_STORE") or "").strip()  # e.g. xxx.myshopify.com — for admin links


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


@app.get("/diag")
def diag():
    """Yes/no status of the backend's integrations — no secrets returned. Open (booleans only) so it
    can be checked quickly. Confirms whether Supabase + QuickBooks are usable from THIS service."""
    out = {"supabase_configured": False, "supabase_read_ok": None, "qbo_connected": None}
    try:
        import supabase_db as sdb
        out["supabase_configured"] = bool(sdb.configured())
        if out["supabase_configured"]:
            try:
                sdb.config_get("invoice_import")   # trivial read → proves it actually connects
                out["supabase_read_ok"] = True
            except Exception as e:  # noqa: BLE001
                out["supabase_read_ok"] = False
                out["supabase_error"] = str(e)[:140]
    except Exception as e:  # noqa: BLE001
        out["supabase_error"] = str(e)[:140]
    try:
        out["qbo_connected"] = bool(ds.qbo_is_connected())
    except Exception as e:  # noqa: BLE001
        out["qbo_error"] = str(e)[:140]
    return out


def _order_out(o: dict) -> dict:
    """Trim a Monday order row to the fields the board needs (UI-friendly, stable shape)."""
    assets = o.get("po_assets") or []
    po = assets[0] if assets else {}
    sid = (o.get("shopify_id") or "").strip()
    return {
        "item_id": o.get("item_id"),
        # Use the Monday ITEM NAME so the order number matches Monday EXACTLY — including the split
        # suffix (31824-1, 31824-2). The order_no column holds only the base number, so name wins.
        "order_no": o.get("name") or o.get("order_no"),
        "customer": o.get("customer") or "",
        "supplier": (o.get("supplier") or "") or None,
        "stage": (o.get("stage") or "") or None,
        "branch_email": (o.get("branch_email") or "") or None,
        "sell": o.get("sell") or None,
        "cost_supplier": o.get("cost_supplier") or None,
        "shopify_id": sid or None,
        "shopify_url": f"https://{_SHOP_STORE}/admin/orders/{sid}" if (_SHOP_STORE and sid) else None,
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
    """CLEAN supplier options for the dropdowns: the real suppliers we actually deal with (routing
    targets + the PO-email and head-office-phone maps), using Monday's exact label spelling where it
    matches so writes still land on a real option. Drops the junk/legacy labels on the raw Monday
    dropdown (fraud, dani, 252.07, typos, dupes, …). Plus the Stage options."""
    import order_processing as op
    real = (set(routing.CANON.values())
            | set(op.SUPPLIER_PO_EMAIL.keys())
            | set(op.SUPPLIER_HEAD_OFFICE_PHONE.keys()))
    try:
        live = [s for s in ds.op_board_supplier_labels() if s]
    except Exception:  # noqa: BLE001
        live = []
    canon_val, live_by_canon, code_name = {}, {}, {}
    for v in routing.CANON.values():
        canon_val.setdefault(_canon(v), v)              # the INTENDED label (e.g. Ctie, LPD, Carron)
    for lbl in live:
        live_by_canon.setdefault(_canon(lbl), []).append(lbl)   # every Monday spelling per supplier
    for n in real:
        code_name.setdefault(_canon(n), n)
    suppliers = set()
    for k in {_canon(n) for n in real}:
        mondays = live_by_canon.get(k, [])
        intended = canon_val.get(k)
        if intended and intended in mondays:
            suppliers.add(intended)         # our intended label AND it's a real Monday option → ideal
        elif intended and not mondays:
            suppliers.add(intended)         # not on Monday yet → use our label
        elif mondays:
            suppliers.add(mondays[0])       # a real Monday option (writes land)
        else:
            suppliers.add(code_name[k])     # from the PO/phone map, not on Monday
    return {"suppliers": sorted(suppliers, key=str.lower), "stages": list(ds.OP_STAGES)}


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
    # NB: no `customer { … }` — that needs the read_customers scope the API token doesn't have, and
    # it would fail the whole query. Name/phone come from the order's own addresses (order scope).
    query = (
        "query($id: ID!) { order(id: $id) { name createdAt updatedAt displayFinancialStatus "
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
            sa, ba = o.get("shippingAddress") or {}, o.get("billingAddress") or {}
            # Name/phone from the order's own addresses (no read_customers scope needed).
            name = sa.get("name") or ba.get("name") or ""
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
            out["shopify"] = {
                "order_name": o.get("name"), "created_at": o.get("createdAt"),
                "updated_at": o.get("updatedAt"), "financial_status": o.get("displayFinancialStatus"),
                "customer": {"name": name, "email": None, "phone": sa.get("phone") or ba.get("phone")},
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


import functools   # noqa: E402
import re as _re    # noqa: E402


def _canon(s):
    """Canonical supplier key via the routing CANON map (mirrors order_processing._canon_sup)."""
    n = _re.sub(r"[^a-z0-9]", "", (s or "").lower())
    lbl = routing.CANON.get(n)
    return _re.sub(r"[^a-z0-9]", "", lbl.lower()) if lbl else n


@functools.lru_cache(maxsize=1)
def _feed_table():
    """{normalised SKU: {supplier_canon: cost}} from the pricing feed — Streamlit-free, loaded once."""
    import json
    try:
        path = Path(__file__).resolve().parent.parent / "pricing_lookup.json"
        d = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for it in d.get("items", []):
        sku = _re.sub(r"[^a-z0-9]", "", (it.get("sku") or "").lower())
        if sku:
            out[sku] = {_canon(o.get("s")): o.get("c") for o in (it.get("offers") or [])}
    return out


def _api_sole_feed_supplier(sku):
    """If the feed prices this SKU from exactly ONE supplier, return it — mirrors
    order_processing._sole_feed_supplier (same colour-suffix tolerance + NBP exclusion)."""
    key = _re.sub(r"[^a-z0-9]", "", (sku or "").lower())
    if len(key) < 5:
        return None
    pr = _feed_table()
    offers = pr.get(key)
    if not offers:
        offers = {}
        for k, v in pr.items():
            if len(k) >= 5 and (k.startswith(key) or key.startswith(k)):
                offers.update(v)
    excl = {_re.sub(r"[^a-z0-9]", "", s.lower()) for s in routing.EXCLUDED_SUPPLIERS}
    sups = {s for s, c in (offers or {}).items() if isinstance(c, (int, float)) and s not in excl}
    return routing.CANON.get(next(iter(sups))) if len(sups) == 1 else None


class RouteIn(BaseModel):
    shopify_id: str = ""
    apply: bool = False   # True = also write the suggested supplier/branch/stage to Monday


@app.post("/orders/{item_id}/route", dependencies=[Depends(require_key)])
def route(item_id: str, body: RouteIn):
    """Route an order with the SAME rules as the live app (order_routing.route_order + the feed
    sole-supplier resolver). Returns the suggestion; with apply=true it writes supplier/branch/stage
    to Monday. NEVER auto-advances to SEND PO here (no PO attached yet) — holds at Needs Review."""
    sid = (body.shopify_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="shopify_id is required to route")
    try:
        lines = ds.fetch_order_lines_with_vendor(sid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read order lines: {e}")
    try:
        pc = (ds.fetch_order_shipping(sid) or {}).get("postcode")
    except Exception:  # noqa: BLE001
        pc = None
    res = routing.route_order(lines, postcode=pc, sku_supplier=_api_sole_feed_supplier)
    suggestion = {
        "split": bool(res.get("split")), "supplier": res.get("overall_supplier"),
        "branch": res.get("branch"), "branch_email": res.get("branch_email"),
        "branch_phone": res.get("branch_phone"), "stage": res.get("stage"),
        "route": res.get("route"), "summary": routing.summary(res),
        "needs_branch": bool(res.get("needs_branch")), "conf": res.get("conf"),
    }
    applied, note = False, None
    if body.apply:
        route_ = res.get("route")
        sup = res.get("overall_supplier")
        in_house = (not sup) and route_ in ("SAMPLES", "CLEARANCE")
        if res.get("split"):
            note = "This order splits across suppliers — not auto-applied; handle the split separately."
        elif route_ == "PICK" or (not sup and not in_house):
            note = "Couldn't identify a single supplier — assign it manually."
        else:
            stage = res.get("stage") or "Needs Review"
            if stage == "SEND PO":            # never auto-send from here — no PO attached yet
                stage = "Needs Review"
            try:
                if sup:
                    ds.op_set_supplier(item_id, sup)
                    if res.get("branch") or res.get("branch_email") or res.get("branch_phone"):
                        ds.op_set_branch(item_id, branch=res.get("branch"),
                                         email=res.get("branch_email"), phone=res.get("branch_phone"))
                else:                         # SAMPLES / CLEARANCE — in-house, post from Head Office
                    import order_processing as op
                    ds.op_set_branch(item_id, branch=route_)
                    op._mark_del_method(item_id, route_)   # Del Method → "To Post"
                ds.op_set_status(item_id, stage)
                applied = True
                suggestion["applied_stage"] = stage
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Routed, but couldn't write to Monday: {e}")
    return {"ok": True, "suggestion": suggestion, "applied": applied, "note": note}


import datetime as _dt   # noqa: E402


def _fetch_one_order(item_id: str) -> dict | None:
    """One Monday order as fetch_new_orders shapes it (so _build_doc gets the exact same dict),
    fetched by item_id — avoids scanning the whole group per PO/process call."""
    ids = ",".join(f'"{c}"' for c in ds.OP_COLS.values())
    q = ("query($i:[ID!]){items(ids:$i){ id name assets{id name url public_url file_size} "
         "column_values(ids:[%s]){id text} }}" % ids)
    data = ds._monday_gql(q, {"i": [str(item_id)]}, ds.get_token())
    items = data.get("items") or []
    if not items:
        return None
    it = items[0]
    inv = {v: k for k, v in ds.OP_COLS.items()}
    row = {"item_id": it["id"], "name": it.get("name") or "",
           "po_assets": [{"id": a.get("id"), "name": a.get("name"), "url": a.get("url"),
                          "public_url": a.get("public_url"), "size": a.get("file_size")}
                         for a in (it.get("assets") or [])]}
    for cv in (it.get("column_values") or []):
        key = inv.get(cv.get("id"))
        if key:
            row[key] = cv.get("text") or ""
    return row


def _doc_kwargs(ov) -> dict:
    """Turn Adjust-panel overrides into _build_doc kwargs (address_override / delivery_override /
    notes_extra / items_override). Address may be a newline string or a list; blank fields ignored."""
    if not ov:
        return {}
    kw = {}
    addr = ov.get("address")
    if isinstance(addr, str):
        addr = [ln.strip() for ln in addr.splitlines() if ln.strip()]
    if addr:
        kw["address_override"] = list(addr)
    if ov.get("delivery") not in (None, ""):
        try:
            kw["delivery_override"] = float(ov["delivery"])
        except (TypeError, ValueError):
            pass
    notes = ov.get("notes")
    if isinstance(notes, str):
        notes = [notes.strip()] if notes.strip() else None
    if notes:
        kw["notes_extra"] = list(notes)
    items = ov.get("items")
    if items:
        rows = []
        for r in items:
            desc = (r.get("item") or "").strip()
            sku = (r.get("sku") or "").strip()
            if not (desc or sku):
                continue
            c = r.get("cost")
            try:
                cost = float(c) if c not in (None, "") else None
            except (TypeError, ValueError):
                cost = None
            rows.append({"SKU": sku, "Item": desc, "Qty": str(r.get("qty") or "1"), "Cost": cost})
        if rows:
            kw["items_override"] = rows
    return kw


def _editable_lines(op, o) -> list:
    """Current order lines as editable rows [{sku, item, qty, cost}] to pre-fill the PO editor —
    parsed from Monday with the routed supplier's own cost (None if unpriced)."""
    sup = o.get("supplier") or ""
    out = []
    for it in op._parse_monday_items(o.get("items")):
        out.append({"sku": it.get("SKU") or "", "item": it.get("Item") or "",
                    "qty": it.get("Qty") or "1",
                    "cost": op._line_cost(it.get("SKU"), sup, it.get("Item"))})
    return out


def _deliv_of(doc) -> float | None:
    """Recover the ex-VAT delivery £ from a PO doc (total = (goods+deliv)*1.2)."""
    t, g = doc.get("total"), doc.get("goods")
    if isinstance(t, (int, float)) and isinstance(g, (int, float)):
        return round(t / 1.2 - g, 2)
    return None


def _attach_doc(op, order_docs, item_id: str, o: dict, overrides=None) -> dict:
    """Build the PO/slip for order `o` (with any Adjust overrides) and attach it to Monday. Blocks
    (no attach) if validate_doc finds a problem (e.g. no Shopify shipping address)."""
    kind, doc = op._build_doc(o, **_doc_kwargs(overrides))
    errs = order_docs.validate_doc(doc, kind)
    if errs:
        return {"ok": False, "blocked": True, "kind": kind, "errors": errs}
    date_str = _dt.date.today().strftime("%d %B %Y")
    builder = order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf
    pdf = builder(doc, date_str=date_str)
    name = f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_Trade_Superstore_Online.pdf"
    r = ds.op_upload_po(item_id, pdf, name)
    ok = bool(r.get("ok"))
    try:
        op._write_po_total(item_id, kind, doc)   # numbers6 = £ supplier (PO inc-VAT total); POs only
    except Exception:  # noqa: BLE001 — best effort, never break the attach
        pass
    return {"ok": ok, "attached": ok, "blocked": False, "kind": kind, "name": name,
            "total": doc.get("total"), "detail": None if ok else "upload didn't verify — try again"}


class PoIn(BaseModel):
    address: str | None = None      # newline-separated delivery address override
    delivery: float | None = None   # delivery £ (ex VAT) override
    notes: str | None = None        # an extra note line for the PO
    items: list[dict] | None = None  # edited line rows [{sku, item, qty, cost}] — overrides the lines


@app.post("/orders/{item_id}/po", dependencies=[Depends(require_key)])
def generate_po(item_id: str, body: PoIn | None = None):
    """Generate the PO (or packing slip) and attach it — reuses order_processing._build_doc (Shopify-
    shipping-only address rule + never-cross pricing). Blocks (never attaches) on any missing field.
    Optional Adjust overrides (address / delivery / notes) are applied via _build_doc."""
    import order_processing as op
    import order_docs
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        res = _attach_doc(op, order_docs, item_id, o, overrides=(body.dict() if body else None))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't generate/attach the PDF: {e}")
    res["supplier"] = (o.get("supplier") or "") or None
    return res


@app.post("/orders/{item_id}/po-preview", dependencies=[Depends(require_key)])
def preview_po(item_id: str, body: PoIn | None = None):
    """Build the PO/slip WITHOUT attaching — for the Adjust panel. Returns the delivery address used,
    the priced lines, delivery £, total, any unpriced lines, and validation problems (e.g. missing
    address) so the user can fix them before generating."""
    import order_processing as op
    import order_docs
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        kind, doc = op._build_doc(o, **_doc_kwargs(body.dict() if body else None))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't build preview: {e}")
    errs = order_docs.validate_doc(doc, kind)
    # Editable rows to pre-fill the editor: echo the user's edits if they sent any, else the current
    # Monday lines with the routed supplier's own cost.
    editable = (body.items if (body and body.items) else _editable_lines(op, o))
    return {
        "kind": kind, "supplier": doc.get("supplier") or None, "dl": doc.get("dl") or [],
        "lines": doc.get("lines") or [], "unpriced": doc.get("unpriced") or [],
        "goods": doc.get("goods"), "delivery": _deliv_of(doc), "total": doc.get("total"),
        "errors": errs, "editable": editable,
    }


@app.post("/orders/{item_id}/split", dependencies=[Depends(require_key)])
def split_order(item_id: str):
    """Execute a split on Monday for an order that routes to 2+ suppliers (reuses
    order_processing._process_split: makes a part per supplier, prices + attaches each part's PO)."""
    import order_processing as op
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    sid = (o.get("shopify_id") or "").strip()
    if not sid:
        return {"ok": False, "result": "no Shopify ID — can't split"}
    try:
        lines = ds.fetch_order_lines_with_vendor(sid)
        pc = (ds.fetch_order_shipping(sid) or {}).get("postcode")
        res = routing.route_order(lines, postcode=pc, sku_supplier=_api_sole_feed_supplier)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't route for split: {e}")
    if not res.get("split"):
        return {"ok": False, "result": "this order routes to a single supplier — no split needed",
                "summary": routing.summary(res)}
    try:
        msg = op._process_split(o, res)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Split failed: {e}")
    return {"ok": True, "result": msg, "summary": routing.summary(res)}


@app.get("/orders/{item_id}/split-lines", dependencies=[Depends(require_key)])
def split_lines(item_id: str):
    """The order's lines with a SUGGESTED supplier per line (from routing) — pre-fills the manual
    split picker. The user can reassign, then POST /split-manual."""
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    sid = (o.get("shopify_id") or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="No Shopify ID — can't read lines")
    try:
        lines = ds.fetch_order_lines_with_vendor(sid)
        pc = (ds.fetch_order_shipping(sid) or {}).get("postcode")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read order lines: {e}")
    out = []
    for ln in lines:
        try:
            r = routing.route_line(ln, area_pc=pc, sku_supplier=_api_sole_feed_supplier)
        except Exception:  # noqa: BLE001
            r = {}
        out.append({"sku": ln.get("sku"), "title": ln.get("title"), "qty": ln.get("qty"),
                    "line_subtotal": ln.get("line_subtotal"), "supplier": (r.get("supplier") or "")})
    return {"lines": out}


class SplitManualIn(BaseModel):
    lines: list[dict]   # [{sku, title, qty, line_subtotal, supplier}] — supplier chosen per line


@app.post("/orders/{item_id}/split-manual", dependencies=[Depends(require_key)])
def split_manual_do(item_id: str, body: SplitManualIn):
    """Create a split from the user's manual line→supplier assignment (reuses _process_split):
    groups the lines by chosen supplier and makes a Monday part per supplier with its own PO."""
    import order_processing as op
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    routed = []
    for L in (body.lines or []):
        sup = (L.get("supplier") or "").strip()
        if not sup:
            raise HTTPException(status_code=400, detail="Every line needs a supplier assigned")
        qty = L.get("qty")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            qty = qty
        routed.append({"sku": L.get("sku"), "title": L.get("title"), "qty": qty,
                       "line_subtotal": L.get("line_subtotal"), "supplier": sup, "route": sup,
                       "quote": False, "portal": sup in routing.PORTAL,
                       "branch": None, "branch_email": None})
    groups = {}
    for l in routed:
        groups.setdefault(l["route"], []).append(l)
    if len(groups) < 2:
        return {"ok": False, "result": "assign lines to at least TWO different suppliers to split"}
    res = {"split": True, "groups": groups, "lines": routed, "overall_supplier": None}
    try:
        msg = op._process_split(o, res)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Split failed: {e}")
    return {"ok": True, "result": msg}


def _part_out(p: dict) -> dict:
    items = p.get("items") or ""
    summary = "; ".join(ln.split("|")[0].strip() for ln in items.splitlines() if ln.strip())
    return {"item_id": p.get("item_id"), "name": p.get("name"),
            "supplier": (p.get("supplier") or "") or None, "items": summary[:160]}


@app.get("/orders/{item_id}/siblings", dependencies=[Depends(require_key)])
def order_siblings(item_id: str):
    """The split-part siblings of an order (31824-1, -2, …) for the Merge panel. Empty if not split."""
    import order_processing as op
    try:
        rows = ds.fetch_new_orders()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read orders: {e}")
    o = next((r for r in rows if str(r.get("item_id")) == str(item_id)), None)
    if not o:
        return {"siblings": []}
    sibs = op._split_parts(o, rows)
    return {"siblings": [_part_out(p) for p in sibs]}


class MergeIn(BaseModel):
    part_item_ids: list[str]
    target_supplier: str


@app.post("/orders/merge", dependencies=[Depends(require_key)])
def merge_parts(body: MergeIn):
    """Merge selected split parts into one part fulfilled by target_supplier (reuses
    order_processing._merge_parts: combines lines, regenerates the PO, archives absorbed parts)."""
    import order_processing as op
    if not body.part_item_ids or len(body.part_item_ids) < 2:
        raise HTTPException(status_code=400, detail="Pick at least two parts to merge")
    try:
        rows = ds.fetch_new_orders()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read orders: {e}")
    by_id = {str(r.get("item_id")): r for r in rows}
    selected = [by_id[i] for i in body.part_item_ids if i in by_id]
    if len(selected) < 2:
        raise HTTPException(status_code=404, detail="Couldn't find the selected parts")
    all_sibs = op._split_parts(selected[0], rows)
    try:
        msg = op._merge_parts(selected, body.target_supplier, all_sibs)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Merge failed: {e}")
    return {"ok": True, "result": msg}


# ---- Statement reconciliation (Phase A: upload a statement → match against QuickBooks) -----------
@app.get("/recon/status", dependencies=[Depends(require_key)])
def recon_status():
    """Is QuickBooks connected, and which company — shown at the top of the recon screen."""
    try:
        connected = bool(ds.qbo_is_connected())
    except Exception:  # noqa: BLE001
        connected = False
    company = None
    if connected:
        try:
            company = ds.qbo_company_name()
        except Exception:  # noqa: BLE001
            company = None
    return {"qbo_connected": connected, "company": company}


def _enrich_num(v):
    if v in (None, ""):
        return None
    t = _re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(t) if t not in ("", "-", ".", "-.") else None
    except ValueError:
        return None


def _statement_monday_enrich(invoice_numbers: list) -> dict:
    """For each statement invoice number, look up its subitem on the Monday invoices board (one
    batched query) → {invoice_no: {monday_status, order_no (incl. -1/-2 split suffix), is_split,
    margin}}. order_no comes from the PARENT order item name; margin from the parent's sell/cost."""
    nums = [str(n).strip() for n in (invoice_numbers or []) if str(n).strip()]
    if not nums:
        return {}
    q = ('query($b:ID!,$vals:[String]!){items_page_by_column_values(board_id:$b,limit:500,'
         'columns:[{column_id:"name",column_values:$vals}]){items{id name '
         'column_values(ids:["status7__1"]){id text} '
         'parent_item{name column_values(ids:["text_mkv6z0nt","numbers48","numbers6"]){id text}}}}}')
    out = {}
    tok = ds.get_token()
    for i in range(0, len(nums), 50):
        chunk = nums[i:i + 50]
        try:
            data = ds._monday_gql(q, {"b": str(ds.SUBITEMS_BOARD_ID), "vals": chunk}, tok)
        except Exception:  # noqa: BLE001
            continue
        for it in (((data.get("items_page_by_column_values") or {}).get("items")) or []):
            cvs = {c["id"]: (c.get("text") or "") for c in (it.get("column_values") or [])}
            parent = it.get("parent_item") or {}
            pcv = {c["id"]: (c.get("text") or "") for c in (parent.get("column_values") or [])}
            sell, cost = _enrich_num(pcv.get("numbers48")), _enrich_num(pcv.get("numbers6"))
            margin = round((sell - cost) / sell * 100, 1) if (sell and cost is not None and sell > 0) else None
            pname = (parent.get("name") or "").strip()
            out[str(it.get("name") or "").strip()] = {
                "monday_status": cvs.get("status7__1") or "",
                "order_no": pname or (pcv.get("text_mkv6z0nt") or ""),
                "is_split": bool(_re.search(r"-\d+$", pname)),
                "margin": margin,
            }
    return out


@app.post("/recon", dependencies=[Depends(require_key)])
async def recon(file: UploadFile = File(...), supplier: str = Form(default="")):
    """Upload a supplier statement (PDF, or text/CSV) → parse it (reuses read_statement_pdf) → match
    every invoice line to the vendor's QuickBooks bills (recon_core.reconcile). Read-only: shows
    outstanding / paid / missing, overdue flags and credit notes. No writes in this phase."""
    import recon_core
    by = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".pdf"):
            stmt = ds.read_statement_pdf(pdf_bytes=by)
        else:
            stmt = ds.read_statement_pdf(text=by.decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the statement: {e}")
    sup = (supplier or "").strip() or (stmt.get("supplier") or "")
    # Resolve the QuickBooks vendor: learned mapping first, then auto-match by name.
    vid = vname = None
    try:
        mp = (ds.qbo_vendor_map_load() or {}).get(recon_core.norm_code(sup))
    except Exception:  # noqa: BLE001
        mp = None
    if mp:
        vid, vname = mp.get("id"), mp.get("name")
    if not vid:
        try:
            auto = ds.qbo_find_vendor(sup)
        except Exception:  # noqa: BLE001
            auto = None
        if auto:
            vid, vname = auto.get("id"), auto.get("name")
    if not vid:
        return {"ok": False, "need_vendor": True, "supplier": sup,
                "statement_date": stmt.get("statement_date"), "balance": stmt.get("balance"),
                "detail": f"No QuickBooks vendor match for “{sup}”. Map it in the live app for now "
                          "(we'll add vendor-picking here in Phase B)."}
    if vname:
        sup = vname                         # the QuickBooks vendor name is the authoritative payee
    try:
        bills = ds.qbo_vendor_bills(vid)
        try:
            paymap = ds.qbo_vendor_payments(vid)
        except Exception:  # noqa: BLE001
            paymap = {}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read QuickBooks bills: {e}")
    rec = recon_core.reconcile(stmt, bills, paymap, sup)
    # Enrich each row with Monday: stage, the parent order no (with any -1/-2 split), and margin.
    try:
        enrich = _statement_monday_enrich([r.get("invoice") for r in (rec.get("rows") or [])])
        for r in (rec.get("rows") or []):
            e = enrich.get(str(r.get("invoice") or "").strip())
            if e:
                r.update(monday_status=e.get("monday_status"), order_no=e.get("order_no"),
                         is_split=e.get("is_split"), margin=e.get("margin"))
    except Exception:  # noqa: BLE001
        pass
    rec.update(ok=True, supplier=sup, vendor_id=vid, vendor_name=vname,
               statement_date=stmt.get("statement_date"), balance=stmt.get("balance"),
               filename=file.filename)
    # Persist the latest reconciliation for this supplier (one per vendor; Supabase + Monday blob).
    try:
        snap = dict(rec)
        snap["vid"] = vid
        snap["saved_at"] = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        ds.recon_save(f"v{vid}", snap)
    except Exception:  # noqa: BLE001
        pass
    return rec


@app.get("/recon/saved", dependencies=[Depends(require_key)])
def recon_saved():
    """The latest saved reconciliation per supplier — with a LIVE re-check against QuickBooks: any
    statement whose ready-to-pay bills are now all paid is auto-removed (and dropped from the store).
    Returns light summaries; open one with /recon/open."""
    try:
        allsnaps = ds.recon_load_all() or {}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't load saved reconciliations: {e}")
    out = []
    for key, snap in allsnaps.items():
        vid = str(snap.get("vid") or "")
        pay_lines = snap.get("pay_lines") or []
        to_pay = snap.get("to_pay") or 0
        n_out = snap.get("n_pay") or 0
        try:
            if vid and pay_lines:
                bills = ds.qbo_vendor_bills(vid)
                open_ids = {str(b["id"]) for b in bills if not b.get("paid")}
                outstanding = [pl for pl in pay_lines if str(pl.get("bill_id")) in open_ids]
                to_pay = round(sum(float(pl.get("amt") or 0) for pl in outstanding), 2)
                n_out = len(outstanding)
                if not outstanding:                      # all paid → auto-remove
                    try:
                        ds.recon_delete(key, vid=vid)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
        except Exception:  # noqa: BLE001 — if QB can't be read, keep the snapshot as-is
            pass
        if not pay_lines and (snap.get("n_pay") or 0) == 0:   # nothing ever to pay → done
            try:
                ds.recon_delete(key, vid=vid)
            except Exception:  # noqa: BLE001
                pass
            continue
        out.append({"key": key, "vid": vid,
                    "supplier": snap.get("vendor_name") or snap.get("supplier"),
                    "statement_date": snap.get("statement_date"), "saved_at": snap.get("saved_at"),
                    "to_pay": to_pay, "n_pay": n_out, "n_missing": snap.get("n_missing") or 0})
    out.sort(key=lambda s: str(s.get("saved_at") or ""), reverse=True)
    return {"saved": out}


def _norm_recon_row(r: dict) -> dict:
    """Bring a stored reconciliation row up to the current shape. Older snapshots stored rows under
    legacy keys (inv/amt/date/order_ref), which render as empty in the new table — map them here so
    reopened statements always show real data."""
    if not isinstance(r, dict):
        return {}
    if r.get("invoice"):
        return r                                             # already current shape
    amt = r.get("amount") if r.get("amount") is not None else r.get("amt")
    unpaid = r.get("unpaid")
    if unpaid is None:
        unpaid = r.get("balance") if r.get("balance") is not None else amt
    return {
        "invoice": r.get("invoice") or r.get("inv") or "",
        "order": r.get("order") or r.get("order_ref") or "",
        "order_no": r.get("order_no"),
        "inv_date": r.get("inv_date") or r.get("date") or "",
        "amount": amt,
        "unpaid": unpaid,
        "due_date": r.get("due_date") or r.get("stmt_due") or "",
        "paid_ref": r.get("paid_ref") or "",
        "status": r.get("status") or "",
        "overdue": r.get("overdue", False),
        "monday_status": r.get("monday_status"),
        "is_split": r.get("is_split"),
        "margin": r.get("margin"),
    }


@app.get("/recon/open", dependencies=[Depends(require_key)])
def recon_open(key: str):
    """Return a saved reconciliation's full snapshot (rows etc.) so it can be reopened without
    re-uploading the statement. Legacy snapshots are normalised; if their rows are unrecoverable the
    table is rebuilt from the still-valid pay_lines so a reopened statement never shows empty rows."""
    try:
        snap = (ds.recon_load_all() or {}).get(key)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't load the reconciliation: {e}")
    if not snap:
        raise HTTPException(status_code=404, detail="Saved reconciliation not found")
    snap = dict(snap)
    rows = [_norm_recon_row(r) for r in (snap.get("rows") or [])]
    rows = [r for r in rows if r]
    pay_lines = snap.get("pay_lines") or []
    if pay_lines and not any((r.get("invoice") or "").strip() for r in rows):
        # Rows are old/blank but the pay list is good → rebuild the outstanding rows from it.
        rebuilt = []
        for pl in pay_lines:
            inv = str(pl.get("inv") or "").strip()
            if not inv:
                continue
            rebuilt.append({
                "invoice": inv, "order": pl.get("order") or "",
                "inv_date": pl.get("inv_date") or "", "amount": pl.get("amt"),
                "unpaid": pl.get("amt"), "due_date": pl.get("due_date") or "",
                "paid_ref": "", "status": "ready", "overdue": pl.get("overdue", False),
            })
        try:                                                  # re-enrich with Monday stage/order/margin
            enrich = _statement_monday_enrich([r["invoice"] for r in rebuilt])
            for r in rebuilt:
                e = enrich.get(r["invoice"])
                if e:
                    r.update(monday_status=e.get("monday_status"), order_no=e.get("order_no"),
                             is_split=e.get("is_split"), margin=e.get("margin"))
        except Exception:  # noqa: BLE001
            pass
        rows = rebuilt
    # Recompute overdue live from the invoice date — a stored flag goes stale as months pass, and
    # older snapshots never had it, which is why the overdue tag was missing on reopen.
    import recon_core
    for r in rows:
        r["overdue"] = recon_core.is_overdue(r.get("inv_date"))
    for pl in pay_lines:
        pl["overdue"] = recon_core.is_overdue(pl.get("inv_date"))
    snap["rows"] = rows
    snap["pay_lines"] = pay_lines
    return snap


# ---- Phase B: pay the bills in QuickBooks + draft the remittance -------------------------------
_ACCOUNTS_MAILBOX = "accounts@tradesuperstoreonline.co.uk"


@app.get("/recon/bank-accounts", dependencies=[Depends(require_key)])
def recon_bank_accounts():
    """QuickBooks bank accounts for the 'pay from' picker."""
    try:
        return {"accounts": ds.qbo_bank_accounts()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read QuickBooks bank accounts: {e}")


class PayIn(BaseModel):
    vendor_id: str
    bank_id: str
    ref: str = ""
    lines: list[dict]   # [{bill_id, amount}]


@app.post("/recon/pay", dependencies=[Depends(require_key)])
def recon_pay(body: PayIn):
    """Record a QuickBooks bill payment that settles the selected bills (marks them paid). FINANCIAL
    WRITE — the front-end confirms first. The money is still moved via the bank separately; this only
    records it in QuickBooks. Credit notes can't be applied via the API — handled in QB by hand."""
    lines = [{"bill_id": str(l.get("bill_id")), "amount": float(l.get("amount") or 0)}
             for l in (body.lines or []) if l.get("bill_id")]
    if not lines:
        return {"ok": False, "detail": "no bills selected to pay"}
    ref = (body.ref or "").strip() or "REM"
    total = round(sum(l["amount"] for l in lines), 2)
    try:
        ds.qbo_pay_bills(body.vendor_id, body.bank_id, lines, memo=ref, doc_no=ref,
                         date=_dt.date.today().strftime("%Y-%m-%d"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": str(e)[:220]}
    try:
        import supabase_db
        if supabase_db.configured():
            supabase_db.audit("", "bill_payment", f"{len(lines)} invoice(s) £{total:,.2f}", ref)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "paid": len(lines), "total": total, "ref": ref}


class RemitIn(BaseModel):
    supplier: str = ""
    ref: str = ""
    to_email: str = ""
    total: float = 0.0
    inv_lines: list[dict] = []   # selected pay_lines
    credits: list[dict] = []     # credit notes to net off


@app.post("/recon/remittance", dependencies=[Depends(require_key)])
def recon_remittance(body: RemitIn):
    """Build the branded remittance-advice PDF and create an Outlook DRAFT to the supplier (never
    auto-sent — a person reviews and sends it). Returns the PDF (base64) to download too."""
    import base64
    ref = (body.ref or "").strip() or "REM"
    pdf_lines = [{"bill_no": l.get("bill_no") or l.get("inv"), "bill_date": l.get("inv_date"),
                  "due_date": l.get("due_date"), "original": l.get("amt"),
                  "balance": l.get("balance") if l.get("balance") is not None else l.get("amt"),
                  "payment": l.get("amt")} for l in (body.inv_lines or [])]
    pdf_lines += [{"bill_no": "CN " + str(c.get("ref") or ""), "bill_date": c.get("date"),
                   "due_date": None, "original": c.get("amount"), "balance": c.get("amount"),
                   "payment": c.get("amount")} for c in (body.credits or [])]
    if not pdf_lines:
        return {"ok": False, "detail": "nothing selected for the remittance"}
    try:
        pdf = ds.build_remittance_pdf(body.supplier, ref, _dt.date.today().strftime("%d/%m/%Y"),
                                      pdf_lines, round(body.total, 2))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't build the remittance PDF: {e}")
    pdf_name = ("Remittance_Advice_" + _re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_")
                + "_from_Trade_Superstore_Online.pdf")
    cover = (f"Hi,\n\nPlease find attached our remittance advice ({ref}) for a total of "
             f"£{body.total:,.2f}.\n\nKind regards,\nTrade Superstore Online\nAccounts")
    draft_link = None
    if (body.to_email or "").strip():
        try:
            draft_link = ds.create_supplier_draft(_ACCOUNTS_MAILBOX, body.to_email.strip(),
                                                  f"Remittance Advice — {ref}", cover,
                                                  pdf_bytes=pdf, pdf_name=pdf_name)
        except Exception:  # noqa: BLE001
            draft_link = None     # still return the PDF so it can be downloaded/sent manually
    return {"ok": True, "pdf_b64": base64.b64encode(pdf).decode(), "pdf_name": pdf_name,
            "draft_link": draft_link, "to_email": (body.to_email or "").strip()}


# ---- Invoice checker (Phase A: list Needs-Review invoices → 3-way check → verdict) --------------
_NEEDS_REVIEW_LABEL = 3   # Subitems board "Payment Status" = Needs Review


@functools.lru_cache(maxsize=1)
def _inv_idx(stamp):
    import json
    import invoice_core as core
    try:
        lookup = json.load(open(Path(__file__).resolve().parent.parent / "pricing_lookup.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        lookup = {"items": []}
    pidx = core.pricelist_index(lookup)
    tidx = core.supplier_title_index(lookup)
    cidx = core.supplier_code_index(pidx)
    return pidx, tidx, cidx


def _inv_indexes():
    try:
        stamp = os.path.getmtime(str(Path(__file__).resolve().parent.parent / "pricing_lookup.json"))
    except OSError:
        stamp = 0.0
    return _inv_idx(stamp)


@app.get("/invoices", dependencies=[Depends(require_key)])
def invoices():
    """Invoices sitting in 'Needs Review' on the Monday invoices board (reuses
    fetch_invoices_by_status), excluded suppliers removed, with a same-£ possible-duplicate flag."""
    import invoice_core as core
    try:
        data = ds.fetch_invoices_by_status([_NEEDS_REVIEW_LABEL], limit=500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read invoices from Monday: {e}")
    invs = [i for i in (data.get("invoices") or []) if not core.is_excluded_supplier(i.get("supplier"))]
    amt_dups = core.amount_dup_ids(invs)
    out = [{"sub_id": str(i.get("sub_id")), "invoice_no": i.get("invoice_no"),
            "supplier": i.get("supplier"), "order_no": i.get("order_no"), "total": i.get("total"),
            "margin": i.get("order_margin_live"), "has_pdf": bool(i.get("asset_id")),
            "possible_dup": amt_dups.get(str(i.get("sub_id")))} for i in invs]
    return {"count": len(out), "invoices": out}


@app.post("/invoices/{sub_id}/check", dependencies=[Depends(require_key)])
def invoice_check(sub_id: str, lo: float | None = None, hi: float | None = None):
    """Run the SAME 3-way check the live app/runner uses (invoice_core.check_invoice): invoice PDF vs
    the supplier's pricelist cost vs the order's SKUs/quantities. Read-only — returns the verdict,
    line-by-line issues, margin and the suggested action. Parse is cached (Supabase) to avoid re-
    reading the PDF with Claude each time."""
    import invoice_core as core
    try:
        data = ds.fetch_invoices_by_status([_NEEDS_REVIEW_LABEL], limit=500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read invoices from Monday: {e}")
    inv = next((i for i in (data.get("invoices") or []) if str(i.get("sub_id")) == str(sub_id)), None)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found in Needs Review")
    if not inv.get("asset_id"):
        return {"ok": False, "detail": "no PDF attached to this invoice"}
    parsed = None
    try:
        import supabase_db
        if supabase_db.configured():
            parsed = supabase_db.invoice_parse_get(f"sub:{sub_id}")
    except Exception:  # noqa: BLE001
        parsed = None
    if not parsed:
        try:
            url = ds.monday_asset_url(inv["asset_id"])
            parsed = ds.read_invoice_pdf(url) if url else {"error": "no download link"}
        except Exception as e:  # noqa: BLE001
            parsed = {"error": str(e)}
        if parsed and not parsed.get("error"):
            try:
                import supabase_db
                if supabase_db.configured():
                    supabase_db.invoice_parse_set(f"sub:{sub_id}", parsed)
            except Exception:  # noqa: BLE001
                pass
    if not parsed or parsed.get("error"):
        return {"ok": False, "detail": "couldn't read the invoice PDF: " + str((parsed or {}).get("error") or "")[:140]}
    sup = inv.get("supplier")
    sid = inv.get("shopify_order_id")
    try:
        lines = ds.fetch_order_line_items(sid) if sid else None
    except Exception:  # noqa: BLE001
        lines = None
    order = core.order_candidates(lines, inv.get("order_items"))
    ship, sup_n = None, core.norm_code(sup)
    if (core.is_carron(sup_n) or core.is_ctie(sup_n)) and sid:
        try:
            ship = ds.fetch_order_shipping(sid)
        except Exception:  # noqa: BLE001
            ship = None
    pidx, tidx, cidx = _inv_indexes()
    res = core.check_invoice(parsed, sup, order, pidx, tidx, cidx, ship)
    matched = res["n_issues"] == 0
    is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
    _lo = lo if lo is not None else core.MARGIN_PUSH_MIN
    _hi = hi if hi is not None else core.MARGIN_PUSH_MAX
    label, action = core.push_decision(matched, is_cn, inv.get("order_margin_live"), sup, _lo, _hi)

    def _line_out(l):
        o = {k: v for k, v in l.items() if k != "issues" and not k.startswith("_")}
        o["issues"] = [list(x) for x in (l.get("issues") or [])]
        return o

    return {"ok": True, "matched": matched, "n_issues": res.get("n_issues"),
            "incomplete": res.get("incomplete"), "missing": res.get("missing") or [],
            "lines": [_line_out(l) for l in (res.get("lines") or [])],
            "verdict": core.verdict(res), "margin": inv.get("order_margin_live"),
            "supplier": sup, "invoice_no": inv.get("invoice_no"), "order_no": inv.get("order_no"),
            "total": parsed.get("total"),
            "suggested_action": action, "suggested_label": label,
            "discrepancy_reason": (None if matched else core.discrepancy_reason(res))}


_APPROVED_QB_LABEL = "Approved (To QB by TradeHub)"


class ApproveIn(BaseModel):
    invoice_no: str
    inv_date: str | None = None   # statement line date, used as a fallback if Monday has none


@app.post("/recon/approve", dependencies=[Depends(require_key)])
def recon_approve(body: ApproveIn):
    """Approve an invoice → create its bill in QuickBooks and mark the Monday subitem 'Approved (To
    QB by TradeHub)'. Mirrors the live app's _approve_to_quickbooks. FINANCIAL WRITE — the front-end
    confirms first. Never double-creates (checks the DocNumber)."""
    import recon_core
    name = (body.invoice_no or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="invoice_no required")
    try:
        det = (ds.subitems_bill_details([name]) or {}).get(name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the invoice on Monday: {e}")
    if not det:
        return {"ok": False, "detail": "couldn't find this invoice on Monday"}
    inv_date = (det.get("invoice_date") or body.inv_date or "")[:10]
    if not inv_date:
        return {"ok": False, "detail": "no invoice date on Monday or the statement — add one first"}
    total = det.get("total")
    if not isinstance(total, (int, float)) or total == 0:
        return {"ok": False, "detail": "no invoice total on Monday"}
    supplier = det.get("supplier") or ""
    try:
        vinfo = (ds.qbo_vendor_map_load() or {}).get(recon_core.norm_code(supplier))
        vid = vinfo.get("id") if vinfo else None
        if not vid:
            v = ds.qbo_find_vendor(supplier)
            vid = v.get("id") if v else None
    except Exception:  # noqa: BLE001
        vid = None
    if not vid:
        return {"ok": False, "detail": f"couldn't match supplier “{supplier}” to a QuickBooks vendor"}
    # Backfill the invoice date onto Monday if it was only on the statement.
    if not det.get("invoice_date") and det.get("sub_id"):
        try:
            ds.set_subitem_text(det["sub_id"], "date_mm3d1ear", inv_date)
        except Exception:  # noqa: BLE001
            pass
    try:
        if ds.qbo_bill_exists(name):
            created = "already on QuickBooks"
        else:
            ds.qbo_create_bill(vid, name, total, txn_date=inv_date, description=name,
                               private_note=det.get("parent_name"))
            created = f"bill created in QuickBooks (£{total:,.2f})"
        if det.get("sub_id"):
            try:
                ds.set_invoice_status(det["sub_id"], _APPROVED_QB_LABEL, create_missing=True)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "detail": created}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": str(e)[:160]}


@app.post("/orders/{item_id}/process", dependencies=[Depends(require_key)])
def process_order(item_id: str):
    """One-click process: route the order → write supplier/branch/stage to Monday → generate + attach
    the PO/slip. Mirrors the live app's _process_one BUT never auto-advances to SEND PO (holds at
    Needs Review — emailing the supplier stays a separate, deliberate step). Splits / unidentifiable
    orders are handed back for manual handling rather than guessed."""
    import order_processing as op
    import order_docs
    o = _fetch_one_order(item_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    tag = o.get("name") or o.get("order_no") or item_id
    sid = (o.get("shopify_id") or "").strip()
    if not sid:
        return {"ok": False, "order": tag, "result": "no Shopify ID — skipped"}
    try:
        lines = ds.fetch_order_lines_with_vendor(sid)
        pc = (ds.fetch_order_shipping(sid) or {}).get("postcode")
        res = routing.route_order(lines, postcode=pc, sku_supplier=_api_sole_feed_supplier)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't route: {e}")
    if res.get("split"):
        return {"ok": False, "order": tag, "result": "splits across suppliers — handle manually",
                "summary": routing.summary(res)}
    sup, route_ = res.get("overall_supplier"), res.get("route")
    in_house = (not sup) and route_ in ("SAMPLES", "CLEARANCE")   # samples/clearance: post in-house, no PO
    if route_ == "PICK" or (not sup and not in_house):
        return {"ok": False, "order": tag, "result": "couldn't identify a supplier — assign manually"}
    # Routing sets stage = "SEND PO" only for clear, high-confidence, non-excluded matches (its
    # _po_autosend_ok + AUTO_SEND_PO kill switch). We hold those at Needs Review until the PO is
    # attached, then advance to SEND PO — exactly like the live app's _process_one. Every other
    # routed stage (Needs Review / Needs Quote / Go To Portal) is set straight away.
    intended = res.get("stage") or "Needs Review"
    init_stage = "Needs Review" if intended == "SEND PO" else intended
    try:
        if sup:
            ds.op_set_supplier(item_id, sup)
            o["supplier"] = sup
            if res.get("branch") or res.get("branch_email") or res.get("branch_phone"):
                ds.op_set_branch(item_id, branch=res.get("branch"), email=res.get("branch_email"),
                                 phone=res.get("branch_phone"))
                o["branch"] = res.get("branch") or o.get("branch")
                o["branch_email"] = res.get("branch_email") or o.get("branch_email")
            op._fix_po_email(item_id, sup, o)                   # correct PO email (Molan/Vista/…)
            op._fix_lpd_home_email(item_id, sup, sid, o, lines=res.get("lines"))  # LPD Home → lpdhome
        else:                                                   # SAMPLES / CLEARANCE — in-house, no supplier/PO
            ds.op_set_branch(item_id, branch=route_)
        op._mark_del_method(item_id, sup or route_)             # samples → "To Post" on Del Method
        ds.op_set_status(item_id, init_stage)
        o["stage"] = init_stage
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Routed, but couldn't write to Monday: {e}")
    try:
        doc_res = _attach_doc(op, order_docs, item_id, o)
    except Exception as e:  # noqa: BLE001
        if in_house:                                            # a slip hiccup must not block a sample
            return {"ok": True, "order": tag, "supplier": None, "route": route_, "stage": init_stage,
                    "result": f"→ {route_} · {init_stage} · Del Method “To Post” (slip skipped)"}
        raise HTTPException(status_code=502, detail=f"Supplier set, but PO failed: {e}")
    # Safe to SEND PO? Two guards (same as _process_one): PO verified-attached AND a branch email is
    # confirmed on Monday (read back) so the automation can't fire to nowhere.
    final_stage, auto_sent = init_stage, False
    if intended == "SEND PO" and doc_res.get("ok"):
        try:
            send_email = ds.op_get_branch_email(item_id)
        except Exception:  # noqa: BLE001
            send_email = o.get("branch_email")
        if send_email:
            try:
                ds.op_set_status(item_id, "SEND PO")
                final_stage, auto_sent = "SEND PO", True
                o["stage"] = "SEND PO"
            except Exception:  # noqa: BLE001
                pass
    who = sup or route_
    doc_res.update(order=tag, supplier=sup, stage=final_stage, route=route_)
    kind_up = (doc_res.get("kind") or ("slip" if in_house else "po")).upper()
    extra = " · Del Method “To Post”" if in_house else ""
    if doc_res.get("blocked"):
        doc_res["result"] = "supplier set — PO BLOCKED: " + "; ".join(doc_res.get("errors") or [])
    elif doc_res.get("ok"):
        tail = (" · → SEND PO (auto)" if auto_sent
                else " · held at Needs Review (not auto-sent)" if intended == "SEND PO"
                else f" · {final_stage}")
        doc_res["result"] = f"→ {who} · {kind_up} attached{tail}{extra}"
    else:
        doc_res["result"] = f"→ {who} · {'slip' if in_house else 'PO'} didn't attach{extra}"
    return doc_res


@app.get("/order-totals", dependencies=[Depends(require_key)])
def order_totals():
    """Live Shopify total + subtotal per order in the NEW ORDERS group, keyed by Monday item_id —
    so the board can warn when Monday's '£ to us' doesn't match the live Shopify total. One Monday
    call (item_id -> shopify_id) + ONE batched Shopify call (all orders via `nodes`), so it stays
    fast regardless of order count."""
    col = ds.OP_COLS["shopify_id"]
    mq = ("query($b:[ID!],$g:[String!]){boards(ids:$b){groups(ids:$g){"
          "items_page(limit:200){items{ id column_values(ids:[\"%s\"]){ text } }}}}}" % col)
    try:
        md = ds._monday_gql(mq, {"b": [str(ds.ORDERS_BOARD_ID)], "g": [ds.ORDERS_NEW_GROUP]},
                            ds.get_token())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read orders: {e}")
    boards = md.get("boards") or []
    groups = (boards[0].get("groups") if boards else []) or []
    items = ((groups[0].get("items_page") or {}).get("items") if groups else []) or []
    item_to_sid = {}
    for it in items:
        cvs = it.get("column_values") or []
        sid = (cvs[0].get("text") if cvs else "") or ""
        sid = sid.strip()
        if sid:
            item_to_sid[it["id"]] = sid
    if not item_to_sid:
        return {"totals": {}}
    gids = [f"gid://shopify/Order/{sid}" for sid in set(item_to_sid.values())]
    store = ds.get_secret("SHOPIFY_STORE")
    token = ds.shopify_products_token()
    sq = ("query($ids:[ID!]!){ nodes(ids:$ids){ ... on Order { id "
          "totalPriceSet{shopMoney{amount}} subtotalPriceSet{shopMoney{amount}} } } }")
    try:
        r = requests.post(f"https://{store}/admin/api/{_SHOPIFY_API}/graphql.json",
                          json={"query": sq, "variables": {"ids": gids}},
                          headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                          timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read Shopify totals: {e}")
    sid_tot = {}
    for n in ((payload.get("data") or {}).get("nodes") or []):
        if not n:
            continue
        sid = str(n.get("id") or "").rsplit("/", 1)[-1]
        if sid:
            sid_tot[sid] = {"total": _sm(n, "totalPriceSet"), "subtotal": _sm(n, "subtotalPriceSet")}
    out = {iid: sid_tot[sid] for iid, sid in item_to_sid.items() if sid in sid_tot}
    return {"totals": out}
