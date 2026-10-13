"""AJW (Cedral) carriage & delivery — shared logic for order processing, invoice checking and
quotes. Data from 'AJW Delivery Zones & Charges 2026-10-12.xlsx' (TSO's corrected working copy),
baked into ajw_delivery.json so the deploy doesn't need the Dropbox file.

Key rules (all money EX VAT):
  * Carriage is a flat per-ZONE charge, by delivery postcode area.
  * AJW delivers FREE once TSO's OWN cost (ex VAT, products only) reaches the zone's threshold.
  * The customer delivery rate is 1p under AJW's carriage; the customer gets free delivery once the
    ORDER value (ex VAT) reaches the (higher) customer threshold — so TSO never eats carriage while
    giving the customer free delivery.
  * White zone (Scotland, N. Ireland, islands) is quoted per order — never auto-charged.
  * Surcharges (per drop, ex VAT): mechanical offload +£75, failed delivery £250.

Nothing here writes anywhere; callers decide how to apply the numbers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DATA = None


def _data() -> dict:
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.loads((Path(__file__).with_name("ajw_delivery.json")).read_text("utf-8"))
        except Exception:  # noqa: BLE001
            _DATA = {"zones": {}, "postcodes": {}, "surcharges": {}}
    return _DATA


def postcode_area(postcode: str) -> str | None:
    """The UK postcode AREA (the leading letters of the outward code): 'NN1 2AB'->'NN', 'W1A'->'W',
    'SW1 1AA'->'SW'. None if unreadable."""
    s = re.sub(r"[^A-Za-z0-9]", "", (postcode or "")).upper()
    m = re.match(r"^[A-Z]+", s)
    return m.group(0) if m else None


def zone_for_postcode(postcode: str) -> str | None:
    """AJW zone name for a delivery postcode (Blue/Green/Yellow/Light Blue/Orange/White), or None if
    the area isn't recognised."""
    area = postcode_area(postcode)
    if not area:
        return None
    return _data().get("postcodes", {}).get(area)


def zone_info(zone: str | None) -> dict | None:
    return _data().get("zones", {}).get(zone or "")


def tso_carriage(postcode: str, net_cost_ex_vat: float) -> dict:
    """What AJW charges TSO to deliver, by postcode and TSO's own ex-VAT product cost.
    Returns {zone, shopify_zone, charge, free_over, is_free, quote, known}:
      charge   = carriage ex VAT TSO will pay (0.0 when over the free threshold)
      quote    = True for White (quote per order) — charge is None
      known    = False when the postcode area isn't recognised (treat as needs-a-look)."""
    zone = zone_for_postcode(postcode)
    info = zone_info(zone)
    if not zone or not info:
        return {"zone": zone, "shopify_zone": None, "charge": None, "free_over": None,
                "is_free": False, "quote": False, "known": False}
    if info.get("ajw_rate") is None:                       # White — quote per order
        return {"zone": zone, "shopify_zone": info.get("shopify_zone"), "charge": None,
                "free_over": None, "is_free": False, "quote": True, "known": True}
    free_over = info.get("ajw_free")
    is_free = isinstance(free_over, (int, float)) and float(net_cost_ex_vat or 0) >= float(free_over)
    return {"zone": zone, "shopify_zone": info.get("shopify_zone"),
            "charge": 0.0 if is_free else float(info["ajw_rate"]),
            "free_over": free_over, "is_free": is_free, "quote": False, "known": True}


def customer_delivery(postcode: str, order_value_ex_vat: float) -> dict:
    """What TSO charges the CUSTOMER for delivery, by postcode and ex-VAT order value.
    Same shape as tso_carriage (charge 0.0 when over the customer free threshold)."""
    zone = zone_for_postcode(postcode)
    info = zone_info(zone)
    if not zone or not info:
        return {"zone": zone, "charge": None, "free_over": None, "is_free": False,
                "quote": False, "known": False}
    if info.get("cust_rate") is None:                      # White — quote
        return {"zone": zone, "charge": None, "free_over": None, "is_free": False,
                "quote": True, "known": True}
    free_over = info.get("cust_free")
    is_free = isinstance(free_over, (int, float)) and float(order_value_ex_vat or 0) >= float(free_over)
    return {"zone": zone, "charge": 0.0 if is_free else float(info["cust_rate"]),
            "free_over": free_over, "is_free": is_free, "quote": False, "known": True}


def surcharges() -> dict:
    """Per-drop surcharges ex VAT: {'mechanical_offload': 75.0, 'failed_delivery': 250.0}."""
    return dict(_data().get("surcharges", {}))
