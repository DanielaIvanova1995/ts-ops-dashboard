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
    "mbdiy": "MB Decor", "permaroof": "Permaroof", "newplas": "newplas", "bricklink": "Bricklink",
    "brickservices": "Brickservices", "plastivan": "Plastivan", "brundle": "Brundle",
    "vista": "Vista", "etills": "Etills", "evolve": "Evolve", "ctie": "C TIE",
    # brand locks
    "jameshardie": "UPB", "hardie": "UPB", "freefoam": "UPB", "fortex": "UPB", "cladco": "UPB",
}

PORTAL = {"PJH", "Toolbank", "Velux", "MB Decor", "Nuie", "National Skirting", "Rexel"}
QUOTE_FIRST = {"Huws Gray", "Etills", "Bricklink", "Brickservices"}
NEEDS_BRANCH = {"Travis Perkins", "Eurocell"}    # nearest physical branch — needs the locator
IN_HOUSE = {"SAMPLES", "CLEARANCE"}

# ---- James Hardie / Freefoam / Fortex / Cladco postcode routing (Aug 2026 map, avoid NBP) ----
# Postcode AREAS (the leading letters of a postcode) → who supplies.
_SCOTLAND = {"AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML", "PA", "PH",
             "TD", "ZE"}
_UPB_NEWMARKET = {"PE", "CB", "SG", "NN", "MK", "EN"}
_UPB_IPSWICH = {"NR", "IP", "CO", "SS", "OX", "HP", "AL", "LU", "RG", "SL", "RH", "GU", "BN",
                "TN", "ME", "CT", "IG"}
_UPB_ALDRIDGE = {"YO", "BD", "HG", "PR", "BB", "HD", "LS", "WF", "HU", "L", "WN", "OL", "HX",
                 "WA", "M", "SK", "CH", "CW", "ST", "DE", "NG", "S", "LN", "LE", "TF", "WS",
                 "B", "WV", "DY", "CV", "LA", "CA"}    # LA=Lancaster, CA=Carlisle (NW, nearest Aldridge)
_SQUAREDEAL = {"TR", "PL", "TQ", "EX", "TA", "DT", "BH", "BA", "BS", "SP", "SO", "PO", "SN",
               "GL", "DA", "BR", "CR", "KT", "SM", "CM", "N", "NW", "E", "EC", "SE", "SW", "W",
               "WC", "RM", "TW", "UB", "HA", "WD", "NP", "CF",
               "OX", "RG", "GU", "RH", "BN", "TN", "ME", "CT", "IG", "SS", "SL", "HP", "LU",
               "AL", "SG", "MK", "EN",
               "SA", "SY", "LD"}    # southern NBP-excluded patch → Squaredeal (quote first)
_UPB_DEPOT = {"UPB Newmarket": "callumpainter@upbuildingproducts.com",
              "UPB Ipswich": "ipswich@upbuildingproducts.co.uk",
              "UPB Aldridge": "martinmelaney@upbuildingproducts.com"}


def postcode_area(pc):
    m = re.match(r"\s*([A-Za-z]{1,2})", pc or "")
    return m.group(1).upper() if m else ""


def hardie_route(pc, smooth=False):
    """Route a Hardie/Freefoam/Fortex/Cladco line by delivery postcode (avoiding NBP). Returns
    {supplier, branch, branch_email, reason, conf, quote, needs_branch}."""
    area = postcode_area(pc)
    note = (" — SMOOTH finish: confirm UPB stock, else Squaredeal always have Smooth"
            if smooth else "")
    if not area:
        return {"supplier": "UPB", "reason": "Hardie/Freefoam — no postcode to route on; "
                "confirm branch" + note, "needs_branch": True, "conf": "low"}
    if area in _SCOTLAND:
        return {"supplier": "Bricklink", "reason": f"Scotland ({area}) → Bricklink (quote first)"
                + note, "quote": True, "conf": "med"}
    for depot, keys in (("UPB Newmarket", _UPB_NEWMARKET), ("UPB Ipswich", _UPB_IPSWICH),
                        ("UPB Aldridge", _UPB_ALDRIDGE)):
        if area in keys:
            return {"supplier": "UPB", "branch": depot, "branch_email": _UPB_DEPOT[depot],
                    "reason": f"{depot} ({area})" + note, "conf": "high"}
    if area in _SQUAREDEAL:
        return {"supplier": "Squaredeal", "reason": f"Squaredeal south ({area}) — quote first"
                + note, "quote": True, "conf": "med"}
    return {"supplier": "UPB", "reason": f"Postcode {area} not on the Hardie map — try "
            "UPB/Squaredeal/Bricklink, confirm" + note, "needs_branch": True, "conf": "low"}


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
    blob = _norm(title) + " " + _norm(vendor)

    def out(route, supplier, reason, conf, portal=False, quote=False, needs_branch=False,
            branch=None, branch_email=None):
        return {"route": route, "supplier": supplier, "reason": reason, "conf": conf,
                "portal": portal, "quote": quote, "needs_branch": needs_branch,
                "branch": branch, "branch_email": branch_email}

    tl = title.lower()
    if "sample" in tl or sku.lower().startswith("sample"):
        return out("SAMPLES", None, "Sample — fulfil & post in-house", "high")
    if "clearance" in tl or sku.lower().startswith("clear"):
        return out("CLEARANCE", None, "Clearance stock we hold — in-house", "high")

    # Hardie / Freefoam / Fortex / Cladco — route by the delivery postcode (Aug 2026 map).
    if any(k in blob for k in ("hardie", "freefoam", "fortex", "cladco")):
        hr = hardie_route(area_pc, smooth="smooth" in tl)
        return out(hr["supplier"], hr["supplier"], hr["reason"], hr["conf"],
                   quote=hr.get("quote", False), needs_branch=hr.get("needs_branch", False),
                   branch=hr.get("branch"), branch_email=hr.get("branch_email"))
    # Shopify VENDOR is the authoritative router for everything else — check it FIRST, so a
    # Storm polycarbonate (vendor "Storm") or a Toolbank tool never gets grabbed by a brand/SKU
    # rule below.
    lbl = CANON.get(_norm(vendor))
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
