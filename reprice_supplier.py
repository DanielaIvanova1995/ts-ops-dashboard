#!/usr/bin/env python3
"""
Reprice a supplier's Shopify range to a target margin.

Carron's bespoke cast iron radiators are the reason this exists. One Shopify SKU covers all
72-90 variants of a range (e.g. LD221/LD222), with the finish and section count living only in
the variant title, so a price can't be set per SKU — each variant's price is

    sections x the finish's cost-per-section / (1 - target_margin)

Doing that by hand across ~3,500 variants is 3,500 chances to fat-finger a live price, so it's
done here instead: costs come from price_overrides.json (the same file TradeHub prices POs and
invoices from), so the shop and the margin checker can never disagree about what a thing costs.

Also handles the FLAT SKUs (valves, towel rails, elements...) where price = cost / (1 - margin).

Usage
-----
    python reprice_supplier.py --supplier Carron --margin 18            # dry run, writes nothing
    python reprice_supplier.py --supplier Carron --margin 18 --apply    # actually push
    python reprice_supplier.py --supplier Carron --margin 18 --csv out.csv

Needs the Shopify app to hold `write_products` (checked up front). Auth reuses whatever
data_sources already uses, so no new credentials.

Variants with no cost are SKIPPED and listed, never guessed — e.g. Carron's Hand Gilded, where
the "+£50 SRP" uplift is ambiguous between per-section and per-radiator. Same house rule as the
PO/invoice side: an unpriced line stays unpriced.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

import requests

import data_sources as ds

HERE = os.path.dirname(os.path.abspath(__file__))
API = ds.SHOPIFY_API_VERSION

# Variant-title finish -> the finish key used in price_overrides.json _persection.
# Order matters: first needle found wins, so "Paint/ Metallic" isn't read as ".../ Powder Coated".
# A finish that maps to None is deliberately unpriceable (Carron Hand Gilded).
FINISH = [("gilded", None), ("burnish", "SATIN-POLISHED"), ("satin", "SATIN-POLISHED"),
          ("antiqu", "ANTIQUED"), ("highlight", "ANTIQUED"), ("baremetal", "ANTIQUED"),
          ("powdercoat", "ANTIQUED"), ("copper", "VINTAGE-COPPER"),
          ("metallic", "PAINTED"), ("paint", "PAINTED"), ("primer", "PRIMER")]
SECTIONS_RE = re.compile(r"(\d{1,3})\s*sections?\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def gql(query, variables=None):
    store = ds.get_secret("SHOPIFY_STORE") or ds.SHOPIFY_DOMAIN_DEFAULT
    r = requests.post(
        f"https://{store}/admin/api/{API}/graphql.json",
        json={"query": query, "variables": variables or {}},
        headers={"X-Shopify-Access-Token": ds.shopify_products_token(),
                 "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify API error: {payload['errors']}")
    return payload["data"]


def load_costs(supplier):
    """(per-section rates {leg_code_norm: {finish: £}}, flat costs {sku_norm: £}) for a supplier."""
    with open(os.path.join(HERE, "price_overrides.json"), encoding="utf-8") as f:
        ov = json.load(f)
    persection = {norm(k): v for k, v in
                  ((ov.get("_persection") or {}).get(supplier) or {}).items()}
    flat = {norm(k): v for k, v in (ov.get(supplier) or {}).items()
            if isinstance(v, (int, float))}
    # The generated feed carries the rest of the supplier's catalogue (stoves, pipes, spares).
    try:
        with open(os.path.join(HERE, "pricing_lookup.json"), encoding="utf-8") as f:
            for it in json.load(f).get("items", []):
                for o in it.get("offers") or []:
                    if norm(o.get("s")) == norm(supplier) and isinstance(o.get("c"), (int, float)):
                        flat.setdefault(norm(it.get("sku")), o["c"])
    except FileNotFoundError:
        pass
    return persection, flat


def fetch_variants(vendor):
    """[{product_id, product, variant_id, title, sku, price}] for every variant of a vendor."""
    out, cursor = [], None
    q = """
    query($q: String!, $after: String) {
      products(first: 25, query: $q, after: $after) {
        edges { node { id title status
          variants(first: 100) { edges { node { id title sku price } } } } }
        pageInfo { hasNextPage endCursor }
      }
    }"""
    while True:
        data = gql(q, {"q": f"vendor:{vendor}", "after": cursor})["products"]
        for e in data["edges"]:
            p = e["node"]
            for ve in p["variants"]["edges"]:
                v = ve["node"]
                out.append(dict(product_id=p["id"], product=p["title"], status=p["status"],
                                variant_id=v["id"], title=v["title"], sku=v["sku"],
                                price=float(v["price"])))
        if not data["pageInfo"]["hasNextPage"]:
            return out
        cursor = data["pageInfo"]["endCursor"]


def target_price(v, persection, flat, margin):
    """(new_price, basis) or (None, why_not). Per-section first, then the flat SKU cost."""
    key = norm(v["sku"])
    leg = next((b for b in sorted(persection, key=len, reverse=True) if b and key.startswith(b)),
               None)
    if leg:
        m = SECTIONS_RE.search(v["title"] or "")
        if not m:
            return None, "per-section range but no section count in the variant title"
        n = int(m.group(1))
        fin = next((f for needle, f in FINISH if needle in norm(v["title"])), None)
        if fin is None:
            return None, "finish has no agreed cost (e.g. Hand Gilded)"
        rate = persection[leg].get(fin)
        if rate is None:
            return None, f"no {fin} rate for {leg}"
        return round(rate * n / (1 - margin) + 1e-9, 2), f"{n} x {rate:.2f} {fin}"
    if key in flat:
        return round(flat[key] / (1 - margin) + 1e-9, 2), f"flat cost {flat[key]:.2f}"
    return None, "no cost held for this SKU"


def push(product_id, changes):
    q = """
    mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        userErrors { field message }
      }
    }"""
    errs = gql(q, {"productId": product_id,
                   "variants": [{"id": c["variant_id"], "price": f"{c['new']:.2f}"}
                                for c in changes]})["productVariantsBulkUpdate"]["userErrors"]
    if errs:
        raise RuntimeError(f"{product_id}: {errs}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supplier", required=True, help="supplier name as it appears in price_overrides.json")
    ap.add_argument("--vendor", help="Shopify vendor, if it differs from --supplier")
    ap.add_argument("--margin", type=float, required=True, help="target margin %%, e.g. 18")
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--csv", help="write the full change list here")
    args = ap.parse_args()
    margin = args.margin / 100.0
    vendor = args.vendor or args.supplier

    if args.apply:
        scopes = {s["handle"] for s in ds.shopify_token_scopes()["accessScopes"]}
        if "write_products" not in scopes:
            sys.exit("This Shopify app can't write prices (needs write_products). Add the scope, "
                     f"or run without --apply. Scopes held: {sorted(scopes)}")

    persection, flat = load_costs(args.supplier)
    print(f"costs: {len(persection)} per-section ranges, {len(flat)} flat SKUs")
    variants = fetch_variants(vendor)
    print(f"{vendor}: {len(variants)} variants on Shopify")

    changes, skipped = [], []
    for v in variants:
        new, basis = target_price(v, persection, flat, margin)
        if new is None:
            skipped.append((v, basis))
        elif abs(new - v["price"]) >= 0.01:
            changes.append({**v, "new": new, "basis": basis})

    by_product = {}
    for c in changes:
        by_product.setdefault(c["product_id"], []).append(c)
    up = sum(1 for c in changes if c["new"] > c["price"])
    print(f"\n{len(changes)} price changes across {len(by_product)} products "
          f"({up} up, {len(changes) - up} down) · {len(skipped)} skipped · "
          f"{len(variants) - len(changes) - len(skipped)} already correct")

    reasons = {}
    for _v, why in skipped:
        reasons[why] = reasons.get(why, 0) + 1
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"   skipped {n:5d}  {why}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["product", "variant", "sku", "current", "new", "change", "basis"])
            for c in sorted(changes, key=lambda c: (c["product"], c["title"])):
                w.writerow([c["product"], c["title"], c["sku"], f"{c['price']:.2f}",
                            f"{c['new']:.2f}", f"{c['new'] - c['price']:+.2f}", c["basis"]])
        print(f"wrote {args.csv}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to push.")
        return

    for i, (pid, group) in enumerate(by_product.items(), 1):
        push(pid, group)
        print(f"  [{i}/{len(by_product)}] {group[0]['product'][:60]} — {len(group)} variants")
        time.sleep(0.3)          # stay well inside Shopify's leaky bucket
    print(f"\napplied {len(changes)} price changes")


if __name__ == "__main__":
    main()
