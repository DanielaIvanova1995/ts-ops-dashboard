"""Order routing engine (Phase 2).

Given an order's line items (each with its Shopify vendor + product type), suggest which supplier
each line routes to, and whether the order needs splitting across suppliers — codifying the clear,
deterministic rules from the supplier rulebook (SKILL.md / supplier_rulebook.json). Genuinely
ambiguous cases return "PICK" so the processor decides (never guessed).

Postcode-level branch selection (which UPB/Eurocell/Travis Perkins branch) is deliberately NOT
guessed here — those are flagged `needs_branch` for the processor / a later phase.
"""
import re

# Shopify vendor / brand (normalised) → the exact Monday Supplier dropdown label.
CANON = {
    "upb": "UPB", "nbp": "NBP", "squaredeal": "Squaredeal", "eurocell": "Eurocell",
    "southernsheeting": "Southern Sheeting", "ss": "Southern Sheeting",
    "travisperkins": "Travis Perkins", "tp": "Travis Perkins", "gap": "GAP",
    "huwsgray": "Huws Gray", "edmundson": "Edmundson", "mercado": "Mercardo",
    "hurlinghambaths": "Hurlingham Baths",
    "nationalskirting": "National Skirting", "molan": "Molan", "storm": "Storm",
    "pjh": "PJH", "nuie": "Nuie", "roxor": "Nuie", "decor8": "Decor8", "paintersworld": "Decor8",
    "rexel": "Rexel", "toolbank": "Toolbank", "lpd": "LPD DOORS", "lpddoors": "LPD DOORS",
    "jbkind": "JB Kind", "deanta": "Deanta", "carron": "Carron", "hurlingham": "Hurlingham",
    "chasehardware": "Chase Hardware", "chhardware": "Chase Hardware",
    "wallsandfloors": "Walls and Floors",
    "splendour": "Walls and Floors", "velux": "Velux", "dolle": "Dolle", "mbdecor": "MB Decor",
    "mbdiy": "MB Decor", "mbdecordiy": "MB Decor", "mbdecordly": "MB Decor",
    "permaroof": "Permaroof", "newplas": "newplas", "bricklink": "Bricklink",
    "brickservices": "Brickservices", "plastivan": "Plastivan", "brundle": "Brundle",
    "vista": "Vista", "etills": "Etills", "evolve": "Evolve", "ctie": "C TIE",
    "nationalplastics": "National Plastics",   # distinct from NBP
    "markovitz": "Markovitz",                    # builders' merchant — PO to Amy Charlesworth
    "ajw": "AJW", "ajwdistribution": "AJW",     # AJW Distribution — Cedral quotes
    # brand locks (Freefoam + Fortex now route by postcode to regional stockists — see
    # FREEFOAM_FORTEX_MAP / freefoam_fortex_route — so they are NOT locked to UPB here any more.)
    "jameshardie": "UPB", "hardie": "UPB", "cladco": "UPB",
}

# MB Decor removed 2026-09-06 — Daniela wants POs (emailed to orders@mbdecor.co.uk) not packing
# slips, now that MB Decor prices are loaded.
# Travis Perkins orders are placed through their online PORTAL (not an emailed PO), so they must
# land on "Go To Portal" and never auto-advance to SEND PO — even once the nearest branch is
# resolved from the postcode (Daniela 2026-09-29). TP stays in NEEDS_BRANCH too: it's both.
PORTAL = {"PJH", "Toolbank", "Velux", "Nuie", "National Skirting", "Rexel", "Travis Perkins",
          "Walls and Floors"}
QUOTE_FIRST = {"Huws Gray", "Etills", "Bricklink", "Brickservices", "AJW"}
NEEDS_BRANCH = {"Travis Perkins", "Eurocell"}    # nearest physical branch — needs the locator
IN_HOUSE = {"SAMPLES", "CLEARANCE"}
# Suppliers we're NOT buying from right now — never route to them or count their feed prices (kept
# on file with all their rules; just remove from this set to switch them back on). NBP paused.
EXCLUDED_SUPPLIERS = {"NBP"}

# ---- James Hardie / Cladco postcode routing (Aug 2026 map, avoid NBP) ----
# (Freefoam + Fortex moved to their own regional-stockist map below — FREEFOAM_FORTEX_MAP.)
# Postcode AREAS (the leading letters of a postcode) → who supplies.
_SCOTLAND = {"AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML", "PA", "PH",
             "TD", "ZE"}
# Definitive James Hardie map (Daniela, Aug 2026). Yellow = UPB Newmarket · Purple = UPB Ipswich ·
# Red = UPB Aldridge (midlands only, up to the ST/NG/DE line). Each supplier prices from its OWN list.
_UPB_NEWMARKET = {"NR", "PE", "CB", "NN", "MK", "SG", "AL", "CM", "EN", "SM"}
_UPB_IPSWICH = {"IP", "CO", "SS", "OX", "HP", "SL", "RG", "GU", "RH", "BN", "TN", "ME", "CT", "LU",
                "N", "NW", "E", "EC", "SE", "SW", "W", "WC", "WD", "HA", "UB", "TW", "KT", "CR",
                "BR", "DA", "RM", "IG"}
_UPB_ALDRIDGE = {"ST", "NG", "DE", "TF", "WS", "WV", "DY", "B", "CV", "LE", "WR", "HR", "GL"}
# North of the Aldridge line (LN/SY/CW/SK and up) → National Plastics (Hardie nationwide).
_NP_NORTH = {"CW", "SK", "S", "DN", "LN", "SY", "YO", "HG", "BD", "HU", "PR", "BB", "LS", "HX",
             "WF", "BL", "OL", "HD", "L", "WN", "WA", "M", "CH", "FY", "LA", "CA",
             "NE", "DL", "TS", "SR", "DH"}
# Pink + green south (and up to Swansea) → Squaredeal. Squaredeal is also always the SMOOTH supplier.
_SQUAREDEAL = {"SA", "CF", "NP", "LD", "TA", "EX", "PL", "TQ", "TR", "DT",
               "BS", "BA", "SP", "SO", "BH", "SN", "PO"}
# Depot ordering emails — per Daniela's map (Newmarket/Ipswich are .co.uk, Aldridge is .com).
# UPB emails are ALWAYS @upbuildingproducts.COM — never .co.uk (Daniela 2026-09-06).
_UPB_DEPOT = {"UPB Newmarket": "callumpainter@upbuildingproducts.com",
              "UPB Ipswich": "ipswich@upbuildingproducts.com",
              "UPB Aldridge": "martinmelaney@upbuildingproducts.com"}
_UPB_DEPOT_PHONE = {"UPB Newmarket": "01638501927",
                    "UPB Ipswich": "01473747122",
                    "UPB Aldridge": "07485928894"}   # all confirmed (Daniela 2026-09-13)

# ---- Freefoam + Fortex regional-stockist map (Daniela 2026-10-02, supplier-delivery-map.pdf) ----
# The WHOLE Freefoam and Fortex range now comes from regional plastics stockists, chosen by the
# delivery postcode AREA. Every one is QUOTE-FIRST for now (stage "Needs Quote", the doc is a
# packing slip with NO prices) until Daniela loads each supplier's pricelist. Where an area lists
# several stockists, the FIRST is the default and the rest are alternatives the processor can switch
# to in the grid. Areas NOT in this map have no supplier yet → the line goes to review to pick one.
# Supplier labels here are the Monday Supplier dropdown labels (auto-created on first use).
FREEFOAM_FORTEX_MAP = {
    "AB": ["Central Plastics and Roofing"],
    "BA": ["Alliance Building Plastics"],
    "BB": ["Bury Plastics", "T Roofing Supplies"],
    "BD": ["TruSeal", "Bury Plastics"],
    "BH": ["Alliance Building Plastics"],
    "BL": ["Bury Plastics", "T Roofing Supplies"],
    "BN": ["Crawley Plastics"],
    "BR": ["Crawley Plastics"],
    "BS": ["Roofbase", "Alliance Building Plastics", "PPW"],
    "CF": ["Roofbase", "PPW"],
    "CH": ["T Roofing Supplies"],
    "CR": ["Crawley Plastics"],
    "CT": ["Crawley Plastics"],
    "CW": ["Bury Plastics", "T Roofing Supplies"],
    "DD": ["Central Plastics and Roofing"],
    "DE": ["Future Building Products", "TruSeal"],
    "DG": ["Central Plastics and Roofing"],
    "DH": ["BD Plastics"],
    "DL": ["BD Plastics"],
    "DN": ["Future Building Products", "TruSeal"],
    "DT": ["Alliance Building Plastics"],
    "EH": ["Central Plastics and Roofing"],
    "EX": ["Roofbase"],
    "FK": ["Central Plastics and Roofing"],
    "FY": ["T Roofing Supplies"],
    "G":  ["Central Plastics and Roofing"],
    "GL": ["Roofbase", "PPW"],
    "GU": ["Crawley Plastics", "Alliance Building Plastics"],
    "HD": ["Future Building Products", "Bury Plastics", "T Roofing Supplies"],
    "HG": ["BD Plastics"],
    "HR": ["PPW"],
    "HX": ["Bury Plastics"],
    "IV": ["Central Plastics and Roofing"],
    "KA": ["Central Plastics and Roofing"],
    "KT": ["Crawley Plastics"],
    "KY": ["Central Plastics and Roofing"],
    "L":  ["Bury Plastics", "T Roofing Supplies"],
    "LA": ["Bury Plastics"],
    "LE": ["Roofbase", "Future Building Products", "TruSeal"],
    "LN": ["Future Building Products", "TruSeal"],
    "LS": ["TruSeal"],
    "M":  ["TruSeal", "Bury Plastics", "T Roofing Supplies"],
    "ME": ["Crawley Plastics"],
    "ML": ["Central Plastics and Roofing"],
    "NE": ["BD Plastics"],
    "NG": ["Future Building Products", "TruSeal"],
    "NP": ["PPW"],
    "OL": ["Bury Plastics", "T Roofing Supplies"],
    "PA": ["Central Plastics and Roofing"],
    "PE": ["Future Building Products"],
    "PH": ["Central Plastics and Roofing"],
    "PL": ["Roofbase"],
    "PO": ["Stalwart", "Crawley Plastics", "Alliance Building Plastics"],
    "PR": ["Bury Plastics", "T Roofing Supplies"],
    "RH": ["Crawley Plastics"],
    "S":  ["Future Building Products", "TruSeal"],
    "SA": ["Roofbase", "PPW"],
    "SK": ["Bury Plastics", "T Roofing Supplies"],
    "SM": ["Crawley Plastics"],
    "SN": ["Roofbase", "Alliance Building Plastics"],
    "SO": ["Stalwart", "Alliance Building Plastics"],
    "SP": ["Alliance Building Plastics"],
    "SR": ["BD Plastics"],
    "ST": ["Future Building Products", "TruSeal"],
    "TA": ["Alliance Building Plastics"],
    "TD": ["Central Plastics and Roofing"],
    "TN": ["Crawley Plastics"],
    "TS": ["BD Plastics"],
    "WA": ["Bury Plastics", "T Roofing Supplies"],
    "WF": ["Future Building Products"],
    "WN": ["Bury Plastics", "T Roofing Supplies"],
    "WR": ["PPW"],
    "YO": ["BD Plastics"],
}
# PO / quote-request emails for the Freefoam/Fortex stockists. Only the confirmed ones are here;
# the rest are blank until Daniela sends them (the order still routes + makes the packing slip, it
# just has no email to send to yet). CREDIT accounts: Stalwart, BD Plastics, PPW, Future Building
# Products. The others are CASH.
FREEFOAM_FORTEX_EMAIL = {
    "Stalwart": "sales@stalwartproducts.co.uk",
    "TruSeal": "steven.pritchard@trusealplastics.co.uk",
}


# CREDIT-account stockists — Daniela 2026-10-02: in a multi-supplier area, ALWAYS prefer a credit
# account first (better cashflow), then whoever's next in the map's own order.
_FF_CREDIT = {"Stalwart", "BD Plastics", "PPW", "Future Building Products"}


def freefoam_fortex_route(pc):
    """Freefoam & Fortex → a regional stockist chosen by delivery postcode area (Daniela 2026-10-02).
    Always QUOTE-first (packing slip, no prices yet). Returns {supplier, branch, branch_email,
    branch_phone, alts, reason, conf}. In a multi-stockist area, CREDIT accounts come first (then the
    map's order). If the area has no stockist yet BUT falls inside a UPB depot area, it goes to that
    UPB depot (still a quote); otherwise supplier=None so the line goes to review for a human to pick."""
    area = postcode_area(pc)
    sups = FREEFOAM_FORTEX_MAP.get(area or "")
    if not sups:
        # No regional stockist yet — but if it's a UPB depot area, send it to UPB as a quote.
        for depot, keys in (("UPB Newmarket", _UPB_NEWMARKET), ("UPB Ipswich", _UPB_IPSWICH),
                            ("UPB Aldridge", _UPB_ALDRIDGE)):
            if area in keys:
                return {"supplier": "UPB", "branch": depot, "branch_email": _UPB_DEPOT[depot],
                        "branch_phone": _UPB_DEPOT_PHONE.get(depot), "alts": [], "conf": "high",
                        "reason": f"Freefoam/Fortex — no local stockist for {area}, in UPB area "
                                  f"→ {depot} (quote)"}
        return {"supplier": None, "branch": None, "branch_email": None, "branch_phone": None,
                "alts": [], "conf": "low",
                "reason": f"Freefoam/Fortex — no stockist mapped for area "
                          f"{area or '(no postcode)'} yet — pick a supplier"}
    # Credit accounts first (stable — keeps the map's order within the credit and the cash tiers).
    ordered = sorted(sups, key=lambda s: 0 if s in _FF_CREDIT else 1)
    primary, alts = ordered[0], ordered[1:]
    alt_txt = f" · alternatives: {', '.join(alts)}" if alts else ""
    credit_note = " [credit]" if primary in _FF_CREDIT else ""
    return {"supplier": primary, "branch": None,
            "branch_email": FREEFOAM_FORTEX_EMAIL.get(primary), "branch_phone": None,
            "alts": alts, "conf": "high",
            "reason": f"Freefoam/Fortex — {area} → {primary}{credit_note} (quote){alt_txt}"}


def postcode_area(pc):
    m = re.match(r"\s*([A-Za-z]{1,2})", pc or "")
    return m.group(1).upper() if m else ""


def upb_depot_for(pc):
    """UPB Hardie depot (branch, order email, phone) for a postcode. ALWAYS returns a depot so
    FORCING UPB on any order still fills the branch + contact: the matching depot, else Newmarket
    for the southern Squaredeal patch, else Aldridge (midlands/north)."""
    area = postcode_area(pc)
    for depot, keys in (("UPB Newmarket", _UPB_NEWMARKET), ("UPB Ipswich", _UPB_IPSWICH),
                        ("UPB Aldridge", _UPB_ALDRIDGE)):
        if area in keys:
            return depot, _UPB_DEPOT[depot], _UPB_DEPOT_PHONE.get(depot)
    fb = "UPB Newmarket" if area in _SQUAREDEAL else "UPB Aldridge"
    return fb, _UPB_DEPOT[fb], _UPB_DEPOT_PHONE.get(fb)


# National Plastics (specbd) branch contacts — used for the offline region fallback when the live
# geocoder (branch_finder) can't be reached. Live path picks the nearest of these by distance.
_NP_CONTACTS = {
    "National Plastics — Rotherham": ("Afearn@specbd.co.uk", "01827 948660"),
    "National Plastics — Abercarn": ("AbercarnManager@nationalplastics.co.uk", "01495 248469"),
    "National Plastics — Maidstone": ("Aellerbeck@shepherdsuk.co.uk", "01622 695909"),
}


def _np_branch(pc):
    """Nearest National Plastics branch for a postcode → {branch_name, email, phone, miles}. Uses the
    live geocoder (branch_finder) for true distance; falls back to a coarse region map offline
    (north/Scotland → Rotherham, Wales/south-west → Abercarn, else → Maidstone)."""
    try:
        import branch_finder
        nb = branch_finder.national_plastics_branch(pc)
        if nb and nb.get("branch_name"):
            return nb
    except Exception:  # noqa: BLE001
        pass
    area = postcode_area(pc)
    if area in _SCOTLAND or area in _NP_NORTH:
        name = "National Plastics — Rotherham"
    elif area in _SQUAREDEAL:
        name = "National Plastics — Abercarn"
    else:
        name = "National Plastics — Maidstone"
    email, phone = _NP_CONTACTS[name]
    return {"branch_name": name, "email": email, "phone": phone, "miles": None}


def _zest_branch(pc):
    """Nearest National Plastics branch (full network) for a Zest order → {branch_name, email,
    phone, miles} or None. Live geocoder (branch_finder); no offline fallback (branch list is large,
    so geocoding is required — a blank postcode just returns None and the order goes to review)."""
    if not (pc or "").strip():
        return None
    try:
        import branch_finder
        return branch_finder.zest_branch(pc)
    except Exception:  # noqa: BLE001
        return None


def hardie_route(pc, smooth=False):
    """Route a Hardie/Cladco line by delivery postcode (Daniela, 2026-09-13):
    ONLY UPB (in their own depot areas) and National Plastics (everywhere else, nearest of their 3
    branches). Squaredeal is a BACKUP only (kept for Smooth, which only they stock). Each supplier
    prices from its OWN list. Returns {supplier, branch, branch_email, branch_phone, reason, conf,
    quote}."""
    area = postcode_area(pc)
    # Smooth-finish Hardie: only Squaredeal stock Smooth boards → Squaredeal (our backup) whatever
    # the area. Everything else stays on UPB / National Plastics.
    if smooth:
        return {"supplier": "Squaredeal", "quote": True, "conf": "high",
                "reason": "Smooth finish — only Squaredeal stock Smooth (backup use)"}
    # UPB in their OWN depot areas (Newmarket / Ipswich / Aldridge).
    for depot, keys in (("UPB Newmarket", _UPB_NEWMARKET), ("UPB Ipswich", _UPB_IPSWICH),
                        ("UPB Aldridge", _UPB_ALDRIDGE)):
        if area in keys:
            return {"supplier": "UPB", "branch": depot, "branch_email": _UPB_DEPOT[depot],
                    "branch_phone": _UPB_DEPOT_PHONE.get(depot),
                    "reason": f"UPB own area — {depot} ({area})", "conf": "high"}
    # EVERYTHING outside a UPB area → National Plastics, nearest of the 3 branches by postcode.
    nb = _np_branch(pc)
    miles = f" ({nb['miles']} mi)" if nb.get("miles") is not None else ""
    return {"supplier": "National Plastics", "branch": nb["branch_name"],
            "branch_email": nb["email"], "branch_phone": nb["phone"],
            "reason": f"{area or 'no postcode'} outside UPB area → {nb['branch_name']}{miles}",
            "conf": "high" if area else "low"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def route_line(line, area_pc=None, sku_supplier=None):
    """Route a single line → {supplier, route, branch, branch_email, portal, quote, needs_branch,
    reason, conf}. `route` is the supplier label, or 'SAMPLES'/'CLEARANCE'/'PICK'. supplier is
    None for the in-house/PICK routes. `area_pc` is the order's delivery postcode (for Hardie).
    `sku_supplier(sku)` (optional) returns the sole supplier that prices a SKU in the feed — a
    fallback when the Shopify vendor is our house brand and reveals nothing."""
    title = line.get("title") or ""
    sku = (line.get("sku") or "").strip()
    vendor = line.get("vendor") or ""
    tags = _norm(" ".join(line.get("tags") or []))
    blob = _norm(title) + " " + _norm(vendor)

    def out(route, supplier, reason, conf, portal=False, quote=False, needs_branch=False,
            branch=None, branch_email=None, branch_phone=None):
        return {"route": route, "supplier": supplier, "reason": reason, "conf": conf,
                "portal": portal, "quote": quote, "needs_branch": needs_branch,
                "branch": branch, "branch_email": branch_email, "branch_phone": branch_phone}

    tl = title.lower()
    if "sample" in tl or sku.lower().startswith("sample"):
        return out("SAMPLES", None, "Sample — fulfil & post in-house", "high")
    if "clearance" in tl or sku.lower().startswith("clear"):
        return out("CLEARANCE", None, "Clearance stock we hold — in-house", "high")

    # Freefoam & Fortex → regional stockist by delivery postcode (Daniela 2026-10-02). Always a
    # QUOTE (packing slip, no prices yet). Unmapped area / no postcode → PICK (review).
    if "freefoam" in blob or "fortex" in blob:
        fr = freefoam_fortex_route(area_pc)
        sup = fr.get("supplier")
        if not sup:
            return out("PICK", None, fr["reason"], fr["conf"], quote=True)
        return out(sup, sup, fr["reason"], fr["conf"], quote=True,
                   branch=fr.get("branch"), branch_email=fr.get("branch_email"),
                   branch_phone=fr.get("branch_phone"))
    # Hardie / Cladco — UPB in their own areas, else National Plastics (nearest branch).
    if any(k in blob for k in ("hardie", "cladco")):
        hr = hardie_route(area_pc, smooth="smooth" in tl)
        return out(hr["supplier"], hr["supplier"], hr["reason"], hr["conf"],
                   quote=hr.get("quote", False), needs_branch=hr.get("needs_branch", False),
                   branch=hr.get("branch"), branch_email=hr.get("branch_email"),
                   branch_phone=hr.get("branch_phone"))
    # Zest wall/shower panels (tagged "Zest…") are sourced from National Plastics — to the customer's
    # NEAREST branch of the full NP network (Daniela 2026-09-16; check the tag so it OVERRIDES any
    # vendor below).
    if "zest" in tags or "zest" in blob:
        nb = _zest_branch(area_pc)
        if nb and nb.get("branch_name"):
            miles = f" ({nb['miles']} mi)" if nb.get("miles") is not None else ""
            return out("National Plastics", "National Plastics",
                       f"Zest → National Plastics — nearest branch {nb['branch_name']}{miles}",
                       "high", branch=nb["branch_name"], branch_email=nb["email"],
                       branch_phone=nb["phone"])
        return out("National Plastics", "National Plastics",
                   "Zest → National Plastics (branch by postcode)", "med")
    # Cedral (fibre-cement cladding) → quote from AJW Distribution until we get their pricelist
    # (Daniela, 2026-08-24). Tag/name check overrides whatever vendor it sits under.
    if "cedral" in tags or "cedral" in blob:
        return out("AJW", "AJW", "Cedral → AJW Distribution for a quote (no pricelist yet)",
                   "high", quote=True, branch_email="kevin.addison@ajwdistribution.co.uk")
    # Shopify VENDOR is the authoritative router for everything else — check it FIRST, so a
    # Storm polycarbonate (vendor "Storm") or a Toolbank tool never gets grabbed by a brand/SKU
    # rule below.
    lbl = CANON.get(_norm(vendor))
    if lbl in EXCLUDED_SUPPLIERS:        # not buying from them — don't route here, fall through
        lbl = None
    # Storm is too expensive right now, so Storm products go to MOLAN for a quote instead (Molan
    # quote them well). EXCEPT Triton decking/cladding, which only Storm do — those quote from
    # Storm. Temporary redirect — remove this block to route all Storm to Storm again.
    if lbl == "Storm":
        if "triton" in blob:
            return out("Storm", "Storm", f"Triton ({vendor}) — Storm-only, quote from Storm",
                       "med", quote=True, branch_email="sales@stormbuildingproducts.com")
        return out("Molan", "Molan", f"Storm (vendor “{vendor}”) → Molan for a quote — Storm too "
                   "expensive; Molan quote nicely", "med", quote=True,
                   branch_email="quotes@molan-uk.com")
    if lbl:
        return out(lbl, lbl, f"Shopify vendor “{vendor}” → {lbl}", "high",
                   portal=(lbl in PORTAL), quote=(lbl in QUOTE_FIRST),
                   needs_branch=(lbl in NEEDS_BRANCH))

    # Fallbacks ONLY when the vendor didn't resolve:
    # Pricing feed: a house-brand line (vendor "Trade Superstore Online") carries no supplier, but
    # if the feed prices this SKU from exactly ONE supplier, that IS its supplier — evidence, not a
    # guess (e.g. window handle WEH5460-40RST is priced only by Eurocell).
    if sku_supplier and sku:
        fs = sku_supplier(sku)
        if fs:
            return out(fs, fs, f"Only {fs} prices SKU {sku} in the feed → {fs}", "med",
                       portal=(fs in PORTAL), quote=(fs in QUOTE_FIRST),
                       needs_branch=(fs in NEEDS_BRANCH))
    if any(k in blob for k in ("polycarbonate", "multiwall", "twinwall", "ezglaze",
                               "solidpolycarbonate")):
        return out("Molan", "Molan", "Polycarbonate (no known vendor) — Molan", "med")
    if re.fullmatch(r"\d{5,6}", sku):
        return out("Travis Perkins", "Travis Perkins",
                   "No known vendor; numeric catalogue SKU → Travis Perkins (nearest branch)",
                   "med", portal=True, needs_branch=True)

    return out("PICK", None, f"Couldn't route (vendor “{vendor or '?'}”) — pick a supplier", "low")


def _stage_for(supplier, route, quote, portal):
    if route in IN_HOUSE or route == "PICK":
        return "Needs Review"
    if quote:
        return "Needs Quote"
    if portal:
        return "Go To Portal"
    return "Needs Review"


# Auto-advance an order straight to "SEND PO" (so Monday's automation emails the supplier) WITHOUT
# a human review — but only for clear, single-supplier, high-confidence Shopify-vendor matches.
# Daniela's exclusions (2026-09-28), which stay in "Needs Review" for Natasha to check: UPB,
# National Plastics, and the Hardie / Freefoam / Fortex / Zest products that route to them (branch/
# area nuance); mixed (split) orders; and anything needing a quote, a portal or a branch decision.
# Flip AUTO_SEND_PO to False to turn the whole thing off (everything reverts to Needs Review).
AUTO_SEND_PO = True
PO_AUTOSEND_EXCLUDE_SUPPLIERS = {"upb", "nationalplastics", "travisperkins", "wallsandfloors"}
PO_AUTOSEND_EXCLUDE_WORDS = ("hardie", "freefoam", "fortex", "zest")


def _po_autosend_ok(result):
    """True only when this order is safe to auto-send: single supplier, real PO route (not quote/
    portal/in-house/PICK), high confidence, branch resolved, and not one of the excluded
    suppliers/products above."""
    if not AUTO_SEND_PO or not result or result.get("split"):
        return False
    if result.get("route") in IN_HOUSE or result.get("route") == "PICK":
        return False
    if result.get("stage") in ("Needs Quote", "Go To Portal"):
        return False
    if result.get("conf") != "high" or result.get("needs_branch"):
        return False
    if _norm(result.get("overall_supplier") or "") in PO_AUTOSEND_EXCLUDE_SUPPLIERS:
        return False
    for l in result.get("lines") or []:
        blob = _norm((l.get("title") or "") + " " + (l.get("vendor") or "")) \
            + " " + _norm(" ".join(l.get("tags") or []))
        if any(w in blob for w in PO_AUTOSEND_EXCLUDE_WORDS):
            return False
    return True


def route_order(lines, postcode=None, sku_supplier=None):
    """Route a whole order → {split, groups, overall_supplier, branch, branch_email, stage,
    needs_branch, conf, lines}. `groups` maps each distinct route → its lines (for a split).
    `overall_supplier`/`branch` are set only when the whole order routes to ONE supplier.
    `sku_supplier` is an optional feed-based supplier resolver (see route_line)."""
    routed = []
    for ln in (lines or []):
        r = route_line(ln, area_pc=postcode, sku_supplier=sku_supplier)
        routed.append({**ln, **r})

    routes = [r["route"] for r in routed]
    distinct = list(dict.fromkeys(routes))
    groups = {rt: [r for r in routed if r["route"] == rt] for rt in distinct}
    conf_order = {"low": 0, "med": 1, "high": 2}
    conf = min((r["conf"] for r in routed), key=lambda c: conf_order[c], default="low")

    # A PICK (unrouteable) line must NEVER trigger an automatic split. That would restructure the
    # Shopify fulfilment for what is usually really a single-supplier order whose extra line is just
    # tagged with our house-brand vendor "Trade Superstore Online" (e.g. an Ogee MDF architrave that
    # belongs with its National Skirting skirting board). If anything can't be routed, hand the WHOLE
    # order to the processor to assign — no split, no auto-supplier, no guess.
    if "PICK" in distinct:
        return {"split": False, "groups": groups, "overall_supplier": None, "branch": None,
                "branch_email": None, "route": "PICK", "stage": "Needs Review",
                "needs_branch": any(r["needs_branch"] for r in routed), "conf": conf,
                "lines": routed}

    split = len(distinct) > 1
    if not split and distinct:
        r0 = routed[0]
        result = {"split": False, "groups": groups, "overall_supplier": r0["supplier"],
                  "branch": r0.get("branch"), "branch_email": r0.get("branch_email"),
                  "branch_phone": r0.get("branch_phone"),
                  "route": r0["route"], "stage": _stage_for(r0["supplier"], r0["route"],
                                                            r0["quote"], r0["portal"]),
                  "needs_branch": any(r["needs_branch"] for r in routed), "conf": conf,
                  "lines": routed}
        # Eurocell / Travis Perkins: fill the nearest physical branch + email from the postcode.
        if result["overall_supplier"] in ("Eurocell", "Travis Perkins") and postcode \
                and not result.get("branch"):
            try:
                import branch_finder
                nb = branch_finder.nearest_branch(postcode, result["overall_supplier"])
                if nb and nb.get("branch_name"):
                    result["branch"] = nb["branch_name"]
                    result["branch_email"] = nb.get("email")
                    result["branch_phone"] = nb.get("phone")
                    result["needs_branch"] = False
                    for l in routed:
                        if l.get("supplier") == result["overall_supplier"]:
                            l["reason"] = (l["reason"] + f" → nearest branch "
                                           f"{nb['branch_name']} ({nb['miles']} mi)")
            except Exception:  # noqa: BLE001
                pass
        # Clear, high-confidence single-supplier match (bar the excluded ones) → skip the human
        # review and go straight to SEND PO, so Monday's automation emails the supplier.
        if _po_autosend_ok(result):
            result["stage"] = "SEND PO"
        return result
    return {"split": split, "groups": groups, "overall_supplier": None, "branch": None,
            "branch_email": None, "route": None, "stage": "Needs Review",
            "needs_branch": any(r["needs_branch"] for r in routed), "conf": conf, "lines": routed}


def summary(res):
    """One-line label for the grid's 'Suggested' column."""
    if not res.get("lines"):
        return ""
    if res.get("split"):
        return "SPLIT: " + " + ".join(res["groups"].keys())
    return res.get("route") or "PICK"
