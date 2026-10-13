"""Quote maths — Streamlit-free, shared by the API (and later the app). Material take-offs per
product range (Cedral first) + the Discount Desk floor. No I/O here: callers pass dimensions and get
back the raw priced-nothing line list + caveats; the API then matches each line to a Shopify variant
and prices it (Cedral costs come ONLY from AJW — a supplier's price is never crossed with another's).

Lifted verbatim from app.py so the new web app quotes identically to the live app.
"""
from __future__ import annotations

import math
import re

# ---- Cedral ----------------------------------------------------------------------------------
CEDRAL_COLOURS = [
    "White", "Vanilla White", "Clay Brown", "Platinum Grey", "Chalk White", "Sky Blue",
    "Steel Grey", "Slate Grey", "Walnut Brown", "Black", "Silver Grey", "Pearl Grey",
    "Pewter Grey", "Sand Yellow", "Brick Red", "Ocean Blue", "Basalt Grey", "Metal Green",
    "Tea Green", "Pebble Grey", "Cocoa Brown",
]
_COLOUR_FAMILY = {"grey", "gray", "green", "blue", "brown", "white", "black", "red", "yellow",
                  "cream", "taupe", "mist", "slate"}


def resolve_clad_colour(stated, palette):
    """Map a stated colour to a REAL palette colour so a quote never silently defaults to the wrong
    one. Returns (colour, how): 'exact' | 'fuzzy' | 'unrecognised' | 'none'."""
    s = (stated or "").strip().lower()
    if not s:
        return None, "none"
    for c in palette:
        if c.lower() in s:
            return c, "exact"
    sw = set(re.findall(r"[a-z]+", s))
    best, score = None, 0
    for c in palette:
        shared = sw & set(re.findall(r"[a-z]+", c.lower()))
        if len(shared) > score:
            best, score = c, len(shared)
    if best and score >= 1:
        return best, "fuzzy"
    return None, "unrecognised"


def cedral_takeoff(clad):
    """Cedral fibre-cement cladding take-off. Boards (Cedral Lap ~0.53 m²/board, or Cedral Click
    ~0.60) + corner profiles + start/base profile + optional battens/fixings. Sizes every accessory
    from the counts/dimensions given or from sensible assumptions, each flagged. Returns
    (raw_lines, caveats) where each line = {description, qty, search}."""
    prod_l = (clad.get("product") or "").lower()
    is_click = "click" in prod_l
    product = "Cedral Click" if is_click else "Cedral Lap"
    cov = 0.60 if is_click else 0.53
    gross = clad.get("gross_area_m2") or 0
    openings = clad.get("openings_m2") or 0
    net = max(0.0, gross - openings)
    if net <= 0:
        return None, None
    colour_in = (clad.get("colour") or "").strip()
    colour, _chow = resolve_clad_colour(colour_in, CEDRAL_COLOURS)
    colour = colour or ""
    cav = []

    boards = math.ceil(net / cov * 1.10)     # +10% waste
    raw = [{"description": f"{product} cladding board" + (f" — {colour}" if colour else ""),
            "qty": boards, "search": f"{product} Plank {colour}".strip()}]
    cav.append(f"Boards: {net:.1f} m² to clad ({gross:.1f} m² less {openings:.1f} m² openings) ÷ "
               f"{cov} m²/board + 10% waste = {boards} {product} boards.")
    if not colour_in:
        cav.append("Colour/finish not confirmed — please confirm which Cedral colour you'd like.")
    elif _chow == "fuzzy":
        cav.append(f"Quoted in Cedral {colour} as the closest match to '{colour_in}' — please "
                   "confirm the exact colour.")
    elif _chow == "unrecognised":
        cav.append(f"'{colour_in}' isn't a Cedral colour we recognise — please confirm the exact "
                   "colour (we have NOT defaulted it).")

    height = clad.get("wall_height_m") or 0
    width = clad.get("total_width_m") or 0
    if not height and width:
        height = net / width if width else 0
    if not height:
        height = 2.4
        cav.append(f"Assumed a cladding height of {height:.1f} m (not stated) to size the trims — "
                   "confirm the run height and we'll refine.")
    if not width:
        width = net / height if height else 0
        cav.append(f"Assumed ~{width:.1f} m total run width (area ÷ height) to size the "
                   "starter/corner trims — confirm the elevation widths and we'll refine.")

    def L3(lm):                              # Cedral trims come in 3 m lengths, round up
        return max(1, math.ceil(lm / 3.0))

    if clad.get("wants_trims"):
        ext = clad.get("external_corners")
        if ext is None:
            ext = 4
            cav.append("Assumed 4 external corners (not confirmed) — tell us the exact number and "
                       "we'll adjust.")
        if ext:
            raw.append({"description": f"{product} external corner profile ({ext} × {height:.1f} m)",
                        "qty": L3(ext * height),
                        "search": f"{product} Plank External Corner {colour}".strip()})
        intc = clad.get("internal_corners") or 0
        if intc:
            raw.append({"description": f"{product} internal corner profile ({intc} × {height:.1f} m)",
                        "qty": L3(intc * height),
                        "search": f"{product} Plank Internal Corner {colour}".strip()})
        raw.append({"description": f"{product} start / base profile", "qty": L3(width),
                    "search": f"{product} Plank Start Profile {colour}".strip()})
        nwin = clad.get("num_windows")
        if nwin is None and openings > 0:
            nwin = max(1, round(openings / 1.5))
        if nwin:
            cav.append(f"{nwin} window/door opening(s) noted — Cedral reveal/sill trims (start, "
                       "connection or end profiles) depend on the detailing, so send the opening "
                       "sizes and finish and we'll add the right reveal trims.")
        cav.append("Trim pack sized from the corners and run width above (Cedral profiles come in "
                   "3 m lengths, rounded up). Send exact elevation widths / corner counts to tighten it.")

    batten_lm = net / 0.6
    if clad.get("wants_battens"):
        raw.append({"description": "Treated timber battens (25×50, per 3 m length)",
                    "qty": max(1, math.ceil(batten_lm / 3.0)),
                    "search": "treated timber batten 25 x 50"})
    if clad.get("wants_screws"):
        raw.append({"description": "Cedral facade fixings (screws / rivets)",
                    "qty": max(1, math.ceil(boards * 8 / 250)),
                    "search": f"Cedral fixing screws {colour}".strip()})
    return raw, cav


# ---- Discount Desk ---------------------------------------------------------------------------
SHOPIFY_FEE = 0.018
ABANDONED_CART_PCT = 0.04   # every customer already gets 4% off via the abandoned-cart email
_DISCOUNT_BANDS = [
    (1500,         0.15, "Under £1.5k"),
    (5000,         0.25, "£1.5k–£5k"),
    (15000,        0.40, "£5k–£15k"),
    (float("inf"), 0.60, "Over £15k"),
]
_DISCOUNT_FLOOR_MIN = 0.08   # never quote below this margin, however big the order


def discount_floor(order_value, margin):
    """Given the ex-VAT order value and its gross margin, return the discount floor:
    {give, band, floor_margin (after fee), margin_now (after fee), floor_price, max_disc, no_room,
    four_pc_price, four_breaches}. floor_price is the lowest we may quote."""
    give, band = next((g, lbl) for cap, g, lbl in _DISCOUNT_BANDS if order_value < cap)
    cost = order_value * (1 - margin)
    floor_margin_gross = max(_DISCOUNT_FLOOR_MIN, margin * (1 - give))
    floor_price = cost / (1 - floor_margin_gross) if floor_margin_gross < 1 else order_value
    max_disc = max(0.0, order_value - floor_price)
    no_room = margin <= floor_margin_gross or max_disc <= 0
    eff_floor = order_value if no_room else floor_price
    four_pc_price = round(order_value * (1 - ABANDONED_CART_PCT), 2)
    return {"give": give, "band": band,
            "floor_margin": floor_margin_gross - SHOPIFY_FEE,
            "margin_now": margin - SHOPIFY_FEE,
            "floor_price": eff_floor,
            "max_disc": 0.0 if no_room else max_disc,
            "no_room": no_room,
            "four_pc_price": four_pc_price,
            "four_breaches": four_pc_price < eff_floor}
