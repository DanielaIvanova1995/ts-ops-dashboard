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
    "travisperkins": "Travis Perkins", "gap": "GAP", "huwsgray": "Huws Gray",
    "nationalskirting": "National Skirting", "molan": "Molan", "storm": "Storm",
    "pjh": "PJH", "nuie": "Nuie", "roxor": "Nuie", "decor8": "Decor8", "paintersworld": "Decor8",
    "rexel": "Rexel", "toolbank": "Toolbank", "lpd": "LPD DOORS", "lpddoors": "LPD DOORS",
    "jbkind": "JB Kind", "deanta": "Deanta", "carron": "Carron", "hurlingham": "Hurlingham",
    "chasehardware": "Chase Hardware", "wallsandfloors": "Walls and Floors",
    "splendour": "Walls and Floors", "velux": "Velux", "dolle": "Dolle", "mbdecor": "MB Decor",
    "mbdiy": "MB Decor", "permaroof": "Permaroof", "newplas": "newplas", "bricklink": "Bricklink",
    "brickservices": "Brickservices", "plastivan": "Plastivan", "brundle": "Brundle",
    "vista": "Vista", "etills": "Etills", "evolve": "Evolve", "ctie": "C TIE",
    # brand locks
    "jameshardie": "UPB", "hardie": "UPB", "freefoam": "UPB", "fortex": "UPB", "cladco": "UPB",
}

PORTAL = {"PJH", "Toolbank", "Velux", "MB Decor", "Nuie", "National Skirting"}
QUOTE_FIRST = {"Huws Gray", "Etills", "Bricklink", "Brickservices"}
NEEDS_BRANCH = {"UPB", "Travis Perkins", "Eurocell", "NBP"}
IN_HOUSE = {"SAMPLES", "CLEARANCE"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def route_line(line):
    """Route a single line → {supplier, route, portal, quote, needs_branch, reason, conf}.
    `route` is the supplier label, or 'SAMPLES'/'CLEARANCE'/'PICK'. supplier is None for the
    in-house/PICK routes."""
    title = line.get("title") or ""
    sku = (line.get("sku") or "").strip()
    vendor = line.get("vendor") or ""
    blob = _norm(title) + " " + _norm(vendor)

    def out(route, supplier, reason, conf, portal=False, quote=False, needs_branch=False):
        return {"route": route, "supplier": supplier, "reason": reason, "conf": conf,
                "portal": portal, "quote": quote, "needs_branch": needs_branch}

    tl = title.lower()
    if "sample" in tl or sku.lower().startswith("sample"):
        return out("SAMPLES", None, "Sample — fulfil & post in-house", "high")
    if "clearance" in tl or sku.lower().startswith("clear"):
        return out("CLEARANCE", None, "Clearance stock we hold — in-house", "high")

    # Brand keyword locks (title or vendor).
    if "hardie" in blob:
        return out("UPB", "UPB", "James Hardie → UPB first (confirm area / Smooth / Scotland)",
                   "med", needs_branch=True)
    if "freefoam" in blob or "fortex" in blob:
        return out("UPB", "UPB", "Freefoam/Fortex → UPB if in area, else NBP (never Squaredeal)",
                   "med", needs_branch=True)
    if "cladco" in blob:
        return out("UPB", "UPB", "Cladco via UPB", "med", needs_branch=True)
    if any(k in blob for k in ("polycarbonate", "multiwall", "ezglaze", "solidpolycarbonate")):
        return out("Molan", "Molan", "Polycarbonate — Molan brand lock", "high")

    # Numeric catalogue SKU → Travis Perkins.
    if re.fullmatch(r"\d{5,6}", sku):
        return out("Travis Perkins", "Travis Perkins",
                   "Numeric catalogue SKU → Travis Perkins (nearest branch)", "med",
                   portal=True, needs_branch=True)

    # Shopify vendor → supplier.
    lbl = CANON.get(_norm(vendor))
    if lbl:
        return out(lbl, lbl, f"Shopify vendor “{vendor}” → {lbl}", "high",
                   portal=(lbl in PORTAL), quote=(lbl in QUOTE_FIRST),
                   needs_branch=(lbl in NEEDS_BRANCH))

    return out("PICK", None, f"Couldn't route (vendor “{vendor or '?'}”) — pick a supplier", "low")


def _stage_for(supplier, route, quote, portal):
    if route in IN_HOUSE or route == "PICK":
        return "Needs Review"
    if quote:
        return "Needs Quote"
    if portal:
        return "Go To Portal"
    return "Needs Review"


def route_order(lines):
    """Route a whole order → {split, groups, overall_supplier, stage, needs_branch, conf, lines}.
    `groups` maps each distinct route → its lines (for a split). `overall_supplier` is set only
    when the whole order routes to ONE supplier."""
    routed = []
    for ln in (lines or []):
        r = route_line(ln)
        routed.append({**ln, **r})

    routes = [r["route"] for r in routed]
    distinct = list(dict.fromkeys(routes))
    groups = {rt: [r for r in routed if r["route"] == rt] for rt in distinct}
    split = len(distinct) > 1
    conf_order = {"low": 0, "med": 1, "high": 2}
    conf = min((r["conf"] for r in routed), key=lambda c: conf_order[c], default="low")

    if not split and distinct:
        r0 = routed[0]
        return {"split": False, "groups": groups, "overall_supplier": r0["supplier"],
                "route": r0["route"], "stage": _stage_for(r0["supplier"], r0["route"],
                                                           r0["quote"], r0["portal"]),
                "needs_branch": any(r["needs_branch"] for r in routed), "conf": conf,
                "lines": routed}
    return {"split": split, "groups": groups, "overall_supplier": None, "route": None,
            "stage": "Needs Review", "needs_branch": any(r["needs_branch"] for r in routed),
            "conf": conf, "lines": routed}


def summary(res):
    """One-line label for the grid's 'Suggested' column."""
    if not res.get("lines"):
        return ""
    if res.get("split"):
        return "SPLIT: " + " + ".join(res["groups"].keys())
    return res.get("route") or "PICK"
