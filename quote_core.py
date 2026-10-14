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


def _clad_boards(clad, cov, openings, cav):
    """Resolve the board count for a cladding take-off from ANY of three inputs: a number of boards,
    a gross m² area, or height × width. `input_mode` picks which ("boards" | "hw" | "area", default
    area). Returns (boards, net_m2, gross_m2, mode), or (None, 0, 0, mode) when the inputs don't give
    a positive quantity. Appends a note when height × width was used to work the area out."""
    mode = (clad.get("input_mode") or "area").lower()
    height = clad.get("wall_height_m") or 0
    width = clad.get("total_width_m") or 0
    if mode == "boards":
        boards = int(clad.get("board_count") or 0)
        if boards <= 0:
            return None, 0, 0, mode
        net = boards * cov / 1.10          # back out an approx net area (for battens/trim sizing)
        return boards, net, net + openings, mode
    if mode == "hw":
        gross = (height * width) if (height and width) else 0
        if gross > 0:
            cav.append(f"Area worked out from {height:.1f} m high × {width:.1f} m wide = {gross:.1f} m².")
    else:
        gross = clad.get("gross_area_m2") or 0
    net = max(0.0, gross - openings)
    if net <= 0:
        return None, 0, 0, mode
    boards = math.ceil(net / cov * 1.10)   # +10% waste
    return boards, net, gross, mode


def cedral_takeoff(clad):
    """Cedral fibre-cement cladding take-off. Boards (Cedral Lap ~0.53 m²/board, or Cedral Click
    ~0.60) + corner profiles + start/base profile + optional battens/fixings. Sizes every accessory
    from the counts/dimensions given or from sensible assumptions, each flagged. Returns
    (raw_lines, caveats) where each line = {description, qty, search}."""
    prod_l = (clad.get("product") or "").lower()
    is_click = "click" in prod_l
    product = "Cedral Click" if is_click else "Cedral Lap"
    cov = 0.60 if is_click else 0.53
    openings = clad.get("openings_m2") or 0
    cav = []
    boards, net, gross, mode = _clad_boards(clad, cov, openings, cav)
    if boards is None:
        return None, None
    colour_in = (clad.get("colour") or "").strip()
    colour, _chow = resolve_clad_colour(colour_in, CEDRAL_COLOURS)
    colour = colour or ""

    raw = [{"description": f"{product} cladding board" + (f" — {colour}" if colour else ""),
            "qty": boards, "search": f"{product} Plank {colour}".strip()}]
    if mode == "boards":
        cav.append(f"Quoting the {boards} {product} board(s) you specified (~{net:.1f} m²).")
    else:
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


# ---- James Hardie ----------------------------------------------------------------------------
HARDIE_COLOURS = [
    "Anthracite Grey", "Arctic White", "Boothbay Blue", "Chestnut Brown", "Cobble Stone",
    "Evening Blue", "Grey Slate", "Heathered Moss", "Iron Grey", "Khaki Brown", "Light Mist",
    "Midnight Black", "Monterey Taupe", "Mountain Sage", "Pearl Grey", "Rich Espresso",
    "Sail Cloth", "Soft Green", "Timber Bark", "Traditional Red", "Woodland Cream",
]


def hardie_takeoff(clad):
    """James Hardie cladding take-off (area-based): boards + starter/top/corner/window trims +
    battens + EPDM + screws + paint/edge seal. Two systems — LAP HardiePlank (0.54 m²/board) and
    the interlocking VL Plank (also called 'Click', 0.72 m²/board, its OWN trim set). Sizes every
    accessory from the counts/dimensions given or from sensible assumptions, each flagged. Returns
    (raw_lines, caveats) where each line = {description, qty, search}. Lifted verbatim from app.py."""
    _pl = (clad.get("product") or "").lower()
    is_vl = any(k in _pl for k in ("vl", "click", "interlock"))
    product = "Hardie VL Plank" if is_vl else "Hardie Plank"
    cov = 0.72 if is_vl else 0.54          # VL Plank ~0.72 m²/board; lap HardiePlank 0.54
    openings = clad.get("openings_m2") or 0
    cav = []
    boards, net, gross, mode = _clad_boards(clad, cov, openings, cav)
    if boards is None:
        return None, None
    colour_in = (clad.get("colour") or "").strip()
    colour, _chow = resolve_clad_colour(colour_in, HARDIE_COLOURS)   # map 'sage green' → the real
    colour = colour or ""                                            #   Hardie colour, never default

    board_desc = f"{product} cladding board" + (f" — {colour}" if colour else "")
    raw = [{"description": board_desc, "qty": boards,
            "search": f"{product} {colour}".strip()}]
    if mode == "boards":
        cav.append(f"Quoting the {boards} {product} board(s) you specified (~{net:.1f} m²).")
    else:
        cav.append(f"Boards: {net:.1f} m² to clad ({gross:.1f} m² less {openings:.1f} m² openings) "
                   f"÷ {cov} m²/board + 10% waste = {boards} boards.")
    if not colour_in:
        cav.append("Colour/finish not confirmed — please let us know which colour you'd like.")
    elif _chow == "fuzzy":
        cav.append(f"Quoted in James Hardie {colour} as the closest match to '{colour_in}' — "
                   "please confirm the exact colour.")
    elif _chow == "unrecognised":
        cav.append(f"'{colour_in}' isn't a James Hardie colour we recognise — please confirm the "
                   "exact colour (we have NOT defaulted it to a grey).")

    height = clad.get("wall_height_m") or 0
    width = clad.get("total_width_m") or 0
    if not height and width:
        height = net / width if width else 0
    if not height:
        height = 2.4
        cav.append(f"Assumed a cladding height of {height:.1f} m (not stated) to size the trims — "
                   "confirm the run height and we'll refine.")
    if not width:
        width = net / height
        cav.append(f"Assumed ~{width:.1f} m total run width (area ÷ height) to size the "
                   "starter/top trims — confirm the elevation widths and we'll refine.")

    def L3(lm):                            # trims come in 3 m lengths, round up
        return max(1, math.ceil(lm / 3.0))

    if clad.get("wants_trims") and is_vl:
        # VL Plank ("Click") interlocking trim pack — its own profiles, NOT the lap trims below.
        ext = clad.get("external_corners")
        if ext is None:
            ext = 4
            cav.append("Assumed 4 external corners (not confirmed) — tell us the exact number and "
                       "we'll adjust.")
        if ext:
            raw.append({"description": f"Hardie VL Plank 2-part corner profile "
                                       f"({ext} corners × {height:.1f} m)",
                        "qty": L3(ext * height),
                        "search": "Hardie VL Plank 2-part Corner Profile"})
        intc = clad.get("internal_corners") or 0
        if intc:
            raw.append({"description": f"Hardie VL Plank J profile — internal corners / abutments "
                                       f"({intc} × {height:.1f} m)",
                        "qty": L3(intc * height),
                        "search": "Hardie VL Plank J Profile"})
        raw.append({"description": "Hardie VL Plank starter profile", "qty": L3(width),
                    "search": "Hardie VL Plank Starter Profile"})
        nwin = clad.get("num_windows")
        if nwin is None and openings > 0:
            nwin = max(1, round(openings / 1.5))
            cav.append(f"Assumed {nwin} window/opening(s) to trim (from {openings:.1f} m² of "
                       "openings) — confirm the number/size and we'll refine.")
        if nwin:
            raw.append({"description": f"Hardie VL Plank window reveal trim ({nwin} opening(s))",
                        "qty": L3(nwin * 5.0),
                        "search": "Hardie VL Plank Window Reveal Trim"})
            raw.append({"description": f"Hardie VL Plank window head & vertical starter trim "
                                       f"({nwin} opening(s))",
                        "qty": L3(nwin * 2.0),
                        "search": "Hardie VL Plank Window Head Vertical Starter Trim"})
        cav.append("VL Plank (interlocking 'Click') trim pack — 2-part corner, J profile, starter "
                   "and window trims, sized from the corners / run width / openings (3 m lengths, "
                   "rounded up). Send exact elevations to tighten it.")
    elif clad.get("wants_trims"):
        ext = clad.get("external_corners")
        if ext is None:
            ext = 4
            cav.append("Assumed 4 external corner trims (not confirmed) — tell us the exact number "
                       "of external corners and we'll adjust.")
        if ext:
            raw.append({"description": f"{product} external corner trim"
                                       f"{(' — ' + colour) if colour else ''} "
                                       f"({ext} corners × {height:.1f} m)",
                        "qty": L3(ext * height),
                        "search": f"Hardie Plank external corner {colour}".strip()})
        intc = clad.get("internal_corners") or 0
        if intc:
            raw.append({"description": f"{product} internal corner trim"
                                       f"{(' — ' + colour) if colour else ''} "
                                       f"({intc} corners × {height:.1f} m)",
                        "qty": L3(intc * height),
                        "search": f"Hardie Plank internal corner {colour}".strip()})
        raw.append({"description": "James Hardie starter strip & ventilation profile",
                    "qty": L3(width),
                    "search": "Hardie Plank starter strip ventilation"})
        raw.append({"description": "James Hardie top ventilation strip", "qty": L3(width),
                    "search": "Hardie Plank top ventilation strip"})
        nwin = clad.get("num_windows")
        if nwin is None and openings > 0:
            nwin = max(1, round(openings / 1.5))
            cav.append(f"Assumed {nwin} window/opening(s) to trim (from {openings:.1f} m² of "
                       "openings) — confirm the number/size and we'll refine.")
        if nwin:
            raw.append({"description": f"HardieTrim NT3 window/door trim"
                                       f"{(' — ' + colour) if colour else ''} ({nwin} opening(s))",
                        "qty": L3(nwin * 5.0),
                        "search": f"James Hardie HardieTrim NT3 {colour}".strip()})
        cav.append("Trim pack sized from the corners, run width and openings above (all 3 m "
                   "lengths, rounded up). Send exact elevation widths / corner counts to tighten it.")

    batten_lm = net / 0.6
    if clad.get("wants_battens"):
        raw.append({"description": "Treated timber battens (25×50, per 3 m length)",
                    "qty": max(1, math.ceil(batten_lm / 3.0)),
                    "search": "treated timber batten 25 x 50"})
    if clad.get("wants_screws"):
        raw.append({"description": ("James Hardie VL coloured fixing screws (box of 250)" if is_vl
                                    else "James Hardie cladding screws (box of 250)"),
                    "qty": max(1, math.ceil(boards * 7 / 250)),
                    "search": ("Hardie VL Coloured Fixing Screws" if is_vl
                               else f"James Hardie cladding fixing screws {colour}".strip())})
    if clad.get("wants_epdm"):
        raw.append({"description": "EPDM joint tape (20 m roll)",
                    "qty": max(1, math.ceil(batten_lm / 20)),
                    "search": "James Hardie EPDM tape 20m"})
    if clad.get("wants_paint"):
        raw.append({"description": f"James Hardie touch-up paint"
                                   f"{(' — ' + colour) if colour else ''}",
                    "qty": 1, "search": f"James Hardie touch up paint {colour}".strip()})
        raw.append({"description": "James Hardie edge sealer (cut edges)", "qty": 1,
                    "search": "James Hardie edge sealer"})
        cav.append("Included 1 touch-up paint" + (f" in {colour}" if colour else "")
                   + " and 1 edge sealer for cut edges — tell us if you need more.")
    return raw, cav


# ---- Molan polycarbonate roof ----------------------------------------------------------------
# Brand-locked: polycarbonate is ALWAYS quoted as Molan products only (see QUOTE_BRAND_LOCKS).
POLY_SHEETS = {
    "10mm Twinwall": "Twinwall", "16mm Multiwall": "Multiwall", "25mm Multiwall": "Multiwall",
    "32mm Multiwall": "Multiwall", "35mm Multiwall": "Multiwall",
}
POLY_COLOURS = ["Clear", "Opal", "Bronze", "Heatguard Opal", "Bronze on Opal"]
POLY_WIDTHS = {"700 mm": 700, "1050 mm": 1050, "1200 mm": 1200, "2100 mm": 2100}
POLY_SYSTEMS = {
    "Self-Supported (16/35mm)": {"end": "Self Supported End Bar",
                                 "inter": "Self Supported Intermediate Bar",
                                 "wallplate": "Wallplate Assembly", "eaves": None},
    "Artisan": {"end": "Artisan Edge Bar + End Cap", "inter": "Artisan Intermediate Bar + End Cap",
                "wallplate": "Artisan Full Wallplate", "eaves": "Artisan Eaves Beam"},
}
POLY_BAR_LENGTHS = [2, 3, 4, 6]


def poly_takeoff(inp):
    """Polycarbonate roof dimensions + sheet/system choice -> Molan take-off lines. Each line carries
    a 'search' string matched against Molan products only. inp keys: width (m, front span), rake (m,
    slope length), sheet_width_mm, sheet_type (a POLY_SHEETS key), colour, system (a POLY_SYSTEMS
    key), bar_colour, include_acc (bool). Returns (lines, meta). Lifted verbatim from app.py."""
    width, rake = inp["width"], inp["rake"]
    sw_m = inp["sheet_width_mm"] / 1000.0
    sheets = math.ceil(width / sw_m) if (width and sw_m) else 0
    barlen = next((b for b in POLY_BAR_LENGTHS if b >= rake), 6) if rake else 0
    inter = max(0, sheets - 1)
    ends = 2 if sheets else 0
    sysd = POLY_SYSTEMS[inp["system"]]
    bc = inp["bar_colour"]
    kind = POLY_SHEETS[inp["sheet_type"]]
    thick = inp["sheet_type"].split("mm")[0] + "mm"
    colour = inp["colour"]
    pieces = lambda run, plen: math.ceil(run / plen) if run > 0 else 0  # noqa: E731
    lines = [
        ("sheet", f"{thick} {colour} {kind} sheet — {inp['sheet_width_mm']}mm × {rake:.1f}m",
         sheets, "sheet", f"{thick} {colour} {kind} Polycarbonate Sheet"),
        ("inter", f"{inp['system']} intermediate bar {bc} — {barlen}m", inter, "bar",
         f"{sysd['inter']} {bc} {barlen}m"),
        ("end", f"{inp['system']} end/edge bar {bc} — {barlen}m", ends, "bar",
         f"{sysd['end']} {bc} {barlen}m"),
        ("wallplate", f"Wallplate {bc} (top, along {width:.1f}m)", pieces(width, 4), "length",
         f"{sysd['wallplate']} {bc} 4m"),
    ]
    if sysd["eaves"]:
        lines.append(("eaves", f"Eaves beam {bc} (front, along {width:.1f}m)", pieces(width, 4),
                      "length", f"{sysd['eaves']} {bc} 4m"))
    if inp["include_acc"]:
        lines += [
            ("antidust", "Anti-dust tape (seals sheet tops)", max(1, pieces(width, 33)), "roll",
             "Anti Dust Tape"),
            ("foil", "Vented foil tape (sheet bottoms)", max(1, pieces(width, 33)), "roll",
             "Aluminium Foil Blanking Tape"),
        ]
    out = [{"key": k, "item": it, "qty": q, "unit": u, "search": s}
           for k, it, q, u, s in lines if q > 0]
    note = ""
    if rake > 6:
        note = (f"Slope is {rake:.1f}m — longer than a 6m bar/sheet, so bars and sheets will "
                "need joining (extra H-section/joints not yet added).")
    return out, {"sheets": sheets, "bars": inter + ends, "barlen": barlen, "note": note}


# ---- Storm self-support polycarbonate roof ---------------------------------------------------
# Storm sells poly sheets cut-to-size (per m²) as exact-size Shopify variants, plus its own
# self-support "Rafter Bar" glazing-bar system. Costs come from Shopify cost-per-item (Storm is in
# order_processing.SHOPIFY_COST_SUPPLIERS). SKU format: PC{thick}-{colour}-{w}x{len}mm.
STORM_SHEETS = {
    "10mm Twinwall": ("10", "Twinwall"), "16mm Triplewall": ("16", "Triplewall"),
    "25mm Multiwall": ("25", "Multiwall"), "35mm Multiwall": ("35", "Multiwall"),
}
STORM_COLOURS = {"Clear": "C", "Bronze": "B", "Opal": "O"}
STORM_SHEET_WIDTHS = [700, 1050, 1400, 2100]
STORM_SHEET_LENGTHS = [2000, 2500, 3000, 3500, 4000, 4500, 5000, 6000, 7000]
STORM_BAR_LENGTHS = [3, 4]            # Rafter Bar comes in 3 m and 4 m
STORM_BAR_COLOURS = ["White", "Brown"]


def storm_roof_takeoff(inp):
    """Storm self-support polycarbonate roof take-off. Multiwall sheets (matched to the nearest Storm
    stock size), Rafter Bar glazing bars + end caps + edge trim, lean-to flashing trim, sheet
    closures, tape and fixing buttons. inp keys: width (m span), slope (m), sheet_width_mm,
    sheet_type (a STORM_SHEETS key), colour (a STORM_COLOURS key), bar_colour, include_acc.
    Returns (lines, caveats); each line {description, qty, search, [code]}. Quantities are sized from
    the span and flagged as estimates — Storm's own layout tightens them."""
    width, slope = inp["width"], inp["slope"]
    sw_mm = int(inp["sheet_width_mm"])
    th, wall = STORM_SHEETS[inp["sheet_type"]]
    ccode = STORM_COLOURS[inp["colour"]]
    colour = inp["colour"]
    barcol = inp["bar_colour"]
    sheets = math.ceil(width / (sw_mm / 1000.0)) if (width and sw_mm) else 0
    if sheets <= 0:
        return None, None
    sheet_len = next((L for L in STORM_SHEET_LENGTHS if L >= slope * 1000), STORM_SHEET_LENGTHS[-1])
    barlen = next((b for b in STORM_BAR_LENGTHS if b >= slope), 4) if slope else 4
    bars = sheets + 1
    cav = []

    sheet_sku = f"PC{th}-{ccode}-{sw_mm}x{sheet_len}mm"
    lines = [{"description": f"{inp['sheet_type']} {colour} sheet — {sw_mm}×{sheet_len}mm",
              "qty": sheets, "code": sheet_sku,
              "search": f"{inp['sheet_type']} {colour} {sw_mm}x{sheet_len}mm"}]
    cav.append(f"{sheets} sheet(s) at {sw_mm} mm wide across the {width:.1f} m span, each "
               f"{sheet_len} mm long (nearest Storm stock length for a {slope:.1f} m slope).")
    if sheet_len / 1000.0 - slope > 0.3:
        cav.append(f"The nearest stock length ({sheet_len/1000:.1f} m) is longer than the "
                   f"{slope:.1f} m slope — trim on site, or ask for a cut-to-size sheet.")

    lines.append({"description": f"Storm rafter bar {barlen} m — {barcol} ({bars} bars)",
                  "qty": bars, "search": f"Rafter Bar {barlen}m {barcol}"})
    lines.append({"description": f"Rafter bar end cap — {barcol}", "qty": bars,
                  "search": f"Rafter Bar End Cap {barcol}"})
    lines.append({"description": "Rafter bar edge trim (2 outer bars)", "qty": 2,
                  "search": f"Rafter Bar Edge Trim {barcol}"})
    lines.append({"description": f"Lean-to flashing trim (top wall, along {width:.1f} m)",
                  "qty": max(1, math.ceil(width / 3.0)), "search": f"Lean-to Flashing Trim {barcol}"})
    lines.append({"description": f"Sheet closure {th}mm (eaves & ridge)", "qty": sheets * 2,
                  "search": f"Sheet Closure {th}mm {barcol}"})
    if inp.get("include_acc"):
        lines.append({"description": f"Storm tape pack {th}mm (anti-dust / foil)",
                      "qty": max(1, sheets), "search": f"Storm Tape Pack {th}mm"})
        lines.append({"description": "Fixing buttons with spacers (10 pk)",
                      "qty": max(1, math.ceil(bars / 2)),
                      "search": f"Fixing Buttons with Spacers {th}mm {barcol}"})
    cav.append(f"{bars} rafter bars at {barlen} m — one either side of each sheet. Bar, closure, "
               "tape and fixing counts are estimates from the span; confirm against Storm's layout.")
    cav.append("Polycarbonate here is quoted as Storm (self-support system) — send the exact roof "
               "sizes and we'll firm it up.")
    if slope > 7:
        cav.append("Slope over 7 m exceeds Storm's longest stock sheet — sheets/bars will need joining.")
    return lines, cav


# ---- Molan EZ Glaze (corrugated polycarbonate) ------------------------------------------------
EZGLAZE_COLOURS = {
    "Clear": ("EZ Glaze Clear", "CLR"),
    "Breeze Blue": ("EZ Glaze Breeze Blue", "BREEZE"),
    "Solar Ice": ("EZ Glaze Solar Ice", "SOLARICE"),
    "Beehive Clear": ("Beehive EZ Glaze", "BEEHIVECLR"),
}
EZGLAZE_LENGTHS = [2.5, 3, 3.5, 4, 6, 7]


def ezglaze_takeoff(inp):
    """EZ Glaze corrugated roof → Molan take-off. Sheets are SKU-exact (matched to the nearest EZ
    Glaze length); accessory quantities are estimates to confirm. inp keys: width (m), slope (m),
    cover (m, sheet cover width), colour (an EZGLAZE_COLOURS key). Returns (lines, meta). Each line
    has {key, item, qty, unit, skus, search}. Lifted verbatim from app.py."""
    width, slope, cover = inp["width"], inp["slope"], inp["cover"]
    sheets = math.ceil(width / cover) if (width and cover) else 0
    length = next((L for L in EZGLAZE_LENGTHS if L >= slope), 7) if slope else 0
    cname, ccode = EZGLAZE_COLOURS[inp["colour"]]
    # length suffix in the SKU (2.5 is written "25" for most, "2.5" for Breeze)
    suffixes = (["25", "2.5"] if length == 2.5 else [("%g" % length)])
    sheet_skus = [f"EZGLAZE{ccode}-{s}" for s in suffixes]
    lines = [
        {"key": "sheet", "item": f"{cname} corrugated sheet — {length:g}m",
         "qty": sheets, "unit": "sheet", "skus": sheet_skus, "search": cname},
        {"key": "foam", "item": "EZ Glaze foam sealing strip (eaves/ridge)",
         "qty": max(1, sheets), "unit": "strip", "skus": ["EZGLAZEFOAM"], "search": "EZ Glaze Foam"},
        {"key": "screws", "item": "EZ Glaze screws & washers (50 pack)",
         "qty": max(1, math.ceil(sheets / 3)), "unit": "pack", "skus": ["EZGLAZESCREW50"],
         "search": "EZ Glaze Screw 50"},
        {"key": "wallconn", "item": f"EZ Glaze 60mm wall connector (2m, along {width:.1f}m)",
         "qty": max(1, math.ceil(width / 2)) if width else 0, "unit": "length",
         "skus": ["EZGLAZEW-CONN2M"], "search": "EZ Glaze Wall Connector"},
    ]
    out = [l for l in lines if l["qty"] > 0]
    return out, {"sheets": sheets, "length": length}


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
