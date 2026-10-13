"""Statement reconciliation core — Streamlit-free, shared by the API (and later the app).

No I/O here: pass in a PARSED supplier statement (from data_sources.read_statement_pdf) plus that
vendor's QuickBooks bills + payments, and get back the reconciliation — per-invoice rows, the
ready-to-pay list, credit notes, and totals. Mirrors app.py's _bulk_reconcile_one matching exactly,
so the new web app reconciles identically to the live app. Overdue flag + credit notes added.
"""
from __future__ import annotations

import re
from datetime import date


def norm_code(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_inv_no(inv, supplier=None):
    """Per-supplier invoice-number normalisation for statement ↔ QuickBooks matching (copied from
    app.py _norm_inv_no): strip an LPD 'NN/' prefix, a leading 'I' before digits (PJH), leading
    zeros for Eurocell/Toolbank, and reduce PJH to significant digits. Applied to BOTH sides."""
    inv = re.sub(r"^\s*\d{1,3}\s*/\s*", "", str(inv or ""))
    s = norm_code(inv)
    if not s:
        return s
    key = norm_code(supplier) if supplier else ""
    if s[:1] == "i" and s[1:2].isdigit():
        s = s[1:]
    if key.startswith("eurocell") or key.startswith("toolbank"):
        s = s.lstrip("0") or s
    if key.startswith("pjh"):
        s = re.sub(r"[^0-9]", "", s).lstrip("0") or s
    return s


def is_overdue(date_str):
    """Overdue once the INVOICE date is 2+ calendar months before the current month (Daniela's
    pay-by-end-of-next-month rule). YYYY-MM-DD string; False if unreadable."""
    try:
        d = date.fromisoformat(str(date_str)[:10])
    except Exception:  # noqa: BLE001
        return False
    today = date.today()
    return (today.year - d.year) * 12 + (today.month - d.month) >= 2


def reconcile(stmt: dict, bills: list, paymap: dict, supplier: str) -> dict:
    """Match a parsed statement's invoice lines to the vendor's QuickBooks bills.
    `bills` = data_sources.qbo_vendor_bills(vid); `paymap` = data_sources.qbo_vendor_payments(vid).
    Returns {rows, pay_lines, credits, to_pay, stmt_total, n_pay, n_paid, n_missing}."""
    bmap = {norm_inv_no(b["doc_no"], supplier): b for b in (bills or []) if b.get("doc_no")}
    rows, pay_lines, credits = [], [], []
    to_pay = stmt_total = 0.0
    n_pay = n_paid = n_missing = 0
    for ln in (stmt.get("lines") or []):
        typ = (ln.get("type") or "").lower()
        try:
            amt = float(ln.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        inv = str(ln.get("invoice_no") or "").strip()
        # Credit notes: an explicit credit line, or a negative amount — surfaced separately.
        if typ == "credit" or amt < 0:
            credits.append({"ref": inv, "date": ln.get("date"), "amount": round(amt, 2)})
            continue
        if typ != "invoice" or amt <= 0:
            continue
        try:
            val = float(ln.get("unpaid")) if ln.get("unpaid") is not None else amt
        except (TypeError, ValueError):
            val = amt
        stmt_total += amt
        overdue = is_overdue(ln.get("date"))
        b = bmap.get(norm_inv_no(inv, supplier))
        paid_ref, status = "", ""
        if b and b.get("paid"):
            pm = paymap.get(str(b["id"]))
            paid_ref = pm.get("ref", "") if pm else ""
            status, n_paid = "paid", n_paid + 1
        elif b:
            status, n_pay = "ready", n_pay + 1
            to_pay += val
            pay_lines.append({"inv": inv, "order": ln.get("order_ref") or "", "amt": round(val, 2),
                              "bill_id": b["id"], "stmt_due": ln.get("due_date"),
                              "inv_date": ln.get("date"), "bill_no": b.get("doc_no") or inv,
                              "due_date": b.get("due"), "balance": b.get("balance"),
                              "overdue": overdue})
        else:
            status, n_missing = "missing", n_missing + 1
        rows.append({"invoice": inv, "order": ln.get("order_ref") or "",
                     "inv_date": ln.get("date") or "", "amount": round(amt, 2),
                     "unpaid": round(val, 2), "due_date": ln.get("due_date") or "",
                     "paid_ref": paid_ref, "status": status, "overdue": overdue})
    stated = stmt.get("balance")
    on_stmt = stated if isinstance(stated, (int, float)) and stated > 0 else stmt_total
    return {"rows": rows, "pay_lines": pay_lines, "credits": credits,
            "to_pay": round(to_pay, 2), "stmt_total": round(on_stmt, 2),
            "n_pay": n_pay, "n_paid": n_paid, "n_missing": n_missing}
