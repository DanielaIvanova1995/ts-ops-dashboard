"""
Headless invoice auto-checker (the scheduled cloud runner).

Pulls 'Needs Review' invoices from Monday, de-dupes Eurocell's second copy (deleting it and
clearing its amount from the order's INV1..INV5 columns), runs the SAME 3-way check the app
uses (invoice_core), and files each result on Monday:
  fully matched + margin in band -> Approved (To QB)   (pushed)
  matched but below the floor     -> Matched (TradeHub) (held)
  a real problem                  -> Discrepancy        (+ reason saved)
  anything unreadable/uncertain   -> left in Needs Review

SAFETY: DRY_RUN is ON by default — it only LOGS what it would do and writes NOTHING. Set
DRY_RUN=0 (or false) to make it write to Monday.

Env:  MONDAY_API_TOKEN, SHOPIFY_STORE, (SHOPIFY_ADMIN_TOKEN | SHOPIFY_CLIENT_ID+SECRET),
      ANTHROPIC_API_KEY.
Opt:  DRY_RUN (default '1'), INV_MARGIN_MIN (5), INV_MARGIN_MAX (35), MAX_INVOICES (40 cap).
"""
import os
import sys
import json
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Local runs can use a .env; CI provides the env directly.
_ENV = os.path.join(_HERE, ".env")
if os.path.exists(_ENV):
    for _line in open(_ENV, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import data_sources as ds          # noqa: E402  (after .env load)
import invoice_core as core        # noqa: E402

NEEDS_REVIEW_LABEL = 3             # status7__1 "Needs Review"
DRY_RUN = os.environ.get("DRY_RUN", "1").strip().lower() not in ("0", "false", "no", "off")
LO = float(os.environ.get("INV_MARGIN_MIN", core.MARGIN_PUSH_MIN))
HI = float(os.environ.get("INV_MARGIN_MAX", core.MARGIN_PUSH_MAX))
MAX_INVOICES = int(os.environ.get("MAX_INVOICES", "40"))


def log(*a):
    print(*a, flush=True)


def _load_lookup():
    p = os.path.join(_HERE, "pricing_lookup.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log("WARN: couldn't read pricing_lookup.json —", e)
    return {"items": [], "supplier_titles": {}}


def _dedup(invs):
    """Delete duplicate invoices (same order + invoice number) and clear the duplicate's
    amount from the order's INV columns. Returns the kept list."""
    kept, dups = core.dedup_plan(invs)
    if not dups:
        return kept
    order_state = {}
    for d in dups:
        log(f"  DUPLICATE {d.get('invoice_no')} (order {d.get('order_no')}, "
            f"£{d.get('total')}) -> {'would delete' if DRY_RUN else 'deleting'}")
        if DRY_RUN:
            continue
        try:
            ds.delete_subitem(d.get("sub_id"))
        except Exception as e:  # noqa: BLE001
            log("     delete failed:", str(e)[:120])
            continue
        pid, amt = d.get("order_item_id"), d.get("total")
        if pid and isinstance(amt, (int, float)):
            cols = order_state.setdefault(pid, dict(d.get("inv_columns") or {}))
            col = next((c for c, v in cols.items()
                        if isinstance(v, (int, float)) and abs(v - amt) <= 0.01), None)
            if col:
                try:
                    ds.set_order_number(pid, col, None)
                    cols[col] = None
                except Exception as e:  # noqa: BLE001
                    log("     INV-column clear failed:", str(e)[:120])
    return kept


def _read_pdf(inv):
    try:
        url = ds.monday_asset_url(inv["asset_id"])
        if not url:
            return {"error": "no download link"}
        return ds.read_invoice_pdf(url)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def main():
    log(f"=== invoice auto-check — {'DRY RUN (writes NOTHING)' if DRY_RUN else 'LIVE'} "
        f"· push floor {LO:.0f}% · flag > {HI:.0f}% ===")
    lookup = _load_lookup()
    pidx = core.pricelist_index(lookup)
    tidx = core.supplier_title_index(lookup)
    cidx = core.supplier_code_index(pidx)
    log(f"pricelist: {len(pidx)} SKUs · supplier-titles: {len(tidx)} · supplier-codes: {len(cidx)}")

    try:
        data = ds.fetch_invoices_by_status([NEEDS_REVIEW_LABEL], limit=500)
    except Exception as e:  # noqa: BLE001
        log("ERROR: couldn't fetch Needs Review from Monday —", e)
        return 1
    invs = data.get("invoices", [])
    log(f"Needs Review: {len(invs)} invoice(s)")
    if not invs:
        log("Nothing to do.")
        return 0

    invs = _dedup(invs)

    n = pushed = held = flagged = review = fail = 0
    for inv in invs[:MAX_INVOICES]:
        n += 1
        no, sup, sid = inv.get("invoice_no"), inv.get("supplier"), inv.get("shopify_order_id")
        if not inv.get("asset_id"):
            review += 1
            log(f"  {no} ({sup}): no PDF attached — left for review")
            continue
        parsed = _read_pdf(inv)
        if parsed.get("error"):
            fail += 1
            log(f"  {no} ({sup}): unreadable — {parsed['error'][:90]}")
            continue
        try:
            lines = ds.fetch_order_line_items(sid) if sid else None
        except Exception:  # noqa: BLE001
            lines = None
        order = core.order_candidates(lines, inv.get("order_items"))
        ship = None
        sup_n = core.norm_code(sup)
        if (core.is_carron(sup_n) or core.is_ctie(sup_n)) and sid:   # zone-priced delivery
            try:
                ship = ds.fetch_order_shipping(sid)
            except Exception:  # noqa: BLE001
                ship = None
        res = core.check_invoice(parsed, sup, order, pidx, tidx, cidx, ship)
        matched = res["n_issues"] == 0
        is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
        label, action = core.push_decision(matched, is_cn, inv.get("order_margin_live"),
                                            sup, LO, HI)
        m = inv.get("order_margin_live")
        verb = "would set" if DRY_RUN else "set"
        # Only auto-APPROVE or auto-HOLD. Never auto-mark Discrepancy — that's set by hand
        # after review + emailing the supplier. High-margin 'flag' and real mismatches are
        # LEFT in Needs Review.
        if action == "push":
            pushed += 1
        elif action == "hold":
            held += 1
        elif action == "flag":
            flagged += 1
            log(f"  {no} ({sup}, order {inv.get('order_no')}): matched, margin {m} > {HI:.0f}% "
                "-> left in Needs Review (high margin — check for a missing invoice)")
            continue
        else:
            review += 1
            log(f"  {no} ({sup}, order {inv.get('order_no')}): {res['n_issues']} issue(s) "
                "-> left in Needs Review for you to check")
            continue
        log(f"  {no} ({sup}, order {inv.get('order_no')}): {res['n_issues']} issue(s), "
            f"margin {m if m is not None else '—'} -> {verb} {label}")
        if not DRY_RUN:
            try:
                ds.set_invoice_status(inv["sub_id"], label)
            except Exception as e:  # noqa: BLE001
                log("     status write failed:", str(e)[:120])
        time.sleep(0.2)

    log(f"=== done · checked {n} · push {pushed} · hold {held} · flag {flagged} · "
        f"review {review} · unreadable {fail} ===")
    if DRY_RUN:
        log("DRY RUN — nothing was written to Monday. Set DRY_RUN=0 to go live.")
    return 0


REPORT_BOARD_NAME = "TradeHub — Invoice Auto-check Reports"


def report_run(hours=24):
    """Daily digest: read the subitems activity log for the last `hours`, list what was moved
    to Approved (To QB) and Matched (TradeHub), and POST it to a Monday board (created on first
    run). DRY_RUN just logs it."""
    from datetime import datetime, timezone, timedelta
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=hours)
    token = ds.get_token()
    try:
        logs = ds.fetch_board_activity(
            ds.SUBITEMS_BOARD_ID, from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), token=token)
    except Exception as e:  # noqa: BLE001
        log("ERROR fetching activity log:", e)
        return 1
    APPROVED = {"Approved (To QB)", "CN Approved (To QB)"}
    approved, matched = {}, {}
    for lg in logs:
        if lg.get("event") != "update_column_value":
            continue
        try:
            d = json.loads(lg.get("data") or "{}")
        except Exception:  # noqa: BLE001
            continue
        if d.get("column_id") != "status7__1":
            continue
        new = (((d.get("value") or {}).get("label") or {}).get("text"))
        sid = str(d.get("pulse_id"))
        if new in APPROVED:
            approved[sid] = d.get("pulse_name")
            matched.pop(sid, None)
        elif new == "Matched (TradeHub)" and sid not in approved:
            matched[sid] = d.get("pulse_name")

    ids = list(set(approved) | set(matched))
    details = ds._fetch_subitem_details(ids, token) if ids else {}

    def _amt(sid):
        v = (details.get(sid) or {}).get("total")
        return v if isinstance(v, (int, float)) else 0.0

    def _fmt(group):
        rows = []
        for sid, no in group.items():
            det = details.get(sid) or {}
            a = f"£{_amt(sid):,.2f}" if _amt(sid) else "—"
            rows.append(f"- {det.get('invoice_no') or no}  ·  order {det.get('order_no') or '?'}"
                        f"  ·  {det.get('supplier') or '?'}  ·  {a}")
        return rows or ["- none"]

    today = to_dt.astimezone().strftime("%d %b %Y")
    ap_tot = sum(_amt(s) for s in approved)
    mt_tot = sum(_amt(s) for s in matched)
    body = "\n".join(
        [f"Invoice auto-check — {today} (last {hours}h)", "",
         f"APPROVED TO QB: {len(approved)}  (£{ap_tot:,.2f})"] + _fmt(approved)
        + ["", f"MATCHED — held for review: {len(matched)}  (£{mt_tot:,.2f})"] + _fmt(matched))
    title = f"Auto-check {today} — {len(approved)} approved, {len(matched)} matched"
    log("=== daily report ===")
    log(body)
    if DRY_RUN:
        log("\nDRY RUN — not posting to Monday.")
        return 0
    try:
        board = ds.monday_find_or_create_board(REPORT_BOARD_NAME, token)
        item = ds.monday_create_item(board, title, token)
        ds.monday_post_update(item, body, token)
        log(f"\nPosted to Monday board '{REPORT_BOARD_NAME}' (item {item}).")
    except Exception as e:  # noqa: BLE001
        log("ERROR posting report to Monday:", e)
        return 1
    return 0


if __name__ == "__main__":
    if "--report" in sys.argv:
        sys.exit(report_run(int(os.environ.get("REPORT_HOURS", "24"))))
    sys.exit(main())

