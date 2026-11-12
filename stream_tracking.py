"""National Skirting / Stream (go2stream) tracking-email engine — PURE logic (no I/O), so it's unit-
testable and shared by the API dry-run + live run.

National Skirting dropship orders are delivered by Stream (go2stream.net), which emails a live
tracking link to hello@/orders@ once the order is on their delivery system. The manual process is:
  1. read the Job no. from the subject ("... National Skirting order - 187629")
  2. find OUR order on Monday by that Job no. (Orders board, "Job no." column text__1)
  3. fulfil the Shopify order with courier "Other" + the tracking LINK as the tracking number/url,
     notifying the customer
  4. post the link to the Monday order's updates
  5. when the tracking link shows a delivery date (later emails in the series), set the Customer ETA
A series of emails arrives per order; the first has no date, later ones do — so fulfilment happens
once (idempotent) and the ETA is filled in when a date becomes available.

This module ONLY parses/plans. The caller (api/main.py) does the Monday/Shopify/Outlook I/O.
"""
import re

STREAM_SENDER = "noreply@go2stream.net"
ORDERS_BOARD_ID = 1786542990
JOB_NO_COL = "text__1"           # Monday Orders board "Job no." (holds National Skirting's order no.)
ORDER_NO_COL = "text_mkv6z0nt"   # "Order no."
ORDER_ID_COL = "text_mm04tmac"   # "Order ID" (Shopify numeric order id)
CUSTOMER_COL = "text2"           # "Customer Name"
SUPPLIER_COL = "dropdown_mkyqdeqd"
CUSTOMER_ETA_COL = "date"        # "Customer ETA" (date)

_JOB_RE = re.compile(r"national\s+skirting\s+order\s*(?:[-#:]\s*)?(\d{3,})", re.I)
_TRACK_RE = re.compile(r"https?://[^\s\"'<>]*go2stream\.net/[^\s\"'<>]*Tracking\.php\?idno=[^\s\"'<>]+", re.I)
_HELLO_RE = re.compile(r"\bHello\s+([^,\r\n]{1,80}?)\s*,", re.I)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
# "Wednesday 11th November 2026", "11th Nov 2026", "11 November 2026"
_DATE_WORD_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(20\d\d)\b")
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_DATE_ISO_RE = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
# a labelled delivery date gets priority over any stray date in the text
_DELIVERY_CUE_RE = re.compile(r"(?i)(?:estimated\s+delivery(?:\s+(?:date|slot))?|delivery\s+date|"
                              r"delivery\s+slot|out\s+for\s+delivery|delivering\s+on)\b")


def is_national_skirting_stream(frm: str, subject: str) -> bool:
    """A National Skirting tracking email from Stream (NOT the MB Distribution ones from the same
    sender, which have a different format and supplier)."""
    f = (frm or "").lower().strip()
    s = (subject or "").lower()
    return (STREAM_SENDER in f) and ("national skirting" in s)


def parse_job_no(subject: str):
    m = _JOB_RE.search(subject or "")
    return m.group(1) if m else None


def parse_tracking_url(body: str):
    m = _TRACK_RE.search(body or "")
    return m.group(0).rstrip(".,) ") if m else None


def parse_customer(body: str):
    m = _HELLO_RE.search(body or "")
    return m.group(1).strip() if m else None


def _norm_month(w):
    w = (w or "").lower()[:3]
    return _MONTHS.get(w)


def parse_delivery_date(text: str):
    """Best-effort ISO (YYYY-MM-DD) delivery date from an email body — None when there's no date
    (the first email of every series). Prefers a date that sits just after a delivery cue so a stray
    'order received 11th Nov' line can't be mistaken for the delivery date."""
    if not text:
        return None
    cue = _DELIVERY_CUE_RE.search(text)
    windows = ([text[cue.end(): cue.end() + 60]] if cue else []) + [text]
    for seg in windows:
        m = _DATE_WORD_RE.search(seg)
        if m:
            mon = _norm_month(m.group(2))
            if mon:
                return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(1)):02d}"
        m = _DATE_ISO_RE.search(seg)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m = _DATE_NUM_RE.search(seg)
        if m:                                    # UK format dd/mm/yyyy
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def parse_stream_email(subject: str, body: str) -> dict:
    """Parse ONE Stream email → {job_no, tracking_url, customer, body_date}. Any field may be None."""
    return {"job_no": parse_job_no(subject),
            "tracking_url": parse_tracking_url(body),
            "customer": parse_customer(body),
            "body_date": parse_delivery_date(body)}


def build_plan(parsed: dict, order: dict | None, already_fulfilled: bool) -> dict:
    """Decide what SHOULD happen for one email, given the parsed email, the matched Monday order (or
    None), and whether the Shopify order is already fulfilled. Pure — no writes.

    Returns {status, job_no, tracking_url, customer, order_no, shopify_id, item_id, do:{...}, note}.
    `do` is the directive the live run obeys:
      fulfil   — fulfil Shopify with the tracking link (courier Other) + notify, only if not already
      update   — post the tracking link to the Monday order's updates
      set_eta  — an ISO date to write to Customer ETA, or None (no date yet)
    """
    job = parsed.get("job_no")
    url = parsed.get("tracking_url")
    out = {"job_no": job, "tracking_url": url, "customer": parsed.get("customer"),
           "order_no": None, "shopify_id": None, "item_id": None,
           "do": {"fulfil": False, "update": False, "set_eta": None}, "note": ""}
    if not job:
        out["status"] = "skip"
        out["note"] = "no National Skirting job number in the subject"
        return out
    if not url:
        out["status"] = "skip"
        out["note"] = "no go2stream tracking link in the email"
        return out
    if not order:
        out["status"] = "no_match"
        out["note"] = f"no Monday order with Job no. {job}"
        return out
    out["order_no"] = order.get("order_no")
    out["shopify_id"] = order.get("shopify_id")
    out["item_id"] = order.get("item_id")
    out["customer"] = out["customer"] or order.get("customer")
    # ETA: a date found in THIS email body; the live run may also read the tracking page.
    eta = parsed.get("body_date")
    already_eta = bool((order.get("customer_eta") or "").strip())
    out["do"]["set_eta"] = eta if (eta and not already_eta) else None
    out["do"]["update"] = True                     # always (idempotent-ish) surface the link on Monday
    out["do"]["fulfil"] = not already_fulfilled
    if already_fulfilled and not out["do"]["set_eta"]:
        out["status"] = "done"
        out["note"] = "already fulfilled; no new ETA"
    elif already_fulfilled:
        out["status"] = "eta"
        out["note"] = f"already fulfilled; set Customer ETA {out['do']['set_eta']}"
    else:
        out["status"] = "fulfil"
        out["note"] = ("fulfil + tracking + notify"
                       + (f"; set ETA {out['do']['set_eta']}" if out["do"]["set_eta"] else ""))
    return out
