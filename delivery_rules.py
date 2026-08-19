"""Shared supplier delivery-charge rules (ex-VAT), used by BOTH the invoice checker and Order
Processing so a PO's delivery line and the invoice check agree. Mirrors the logic in app.py.

expected_delivery(supplier, goods, ship, lines) → the MAX legitimate ex-VAT delivery £, or None
if it can't be priced (unknown supplier / postcode not covered). ship = {postcode, country};
lines = [{sku, description, qty}].
"""
import json
import re
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _is_delivery(text):
    t = (text or "").lower()
    return any(w in t for w in ("deliver", "carriage", "carrier", "courier", "freight",
                                "shipping", "postage", "haulage", "transport"))


def _is_surcharge(text):
    t = (text or "").lower()
    return "surcharge" in t or "uplift" in t


def _product_lines(lines):
    out = []
    for l in (lines or []):
        s, d = l.get("sku") or "", l.get("description") or ""
        if _is_delivery(s) or _is_delivery(d) or _is_surcharge(s) or _is_surcharge(d):
            continue
        out.append(l)
    return out


# --- Flat / free-over suppliers (confident) -------------------------------------------------
FLAT = {
    "upb": (15.00, 100), "nbp": (17.00, 250), "eurocell": (12.50, 100),
    "travisperkins": (24.99, 100), "gap": (20.83, 150), "pjh": (37.50, 1000),
    "molan": (23.74, None), "decor8": (5.99, 50), "deanta": (8.00, None),
    "chasehardware": (10.00, None), "bricklink": (16.99, 100),
}


# --- Carron (zone by delivery postcode) -----------------------------------------------------
CARRON_FREE_OVER = 250.0
CARRON_ZONES = {1: {"large": 25.0}, 2: {"large": 50.0}, 3: {"large": 85.0}, 4: {"large": 65.0},
                5: {"large": None}, 6: {"large": 105.0}}
CARRON_AREA_ZONE = {"AB": 2, "DD": 2, "DG": 2, "EH": 2, "FK": 2, "G": 2, "KA": 2, "KY": 2,
                    "ML": 2, "PA": 2, "TD": 2, "IV": 3, "KW": 3, "PH": 3, "BT": 4,
                    "HS": 6, "ZE": 6, "IM": 6}


def _carron_zone(ship):
    if not ship:
        return 1
    country = (ship.get("country") or "").strip().upper()
    if country in ("IE", "IRL", "IRELAND", "REPUBLIC OF IRELAND", "EIRE"):
        return 5
    pc = re.sub(r"[^A-Z0-9]", "", (ship.get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    return CARRON_AREA_ZONE.get(area, 1)


def carron_expected(goods, ship):
    z = _carron_zone(ship)
    if z == 1 and goods is not None and goods >= CARRON_FREE_OVER:
        return 0.0
    return CARRON_ZONES[z]["large"]


# --- C TIE (UK £7 <£100 free-over; NI £13 <£250 free-over) -----------------------------------
def ctie_expected(goods, ship):
    pc = re.sub(r"[^A-Z0-9]", "", ((ship or {}).get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    country = ((ship or {}).get("country") or "").strip().upper()
    is_ni = area == "BT" or country in ("GB-NIR", "NORTHERN IRELAND")
    rule = (13.0, 250.0) if is_ni else (7.0, 100.0)
    if goods is not None and goods >= rule[1]:
        return 0.0
    return rule[0]


# --- Southern Sheeting (postcode colour zone) -----------------------------------------------
@lru_cache(maxsize=1)
def _southern_zones():
    try:
        with open(BASE / "southern_zones.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def southern_expected(ship):
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    if not pc:
        return None
    if " " in pc:
        outward = pc.split(" ")[0]
    elif len(pc) > 3:
        outward = pc[:-3]
    else:
        outward = pc
    return _southern_zones().get(outward.strip())


# --- JB Kind (door count) -------------------------------------------------------------------
JBKIND_DOOR_DELIVERY = {1: 42.0, 2: 47.0, 3: 52.0, 4: 57.0}
JBKIND_5PLUS = 62.0
JBKIND_IRONMONGERY = 15.0
_JBKIND_IRONMONGERY_WORDS = (
    "hinge", "handle", "latch", "knob", "pull", "bolt", "escutcheon", "spindle", "screw",
    "fixing", "lock", "catch", "stay", "hook", "numeral", "letterplate", "letter plate",
    "doorstop", "door stop", "tubular", "mortice", "cylinder", "keep", "strike", "ironmongery")
_JBKIND_EXCLUDED_AREAS = {"BT", "GY", "HS", "IM", "IV", "JE", "KW", "ZE"}
_JBKIND_EXCLUDED_RANGES = {"KA": (27, 28), "PA": (20, 80), "PH": (39, 44),
                           "PO": (30, 41), "TR": (21, 25)}


def _jbkind_excluded(ship):
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    m = re.match(r"([A-Z]{1,2})(\d{1,2})", pc)
    if not m:
        return False
    area, dist = m.group(1), int(m.group(2))
    if area in _JBKIND_EXCLUDED_AREAS:
        return True
    if area in _JBKIND_EXCLUDED_RANGES:
        lo, hi = _JBKIND_EXCLUDED_RANGES[area]
        return lo <= dist <= hi
    return False


def _jbkind_doors(lines):
    doors, iron = 0, False
    for l in _product_lines(lines):
        d = l.get("description") or ""
        q = l.get("qty") if isinstance(l.get("qty"), (int, float)) else 1
        if any(w in d.lower() for w in _JBKIND_IRONMONGERY_WORDS):
            iron = True
        else:
            doors += q
    return int(round(doors)), iron


def jbkind_expected(lines, ship=None):
    if ship and _jbkind_excluded(ship):
        return None
    doors, iron = _jbkind_doors(lines)
    if doors <= 0:
        return JBKIND_IRONMONGERY if iron else None
    if doors >= 5:
        return JBKIND_5PLUS
    return JBKIND_DOOR_DELIVERY.get(doors)


# --- LPD (door count + postcode surcharge) --------------------------------------------------
LPD_DOOR_BASE, LPD_DOOR_STEP, LPD_DOOR_CAP = 40.0, 5.0, 80.0
LPD_HARDWARE_LO, LPD_HARDWARE_HI = 15.0, 20.0
_LPD_CONGESTION = {"W1", "NW1", "WC1", "WC2", "EC1", "EC2", "EC3", "EC4", "E1", "SE1", "SE11"}


def _lpd_pc_parts(ship):
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    m = re.match(r"([A-Z]{1,2})(\d{1,2})", pc)
    if not m:
        return None, None, None
    outward = pc.split(" ")[0] if " " in pc else (pc[:-3] if len(pc) > 3 else pc)
    return m.group(1), int(m.group(2)), outward.strip()


def _lpd_surcharge(ship):
    area, dist, outward = _lpd_pc_parts(ship)
    if area is None:
        return 0.0, False
    if area in ("GY", "IM", "JE"):
        return 0.0, True
    if (area == "IV" and dist == 40) or (area == "TR" and 21 <= dist <= 25) \
            or (area == "PO" and 30 <= dist <= 40):
        return 0.0, True
    s = 0.0
    if area == "AB":
        s = 37.0
    elif area == "BT":
        s = 70.0
    elif area == "DD":
        s = 42.0
    elif area == "HS":
        s = 95.0
    elif area == "IV":
        s = 40.0
    elif area == "KY":
        s = 37.0
    elif area == "PH":
        s = 40.0
    elif area == "ZE":
        s = 95.0
    elif area == "KW":
        s = 40.0 if dist <= 14 else 95.0
    elif area == "PA":
        s = 37.0 if dist <= 19 else 67.50
    elif area == "KA" and 27 <= dist <= 28:
        s = 95.0
    elif area == "FK" and 8 <= dist <= 21:
        s = 20.0
    elif area == "G" and (dist == 63 or 82 <= dist <= 84):
        s = 20.0
    if f"{area}{dist}" in _LPD_CONGESTION:
        s += 15.0
    return s, False


def _lpd_doors(lines):
    doors, packs = 0, 0
    for l in _product_lines(lines):
        d = l.get("description") or ""
        q = l.get("qty") if isinstance(l.get("qty"), (int, float)) else 1
        if any(w in d.lower() for w in _JBKIND_IRONMONGERY_WORDS):
            packs += q
        else:
            doors += q
    return int(round(doors)), int(round(packs))


def lpd_expected(lines, ship=None):
    surcharge, poa = _lpd_surcharge(ship)
    if poa:
        return None
    doors, packs = _lpd_doors(lines)
    if doors > 0:
        base = min(LPD_DOOR_BASE + (doors - 1) * LPD_DOOR_STEP, LPD_DOOR_CAP)
    elif packs > 0:
        base = LPD_HARDWARE_LO if packs <= 10 else LPD_HARDWARE_HI
    else:
        return None
    return base + surcharge


# --- Vista (door canopies): box-count, with carriage-paid over a category threshold ----------
# 1 box £15, 2 £17.50, 3 £20, 4 £25, 5 £30 (5+ capped at £30). Carriage paid over the category
# threshold (Wall Ties £225 / Metalwork £450 / Beads-Mesh £625 / Deck-Fencing £450) — we can't
# read the category from the order, so we use the HIGHEST (£625) as a safe free-over (only very
# large orders assumed carriage-paid), box-count below. Boxes ≈ number of product lines.
VISTA_BOX = {1: 15.0, 2: 17.50, 3: 20.0, 4: 25.0, 5: 30.0}
VISTA_CARRIAGE_PAID = 625.0


def vista_expected(goods, lines):
    if goods is not None and goods >= VISTA_CARRIAGE_PAID:
        return 0.0
    boxes = len(_product_lines(lines)) or 1
    return VISTA_BOX[5] if boxes >= 5 else VISTA_BOX.get(boxes, 15.0)


# --- dispatch -------------------------------------------------------------------------------
def expected_delivery(supplier, goods=None, ship=None, lines=None):
    s = _norm(supplier)
    if s.startswith("carron"):
        return carron_expected(goods, ship)
    if s.startswith("ctie"):
        return ctie_expected(goods, ship)
    if s.startswith("southern"):
        return southern_expected(ship)
    if s.startswith("jbkind"):
        return jbkind_expected(lines, ship)
    if s.startswith("lpd"):
        return lpd_expected(lines, ship)
    if s.startswith("vista"):
        return vista_expected(goods, lines)
    if s in FLAT:
        flat, free_over = FLAT[s]
        if free_over is not None and goods is not None and goods >= free_over:
            return 0.0
        return flat
    return None
