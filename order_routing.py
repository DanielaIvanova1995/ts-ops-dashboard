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
    "nationalplastics": "National Plastics",   # distinct from NBP
    "ajw": "AJW", "ajwdistribution": "AJW",     # AJW Distribution — Cedral quotes
    # brand locks
    "jameshardie": "UPB", "hardie": "UPB", "freefoam": "UPB", "fortex": "UPB", "cladco": "UPB",
}

PORTAL = {"PJH", "Toolbank", "Velux", "MB Decor", "Nuie", "National Skirting", "Rexel"}
QUOTE_FIRST = {"Huws Gray", "Etills", "Bricklink", "Brickservices", "AJW"}
NEEDS_BRANCH = {"Travis Perkins", "Eurocell"}    # nearest physical branch — needs the locator
IN_HOUSE = {"SAMPLES", "CLEARANCE"}
# Suppliers we're NOT buying from right now — never route to them or count their feed prices (kept
# on file with all their rules; just remove from this set to switch them back on). NBP paused.
EXCLUDED_SUPPLIERS = {"NBP"}

# ---- James Hardie / Freefoam / Fortex / Cladco postcode routing (Aug 2026 map, avoid NBP) ----
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
_UPB_DEPOT = {"UPB Newmarket": "callumpainter@upbuildingproducts.co.uk",
              "UPB Ipswich": "ipswich@upbuildingproducts.co.uk",
              "UPB Aldridge": "martinmelaney@upbuildingproducts.com"}
_UPB_DEPOT_PHONE = {"UPB Newmarket": "01638501927"}   # Ipswich / Aldridge TBC


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


def hardie_route(pc, smooth=False):
    """Route a Hardie/Freefoam/Fortex/Cladco line by delivery postcode (definitive Aug 2026 map).
    Each supplier prices from its OWN list. Returns {supplier, branch, branch_email, branch_phone,
    reason, conf, quote}."""
    area = postcode_area(pc)
    # Smooth-finish Hardie: Squaredeal always hold Smooth boards → route there whatever the area.
    if smooth:
        return {"supplier": "Squaredeal", "reason": "Smooth finish — Squaredeal always supply Smooth",
                "quote": True, "conf": "high"}
    if not area:
        return {"supplier": "National Plastics", "reason": "Hardie — no postcode; National Plastics "
                "do Hardie nationwide", "conf": "low"}
    if area in _SCOTLAND:
        return {"supplier": "Bricklink", "reason": f"Scotland ({area}) → Bricklink (quote; free "
                "collection, Glasgow)", "quote": True, "conf": "high"}
    for depot, keys in (("UPB Newmarket", _UPB_NEWMARKET), ("UPB Ipswich", _UPB_IPSWICH),
                        ("UPB Aldridge", _UPB_ALDRIDGE)):
        if area in keys:
            return {"supplier": "UPB", "branch": depot, "branch_email": _UPB_DEPOT[depot],
                    "branch_phone": _UPB_DEPOT_PHONE.get(depot),
                    "reason": f"{depot} ({area})", "conf": "high"}
    if area in _NP_NORTH:
        return {"supplier": "National Plastics",
                "reason": f"{area} (north of the Aldridge line) → National Plastics", "conf": "high"}
    if area in _SQUAREDEAL:
        return {"supplier": "Squaredeal", "reason": f"Squaredeal ({area}) — south/Wales, quote first",
                "quote": True, "conf": "high"}
    return {"supplier": "National Plastics", "reason": f"{area} not on the Hardie map → National "
            "Plastics (nationwide)", "conf": "med"}


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

    # Hardie / Freefoam / Fortex / Cladco — route by the delivery postcode (Aug 2026 map).
    if any(k in blob for k in ("hardie", "freefoam", "fortex", "cladco")):
        hr = hardie_route(area_pc, smooth="smooth" in tl)
        return out(hr["supplier"], hr["supplier"], hr["reason"], hr["conf"],
                   quote=hr.get("quote", False), needs_branch=hr.get("needs_branch", False),
                   branch=hr.get("branch"), branch_email=hr.get("branch_email"),
                   branch_phone=hr.get("branch_phone"))
    # Zest wall/shower panels (tagged "Zest…", currently vendor UPB) are now sourced from National
    # Plastics (Daniela, 2026-08-24) — check the tag so it OVERRIDES the UPB vendor below.
    if "zest" in tags or "zest" in blob:
        return out("National Plastics", "National Plastics",
                   "Zest panel → National Plastics", "high")
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
