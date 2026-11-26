"""Nuie (Roxor Group / Hudson Reed / Ultra Finishing) carriage — what Nuie charge US to deliver.

Model (Tom Hudson rate card + Daniela 2026-11-26):
  * Each product has a SHIPPING LOAD TYPE (from the Hudson Reed datapack, column 84), mapped to one of
    three rate categories: parcel / oversized / pallet. 'Standard Parcel'->parcel, 'Oversized Parcel'->
    oversized, 'Standard Pallet'/'A-Frame pallet'/'Multi Carton'->pallet (A-Frame rate == Pallet rate;
    Multi Carton billed as Pallet — Daniela's call). SKU->category lives in nuie_delivery.json (3,906 SKUs).
  * Rates are by ZONE: Zone 1 = UK Mainland, Zone 2 = offshore islands / Scottish Highlands / NI / Ireland
    (specific postcode districts). Base rates below; **Nuie add 10% on top** (UPLIFT), so the cost to us
    is rate x 1.10, ex VAT.
  * An order's carriage = the HIGHEST single item's rate (one consolidated delivery; pallets do NOT stack,
    so the Double Pallet rate is never auto-applied — Daniela 2026-11-26).

expected(lines, ship) -> ex-VAT carriage £ (inc the +10%), or None if no line resolves to a category.
Nothing here writes anywhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Base rates ex VAT, BEFORE the +10% Nuie add. (zone1, zone2).
_RATES = {
    "parcel":    (15.00, 15.00),
    "oversized": (28.00, 40.00),
    "pallet":    (54.50, 100.00),
    # 'double' (Double Pallet) £100/£175 exists on the card but is never auto-applied (no stacking).
    "double":    (100.00, 175.00),
}
UPLIFT = 1.10   # Nuie charge their rate card + 10% (Daniela 2026-11-26)

# Zone 2 = UK offshore islands / Highlands / NI / Ireland. Whole postcode AREAS always Zone 2:
_Z2_AREAS = {"BT", "HS", "IM", "IV", "KW", "ZE"}
# Area -> district-number ranges that are Zone 2 (the rest of the area is Zone 1):
_Z2_RANGES = {
    "AB": [(31, 38), (41, 56)],   # Aberdeen rural / Northern Highlands (city AB10-25 stays Zone 1)
    "KA": [(27, 28)],             # Isle of Arran / North Ayrshire
    "PA": [(20, 78)],             # Argyll (Paisley PA1-19 stays Zone 1)
    "PH": [(15, 99)],             # Perth & Kinross / Highlands (Perth PH1-14 stays Zone 1)
    "PO": [(30, 41)],             # Isle of Wight (Portsmouth PO1-29 stays Zone 1)
    "TR": [(3, 6), (10, 25)],     # Truro rural / Scilly Isles
}

_SKU_CAT = None


def _sku_cat() -> dict:
    global _SKU_CAT
    if _SKU_CAT is None:
        try:
            _SKU_CAT = json.loads(Path(__file__).with_name("nuie_delivery.json").read_text("utf-8"))
        except Exception:  # noqa: BLE001
            _SKU_CAT = {}
    return _SKU_CAT


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def zone_for_postcode(postcode, country=None) -> int:
    """1 (UK mainland) or 2 (offshore/Highlands/NI/Ireland)."""
    c = (country or "").strip().upper()
    if c in ("IE", "IRL", "IRELAND", "EIRE", "REPUBLIC OF IRELAND", "GB-NIR"):
        return 2
    pc = re.sub(r"[^A-Z0-9]", "", (postcode or "").upper())
    if not pc:
        return 1
    outward = pc[:-3] if len(pc) > 3 else pc          # strip the inward code
    m = re.match(r"^([A-Z]+)(\d+)", outward)
    if not m:
        a = re.match(r"^([A-Z]+)", outward)
        return 2 if (a and a.group(1) in _Z2_AREAS) else 1
    area, num = m.group(1), int(m.group(2))
    if area in _Z2_AREAS:
        return 2
    for lo, hi in _Z2_RANGES.get(area, []):
        if lo <= num <= hi:
            return 2
    return 1


def zone_label(ship) -> str:
    z = zone_for_postcode((ship or {}).get("postcode"), (ship or {}).get("country"))
    pc = (ship or {}).get("postcode") or "no postcode"
    return f"Nuie Zone {z} ({'UK mainland' if z == 1 else 'offshore/Highlands/NI'}), {pc}"


def category_for_sku(sku) -> str | None:
    return _sku_cat().get(_norm(sku))


def rate(category, zone) -> float | None:
    """Ex-VAT carriage for a category at a zone, INCLUDING the +10% Nuie add."""
    pair = _RATES.get(category)
    if not pair:
        return None
    base = pair[1] if zone == 2 else pair[0]
    return round(base * UPLIFT, 2)


def expected(lines, ship) -> float | None:
    """The order's Nuie carriage = the highest single line's rate (inc +10%), by zone. None if no line
    resolves to a known category (e.g. SKUs not in the datapack)."""
    zone = zone_for_postcode((ship or {}).get("postcode"), (ship or {}).get("country"))
    best = None
    for l in (lines or []):
        cat = category_for_sku(l.get("sku"))
        if not cat:
            continue
        r = rate(cat, zone)
        if r is not None and (best is None or r > best):
            best = r
    return best
