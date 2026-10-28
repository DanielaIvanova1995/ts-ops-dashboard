"""Shopify Housekeeping — tidy the Unfulfilled / Open order tabs on demand.

PREVIEW-FIRST: build_preview() only READS (classifies orders into fulfil / archive / leave); run()
only acts on the EXACT order ids the preview returned and the UI approved. Nothing is scheduled.

STEP 1 FULFIL (silently, notifyCustomer ALWAYS false) — open & unfulfilled/partial orders, except:
  - anything created in the last 24h (too new), and
  - any order ANY of whose Monday Orders-board parts sits in a LEAVE group (below).
  An order not on the Orders board at all is on Archive 2026 → fulfil it too.
STEP 2 ARCHIVE (orderClose) — open orders that need no more work: fully refunded; all fulfilment
  orders CLOSED with 0 unfulfilled; or fully fulfilled + PAID/PARTIALLY_REFUNDED + 0 outstanding.
  Never archive with money outstanding or a partially-refunded still-unfulfilled order.

Every Shopify call has a 60s timeout and retries on 429/5xx/timeout.
"""
from __future__ import annotations

import time as _time

import requests

import data_sources as ds

ORDERS_BOARD = "1786542990"
ORDER_NO_COL = "text_mkv6z0nt"

# Monday groups that mean "leave this order alone entirely".
LEAVE_GROUPS = {
    "group_mm5q9n7s":    "New Orders Requiring Review",
    "new_group4381__1":  "New Orders Awaiting Customer Response",
    "new_group84744":    "To post",
    "group_mkpt9qpe":    "Accepted Returns",
    "group_mkv7fz2b":    "Unconfirmed Orders - Call for ETA",
    "group_mkv7t11j":    "Supplier Delivery - Booked with Customer",
    "group_mkpwjda5":    "Cancelled orders 2026",
    "group_mks290tr":    "Refunds owed upon delivery",
    "new_group42542__1": "Refund/Credit required by supplier",
}

NEEDED_SCOPES = [
    "read_orders", "read_all_orders", "write_orders",
    "write_merchant_managed_fulfillment_orders", "write_assigned_fulfillment_orders",
]

_API = "2024-10"


def _store_token():
    store = ds.get_secret("SHOPIFY_STORE")
    token = ds.get_secret("SHOPIFY_ADMIN_TOKEN")
    if not token:
        try:
            token = ds.shopify_products_token()
        except Exception:  # noqa: BLE001
            token = None
    return store, token


def _shop_gql(query, variables=None, timeout=60, tries=4):
    """One Shopify Admin GraphQL call, 60s timeout, retry on 429/5xx/timeout. Raises on a GraphQL
    'errors' payload (those are query problems, not transient)."""
    store, token = _store_token()
    if not store or not token:
        raise RuntimeError("Shopify store/token not configured")
    url = f"https://{store}/admin/api/{_API}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    last = None
    for attempt in range(max(1, tries)):
        try:
            r = requests.post(url, json={"query": query, "variables": variables or {}},
                              headers=headers, timeout=timeout)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                last = f"HTTP {r.status_code}"
                _time.sleep(min(2 ** attempt, 20))
                continue
            r.raise_for_status()
            payload = r.json()
            if payload.get("errors"):
                raise RuntimeError(f"Shopify GraphQL error: {str(payload['errors'])[:300]}")
            return payload.get("data") or {}
        except requests.Timeout:
            last = "timeout"
            _time.sleep(min(2 ** attempt, 20))
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 — network blip → retry
            last = str(e)[:120]
            _time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"Shopify call failed after retries ({last})")


def check_scopes() -> dict:
    """{ok, granted, missing}. Compares the app's granted access scopes to NEEDED_SCOPES."""
    try:
        data = _shop_gql("{ currentAppInstallation { accessScopes { handle } } }")
        granted = [s.get("handle") for s in
                   (((data.get("currentAppInstallation") or {}).get("accessScopes")) or [])]
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "granted": [], "missing": NEEDED_SCOPES, "error": str(e)[:160]}
    missing = [s for s in NEEDED_SCOPES if s not in granted]
    return {"ok": not missing, "granted": granted, "missing": missing}


_ORDER_FIELDS = """
  id name createdAt
  displayFinancialStatus displayFulfillmentStatus
  totalOutstandingSet { shopMoney { amount } }
  fulfillmentOrders(first: 25) {
    edges { node { id status supportedActions
      lineItems(first: 50) { edges { node { remainingQuantity totalQuantity } } } } }
  }
"""


def _fetch_open_unfulfilled(cap=2000):
    """Open orders that are unshipped or partially fulfilled (needs read_all_orders for >60 days)."""
    q = ("query($c:String){ orders(first: 100, after: $c, query: \"status:open AND "
         "(fulfillment_status:unshipped OR fulfillment_status:partial)\") { "
         "edges { cursor node { %s } } pageInfo { hasNextPage endCursor } } }" % _ORDER_FIELDS)
    out, cursor = [], None
    while True:
        data = _shop_gql(q, {"c": cursor})
        conn = data.get("orders") or {}
        for e in (conn.get("edges") or []):
            out.append(e["node"])
            if len(out) >= cap:
                return out
        pi = conn.get("pageInfo") or {}
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
    return out


def _order_no(name):
    """Shopify order name → bare order number (strip leading #)."""
    return str(name or "").lstrip("#").strip()


def _monday_groups(order_numbers):
    """{order_no: set(group_ids)} from the Monday Orders board, matching the order number to the
    order-no column (split parts share the base number). Batched."""
    nums = [str(n).strip() for n in order_numbers if str(n).strip()]
    out = {}
    q = ('query($b:ID!,$vals:[String]!){items_page_by_column_values(board_id:$b,limit:500,'
         'columns:[{column_id:"%s",column_values:$vals}]){items{id name group{id} '
         'column_values(ids:["%s"]){text}}}}' % (ORDER_NO_COL, ORDER_NO_COL))
    tok = ds.get_token()
    for i in range(0, len(nums), 100):
        chunk = nums[i:i + 100]
        try:
            data = ds._monday_gql(q, {"b": ORDERS_BOARD, "vals": chunk}, tok)
        except Exception:  # noqa: BLE001
            continue
        for it in (((data.get("items_page_by_column_values") or {}).get("items")) or []):
            cvs = it.get("column_values") or []
            ono = (cvs[0].get("text") if cvs else "") or ""
            ono = str(ono).strip()
            gid = (it.get("group") or {}).get("id")
            if ono and gid:
                out.setdefault(ono, set()).add(gid)
    return out


def _fo_nodes(order):
    return [e["node"] for e in (((order.get("fulfillmentOrders") or {}).get("edges")) or [])]


def _unfulfilled_qty(fo):
    tot = 0
    for e in (((fo.get("lineItems") or {}).get("edges")) or []):
        rq = (e.get("node") or {}).get("remainingQuantity")
        if isinstance(rq, int):
            tot += rq
    return tot


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _classify(order, mg):
    """Return (action, reason): action in 'fulfil' / 'archive' / 'leave_group' / 'leave_young' /
    'review_partial_refund'. mg = {order_no: set(group_ids)}."""
    import datetime as _dt
    # Too new (<24h) → leave.
    try:
        created = _dt.datetime.fromisoformat((order.get("createdAt") or "").replace("Z", "+00:00"))
        if (_dt.datetime.now(_dt.timezone.utc) - created).total_seconds() < 24 * 3600:
            return ("leave_young", "created in the last 24h")
    except Exception:  # noqa: BLE001
        pass

    ono = _order_no(order.get("name"))
    groups = mg.get(ono)
    fin = (order.get("displayFinancialStatus") or "").upper()
    ful = (order.get("displayFulfillmentStatus") or "").upper()
    outstanding = _num((((order.get("totalOutstandingSet") or {}).get("shopMoney") or {}).get("amount")))
    fos = _fo_nodes(order)

    # ---- STEP 2 ARCHIVE candidates (checked first; they're "no more work") ----
    all_fo_closed_zero = bool(fos) and all(
        (fo.get("status") == "CLOSED") and _unfulfilled_qty(fo) == 0 for fo in fos)
    if fin == "REFUNDED":
        return ("archive", "fully refunded")
    if all_fo_closed_zero:
        return ("archive", "all fulfilment orders closed, 0 unfulfilled (refunded/restocked)")
    if ful == "FULFILLED" and fin in ("PAID", "PARTIALLY_REFUNDED") and outstanding <= 0:
        return ("archive", f"fully fulfilled, {fin.lower()}, nothing outstanding")
    # Partially refunded AND still unfulfilled → list for review, never auto-archive.
    if fin == "PARTIALLY_REFUNDED" and ful in ("UNFULFILLED", "PARTIALLY_FULFILLED"):
        return ("review_partial_refund", "partially refunded but still unfulfilled")

    # ---- STEP 1 FULFIL ----
    if groups:
        if groups & set(LEAVE_GROUPS):
            hit = sorted(groups & set(LEAVE_GROUPS))
            return ("leave_group", LEAVE_GROUPS.get(hit[0], hit[0]))
        return ("fulfil", "on the Orders board, not in a leave group")
    # Not on the Orders board → it's on Archive 2026 → fulfil.
    return ("fulfil", "not on the Orders board (archived) → fulfil")


def build_preview(cap=2000):
    """READ-ONLY. Classify every open unfulfilled/partial order. Returns the plan: lists of order
    ids per action, per-leave-group counts, samples, and the scope check. Writes nothing."""
    scopes = check_scopes()
    orders = _fetch_open_unfulfilled(cap=cap)
    mg = _monday_groups([_order_no(o.get("name")) for o in orders])
    plan = {"fulfil": [], "archive": [], "leave_young": [], "review_partial_refund": [],
            "leave_group_counts": {}, "scanned": len(orders)}
    for o in orders:
        action, reason = _classify(o, mg)
        rec = {"id": o.get("id"), "name": o.get("name"), "reason": reason}
        if action == "leave_group":
            plan["leave_group_counts"][reason] = plan["leave_group_counts"].get(reason, 0) + 1
        elif action in ("fulfil", "archive", "leave_young", "review_partial_refund"):
            plan[action].append(rec)
    def _sample(lst):
        return [r.get("name") for r in lst[:12]]
    return {
        "ok": True, "scopes": scopes, "scanned": len(orders),
        "fulfil": {"count": len(plan["fulfil"]), "sample": _sample(plan["fulfil"]),
                   "ids": [r["id"] for r in plan["fulfil"]], "names": [r["name"] for r in plan["fulfil"]]},
        "archive": {"count": len(plan["archive"]), "sample": _sample(plan["archive"]),
                    "ids": [r["id"] for r in plan["archive"]], "names": [r["name"] for r in plan["archive"]]},
        "leave_young": {"count": len(plan["leave_young"]), "sample": _sample(plan["leave_young"])},
        "review_partial_refund": {"count": len(plan["review_partial_refund"]),
                                  "sample": _sample(plan["review_partial_refund"])},
        "leave_group_counts": plan["leave_group_counts"],
    }


def _fulfil_order(order_id):
    """Fulfil every fulfilment order on this order that supports CREATE_FULFILLMENT, notifyCustomer
    false. Returns (done, skipped, errors[])."""
    data = _shop_gql("query($id:ID!){order(id:$id){ %s }}" % _ORDER_FIELDS, {"id": order_id})
    order = data.get("order") or {}
    done = skipped = 0
    errs = []
    for fo in _fo_nodes(order):
        if "CREATE_FULFILLMENT" not in (fo.get("supportedActions") or []):
            skipped += 1
            continue
        m = ("mutation($f:FulfillmentV2Input!){fulfillmentCreateV2(fulfillment:$f){"
             "fulfillment{id} userErrors{message}}}")
        var = {"f": {"notifyCustomer": False,
                     "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": fo["id"]}]}}
        try:
            r = _shop_gql(m, var)
            ue = ((r.get("fulfillmentCreateV2") or {}).get("userErrors")) or []
            if ue:
                errs.append(str(ue[0].get("message"))[:160])
            else:
                done += 1
        except Exception as e:  # noqa: BLE001
            errs.append(str(e)[:160])
    return done, skipped, errs


def _archive_order(order_id):
    m = "mutation($id:ID!){orderClose(input:{id:$id}){order{id} userErrors{message}}}"
    r = _shop_gql(m, {"id": order_id})
    ue = ((r.get("orderClose") or {}).get("userErrors")) or []
    if ue:
        raise RuntimeError(str(ue[0].get("message"))[:160])
    return True


def run(fulfil_ids=None, archive_ids=None):
    """Act ONLY on the exact order ids the preview returned and the UI approved. Returns a results
    log. Does not re-scan, so orders that arrived during the run are never touched."""
    fulfil_ids = list(fulfil_ids or [])
    archive_ids = list(archive_ids or [])
    log = {"fulfilled": 0, "fulfil_skipped": 0, "archived": 0, "failed": 0, "items": []}
    for oid in fulfil_ids:
        try:
            done, skipped, errs = _fulfil_order(oid)
            log["fulfilled"] += done
            log["fulfil_skipped"] += skipped
            if errs:
                log["failed"] += 1
                log["items"].append({"id": oid, "action": "fulfil", "result": "error",
                                     "detail": "; ".join(errs)[:200]})
            else:
                log["items"].append({"id": oid, "action": "fulfil",
                                     "result": f"fulfilled {done}" + (f", {skipped} unsupported" if skipped else "")})
        except Exception as e:  # noqa: BLE001
            log["failed"] += 1
            log["items"].append({"id": oid, "action": "fulfil", "result": "error", "detail": str(e)[:200]})
        _time.sleep(0.15)
    for oid in archive_ids:
        try:
            _archive_order(oid)
            log["archived"] += 1
            log["items"].append({"id": oid, "action": "archive", "result": "archived"})
        except Exception as e:  # noqa: BLE001
            log["failed"] += 1
            log["items"].append({"id": oid, "action": "archive", "result": "error", "detail": str(e)[:200]})
        _time.sleep(0.15)
    log["ok"] = True
    log["failures"] = [i for i in log["items"] if i.get("result") == "error"]
    return log
