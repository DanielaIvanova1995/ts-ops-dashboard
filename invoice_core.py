"""
Headless invoice-check engine — the SAME 3-way match, supplier rules, matching and
push-decision logic the Trade Hub app uses, but with NO Streamlit / no I/O so it can run
in the scheduled cloud runner (run_invoice_check.py) as well as the app.

Pure by design: the caller fetches the order lines, shipping and pricing lookup and passes
them in. Kept deliberately in step with app.py — if you change a rule in one, change it in
the other (a later refactor will make app.py import from here so there's a single copy).
"""
import re

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
    "chasehardware": {"name": "Chase Hardware", "flat": 10.0},
}
DECOR8_DISCOUNT = 0.12
DECOR8_MIN_DISCOUNT = 0.10
SUPPLIER_SURCHARGE = {"eurocell": 0.05}

CARRON_FREE_OVER = 250.0
CARRON_ZONES = {
    1: {"name": "UK Mainland", "large": 25.0, "small": 10.0},
    2: {"name": "Scotland", "large": 50.0, "small": 20.0},
    3: {"name": "Scottish Highlands", "large": 85.0, "small": 25.0},
    4: {"name": "Northern Ireland", "large": 65.0, "small": 25.0},
    5: {"name": "Republic of Ireland", "large": None, "small": None},
    6: {"name": "Isles", "large": 105.0, "small": 25.0},
}
CARRON_AREA_ZONE = {
    "AB": 2, "DD": 2, "DG": 2, "EH": 2, "FK": 2, "G": 2, "KA": 2, "KY": 2,
    "ML": 2, "PA": 2, "TD": 2, "IV": 3, "KW": 3, "PH": 3, "BT": 4,
    "HS": 6, "ZE": 6, "IM": 6,
}

SUPPLIER_RULES = {
    "travisperkins": {"name": "Travis Perkins", "no_pricelist": True,
                      "push_min": 10.0, "flag_high": False},
    "decor8": {"name": "Decor8", "push_min": 5.0},
}
SUPPLIER_EMAILS = {
    "upb": "janetwitt@upbuildingproducts.com",
    "up": "janetwitt@upbuildingproducts.com",
    "upbuildingproducts": "janetwitt@upbuildingproducts.com",
    "pjh": "accounts@pjh.uk",
    "gap": "carrie.morris@gap.uk.com",
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


def title_tokens(s):
    s = (s or "").lower()
    s = re.sub(r"(?<=\d)(?=[a-z])", " ", s)
    s = re.sub(r"(?<=[a-z])(?=\d)", " ", s)
    out = set()
    for w in re.findall(r"[a-z0-9]+", s):
        for part in _TOK_ABBREV.get(w, w).split():
            if part in _TOK_STOP or (len(part) < 2 and not part.isdigit()):
                continue
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
                        "qty": l.get("qty"), "name": l.get("title"), "price": l.get("price")}
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
def pricelist_index(lookup):
    """{norm_sku: {norm_supplier: cost}} from the lookup offers."""
    idx = {}
    for it in (lookup["items"] if lookup else []):
        sk = norm_code(it.get("sku"))
        if not sk:
            continue
        for o in (it.get("offers") or []):
            sup = norm_code(o.get("s"))
            if sup and o.get("c") is not None:
                idx.setdefault(sk, {})[sup] = o.get("c")
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
def is_decor8(supplier):
    return (supplier or "").startswith("decor8") or (supplier or "").startswith("decor")


def is_carron(supplier):
    return (supplier or "").startswith("carron")


# Ctie (C TIE) zone-based delivery: UK mainland £7 under £100 (free over); Northern Ireland
# (BT postcodes) £13 under £250 (free over). Priced on the delivery postcode.
CTIE_UK = {"flat": 7.0, "free_over": 100.0}
CTIE_NI = {"flat": 13.0, "free_over": 250.0}


def is_ctie(supplier):
    return (supplier or "").startswith("ctie")


def ctie_expected(goods_value, ship):
    pc = re.sub(r"[^A-Z0-9]", "", ((ship or {}).get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    country = ((ship or {}).get("country") or "").strip().upper()
    is_ni = area == "BT" or country in ("GB-NIR", "NORTHERN IRELAND")
    rule = CTIE_NI if is_ni else CTIE_UK
    if goods_value is not None and goods_value >= rule["free_over"]:
        return 0.0
    return rule["flat"]


def carron_zone(ship):
    if not ship:
        return 1
    country = (ship.get("country") or "").strip().upper()
    if country in ("IE", "IRL", "IRELAND", "REPUBLIC OF IRELAND", "EIRE"):
        return 5
    pc = re.sub(r"[^A-Z0-9]", "", (ship.get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    return CARRON_AREA_ZONE.get(area, 1)


def carron_zone_label(ship):
    z = carron_zone(ship)
    pc = (ship or {}).get("postcode") or "no postcode"
    return f"Carron Zone {z} — {CARRON_ZONES[z]['name']}, {pc}"


def carron_expected(goods_value, ship):
    z = carron_zone(ship)
    zc = CARRON_ZONES[z]
    if z == 1 and goods_value is not None and goods_value >= CARRON_FREE_OVER:
        return 0.0
    return zc["large"]


def expected_delivery(supplier, goods_value, ship=None):
    if is_carron(supplier):
        return carron_expected(goods_value, ship)
    if is_ctie(supplier):
        return ctie_expected(goods_value, ship)
    rule = DELIVERY_CHARGES.get(supplier)
    if not rule:
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


# ---- the 3-way check ------------------------------------------------------------------
def check_invoice(parsed, supplier_name, order, pidx, tidx, cidx, carron_ship=None, tol=0.01):
    """3-way match: each invoice line vs the supplier's pricelist cost and vs the order's
    SKUs/quantities. `order`, `tidx`, `cidx`, `carron_ship` are supplied by the caller
    (the app or the headless runner). Returns the same result dict app._check_invoice does."""
    supplier = norm_code(supplier_name)
    no_pl = SUPPLIER_RULES.get(supplier, {}).get("no_pricelist", False)
    if no_pl:
        tidx = cidx = None
    parsed_lines = parsed.get("lines") or []

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
            known = expected_delivery(supplier, delivery_goods, carron_ship)
            zinfo = f" ({carron_zone_label(carron_ship)})" if is_carron(supplier) else ""
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            dissues = []
            if isinstance(amt, (int, float)):
                if known is not None:
                    if amt > known + tol:
                        dissues.append(("delivery", f"delivery £{amt:,.2f} vs expected "
                                                    f"£{known:,.2f}{zinfo}"))
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
            if ck and names_ok(desc, order[ck].get("name"), common):
                _hit(rec, ck)
                issues.append(("name", f"matched to order line {order[ck]['sku']} by product "
                                       "code (in our SKU)"))
            else:
                pending.append(rec)

    carriage = parsed.get("carriage")
    if isinstance(carriage, (int, float)) and carriage > tol and not saw_delivery:
        known = expected_delivery(supplier, delivery_goods, carron_ship)
        cissues = []
        if known is not None:
            if carriage > known + tol:
                zinfo = f" ({carron_zone_label(carron_ship)})" if is_carron(supplier) else ""
                cissues.append(("delivery", f"carriage £{carriage:,.2f} vs expected "
                                            f"£{known:,.2f}{zinfo}"))
        elif not is_carron(supplier):
            cissues.append(("delivery", f"carriage £{carriage:,.2f} — no agreed rate on file"))
        lines.append({"sku": "Carriage", "desc": "Carriage (from invoice totals)", "qty": None,
                      "unit": carriage, "cost": known, "issues": cissues})

    scored = []
    for idx, rec in enumerate(pending):
        dt = title_tokens(rec["desc"])
        for k, v in order.items():
            if k in hit:
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
    for idx, rec in enumerate(pending):
        if idx not in done:
            rec["issues"].append(("notorder", "not on the order"))

    for k in hit:
        exp, tot = order[k]["qty"], inv_qty.get(k)
        if exp is None or tot is None or int(round(tot)) == exp:
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

    missing = [order[s]["sku"] for s in order if s not in hit]
    n_issues = sum(1 for l in lines for t, _ in l["issues"] if t != "name")
    incomplete = bool(missing) and n_issues == 0
    return {"lines": lines, "missing": missing, "n_issues": n_issues, "incomplete": incomplete,
            "covered": set(hit), "order_map": {s: order[s]["sku"] for s in order}}


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
