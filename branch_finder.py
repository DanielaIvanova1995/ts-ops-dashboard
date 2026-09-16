"""Nearest Eurocell / Travis Perkins branch for a UK customer postcode.

Neither supplier publishes a fixed postcode→branch map — coverage is "whichever branch is
physically closest". So we geocode the customer postcode (postcodes.io, free, no key) and rank the
pre-geocoded branch list (order_processing/branches_geocoded.csv) by straight-line distance —
mirroring the suppliers' own branch-finder pages. Standard library only.
"""
import csv
import json
import math
import os
import re
import urllib.parse
import urllib.request
from functools import lru_cache

_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "order_processing", "branches_geocoded.csv")


@lru_cache(maxsize=1)
def _branches():
    out = []
    try:
        with open(_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    r["latitude"] = float(r["latitude"])
                    r["longitude"] = float(r["longitude"])
                except (ValueError, KeyError):
                    continue
                out.append(r)
    except Exception:  # noqa: BLE001
        pass
    return out


@lru_cache(maxsize=4096)
def _geocode(postcode):
    """(lat, lon) for a UK postcode via postcodes.io; falls back to the outcode. None on failure."""
    pc = (postcode or "").strip().replace(" ", "")
    if not pc:
        return None
    try:
        with urllib.request.urlopen(
                f"https://api.postcodes.io/postcodes/{urllib.parse.quote(pc)}", timeout=8) as resp:
            d = json.loads(resp.read())
        if d.get("status") == 200 and d.get("result"):
            return (d["result"]["latitude"], d["result"]["longitude"])
    except Exception:  # noqa: BLE001
        pass
    try:
        oc = pc[:-3] if len(pc) > 3 else pc
        with urllib.request.urlopen(
                f"https://api.postcodes.io/outcodes/{urllib.parse.quote(oc)}", timeout=8) as resp:
            d = json.loads(resp.read())
        if d.get("status") == 200 and d.get("result"):
            return (d["result"]["latitude"], d["result"]["longitude"])
    except Exception:  # noqa: BLE001
        pass
    return None


@lru_cache(maxsize=64)
def _geocode_outcode(outcode):
    """(lat, lon) for a bare UK outcode (e.g. 'NP11', 'ME14') via postcodes.io's /outcodes endpoint.
    `_geocode` mangles a bare outcode (its full-postcode fallback chops the last 3 chars), so branch
    outcodes must use this. None on failure."""
    oc = (outcode or "").strip().replace(" ", "")
    if not oc:
        return None
    try:
        with urllib.request.urlopen(
                f"https://api.postcodes.io/outcodes/{urllib.parse.quote(oc)}", timeout=8) as resp:
            d = json.loads(resp.read())
        if d.get("status") == 200 and d.get("result"):
            return (d["result"]["latitude"], d["result"]["longitude"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _haversine(a, b, c, d):
    R = 3958.8
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))


# National Plastics (specbd) — the 3 branches we can send Hardie orders to. Each carries a
# representative outcode we geocode once to rank by distance (Daniela, 2026-09-13).
_NP_BRANCHES = [
    {"branch_name": "National Plastics — Rotherham", "email": "Afearn@specbd.co.uk",
     "phone": "01827 948660", "contact": "Anthony", "outcode": "S60"},
    {"branch_name": "National Plastics — Abercarn",
     "email": "AbercarnManager@nationalplastics.co.uk", "phone": "01495 248469",
     "contact": "Phil", "outcode": "NP11"},
    {"branch_name": "National Plastics — Maidstone", "email": "Aellerbeck@shepherdsuk.co.uk",
     "phone": "01622 695909", "contact": "Allen", "outcode": "ME14"},
]


_NP_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "national_plastics_branches.json")


@lru_cache(maxsize=1)
def _np_zest_branches():
    """The full National Plastics branch network (name, email, phone, postcode, lat, lon) — used to
    route Zest cladding orders to the customer's nearest branch. Pre-geocoded from Branches.xlsx."""
    try:
        with open(_NP_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return []


def zest_branch(postcode):
    """Nearest National Plastics branch (of the full network) for a Zest order → {branch_name, email,
    phone, postcode, miles}. None if the postcode won't geocode or no branch data."""
    coords = _geocode(postcode)
    if not coords:
        return None
    lat, lon = coords
    bs = _np_zest_branches()
    if not bs:
        return None
    best = min(bs, key=lambda b: _haversine(lat, lon, b["lat"], b["lon"]))
    return {"branch_name": best.get("name") or "", "email": best.get("email") or "",
            "phone": best.get("phone") or "", "postcode": best.get("pc") or "",
            "miles": round(_haversine(lat, lon, best["lat"], best["lon"]), 1)}


def national_plastics_branch(postcode):
    """Nearest National Plastics branch (Rotherham / Abercarn / Maidstone) for a customer postcode
    → {branch_name, email, phone, contact, miles}. None if the postcode won't geocode (caller then
    falls back to a coarse region map). Geocodes the branch outcodes via postcodes.io like the
    Eurocell/TP finder."""
    coords = _geocode(postcode)
    if not coords:
        return None
    lat, lon = coords
    best, best_d = None, None
    for b in _NP_BRANCHES:
        bc = _geocode_outcode(b["outcode"])
        if not bc:
            continue
        d = _haversine(lat, lon, bc[0], bc[1])
        if best_d is None or d < best_d:
            best, best_d = b, d
    if not best:
        return None
    return {"branch_name": best["branch_name"], "email": best["email"], "phone": best["phone"],
            "contact": best["contact"], "miles": round(best_d, 1)}


def nearest_branch(postcode, supplier):
    """Nearest branch → {branch_name, email, phone, address, postcode, miles}. None if the supplier
    isn't Eurocell/Travis Perkins, the postcode won't geocode, or no branch data."""
    key = re.sub(r"[^a-z]", "", (supplier or "").lower())
    sup = ("Eurocell" if key.startswith("eurocell")
           else "Travis Perkins" if key.startswith("travis") else None)
    if not sup:
        return None
    coords = _geocode(postcode)
    if not coords:
        return None
    lat, lon = coords
    cands = [b for b in _branches() if b.get("supplier") == sup]
    if not cands:
        return None
    best = min(cands, key=lambda b: _haversine(lat, lon, b["latitude"], b["longitude"]))
    return {"branch_name": best.get("branch_name") or "", "email": best.get("email") or "",
            "phone": best.get("phone") or "", "address": best.get("address") or "",
            "postcode": best.get("postcode") or "",
            "miles": round(_haversine(lat, lon, best["latitude"], best["longitude"]), 1)}
