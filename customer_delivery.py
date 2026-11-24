"""What TSO charges the CUSTOMER for delivery, per supplier — the counterpart to delivery_rules.py
(which is what the SUPPLIER charges US). Used to attribute delivery REVENUE to each part of a SPLIT
order, so each supplier part's '£ to us' (and therefore its margin) reflects the delivery we charge
for that supplier's goods, instead of smearing one combined shipping figure proportionally.

MONEY BASIS (Daniela 2026-11-24):
  * Charges here are EX VAT — they mirror the Shopify shipping rates, which are ex-VAT; VAT is added
    after at checkout. Monday's '£ to us' (numbers48) is INC VAT, so callers gross the charge up by
    ×1.2 before writing it.
  * Bands are judged on that supplier's SLICE of the order — its own goods value, ex-VAT, net of any
    discount (Shopify's discountedTotalSet per line already nets the discount off).

charge(supplier, goods_ex_vat) -> ex-VAT customer delivery £, or None if the supplier isn't modelled
here yet (the caller then falls back to its existing behaviour). is_modelled(supplier) -> bool.

TO ADD A SUPPLIER: add a RULES entry — ascending bands as (upper_limit_ex_vat | None, charge_ex_vat).
A band applies when goods_ex_vat <= upper_limit; None upper limit means "and over" (the top band).
Nothing here writes anywhere; callers decide how to apply the numbers.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    """Same supplier-name normaliser as delivery_rules: 'Travis Perkins' -> 'travisperkins'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# supplier (normalised) -> ascending bands [(upper_limit_ex_vat | None, charge_ex_vat)]
RULES: dict[str, list[tuple[float | None, float]]] = {
    # Eurocell: £12.99 up to £150, free over £150.01 (Daniela 2026-11-24)
    "eurocell":      [(150.0, 12.99), (None, 0.0)],
    # GAP: £19.99 on every order (Daniela 2026-11-24)
    "gap":           [(None, 19.99)],
    # Travis Perkins: £24.99 up to £120, £5.99 over £120.01 (Daniela 2026-11-24)
    "travisperkins": [(120.0, 24.99), (None, 5.99)],
}

# Human labels for the delivery-catalog display (fall back to .title() otherwise).
NAMES = {"eurocell": "Eurocell", "gap": "GAP", "travisperkins": "Travis Perkins"}


def is_modelled(supplier: str) -> bool:
    """True if we have a customer-delivery rule for this supplier."""
    return _norm(supplier) in RULES


def charge(supplier: str, goods_ex_vat: float | None) -> float | None:
    """Ex-VAT customer delivery charge for `supplier` at this ex-VAT slice value, or None if the
    supplier has no rule yet. goods_ex_vat None/blank is treated as £0 (so the first band applies)."""
    bands = RULES.get(_norm(supplier))
    if not bands:
        return None
    try:
        g = float(goods_ex_vat or 0.0)
    except (TypeError, ValueError):
        g = 0.0
    for upper, amt in bands:
        if upper is None or g <= float(upper):
            return float(amt)
    return float(bands[-1][1])


def describe(supplier: str) -> str | None:
    """One-line plain-English summary of a supplier's bands for the delivery catalog, or None."""
    bands = RULES.get(_norm(supplier))
    if not bands:
        return None
    parts, low = [], 0.0
    for upper, amt in bands:
        amt_s = "free" if amt == 0 else f"£{amt:,.2f}"
        if upper is None:
            parts.append(f"{amt_s} over £{low:,.0f}" if low else f"{amt_s} on every order")
        else:
            parts.append(f"{amt_s} up to £{upper:,.0f}")
            low = float(upper)
    return " / ".join(parts) + " (ex VAT)"
