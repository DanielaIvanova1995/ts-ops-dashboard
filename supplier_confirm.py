"""Classify supplier emails in the "Natasha - Supplier - No ETA" folder as PURE ORDER
CONFIRMATIONS — a supplier acknowledging one of our POs with nothing left for us to do — so they can
be auto-archived to "NV Resolved". HIGH PRECISION by design: any sign of an outstanding action, a
stock/timing/money/pricing issue, a question, or a closure leaves the email untouched.

This module is pure logic (no I/O) so it can be unit-tested and dry-run safely. The caller handles
reading the folder, matching the order on Monday, moving the email, and the audit log.

Rules mirror Daniela's spec (2026-11-10). Phase 1 = DRY RUN (classify + list only; never move).

Per-supplier handlers live below the generic classifier. CARRON (2026-11-10):
  * "booked in for you" → the agreed delivery date is read back from the thread → set Monday
    Customer ETA (col `date`) → archive to NV Resolved.
  * an order confirmation that still needs a delivery date ("when would your customer like
    delivery", "order confirmation attached") → move to "Supplier - ETAs" for someone to validate
    /upload the confirmation and RING THE CUSTOMER for a date (never archived).
"""
import re
import datetime as _dt

# ---- HARD EXCLUSIONS: if ANY appears, it is NOT a clean confirmation — leave it. -----------------
# Each entry is (category, compiled regex). Order doesn't matter; the first hit is reported.
_EXCLUSION_PATTERNS = [
    # Stock / timing
    ("stock/timing", r"out of stock"), ("stock/timing", r"\bno stock\b"),
    ("stock/timing", r"back\s?order"), ("stock/timing", r"discontinued"),
    ("stock/timing", r"not expected until"), ("stock/timing", r"lead\s?time"),
    ("stock/timing", r"\b\d+\s*weeks?\b"), ("stock/timing", r"\b\d+\s*working days?\b"),
    ("stock/timing", r"\beta\b"), ("stock/timing", r"\bdelay(ed|s)?\b"),
    ("stock/timing", r"awaiting stock"), ("stock/timing", r"on order with"),
    # Fulfilment
    ("fulfilment", r"can\s?no?t fulfil"), ("fulfilment", r"unable to (supply|fulfil|complete)"),
    ("fulfilment", r"won'?t be able"), ("fulfilment", r"out of (our )?delivery area"),
    # Money
    ("money", r"\bpayment\b"), ("money", r"pro[-\s]?forma"), ("money", r"\bto pay\b"),
    ("money", r"over (your )?credit limit"), ("money", r"account on hold"),
    ("money", r"outstanding balance"),
    # Pricing
    ("pricing", r"quotation"), ("pricing", r"\bquote\b"), ("pricing", r"\bprice[sd]?\b"),
    ("pricing", r"pricing"),
    # Questions / needs input
    ("question", r"please confirm"), ("question", r"please advise"), ("question", r"let us know"),
    ("question", r"how would you like"), ("question", r"contact (tel|telephone|number|no)"),
    ("question", r"delivery date"), ("question", r"could you (please )?"),
    ("question", r"can you (please )?(confirm|advise|send|provide)"),
    # Closure
    ("closure", r"cancel"), ("closure", r"refund"), ("closure", r"credit note"),
]
_EXCLUSIONS = [(cat, re.compile(p, re.I)) for cat, p in _EXCLUSION_PATTERNS]

# Accounts-only suppliers — archiving for them is handled elsewhere, never here.
_ACCOUNTS_ONLY = re.compile(r"\bc\s?tie\b|square\s?deal", re.I)

# ---- POSITIVE SIGNALS (need BOTH a PO reference AND a confirmation phrase) -----------------------
_PO_REF = re.compile(
    r"purchase order|\bp\.?\s?o\.?\b|sales order|\bs\.?o\.?\b|order (confirmation|acknowledg|number|no|ref)"
    r"|your order|our order|order\s*#?\s*\d{3,6}", re.I)
_CONFIRM = re.compile(
    r"thank you for your order|order (has been )?(received|placed|processed|confirmed|acknowledg)"
    r"|we (have )?(received|placed|processed|acknowledg)|has been (placed|received|processed)"
    r"|is confirmed|confirmation of your order|order confirmation|acknowledg(e|ement) of your order"
    r"|booked in|all booked in|has been booked",   # Carron etc. confirm with "booked in for you"
    re.I)

# TSO order number — used to find the order on the Monday board. Suppliers label OUR number in
# different ways; prefer the most TSO-specific first so we never grab the supplier's own account
# code (e.g. PJH: "Account Code: 33441" vs the real "Your Ref: 33446").
_REF_LABELLED = re.compile(r"(?:your\s*ref(?:erence)?|customer\s*ref(?:erence)?|cust\s*ref|your\s*order)\s*:?\s*#?\s*(\d{4,6})", re.I)
_ORDER_LABELLED = re.compile(r"(?:purchase order|p\.?\s?o\.?|order|\bref)\s*:?\s*#?\s*(\d{4,6})", re.I)
_ANY_5DIG = re.compile(r"\b(\d{5})\b")


def extract_order_no(subject, body):
    """Best-guess TSO order number for the Monday lookup. Priority: an explicitly TSO-labelled ref
    ("Your Ref" / "Customer Ref" / "Your Order"), then a Purchase-Order/Order/Ref number, then any
    bare 5-digit number. None if none. The SUBJECT is checked before the body (most reliable)."""
    for text in (subject or "", f"{subject or ''}\n{body or ''}"):
        for rx in (_REF_LABELLED, _ORDER_LABELLED):
            m = rx.search(text)
            if m:
                return m.group(1)
    m = _ANY_5DIG.search(f"{subject or ''}\n{body or ''}")
    return m.group(1) if m else None


def classify(subject, body, sender=""):
    """Decide whether an email is a pure order confirmation safe to archive.

    Returns a dict:
      verdict: "confirmation" (would archive) | "leave" (do nothing)
      reason:  short human explanation
      exclusion: the exclusion category that blocked it, or None
      order_no: extracted TSO order number (for the Monday match), or None
    HIGH PRECISION: exclusions win over positive signals; both a PO ref and a confirm phrase are
    required to call it a confirmation.
    """
    subj = subject or ""
    bod = body or ""
    text = f"{subj}\n{bod}"
    order_no = extract_order_no(subj, bod)

    # Accounts-only suppliers are never archived here.
    if _ACCOUNTS_ONLY.search(f"{sender}\n{text}"):
        return {"verdict": "leave", "reason": "Accounts-only supplier (C TIE / Squaredeal) — handled elsewhere",
                "exclusion": "accounts-only", "order_no": order_no}

    # Any hard exclusion → leave.
    for cat, rx in _EXCLUSIONS:
        m = rx.search(text)
        if m:
            return {"verdict": "leave", "reason": f"Excluded ({cat}): matched “{m.group(0).strip()}”",
                    "exclusion": cat, "order_no": order_no}

    has_ref = bool(_PO_REF.search(text))
    conf = _CONFIRM.search(text)
    if has_ref and conf:
        return {"verdict": "confirmation",
                "reason": f"Order confirmation: “{conf.group(0).strip()}”" + (f" · order {order_no}" if order_no else ""),
                "exclusion": None, "order_no": order_no}

    # Not a clear confirmation.
    if not has_ref:
        why = "No PO/order reference found"
    else:
        why = "Has an order reference but no clear 'received/placed/processed' confirmation"
    return {"verdict": "leave", "reason": why, "exclusion": None, "order_no": order_no}


# =================================================================================================
# CARRON handler
# =================================================================================================
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6}
# "Sent: 10 November 2026 10:23" headers in a quoted thread — anchor relative words to the message
# that actually wrote them.
_SENT_HDR = re.compile(r"Sent:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)
_EXPLICIT_DMY = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_EXPLICIT_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)
_REL = re.compile(r"\b(tomorrow|today)\b", re.I)
_DAYNAME = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

_CARRON_BOOKED = re.compile(r"booked in", re.I)
# Carron still needs a delivery date from us (ring the customer) / sent an order confirmation to check.
_CARRON_NEEDS_ETA = re.compile(
    r"when (would |will )?(your|the) customer would like delivery|would like delivery"
    r"|order confirmation (is )?attached|please see your order confirmation|thank you for your order",
    re.I)


def _anchor_date_for(text, pos, fallback):
    """The 'Sent:' date of the quoted message that contains position `pos` (so 'tomorrow' is measured
    from when it was written, not when Carron later booked in). Falls back to `fallback`."""
    best = None
    for m in _SENT_HDR.finditer(text):
        if m.start() < pos:
            try:
                best = _dt.date(int(m.group(3)), _MONTHS.get(m.group(2).lower(), 0), int(m.group(1)))
            except (ValueError, TypeError):
                continue
    return best or fallback


def parse_delivery_date(body, email_date):
    """Pull the agreed delivery date out of a Carron thread. Returns (iso_date|None, confidence, note).
    Priority: an explicit calendar date, then a weekday name, then 'tomorrow'/'today' — the last two
    measured from the quoted reply that wrote them. Quoted 'Sent:' header dates are NOT treated as
    delivery dates. None → caller flags 'set ETA manually'."""
    text = body or ""
    # Spans of the quoted "Sent: 10 November 2026" headers — their dates are when a reply was WRITTEN,
    # never the delivery date, so explicit-date matching must skip them.
    sent_spans = [(m.start(), m.end()) for m in _SENT_HDR.finditer(text)]

    def _in_sent(p):
        return any(a <= p < b for a, b in sent_spans)

    # 1) explicit "11 November" / "11th Nov" (not inside a Sent header)
    for m in _EXPLICIT_DM.finditer(text):
        if _in_sent(m.start()):
            continue
        mon = _MONTHS[[k for k in _MONTHS if k.startswith(m.group(2).lower())][0]]
        yr = email_date.year
        try:
            d = _dt.date(yr, mon, int(m.group(1)))
            if d < email_date - _dt.timedelta(days=1):   # rolled into next year
                d = _dt.date(yr + 1, mon, int(m.group(1)))
            return d.isoformat(), "high", f"explicit date “{m.group(0)}”"
        except ValueError:
            pass
    # 2) explicit dd/mm(/yy) (not inside a Sent header)
    for m in _EXPLICIT_DMY.finditer(text):
        if _in_sent(m.start()):
            continue
        dd, mm = int(m.group(1)), int(m.group(2))
        yy = m.group(3)
        yr = (2000 + int(yy)) if (yy and len(yy) == 2) else (int(yy) if yy else email_date.year)
        try:
            return _dt.date(yr, mm, dd).isoformat(), "high", f"explicit date “{m.group(0)}”"
        except ValueError:
            pass
    # 3) weekday name → the next such weekday after the anchor
    m = _DAYNAME.search(text)
    if m:
        anchor = _anchor_date_for(text, m.start(), email_date)
        delta = (_WEEKDAYS[m.group(1).lower()] - anchor.weekday()) % 7
        delta = delta or 7
        return (anchor + _dt.timedelta(days=delta)).isoformat(), "med", f"“{m.group(1)}” after {anchor.isoformat()}"
    # 4) tomorrow / today
    m = _REL.search(text)
    if m:
        anchor = _anchor_date_for(text, m.start(), email_date)
        add = 1 if m.group(1).lower() == "tomorrow" else 0
        return (anchor + _dt.timedelta(days=add)).isoformat(), "med", f"“{m.group(1)}” from {anchor.isoformat()}"
    return None, "none", "no delivery date found in the thread"


def classify_carron(subject, body, sender="", email_date=None):
    """Carron-specific routing. Returns dict: action (booked_in | needs_eta | leave), dest folder,
    order_no, eta (iso|None) + eta_conf/eta_note for booked_in, reason."""
    email_date = email_date or _dt.date.today()
    text = f"{subject or ''}\n{body or ''}"
    order_no = extract_order_no(subject, body)
    # A genuine problem (stock / money / cancel / fulfilment) always wins — leave for a human.
    for cat, rx in _EXCLUSIONS:
        if cat in ("stock/timing", "money", "closure", "fulfilment") and rx.search(text):
            m = rx.search(text)
            return {"action": "leave", "dest": None, "order_no": order_no,
                    "reason": f"Problem ({cat}): “{m.group(0).strip()}” — needs a human"}
    if _CARRON_BOOKED.search(text):
        eta, conf, note = parse_delivery_date(body, email_date)
        return {"action": "booked_in", "dest": "NV Resolved", "order_no": order_no,
                "eta": eta, "eta_conf": conf, "eta_note": note,
                "reason": ("Booked in — set Customer ETA " + (eta or "(none: flag to set manually)"))}
    if _CARRON_NEEDS_ETA.search(text):
        return {"action": "needs_eta", "dest": "Supplier - ETAs", "order_no": order_no,
                "reason": "Order confirmation — validate/upload + ring the customer for a delivery date"}
    return {"action": "leave", "dest": None, "order_no": order_no,
            "reason": "Not a Carron confirmation or ETA request"}


# --- Order-confirmation money-check (line-by-line vs Shopify + prices + carriage + margin) ---------
SHOPIFY_FEE_PCT = 1.8        # card/platform fee taken off the customer's inc-VAT payment
MARGIN_FLOOR_PCT = 10.0     # below this (after the fee) = flag, don't lose money even if lines match
_CARRIAGE_SKU = re.compile(r"carriage|deliver|shipping|freight|pallet", re.I)


def _nsku(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def validate_confirmation(conf_lines, conf_carriage, order, our_costs=None, expected_carriage=None,
                          fee_pct=SHOPIFY_FEE_PCT, floor_pct=MARGIN_FLOOR_PCT):
    """Validate a supplier order confirmation against the Shopify order and the money.

    conf_lines: [{sku, desc, qty, unit_price}] product lines from the confirmation PDF (carriage
                excluded — pass it as conf_carriage).
    conf_carriage: £ ex-VAT carriage the supplier is charging us (0 if none).
    order: {lines:[{sku, title, qty, sell_ex_vat}], shipping_ex_vat, total_inc_vat}.
    our_costs: optional {sku: our_agreed_ex_vat_cost} — flags an overcharge when present.
    expected_carriage: optional £ we expect the supplier to charge (e.g. Carron zone rate).

    Returns {verdict: 'validated'|'review', issues:[...], margin_pct, profit, sell, cost, fee, lines:[...]}.
    HIGH CAUTION: any line mismatch, overcharge, carriage mismatch OR margin below floor → 'review'.
    """
    issues = []
    conf_by = {}
    for c in (conf_lines or []):
        conf_by.setdefault(_nsku(c.get("sku")), []).append(c)
    ord_by = {}
    for o in (order.get("lines") or []):
        ord_by.setdefault(_nsku(o.get("sku")), []).append(o)

    line_report = []
    all_verified = our_costs is not None   # did we confirm EVERY product line's price vs our cost?
    overcharge = False
    # Every Shopify line must appear on the confirmation at the right qty.
    for k, olist in ord_by.items():
        oq = sum(float(o.get("qty") or 0) for o in olist)
        clist = conf_by.get(k) or []
        cq = sum(float(c.get("qty") or 0) for c in clist)
        title = olist[0].get("title") or olist[0].get("sku")
        if not clist:
            issues.append(f"On the order but NOT on the confirmation: {title} (SKU {olist[0].get('sku')})")
            line_report.append({"sku": olist[0].get("sku"), "title": title, "status": "missing"})
            continue
        if abs(cq - oq) > 0.001:
            issues.append(f"Qty mismatch for {title}: order {oq:g} vs confirmation {cq:g}")
        unit = clist[0].get("unit_price")
        if our_costs is not None:
            oc = our_costs.get(olist[0].get("sku")) or our_costs.get(k)
            if oc is None or unit is None:
                all_verified = False
            elif float(unit) > float(oc) + 0.01:
                issues.append(f"Overcharge on {title}: £{float(unit):.2f} vs our cost £{float(oc):.2f}")
                overcharge = True
        line_report.append({"sku": olist[0].get("sku"), "title": title, "status": "ok",
                            "qty": oq, "unit_price": unit})
    # Extra lines on the confirmation that aren't on the order (ignore carriage-type lines).
    for k, clist in conf_by.items():
        if k not in ord_by and not _CARRIAGE_SKU.search((clist[0].get("sku") or "") + " " + (clist[0].get("desc") or "")):
            issues.append(f"On the confirmation but NOT on the order: {clist[0].get('desc') or clist[0].get('sku')}")
            line_report.append({"sku": clist[0].get("sku"), "title": clist[0].get("desc"), "status": "extra"})

    # Carriage check.
    if expected_carriage is not None and conf_carriage is not None \
            and abs(float(conf_carriage) - float(expected_carriage)) > 0.01:
        issues.append(f"Carriage £{float(conf_carriage):.2f} vs expected £{float(expected_carriage):.2f}")

    # Money: sell (ex VAT, products + what the customer paid for shipping) vs cost (confirmation incl
    # carriage), minus the platform fee on the customer's inc-VAT total.
    sell = round(sum(float(o.get("sell_ex_vat") or 0) for o in (order.get("lines") or []))
                 + float(order.get("shipping_ex_vat") or 0), 2)
    cost = round(sum(float(c.get("unit_price") or 0) * float(c.get("qty") or 0) for c in (conf_lines or []))
                 + float(conf_carriage or 0), 2)
    fee = round(float(order.get("total_inc_vat") or 0) * fee_pct / 100.0, 2)
    profit = round(sell - cost - fee, 2)
    margin_pct = round(profit / sell * 100.0, 1) if sell else None
    matches_pricelist = all_verified and not overcharge   # supplier charged us our agreed prices
    note = None
    if margin_pct is None:
        issues.append("Can't read the sell price — margin unknown")
    elif matches_pricelist:
        # Prices match our pricelist, so a thin margin is just a low-margin sale we already made —
        # NOT a reason to hold the confirmation for review (Daniela 2026-11-10). Only an actual LOSS
        # still gets flagged.
        if profit < 0:
            issues.append(f"We'd LOSE £{abs(profit):.2f} on this (margin {margin_pct:.1f}% after the "
                          f"{fee_pct:g}% fee) even though prices match — check before proceeding")
        elif margin_pct < floor_pct:
            note = f"Thin margin {margin_pct:.1f}% after the {fee_pct:g}% fee, but prices match our pricelist — OK to proceed"
    elif margin_pct < floor_pct:
        # Price NOT verified against our pricelist (or an overcharge) — margin is the safeguard.
        issues.append(f"Margin only {margin_pct:.1f}% after the {fee_pct:g}% fee (floor {floor_pct:g}%) "
                      f"and prices not confirmed against our pricelist — review")

    return {"verdict": "review" if issues else "validated", "issues": issues, "note": note,
            "margin_pct": margin_pct, "profit": profit, "sell": sell, "cost": cost, "fee": fee,
            "matches_pricelist": matches_pricelist, "lines": line_report}


# =================================================================================================
# RUNNER — decides the planned action per email WITHOUT doing it (dry run). The caller injects the
# real I/O via `deps` so this stays pure/testable. `deps` provides:
#   find_monday(order_no)            -> monday item id | None
#   fetch_confirmation(email)        -> (conf_lines, carriage) | None   (parse the attached PDF)
#   fetch_order(order_no)            -> {lines, shipping_ex_vat, total_inc_vat, postcode} | None
#   our_costs(order_no)              -> {sku: our_ex_vat_cost}           (Carron pricelist)
#   expected_carriage(order)         -> £ | None                         (Carron zone rate)
# =================================================================================================
# Short Monday notes (Daniela: keep updates short). The Supplier-ETAs note tells whoever picks the
# order up to phone the customer and agree a date, so Carron don't turn up to an empty house and bill
# us a re-delivery charge.
CARRON_RING_NOTE = "☎ Ring customer to agree a delivery date — avoids a re-delivery charge."
NV_RESOLVED = "NV Resolved"
SUPPLIER_ETAS = "Supplier - ETAs"


def plan_carron_email(email, deps):
    """Return the PLAN for one Carron folder email. `do` is the live directive the runner executes
    (attach PDF / set ETA / post update / move folder); an empty `do` means leave it in the folder."""
    r = classify_carron(email.get("subject"), email.get("body"), email.get("sender", ""),
                        email.get("date"))
    base = {"subject": email.get("subject"), "order_no": r.get("order_no"), "email_id": email.get("id"),
            "action": r["action"], "dest": r.get("dest"), "do": {}}

    if r["action"] == "leave":
        return {**base, "plan": "LEAVE in folder", "reason": r["reason"]}

    mon = deps.find_monday(r["order_no"]) if r.get("order_no") else None

    if r["action"] == "booked_in":
        if not mon:
            return {**base, "plan": "FLAG — no matching Monday order (don't archive)",
                    "reason": f"order {r.get('order_no') or '?'} not found on the board"}
        if not r.get("eta"):
            return {**base, "monday": mon, "plan": "ARCHIVE to NV Resolved + FLAG 'set ETA manually'",
                    "reason": r.get("eta_note"),
                    "do": {"move_to": NV_RESOLVED,
                           "update": "⚠ Carron booked this in — set the Customer ETA manually (date couldn't be auto-read)."}}
        return {**base, "monday": mon, "eta": r["eta"],
                "plan": f"SET Customer ETA {r['eta']} + ✅ confirmed update + ARCHIVE to NV Resolved",
                "reason": r["reason"],
                "do": {"set_eta": r["eta"], "move_to": NV_RESOLVED,
                       "update": f"✅ Carron confirmed delivery {r['eta']}."}}

    if r["action"] == "needs_eta":
        if not mon:
            return {**base, "plan": "FLAG — order confirmation but no matching Monday order",
                    "reason": f"order {r.get('order_no') or '?'} not found on the board"}
        conf = deps.fetch_confirmation(email)
        if not conf:
            return {**base, "monday": mon, "validation": None,
                    "plan": "MOVE to Supplier - ETAs (⚠ couldn't read the confirmation PDF — validate by hand)",
                    "do": {"attach": True, "move_to": SUPPLIER_ETAS, "update": CARRON_RING_NOTE}}
        conf_lines, carriage = conf
        order = deps.fetch_order(r["order_no"])
        if not order:
            return {**base, "monday": mon, "plan": "FLAG — couldn't read the Shopify order",
                    "reason": f"order {r['order_no']} not found in Shopify"}
        v = validate_confirmation(conf_lines, carriage, order,
                                  our_costs=deps.our_costs(order),
                                  expected_carriage=deps.expected_carriage(order))
        if v["verdict"] == "validated":
            msg = "MOVE to Supplier - ETAs (✅ validated — ring customer for a date)"
            if v.get("note"):
                msg += f" · {v['note']}"
            return {**base, "monday": mon, "plan": msg, "validation": v,
                    "do": {"attach": True, "move_to": SUPPLIER_ETAS, "update": CARRON_RING_NOTE}}
        return {**base, "monday": mon, "plan": "FLAG for review — do NOT hand over",
                "reason": "; ".join(v["issues"]), "validation": v}

    return {**base, "plan": "LEAVE in folder", "reason": r.get("reason")}


# =================================================================================================
# LPD (Leeds Plywood & Doors) handler — sales-order confirmations whose OUR-order reference sits
# INSIDE the PDF (the email only says 'document attached'). Clean + validated → archive to NV
# Resolved; a backorder, an amendment, or a price/line/margin issue → flag (never auto-archived).
# =================================================================================================
_LPD_BACKORDER = re.compile(r"back\s?order", re.I)
_LPD_AMENDED = re.compile(r"amend", re.I)


def classify_lpd(subject, body, sender=""):
    text = f"{subject or ''}\n{body or ''}"
    if _LPD_BACKORDER.search(text):
        return {"action": "flag", "reason": "Backorder confirmation — stock issue, needs a human"}
    if _LPD_AMENDED.search(text):
        return {"action": "flag", "reason": "Amended sales order — review the change before clearing"}
    return {"action": "confirm", "reason": "LPD sales-order confirmation"}


def plan_lpd_email(email, deps):
    """Dry-run plan for one LPD sales-order email. deps.fetch_confirmation returns
    (product_lines, carriage£, our_order_ref) — the order ref comes from INSIDE the PDF."""
    r = classify_lpd(email.get("subject"), email.get("body"), email.get("sender", ""))
    base = {"supplier": "LPD", "subject": email.get("subject"), "order_no": None,
            "email_id": email.get("id"), "action": r["action"], "do": {}}
    sig = delay_signal(email.get("subject"), email.get("body"))
    if sig:
        return {**base, "action": "flag", "reason": f"delay signal: {sig}",
                "plan": f"FLAG — email mentions “{sig}” (possible delay) — check by hand"}
    if r["action"] == "flag":
        return {**base, "plan": f"FLAG — {r['reason']} (leave in folder)", "reason": r["reason"]}
    conf = deps.fetch_confirmation(email)
    if not conf:
        return {**base, "action": "flag", "plan": "FLAG — couldn't read the sales-order PDF (check by hand)", "reason": "PDF unreadable"}
    lines, carriage, order_no, stock_warning = conf
    base["order_no"] = order_no
    if stock_warning:
        return {**base, "action": "flag", "reason": f"delay signal on the PDF: {stock_warning}",
                "plan": f"FLAG — the document mentions “{stock_warning}” (possible delay) — check by hand"}
    if not order_no:
        return {**base, "action": "flag", "plan": "FLAG — no customer order reference on the PDF (can't match our order)", "reason": "no order ref"}
    mon = deps.find_monday(order_no)
    if not mon:
        return {**base, "action": "flag", "plan": f"FLAG — order {order_no} not found on Monday", "reason": "no Monday match"}
    order = deps.fetch_order(order_no)
    if not order:
        return {**base, "action": "flag", "monday": mon, "plan": f"FLAG — couldn't read Shopify order {order_no}", "reason": "no Shopify order"}
    v = validate_confirmation(lines, carriage, order, our_costs=deps.our_costs(order),
                              expected_carriage=deps.expected_carriage(order))
    if v["verdict"] == "validated":
        msg = "ARCHIVE to NV Resolved (✅ validated — sales order confirmed)"
        if v.get("note"):
            msg += f" · {v['note']}"
        return {**base, "action": "confirm", "monday": mon, "plan": msg, "validation": v,
                "do": {"attach": True, "move_to": NV_RESOLVED,
                       "update": "✅ LPD sales order confirmed — attached to Job."}}
    return {**base, "action": "flag", "monday": mon, "plan": "FLAG for review — do NOT archive",
            "reason": "; ".join(v["issues"]), "validation": v}


def plan_lpd_folder(emails, deps):
    return [plan_lpd_email(e, deps) for e in (emails or [])]


# =================================================================================================
# Shared DELAY guard (Daniela 2026-11-10): never auto-clear an order if the email OR the document
# mentions anything that could delay it (out of stock, back order, discontinued, lead time, to
# follow…). The parsed PDF surfaces this as `stock_warning`; this regex catches it on the email text.
# =================================================================================================
_DELAY_RE = re.compile(
    r"out[\s-]?of[\s-]?stock|\bno stock\b|not in stock|back[\s-]?order|\boos\b|discontinued|"
    r"awaiting stock|to follow|on back[\s-]?order|no longer available|unavailable|lead[\s-]?time|"
    r"\bdelay(?:ed|s)?\b|not expected until", re.I)


def delay_signal(*texts):
    """Return the first delay/stock phrase found across the given texts, else None."""
    for t in texts:
        if not t:
            continue
        m = _DELAY_RE.search(str(t))
        if m:
            return m.group(0)
    return None


# =================================================================================================
# SOUTHERN SHEETING handler — two email types in the 'Sales Orders' subfolder:
#   * "Sales Order SOxxxx" (order confirmation, our ref INSIDE the PDF) → money-check (8% floor) →
#     attach to Job + archive to NV Resolved.
#   * "Delivery Date Booked - Order SOxxxx" (the date is in the body) → set Customer ETA + archive.
# Southern Sheeting books the delivery itself, so NOTHING routes to Supplier-ETAs (Daniela 2026-11-10).
# Any out-of-stock / back-order / delay wording on the email OR the PDF → flag, never archived.
# =================================================================================================
_SS_BOOKED_RE = re.compile(r"delivery date booked|booked for delivery", re.I)
_SS_AMEND_RE = re.compile(r"\bamend", re.I)
_SS_CONFIRM_RE = re.compile(r"sales order|confirmation of your order|thank you for your (?:recent )?order", re.I)
_SS_DATE_RE = re.compile(r"booked for delivery on[^0-9]*?(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I)


def parse_ss_booked_date(body):
    """'…booked for delivery on Friday, 13 November 2026.' → '2026-11-13'. None if not found."""
    m = _SS_DATE_RE.search(body or "")
    if not m:
        return None
    try:
        return _dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def classify_ss(subject, body, sender=""):
    text = f"{subject or ''}\n{body or ''}"
    if _SS_AMEND_RE.search(text):
        return {"type": "flag", "reason": "Amended order — review the change before clearing"}
    if _SS_BOOKED_RE.search(text):
        return {"type": "booked"}
    if _SS_CONFIRM_RE.search(text):
        return {"type": "confirm"}
    return {"type": "flag", "reason": "Not a recognised Southern Sheeting sales-order email"}


def plan_ss_email(email, deps):
    """Plan for one Southern Sheeting email. deps.fetch_confirmation(email) returns
    (lines, carriage, our_order_ref, stock_warning). `do` is the live directive the runner executes."""
    subj, body = email.get("subject"), email.get("body")
    base = {"supplier": "Southern Sheeting", "subject": subj, "email_id": email.get("id"),
            "order_no": None, "action": "flag", "do": {}}

    sig = delay_signal(subj, body)
    if sig:
        return {**base, "plan": f"FLAG — email mentions “{sig}” (possible delay) — check by hand",
                "reason": f"delay signal: {sig}"}
    c = classify_ss(subj, body, email.get("sender", ""))
    if c["type"] == "flag":
        return {**base, "plan": f"FLAG — {c['reason']} (leave in folder)", "reason": c["reason"]}

    conf = deps.fetch_confirmation(email)
    if not conf:
        return {**base, "plan": "FLAG — couldn't read the sales-order PDF (check by hand)", "reason": "PDF unreadable"}
    lines, carriage, order_no, stock_warning = conf
    base["order_no"] = order_no
    if stock_warning:
        return {**base, "plan": f"FLAG — the document mentions “{stock_warning}” (possible delay) — check by hand",
                "reason": f"delay signal on the PDF: {stock_warning}"}
    if not order_no:
        return {**base, "plan": "FLAG — no customer order reference on the PDF (can't match our order)", "reason": "no order ref"}
    mon = deps.find_monday(order_no)
    if not mon:
        return {**base, "plan": f"FLAG — order {order_no} not found on Monday", "reason": "no Monday match"}

    if c["type"] == "booked":
        eta = parse_ss_booked_date(body)
        if eta:
            return {**base, "action": "booked", "monday": mon, "eta": eta,
                    "plan": f"SET Customer ETA {eta} + ARCHIVE to NV Resolved", "reason": "SS booked delivery",
                    "do": {"set_eta": eta, "move_to": NV_RESOLVED,
                           "update": f"✅ Southern Sheeting booked delivery {eta}."}}
        return {**base, "action": "booked", "monday": mon,
                "plan": "ARCHIVE to NV Resolved + FLAG 'set ETA manually'", "reason": "couldn't read the booked date",
                "do": {"move_to": NV_RESOLVED,
                       "update": "⚠ Southern Sheeting booked delivery — set the Customer ETA manually (date couldn't be read)."}}

    # confirm
    order = deps.fetch_order(order_no)
    if not order:
        return {**base, "monday": mon, "plan": f"FLAG — couldn't read Shopify order {order_no}", "reason": "no Shopify order"}
    v = validate_confirmation(lines, carriage, order, our_costs=deps.our_costs(order),
                              expected_carriage=deps.expected_carriage(order), floor_pct=8.0)
    if v["verdict"] == "validated":
        msg = "ARCHIVE to NV Resolved (✅ validated — order confirmed)"
        if v.get("note"):
            msg += f" · {v['note']}"
        return {**base, "action": "confirm", "monday": mon, "plan": msg, "validation": v,
                "do": {"attach": True, "move_to": NV_RESOLVED,
                       "update": "✅ Southern Sheeting order confirmed — attached to Job."}}
    return {**base, "monday": mon, "plan": "FLAG for review — do NOT archive",
            "reason": "; ".join(v["issues"]), "validation": v}


def plan_ss_folder(emails, deps):
    return [plan_ss_email(e, deps) for e in (emails or [])]


# =================================================================================================
# GENERIC order-confirmation suppliers (JB Kind, Vista, MB DIY, Roxor…). All follow the same shape:
# a PDF acknowledgement of our PO → money-check → attach to Job + archive to NV Resolved. They differ
# only in how OUR order ref is found (the email subject, the email body, or the PDF's customer_ref)
# and the margin floor. Driven by SIMPLE_CONFIRM config so a new supplier is a few lines, no new code.
# Any delay/stock wording on the email OR the PDF → flag (never archived).
# =================================================================================================
SIMPLE_CONFIRM = {
    # order no is in the subject: "Sales Order Acknowledgement 219312 - Your Order 33408"
    "jbkind": {"name": "JB Kind", "subject_re": r"your order\s+(\d{3,})", "floor": 10.0},
    # ref inside the PDF (the email only says "order acknowledgement attached")
    "vista": {"name": "Vista", "floor": 10.0},
    "mbdiy": {"name": "MB DIY", "floor": 10.0},
    # Roxor/Ultra Finishing: body "Your Reference: 32930_1-REM" → our order 32930
    "roxor": {"name": "Roxor", "body_re": r"your reference:\s*(\d{3,})", "floor": 10.0},
}
_SIMPLE_AMEND_RE = re.compile(r"\bamend|\brevised\b", re.I)


def plan_simple_email(email, deps, cfg):
    """Generic confirmation plan. deps.fetch_confirmation(email) → (lines, carriage, pdf_ref, stock).
    Order ref: subject regex, then body regex, then the PDF's customer_ref. `do` is the live directive."""
    subj, body = email.get("subject") or "", email.get("body") or ""
    base = {"supplier": cfg["name"], "subject": email.get("subject"), "email_id": email.get("id"),
            "order_no": None, "action": "flag", "do": {}}

    sig = delay_signal(subj, body)
    if sig:
        return {**base, "plan": f"FLAG — email mentions “{sig}” (possible delay) — check by hand", "reason": f"delay signal: {sig}"}
    if _SIMPLE_AMEND_RE.search(f"{subj}\n{body}"):
        return {**base, "plan": "FLAG — amended/revised order — review the change (leave in folder)", "reason": "amended"}

    order_no = None
    if cfg.get("subject_re"):
        m = re.search(cfg["subject_re"], subj, re.I)
        order_no = m.group(1) if m else None
    if not order_no and cfg.get("body_re"):
        m = re.search(cfg["body_re"], body, re.I)
        order_no = m.group(1) if m else None

    conf = deps.fetch_confirmation(email)
    if not conf:
        return {**base, "plan": "FLAG — couldn't read the confirmation PDF (check by hand)", "reason": "PDF unreadable"}
    lines, carriage, pdf_ref, stock = conf
    if stock:
        return {**base, "plan": f"FLAG — the document mentions “{stock}” (possible delay) — check by hand",
                "reason": f"delay signal on the PDF: {stock}"}
    if not order_no:
        order_no = pdf_ref
    base["order_no"] = order_no
    if not order_no:
        return {**base, "plan": "FLAG — no order reference found (subject, body or PDF)", "reason": "no order ref"}
    mon = deps.find_monday(order_no)
    if not mon:
        return {**base, "plan": f"FLAG — order {order_no} not found on Monday", "reason": "no Monday match"}
    order = deps.fetch_order(order_no)
    if not order:
        return {**base, "monday": mon, "plan": f"FLAG — couldn't read Shopify order {order_no}", "reason": "no Shopify order"}
    v = validate_confirmation(lines, carriage, order, our_costs=deps.our_costs(order),
                              expected_carriage=deps.expected_carriage(order), floor_pct=cfg.get("floor", 10.0))
    if v["verdict"] == "validated":
        msg = "ARCHIVE to NV Resolved (✅ validated — order confirmed)"
        if v.get("note"):
            msg += f" · {v['note']}"
        return {**base, "action": "confirm", "monday": mon, "plan": msg, "validation": v,
                "do": {"attach": True, "move_to": NV_RESOLVED, "update": f"✅ {cfg['name']} order confirmed — attached to Job."}}
    return {**base, "monday": mon, "plan": "FLAG for review — do NOT archive",
            "reason": "; ".join(v["issues"]), "validation": v}


def plan_simple_folder(emails, deps, cfg):
    return [plan_simple_email(e, deps, cfg) for e in (emails or [])]


def plan_folder(emails, deps):
    """Dry-run plan for a list of Carron folder emails, with per-order dedupe: when several emails
    share an order number and the LATEST one resolves it (booked-in → archive, or a validated move),
    the earlier ones in that now-settled thread are archived as 'superseded' rather than re-actioned.
    If the latest is still open (a problem/question/leave), every email in the thread is left as-is.
    Needs each email to carry a sortable `received` (ISO) or `date` for ordering."""
    planned = [(e, plan_carron_email(e, deps)) for e in (emails or [])]
    groups = {}
    for e, p in planned:
        groups.setdefault(p.get("order_no"), []).append((e, p))
    out = []
    for no, items in groups.items():
        if not no or len(items) == 1:
            out.extend(p for _, p in items)
            continue
        items.sort(key=lambda ep: str(ep[0].get("received") or ep[0].get("date") or ""), reverse=True)
        _, latest = items[0]
        resolving = ((latest["action"] == "booked_in" and "ARCHIVE" in latest.get("plan", ""))
                     or (latest["action"] == "needs_eta" and latest.get("plan", "").startswith("MOVE")))
        out.append(latest)
        for _, p in items[1:]:
            if resolving:
                out.append({**p, "plan": f"ARCHIVE to NV Resolved — superseded by the later "
                            f"{latest['action'].replace('_', ' ')} on order {no}", "superseded": True,
                            "do": {"move_to": NV_RESOLVED}})
            else:
                out.append(p)
    return out
