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


@app.on_event("startup")
def _start_scheduler():
    """Run the always-on triage scheduler inside this (always-on) API service, so email + quote
    triage no longer depend on the Streamlit app being open. A Supabase lease stops it double-running
    with the Streamlit worker. Disable with RUN_SCHEDULER=0."""
    try:
        import scheduler
        if scheduler.start():
            print("[scheduler] triage scheduler started")
    except Exception as e:  # noqa: BLE001
        print(f"[scheduler] not started: {e}")

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


# Extra passcode on the Statements/reconciliation section (financial data) — set
# TRADEHUB_STATEMENTS_KEY on the host to Daniela's private PIN. The recon endpoints require it in
# addition to the shared access key, via the X-TradeHub-Statements-Key header. If UNSET the section
# stays open (so nothing breaks before it's configured) — set it on the host to activate the lock.
_STATEMENTS_KEY = (os.environ.get("TRADEHUB_STATEMENTS_KEY") or "").strip()


def require_statements_key(x_tradehub_statements_key: str | None = Header(default=None)):
    """Guard the Statements section. 403 (not 401) on a bad PIN so the front-end can tell this apart
    from the shared-access-code gate and re-prompt for the statements passcode only."""
    if not _STATEMENTS_KEY:
        return  # no statements PIN configured → section open until TRADEHUB_STATEMENTS_KEY is set
    if not x_tradehub_statements_key or not hmac.compare_digest(x_tradehub_statements_key, _STATEMENTS_KEY):
        raise HTTPException(status_code=403, detail="Invalid or missing Statements passcode")


@app.get("/recon/lock-status")
def recon_lock_status():
    """Whether the Statements section has a passcode configured — so the front-end knows to prompt."""
    return {"locked": bool(_STATEMENTS_KEY)}


@app.get("/")
def root():
    return {"service": "tradehub-api", "status": "ok", "locked": bool(_ACCESS_KEY), "docs": "/docs"}


@app.get("/health")
def health():
    """Liveness probe for the host's health check."""
    return {"ok": True, "service": "tradehub-api"}


@app.get("/diag")
def diag(sweep: int = 0):
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
    # Why is the 'pay from' bank dropdown empty? Show the account-type spread (types only, no names).
    try:
        from collections import Counter
        accs = (ds.qbo_query("select Id, AccountType from Account where Active = true MAXRESULTS 600")
                .get("Account") or [])
        out["qbo_accounts"] = {"active_total": len(accs),
                               "by_type": dict(Counter(a.get("AccountType") for a in accs)),
                               "bank": sum(1 for a in accs if a.get("AccountType") == "Bank")}
    except Exception as e:  # noqa: BLE001
        out["qbo_accounts_error"] = str(e)[:160]
    try:
        out["bank_accounts_fn"] = len(ds.qbo_bank_accounts())   # exactly what the pay dropdown calls
    except Exception as e:  # noqa: BLE001
        out["bank_accounts_fn_error"] = str(e)[:160]
    if sweep:   # ?sweep=1 → DRY-run the 'clear ones already on Monday' matcher (diagnostic)
        try:
            import supabase_db as sdb
            frows = sdb.invoice_import_recent(limit=500, status="failed") or []
            nrm = lambda s: _re.sub(r"[^a-z0-9]", "", str(s or "").lower())
            invs = [(r.get("invoice_no") or "").strip() for r in frows if (r.get("invoice_no") or "").strip()]
            uniq = list(dict.fromkeys(invs))
            on_m = set()
            q = ('query($b:ID!,$vals:[String]!){items_page_by_column_values(board_id:$b,limit:500,'
                 'columns:[{column_id:"name",column_values:$vals}]){items{name}}}')
            tok = ds.get_token()
            for i in range(0, len(uniq), 50):
                data = ds._monday_gql(q, {"b": str(ds.SUBITEMS_BOARD_ID), "vals": uniq[i:i + 50]}, tok)
                for it in (((data.get("items_page_by_column_values") or {}).get("items")) or []):
                    on_m.add(nrm(it.get("name")))
            matched = [v for v in uniq if nrm(v) in on_m]
            out["import_sweep"] = {"failed": len(frows), "distinct_invoices": len(uniq),
                                   "would_clear": len(matched),
                                   "sample_match": matched[:10],
                                   "sample_no_match": [v for v in uniq if nrm(v) not in on_m][:15]}
        except Exception as e:  # noqa: BLE001
            out["import_sweep_error"] = str(e)[:200]
    # Background schedulers live in the always-on app host (a separate service), but they write their
    # config + last-run to the SAME Supabase — so surface them here to diagnose "auto isn't running".
    try:
        import supabase_db as sdb
        if out.get("supabase_configured"):
            jobs = {}
            for name in ("email_triage", "quote_triage", "invoice_import", "invoice_check"):
                cfg = sdb.config_get(name) or {}
                stat = sdb.config_get(name + "_status") or {}
                jobs[name] = {
                    "auto_enabled": bool(cfg.get("auto_enabled")),
                    "interval_min": cfg.get("interval_min"),
                    "last_run_at": stat.get("at"),
                    "last_reason": stat.get("reason"),
                    "last_ok": stat.get("ok"),
                    "last_error": (str(stat.get("error"))[:140] if stat.get("error") else None),
                }
            out["jobs"] = jobs
            # Invoice-import health: recent outcomes + the top reasons invoices were left unimported.
            try:
                from collections import Counter
                recent = sdb.invoice_import_recent(limit=400) or []
                by_status = Counter((r.get("status") or "?") for r in recent)
                fail_reasons = Counter()
                for r in recent:
                    if r.get("status") in ("failed", "ignored"):
                        d = (r.get("detail") or "").strip()
                        d = _re.sub(r"\b\d{4,}\b", "N", d)[:60]        # collapse ids so reasons group
                        fail_reasons[d or r.get("status")] += 1
                out["invoice_import_log"] = {
                    "sample": len(recent),
                    "by_status": dict(by_status),
                    "top_unimported_reasons": fail_reasons.most_common(12),
                }
            except Exception as e:  # noqa: BLE001
                out["invoice_import_log_error"] = str(e)[:140]
    except Exception as e:  # noqa: BLE001
        out["jobs_error"] = str(e)[:140]
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
            # Multi-supplier order → TradeHub splits it automatically (a part per supplier, each with
            # its own priced PO). Never emails a supplier (splits are excluded from PO auto-send).
            try:
                import order_processing as op
                o = _fetch_one_order(item_id)
                msg = op._process_split(o, res) if o else "couldn't load the order to split"
                applied = bool(o)
                suggestion["applied_stage"] = "Split"
                note = ("Multi-supplier order — TradeHub split it automatically: " + msg) if o else msg
            except Exception as e:  # noqa: BLE001
                note = "Multi-supplier order — auto-split failed: " + str(e)[:150]
        elif route_ == "WDL":
            try:
                ds.move_order_to_group(item_id, ds.WDL_GROUP)
                applied = True
                suggestion["applied_stage"] = "Windows, Doors & Lanterns"
                note = "Door order — moved to the Windows, Doors & Lanterns group."
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Couldn't move to Windows, Doors & Lanterns: {e}")
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
    built ONLY from the live Shopify order (never Monday's summary), with the routed supplier's own
    cost (None if unpriced). One row per Shopify line, so two sizes sharing a SKU stay separate."""
    sup = o.get("supplier") or ""
    sid = (o.get("shopify_id") or "").strip()
    out = []
    if not sid:
        return out
    for l in (ds.fetch_order_line_items(sid) or []):
        item = (l.get("base_title") or l.get("title") or "").strip()
        sku = (l.get("sku") or "").strip()
        out.append({"sku": sku, "item": item, "qty": str(l.get("qty") or 1),
                    "cost": op._line_cost(sku, sup, item, l.get("variant"))})
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


@app.post("/orders/auto-split", dependencies=[Depends(require_key)])
def orders_auto_split():
    """Scan the NEW ORDERS group and AUTO-SPLIT every order that routes to 2+ suppliers (a part per
    supplier, each with its own priced PO). Skips orders that are already split parts (name '...-N')
    and single-supplier orders. Never emails a supplier. Returns a per-order summary."""
    import re as _re
    import order_processing as op
    try:
        rows = ds.fetch_new_orders()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the orders board: {e}")
    done, single, errors = [], 0, []
    for row in rows:
        item_id = row.get("item_id")
        name = str(row.get("name") or row.get("order_no") or "").strip()
        if not item_id or _re.search(r"-\d+$", name):   # skip existing split parts
            continue
        sid = (row.get("shopify_id") or "").strip()
        if not sid:
            continue
        try:
            lines = ds.fetch_order_lines_with_vendor(sid)
            pc = (ds.fetch_order_shipping(sid) or {}).get("postcode")
            res = routing.route_order(lines, postcode=pc, sku_supplier=_api_sole_feed_supplier)
        except Exception as e:  # noqa: BLE001
            errors.append({"order": name, "error": str(e)[:120]})
            continue
        if not res.get("split"):
            single += 1
            continue
        try:
            o = _fetch_one_order(item_id)
            msg = op._process_split(o, res) if o else "couldn't load the order"
            done.append({"order": name, "result": msg})
        except Exception as e:  # noqa: BLE001
            errors.append({"order": name, "error": str(e)[:120]})
    return {"ok": True, "split": len(done), "single": single, "errors": errors, "done": done}


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
@app.get("/recon/status", dependencies=[Depends(require_key), Depends(require_statements_key)])
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


@app.post("/recon", dependencies=[Depends(require_key), Depends(require_statements_key)])
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


@app.get("/recon/saved", dependencies=[Depends(require_key), Depends(require_statements_key)])
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


@app.get("/recon/open", dependencies=[Depends(require_key), Depends(require_statements_key)])
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
    # Reflect LIVE QuickBooks so a reopened statement shows what's actually paid now: mark each row
    # paid/ready by its current bill status, and keep only still-open bills in the pay list.
    vid = str(snap.get("vid") or "")
    supplier = snap.get("vendor_name") or snap.get("supplier") or ""
    if vid:
        try:
            bills = ds.qbo_vendor_bills(vid)
            open_ids = {str(b["id"]) for b in bills if not b.get("paid")}
            bmap = {recon_core.norm_inv_no(b.get("doc_no"), supplier): b
                    for b in bills if b.get("doc_no")}
            for r in rows:
                b = bmap.get(recon_core.norm_inv_no(r.get("invoice"), supplier))
                if b and b.get("paid"):
                    r["status"] = "paid"
                elif b and r.get("status") != "paid":
                    r["status"] = "ready"
                elif not b:
                    r["status"] = r.get("status") or "missing"
            pay_lines = [pl for pl in pay_lines if str(pl.get("bill_id")) in open_ids]
        except Exception:  # noqa: BLE001 — if QB can't be read, keep the snapshot as-is
            pass
    snap["rows"] = rows
    snap["pay_lines"] = pay_lines
    return snap


# ---- Phase B: pay the bills in QuickBooks + draft the remittance -------------------------------
_ACCOUNTS_MAILBOX = "accounts@tradesuperstoreonline.co.uk"


@app.get("/recon/bank-accounts", dependencies=[Depends(require_key), Depends(require_statements_key)])
def recon_bank_accounts():
    """QuickBooks bank accounts for the 'pay from' picker."""
    try:
        return {"accounts": ds.qbo_bank_accounts()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read QuickBooks bank accounts: {e}")


@app.get("/recon/vendors", dependencies=[Depends(require_key), Depends(require_statements_key)])
def recon_vendors():
    """Active QuickBooks vendors for the statement-recon supplier picker — so the supplier is SELECTED
    (and matches QB exactly) instead of typed into a free-text box."""
    try:
        return {"vendors": ds.qbo_list_vendors()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read QuickBooks vendors: {e}")


class PayIn(BaseModel):
    vendor_id: str
    bank_id: str
    ref: str = ""
    lines: list[dict]   # [{bill_id, amount}]


@app.post("/recon/pay", dependencies=[Depends(require_key), Depends(require_statements_key)])
def recon_pay(body: PayIn):
    """Record a QuickBooks bill payment that settles the selected bills (marks them paid). FINANCIAL
    WRITE — the front-end confirms first. The money is still moved via the bank separately; this only
    records it in QuickBooks. Credit notes can't be applied via the API — handled in QB by hand."""
    lines = [{"bill_id": str(l.get("bill_id")), "amount": float(l.get("amount") or 0)}
             for l in (body.lines or []) if l.get("bill_id")]
    if not lines:
        return {"ok": False, "detail": "no bills selected to pay"}
    # Re-check every bill against LIVE QuickBooks before paying. A reopened/old statement can carry
    # bills that are already paid or whose balance has changed — QuickBooks rejects a BillPayment
    # that links a closed bill or over-pays one, which would fail the WHOLE payment. So drop bills
    # that no longer exist or are already paid, and clamp each amount to its current open balance.
    try:
        live = {str(b["id"]): b for b in (ds.qbo_vendor_bills(body.vendor_id) or [])}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"Couldn't re-check QuickBooks bills: {str(e)[:180]}"}
    clean, skipped_paid, missing = [], 0, 0
    for l in lines:
        b = live.get(l["bill_id"])
        if not b:
            missing += 1
            continue
        if b.get("paid"):
            skipped_paid += 1
            continue
        bal = b.get("balance")
        # Pay the lesser of what the statement said and the bill's current open balance.
        if isinstance(bal, (int, float)) and bal > 0:
            amt = round(min(l["amount"], float(bal)), 2)
        else:
            amt = round(l["amount"], 2)
        if amt > 0:
            clean.append({"bill_id": l["bill_id"], "amount": amt})
    if not clean:
        note = []
        if skipped_paid:
            note.append(f"{skipped_paid} already paid in QuickBooks")
        if missing:
            note.append(f"{missing} no longer in QuickBooks")
        return {"ok": False, "detail": "Nothing to pay — " + (", ".join(note) or "no open bills") +
                ". Reopen the statement to refresh it."}
    lines = clean
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
    return {"ok": True, "paid": len(lines), "total": total, "ref": ref,
            "skipped_paid": skipped_paid, "missing": missing}


class RemitIn(BaseModel):
    supplier: str = ""
    ref: str = ""
    to_email: str = ""
    total: float = 0.0
    inv_lines: list[dict] = []   # selected pay_lines
    credits: list[dict] = []     # credit notes to net off


@app.post("/recon/remittance", dependencies=[Depends(require_key), Depends(require_statements_key)])
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
_DISCREPANCY_LABEL = 4    # Subitems board "Payment Status" = Discrepancy (flagged/queried)


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
            "order_url": i.get("order_url"), "order_item_id": i.get("order_item_id"),
            "possible_dup": amt_dups.get(str(i.get("sub_id")))} for i in invs]
    return {"count": len(out), "invoices": out}


@app.get("/invoices/discrepancies", dependencies=[Depends(require_key)])
def invoice_discrepancies():
    """Invoices flagged 'Discrepancy' on the Monday invoices board — the ones that didn't match and
    were queried. Shows the reason that was written back to Monday (text_mm3gh2za) so the whole
    queried pile is visible in one place. Read-only."""
    try:
        data = ds.fetch_invoices_by_status([_DISCREPANCY_LABEL], limit=500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read invoices from Monday: {e}")
    invs = data.get("invoices") or []
    out = [{"sub_id": str(i.get("sub_id")), "invoice_no": i.get("invoice_no"),
            "supplier": i.get("supplier"), "order_no": i.get("order_no"), "total": i.get("total"),
            "margin": i.get("order_margin_live"), "has_pdf": bool(i.get("asset_id")),
            "reason": (i.get("query_note") or "").strip(),
            "sent": (i.get("action_note") or "").strip(),
            "flagged_on": i.get("date"), "order_url": i.get("order_url")} for i in invs]
    # Most recently flagged first (status change date).
    out.sort(key=lambda r: r.get("flagged_on") or "", reverse=True)
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
        # Multi-supplier order → TradeHub splits it automatically (a part per supplier, each with its
        # own priced PO). Never emails a supplier (splits are excluded from PO auto-send).
        try:
            msg = op._process_split(o, res)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Auto-split failed: {e}")
        return {"ok": True, "order": tag, "route": "SPLIT",
                "result": "multi-supplier — TradeHub split it automatically: " + msg,
                "summary": routing.summary(res)}
    sup, route_ = res.get("overall_supplier"), res.get("route")
    if route_ == "WDL":                                          # heritage/bifold/uPVC doors → Daniela's group
        try:
            ds.move_order_to_group(item_id, ds.WDL_GROUP)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Couldn't move to Windows, Doors & Lanterns: {e}")
        return {"ok": True, "order": tag, "route": "WDL",
                "result": "→ moved to Windows, Doors & Lanterns (door order — no PO)"}
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


# ---- Triage: native email triage (hello@ inbox) — same engine as the Streamlit app ------------
class TriageRunIn(BaseModel):
    dry_run: bool = True
    since_days: int | None = None
    max_total: int | None = 40


class TriageCfgIn(BaseModel):
    auto_enabled: bool = False
    interval_min: int = 10
    max_total: int = 40
    since_days: int | None = None


@app.post("/triage/run", dependencies=[Depends(require_key)])
def triage_run(body: TriageRunIn):
    """Classify + file new hello@ inbox mail into the Outlook folders (reuses email_triage.run_triage,
    the verbatim copy of the old Make scenario). dry_run=True previews without moving anything."""
    import email_triage
    try:
        res = email_triage.run_triage(dry_run=bool(body.dry_run),
                                      since_days=body.since_days,
                                      max_total=int(body.max_total or 40))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Triage failed: {e}")
    return res


@app.get("/triage/status", dependencies=[Depends(require_key)])
def triage_status():
    """Automatic-triage settings + the last scheduled/manual run summary (from Supabase config)."""
    try:
        import supabase_db
        cfg = supabase_db.config_get("email_triage") or {}
        status = supabase_db.config_get("email_triage_status") or {}
    except Exception:  # noqa: BLE001
        cfg, status = {}, {}
    return {"config": {"auto_enabled": bool(cfg.get("auto_enabled")),
                       "interval_min": int(cfg.get("interval_min") or 10),
                       "max_total": int(cfg.get("max_total") or 40),
                       "since_days": cfg.get("since_days")},
            "status": status}


@app.post("/triage/config", dependencies=[Depends(require_key)])
def triage_config(body: TriageCfgIn):
    """Turn automatic triage on/off and set the interval. The always-on worker (in the app host)
    reads this same config, so saving here controls the hands-off schedule."""
    try:
        import supabase_db
        cfg = supabase_db.config_get("email_triage") or {}
        cfg.update(auto_enabled=bool(body.auto_enabled), interval_min=int(body.interval_min),
                   max_total=int(body.max_total or 40))
        if body.since_days is not None:
            cfg["since_days"] = int(body.since_days)
        ok = supabase_db.config_set("email_triage", cfg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't save: {e}")
    if not ok:
        raise HTTPException(status_code=502, detail="Couldn't save (Supabase not configured).")
    return {"ok": True, "config": cfg}


class FindPdfIn(BaseModel):
    invoice_no: str
    supplier: str = ""


@app.post("/invoices/{sub_id}/find-pdf", dependencies=[Depends(require_key)])
def invoice_find_pdf(sub_id: str, body: FindPdfIn):
    """For an invoice subitem with NO PDF: hunt the accounts@ mailbox for the invoice's PDF (by
    invoice number, then supplier) and attach it to the Monday subitem so it can be checked."""
    inv = (body.invoice_no or "").strip()
    if not inv:
        return {"ok": False, "detail": "no invoice number to search for"}
    try:
        hit = ds.find_invoice_pdf_in_mail(inv, body.supplier or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't search Outlook: {e}")
    if not hit:
        return {"ok": True, "found": False,
                "detail": f"No PDF found in Outlook for invoice {inv}"}
    try:
        attached = ds.add_pdf_to_subitem_file(sub_id, hit["bytes"], hit.get("name") or f"{inv}.pdf")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Found a PDF but couldn't attach it: {e}")
    return {"ok": bool(attached), "found": True, "attached": bool(attached),
            "filename": hit.get("name"), "from": hit.get("from"), "subject": hit.get("subject"),
            "detail": (f"Attached “{hit.get('name')}” from {hit.get('from')}" if attached
                       else "Found a PDF but Monday didn't confirm the attachment — try again")}


@app.get("/invoices/suggest-order", dependencies=[Depends(require_key)])
def invoice_suggest_order(total: float, supplier: str = ""):
    """Confirm-first hint for a left-behind invoice: live orders whose cost/value matches the
    invoice amount (and supplier). Read-only — nothing is attached."""
    try:
        rows = ds.suggest_orders_by_amount(total, supplier or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't search Monday: {e}")
    return {"rows": rows}


class FlagIn(BaseModel):
    reason: str = ""


@app.post("/invoices/{sub_id}/flag", dependencies=[Depends(require_key)])
def invoice_flag(sub_id: str, body: FlagIn):
    """Flag an invoice as a Discrepancy on Monday (Payment Status → 'Discrepancy') and save the
    reason on the subitem, so it drops out of Needs Review into the discrepancy queue."""
    try:
        ds.set_invoice_status(sub_id, "Discrepancy")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't flag on Monday: {e}")
    if (body.reason or "").strip():
        try:
            ds.set_subitem_text(sub_id, "text_mm3gh2za", body.reason.strip()[:1500])
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


@app.post("/invoices/{sub_id}/unflag", dependencies=[Depends(require_key)])
def invoice_unflag(sub_id: str):
    """Move a flagged invoice back from 'Discrepancy' to 'Needs Review' (query resolved), so it
    returns to the main checker queue."""
    try:
        ds.set_invoice_status(sub_id, "Needs Review")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't move back to review on Monday: {e}")
    return {"ok": True}


class FixMarginsIn(BaseModel):
    sub_ids: list[str]


@app.post("/invoices/fix-margins", dependencies=[Depends(require_key)])
def invoice_fix_margins(body: FixMarginsIn):
    """Fix the order margin for the selected invoices: add any invoice totals that never made it into
    the order's INV columns on Monday (the cause of a bogus 98%-type margin). Duplicate-safe and
    deduped by order. Returns how many orders were touched and how many totals were filled in."""
    ids = {str(s) for s in (body.sub_ids or []) if s}
    if not ids:
        return {"ok": False, "detail": "No invoices selected."}
    try:
        data = ds.fetch_invoices_by_status([_NEEDS_REVIEW_LABEL], limit=500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read invoices from Monday: {e}")
    sel = [i for i in (data.get("invoices") or []) if str(i.get("sub_id")) in ids]
    done, filled = set(), 0
    for i in sel:
        oid = i.get("order_item_id")
        ono = (i.get("order_no") or "").strip()
        okey = oid or ono
        if not okey or okey in done:
            continue
        done.add(okey)
        try:
            if not oid and ono:
                o = ds.find_order_item_by_number(ono)
                oid = o.get("id") if o else None
            if oid:
                filled += ds.reconcile_order_inv_slots(oid)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "orders": len(done), "filled": filled}


@app.get("/invoices/{sub_id}/order", dependencies=[Depends(require_key)])
def invoice_order_view(sub_id: str, order_item_id: str | None = None):
    """The Monday-like order view for an invoice: the parent order (totals, margin, stage, supplier),
    its INV1..INV6 slots (and what's in each), and every sibling invoice on that order — so the whole
    order can be seen (and amended) from the checker without opening Monday. Pass order_item_id (the
    checker list already has it) so the order is read directly rather than via the subitem's parent."""
    try:
        view = ds.fetch_invoice_order_view(sub_id, order_item_id=order_item_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the order from Monday: {e}")
    if not view:
        raise HTTPException(status_code=404, detail="No parent order found for this invoice")
    return view


class NoteIn(BaseModel):
    note: str = ""


@app.post("/invoices/{sub_id}/note", dependencies=[Depends(require_key)])
def invoice_note(sub_id: str, body: NoteIn):
    """Save a note on an invoice (subitem Notes column, text_mm3gh2za) — for invoices stuck for any
    reason. Empty note clears it."""
    try:
        ds.set_subitem_text(sub_id, "text_mm3gh2za", (body.note or "")[:2000])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't save the note on Monday: {e}")
    return {"ok": True}


class OrderFieldIn(BaseModel):
    order_item_id: str
    col: str                       # must be one of ds.ORDER_EDITABLE_COLS (INV1..INV6 / numbers48 / numbers6)
    value: float | None = None     # None / "" clears the cell


@app.post("/invoices/order-set", dependencies=[Depends(require_key)])
def invoice_order_set(body: OrderFieldIn):
    """Amend an editable column on the parent ORDER from the checker: an INV1..INV6 slot, '£ to us'
    (numbers48) or '£ to supplier' (numbers6). Writes straight to Monday."""
    if body.col not in ds.ORDER_EDITABLE_COLS:
        raise HTTPException(status_code=400, detail="That column can't be edited from here")
    if not body.order_item_id:
        raise HTTPException(status_code=400, detail="order_item_id is required")
    try:
        ds.set_order_number(body.order_item_id, body.col, body.value)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't write to Monday: {e}")
    return {"ok": True}


@app.get("/invoices/import-issues", dependencies=[Depends(require_key)])
def invoice_import_issues(limit: int = 100):
    """Invoices that DIDN'T import as Monday subitems (newest first) — the 'no matching order' and
    unreadable ones — so they can be seen and chased instead of silently left."""
    try:
        import supabase_db
        rows = supabase_db.invoice_import_recent(limit=int(limit), status="failed") or []
    except Exception:  # noqa: BLE001
        rows = []
    out = []
    for r in rows:
        detail = r.get("detail") or ""
        m = _re.match(r"^\s*(\d{4}-\d{2}-\d{2})\s*·\s*(.*)$", detail)   # invoice date prefix, if present
        inv_date = m.group(1) if m else None
        why = m.group(2) if m else detail
        out.append({"id": r.get("internet_id"), "invoice_no": r.get("invoice_no"),
                    "supplier": r.get("supplier"), "order_no": r.get("order_no"),
                    "total": r.get("total"), "inv_date": inv_date, "detail": why, "at": r.get("at")})
    return {"rows": out}


class ClearIn(BaseModel):
    ids: list[str]


@app.post("/invoices/import-issues/clear-on-monday", dependencies=[Depends(require_key)])
def invoice_import_clear_on_monday():
    """Sweep the whole 'didn't import' list and clear every invoice whose number is ALREADY a
    subitem on Monday (batched — one query per 50 invoices, not one per invoice)."""
    try:
        import supabase_db
        rows = supabase_db.invoice_import_recent(limit=500, status="failed") or []
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read the list: {e}")
    norm = lambda s: _re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    by_norm = {}
    nums = []
    for r in rows:
        inv = (r.get("invoice_no") or "").strip()
        if not inv or not r.get("internet_id"):
            continue
        by_norm.setdefault(norm(inv), []).append(r["internet_id"])
        nums.append(inv)
    # Which of these invoice numbers exist as subitems (names) on the invoices subitems board?
    on_monday = set()
    q = ('query($b:ID!,$vals:[String]!){items_page_by_column_values(board_id:$b,limit:500,'
         'columns:[{column_id:"name",column_values:$vals}]){items{name}}}')
    try:
        tok = ds.get_token()
        uniq = list(dict.fromkeys(nums))
        for i in range(0, len(uniq), 50):
            chunk = uniq[i:i + 50]
            data = ds._monday_gql(q, {"b": str(ds.SUBITEMS_BOARD_ID), "vals": chunk}, tok)
            for it in (((data.get("items_page_by_column_values") or {}).get("items")) or []):
                on_monday.add(norm(it.get("name")))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't check Monday: {e}")
    ids = [iid for n, lst in by_norm.items() if n in on_monday for iid in lst]
    try:
        import supabase_db
        cleared = supabase_db.invoice_import_clear(ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't clear: {e}")
    return {"ok": True, "checked": len(rows), "on_monday": len(on_monday), "cleared": cleared}


@app.post("/invoices/import-issues/clear", dependencies=[Depends(require_key)])
def invoice_import_issues_clear(body: ClearIn):
    """Clear the selected failed-import rows (by id) off the 'didn't import' list — marked 'cleared',
    so they drop off AND won't be retried."""
    try:
        import supabase_db
        n = supabase_db.invoice_import_clear(body.ids)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't clear: {e}")
    return {"ok": True, "cleared": n}


@app.get("/triage/history", dependencies=[Depends(require_key)])
def triage_history(limit: int = 100, only_failed: bool = False):
    """Recent triage outcomes for the history view (newest first). only_failed → just the ones that
    didn't get filed."""
    try:
        import supabase_db
        rows = supabase_db.email_triage_recent(limit=int(limit),
                                               status="failed" if only_failed else None) or []
    except Exception:  # noqa: BLE001
        rows = []
    return {"rows": rows}


# ---- Pricing tab: supplier pricelists + delivery charges ---------------------------------------
_FEED_PATH = Path(__file__).resolve().parent.parent / "pricing_lookup.json"
_OV_PATH = Path(__file__).resolve().parent.parent / "price_overrides.json"
_DELIV_NAMES = {"upb": "UPB", "nbp": "NBP", "eurocell": "Eurocell", "travisperkins": "Travis Perkins",
                "gap": "GAP", "pjh": "PJH", "molan": "Molan", "decor8": "Decor8",
                "chasehardware": "Chase Hardware", "bricklink": "Bricklink", "markovitz": "Markovitz",
                "storm": "Storm"}


def _load_json(path):
    import json
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@app.get("/pricing/suppliers", dependencies=[Depends(require_key)])
def pricing_suppliers():
    """Suppliers we hold cost prices for, with how many priced SKUs each has (feed + overrides)."""
    from collections import Counter
    c = Counter()
    for it in (_load_json(_FEED_PATH).get("items") or []):
        for o in (it.get("offers") or []):
            if o.get("s"):
                c[o["s"]] += 1
    ov = _load_json(_OV_PATH)
    for sup, skus in ov.items():
        if not sup.startswith("_") and isinstance(skus, dict):
            # merge an override block onto a feed supplier of the same canonical name where possible
            disp = next((s for s in c if _canon(s) == _canon(sup)), sup)
            c[disp] += len(skus)
    return {"suppliers": [{"supplier": s, "count": n, "date": _pl_date_for(s)}
                          for s, n in sorted(c.items(), key=lambda x: (-x[1], x[0].lower()))]}


_TXN_FEE = 0.018   # Shopify transaction fee used for the net (after-fee) margin


def _norm_sku(s):
    return _re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _pl_date_for(supplier):
    """The supplier's own pricelist date (e.g. 'Oct 2026') from price_overrides '_pricelist_dates'."""
    for k, v in (_load_json(_OV_PATH).get("_pricelist_dates") or {}).items():
        if _canon(k) == _canon(supplier):
            return v
    return None


@app.get("/pricing/prices", dependencies=[Depends(require_key)])
def pricing_prices(supplier: str, q: str = "", limit: int = 500, sort: str = "sku", dir: str = "asc"):
    """This supplier's priced SKUs: ex-VAT cost (feed + overrides), the Shopify product name (or a
    'not on Shopify' flag), our sell price, and the net margin after the transaction fee. Sorted
    across the WHOLE matched set (by sku/cost/sell/margin) before the cap. `updated` is when the
    price feed was last rebuilt."""
    feed = _load_json(_FEED_PATH)
    updated = feed.get("generated_at")
    items = feed.get("items") or []
    sup_c = _canon(supplier)
    ql = (q or "").strip().lower()

    # Index every feed SKU's Shopify name + sell, and this supplier's feed cost.
    idx, sup_cost = {}, {}
    for it in items:
        ns = _norm_sku(it.get("sku"))
        if not ns:
            continue
        idx[ns] = {"sku": (it.get("sku") or "").strip(), "name": (it.get("name") or "").strip(),
                   "sell": it.get("sell") if isinstance(it.get("sell"), (int, float)) else None}
        for o in (it.get("offers") or []):
            if _canon(o.get("s")) == sup_c and isinstance(o.get("c"), (int, float)):
                sup_cost[ns] = o["c"]
                break

    # Overrides for this supplier WIN on cost (and add SKUs the feed doesn't price from them).
    ov_cost = {}
    for sup, skus in _load_json(_OV_PATH).items():
        if sup.startswith("_") or not isinstance(skus, dict) or _canon(sup) != sup_c:
            continue
        for sk, cst in skus.items():
            if isinstance(cst, (int, float)):
                ov_cost[_norm_sku(sk)] = (sk, cst)

    def _row(ns, cost, is_override, sku_fallback=None):
        info = idx.get(ns) or {}
        sku = info.get("sku") or sku_fallback or ns
        name = info.get("name") or ""
        sell = info.get("sell")
        on_shopify = bool(name)
        margin = None
        if isinstance(sell, (int, float)) and sell > 0 and isinstance(cost, (int, float)):
            margin = round((sell - cost - sell * _TXN_FEE) / sell * 100, 1)
        return {"sku": sku, "name": name, "on_shopify": on_shopify, "cost": cost,
                "sell": sell, "margin": margin, "source": "override" if is_override else "feed"}

    all_ns = set(sup_cost) | set(ov_cost)
    allrows = []
    for ns in all_ns:
        is_ov = ns in ov_cost
        cost = ov_cost[ns][1] if is_ov else sup_cost[ns]
        sk_fb = ov_cost[ns][0] if is_ov else None
        row = _row(ns, cost, is_ov, sk_fb)
        if ql and ql not in (row["sku"] or "").lower() and ql not in (row["name"] or "").lower():
            continue
        allrows.append(row)
    # Sort the WHOLE matched set before capping, so e.g. "lowest margin" shows the true worst.
    reverse = (dir or "asc").lower() == "desc"
    if sort in ("cost", "sell", "margin"):
        INF = float("inf")
        allrows.sort(key=lambda r: (r.get(sort) if isinstance(r.get(sort), (int, float)) else INF),
                     reverse=reverse)
    else:
        allrows.sort(key=lambda r: (r.get("sku") or "").lower(), reverse=reverse)
    total = len(allrows)
    rows = allrows[:limit]
    return {"rows": rows, "total": total, "capped": total > len(rows),
            "updated": updated, "fee_pct": round(_TXN_FEE * 100, 2),
            "pricelist_date": _pl_date_for(supplier)}


_UMBRELLA_BUILDING = "Building materials"   # cladding/roofline + building plastics + builders' merchants
_DELIV_CATEGORY = {
    "upb": _UMBRELLA_BUILDING, "ajw": _UMBRELLA_BUILDING, "southern sheeting": _UMBRELLA_BUILDING,
    "nbp": _UMBRELLA_BUILDING, "eurocell": _UMBRELLA_BUILDING,
    "travis perkins": _UMBRELLA_BUILDING, "markovitz": _UMBRELLA_BUILDING, "gap": _UMBRELLA_BUILDING,
    "bricklink": _UMBRELLA_BUILDING,
    "pjh": "Bathrooms & plumbing", "carron": "Bathrooms & plumbing",
    "molan": "Polycarbonate & roofing", "storm": "Polycarbonate & roofing",
    "decor8": "Paint & decorating",
    "chase hardware": "Ironmongery & hardware",
    "ctie": "Electricals",
    "jb kind": "Internal doors", "lpd": "Internal doors", "deanta": "Internal doors",
    "dolle": "Stairs & loft ladders",
}


def _cat_for(name):
    return _DELIV_CATEGORY.get((name or "").lower().split(" (")[0].strip(), "Other")


def _door_detail(base, step, cap, max_doors, extra_rows):
    """Per-door band table [[label, '£x.xx'], ...] for a door supplier (base + step/door, capped)."""
    rows = []
    for d in range(1, max_doors + 1):
        amt = min(base + (d - 1) * step, cap)
        label = f"{d} door{'s' if d > 1 else ''}"
        if amt >= cap:
            rows.append([f"{d}+ doors (cap)", f"£{cap:,.2f}"])
            break
        rows.append([label, f"£{amt:,.2f}"])
    return {"title": "Per door (ex VAT) — before any area surcharge",
            "headers": ["Doors", "We pay"], "rows": rows + extra_rows}


def _delivery_catalog():
    """Per-supplier delivery: what the supplier charges US (ex VAT) and what we charge the CUSTOMER,
    grouped by category. Door suppliers + AJW carry an expandable `detail` table. Flat rules come
    from delivery_rules.FLAT; AJW from ajw_delivery. Customer delivery for non-AJW is Shopify shipping."""
    import delivery_rules as dr
    rows = []
    for key, (flat, free) in dr.FLAT.items():
        rows.append({"supplier": _DELIV_NAMES.get(key, key.title()), "basis": "Flat rate",
                     "we_pay": f"£{flat:,.2f}",
                     "free_over": (f"free over £{free:,.0f}" if free else "no free threshold"),
                     "customer": "Set in Shopify shipping", "notes": "", "detail": None})
    try:
        import ajw_delivery
        data = ajw_delivery._data()
        zr = []
        for z, info in (data.get("zones") or {}).items():
            if info.get("ajw_rate") is None:
                zr.append([z, "Quote per order", "—", "Quote required", "—"])
            else:
                zr.append([z, f"£{info['ajw_rate']:,.2f}", f"£{info['ajw_free']:,.0f}",
                           f"£{info['cust_rate']:,.2f}", f"£{info['cust_free']:,.0f}"])
        rows.append({"supplier": "AJW (Cedral)", "basis": "Postcode zone", "we_pay": "£40–£115 by zone",
                     "free_over": "free over each zone's ex-VAT cost threshold",
                     "customer": "£39.99–£114.99 by zone (free over the zone threshold)",
                     "notes": "Scotland/NI/islands quoted per order; +£75 mechanical offload per drop",
                     "detail": {"title": "By postcode zone (ex VAT)",
                                "headers": ["Zone", "We pay", "Free over (our cost)", "Customer", "Customer free over"],
                                "rows": zr}})
    except Exception:  # noqa: BLE001
        pass
    rows += [
        {"supplier": "Carron", "basis": "Postcode zone", "we_pay": "£25–£85 by zone",
         "free_over": "Zone 1 free over £250", "customer": "Set in Shopify shipping",
         "notes": "Ireland quoted", "detail": None},
        {"supplier": "Ctie", "basis": "Postcode zone", "we_pay": "£7 UK mainland / £13 NI (BT)",
         "free_over": "UK free over £100 / NI free over £250", "customer": "Set in Shopify shipping",
         "notes": "", "detail": None},
        {"supplier": "Southern Sheeting", "basis": "Postcode zone", "we_pay": "by postcode colour zone",
         "free_over": "by zone", "customer": "Set in Shopify shipping", "notes": "", "detail": None},
        {"supplier": "Storm", "basis": "Per product type", "we_pay": "£21+VAT poly / £80 decking / £80 cladding",
         "free_over": "no free threshold", "customer": "Set in Shopify shipping",
         "notes": "Polycarbonate sheeting carriage doubles to Scotland.",
         "detail": {"title": "Per product type (ex VAT)", "headers": ["Product", "We pay"],
                    "rows": [["Polycarbonate sheeting", "£21.00 + VAT"],
                             ["Polycarbonate sheeting — Scotland", "£42.00 + VAT (double)"],
                             ["Decking", "£80.00"], ["Cladding", "£80.00"]]}},
        {"supplier": "Dolle", "basis": "Per product", "we_pay": "highest per-product band on the order",
         "free_over": "—", "customer": "Set in Shopify shipping", "notes": "", "detail": None},
    ]
    # Internal doors — per-door tables (same expandable treatment as AJW's zones).
    jb = {"title": "Per door (ex VAT)", "headers": ["Doors", "We pay"],
          "rows": [["1 door", "£42.00"], ["2 doors", "£47.00"], ["3 doors", "£52.00"],
                   ["4 doors", "£57.00"], ["5+ doors", "£62.00"], ["Ironmongery only", "£15.00"]]}
    lpd = _door_detail(dr.LPD_DOOR_BASE, dr.LPD_DOOR_STEP, dr.LPD_DOOR_CAP, 9,
                       [["Hardware only", "£15.00 (≤10 packs) / £20.00 (>10)"]])
    deanta = _door_detail(dr.DEANTA_DOOR_BASE, dr.DEANTA_DOOR_STEP, dr.DEANTA_DOOR_CAP, 7,
                          [["Hardware only", "£8.00 (<£100) / free ≥£100 or shipped with doors"],
                           ["Next-day / express", "+£50.00"]])
    rows += [
        {"supplier": "JB Kind", "basis": "Per door", "we_pay": "£42–£62 by door count",
         "free_over": "—", "customer": "Set in Shopify shipping",
         "notes": "Some Scottish & island postcodes excluded / POA.", "detail": jb},
        {"supplier": "LPD", "basis": "Per door", "we_pay": "£40–£80 by door count",
         "free_over": "—", "customer": "Set in Shopify shipping",
         "notes": "+ area surcharge: London congestion +£15; Scottish Highlands & islands £20–£95; some areas POA.",
         "detail": lpd},
        {"supplier": "Deanta", "basis": "Per door", "we_pay": "£40–£70 by door count",
         "free_over": "—", "customer": "Set in Shopify shipping",
         "notes": "+ area surcharge £20–£150 (Scottish Highlands & islands); HS / IV40+ POA. Next-day +£50.",
         "detail": deanta},
    ]
    for r in rows:
        r["category"] = _cat_for(r["supplier"])
    rows.sort(key=lambda r: (r["category"], r["supplier"].lower()))
    return rows


@app.get("/pricing/delivery", dependencies=[Depends(require_key)])
def pricing_delivery():
    return {"rows": _delivery_catalog()}


# ---- Quotes: Cedral cladding take-off → priced quote (all-AJW) ---------------------------------
class CedralQuoteIn(BaseModel):
    system: str = "Lap"                 # "Lap" or "Click"
    colour: str = ""
    input_mode: str = "area"            # "area" | "hw" (height×width) | "boards"
    board_count: int | None = None
    gross_area_m2: float = 0.0
    openings_m2: float = 0.0
    wall_height_m: float | None = None
    total_width_m: float | None = None
    num_windows: int | None = None
    external_corners: int | None = None
    internal_corners: int = 0
    wants_trims: bool = True
    wants_battens: bool = False
    wants_screws: bool = True


@app.post("/quotes/cedral", dependencies=[Depends(require_key)])
def quote_cedral(body: CedralQuoteIn):
    """Cedral take-off → matched Shopify variants → priced quote. Cedral boards/trims/fixings are
    costed ONLY from AJW (a supplier's price is never crossed). Lines that aren't a Cedral/AJW
    product are flagged, not cross-sourced. Returns priced lines, totals, caveats and the discount."""
    import quote_core as qc
    import order_processing as op
    clad = {"product": f"Cedral {body.system}".strip(), "colour": body.colour,
            "input_mode": body.input_mode, "board_count": body.board_count,
            "gross_area_m2": body.gross_area_m2, "openings_m2": body.openings_m2,
            "wall_height_m": body.wall_height_m, "total_width_m": body.total_width_m,
            "num_windows": body.num_windows, "external_corners": body.external_corners,
            "internal_corners": body.internal_corners, "wants_trims": body.wants_trims,
            "wants_battens": body.wants_battens, "wants_screws": body.wants_screws}
    raw, cav = qc.cedral_takeoff(clad)
    if not raw:
        return {"ok": False, "detail": "Nothing to clad — net area is zero (check the area and openings)."}
    try:
        tok = ds.shopify_products_token()
    except Exception:  # noqa: BLE001
        tok = None
    lines, sell, cost, n_priced = [], 0.0, 0.0, 0
    for l in raw:
        # Battens are a generic timber item AJW doesn't supply — don't brand-lock/price them to AJW.
        is_batten = "batten" in (l.get("search") or "").lower()
        m = None
        if not is_batten:
            try:
                m = ds.match_quote_variant(None, l["search"], token=tok, brand="Cedral")
            except Exception:  # noqa: BLE001
                m = None
        price = m.get("price") if m else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        ajw_cost = None
        if m and m.get("sku"):
            try:
                ajw_cost = op._line_cost(m["sku"], "AJW", m.get("title"))
            except Exception:  # noqa: BLE001
                ajw_cost = None
        ajw_supplied = isinstance(ajw_cost, (int, float))
        qty = l["qty"]
        priced = price is not None and ajw_supplied
        lines.append({
            "description": l["description"], "qty": qty, "search": l["search"],
            "matched": ({"sku": m.get("sku"), "title": m.get("title"), "variant_id": m.get("variant_id"),
                         "vendor": m.get("vendor"), "available": m.get("available")} if m else None),
            "unit_sell": price, "line_sell": round(price * qty, 2) if price is not None else None,
            "unit_cost": round(ajw_cost, 2) if ajw_supplied else None,
            "line_cost": round(ajw_cost * qty, 2) if ajw_supplied else None,
            "ajw_supplied": ajw_supplied,
            "note": ("not supplied by AJW — source separately" if (is_batten or (m and not ajw_supplied))
                     else ("couldn't match a Cedral product — check wording" if not m else "")),
        })
        if priced:
            sell += price * qty
            cost += ajw_cost * qty
            n_priced += 1
    margin = (sell - cost) / sell if sell > 0 else None
    disc = qc.discount_floor(sell, margin) if margin is not None else None
    return {"ok": True, "product": clad["product"], "colour": body.colour,
            "lines": lines, "caveats": cav,
            "totals": {"sell": round(sell, 2), "cost": round(cost, 2), "margin": margin,
                       "margin_net": (round((margin - qc.SHOPIFY_FEE) * 100, 1) if margin is not None else None),
                       "n_priced": n_priced, "n_total": len(lines)},
            "discount": disc}


class HardieQuoteIn(BaseModel):
    system: str = "Lap"                 # "Lap" (HardiePlank) or "VL" (VL Plank / 'Click')
    colour: str = ""
    input_mode: str = "area"            # "area" | "hw" (height×width) | "boards"
    board_count: int | None = None
    gross_area_m2: float = 0.0
    openings_m2: float = 0.0
    wall_height_m: float | None = None
    total_width_m: float | None = None
    num_windows: int | None = None
    external_corners: int | None = None
    internal_corners: int = 0
    wants_trims: bool = True
    wants_battens: bool = False
    wants_screws: bool = True
    wants_epdm: bool = False
    wants_paint: bool = False


@app.post("/quotes/hardie", dependencies=[Depends(require_key)])
def quote_hardie(body: HardieQuoteIn):
    """James Hardie take-off → matched Shopify variants → priced quote. Hardie boards/trims/fixings
    are costed ONLY from UPB (our Hardie stockist — a supplier's price is never crossed). Lines that
    aren't a Hardie/UPB product are flagged, not cross-sourced. Returns priced lines, totals,
    caveats and the discount."""
    import quote_core as qc
    import order_processing as op
    sys_name = "Hardie VL Plank" if (body.system or "").lower() in ("vl", "click", "interlock") else "Hardie Plank"
    clad = {"product": sys_name, "colour": body.colour,
            "input_mode": body.input_mode, "board_count": body.board_count,
            "gross_area_m2": body.gross_area_m2, "openings_m2": body.openings_m2,
            "wall_height_m": body.wall_height_m, "total_width_m": body.total_width_m,
            "num_windows": body.num_windows, "external_corners": body.external_corners,
            "internal_corners": body.internal_corners, "wants_trims": body.wants_trims,
            "wants_battens": body.wants_battens, "wants_screws": body.wants_screws,
            "wants_epdm": body.wants_epdm, "wants_paint": body.wants_paint}
    raw, cav = qc.hardie_takeoff(clad)
    if not raw:
        return {"ok": False, "detail": "Nothing to clad — net area is zero (check the area and openings)."}
    try:
        tok = ds.shopify_products_token()
    except Exception:  # noqa: BLE001
        tok = None
    lines, sell, cost, n_priced = [], 0.0, 0.0, 0
    for l in raw:
        # Battens are a generic timber item UPB doesn't price as Hardie — don't brand-lock/cost them.
        is_batten = "batten" in (l.get("search") or "").lower()
        m = None
        if not is_batten:
            try:
                m = ds.match_quote_variant(None, l["search"], token=tok, brand="Hardie")
            except Exception:  # noqa: BLE001
                m = None
        price = m.get("price") if m else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        upb_cost = None
        if m and m.get("sku"):
            try:
                upb_cost = op._line_cost(m["sku"], "UPB", m.get("title"))
            except Exception:  # noqa: BLE001
                upb_cost = None
        upb_supplied = isinstance(upb_cost, (int, float))
        qty = l["qty"]
        priced = price is not None and upb_supplied
        lines.append({
            "description": l["description"], "qty": qty, "search": l["search"],
            "matched": ({"sku": m.get("sku"), "title": m.get("title"), "variant_id": m.get("variant_id"),
                         "vendor": m.get("vendor"), "available": m.get("available")} if m else None),
            "unit_sell": price, "line_sell": round(price * qty, 2) if price is not None else None,
            "unit_cost": round(upb_cost, 2) if upb_supplied else None,
            "line_cost": round(upb_cost * qty, 2) if upb_supplied else None,
            "ajw_supplied": upb_supplied,   # (front-end flag name) — "has a confirmed supplier cost"
            "note": ("not priced from UPB — source separately" if (is_batten or (m and not upb_supplied))
                     else ("couldn't match a Hardie product — check wording" if not m else "")),
        })
        if priced:
            sell += price * qty
            cost += upb_cost * qty
            n_priced += 1
    margin = (sell - cost) / sell if sell > 0 else None
    disc = qc.discount_floor(sell, margin) if margin is not None else None
    return {"ok": True, "product": sys_name, "colour": body.colour,
            "lines": lines, "caveats": cav,
            "totals": {"sell": round(sell, 2), "cost": round(cost, 2), "margin": margin,
                       "margin_net": (round((margin - qc.SHOPIFY_FEE) * 100, 1) if margin is not None else None),
                       "n_priced": n_priced, "n_total": len(lines)},
            "discount": disc}


class MolanQuoteIn(BaseModel):
    width: float                        # front span (m)
    rake: float                         # slope / rafter length (m)
    sheet_width_mm: int = 1050
    sheet_type: str = "25mm Multiwall"  # a quote_core.POLY_SHEETS key
    colour: str = "Clear"
    system: str = "Self-Supported (16/35mm)"  # a quote_core.POLY_SYSTEMS key
    bar_colour: str = "White"
    include_acc: bool = True


@app.post("/quotes/molan", dependencies=[Depends(require_key)])
def quote_molan(body: MolanQuoteIn):
    """Molan polycarbonate roof take-off → matched Shopify variants → priced quote. Polycarbonate is
    brand-locked to Molan (sheets, bars, wallplate/eaves, tapes) — never cross-priced. Returns priced
    lines, totals, caveats and the discount."""
    import quote_core as qc
    import order_processing as op
    if body.sheet_type not in qc.POLY_SHEETS:
        return {"ok": False, "detail": f"Unknown sheet type '{body.sheet_type}'."}
    if body.system not in qc.POLY_SYSTEMS:
        return {"ok": False, "detail": f"Unknown bar system '{body.system}'."}
    inp = {"width": body.width, "rake": body.rake, "sheet_width_mm": body.sheet_width_mm,
           "sheet_type": body.sheet_type, "colour": body.colour, "system": body.system,
           "bar_colour": body.bar_colour, "include_acc": body.include_acc}
    raw, meta = qc.poly_takeoff(inp)
    if not raw:
        return {"ok": False, "detail": "Nothing to build — check the roof width and slope length."}
    cav = []
    if meta.get("note"):
        cav.append(meta["note"])
    cav.append(f"{meta['sheets']} sheet(s) across the {body.width:.1f} m span and {meta['bars']} "
               f"bar(s) at {meta['barlen']} m. Confirm the exact span/slope and we'll tighten it.")
    cav.append("Polycarbonate is quoted in Molan products only. Bar/tape quantities are estimates "
               "sized from the span — send the exact roof sizes to firm them up.")
    try:
        tok = ds.shopify_products_token()
    except Exception:  # noqa: BLE001
        tok = None
    lines, sell, cost, n_priced = [], 0.0, 0.0, 0
    for l in raw:
        m = None
        try:
            m = ds.match_quote_variant(None, l["search"], token=tok, brand="Molan")
        except Exception:  # noqa: BLE001
            m = None
        price = m.get("price") if m else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        mo_cost = None
        if m and m.get("sku"):
            try:
                mo_cost = op._line_cost(m["sku"], "Molan", m.get("title"))
            except Exception:  # noqa: BLE001
                mo_cost = None
        mo_supplied = isinstance(mo_cost, (int, float))
        qty = l["qty"]
        priced = price is not None and mo_supplied
        lines.append({
            "description": l["item"], "qty": qty, "search": l["search"],
            "matched": ({"sku": m.get("sku"), "title": m.get("title"), "variant_id": m.get("variant_id"),
                         "vendor": m.get("vendor"), "available": m.get("available")} if m else None),
            "unit_sell": price, "line_sell": round(price * qty, 2) if price is not None else None,
            "unit_cost": round(mo_cost, 2) if mo_supplied else None,
            "line_cost": round(mo_cost * qty, 2) if mo_supplied else None,
            "ajw_supplied": mo_supplied,   # (front-end flag name) — "has a confirmed supplier cost"
            "note": ("no Molan cost on file — check the price list" if (m and not mo_supplied)
                     else ("couldn't match a Molan product — check wording" if not m else "")),
        })
        if priced:
            sell += price * qty
            cost += mo_cost * qty
            n_priced += 1
    margin = (sell - cost) / sell if sell > 0 else None
    disc = qc.discount_floor(sell, margin) if margin is not None else None
    return {"ok": True, "product": f"{body.sheet_type} {body.colour} polycarbonate roof",
            "colour": body.colour, "lines": lines, "caveats": cav,
            "totals": {"sell": round(sell, 2), "cost": round(cost, 2), "margin": margin,
                       "margin_net": (round((margin - qc.SHOPIFY_FEE) * 100, 1) if margin is not None else None),
                       "n_priced": n_priced, "n_total": len(lines)},
            "discount": disc}


class StormQuoteIn(BaseModel):
    width: float                        # roof span (m)
    slope: float                        # slope / rafter length (m)
    sheet_width_mm: int = 1050
    sheet_type: str = "25mm Multiwall"  # a quote_core.STORM_SHEETS key
    colour: str = "Clear"               # a quote_core.STORM_COLOURS key
    bar_colour: str = "White"
    include_acc: bool = True


@app.post("/quotes/storm", dependencies=[Depends(require_key)])
def quote_storm(body: StormQuoteIn):
    """Storm self-support polycarbonate roof take-off → matched Storm Shopify variants → priced quote.
    Costed from Storm (its costs are on Shopify cost-per-item). Returns priced lines, totals, caveats
    and the discount."""
    import quote_core as qc
    import order_processing as op
    if body.sheet_type not in qc.STORM_SHEETS:
        return {"ok": False, "detail": f"Unknown sheet type '{body.sheet_type}'."}
    if body.colour not in qc.STORM_COLOURS:
        return {"ok": False, "detail": f"Unknown colour '{body.colour}'."}
    raw, cav = qc.storm_roof_takeoff({"width": body.width, "slope": body.slope,
        "sheet_width_mm": body.sheet_width_mm, "sheet_type": body.sheet_type,
        "colour": body.colour, "bar_colour": body.bar_colour, "include_acc": body.include_acc})
    if not raw:
        return {"ok": False, "detail": "Nothing to build — check the roof span and slope length."}
    try:
        tok = ds.shopify_products_token()
    except Exception:  # noqa: BLE001
        tok = None
    lines, sell, cost, n_priced = [], 0.0, 0.0, 0
    for l in raw:
        m = None
        try:
            m = ds.match_quote_variant(l.get("code"), l["search"], token=tok, brand="Storm")
        except Exception:  # noqa: BLE001
            m = None
        price = m.get("price") if m else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        st_cost = None
        if m and m.get("sku"):
            try:
                st_cost = op._line_cost(m["sku"], "Storm", m.get("title"))
            except Exception:  # noqa: BLE001
                st_cost = None
        st_supplied = isinstance(st_cost, (int, float))
        qty = l["qty"]
        priced = price is not None and st_supplied
        lines.append({
            "description": l["description"], "qty": qty, "search": l["search"],
            "matched": ({"sku": m.get("sku"), "title": m.get("title"), "variant_id": m.get("variant_id"),
                         "vendor": m.get("vendor"), "available": m.get("available")} if m else None),
            "unit_sell": price, "line_sell": round(price * qty, 2) if price is not None else None,
            "unit_cost": round(st_cost, 2) if st_supplied else None,
            "line_cost": round(st_cost * qty, 2) if st_supplied else None,
            "ajw_supplied": st_supplied,
            "note": ("no Storm cost on file — check the price list" if (m and not st_supplied)
                     else ("couldn't match a Storm product — check wording" if not m else "")),
        })
        if priced:
            sell += price * qty
            cost += st_cost * qty
            n_priced += 1
    margin = (sell - cost) / sell if sell > 0 else None
    disc = qc.discount_floor(sell, margin) if margin is not None else None
    return {"ok": True, "product": f"Storm {body.sheet_type} {body.colour} self-support roof",
            "colour": body.colour, "lines": lines, "caveats": cav,
            "totals": {"sell": round(sell, 2), "cost": round(cost, 2), "margin": margin,
                       "margin_net": (round((margin - qc.SHOPIFY_FEE) * 100, 1) if margin is not None else None),
                       "n_priced": n_priced, "n_total": len(lines)},
            "discount": disc}


@app.get("/quotes/search", dependencies=[Depends(require_key)])
def quote_search(q: str, limit: int = 12):
    """Search Shopify variants by text — for manually adding an extra product line to a quote.
    Returns [{variant_id, title, sku, price, available, vendor}]."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"results": []}
    try:
        cands = ds._variant_search_flex(q, ds.shopify_products_token(), first=min(limit, 25))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Shopify search failed: {e}")
    out = [{"variant_id": c.get("variant_id"), "title": c.get("title"), "sku": c.get("sku"),
            "price": c.get("price"), "available": c.get("available"), "vendor": c.get("vendor")}
           for c in (cands or [])][:limit]
    return {"results": out}


class EzglazeQuoteIn(BaseModel):
    width: float                        # roof width (m)
    slope: float                        # slope length, eaves→ridge (m)
    cover: float = 1.0                  # sheet cover width (m)
    colour: str = "Clear"               # an EZGLAZE_COLOURS key


@app.post("/quotes/ezglaze", dependencies=[Depends(require_key)])
def quote_ezglaze(body: EzglazeQuoteIn):
    """Molan EZ Glaze corrugated roof take-off → matched Shopify variants → priced quote. Brand-locked
    to Molan. Sheets are SKU-exact (matched to the nearest EZ Glaze length); accessory quantities are
    estimates. Returns priced lines, totals, caveats and the discount."""
    import quote_core as qc
    import order_processing as op
    if body.colour not in qc.EZGLAZE_COLOURS:
        return {"ok": False, "detail": f"Unknown EZ Glaze colour '{body.colour}'."}
    raw, meta = qc.ezglaze_takeoff({"width": body.width, "slope": body.slope,
                                    "cover": body.cover, "colour": body.colour})
    if not raw:
        return {"ok": False, "detail": "Nothing to build — check the roof width and slope length."}
    cav = [f"{meta['sheets']} sheet(s) across the {body.width:.1f} m width, each {meta['length']:g} m "
           "long (nearest EZ Glaze length). Confirm the exact sizes and we'll tighten it.",
           "EZ Glaze is quoted in Molan products only. Foam/screw/connector quantities are estimates "
           "sized from the roof — confirm against the job."]
    try:
        tok = ds.shopify_products_token()
    except Exception:  # noqa: BLE001
        tok = None
    lines, sell, cost, n_priced = [], 0.0, 0.0, 0
    for l in raw:
        code = (l.get("skus") or [None])[0]
        m = None
        try:
            m = ds.match_quote_variant(code, l["search"], token=tok, brand="Molan")
        except Exception:  # noqa: BLE001
            m = None
        price = m.get("price") if m else None
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        mo_cost = None
        if m and m.get("sku"):
            try:
                mo_cost = op._line_cost(m["sku"], "Molan", m.get("title"))
            except Exception:  # noqa: BLE001
                mo_cost = None
        mo_supplied = isinstance(mo_cost, (int, float))
        qty = l["qty"]
        priced = price is not None and mo_supplied
        lines.append({
            "description": l["item"], "qty": qty, "search": l["search"],
            "matched": ({"sku": m.get("sku"), "title": m.get("title"), "variant_id": m.get("variant_id"),
                         "vendor": m.get("vendor"), "available": m.get("available")} if m else None),
            "unit_sell": price, "line_sell": round(price * qty, 2) if price is not None else None,
            "unit_cost": round(mo_cost, 2) if mo_supplied else None,
            "line_cost": round(mo_cost * qty, 2) if mo_supplied else None,
            "ajw_supplied": mo_supplied,
            "note": ("no Molan cost on file — check the price list" if (m and not mo_supplied)
                     else ("couldn't match an EZ Glaze product — check wording" if not m else "")),
        })
        if priced:
            sell += price * qty
            cost += mo_cost * qty
            n_priced += 1
    margin = (sell - cost) / sell if sell > 0 else None
    disc = qc.discount_floor(sell, margin) if margin is not None else None
    cname = qc.EZGLAZE_COLOURS[body.colour][0]
    return {"ok": True, "product": f"{cname} corrugated roof", "colour": body.colour,
            "lines": lines, "caveats": cav,
            "totals": {"sell": round(sell, 2), "cost": round(cost, 2), "margin": margin,
                       "margin_net": (round((margin - qc.SHOPIFY_FEE) * 100, 1) if margin is not None else None),
                       "n_priced": n_priced, "n_total": len(lines)},
            "discount": disc}


class QuoteDraftItem(BaseModel):
    variant_id: str
    qty: int = 1


class QuoteDraftIn(BaseModel):
    items: list[QuoteDraftItem]
    customer_email: str | None = None
    customer_name: str | None = None
    postcode: str | None = None
    note: str | None = None


@app.post("/quotes/draft", dependencies=[Depends(require_key)])
def quote_draft(body: QuoteDraftIn):
    """Create a Shopify DRAFT order from the matched quote lines (human-gated: the user clicks Build
    draft). Shopify prices it and ADDS 20% VAT (store is ex-VAT). Returns the draft name + invoice URL
    so it can be opened/finished in Shopify. Not an order and takes no payment."""
    line_items = [{"variantId": it.variant_id, "quantity": int(it.qty)}
                  for it in body.items if it.variant_id and int(it.qty) > 0]
    if not line_items:
        return {"ok": False, "detail": "No matched lines to put on a draft order."}
    try:
        d = ds.create_draft_order(
            line_items,
            email=(body.customer_email or None),
            name=(body.customer_name or None),
            postcode=(body.postcode or None),
            note=(body.note or "TradeHub quote"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't create the draft order: {e}")
    return {"ok": True, "name": d.get("name"), "invoice_url": d.get("invoiceUrl"),
            "admin_url": d.get("admin_url"), "total": d.get("total"), "tax": d.get("tax"),
            "id": d.get("id")}
