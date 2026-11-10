"""Classify supplier emails in the "Natasha - Supplier - No ETA" folder as PURE ORDER
CONFIRMATIONS — a supplier acknowledging one of our POs with nothing left for us to do — so they can
be auto-archived to "NV Resolved". HIGH PRECISION by design: any sign of an outstanding action, a
stock/timing/money/pricing issue, a question, or a closure leaves the email untouched.

This module is pure logic (no I/O) so it can be unit-tested and dry-run safely. The caller handles
reading the folder, matching the order on Monday, moving the email, and the audit log.

Rules mirror Daniela's spec (2026-11-10). Phase 1 = DRY RUN (classify + list only; never move).
"""
import re

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
