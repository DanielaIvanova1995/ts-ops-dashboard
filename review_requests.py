"""Review Requests engine — reads delivered orders from the Monday Orders board, filters them to
smooth/fast orders that haven't been reviewed, and prepares review-request emails. Sending is done
by api.main via the existing Outlook/Graph path; this module only READS Monday + decides who qualifies.

Board 1786542990 "Orders". Groups read:
  group_mkv7mvgm  "Delivered Orders (MALYEKA)"   (~1,850 items — paginated)
  new_group67810  "Delivered & Paid (AUTO)"
"""
import re
import datetime as _dt
from collections import Counter

import data_sources as ds

BOARD_ID = 1786542990
GROUPS = ["group_mkv7mvgm", "new_group67810"]

COL = {
    "order_no": "text_mkv6z0nt",
    "name": "text2",
    "email": "text52",
    "phone": "text20",
    "order_date": "date1",
    "cust_eta": "date",
    "wc_eta": "date__1",
    "delivery": "color_mktyhmf3",
    "stage": "color_mktyyf7w",
    "aftersales": "status_1__1",
    "review": "status_18",
}
_COL_IDS = list(COL.values())
_FIELDS = ('id name updates(limit:25){id creator{id}} column_values(ids:[%s]){id text}'
           % ",".join(f'"{c}"' for c in _COL_IDS))

# Update creators that are NOT a real person — automations post with a null creator (TradeHub's
# order-processing / ETA emails logged to the item), and Monday's own automation user is -4. Only
# updates from a real team member count as "manual" (i.e. a human chased / there was an issue).
_AUTOMATION_CREATORS = {None, "", "-4", -4}


def _manual_updates(it):
    n = 0
    for u in (it.get("updates") or []):
        cid = (u.get("creator") or {}).get("id")
        if cid not in _AUTOMATION_CREATORS:
            n += 1
    return n

# Review labels that mean "don't ask again" (already asked, or unhappy).
_REVIEW_SKIP = {"sent", "bad experience", "apology"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _parse_date(txt):
    s = (txt or "").strip()[:10]
    try:
        return _dt.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _base_order_no(s):
    """'24234 (2 of 2)' / '24234-2' → '24234' so split/part orders dedupe to one customer."""
    s = (s or "").strip()
    m = re.match(r"^\s*([A-Za-z]*\d+)", s)
    return (m.group(1) if m else s).upper()


def _norm_label(txt):
    return (txt or "").strip().lower()


def _page_group(group_id, token):
    q1 = ('query($b:[ID!],$g:[String]){boards(ids:$b){groups(ids:$g){'
          'items_page(limit:500){cursor items{%s}}}}}' % _FIELDS)
    data = ds._monday_gql(q1, {"b": [str(BOARD_ID)], "g": [group_id]}, token)
    groups = (((data.get("boards") or [{}])[0]).get("groups") or [])
    page = (groups[0].get("items_page") if groups else {}) or {}
    items = list(page.get("items") or [])
    cursor = page.get("cursor")
    qn = ('query($c:String!){next_items_page(cursor:$c,limit:500){cursor items{%s}}}' % _FIELDS)
    pages = 1
    while cursor and pages < 25:            # safety cap (25×500 = 12,500)
        try:
            d2 = ds._monday_gql(qn, {"c": cursor}, token)
        except Exception:  # noqa: BLE001 — a paging glitch shouldn't lose the pages we already have
            break
        np = (d2.get("next_items_page") or {})
        items += list(np.get("items") or [])
        cursor = np.get("cursor")
        pages += 1
    return items


def fetch_raw(token=None):
    """Both delivered groups as flat dicts (one per Monday item)."""
    token = token or ds.get_token()
    out, seen = [], set()
    for g in GROUPS:
        for it in _page_group(g, token):
            iid = str(it.get("id"))
            if iid in seen:
                continue
            seen.add(iid)
            cv = {c["id"]: (c.get("text") or "").strip() for c in (it.get("column_values") or [])}
            out.append({
                "item_id": iid,
                "order_no": cv.get(COL["order_no"]) or (it.get("name") or "").strip(),
                "name": cv.get(COL["name"]),
                "email": (cv.get(COL["email"]) or "").strip(),
                "phone": cv.get(COL["phone"]),
                "order_date": cv.get(COL["order_date"]),
                "cust_eta": cv.get(COL["cust_eta"]),
                "wc_eta": cv.get(COL["wc_eta"]),
                "delivery": cv.get(COL["delivery"]),
                "stage": cv.get(COL["stage"]),
                "aftersales": cv.get(COL["aftersales"]),
                "review": cv.get(COL["review"]),
                "n_updates": _manual_updates(it),              # MANUAL updates only (ignore automations)
                "n_updates_all": len(it.get("updates") or []),
            })
    return out


def build(window_days=60, max_gap=5, max_updates=3, include_b=True, suppression=None, raw=None,
          delivered_statuses=None):
    """Decide who qualifies, assign Tier A/B, dedupe, and count every exclusion reason. `raw` lets a
    caller reuse a cached pull. `delivered_statuses` = the Delivery-status labels that count as
    delivered (default just 'Delivered'). Returns {rows, counts, excluded, delivery_dist, total}."""
    raw = raw if raw is not None else fetch_raw()
    supp = {(e or "").strip().lower() for e in (suppression or set())}
    # By default every order in the Delivered groups counts as delivered (group membership IS the
    # signal) — delivered_ok = None means "don't filter on the Delivery-status column at all". Pass a
    # list to narrow to specific status labels.
    delivered_ok = {_norm_label(s) for s in delivered_statuses} if delivered_statuses else None
    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=int(window_days)) if window_days else None
    excl = Counter()
    delivery_dist = {}            # {display label: count} across everything scanned — for the UI picker
    cand = []
    for r in raw:
        lbl = (r["delivery"] or "").strip() or "(blank)"
        delivery_dist[lbl] = delivery_dist.get(lbl, 0) + 1
        if delivered_ok is not None and _norm_label(r["delivery"]) not in delivered_ok:
            excl["not_delivered"] += 1
            continue
        if r["n_updates"] > max_updates:                      # 4+ updates = there was an issue
            excl["updates_4plus"] += 1
            continue
        if (r["stage"] or "").strip():                        # any stage = return/refund/chargeback
            excl["customer_stage_set"] += 1
            continue
        if (r["aftersales"] or "").strip():
            excl["aftersales_set"] += 1
            continue
        if _norm_label(r["review"]) in _REVIEW_SKIP:          # already asked / unhappy
            excl["already_reviewed"] += 1
            continue
        email = (r["email"] or "").strip()
        if not _EMAIL_RE.match(email):
            excl["no_email"] += 1
            continue
        if email.lower() in supp:
            excl["suppressed"] += 1
            continue
        od = _parse_date(r["order_date"])
        if cutoff and (od is None or od < cutoff):
            excl["out_of_window"] += 1
            continue
        eta = _parse_date(r["cust_eta"]) or _parse_date(r["wc_eta"])
        gap = (eta - od).days if (eta and od) else None
        if eta is not None:
            if gap is None or gap < 0 or gap > max_gap:
                excl["eta_gap_too_long"] += 1
                continue
            tier = "A"
        else:
            if not include_b:
                excl["tier_b_excluded"] += 1
                continue
            tier = "B"
        cand.append({**r, "email": email, "tier": tier, "gap": gap,
                     "eta": (eta.isoformat() if eta else None),
                     "order_date_d": od, "base": _base_order_no(r["order_no"])})

    # Dedupe: by base order number (keep most recent order date), then one per email address.
    cand.sort(key=lambda c: (c.get("order_date_d") or _dt.date.min), reverse=True)
    seen_base, seen_email, rows = set(), set(), []
    for c in cand:
        key_b = c["base"]
        key_e = c["email"].lower()
        if key_b in seen_base or key_e in seen_email:
            excl["duplicate_customer"] += 1
            continue
        seen_base.add(key_b)
        seen_email.add(key_e)
        c.pop("order_date_d", None)
        rows.append(c)

    counts = {"A": sum(1 for r in rows if r["tier"] == "A"),
              "B": sum(1 for r in rows if r["tier"] == "B"),
              "total": len(rows)}
    dist = dict(sorted(delivery_dist.items(), key=lambda kv: kv[1], reverse=True))
    return {"rows": rows, "counts": counts, "excluded": dict(excl),
            "delivery_dist": dist,
            "delivered_statuses": sorted(delivered_ok) if delivered_ok is not None else None,
            "total_scanned": len(raw)}


def first_name(full):
    s = (full or "").strip()
    return s.split()[0] if s else "there"


def mark_sent(item_id, token=None):
    """After a review email goes out: set the Review column (status_18) to 'Sent' and post an update."""
    import json as _json
    token = token or ds.get_token()
    ds._monday_gql(
        "mutation($b:ID!,$i:ID!,$v:JSON!){change_multiple_column_values(board_id:$b,item_id:$i,"
        "column_values:$v){id}}",
        {"b": str(BOARD_ID), "i": str(item_id), "v": _json.dumps({COL["review"]: {"label": "Sent"}})},
        token)
    ds._monday_gql(
        "mutation($i:ID!,$b:String!){create_update(item_id:$i,body:$b){id}}",
        {"i": str(item_id), "b": f"Review request sent {_dt.date.today().isoformat()}"}, token)
