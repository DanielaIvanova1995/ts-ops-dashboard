"""Order documents (Phase 3) — branded Purchase Order / Packing Slip PDFs.

A Python (fpdf2) port of the old build_batch.js template, matching the TradeHub branding, with the
SUPPLIER block removed (FROM | DELIVER TO only, per Daniela) and the MANDATORY validation gate:
if any required field is blank the build refuses to produce a file and reports exactly what's
missing — a blank field must never reach a PDF a supplier opens.

PO = full priced document (email-order suppliers). Packing slip = no prices (portal, in-house,
samples, clearance, supplier-unidentified).
"""
import json
import os

ORANGE = (242, 106, 33)
INK = (29, 29, 29)
GREY = (89, 89, 89)
PALE = (245, 245, 245)
LIGHT = (255, 241, 230)
WHITE = (255, 255, 255)

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(_HERE, "order_processing", "tso-logo.png")
_RULEBOOK = os.path.join(_HERE, "order_processing", "supplier_rulebook.json")

TSO_FROM = ["Trade Superstore Online (TSO UK Ltd)", "Unit 8, Tomlinson Industrial Estate",
            "Alfreton Road, Derby, DE21 4ED", "T: 0333 090 9217",
            "hello@tradesuperstoreonline.co.uk"]
TSO_DELIVER = ["DELIVER TO TSO", "Trade Superstore Online", "Unit 8, Tomlinson Industrial Estate",
               "Alfreton Road, Derby DE21 4ED", "0333 090 9217"]

TERMS = [
    "1. NO SUBSTITUTIONS — do not substitute any product without our prior written agreement.",
    "2. THE DELIVERY ADDRESS IS OUR CUSTOMER — you are supplying Trade Superstore Online, not the "
    "end user. Do not contact them for any reason except to arrange the delivery itself.",
    "3. NEVER discuss with the end customer: our trade account, prices, replacements, shortages, "
    "stock issues or anything else. Raise these with US FIRST (0333 090 9217 / "
    "hello@tradesuperstoreonline.co.uk) — never with the end customer.",
    "4. REPLACEMENT deliveries: collect the original/faulty goods at the same time. If the "
    "collection cannot be made, do not drop off the replacement.",
    "5. Do not leave pallets with the customer.",
    "6. NO PRICING PAPERWORK with the goods — no invoices, price lists or priced delivery notes. "
    "Paperwork with the goods should quote our TSO order number only.",
    "7. Delivery problems (no answer, refused, access issues): contact us BEFORE rebooking or "
    "returning the goods — do not negotiate with the customer.",
    "8. Any change to the delivery date must be advised to us so we can inform the customer.",
]


def _accounts():
    """Map normalised supplier label → our account number, from the rulebook."""
    import re
    out = {}
    try:
        data = json.load(open(_RULEBOOK, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    for s in data.get("suppliers", []):
        acct = (s.get("account") or "").strip()
        if not acct:
            continue
        first = re.sub(r"[^a-z0-9]", "", (s.get("name") or "").split("(")[0].split()[0].lower())
        if first:
            out[first] = acct
    return out


_ACCTS = None


def account_for(supplier):
    import re
    global _ACCTS
    if _ACCTS is None:
        _ACCTS = _accounts()
    key = re.sub(r"[^a-z0-9]", "", (supplier or "").split()[0].lower()) if supplier else ""
    return _ACCTS.get(key, "On account")


# --------------------------------------------------------------------------- validation gate
def _blank(v):
    return v is None or str(v).strip() == ""


def validate_doc(d, kind):
    """Return a list of missing-field errors; empty list = OK. Never write a file if non-empty."""
    errs = []
    label = d.get("order") or d.get("po") or "(unknown order)"
    if _blank(d.get("order")) and _blank(d.get("po")):
        errs.append(f"[{label}] missing order / PO number")
    if not (kind == "slip" and d.get("tso")):
        dl = d.get("dl")
        if not isinstance(dl, list) or not dl or any(_blank(x) for x in dl):
            errs.append(f"[{label}] delivery address is missing, empty or has a blank line")
    lines = d.get("lines")
    if not isinstance(lines, list) or not lines:
        errs.append(f"[{label}] has NO order lines — every document must have at least one")
        return errs
    for i, l in enumerate(lines):
        if kind == "po":
            sku, desc, qty, cost, total = (list(l) + ["", "", "", "", ""])[:5]
            if _blank(desc):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Description")
            if _blank(qty):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Qty")
            if _blank(cost):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Unit cost — use 'confirm'")
            if _blank(total):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Line total — use 'confirm'")
        else:
            sku, desc, qty = (list(l) + ["", "", ""])[:3]
            if _blank(desc):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Description")
            if _blank(qty):
                errs.append(f"[{label}] line {i + 1} (SKU {sku}) missing Qty")
    if kind == "po":
        sums = d.get("sums")
        if not isinstance(sums, list) or not sums:
            errs.append(f"[{label}] has no sums block (Goods/Delivery/VAT/Total)")
        else:
            for s in sums:
                if _blank(s[0]) or _blank(s[1]):
                    errs.append(f"[{label}] a sums row is incomplete: {s}")
    return errs


# --------------------------------------------------------------------------- rendering
_PUNC = {"—": "-", "–": "-", "’": "'", "‘": "'", "“": '"',
         "”": '"', "•": "-", "·": "-", "…": "...", "™": "(TM)"}


def _S(x):
    """Make any text safe for the core (latin-1) PDF font — POs/slips must never crash on an
    em-dash or an accented customer name from Shopify."""
    s = "" if x is None else str(x)
    for k, v in _PUNC.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _block(pdf, title, lines, x, w, fill=None):
    pdf.set_xy(x, pdf.get_y())
    if fill:
        pdf.set_fill_color(*fill)
    pdf.set_text_color(*ORANGE)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_x(x)
    pdf.cell(w, 5, title, ln=2, fill=bool(fill))
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for ln in lines:
        pdf.set_x(x)
        pdf.cell(w, 4.6, _S(ln), ln=2, fill=bool(fill))


def _header(pdf, title, ref):
    if os.path.exists(LOGO):
        try:
            pdf.image(LOGO, x=12, y=11, w=52)
        except Exception:  # noqa: BLE001
            pass
    pdf.set_xy(120, 12)
    pdf.set_text_color(*ORANGE)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(78, 10, title, align="R", ln=2)
    pdf.set_x(120)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(78, 6, ("Ref: " if title == "PACKING SLIP" else "PO No: ") + _S(ref), align="R", ln=2)
    pdf.set_x(120)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GREY)
    pdf.cell(78, 5, "Date: " + _S(pdf._tso_date), align="R", ln=2)
    pdf.set_text_color(*INK)
    pdf.set_y(34)


def _from_del(pdf, dl):
    y0 = pdf.get_y()
    _block(pdf, "FROM", TSO_FROM, 12, 93, fill=PALE)
    y1 = pdf.get_y()
    pdf.set_y(y0)
    _block(pdf, "DELIVER TO", dl, 108, 90)
    pdf.set_y(max(y1, pdf.get_y()) + 4)


def _meta(pdf, acct, order, req, contact):
    heads = ["Our account no", "TSO order no", "Requested delivery", "Contact for delivery"]
    vals = [acct, order, req, contact]
    w = 186 / 4
    pdf.set_x(12)
    pdf.set_fill_color(*INK)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for h in heads:
        pdf.cell(w, 6, h, border=0, fill=True, align="C")
    pdf.ln()
    pdf.set_x(12)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for v in vals:
        pdf.cell(w, 6, _S(v), border="LR", align="C")
    pdf.ln()
    pdf.set_x(12)
    pdf.cell(186, 0, "", border="T", ln=1)
    pdf.ln(3)


def _po_table(pdf, lines):
    cols = [(30, "SKU", "L"), (78, "Description", "L"), (16, "Qty", "C"),
            (30, "Unit cost (ex VAT)", "R"), (32, "Line total", "R")]
    pdf.set_x(12)
    pdf.set_fill_color(*ORANGE)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for w, h, a in cols:
        pdf.cell(w, 7, h, fill=True, align=a)
    pdf.ln()
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for i, l in enumerate(lines):
        vals = (list(l) + ["", "", "", "", ""])[:5]
        pdf.set_x(12)
        pdf.set_fill_color(*(PALE if i % 2 else WHITE))
        for (w, h, a), v in zip(cols, vals):
            pdf.cell(w, 6.5, ("  " + _S(v)) if a == "L" else (_S(v) + "  "), border="LR",
                     align=a, fill=True)
        pdf.ln()
    pdf.set_x(12)
    pdf.cell(186, 0, "", border="T", ln=1)
    pdf.ln(2)


def _sums(pdf, sums):
    for lab, val, bold in [(s[0], s[1], (len(s) > 2 and s[2])) for s in sums]:
        pdf.set_x(12 + 124)
        if bold:
            pdf.set_fill_color(*LIGHT)
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        pdf.cell(30, 6, _S(lab), align="R", fill=bool(bold))
        pdf.cell(32, 6, _S(val), align="R", fill=bool(bold), ln=1)
    pdf.ln(2)


def _slip_table(pdf, lines):
    cols = [(40, "SKU", "L"), (116, "Description", "L"), (30, "Qty", "C")]
    pdf.set_x(12)
    pdf.set_fill_color(*ORANGE)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for w, h, a in cols:
        pdf.cell(w, 7, h, fill=True, align=a)
    pdf.ln()
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for i, l in enumerate(lines):
        vals = (list(l) + ["", "", ""])[:3]
        pdf.set_x(12)
        pdf.set_fill_color(*(PALE if i % 2 else WHITE))
        for (w, h, a), v in zip(cols, vals):
            pdf.cell(w, 6.5, ("  " + _S(v)) if a == "L" else _S(v), border="LR", align=a, fill=True)
        pdf.ln()
    pdf.set_x(12)
    pdf.cell(186, 0, "", border="T", ln=1)
    pdf.ln(2)


def _notes(pdf, notes):
    pdf.set_x(12)
    pdf.set_fill_color(*INK)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(186, 6, "DELIVERY NOTES", fill=True, ln=1)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for n in notes:
        pdf.set_x(12)
        pdf.multi_cell(186, 4.8, _S(n), border="LR")
    pdf.set_x(12)
    pdf.cell(186, 0, "", border="T", ln=1)
    pdf.ln(3)


def _terms(pdf):
    pdf.set_x(12)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*INK)
    pdf.cell(186, 6, _S("SUPPLIER TERMS - APPLY TO EVERY ORDER"), ln=1)
    pdf.set_font("Helvetica", "", 7.5)
    for t in TERMS:
        pdf.set_x(12)
        pdf.multi_cell(186, 4, _S(t))
    pdf.ln(1)
    pdf.set_x(12)
    pdf.set_text_color(*GREY)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.multi_cell(186, 4, _S("Invoices to: accounts@tradesuperstoreonline.co.uk  -  Order "
                              "queries: hello@tradesuperstoreonline.co.uk  -  0333 090 9217"))


def _new_pdf(date_str):
    from fpdf import FPDF
    pdf = FPDF("P", "mm", "A4")
    pdf._tso_date = date_str
    pdf.set_auto_page_break(True, 14)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    return pdf


def build_po_pdf(d, date_str=""):
    """Branded Purchase Order PDF as bytes. Raises ValueError (with every missing field) if the
    validation gate fails — no file is produced."""
    errs = validate_doc(d, "po")
    if errs:
        raise ValueError("PO validation failed — nothing generated:\n- " + "\n- ".join(errs))
    pdf = _new_pdf(date_str)
    _header(pdf, "PURCHASE ORDER", d.get("po"))
    _from_del(pdf, d["dl"])
    _meta(pdf, d.get("acct") or account_for(d.get("supplier")), d.get("order"),
          d.get("req") or "Standard", d.get("contact") or "TSO - 0333 090 9217")
    _po_table(pdf, d["lines"])
    _sums(pdf, d["sums"])
    _notes(pdf, d.get("notes") or [])
    _terms(pdf)
    return bytes(pdf.output())


def build_slip_pdf(d, date_str=""):
    """Branded Packing Slip PDF (no prices) as bytes. Raises ValueError if the gate fails."""
    errs = validate_doc(d, "slip")
    if errs:
        raise ValueError("Packing slip validation failed — nothing generated:\n- "
                         + "\n- ".join(errs))
    pdf = _new_pdf(date_str)
    _header(pdf, "PACKING SLIP", d.get("po") or d.get("order"))
    _from_del(pdf, TSO_DELIVER if d.get("tso") else d["dl"])
    _meta(pdf, d.get("acct") or "On account", d.get("order"),
          d.get("req") or "Standard", d.get("contact") or "TSO - 0333 090 9217")
    _slip_table(pdf, d["lines"])
    _notes(pdf, d.get("notes") or [])
    _terms(pdf)
    return bytes(pdf.output())
