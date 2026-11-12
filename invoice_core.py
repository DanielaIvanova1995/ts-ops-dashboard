"""
Headless invoice-check engine — the SAME 3-way match, supplier rules, matching and
push-decision logic the Trade Hub app uses, but with NO Streamlit / no I/O so it can run
in the scheduled cloud runner (run_invoice_check.py) as well as the app.

Pure by design: the caller fetches the order lines, shipping and pricing lookup and passes
them in. Kept deliberately in step with app.py — if you change a rule in one, change it in
the other (a later refactor will make app.py import from here so there's a single copy).
"""
import re
import os
import json

import delivery_rules as _dr   # the single source for carriage (Carron/Ctie/LPD/… live here)

# ---- Monday Payment Status labels -----------------------------------------------------
MATCHED_LABEL = "Matched (TradeHub)"
APPROVED_QB_LABEL = "Approved (To QB)"
CN_APPROVED_QB_LABEL = "CN Approved (To QB)"
DISCREPANCY_LABEL = "Discrepancy"
MARGIN_PUSH_MIN = 10.0          # default lowest margin to auto-approve (Decor8 -> 5% below)
MARGIN_PUSH_MAX = 35.0

# ---- Supplier delivery / carriage (ex-VAT £) ------------------------------------------
DELIVERY_CHARGES = {
    "molan": {"name": "Molan", "flat": 23.74},
    "pjh": {"name": "PJH", "flat": 37.50, "free_over": 1000.0},
    "travisperkins": {"name": "Travis Perkins", "flat": 25.0, "free_over": 100.0},
    "nbp": {"name": "NBP", "flat": 17.0, "free_over": 250.0},
    "upb": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
    "up": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
    "eurocell": {"name": "Eurocell", "flat": 12.50, "free_over": 100.0},
    "gap": {"name": "GAP", "flat": 20.83, "free_over": 150.0},
    "deanta": {"name": "Deanta", "flat": 8.0},
    "decor8": {"name": "Decor8", "flat": 5.99, "free_over": 50.0},
    "chasehardware": {"name": "Chase Hardware", "flat": 14.0},   # accept up to £14 carriage (undefined
    #   when they charge it); the default 10% push floor still holds a thin-margin order for review.
    "velux": {"name": "Velux", "flat": 50.0},   # always £50 + VAT carriage (Daniela 2026-10-05)
    "edmundson": {"name": "Edmundson", "flat": 10.0},   # £10 + VAT per delivery, to us AND to customer (Daniela 2026-11-10)
    "storm": {"name": "Storm", "flat": 21.0},           # £21 + VAT per delivery (Daniela 2026-11-10)
}
DECOR8_DISCOUNT = 0.12
DECOR8_MIN_DISCOUNT = 0.10
SUPPLIER_SURCHARGE = {"eurocell": 0.05}
# "Agreed PO total" fast-path: when the order's £-to-supplier (our PO total, ex-VAT incl. carriage) is
# filled in and a SINGLE invoice's ex-VAT total matches it within a few pence, the price is confirmed by
# the agreed figure, so approve regardless of margin (Daniela 2026-11-12). Part-invoices (total < agreed)
# and orders with no £-to-supplier fall through to the normal full line check / supplier rules.
AGREED_TOTAL_TOL = 0.05

# Carron carriage data + logic now live ONCE in delivery_rules (so quotes, POs and the checker can
# never drift); these names are re-exported for the many call sites that import them from invoice_core.
CARRON_FREE_OVER = _dr.CARRON_FREE_OVER
CARRON_ZONES = _dr.CARRON_ZONES
CARRON_AREA_ZONE = _dr.CARRON_AREA_ZONE

SUPPLIER_RULES = {
    "travisperkins": {"name": "Travis Perkins", "no_pricelist": True,
                      "push_min": 8.0, "flag_high": False, "flag_below": True},
    "decor8": {"name": "Decor8", "push_min": 5.0, "push_max": 55.0, "flag_below": True},
    # Rexel: no pricelist held yet, order margin is the safeguard. Approve at 10%+ with NO upper cap
    # (Daniela — approve even over 35%); below 10% → Needs Review.
    "rexel": {"name": "Rexel", "no_pricelist": True, "push_min": 10.0,
              "flag_high": False, "flag_below": True},
    # PJH: approve every matched invoice regardless of how high the margin is (no 35% cap).
    "pjh": {"name": "PJH", "flag_high": False},
    # Huws Gray: no pricelist held (quote-first), so the ORDER margin is the safeguard. Auto-approve a
    # matched invoice when margin is 8%–55%; outside that → Needs Review (Daniela 2026-10-13).
    "huwsgray": {"name": "Huws Gray", "no_pricelist": True, "push_min": 8.0, "push_max": 55.0,
                 "flag_below": True, "flag_high": True, "delivery_any": True},
    "huws": {"name": "Huws Gray", "no_pricelist": True, "push_min": 8.0, "push_max": 55.0,
             "flag_below": True, "flag_high": True, "delivery_any": True},
    # MB Decor: pricelist loaded 2026-10-16 (price_overrides.json "MB Decor", by Item Code QMB..).
    # Lines are price-checked against it; auto-approve matched at 10%+ with NO upper cap; below 10% →
    # Needs Review. pdf_optional = still approvable with no PDF (order margin is the safeguard).
    "mbdecor": {"name": "MB Decor", "pdf_optional": True, "push_min": 10.0,
                "flag_high": False, "flag_below": True, "delivery_any": True},
    "mbdecorltd": {"name": "MB Decor", "pdf_optional": True, "push_min": 10.0,
                   "flag_high": False, "flag_below": True, "delivery_any": True},
}
SUPPLIER_EMAILS = {
    "upb": "janetwitt@upbuildingproducts.com",
    "up": "janetwitt@upbuildingproducts.com",
    "upbuildingproducts": "janetwitt@upbuildingproducts.com",
    "pjh": "accounts@pjh.uk",
    "gap": "carrie.morris@gap.uk.com",
    "toolbank": "abasterfield@toolbank.com",            # Alison Basterfield
    "deanta": "salesledger@deanta.co.uk",               # all Deanta discrepancies (Daniela 2026-10-05)
}
SUPPLIER_CHARGES = {
    "gap": (
        {"keywords": ("redeliver", "re-deliver", "failed delivery"),
         "label": "redelivery (failed delivery)", "amount": 45.0},
        {"keywords": ("collection charge", "carriage collection", "returns collection",
                      "collection fee"),
         "label": "returns collection", "amount": 35.0},
        {"keywords": ("restock", "re-stock"), "label": "restocking (10%)"},
    ),
}
PRODUCT_EQUIV = [
    {"inv_sku": "PJ40WLO1", "order_sku": "GHSIO"},
    {"supplier": "upb", "inv_sku": "5300303", "order_name_has": ["fixing", "screws"]},
    # UPB 'VL7 HardiePlank Screw 4.2x40mm' (5300319) = our 'VL (Coloured) Fixing Screws' order line.
    {"supplier": "upb", "inv_sku": "5300319", "order_name_has": ["fixing", "screws"]},
    # Anthracite Grey HardiePlank Coloured Fixing Screws (UPB code 5300448) = our VL7 order line.
    {"supplier": "upb", "inv_sku": "5300448", "order_name_has": ["fixing", "screws"]},
    # Catch-all: UPB bills its HardiePlank coloured fixing screws under per-colour codes
    # (5300303/5300319/5300448/…), all our single 'VL… Coloured Fixing Screws' line — so match ANY
    # UPB invoice line described as 'fixing screws' to the order's fixing-screws line.
    {"supplier": "upb", "inv_name_has": ["fixing", "screws"], "order_name_has": ["fixing", "screws"]},
    # UPB bills the HardiePlank starter strip / starter profile under its own codes (e.g. 5300184,
    # described 'HardiePlank Starter Vent / 50mm Starter Profile') = our 'Starter Strip and Ventilation
    # Profile' order line (SKU JHPROFP…). The names share only 'starter' (7 chars) so the name-scorer
    # just misses it — pin it: any UPB line saying 'starter' → the order's 'starter' line.
    {"supplier": "upb", "inv_name_has": ["starter"], "order_name_has": ["starter"]},
    # Eurocell bills the Walnut Eco Fencing Panel as ECOFPANWALS; our Shopify SKU is ECOFPAN6WAL
    # (extra '6', no trailing 'S') — so the exact-SKU match misses it (invoice 337874008 / order
    # 30781). Pin the equivalence. (If other colours show the same ECOFPAN<colour>S ↔ ECOFPAN6<colour>
    # pattern, add them here too.)
    {"supplier": "eurocell", "inv_sku": "ECOFPANWALS", "order_sku": "ECOFPAN6WAL"},
]

_TOK_ABBREV = {
    "ext": "external", "int": "internal",
    "hplank": "hardie plank", "hplk": "hardie plank", "hardieplank": "hardie plank",
    "hardieseal": "hardie seal",
    "galvan": "galvanised", "galv": "galvanised",
    "conn": "connector", "vert": "vertical", "horiz": "horizontal",
    "vent": "ventilation", "qty": "", "pk": "pack",
}
_TOK_STOP = {"and", "the", "for", "with", "mm", "cm", "to", "of", "in", "on", "at", "by", "or"}


# ---- small pure helpers ---------------------------------------------------------------
def norm_code(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def canon_supplier(s):
    """Normalised supplier key, canonicalised via the routing map so the FEED's name and our
    invoice/order label resolve to the SAME key (the feed calls it 'LPD', we call it 'LPD DOORS' —
    both must key to the same cost, else RFLB36 reads as 'no pricelist cost')."""
    n = norm_code(s)
    try:
        import order_routing as _rt
        lbl = _rt.CANON.get(n)
        return norm_code(lbl) if lbl else n
    except Exception:  # noqa: BLE001
        return n


def title_tokens(s):
    s = (s or "").lower()
    s = re.sub(r"(?<=\d)(?=[a-z])", " ", s)
    s = re.sub(r"(?<=[a-z])(?=\d)", " ", s)
    out = set()
    for w in re.findall(r"[a-z0-9]+", s):
        for part in _TOK_ABBREV.get(w, w).split():
            if part in _TOK_STOP or (len(part) < 2 and not part.isdigit()):
                continue
            # Normalise simple plurals (buttons→button) so singular/plural wording lines up;
            # 5+ char alphabetic words only, never a '…ss' word (keeps 'glass'/'class').
            if part.isalpha() and len(part) >= 5 and part.endswith("s") and part[-2] != "s":
                part = part[:-1]
            out.add(part)
    return out


def parse_order_items(text):
    """Monday order-items text → {key: {sku, qty, name}} (fallback when Shopify unreadable)."""
    out = {}
    for i, line in enumerate((text or "").split("\n")):
        skum = re.search(r"SKU:\s*([^\s|]+)", line)
        qtym = re.search(r"Quantity:\s*(\d+)", line)
        if not skum and not qtym:
            continue
        name = re.split(r"\|?\s*(?:Quantity:|SKU:)", line)[0].strip(" |-\t")
        if not skum and not name:
            continue
        key = norm_code(skum.group(1)) if skum else f"line{i}:{norm_code(name)}"
        out[key] = {"sku": skum.group(1) if skum else (name or "(no SKU)"),
                    "qty": int(qtym.group(1)) if qtym else None, "name": name}
    return out


def order_candidates(shopify_lines, order_items_text=None):
    """Order lines to check against: prefer the LIVE Shopify order lines (already fetched
    and passed in), fall back to Monday's order_items text. Same keying as the app,
    including '#n' suffixes for variants that share a SKU."""
    if shopify_lines:
        out = {}
        for i, l in enumerate(shopify_lines):
            sku = l.get("sku")
            key = norm_code(sku) if sku else f"shop{i}:{norm_code(l.get('title'))}"
            if key in out:
                key = f"{key}#{i}"
            out[key] = {"sku": sku or (l.get("title") or "(no SKU)"),
                        "qty": l.get("qty"), "name": l.get("title"), "price": l.get("price"),
                        "tags": l.get("tags") or [], "weight": l.get("weight")}
        if out:
            return out
    return parse_order_items(order_items_text)


def code_match(sk, order, used):
    if not (sk and sk.isdigit() and len(sk) >= 6):
        return None
    for k in order:
        if k not in used and sk in k:
            return k
    return None


def sku_keys(sk, order):
    if not sk:
        return []
    pre = sk + "#"
    return [k for k in order if k == sk or k.startswith(pre)]


_PERSQM_RE = re.compile(r"(GSQ|NET)$", re.I)
_SHEET_SIZE_RE = re.compile(r"(\d{3,4})\s*[x×*]\s*(\d{3,4})")


def is_persqm_poly(sku):
    """Molan polycarbonate codes billed by the m² (GSQ/NET/QNET…) — the invoice qty is the AREA, not
    a sheet count, so it can't be compared to the order's sheet quantity directly."""
    s = (sku or "").upper()
    return bool(_PERSQM_RE.search(s)) or s.startswith("QNET")


def sheet_sqm(name):
    """m² of ONE sheet from a 'WIDTH x HEIGHT' (mm) in the product name, e.g. '2000 x 700mm' → 1.4."""
    m = _SHEET_SIZE_RE.search(name or "")
    return round(int(m.group(1)) * int(m.group(2)) / 1_000_000, 4) if m else None


def cost_by_prefix(sk, supplier, pidx):
    """Cost for a TRUNCATED invoice SKU that's a prefix of exactly one pricelist key carrying this
    supplier's price (e.g. invoice 'ZZZ040-CSA3118' → pricelist 'ZZZ040-CSA3118C' at £15.21). Needs
    the prefix to be long (≥8) and UNAMBIGUOUS (one match). None otherwise. Only this supplier's own
    price — never another's."""
    if not sk or len(sk) < 8:
        return None
    hits = [k for k in pidx if k != sk and k.startswith(sk)
            and isinstance(pidx[k].get(supplier), (int, float))]
    return pidx[hits[0]].get(supplier) if len(hits) == 1 else None


def prefix_match(sk, order, used):
    """When a supplier TRUNCATES the SKU on the invoice so it's a prefix of our full order SKU
    (e.g. Molan poly 'ZZZ047-SUNTUFI' on the invoice → 'ZZZ047-SUNTUFIRNBHCLR35' on the order),
    match it — but only when the prefix is long (≥8 chars, so it's specific) and UNAMBIGUOUS
    (exactly one order SKU starts with it). Returns that order key or None."""
    if not sk or len(sk) < 8:
        return None
    cands = [k for k in order if k not in used and k != sk
             and (k.startswith(sk) or k.split("#", 1)[0].startswith(sk))]
    return cands[0] if len(cands) == 1 else None


def equiv_match(supplier, sk, desc, order, hit):
    dl = (desc or "").lower()
    for r in PRODUCT_EQUIV:
        if r.get("supplier") and r["supplier"] != supplier:
            continue
        if not (r.get("inv_sku") or r.get("inv_name_has")):
            continue
        if r.get("inv_sku") and norm_code(r["inv_sku"]) != sk:
            continue
        if r.get("inv_name_has") and not all(w.lower() in dl for w in r["inv_name_has"]):
            continue
        if r.get("order_sku"):
            for k in sku_keys(norm_code(r["order_sku"]), order):
                if k not in hit:
                    return k
        for frags in ([r["order_name_has"]] if r.get("order_name_has") else []):
            for k, v in order.items():
                if k in hit:
                    continue
                if all(w.lower() in (v.get("name") or "").lower() for w in frags):
                    return k
    return None


def order_common_tokens(order):
    from collections import Counter
    if len(order) < 2:
        return set()
    c = Counter()
    for v in order.values():
        c.update(title_tokens(v.get("name")))
    thresh = max(2, (len(order) + 1) // 2)
    return {t for t, cnt in c.items() if cnt >= thresh}


def names_ok(desc, order_name, common):
    shared = title_tokens(desc) & title_tokens(order_name)
    return bool(shared - common)


def name_pair_score(dt, ot, common):
    if not dt or not ot:
        return 0.0
    shared = dt & ot
    if not shared:
        return 0.0
    distinctive = shared - common
    overlap = len(shared) / max(len(dt), len(ot))
    if overlap < 0.8:
        if len(distinctive) < 2 and not (len(distinctive) == 1
                                         and len(next(iter(distinctive))) >= 8):
            return 0.0
        if len(shared) / min(len(dt), len(ot)) < 0.4:
            return 0.0
    return float(sum(len(t) for t in distinctive)) + 12.0 * overlap


# Suppliers that re-code / re-name products, where a final product-TYPE leftover match is appropriate.
_TYPE_MATCH_SUPPLIERS = ("squaredeal", "eurocell", "gap", "jbkind", "molan")


def product_type(s):
    """Coarse product family for a cladding line, from its description/name. Lets us pair an invoice
    line to its order line by TYPE when the colour words are shared across several same-colour order
    lines (board + corner), which the distinctive-word scorer wipes out. Order matters — the first
    keyword hit wins (a 'Hardie Plank External Corner' is a corner, not a board)."""
    t = (s or "").lower()
    if "corner" in t:
        return "corner"
    if any(w in t for w in ("starter", "vent", "profile", "trim", "reveal", "window head")):
        return "trim"
    if any(w in t for w in ("screw", "fixing", "nail")):
        return "fixing"
    if "tape" in t:
        return "tape"
    if any(w in t for w in ("paint", "touch up", "touch-up", "edge coat", "seal edge", "silicone", "sealant")):
        return "paint"
    if "guillotine" in t or "roughneck" in t:
        return "guillotine"
    if "gauge" in t or "gecko" in t:
        return "gauge"
    if any(w in t for w in ("blade", "saw", "jigsaw")):
        return "blade"
    if "backer" in t:
        return "backer"
    if "panel" in t:
        return "panel"
    if any(w in t for w in ("cill", "sill")):
        return "cill"
    if any(w in t for w in ("felt", "membrane", "breathable")):
        return "membrane"
    if any(w in t for w in ("block", "batten")):
        return "batten"
    if any(w in t for w in ("plank", "cladding", "board", "weatherboard")):
        return "board"
    return "other"


def is_code(tok):
    has_d = any(c.isdigit() for c in tok)
    has_a = any(c.isalpha() for c in tok)
    return (len(tok) >= 3 and has_d and has_a) or (len(tok) >= 5 and tok.isdigit())


def supplier_title_cost(desc, supplier, tidx):
    cands = tidx.get(supplier)
    if not cands:
        return None, None
    dt = title_tokens(desc)
    if not dt:
        return None, None
    best, best_score, best_title = None, 0.0, None
    for toks, title, cost in cands:
        shared = dt & toks
        n = len(shared)
        if n == 0:
            continue
        mn = min(len(dt), len(toks))
        if n < 2 and not (mn == 1 and len(next(iter(shared))) >= 8):
            continue
        ratio = n / mn
        if ratio >= 0.5 and (n + ratio) > best_score:
            best, best_score, best_title = cost, n + ratio, title
    return best, best_title


def supplier_code_cost(sku_raw, desc, supplier, cidx):
    codes = cidx.get(supplier)
    if not codes:
        return None, None
    toks = {t for t in re.findall(r"[a-z0-9]+", f"{sku_raw} {desc}".lower()) if is_code(t)}
    for t in toks:
        if t in codes:
            return codes[t], t.upper()
    return None, None


# ---- index builders (from the pricing_lookup.json the app/runner load) ----------------
def _price_overrides():
    """Durable per-supplier SKU cost overrides from price_overrides.json (kept in the repo so a
    feed rebuild can't wipe them), PLUS the bulk Molan polycarbonate pricelist in molan_poly.json
    (3,080 per-size variants, kept in its own file so price_overrides.json stays small). A hand-set
    price in price_overrides.json always wins over the bulk file. {} if unreadable."""
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, "price_overrides.json"), encoding="utf-8") as f:
            ov = json.load(f) or {}
    except Exception:  # noqa: BLE001
        ov = {}
    try:
        with open(os.path.join(base, "molan_poly.json"), encoding="utf-8") as f:
            poly = json.load(f) or {}
        for sup, skus in poly.items():
            if isinstance(skus, dict) and isinstance(ov.setdefault(sup, {}), dict):
                for k, v in skus.items():
                    ov[sup].setdefault(k, v)        # price_overrides.json wins on a clash
    except Exception:  # noqa: BLE001
        pass
    return ov


def order_sku_cost(order_sku, supplier, pidx):
    """THIS supplier's own cost for one of OUR order-line SKUs. For re-coded suppliers (Squaredeal,
    GAP, Eurocell…) the invoice prints the supplier's OWN product code, so pricing by the invoice SKU
    fails — but the line gets matched to an order line whose SKU does carry this supplier's cost.
    Checks the prebuilt index first, then the durable overrides directly, INCLUDING the _patterns (so
    an order SKU that isn't in the feed, e.g. a Smooth board or a colour corner, still resolves).
    NEVER returns another supplier's price — only `supplier`'s own. `supplier` is the normalised name."""
    nk = norm_code(order_sku)
    if not nk:
        return None
    supplier = canon_supplier(supplier)   # feed/override/invoice names all resolve to one key
    c = (pidx.get(nk) or {}).get(supplier)
    if isinstance(c, (int, float)):
        return c
    ov = _price_overrides()
    for sup, skus in ov.items():
        if sup.startswith("_") or not isinstance(skus, dict) or canon_supplier(sup) != supplier:
            continue
        for sk2, cost in skus.items():
            if isinstance(cost, (int, float)) and norm_code(sk2) == nk:
                return cost
    for sup, rules in (ov.get("_patterns") or {}).items():
        if canon_supplier(sup) != supplier:
            continue
        for r in (rules or []):
            cost = r.get("cost")
            pref = norm_code(r.get("prefix"))
            suf = norm_code(r.get("suffix") or "")
            ok_pref = (not pref) or nk.startswith(pref)
            ok_suf = (not suf) or nk.endswith(suf)
            if isinstance(cost, (int, float)) and (pref or suf) and ok_pref and ok_suf:
                return cost
    return None


def _persection_rates():
    """{supplier_norm: {leg_code_norm: {finish: £/section}}} from price_overrides.json '_persection'
    (Carron cast-iron radiators are priced PER SECTION, one Shopify SKU per range × 4–18 sections)."""
    ov = _price_overrides()
    return {norm_code(sup): {norm_code(k): fin for k, fin in (rules or {}).items() if isinstance(fin, dict)}
            for sup, rules in (ov.get("_persection") or {}).items()}


_SECTIONS_RE = re.compile(r"(\d{1,3})\s*sections?\b", re.I)
# Carron finish needles (as on the Shopify variant / invoice description) → the pricelist finish key.
# Order matters (first match wins). "gilded" → None on purpose (Carron's +£50 gilding note is
# ambiguous per-section vs per-radiator), so a gilded line stays unpriced rather than guessed.
_CARRON_FINISH = [("gilded", None), ("burnish", "SATIN-POLISHED"), ("satin", "SATIN-POLISHED"),
                  ("antiqu", "ANTIQUED"), ("highlight", "ANTIQUED"), ("baremetal", "ANTIQUED"),
                  ("powdercoat", "ANTIQUED"), ("copper", "VINTAGE-COPPER"),
                  ("metallic", "PAINTED"), ("paint", "PAINTED"), ("primer", "PRIMER")]


def persection_cost(sku, supplier, *texts):
    """Per-section cost = section count × the range's £/section for the chosen finish (Carron bespoke
    radiators). The count and finish are read from the texts (invoice description / Shopify variant),
    because every finish+size of a range shares ONE SKU. `sku` should be the LEG-coded SKU (our order
    SKU, e.g. 'LD013/LD014'). None if not per-section, or the leg/finish/count can't be read."""
    rates = _persection_rates().get(norm_code(supplier))
    if not rates:
        return None
    key = norm_code(sku)
    leg = next((b for b in sorted(rates, key=len, reverse=True) if b and key.startswith(b)), None)
    if not leg:
        return None
    blob = " ".join(str(t or "") for t in texts)
    m = _SECTIONS_RE.search(blob)
    if not m:
        return None
    n = int(m.group(1))
    fin = next((f for needle, f in _CARRON_FINISH if needle in norm_code(blob)), None)
    if not fin or not 1 <= n <= 40:
        return None
    rate = rates[leg].get(fin)
    return round(n * rate, 2) if isinstance(rate, (int, float)) else None


def pricelist_index(lookup):
    """{norm_sku: {norm_supplier: cost}} from the lookup offers PLUS the durable overrides in
    price_overrides.json. The overrides must be applied here too: the scheduled runner
    (run_invoice_check.py) builds its index from this function alone, so without them it would
    check invoices against a pricelist the Streamlit app doesn't agree with."""
    idx = {}
    for it in (lookup["items"] if lookup else []):
        sk = norm_code(it.get("sku"))
        if not sk:
            continue
        for o in (it.get("offers") or []):
            sup = canon_supplier(o.get("s"))
            if sup and o.get("c") is not None:
                idx.setdefault(sk, {})[sup] = o.get("c")
    ov = _price_overrides()
    for sup, skus in ov.items():
        if sup.startswith("_") or not isinstance(skus, dict):
            continue
        sn = canon_supplier(sup)
        for sk, cost in skus.items():
            if isinstance(cost, (int, float)):
                idx.setdefault(norm_code(sk), {})[sn] = cost
    # Same-supplier family patterns (e.g. UPB price one product TYPE, not per colour). Fills ONLY
    # that supplier's own cost — never borrows another supplier's price.
    pats = [(canon_supplier(sup), norm_code(r.get("prefix")), norm_code(r.get("suffix") or ""),
             r.get("cost"))
            for sup, rules in (ov.get("_patterns") or {}).items()
            for r in (rules or []) if isinstance(r.get("cost"), (int, float))]
    for sk, offers in idx.items():
        for sn, pref, suf, cost in pats:
            if pref and sk.startswith(pref) and (not suf or sk.endswith(suf)):
                offers.setdefault(sn, cost)
    return idx


def supplier_title_index(lookup):
    st_map = (lookup or {}).get("supplier_titles") or {}
    out = {}
    for sup, pairs in st_map.items():
        lst = []
        for t, c in pairs:
            toks = title_tokens(t)
            if toks and c is not None:
                lst.append((toks, t, c))
        if lst:
            out[norm_code(sup)] = lst
    return out


def supplier_code_index(pidx):
    out = {}
    for sku, supmap in pidx.items():
        if not is_code(sku):
            continue
        for sup, cost in supmap.items():
            if cost is not None:
                out.setdefault(sup, {})[sku] = cost
    return out


# ---- delivery / carron / charges ------------------------------------------------------
# Suppliers to skip in the invoice checker entirely (substrings of the normalised supplier
# name) — e.g. MB Decor, which is paid in advance. Remove to switch back on. Kept in step
# with app.py's EXCLUDED_SUPPLIER_KEYS.
EXCLUDED_SUPPLIER_KEYS = ()   # MB Decor brought back into the checker 2026-10-14 (auto-approve 10%+)


def is_excluded_supplier(supplier):
    s = norm_code(supplier)
    return any(x in s for x in EXCLUDED_SUPPLIER_KEYS)


def is_decor8(supplier):
    return (supplier or "").startswith("decor8") or (supplier or "").startswith("decor")


def is_carron(supplier):
    return (supplier or "").startswith("carron")


def is_ctie(supplier):
    return (supplier or "").startswith("ctie")


# C TIE + Carron carriage: delegate to delivery_rules (the single source). Thin wrappers keep the
# invoice_core import paths these call sites already use.
def ctie_expected(goods_value, ship):
    return _dr.ctie_expected(goods_value, ship)


def carron_zone(ship):
    return _dr.carron_zone(ship)


def carron_zone_label(ship):
    return _dr.carron_zone_label(ship)


def carron_expected(goods_value, ship):
    return _dr.carron_expected(goods_value, ship)


def _dolle_rates():
    """{norm_sku: delivery£} for Dolle from price_overrides.json '_delivery'.'dolle'."""
    ov = _price_overrides()
    raw = (ov.get("_delivery") or {})
    # key may be 'dolle'/'Dolle' — match case-insensitively
    for k, m in raw.items():
        if norm_code(k) == "dolle":
            return {norm_code(s): v for s, v in (m or {}).items()
                    if isinstance(v, (int, float))}
    return {}


def expected_delivery(supplier, goods_value, ship=None, order=None):
    if is_carron(supplier):
        return carron_expected(goods_value, ship)
    if is_ctie(supplier):
        return ctie_expected(goods_value, ship)
    # AJW / Dolle / GAP carriage now lives ONCE in delivery_rules (Daniela 2026-11-11: "fold
    # AJW/GAP/Dolle into delivery_rules too"), so quotes, POs and the invoice checker price them
    # identically. Build simple lines from the order dict (carry `sku` for Dolle's per-product band,
    # tags/weight for completeness). AJW = per-zone by postcode (free over the zone threshold); Dolle
    # = highest per-product band among ordered SKUs; GAP = free to Derby DE21 4ED, else £20.83 (<£150).
    sc0 = norm_code(supplier)
    if sc0 == "ajw" or sc0.startswith("dolle") or sc0 == "gap":
        try:
            import delivery_rules as dr
            lines = [{"description": v.get("name"),
                      "sku": (k.split("#")[0] if isinstance(k, str) else v.get("sku")),
                      "qty": v.get("qty"), "tags": v.get("tags") or [], "weight": v.get("weight")}
                     for k, v in (order or {}).items()]
            return dr.expected_delivery(supplier, goods_value, ship, lines)
        except Exception:  # noqa: BLE001
            return None
    # Door- / line-count suppliers: DELEGATE to delivery_rules — the SAME module the quote + PO
    # builders use — so the invoice checker charges the identical rate (Daniela 2026-11-11: new
    # delivery rules must apply everywhere). LPD/JB Kind/Deanta price by door count + postcode
    # surcharge; Vista by goods + lines. `order` → simple lines for the door/hardware split.
    sc = norm_code(supplier)
    if sc.startswith(("lpd", "jbkind", "deanta", "vista")):
        try:
            import delivery_rules as dr
            lines = [{"description": v.get("name"), "qty": v.get("qty"),
                      "tags": v.get("tags") or [], "weight": v.get("weight")}
                     for v in (order or {}).values()]
            if sc.startswith("lpd"):
                return dr.lpd_expected(lines, ship)
            if sc.startswith("jbkind"):
                return dr.jbkind_expected(lines, ship)
            if sc.startswith("deanta"):
                return dr.deanta_expected(goods_value, lines, ship)
            if sc.startswith("vista"):
                return dr.vista_expected(goods_value, lines)
        except Exception:  # noqa: BLE001
            return None

    rule = DELIVERY_CHARGES.get(supplier)
    if not rule:
        # Fall back to the quote/PO flat map (delivery_rules.FLAT) so a flat carriage rate added there
        # ALSO applies to the invoice checker — one place to add a supplier's rate (Daniela 2026-11-11).
        try:
            import delivery_rules as dr
            flr = (getattr(dr, "FLAT", None) or {}).get(supplier)
            if flr:
                flat, free_over = flr
                if free_over is not None and goods_value is not None and goods_value >= free_over:
                    return 0.0
                return float(flat or 0.0)
        except Exception:  # noqa: BLE001
            pass
        return None
    free_over = rule.get("free_over")
    if free_over is not None and goods_value is not None and goods_value >= free_over:
        return 0.0
    return float(rule.get("flat", 0.0))


def is_delivery(text):
    t = (text or "").lower()
    return any(w in t for w in ("deliver", "carriage", "carrier", "courier", "freight",
                                "shipping", "postage", "haulage", "transport"))


def is_surcharge(text):
    t = (text or "").lower()
    return "surcharge" in t or "uplift" in t


def ancillary_charge(supplier, sku_raw, desc):
    t = f"{sku_raw} {desc}".lower()
    for rule in SUPPLIER_CHARGES.get(supplier, ()):
        if any(k in t for k in rule["keywords"]):
            return rule
    return None


def _merge_lpd_packs(parsed_lines, supplier, pidx):
    """LPD split one furniture product (e.g. a HALSTON bed) across several 'pack' invoice lines, each
    with SKU = the base code + a pack index (HALSTON4.6 → HALSTON4.61 + HALSTON4.62) carrying a SHARE
    of the price; our pricelist holds only the BASE (whole-item) cost. Merge the sibling packs back
    into ONE line (base SKU, summed total, shared qty) BEFORE pricing, so the item checks against the
    base cost and matches its order line once — instead of every pack reading 'no pricelist cost' and
    the quantity being counted once per pack. Only fires for LPD, for a SKU not itself on the
    pricelist whose base (minus 1-2 trailing digits) IS, with ≥2 such siblings. Non-LPD is untouched."""
    def _priced(sk_norm):
        return (pidx.get(sk_norm) or {}).get(supplier) is not None \
            or order_sku_cost(sk_norm, supplier, pidx) is not None

    def _base(sk_norm):
        for n in (2, 1):                       # strip up to 2 trailing pack digits to reach a priced base
            if len(sk_norm) > n and sk_norm[-n:].isdigit() and _priced(sk_norm[:-n]):
                return sk_norm[:-n]
        return None

    def _tot(l):
        if isinstance(l.get("line_total"), (int, float)):
            return l["line_total"]
        u, q = l.get("unit_price"), l.get("qty")
        return u * q if isinstance(u, (int, float)) and isinstance(q, (int, float)) else None

    groups = {}
    for i, l in enumerate(parsed_lines):
        raw = l.get("sku") or ""
        snorm = norm_code(raw)
        if (not snorm) or str(raw).lstrip().startswith(".") or _priced(snorm) \
                or is_delivery(raw) or is_delivery(l.get("description")) \
                or is_surcharge(raw) or is_surcharge(l.get("description")):
            continue
        b = _base(snorm)
        if b:
            groups.setdefault(b, []).append(i)
    packs_by_first = {idxs[0]: b for b, idxs in groups.items() if len(idxs) >= 2}
    if not packs_by_first:
        return parsed_lines
    member = {i for idxs in groups.values() if len(idxs) >= 2 for i in idxs}
    out = []
    for i, l in enumerate(parsed_lines):
        if i in packs_by_first:
            b = packs_by_first[i]
            packs = [parsed_lines[j] for j in groups[b]]
            tots = [_tot(p) for p in packs]
            if any(t is None for t in tots):      # can't sum reliably → leave packs to flag, not mis-price
                out.extend(packs)
                continue
            total = round(sum(tots), 2)
            qtys = [p.get("qty") for p in packs if isinstance(p.get("qty"), (int, float))]
            q = qtys[0] if (qtys and len(set(qtys)) == 1) else (qtys[0] if qtys else 1)
            disp = (os.path.commonprefix([str(p.get("sku") or "") for p in packs])
                    or str(packs[0].get("sku") or "")).rstrip(" .-") or str(packs[0].get("sku") or "")
            out.append({"sku": disp, "description": packs[0].get("description"), "qty": q,
                        "unit_price": round(total / q, 2) if q else total, "line_total": total,
                        "_pack_note": (f"{len(packs)} packs ("
                                       + ", ".join(str(p.get("sku")) for p in packs)
                                       + f") summed to £{total:,.2f}, checked vs the base pricelist cost")})
        elif i not in member:
            out.append(l)
    return out


# ---- the 3-way check ------------------------------------------------------------------
def check_invoice(parsed, supplier_name, order, pidx, tidx, cidx, carron_ship=None, tol=0.01,
                  agreed_cost=None, single_invoice=False):
    """3-way match: each invoice line vs the supplier's pricelist cost and vs the order's
    SKUs/quantities. `order`, `tidx`, `cidx`, `carron_ship` are supplied by the caller
    (the app or the headless runner). Returns the same result dict app._check_invoice does."""
    supplier = canon_supplier(supplier_name)   # 'LPD DOORS'/'LPD', 'Hurlingham'/'Carron' → one key
    no_pl = SUPPLIER_RULES.get(supplier, {}).get("no_pricelist", False)
    if no_pl:
        tidx = cidx = None
    parsed_lines = parsed.get("lines") or []
    if norm_code(supplier).startswith("lpd"):
        # LPD split furniture into priced 'packs' (HALSTON4.6 → HALSTON4.61 + HALSTON4.62) — merge them
        # back to one base line so the summed packs check against the base pricelist cost once.
        parsed_lines = _merge_lpd_packs(parsed_lines, supplier, pidx)

    def _line_total(l):
        if isinstance(l.get("line_total"), (int, float)):
            return l["line_total"]
        u, q = l.get("unit_price"), l.get("qty")
        return u * q if isinstance(u, (int, float)) and isinstance(q, (int, float)) else 0

    def _is_charge_line(l):
        return (is_delivery(l.get("sku")) or is_delivery(l.get("description"))
                or is_surcharge(l.get("sku")) or is_surcharge(l.get("description")))

    goods_value = sum(_line_total(l) for l in parsed_lines if not _is_charge_line(l))
    delivery_goods = goods_value
    if is_decor8(supplier) and goods_value:
        delivery_goods = goods_value / max(0.01, 1.0 - DECOR8_DISCOUNT)

    common = order_common_tokens(order)
    lines, pending, hit = [], [], set()
    saw_delivery = False
    inv_qty = {}

    def _hit(rec, k):
        rec["_okey"] = k
        hit.add(k)
        q = rec.get("qty")
        if isinstance(q, (int, float)):
            inv_qty[k] = inv_qty.get(k, 0) + q

    for ln in parsed_lines:
        sku_raw = ln.get("sku") or ""
        desc = ln.get("description") or ""
        qty, unit = ln.get("qty"), ln.get("unit_price")

        # Bundled component line (e.g. Nuie '..WRSB700G', '..WRSF018') — included in the parent
        # product's price above, not a separate order line. Don't price-check or flag it.
        if str(sku_raw).lstrip().startswith("."):
            lines.append({"sku": str(sku_raw).lstrip(". "), "desc": desc, "qty": qty,
                          "unit": None, "cost": None, "_okey": None,
                          "issues": [("name", "included component of the product above "
                                              "— no separate charge")]})
            continue

        chg = ancillary_charge(supplier, sku_raw, desc)
        if chg:
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            cap = chg.get("amount")
            aissues = []
            if cap is not None and isinstance(amt, (int, float)) and abs(amt) > cap + tol:
                aissues.append(("price", f"{chg['label']} £{abs(amt):,.2f} vs agreed £{cap:,.2f}"))
            lines.append({"sku": sku_raw or chg["label"], "desc": desc or chg["label"],
                          "qty": qty, "unit": unit, "cost": cap, "issues": aissues})
            continue

        if is_delivery(sku_raw) or is_delivery(desc):
            saw_delivery = True
            known = expected_delivery(supplier, delivery_goods, carron_ship, order)
            zinfo = f" ({carron_zone_label(carron_ship)})" if is_carron(supplier) else ""
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            dissues = []
            if isinstance(amt, (int, float)):
                if known is not None:
                    if amt > known + tol:
                        dissues.append(("delivery", f"delivery £{amt:,.2f} vs expected "
                                                    f"£{known:,.2f}{zinfo}"))
                elif SUPPLIER_RULES.get(supplier, {}).get("delivery_any"):
                    dissues.append(("name", f"delivery £{amt:,.2f} — accepted (no agreed rate; "
                                            "quote-by-quote)"))
                elif is_carron(supplier):
                    dissues.append(("delivery", f"delivery £{amt:,.2f} —{zinfo} rate is TBC, "
                                                "can't check"))
                else:
                    dissues.append(("delivery", f"delivery £{amt:,.2f} — no agreed rate on file"))
            lines.append({"sku": sku_raw or "Delivery", "desc": desc, "qty": qty,
                          "unit": unit, "cost": known, "issues": dissues})
            continue

        if is_surcharge(sku_raw) or is_surcharge(desc):
            sur = SUPPLIER_SURCHARGE.get(supplier, 0.0)
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            sissues = []
            if sur and isinstance(amt, (int, float)) and goods_value:
                exp = goods_value * sur
                if amt > exp + tol:
                    sissues.append(("price", f"surcharge £{amt:,.2f} vs expected "
                                             f"{sur * 100:.0f}% of goods (£{exp:,.2f})"))
                else:
                    sissues.append(("name", f"{sur * 100:.0f}% surcharge £{amt:,.2f} — expected, "
                                            "not on the Shopify order"))
            else:
                sissues.append(("name", "surcharge — expected, not on the Shopify order"))
            lines.append({"sku": sku_raw or "Surcharge", "desc": desc, "qty": qty,
                          "unit": unit, "cost": None, "issues": sissues})
            continue

        sk = norm_code(sku_raw)
        issues = []
        cost = None
        title_note = None
        if is_decor8(supplier):
            pass
        else:
            supcosts = pidx.get(sk) or {}
            cost = supcosts.get(supplier)
            if cost is None and not no_pl and cidx:
                c2, mc = supplier_code_cost(sku_raw, desc, supplier, cidx)
                if c2 is not None:
                    cost, title_note = c2, f"code {mc}"
            if cost is None and not no_pl and tidx:
                c2, mt = supplier_title_cost(desc, supplier, tidx)
                if c2 is not None:
                    cost, title_note = c2, mt
            if cost is None and not no_pl:
                # Re-coded suppliers (Squaredeal) print their own codes — resolve the cost from those
                # via the durable overrides, including code patterns (e.g. any colour's ext corner
                # 'KB571859' → suffix 859 → £25.20). Still only this supplier's own price.
                c2 = order_sku_cost(sku_raw, supplier, pidx)
                if c2 is not None:
                    cost = c2
            if cost is None and not no_pl:
                # Supplier truncated the SKU on the invoice (dropped a trailing suffix like 'C') so it
                # no longer matches our fuller pricelist code — resolve by unambiguous prefix.
                c3 = cost_by_prefix(sk, supplier, pidx)
                if c3 is not None:
                    cost, title_note = c3, "matched to our pricelist code by SKU prefix"
            if cost is None and not no_pl and len(sk) >= 8:
                # Pricelist prefix still ambiguous (e.g. 'ZZZ047-SUNTUF' matches many Suntuf sizes), but
                # THIS order usually has just ONE such line — disambiguate via the order and take its
                # cost (the full order SKU IS in our pricelist).
                oks = [ok for ok, ov in order.items()
                       if (ok and ok.startswith(sk)) or (ov.get("sku") and norm_code(ov["sku"]).startswith(sk))]
                if len(oks) == 1:
                    c4 = order_sku_cost(order[oks[0]].get("sku"), supplier, pidx)
                    if c4 is not None:
                        cost, title_note = c4, f"matched to order line {order[oks[0]].get('sku')}"
            if not no_pl:
                if isinstance(unit, (int, float)) and isinstance(cost, (int, float)):
                    sur = SUPPLIER_SURCHARGE.get(supplier, 0.0)
                    allowed = cost * (1 + sur)
                    via = f" (vs '{title_note}' on the pricelist)" if title_note else ""
                    if unit > allowed + tol:
                        if sur:
                            issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                                    f"+{sur * 100:.0f}% surcharge (£{allowed:,.2f}) — "
                                                    f"still over by £{unit - allowed:,.2f}{via}"))
                        else:
                            issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                                    f"(+£{unit - cost:,.2f}){via}"))
                    elif sur and unit > cost + tol:
                        issues.append(("name", f"£{unit:,.2f} = pricelist £{cost:,.2f} + "
                                               f"{sur * 100:.0f}% surcharge{via}"))
                    elif title_note:
                        issues.append(("name", f"price checked vs '{title_note}' on the pricelist"))
                elif isinstance(unit, (int, float)) and cost is None:
                    issues.append(("noprice", "no pricelist cost for this supplier/SKU"))
        if ln.get("_pack_note"):
            issues.append(("name", ln["_pack_note"]))
        rec = {"sku": sku_raw, "desc": ln.get("description"), "qty": qty,
               "unit": unit, "line_total": ln.get("line_total"), "cost": cost,
               "issues": issues, "_okey": None}
        lines.append(rec)

        eq = equiv_match(supplier, sk, desc, order, hit)
        skc = sku_keys(sk, order)
        if eq:
            _hit(rec, eq)
            issues.append(("name", f"matched to order line {order[eq]['sku']} — known product "
                                   "equivalence (supplier names it differently)"))
        elif len(skc) == 1:
            _hit(rec, skc[0])
            issues.append(("name", f"matched to order line {order[skc[0]]['sku']} — SKU matches "
                                   "exactly"))
        elif len(skc) > 1:
            pending.append(rec)
        else:
            ck = code_match(sk, order, hit)
            pk = prefix_match(sk, order, hit)
            if ck and names_ok(desc, order[ck].get("name"), common):
                _hit(rec, ck)
                issues.append(("name", f"matched to order line {order[ck]['sku']} by product "
                                       "code (in our SKU)"))
            elif pk and (len(sk) >= 12 or names_ok(desc, order[pk].get("name"), common)):
                # Truncated invoice SKU that's a unique prefix of our order SKU (a long, unambiguous
                # prefix is strong on its own; a shorter one still needs the description to agree).
                _hit(rec, pk)
                issues.append(("name", f"matched to order line {order[pk]['sku']} — invoice SKU is a "
                                       "truncated prefix of ours"))
            else:
                pending.append(rec)

    carriage = parsed.get("carriage")
    if isinstance(carriage, (int, float)) and carriage > tol and not saw_delivery:
        known = expected_delivery(supplier, delivery_goods, carron_ship, order)
        cissues = []
        if known is not None:
            if carriage > known + tol:
                zinfo = f" ({carron_zone_label(carron_ship)})" if is_carron(supplier) else ""
                cissues.append(("delivery", f"carriage £{carriage:,.2f} vs expected "
                                            f"£{known:,.2f}{zinfo}"))
        elif SUPPLIER_RULES.get(supplier, {}).get("delivery_any"):
            cissues.append(("name", f"carriage £{carriage:,.2f} — accepted (no agreed rate; "
                                    "quote-by-quote)"))
        elif not is_carron(supplier):
            cissues.append(("delivery", f"carriage £{carriage:,.2f} — no agreed rate on file"))
        lines.append({"sku": "Carriage", "desc": "Carriage (from invoice totals)", "qty": None,
                      "unit": carriage, "cost": known, "issues": cissues})

    scored = []
    type_guard = supplier in _TYPE_MATCH_SUPPLIERS
    for idx, rec in enumerate(pending):
        dt = title_tokens(rec["desc"])
        rtype = product_type(rec.get("desc")) if type_guard else None
        for k, v in order.items():
            if k in hit:
                continue
            # Re-coded suppliers: don't let a shared generic word pull a line onto the wrong PRODUCT
            # (a "fibre cement SAW BLADE" matching a "fibre cement GUILLOTINE"). When both sides have a
            # definite, different product type, they can't be the same line.
            if type_guard:
                vtype = product_type(v.get("name"))
                if rtype != "other" and vtype != "other" and rtype != vtype:
                    continue
            s = name_pair_score(dt, title_tokens(v.get("name")), common)
            if s > 0:
                scored.append((s, idx, k))
    scored.sort(key=lambda x: (-x[0], x[1]))
    done = set()
    for _s, idx, k in scored:
        if idx in done or k in hit:
            continue
        done.add(idx)
        _hit(pending[idx], k)
        pending[idx]["issues"].append(("name", f"matched to order line {order[k]['sku']} by "
                                               "product name (invoice SKU differs)"))
    # Decor8 have NO SKUs, so a line is name-only and essentially always on the order. Any
    # Decor8 line still unmatched gets a lenient leftover pass: pair it to the remaining order
    # line with the most shared words, so we don't falsely say 'not on the order'.
    if is_decor8(supplier):
        lscored = []
        for idx in range(len(pending)):
            if idx in done:
                continue
            dt = title_tokens(pending[idx]["desc"])
            for k, v in order.items():
                if k in hit:
                    continue
                shared = dt & title_tokens(v.get("name"))
                # Needs a real shared WORD (4+ chars), not just a size digit like '5' (5L vs
                # 2.5L) which must never link two unrelated products.
                if any(len(t) >= 4 for t in shared):
                    lscored.append((len(shared), idx, k))
        lscored.sort(key=lambda x: (-x[0], x[1]))
        for ov, idx, k in lscored:
            if idx in done or k in hit:
                continue
            done.add(idx)
            _hit(pending[idx], k)
            pending[idx]["issues"].append(("name", f"matched to order line {order[k]['sku']} by "
                                                   "name (Decor8 — no SKU, so name-matched)"))
    # Product-TYPE leftover (re-coded suppliers). When an order has several lines of the SAME colour
    # (e.g. a Monterey Taupe BOARD and a Monterey Taupe CORNER), the colour words become "common" and
    # the distinctive-word scorer wipes them out, so the board line scores 0 everywhere → false "not on
    # the order". Pair each still-unmatched invoice line to the remaining order line of the SAME product
    # TYPE, confirmed by a shared real word (the colour) OR an exact quantity match. High-confidence:
    # only fires on leftovers, never steals a scored match, and needs type + (colour or qty) to agree.
    if supplier in _TYPE_MATCH_SUPPLIERS:
        for idx, rec in enumerate(pending):
            if idx in done:
                continue
            itype = product_type(rec.get("desc"))
            dt = {t for t in title_tokens(rec.get("desc")) if len(t) >= 4 and not t.isdigit()}
            best, best_key = (-1, -1), None
            for k, v in order.items():
                if k in hit or product_type(v.get("name")) != itype:
                    continue
                real_shared = len(dt & {t for t in title_tokens(v.get("name")) if len(t) >= 4 and not t.isdigit()})
                qty_m = 1 if (rec.get("qty") is not None and rec.get("qty") == v.get("qty")) else 0
                if real_shared == 0 and qty_m == 0:
                    continue                       # same type but nothing confirms it — skip
                score = (qty_m, real_shared)
                if score > best:
                    best, best_key = score, k
            if best_key is not None:
                done.add(idx)
                _hit(pending[idx], best_key)
                pending[idx]["issues"].append(("name", f"matched to order line {order[best_key]['sku']} "
                                               "by product type + colour (invoice code differs)"))

    # Carron radiators: one order line per SECTION COUNT of a range, and the Shopify names are near
    # identical except the count (a 7-section and a 10-section Victorian 4 Col 810mm). The distinctive-
    # word scorer can't tell them apart, so match each remaining Carron line to the order line with the
    # SAME section count (Carron's invoice uses its own CFG codes, which carry no cost of their own).
    if is_carron(supplier):
        def _sec(t):
            m = _SECTIONS_RE.search(str(t or ""))
            return int(m.group(1)) if m else None
        for idx, rec in enumerate(pending):
            if idx in done:
                continue
            isec = _sec(rec.get("desc"))
            if isec is None:
                continue
            for k, v in order.items():
                if k in hit or _sec(v.get("name")) != isec:
                    continue
                done.add(idx)
                _hit(pending[idx], k)
                pending[idx]["issues"].append(("name", f"matched to order line {order[k]['sku']} "
                                               f"by section count ({isec})"))
                break

    for idx, rec in enumerate(pending):
        if idx not in done:
            # A line with no charge (unit and line-total both blank/0) is an INCLUDED item (e.g. the
            # free bleed/blank valves on a Carron radiator) — not on the Shopify order, but not a
            # discrepancy either.
            if rec.get("unit") in (None, 0) and rec.get("line_total") in (None, 0):
                rec["issues"].append(("name", "no charge — included item, not on the Shopify order"))
            else:
                rec["issues"].append(("notorder", "not on the order"))

    for k in hit:
        exp, tot = order[k]["qty"], inv_qty.get(k)
        if exp is None or tot is None:
            continue
        # Molan per-m² polycarbonate: they invoice by AREA, we order by SHEET, so reconcile the
        # invoiced m² against sheets × the sheet size (e.g. 7 × 2000×700mm = 9.8 m²) instead of
        # flagging '9.8 vs 7'. If we can't read the sheet size, don't flag (numeric diff is expected).
        if norm_code(supplier) == "molan" and is_persqm_poly(order[k].get("sku")):
            area = sheet_sqm(order[k].get("name"))
            if area:
                order_sqm = round(exp * area, 2)
                if abs(tot - order_sqm) > max(0.1, order_sqm * 0.02):
                    recs = [r for r in lines if r.get("_okey") == k]
                    if recs:
                        recs[0]["issues"].append(("qty", f"invoiced {tot} m² vs {exp} sheet(s) × "
                                                  f"{area} m² = {order_sqm} m²"))
            continue
        if int(round(tot)) == exp:
            continue
        recs = [r for r in lines if r.get("_okey") == k]
        if recs:
            td = int(tot) if float(tot).is_integer() else tot
            extra = f" (across {len(recs)} invoice lines)" if len(recs) > 1 else ""
            recs[0]["issues"].append(("qty", f"invoiced {td}{extra} vs order {exp}"))

    if is_decor8(supplier):
        for rec in lines:
            okey = rec.get("_okey")
            if okey is None:
                continue
            rec["issues"].append(("name", "⚠ check the SIZE matches (Decor8 name different "
                                          "pot sizes very similarly)"))
            our_sell = order[okey].get("price")
            q, lt = rec.get("qty"), rec.get("line_total")
            paid = (lt / q if isinstance(lt, (int, float)) and isinstance(q, (int, float)) and q
                    else rec.get("unit"))
            if our_sell and isinstance(paid, (int, float)):
                rec["cost"] = paid
                disc = (1 - paid / our_sell) * 100
                if paid > our_sell * (1 - DECOR8_MIN_DISCOUNT) + tol:
                    rec["issues"].append(("price", f"paid £{paid:,.2f}/unit vs our price "
                                                   f"£{our_sell:,.2f} — only {disc:.1f}% off "
                                                   f"(expect ~{DECOR8_DISCOUNT * 100:.0f}%)"))
                else:
                    rec["issues"].append(("name", f"£{paid:,.2f} = our price £{our_sell:,.2f} "
                                                  f"less {disc:.1f}%"))
            elif isinstance(paid, (int, float)):
                rec["issues"].append(("noprice", "matched by name, but that Shopify order line "
                                                 "has no price to compare"))

    # Re-coded suppliers (Squaredeal, GAP, Eurocell…) print their OWN product codes on the invoice, so
    # the cost lookup by the invoice SKU above returned nothing ("no pricelist cost"). Each such line
    # has since been matched to one of OUR order lines whose SKU DOES carry this supplier's cost —
    # reprice against that order SKU (still this supplier's own price, never another's). Mirrors the
    # Streamlit app's _price_issues, which the web/runner checker never had.
    if not no_pl and not is_decor8(supplier):
        for rec in lines:
            if rec.get("cost") is not None:
                continue
            okey = rec.get("_okey")
            if not okey:
                continue
            osku = order[okey].get("sku")
            # Carron radiators price PER SECTION off the matched order's leg-coded SKU, reading the
            # section count + finish from the invoice description / order variant (the invoice uses
            # Carron's own CFG codes which carry no cost of their own).
            c = persection_cost(osku, supplier, order[okey].get("name"), rec.get("desc"))
            if c is None:
                c = order_sku_cost(osku, supplier, pidx)
            if c is None:
                continue
            rec["cost"] = c
            rec["issues"] = [i for i in rec["issues"] if i[0] != "noprice"]
            unit = rec.get("unit")
            if isinstance(unit, (int, float)):
                sur = SUPPLIER_SURCHARGE.get(supplier, 0.0)
                allowed = c * (1 + sur)
                if unit > allowed + tol:
                    rec["issues"].append(("price", f"£{unit:,.2f} vs pricelist £{c:,.2f} "
                                                   f"(+£{unit - c:,.2f}) — priced on our SKU {osku}"))
                else:
                    rec["issues"].append(("name", f"priced on our SKU {osku} — £{c:,.2f} "
                                                  "(invoice code differs)"))

    missing = [order[s]["sku"] for s in order if s not in hit]
    n_issues = sum(1 for l in lines for t, _ in l["issues"] if t != "name")
    incomplete = bool(missing) and n_issues == 0

    # AGREED PO TOTAL fast-path (Daniela 2026-11-12). The invoice's ex-VAT total to us = goods + every
    # charge line (delivery/surcharge) + any separate carriage. When a SINGLE invoice on the order
    # matches the order's £-to-supplier (our agreed PO total) within a few pence, the price is confirmed
    # by the agreed figure, so it's approvable on the total regardless of margin. A credit note, a
    # part-invoice (total < agreed), or a missing £-to-supplier falls through to the full check below.
    _charge_sum = sum(_line_total(l) for l in parsed_lines if _is_charge_line(l))
    _carr = parsed.get("carriage")
    _extra_carr = _carr if (isinstance(_carr, (int, float)) and not saw_delivery) else 0.0
    inv_total_net = round(goods_value + _charge_sum + _extra_carr, 2)
    _is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
    try:
        _agreed = float(agreed_cost) if agreed_cost not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        _agreed = None
    agreed_total_match = bool(single_invoice and _agreed and not _is_cn and inv_total_net > 0
                              and abs(inv_total_net - _agreed) <= AGREED_TOTAL_TOL)
    if agreed_total_match:
        lines.insert(0, {"sku": "✓ Agreed total", "desc": (
            f"Invoice total £{inv_total_net:,.2f} = agreed £ to supplier £{_agreed:,.2f} — approved on "
            "the agreed PO total (price confirmed; margin not required)"), "qty": None, "unit": None,
            "cost": _agreed, "issues": [("name", "matches the agreed PO total")], "_okey": None})
    return {"lines": lines, "missing": missing, "n_issues": n_issues, "incomplete": incomplete,
            "covered": set(hit), "order_map": {s: order[s]["sku"] for s in order},
            "agreed_total_match": agreed_total_match, "inv_total_net": inv_total_net,
            "agreed_cost": _agreed}


def verdict(res):
    order_issue = any(t in ("qty", "notorder") for l in res["lines"] for t, _ in l["issues"])
    price_issue = any(t in ("price", "delivery") for l in res["lines"] for t, _ in l["issues"])
    price_unchecked = any(t == "noprice" for l in res["lines"] for t, _ in l["issues"])
    price = False if price_issue else (None if price_unchecked else True)
    return {"order": not order_issue, "price": price, "incomplete": bool(res.get("incomplete"))}


def push_decision(matched, is_cn, live_margin, supplier=None,
                  lo=MARGIN_PUSH_MIN, hi=MARGIN_PUSH_MAX):
    """(label, action) — action: 'push' | 'hold' | 'flag' | None. Same as app._push_decision
    but thresholds are passed in (defaults MARGIN_PUSH_MIN/MAX) since there's no UI session."""
    rule = SUPPLIER_RULES.get(norm_code(supplier), {}) if supplier else {}
    lo = rule.get("push_min", lo)
    hi = rule.get("push_max", hi)            # per-supplier high ceiling (e.g. Decor8 65%)
    flag_high = rule.get("flag_high", True)
    if not matched:
        return None, None
    if live_margin is None or live_margin < lo:
        return MATCHED_LABEL, "hold"
    if flag_high and live_margin > hi:
        return DISCREPANCY_LABEL, "flag"
    return (CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL), "push"


def dedup_plan(invs):
    """Split a list of invoices into (kept, duplicates): a duplicate is a later subitem with
    the SAME order + invoice number as one already seen (Eurocell send two copies)."""
    seen, kept, dups = {}, [], []
    for i in invs:
        no = (i.get("invoice_no") or "").strip().upper()
        k = (i.get("order_no") or "", no)
        if no and k in seen:
            dups.append(i)
        else:
            if no:
                seen[k] = i
            kept.append(i)
    return kept, dups


def amount_dup_ids(invs):
    """{sub_id: other_invoice_no} for invoices sharing the SAME order + SAME total as another
    invoice with a DIFFERENT number — a likely double-invoice (Decor8 billing one order twice
    under two numbers). Flagged, not deleted (numbers differ ⇒ could rarely be legit)."""
    from collections import defaultdict
    groups = defaultdict(list)
    for i in invs:
        t = i.get("total")
        if isinstance(t, (int, float)) and (i.get("order_no") or "").strip():
            groups[(i.get("order_no"), round(t, 2))].append(i)
    out = {}
    for g in groups.values():
        nums = {(x.get("invoice_no") or "").strip().upper() for x in g if x.get("invoice_no")}
        if len(g) >= 2 and len(nums) >= 2:
            for x in g:
                others = [y.get("invoice_no") for y in g if y.get("sub_id") != x.get("sub_id")]
                out[str(x["sub_id"])] = next((o for o in others if o), "another invoice")
    return out


def discrepancy_reason(res):
    """One-line reason for the log/note (no 'awaiting credit note' wording)."""
    reasons, seen = [], set()
    for l in res["lines"]:
        sku = l.get("sku") or "item"
        for t, _m in l["issues"]:
            r = ({"price": f"{sku} overcharged", "delivery": "delivery overcharged",
                  "notorder": f"{sku} not on order", "qty": f"{sku} qty wrong"}).get(t)
            if r and r not in seen:
                seen.add(r)
                reasons.append(r)
    return "TradeHub: " + ("; ".join(reasons[:6]) or "see invoice")
