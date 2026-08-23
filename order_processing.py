"""Order Processing cockpit (Phase 1) — board-style grid.

Reads the "NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)" group on the Monday Orders board and
shows it like the Monday board itself: one editable row per order with inline Supplier and
Order-Process-Stage dropdowns and a Select tick. Edits are written back to Monday on Save
(Monday stays the source of truth). A detail panel below shows the full order + live Shopify
lines/fulfilments and handles PO download/replace.

Phase 2 (routing engine) and Phase 3 (PO/packing-slip generation + verified attach) plug into
the Process buttons, which are stubbed here.
"""
import datetime
import html
import json
import re

import pandas as pd
import streamlit as st

import branch_finder
import data_sources
import delivery_rules
import order_docs
import order_routing

DANIELA = "daniela@tradesuperstoreonline.co.uk"
FROM_MAILBOX = "accounts@tradesuperstoreonline.co.uk"
PLACE_ORDER = "Place Order"      # only orders at this stage are unprocessed / safe to process
# Correct PO email per supplier (set on Monday after the supplier). Filled from the supplier
# rulebook's po_email. EXCLUDES suppliers whose email is resolved elsewhere: Eurocell / Travis
# Perkins / UPB (nearest branch or depot), GAP (Monday auto-fills from the GAP tag), and portal-only
# PJH / Toolbank. Suppliers the rulebook marks "confirm" are left out until Daniela gives the email.
SUPPLIER_PO_EMAIL = {"Molan": "orders@molan-uk.com",    # board auto-fills transport@ (wrong)
                     "Vista": "orders@vistaeng.co.uk",   # confirmed (not the rulebook's sales@)
                     "Plastivan": "becky.thompson@plastivan.co.uk",   # Becky Thompson
                     "Bricklink": "tessallingham@bricklink.co.uk",    # Tess Allingham
                     "MB Decor": "orders@mbdecor.co.uk",              # DecorOrders
                     "Decor8": "hello@paintersworld.co.uk",           # Painters World
                     "Etills": "info@etills.com",
                     "NBP": "sales@nbp.co.uk",
                     "Southern Sheeting": "jordan@southernsheeting.co.uk",
                     "Huws Gray": "colin.tansley@huwsgray.co.uk",     # Colin Tansley, Derby
                     "Storm": "sales@stormbuildingproducts.com",
                     "Rexel": "adam.mussa@rexel.co.uk",
                     "LPD DOORS": "sales@lpddoors.co.uk",
                     "JB Kind": "jordan.lees@jbkind.com",
                     "Deanta": "ecommerce@deanta.co.uk",
                     "Carron": "sales@carronheating.co.uk",
                     "Chase Hardware": "matt.jenkinson@chase-hardware.co.uk",
                     "Dolle": "uksales@dolle.com",
                     "Evolve": "sales@evolveflooring.co.uk",
                     "Squaredeal": "info@squaredealupvc.co.uk",
                     "Nuie": "sales@roxorgroup.com",                  # Roxor Group
                     "Walls and Floors": "wholesale@wallsandfloors.co.uk",
                     "Velux": "customer.support@velux.co.uk",
                     "Permaroof": "sales@permaroof.co.uk",
                     "Newplas": "toby@newplas.co.uk",                 # Toby
                     "Brickservices": "tessallingham@bricklink.co.uk",  # Tess Allingham
                     "Brundle": "connor.branigan@brundle.com",        # Connor Branigan
                     "Edmundson": "steve.hallsworth@eel.co.uk",       # Steve Hallsworth
                     "Mercardo": "mark.jackson@mercado.co.uk",        # Mark Jackson
                     "C TIE": "sales@ctie.co.uk",
                     "Hurlingham Baths": "sales@hurlinghambaths.co.uk",
                     "Hurlingham": "sales@hurlinghambaths.co.uk",
                     "National Skirting": "info@nationalskirting.co.uk"}

# Head-office contact number per supplier, for the Branch contact number when the order ISN'T a
# branch order (Eurocell/Travis Perkins get the nearest branch's number from the branch finder
# instead). Seeded from the rulebook's confident landlines — Daniela to confirm/complete the rest
# from the supplier & contacts sheet.
SUPPLIER_HEAD_OFFICE_PHONE = {
    "Southern Sheeting": "01342 337119", "Decor8": "0161 763 7007", "Rexel": "0330 045 0606",
    "LPD DOORS": "0113 251 3948", "JB Kind": "01283 554197", "Carron": "01400 263 310",
    "Hurlingham": "01400 263 310", "Hurlingham Baths": "01400 263 310",
    "Walls and Floors": "01536 410484", "Permaroof": "01773 608808", "Newplas": "01332 322160",
    "Bricklink": "0141 286 3600", "Brickservices": "0141 286 3600", "Plastivan": "0117 300 5625",
    "Brundle": "0115 930 2070", "Dolle": "01332 811611", "Nuie": "01422 417100",
    "GAP": "01332 410004", "Molan": "01529 461867", "Vista": "01663 736 700",
    "PJH": "0345 450 8932", "Deanta": "01353 698602", "MB Decor": "01642 455945",
    "Toolbank": "0344 463 6050", "Etills": "01763 261 781", "C TIE": "01737 760645",
    "Chase Hardware": "01889 598630",
}

# Suppliers who DON'T deliver to site — every PO ships to our own address (they deliver to us and
# we forward). Address used verbatim on the PO's delivery block.
DELIVER_TO_US = {"Plastivan"}
OUR_ADDRESS_LINES = ["Trade Superstore Online", "Unit 8, Alfreton Road", "Derby", "DE21 4ED"]

# Colour cue on the Stage dropdown (an editable grid cell can't have a coloured background, so we
# prefix the label with a coloured dot). Maps the plain Monday label ↔ the coloured display label.
STAGE_DOTS = {"Go To Portal": "🟡", "Needs Review": "🔴", "SEND PO": "🟢", "SEND QUOTE": "🔵"}


def _stage_disp(label):
    if not label:
        return None
    d = STAGE_DOTS.get(label)
    return f"{d} {label}" if d else label


def _stage_plain(disp):
    if not disp:
        return disp
    for d in STAGE_DOTS.values():
        if disp.startswith(d + " "):
            return disp[len(d) + 1:]
    return disp


def _esc(s):
    return html.escape(str(s if s is not None else ""))


def _norm_addr(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _addr_changed(monday_addr, ship):
    """True if the live Shopify shipping postcode or first address line isn't present in the Monday
    address text — i.e. the customer likely changed the delivery address after it synced."""
    if not ship:
        return False
    m = _norm_addr(monday_addr)
    for key in (ship.get("zip"), ship.get("address1")):
        if key and _norm_addr(key) and _norm_addr(key) not in m:
            return True
    return False


def _orders():
    if st.session_state.get("_op_orders") is None:
        with st.spinner("Reading the NEW ORDERS group from Monday…"):
            st.session_state["_op_orders"] = data_sources.fetch_new_orders()
    return st.session_state["_op_orders"]


def _supplier_labels():
    """Suppliers selectable in TradeHub. The LIVE Monday dropdown labels (authoritative order)
    merged with every known supplier from the routing map, so a supplier that's on Monday but
    missing from a stale/failed label fetch (e.g. Permaroof) is still always pickable. Every name
    here is a real Monday label, so writing it back always succeeds."""
    if st.session_state.get("_op_suppliers") is None:
        try:
            live = data_sources.op_board_supplier_labels()
        except Exception:  # noqa: BLE001
            live = []
        known = sorted(set(order_routing.CANON.values()))
        st.session_state["_op_suppliers"] = list(dict.fromkeys([s for s in live if s] + known))
    return st.session_state["_op_suppliers"]


def _live_detail(shopify_id):
    """Lazy-load (and cache) live Shopify line items + fulfilment split for one order."""
    cache = st.session_state.setdefault("_op_detail", {})
    if shopify_id not in cache:
        d = {"lines": [], "split": {}, "error": None}
        try:
            d["lines"] = data_sources.fetch_order_line_items(shopify_id)
        except Exception as e:  # noqa: BLE001
            d["error"] = str(e)[:160]
        try:
            d["split"] = data_sources.fetch_order_fulfillment_split(shopify_id)
        except Exception:  # noqa: BLE001
            pass
        cache[shopify_id] = d
    return cache[shopify_id]


def _suggestion_box():
    with st.expander("💡 Notes / suggestions (saved for Daniela)"):
        st.caption("Anything that doesn't work, or would help — this is **saved for Daniela** to "
                   "review here, and emailed too once email sending is switched on.")
        who = st.text_input("Your name", value=(st.session_state.get("name") or ""),
                            key="op_sugg_who", help="Pre-filled from your login — the note is saved "
                            "under this name so Daniela knows who it's from.")
        msg = st.text_area("What's up?", key="op_sugg_msg", height=110,
                           placeholder="e.g. the supplier dropdown is missing X, or the PO for "
                                       "order 30xxx has the wrong branch…")
        if st.button(":material/save: Save note", key="op_sugg_send", disabled=not msg.strip()):
            saved = False
            try:
                data_sources.op_save_suggestion(who, msg.strip())
                saved = True
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't save the note: " + str(e)[:150])
            emailed = False
            try:                                    # best-effort email (works once Mail.Send is on)
                subj = f"TradeHub note from {who or 'the team'}"
                data_sources.send_supplier_email(FROM_MAILBOX, DANIELA, subj,
                                                 f"From: {who or 'the team'}\n\n{msg.strip()}")
                emailed = True
            except Exception:  # noqa: BLE001
                pass
            if saved:
                st.success("Saved for Daniela." + (" Emailed too." if emailed else
                                                   " (Email is off for now — it's stored here.)"))
        try:
            recent = data_sources.op_load_suggestions(8)
        except Exception:  # noqa: BLE001
            recent = []
        if recent:
            st.markdown("**Recent notes**")
            for r in recent:
                txt = re.sub(r"<[^>]+>", "", r.get("body") or "").strip()
                st.caption(f"{(r.get('created_at') or '')[:10]} — {txt[:220]}")


def _order_label(o):
    """What to show in the grid's 'Order' column. Split parts carry a Monday item name like
    '30107-1' while the order-number column stays '30107' for all three — so prefer the part
    name when it's a '{order_no}-N' split part, else the plain order number."""
    nm = (o.get("name") or "").strip()
    ono = (o.get("order_no") or "").strip()
    if ono and nm.startswith(ono + "-") and nm[len(ono) + 1:].isdigit():
        return nm
    return ono or nm or ""


def _split_parts(o, orders):
    """The sibling split parts of an order (all Monday items whose name is '{order_no}-N'),
    sorted by N. Returns [] when the order isn't a split part."""
    ono = (o.get("order_no") or "").strip()
    nm = (o.get("name") or "").strip()
    if not (ono and nm.startswith(ono + "-") and nm[len(ono) + 1:].isdigit()):
        return []
    sibs = [s for s in orders
            if (s.get("order_no") or "").strip() == ono
            and (s.get("name") or "").strip().startswith(ono + "-")
            and (s.get("name") or "").strip()[len(ono) + 1:].isdigit()]
    return sorted(sibs, key=lambda s: int((s.get("name") or "").strip()[len(ono) + 1:]))


def _parse_monday_items(txt):
    """Turn the Monday 'Order items' text ('Title | Quantity: N | SKU: XXX' per line) into
    [{Item, SKU, Qty}] so SKU and Qty sit in their own columns instead of one messy line."""
    out = []
    for line in (txt or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        qty = sku = ""
        for p in parts[1:]:
            low = p.lower()
            if low.startswith("quantity") and ":" in p:
                qty = p.split(":", 1)[1].strip()
            elif low.startswith("sku") and ":" in p:
                sku = p.split(":", 1)[1].strip()
        out.append({"Item": parts[0] if parts else line, "SKU": sku, "Qty": qty})
    return out


def _canon_sup(s):
    """Normalise a supplier name to ONE canonical key, so the feed/Airtable name and our order
    label match even when they differ (the feed calls it 'LPD', we label orders 'LPD DOORS').
    Uses the routing CANON map (which already knows lpd == lpddoors)."""
    n = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    lbl = order_routing.CANON.get(n)
    return re.sub(r"[^a-z0-9]", "", lbl.lower()) if lbl else n


@st.cache_data(show_spinner=False)
def _pricing():
    """{normalised SKU: {supplier_canon: cost}} from the pricing feed (Airtable-derived).
    Supplier names are canonicalised (see _canon_sup) so 'LPD' in the feed matches 'LPD DOORS'
    on the order."""
    try:
        d = json.load(open("pricing_lookup.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for it in d.get("items", []):
        sku = re.sub(r"[^a-z0-9]", "", (it.get("sku") or "").lower())
        if sku:
            out[sku] = {_canon_sup(o.get("s")): o.get("c") for o in (it.get("offers") or [])}
    # Durable code-side overrides (in the repo, so a feed rebuild can't wipe them) — e.g. UPB's
    # Hardie prices keyed by OUR Shopify SKUs, which UPB's own 'any colour' pricelist SKUs don't
    # match. Fills/overrides the supplier's cost for those SKUs.
    try:
        ov = json.load(open("price_overrides.json", encoding="utf-8"))
        for sup, skus in ov.items():
            if sup in ("_patterns", "_titles") or not isinstance(skus, dict):   # handled in _line_cost
                continue
            sn = _canon_sup(sup)
            for sk, cost in skus.items():
                if isinstance(cost, (int, float)):
                    out.setdefault(re.sub(r"[^a-z0-9]", "", (sk or "").lower()), {})[sn] = cost
    except Exception:  # noqa: BLE001
        pass
    return out


def _price_patterns():
    """{supplier_norm: [(prefix, cost)]} family price patterns — a supplier that prices by product
    TYPE not colour (e.g. UPB: all trims one price, all boards one price). ALWAYS the same
    supplier's own price; NEVER another supplier's."""
    try:
        ov = json.load(open("price_overrides.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for sup, rules in (ov.get("_patterns") or {}).items():
        sn = re.sub(r"[^a-z0-9]", "", (sup or "").lower())
        out[sn] = [(re.sub(r"[^a-z0-9]", "", (r.get("prefix") or "").lower()),
                    re.sub(r"[^a-z0-9]", "", (r.get("suffix") or "").lower()), r.get("cost"))
                   for r in (rules or []) if isinstance(r.get("cost"), (int, float))]
    return out


def _price_titles():
    """{supplier_norm: [(needle_norm, cost)]} — price a line by its PRODUCT TITLE, for products
    whose Shopify variant carries no SKU (e.g. UPB 'VL Coloured Fixing Screws'). Same supplier's
    own price only; from price_overrides.json '_titles'."""
    try:
        ov = json.load(open("price_overrides.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for sup, rules in (ov.get("_titles") or {}).items():
        sn = re.sub(r"[^a-z0-9]", "", (sup or "").lower())
        out[sn] = [(re.sub(r"[^a-z0-9]", "", (r.get("contains") or "").lower()), r.get("cost"))
                   for r in (rules or []) if isinstance(r.get("cost"), (int, float))]
    return out


def _sole_feed_supplier(sku):
    """If the pricing feed prices this SKU from exactly ONE supplier, return that supplier's label
    (routing fallback for a house-brand line whose Shopify vendor reveals no supplier). Matches the
    exact SKU, else colour-suffix variants (feed has WEH5460-40RST-WH etc. for order
    WEH5460-40RST). None if unpriced or ambiguous (2+ suppliers)."""
    key = re.sub(r"[^a-z0-9]", "", (sku or "").lower())
    if len(key) < 5:
        return None
    pr = _pricing()
    offers = pr.get(key)
    if not offers:                      # colour-suffix tolerance (order SKU vs feed's -WH/-PCH etc.)
        offers = {}
        for k, v in pr.items():
            if len(k) >= 5 and (k.startswith(key) or key.startswith(k)):
                offers.update(v)
    excl = {re.sub(r"[^a-z0-9]", "", s.lower()) for s in order_routing.EXCLUDED_SUPPLIERS}
    sups = {s for s, c in (offers or {}).items()
            if isinstance(c, (int, float)) and s not in excl}   # ignore paused suppliers (NBP)
    return order_routing.CANON.get(next(iter(sups))) if len(sups) == 1 else None


def _line_cost(sku, supplier, name=None):
    """The routed supplier's OWN cost for a SKU (or, failing that, its product title), or None.
    STRICT RULE: a supplier's cost is only ever that supplier's own price — never another
    supplier's (Daniela, 2026-08-18). If the supplier has no price the line stays unpriced (→
    packing slip), it never borrows another's."""
    key = re.sub(r"[^a-z0-9]", "", (sku or "").lower())
    sup = _canon_sup(supplier)
    c = (_pricing().get(key) or {}).get(sup)
    if isinstance(c, (int, float)):
        return c
    # Same-supplier family pattern (e.g. UPB prices all trims/boards one price per type). Still the
    # SAME supplier's own price only. Optional suffix distinguishes families that share a prefix but
    # differ in price (e.g. Squaredeal HardiePlank Cedar -CE vs Smooth -SM).
    for prefix, suffix, cost in _price_patterns().get(sup, []):
        if prefix and key.startswith(prefix) and (not suffix or key.endswith(suffix)):
            return cost
    # Title fallback — for products with no/uncatalogued SKU. Same supplier's own price only.
    nm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if nm:
        for needle, cost in _price_titles().get(sup, []):
            if needle and needle in nm:
                return cost
    return None


def _money(x):
    return f"£{float(x):,.2f}"


# ex-VAT delivery-to-us that we're confident of: {supplier_norm: (flat_charge, free_over or None)}.
# Suppliers NOT here get £0 on the PO for now (interim) and are listed for Daniela to confirm.
DELIVERY_TO_US = {
    "upb": (17.50, 100), "nbp": (17.00, 250), "eurocell": (12.50, 100),
    "travisperkins": (24.99, 100), "gap": (20.83, 150), "pjh": (37.50, 1000),
    "molan": (23.74, None), "decor8": (5.99, 50), "deanta": (8.00, None),
    "chasehardware": (10.00, None), "bricklink": (16.99, 100),
}


def _delivery_charge(supplier, goods):
    """(amount, known). Known suppliers use their flat/free-over rule; unknown → £0 interim."""
    key = re.sub(r"[^a-z0-9]", "", (supplier or "").lower())
    if key not in DELIVERY_TO_US:
        return 0.0, False
    flat, free_over = DELIVERY_TO_US[key]
    if free_over is not None and goods >= free_over:
        return 0.0, True
    return float(flat), True


def _po_desc(it):
    """Description for a PO/slip line: the product name, with the customer's chosen VARIANT
    (colour/size) on its OWN line so it's unmistakable to the supplier (the renderer honours the
    newline and wraps each line inside its box)."""
    base = (it.get("Item") or "").strip()
    v = (it.get("Variant") or "").strip()
    return f"{base}\nVariant: {v}" if v and v.lower() not in base.lower() else base


def _build_doc(o, delivery_override=None, notes_extra=None, items_override=None,
               address_override=None):
    """Assemble the (kind, doc) for order `o`: a priced PO for email-order suppliers, a packing
    slip (no prices) for portal / in-house / unidentified. Delivery address = Shopify shipping.
    Overrides (from Natasha's 'Adjust' panel) let her fix anything the automation missed:
    delivery_override = a corrected carriage £; notes_extra = extra note line(s);
    items_override = edited line list [{SKU, Item, Qty, Cost}]; address_override = edited address."""
    supplier = (o.get("supplier") or "").strip()
    sid = (o.get("shopify_id") or "").strip()
    ship = _ship(sid) if sid else None
    # Ship to OUR address (not the customer) when: the supplier doesn't deliver to site (e.g.
    # Plastivan), OR the order is marked "TO POST" (we bring it in and post it ourselves). A
    # hand-edited Adjust address still wins.
    to_post = (o.get("branch") or "").strip().upper().startswith("TO POST")
    deliver_to_us = (supplier in DELIVER_TO_US or to_post) and not address_override
    dl = list(OUR_ADDRESS_LINES) if deliver_to_us else (
        address_override or (ship or {}).get("lines")
        or [x.strip() for x in (o.get("address") or "").split(",") if x.strip()])
    order_no = o.get("order_no") or o.get("name") or ""
    contact = f"{o.get('customer') or ''}".strip()
    phone = (ship or {}).get("phone") or o.get("phone") or ""
    if supplier == "Eurocell":
        phone = "0333 090 9217"    # Eurocell POs: ALWAYS our number, never the customer's
    if to_post:
        notes = [f"Deliver to the address above (Trade Superstore Online) — we post this small order "
                 "to the customer ourselves.",
                 f"Quote TSO order {order_no} on all paperwork."]
    elif deliver_to_us:
        notes = [f"Deliver to the address above — {supplier} does not deliver to site; we forward "
                 "to the customer.",
                 f"Quote TSO order {order_no} on all paperwork."]
    else:
        notes = [f"Kerbside delivery to: {contact}" + (f", {phone}" if phone else "") + ".",
                 f"Quote TSO order {order_no} on all paperwork."]
    if notes_extra:
        notes += [n for n in notes_extra if n and str(n).strip()]

    items = items_override if items_override is not None else _parse_monday_items(o.get("items"))
    # Ensure the customer's chosen VARIANT (colour/size) is on every PO line. Monday's order text can
    # predate this / omit it, so pull the folded product+variant title from Shopify and match by SKU.
    # (Skipped when the processor hand-edited the lines in Adjust — respect their wording.)
    if sid and items_override is None:
        _sl_cache = st.session_state.setdefault("_op_shoplines", {})
        if sid not in _sl_cache:
            try:
                _sl_cache[sid] = data_sources.fetch_order_line_items(sid)
            except Exception:  # noqa: BLE001
                _sl_cache[sid] = []
        _by_sku = {re.sub(r"[^a-z0-9]", "", (sl.get("sku") or "").lower()): sl
                   for sl in (_sl_cache[sid] or []) if sl.get("sku")}
        for _it in items:
            sl = _by_sku.get(re.sub(r"[^a-z0-9]", "", (_it.get("SKU") or "").lower()))
            if sl:                                # base title + variant kept separate for the PO
                _it["Item"] = (sl.get("base_title") or sl.get("title") or "").strip()
                _it["Variant"] = (sl.get("variant") or "").strip()
    is_portal = supplier in order_routing.PORTAL
    in_house = supplier in ("", "SAMPLES", "CLEARANCE")

    # Price every line for an email-order supplier. RULE: all prices in → PO; ANY price missing →
    # packing slip (never a PO with 'confirm' prices, and never another supplier's price). When a
    # line can't be priced we NOTE it by name on the slip so it can be filled in.
    po_lines, goods, unpriced_items = [], 0.0, []
    for it in items:
        qty = it.get("Qty") or "1"
        try:
            q = float(qty)
        except (TypeError, ValueError):
            q = 1
        cost = it.get("Cost") if isinstance(it.get("Cost"), (int, float)) \
            else _line_cost(it.get("SKU"), supplier, it.get("Item"))
        if cost is None:
            unpriced_items.append((it.get("Item") or it.get("SKU") or "?").strip())
        else:
            lt = round(cost * q, 2)
            goods += lt
            po_lines.append([(it.get("SKU") or "-"), _po_desc(it), qty, _money(cost),
                             _money(lt)])

    make_slip = is_portal or in_house or bool(unpriced_items)

    if make_slip:
        lines = [[(it.get("SKU") or "-"), _po_desc(it), (it.get("Qty") or "1")]
                 for it in items]
        if is_portal:
            head = ["Portal order - place on the supplier portal."]
        elif in_house:
            head = ["In-house — post / fulfil from Head Office."]
        else:
            head = []            # no internal price chatter on the supplier-facing slip
        return "slip", {"order": order_no, "po": order_no, "supplier": supplier, "dl": dl,
                        "lines": lines, "notes": head + notes, "unpriced": unpriced_items,
                        "contact": (contact + (f" - {phone}" if phone else "")) or "TSO"}

    # PO — every line priced. VAT is ALWAYS 20%; a missing delivery rate is just £0.
    dlines = [{"sku": it.get("SKU"), "description": it.get("Item"),
               "qty": (float(it.get("Qty")) if str(it.get("Qty") or "").replace(".", "", 1)
                       .isdigit() else 1)}
              for it in items]
    ship_pc = {"postcode": (ship or {}).get("zip"), "country": (ship or {}).get("country")}
    if delivery_override is not None:
        deliv = float(delivery_override)
    elif to_post:
        deliv = 0.0        # TO POST → GAP/Eurocell/TP/UPB deliver to US free; we pay only postage
    else:
        _d = delivery_rules.expected_delivery(supplier, goods, ship_pc, dlines)
        deliv = _d if isinstance(_d, (int, float)) else 0.0
    vat = round((goods + deliv) * 0.20, 2)
    total_inc_vat = round(goods + deliv + vat, 2)
    sums = [["Goods (ex VAT)", _money(goods), False], ["Delivery (ex VAT)", _money(deliv), False],
            ["VAT @20%", _money(vat), False],
            ["Total (inc VAT)", _money(total_inc_vat), True]]
    return "po", {"order": order_no, "po": order_no, "supplier": supplier, "dl": dl,
                  "acct": order_docs.account_for(supplier), "lines": po_lines, "sums": sums,
                  "total": total_inc_vat, "goods": round(goods, 2),
                  "notes": notes, "contact": (contact + (f" - {phone}" if phone else "")) or "TSO"}


DEL_METHOD_COL = "color_mm06fnhe"    # Orders board "Del Method" status column


def _mark_del_method(iid, supplier):
    """Samples orders are posted from Head Office, so flag the Del Method column 'To Post'.
    Best-effort — never breaks processing."""
    if (supplier or "").strip().upper() == "SAMPLES":
        try:
            data_sources.op_set_status(iid, "To Post", column_id=DEL_METHOD_COL)
        except Exception:  # noqa: BLE001
            pass


# Local (to-us, Derby/Midlands) branch email for suppliers not in the branch finder — used when we
# bring a "TO POST" order in to ourselves rather than dropship it.
_DERBY_BRANCH_EMAIL = {"GAP": "derby@gaptrade.com",
                       "UPB": "martinmelaney@upbuildingproducts.com"}   # UPB Aldridge (nearest us)


def _all_touch_up_paint(items):
    """True if EVERY line on the order is James Hardie touch-up paint — the one UPB item small
    enough that we post it ourselves (UPB isn't otherwise a posting supplier)."""
    if not items:
        return False
    return all(any(w in (it.get("Item") or it.get("title") or "").lower()
                   for w in ("touch up paint", "touch-up paint")) for it in items)


def _force_to_post(iid, supplier, o=None):
    """Manually mark an order TO POST: Branch = 'TO POST' (so the PO ships to OUR address) and set
    the ordering email — the local DERBY branch for Eurocell/GAP/Travis Perkins (and UPB Aldridge);
    a head-office supplier keeps its existing head-office email (left untouched)."""
    email = None
    if supplier in ("Eurocell", "Travis Perkins"):
        try:
            import branch_finder
            email = (branch_finder.nearest_branch("DE21 4ED", supplier) or {}).get("email")
        except Exception:  # noqa: BLE001
            email = None
    elif supplier in _DERBY_BRANCH_EMAIL:
        email = _DERBY_BRANCH_EMAIL[supplier]
    branch_lbl = "TO POST - UPB Aldridge" if supplier == "UPB" else "TO POST"
    if email:                              # Eurocell/GAP/TP/UPB → the Derby branch email
        data_sources.op_set_branch(iid, branch=branch_lbl, email=email)
        if o is not None:
            o["branch"] = branch_lbl
            o["branch_email"] = email
    else:                                  # head-office supplier → keep it at its correct PO email
        data_sources.op_set_branch(iid, branch=branch_lbl)
        if o is not None:
            o["branch"] = branch_lbl
        _fix_po_email(iid, supplier, o)    # e.g. Vista is always orders@vistaeng.co.uk


_UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def _max_dim_mm(text):
    """Largest length dimension (mm) stated in a product title, else 0. Handles '3600mm', '3.6m',
    '1981 x 762mm', '50mm x 50mm'."""
    best = 0.0
    for m in re.finditer(r"([\d.]+(?:\s*[x×]\s*[\d.]+)*)\s*(mm|cm|m)\b", (text or "").lower()):
        unit = _UNIT_MM.get(m.group(2), 0)
        for n in re.findall(r"[\d.]+", m.group(1)):
            try:
                best = max(best, float(n) * unit)
            except ValueError:
                pass
    return best


# Small consumables/hardware that always post fine (checked FIRST, so "door handle" is postable
# even though "door" is a never-post word). Includes rolled tape and small touch-up paint tins.
_ALWAYS_POST = ("tape", "coil", "touch up paint", "touch-up paint", "handle", "spindle",
                "escutcheon", "hinge", "screw", "fixing", "pin", "clip", "bracket", "cap",
                "washer", "bolt", "gasket", "sealant", "silicone", "adhesive", "sample", "key",
                "latch", "knob", "letterplate", "numeral")
# Bulky / heavy things that must NEVER be posted — fireplaces, sheets, doors, furniture, bathrooms.
_NEVER_POST = ("fireplace", "surround", "radiator", "stove", "sleeper", "door", "panel", "board",
               "sheet", "cladding", "bath", "wardrobe", "bed", "drawers", "table", "chair", "sofa",
               "cill", "gate", "ladder", "stair", "canopy", "decking", "fence", "membrane", "felt",
               "furniture", "worktop", "mirror", "cistern", "basin", "toilet", "shower", "tray",
               "flooring", "tile", "plank", "beam", "joist", "pergola")
# TO POST only applies to these suppliers (small roofline/hardware goods, ordered in to our Derby
# branch). Never bulky suppliers like Carron.
_POSTABLE_SUPPLIERS = {"Eurocell", "GAP", "Travis Perkins"}
_POST_MAX_MM = 600            # "fits in a small box" — a stated dimension must be within this


def _is_postable(items):
    """True ONLY if every line really fits in a small postable box. A line qualifies on a small-
    hardware keyword or a stated dimension within _POST_MAX_MM; a bulky keyword — or NO stated size
    at all — disqualifies it. So a 'Fireplace Surround' (bulky word, no dimension) is never
    postable, while 'EPDM Tape 20m' or a '40mm window handle' is."""
    for it in (items or []):
        title = (it.get("Item") or it.get("title") or "").lower()
        if any(w in title for w in _ALWAYS_POST):
            continue
        if any(w in title for w in _NEVER_POST):
            return False
        dim = _max_dim_mm(title)
        if dim == 0 or dim > _POST_MAX_MM:    # no stated size, or too big for a small box → don't post
            return False
    return True


def _apply_post_if_cheaper(iid, supplier, items, sid, o=None):
    """If it's cheaper to POST a small order ourselves than have the supplier deliver it, mark the
    Branch column 'TO POST' (NOT the Del Method status, which would move the order on) and point the
    order at where we bring stock in to OURSELVES — the local Derby branch for Eurocell / Travis
    Perkins, the supplier's central email otherwise. Trigger: postable (<=1 m) AND the supplier's
    delivery would cost MORE than the shipping the customer paid. Returns True if marked to post."""
    # Eligible suppliers: Eurocell/GAP/Travis Perkins for small items — plus UPB, but ONLY when the
    # whole order is James Hardie touch-up paint.
    eligible = supplier in _POSTABLE_SUPPLIERS or (supplier == "UPB" and _all_touch_up_paint(items))
    if not (eligible and sid and _is_postable(items)):
        return False
    try:
        sh = data_sources.fetch_order_shipping(sid) or {}
    except Exception:  # noqa: BLE001
        return False
    cust = sh.get("shipping")
    if not isinstance(cust, (int, float)):
        return False
    goods = 0.0
    for it in items:
        c = _line_cost(it.get("SKU") or it.get("sku"), supplier, it.get("Item") or it.get("title"))
        if isinstance(c, (int, float)):
            try:
                goods += c * float(it.get("Qty") or it.get("qty") or 1)
            except (TypeError, ValueError):
                goods += c
    dlines = [{"sku": it.get("SKU") or it.get("sku"),
               "description": it.get("Item") or it.get("title"),
               "qty": (float(it.get("Qty") or it.get("qty"))
                       if str(it.get("Qty") or it.get("qty") or "").replace(".", "", 1).isdigit()
                       else 1)} for it in items]
    d = delivery_rules.expected_delivery(
        supplier, goods, {"postcode": sh.get("postcode"), "country": sh.get("country")}, dlines)
    if not (isinstance(d, (int, float)) and d > cust + 0.01):
        return False
    email = None                                     # Derby branch email for branch suppliers
    if supplier in ("Eurocell", "Travis Perkins"):
        try:
            import branch_finder
            email = (branch_finder.nearest_branch("DE21 4ED", supplier) or {}).get("email")
        except Exception:  # noqa: BLE001
            email = None
    elif supplier in _DERBY_BRANCH_EMAIL:
        email = _DERBY_BRANCH_EMAIL[supplier]
    branch_lbl = "TO POST - UPB Aldridge" if supplier == "UPB" else "TO POST"
    try:
        data_sources.op_set_branch(iid, branch=branch_lbl, email=email)   # email=None → keep central
    except Exception:  # noqa: BLE001
        return False
    if o is not None:
        o["branch"] = branch_lbl
        if email:
            o["branch_email"] = email
    return True


def _write_po_total(iid, kind, doc):
    """Write the generated PO's inc-VAT total to Monday `numbers6` (£ to supplier), so the board
    shows what the order costs from the supplier. POs only — a packing slip has no prices, so we
    leave numbers6 untouched. Best-effort: a Monday write hiccup never breaks processing."""
    if kind != "po":
        return
    total = (doc or {}).get("total")
    if isinstance(total, (int, float)):
        try:
            data_sources.set_order_number(iid, OP["cost_supplier"], round(total, 2))
        except Exception:  # noqa: BLE001
            pass


def _to_float(x):
    try:
        return float(str(x).replace(",", "").replace("£", "").strip())
    except (TypeError, ValueError):
        return None


def _process_split(o, res):
    """Execute a split on Monday: for each supplier group, make a part item (1st reuses the
    original, rest are duplicates), rename to {order}-N, set its lines / supplier / branch / stage,
    allocate the sell total by line value, generate + attach that part's PO/slip. Returns a
    summary string. (The Shopify fulfilment split is NOT done here — flagged for manual.)"""
    sid = (o.get("shopify_id") or "").strip()
    order_no = o.get("order_no") or o.get("name") or ""
    groups = list(res.get("groups", {}).items())          # [(route, [lines]), ...]
    if len(groups) < 2:
        return "not actually a split"
    OP = data_sources.OP_COLS
    try:
        pc = (_ship(sid) or {}).get("zip")                # shipping postcode ('zip') for branches
    except Exception:  # noqa: BLE001
        pc = None

    def sub(lines):
        return sum((l.get("line_subtotal") or 0) for l in lines)

    total_sub = sub(res.get("lines") or []) or 0
    orig_sell = _to_float(o.get("sell"))
    n = len(groups)
    allocated = 0.0
    parts, date_str = [], datetime.date.today().strftime("%d %B %Y")

    for idx, (route, glines) in enumerate(groups, start=1):
        gsup = glines[0].get("supplier")
        # sell allocation by line value; last part gets the remainder so parts sum to the original
        if orig_sell is not None and total_sub:
            psell = round(orig_sell - allocated, 2) if idx == n \
                else round(orig_sell * sub(glines) / total_sub, 2)
            if idx < n:
                allocated += psell
        else:
            psell = None
        # supplier goods cost inc VAT, only if every line is priced for that supplier
        pcost, priced = 0.0, True
        for l in glines:
            c = _line_cost(l.get("sku"), gsup or "")
            if c is None:
                priced = False
                break
            q = l.get("qty") if isinstance(l.get("qty"), (int, float)) else 1
            pcost += c * q
        pcost = round(pcost * 1.2, 2) if priced else None
        try:
            pid = o["item_id"] if idx == 1 else data_sources.op_duplicate_item(o["item_id"])
        except Exception as e:  # noqa: BLE001
            return f"couldn't duplicate the Monday item: {str(e)[:60]}"
        items_text = "\n".join(
            f"{l.get('title')} | Quantity: {l.get('qty')} | SKU: {l.get('sku') or ''}"
            for l in glines)
        try:
            data_sources.set_order_number(pid, "name", f"{order_no}-{idx}")
            data_sources.set_order_number(pid, OP["items"], items_text)
            if gsup:
                data_sources.op_set_supplier(pid, gsup)
                # Resolve THIS supplier's own branch + email and ALWAYS overwrite. Duplicated parts
                # inherit the original (first supplier's) branch/email, so a GAP or Eurocell part
                # would otherwise keep "UPB Aldridge" + UPB's email — clear/replace it every time.
                gbranch = glines[0].get("branch")
                gemail = glines[0].get("branch_email")
                gphone = None
                if not (gbranch or gemail):
                    gbranch, gemail, gphone = _resolve_branch(gsup, pc)
                data_sources.op_set_branch(pid, branch=(gbranch or ""), email=(gemail or ""),
                                           phone=(gphone or ""))
                _fix_po_email(pid, gsup)          # Molan/Vista email override (also overwrites)
            else:
                data_sources.op_set_branch(pid, branch=route, email="", phone="")  # clear inherited
            _mark_del_method(pid, gsup or route)     # samples part → "To Post" on Del Method
            data_sources.op_set_status(pid, order_routing._stage_for(
                gsup, route, glines[0].get("quote"), glines[0].get("portal")))
            if psell is not None:
                data_sources.set_order_number(pid, OP["sell"], psell)
            # numbers6 (£ to supplier) is set from the generated PO's inc-VAT total below.
        except Exception as e:  # noqa: BLE001
            parts.append(f"{order_no}-{idx} {gsup or route}: Monday write failed")
            continue
        temp = {"item_id": pid, "order_no": f"{order_no}-{idx}", "name": f"{order_no}-{idx}",
                "supplier": gsup or "", "shopify_id": sid, "customer": o.get("customer"),
                "address": o.get("address"), "phone": o.get("phone"), "items": items_text}
        try:
            kind, doc = _build_doc(temp)
            pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
                doc, date_str=date_str)
            nm = f"{'PO' if kind == 'po' else 'PackingSlip'}_{order_no}-{idx}_" \
                 "Trade_Superstore_Online.pdf"
            rr = data_sources.op_upload_po(pid, pdf, nm)
            if kind == "po":
                _write_po_total(pid, kind, doc)      # numbers6 = the PO's inc-VAT total
            else:
                # A duplicated split part inherits the original's numbers6; a packing slip has no
                # price, so CLEAR it rather than leave the wrong inherited cost showing.
                data_sources.set_order_number(pid, OP["cost_supplier"], "")
            dm = "doc ✓" if rr.get("ok") else "doc unverified"
        except ValueError:
            dm = "doc BLOCKED"
        except Exception:  # noqa: BLE001
            dm = "doc error"
        parts.append(f"{order_no}-{idx} → {gsup or route} ({dm})")

    # Shopify fulfilment split — group each supplier's SKUs onto their own fulfilment order
    # (all UPB together, all GAP together). Samples / in-house lines are left alone (we post them).
    fmsg = ""
    try:
        key_sup = {}
        for l in res.get("lines", []):
            sup = l.get("supplier")
            if not sup:
                continue
            if l.get("sku"):
                key_sup["sku:" + re.sub(r"[^a-z0-9]", "", l["sku"].lower())] = sup
            if l.get("title"):
                key_sup["ttl:" + re.sub(r"[^a-z0-9]", "", l["title"].lower())] = sup
        if sid and key_sup:
            acts = data_sources.split_fulfillment_by_supplier(sid, key_sup)
            if acts:
                fmsg = " · Shopify fulfilment: " + "; ".join(acts)
    except Exception as e:  # noqa: BLE001
        fmsg = f" · ⚠ Shopify fulfilment split failed: {str(e)[:70]}"
    return "split into " + str(n) + " parts: " + "; ".join(parts) + fmsg


_PO_EMAIL_BY_NORM = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in SUPPLIER_PO_EMAIL.items()}
_HEAD_OFFICE_BY_NORM = {re.sub(r"[^a-z0-9]", "", k.lower()): v
                        for k, v in SUPPLIER_HEAD_OFFICE_PHONE.items()}


def _fix_po_email(iid, supplier, o=None):
    """Set the supplier's known PO email AND head-office contact number after the supplier is set
    (overriding any wrong/blank Monday auto-fill). Branch orders — Eurocell/Travis Perkins — keep
    the nearest branch's email + number (set from the branch finder) instead, as they're in neither
    map. Matched case/spacing-insensitively ('Newplas'/'newplas', 'LPD DOORS'/'LPD Doors')."""
    key = re.sub(r"[^a-z0-9]", "", (supplier or "").lower())
    em = _PO_EMAIL_BY_NORM.get(key)
    ph = _HEAD_OFFICE_BY_NORM.get(key)
    # Don't clobber a quote email the router already set (Storm→Molan uses quotes@molan-uk.com for
    # the quote, not Molan's orders@ PO address).
    if em and o and (o.get("branch_email") or "").lower().startswith("quotes@"):
        em = None
    try:
        if em:
            data_sources.op_set_branch(iid, email=em)
            if o is not None:
                o["branch_email"] = em
        if ph:
            data_sources.op_set_branch(iid, phone=ph)
            if o is not None:
                o["branch_phone"] = ph
    except Exception:  # noqa: BLE001
        pass


def _fix_lpd_home_email(iid, supplier, sid, o=None, lines=None):
    """LPD's Home Furniture range (Shopify tag 'Home Furniture', vendor LPD) is ordered from LPD's
    home division, not the doors branch — send those POs to orders@lpdhome.co.uk instead of
    sales@lpddoors.co.uk. Run AFTER _fix_po_email so it overrides the default LPD email."""
    if _canon_sup(supplier) != _canon_sup("LPD DOORS"):
        return
    if lines is None:
        if not sid:
            return
        try:
            lines = data_sources.fetch_order_lines_with_vendor(sid)
        except Exception:  # noqa: BLE001
            return
    if not any("home furniture" in (t or "").lower()
               for ln in (lines or []) for t in (ln.get("tags") or [])):
        return
    try:
        data_sources.op_set_branch(iid, email="orders@lpdhome.co.uk")
        if o is not None:
            o["branch_email"] = "orders@lpdhome.co.uk"
    except Exception:  # noqa: BLE001
        pass


def _resolve_branch(supplier, postcode):
    """(branch, email, phone) for a chosen supplier + postcode: nearest branch for Eurocell/Travis
    Perkins, the UPB Hardie depot for UPB, else (None, None, None)."""
    if not postcode:
        return None, None, None
    if supplier in ("Eurocell", "Travis Perkins"):
        nb = branch_finder.nearest_branch(postcode, supplier)
        if nb and nb.get("branch_name"):
            return nb["branch_name"], nb.get("email"), nb.get("phone")
    if supplier == "UPB":
        hr = order_routing.hardie_route(postcode)
        return hr.get("branch"), hr.get("branch_email"), None
    return None, None, None


def _stage_for_supplier(supplier):
    if supplier in order_routing.PORTAL:
        return "Go To Portal"
    if supplier in order_routing.QUOTE_FIRST:
        return "Needs Quote"
    return "Needs Review"


def _merge_parts(selected, target_supplier, all_siblings):
    """Merge selected split parts of one order into a SINGLE part fulfilled by `target_supplier`
    (e.g. UPB can also cover the GAP items → one delivery). Combines their line items, sums the
    sell, sets the supplier + recomputes cost, regenerates the PO, and ARCHIVES the absorbed parts
    (recoverable on Monday). If that leaves the order with a single part, drops the '-N' suffix.
    Returns a summary string. Does NOT touch the Shopify fulfilment split."""
    if len(selected) < 2:
        return "pick at least two parts to merge"
    OP = data_sources.OP_COLS
    order_no = (selected[0].get("order_no") or "").strip()
    # survivor: a selected part already on the target supplier, else the lowest-numbered one
    survivor = next((p for p in selected if (p.get("supplier") or "") == target_supplier),
                    selected[0])
    iid = survivor["item_id"]
    absorbed = [p for p in selected if p["item_id"] != iid]

    items_text = "\n".join((p.get("items") or "").strip() for p in selected
                           if (p.get("items") or "").strip())
    sell = round(sum((_to_float(p.get("sell")) or 0.0) for p in selected), 2)

    # supplier cost inc VAT for ALL merged lines at the target supplier's prices (blank if any gap)
    pcost, priced = 0.0, True
    for it in _parse_monday_items(items_text):
        c = _line_cost(it.get("SKU"), target_supplier)
        if c is None:
            priced = False
            break
        try:
            q = float(it.get("Qty") or 1)
        except Exception:  # noqa: BLE001
            q = 1
        pcost += c * q
    pcost = round(pcost * 1.2, 2) if priced else None

    sid = (survivor.get("shopify_id") or "").strip()
    try:
        pc = (_ship(sid) or {}).get("zip")           # shipping postcode is under 'zip'
    except Exception:  # noqa: BLE001
        pc = None
    branch, bemail, bphone = _resolve_branch(target_supplier, pc)
    # Fall back to the survivor's existing branch/email ONLY if that part was ALREADY the target
    # supplier — never borrow a DIFFERENT supplier's branch (e.g. merging to UPB must not keep the
    # survivor's Eurocell Crawley branch when the UPB depot couldn't be re-resolved). Better to leave
    # it blank for the processor than to send the PO to the wrong supplier's branch.
    if (target_supplier in ("Eurocell", "Travis Perkins", "UPB") and not (branch or bemail)
            and (survivor.get("supplier") or "") == target_supplier):
        branch = branch or survivor.get("branch")
        bemail = bemail or survivor.get("branch_email")

    data_sources.set_order_number(iid, OP["items"], items_text)
    data_sources.op_set_supplier(iid, target_supplier)
    # Always overwrite branch + email + phone for the target supplier (clear if it has none) so the
    # merged part never keeps a previous supplier's branch/email.
    data_sources.op_set_branch(iid, branch=(branch or ""), email=(bemail or ""),
                               phone=(bphone or ""))
    _fix_po_email(iid, target_supplier)
    data_sources.op_set_status(iid, _stage_for_supplier(target_supplier))
    data_sources.set_order_number(iid, OP["sell"], sell)
    # numbers6 (£ to supplier) is set from the generated PO's inc-VAT total below.

    survivor = {**survivor, "items": items_text, "supplier": target_supplier,
                "branch": branch, "branch_email": bemail, "sell": sell}
    try:
        kind, doc = _build_doc(survivor)
        pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
            doc, date_str=datetime.date.today().strftime("%d %B %Y"))
        nm = f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_" \
             "Trade_Superstore_Online.pdf"
        rr = data_sources.op_upload_po(iid, pdf, nm)
        _write_po_total(iid, kind, doc)          # numbers6 = the PO's inc-VAT total
        docmsg = "PO/slip ✓" if rr.get("ok") else "doc unverified"
    except ValueError:
        docmsg = "doc blocked — a price/field is missing (fix in Adjust)"
    except Exception as e:  # noqa: BLE001
        docmsg = "doc error: " + str(e)[:40]

    for p in absorbed:
        try:
            data_sources.op_archive_item(p["item_id"])
        except Exception as e:  # noqa: BLE001
            return (f"merged onto {survivor.get('name')} ({docmsg}) but couldn't archive "
                    f"{p.get('name')}: {str(e)[:50]} — archive it by hand on Monday")

    remaining = len(all_siblings) - len(absorbed)
    final_name = survivor.get("name")
    if remaining == 1:                                   # order is whole again → drop the -N suffix
        try:
            data_sources.set_order_number(iid, "name", order_no)
            final_name = order_no
        except Exception:  # noqa: BLE001
            pass
    return (f"Merged {', '.join(p.get('name') for p in selected)} → {final_name} "
            f"({target_supplier}, {docmsg}). Archived: {', '.join(p.get('name') for p in absorbed)}.")


def _process_current(o):
    """Process ONE order using the supplier already chosen on it (a manual override) — resolve the
    branch, set supplier/branch/stage on Monday, generate the PO/slip and verified-attach. Does NOT
    re-route, so your dropdown choice is honoured. Returns a status string."""
    iid = o["item_id"]
    sid = (o.get("shopify_id") or "").strip()
    supplier = (o.get("supplier") or "").strip()
    if not supplier:
        return "Pick a supplier in the dropdown first."
    pc = None
    if sid:
        try:
            pc = (data_sources.fetch_order_shipping(sid) or {}).get("postcode")
        except Exception:  # noqa: BLE001
            pc = None
    br, em, ph = _resolve_branch(supplier, pc)
    stage = _stage_for_supplier(supplier)
    try:
        data_sources.op_set_supplier(iid, supplier)
        if br or em or ph:
            data_sources.op_set_branch(iid, branch=br, email=em, phone=ph)
            if br:
                o["branch"] = br
            if em:
                o["branch_email"] = em
        _fix_po_email(iid, supplier, o)           # correct email for Molan/Vista etc.
        _fix_lpd_home_email(iid, supplier, sid, o)   # LPD Home Furniture → orders@lpdhome.co.uk
        _apply_post_if_cheaper(iid, supplier, _parse_monday_items(o.get("items")), sid, o)
        data_sources.op_set_status(iid, stage)
        o["stage"] = stage
    except Exception as e:  # noqa: BLE001
        return "Monday write failed: " + str(e)[:80]
    try:
        kind, doc = _build_doc(o)
        pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
            doc, date_str=datetime.date.today().strftime("%d %B %Y"))
        nm = f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_" \
             "Trade_Superstore_Online.pdf"
        r = data_sources.op_upload_po(iid, pdf, nm)
        _write_po_total(iid, kind, doc)          # numbers6 = the PO's inc-VAT total
        docmsg = f"{kind.upper()} attached ✓" if r.get("ok") else f"{kind} attach UNVERIFIED"
    except ValueError:
        docmsg = "doc BLOCKED — a field is missing (use Adjust)"
    except Exception as e:  # noqa: BLE001
        docmsg = "doc error: " + str(e)[:50]
    return f"{supplier}" + (f" ({br})" if br else "") + f" · stage {stage} · {docmsg}"


def _process_one(o):
    """Route → apply supplier/branch/stage to Monday → generate the PO/slip → verified-attach.
    Skips splits and un-routable orders (flagged for a human). Never emails a supplier. Returns a
    result row for the summary table."""
    iid = o["item_id"]
    sid = (o.get("shopify_id") or "").strip()
    tag = o.get("order_no") or o.get("name") or iid
    if (o.get("stage") or "").strip() != PLACE_ORDER:      # only ever process unprocessed orders
        return {"Order": tag, "Supplier": o.get("supplier") or "",
                "Result": f"already {(o.get('stage') or '—')} — skipped"}
    if not sid:
        return {"Order": tag, "Supplier": "", "Result": "no Shopify ID — skipped"}
    routes = st.session_state.setdefault("_op_routes", {})
    res = routes.get(iid)
    if res is None:
        try:
            lines = data_sources.fetch_order_lines_with_vendor(sid)
            try:
                pc = (data_sources.fetch_order_shipping(sid) or {}).get("postcode")
            except Exception:  # noqa: BLE001
                pc = None
            res = order_routing.route_order(lines, postcode=pc, sku_supplier=_sole_feed_supplier)
            routes[iid] = res
        except Exception as e:  # noqa: BLE001
            return {"Order": tag, "Supplier": "", "Result": "couldn't route: " + str(e)[:60]}
    if not res.get("lines"):
        return {"Order": tag, "Supplier": "", "Result": "no lines to route"}
    if res.get("split"):
        return {"Order": tag, "Supplier": order_routing.summary(res),
                "Result": _process_split(o, res)}
    sup, route = res.get("overall_supplier"), res.get("route")
    if route == "PICK":
        return {"Order": tag, "Supplier": "", "Result": "couldn't identify supplier — pick manually"}
    try:
        if sup:
            data_sources.op_set_supplier(iid, sup)
            o["supplier"] = sup
            if res.get("branch") or res.get("branch_email") or res.get("branch_phone"):
                data_sources.op_set_branch(iid, branch=res.get("branch"),
                                           email=res.get("branch_email"),
                                           phone=res.get("branch_phone"))
                if res.get("branch"):
                    o["branch"] = res["branch"]
                if res.get("branch_email"):
                    o["branch_email"] = res["branch_email"]
            _fix_po_email(iid, sup, o)           # correct email for Molan/Vista etc.
            _fix_lpd_home_email(iid, sup, sid, o, lines=res.get("lines"))   # LPD Home → lpdhome
            _apply_post_if_cheaper(iid, sup, _parse_monday_items(o.get("items")), sid, o)
        else:                                    # SAMPLES / CLEARANCE
            data_sources.op_set_branch(iid, branch=route)
        _mark_del_method(iid, sup or route)      # samples → "To Post" on the Del Method column
        data_sources.op_set_status(iid, res.get("stage") or "Needs Review")
        o["stage"] = res.get("stage") or "Needs Review"
    except Exception as e:  # noqa: BLE001
        return {"Order": tag, "Supplier": sup or route,
                "Result": "Monday write failed: " + str(e)[:50]}
    try:
        kind, doc = _build_doc(o)
        pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
            doc, date_str=datetime.date.today().strftime("%d %B %Y"))
        name = f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_" \
               "Trade_Superstore_Online.pdf"
        r = data_sources.op_upload_po(iid, pdf, name)
        _write_po_total(iid, kind, doc)          # numbers6 = the PO's inc-VAT total
        docmsg = f"{kind.upper()} attached ✓" if r.get("ok") else f"{kind} attach UNVERIFIED"
    except ValueError:                           # validation gate blocked it
        docmsg = "doc BLOCKED — missing a field"
    except Exception as e:  # noqa: BLE001
        docmsg = "doc error: " + str(e)[:45]
    return {"Order": tag, "Supplier": sup or route, "Result": f"routed → {docmsg}"}


def _ship(sid):
    """Cached Shopify SHIPPING address (the delivery address) for one order."""
    cache = st.session_state.setdefault("_op_ship", {})
    if sid not in cache:
        try:
            cache[sid] = data_sources.fetch_order_shipping_full(sid)
        except Exception:  # noqa: BLE001
            cache[sid] = None
    return cache[sid]


def _order_detail(o):
    """Clean full-order view: customer, the Shopify shipping (delivery) address, the items as a
    table, an optional live-from-Shopify refresh, and the PO. Rendered inside the row's expander."""
    iid = o["item_id"]
    sid = (o.get("shopify_id") or "").strip()

    # Instant Supplier / Stage change — a selectbox applies the moment you pick (unlike the grid,
    # which only commits when you click away). Empty = clear it on Monday.
    e1, e2 = st.columns(2)
    sopts = [""] + [s for s in _supplier_labels() if s]
    csup = o.get("supplier") or ""
    if csup and csup not in sopts:
        sopts = [csup] + sopts
    nsup = e1.selectbox("Supplier", sopts, index=sopts.index(csup) if csup in sopts else 0,
                        key=f"op_dsup_{iid}")
    if nsup != csup:
        try:
            data_sources.op_set_supplier(iid, nsup)
            o["supplier"] = nsup
            st.toast(f"{o.get('order_no')} · supplier → {nsup or '(cleared)'}")
        except Exception as ex:  # noqa: BLE001
            st.toast("Supplier didn't save: " + str(ex)[:60])
    stopts = [""] + list(data_sources.OP_STAGES)
    cstg = o.get("stage") or ""
    if cstg and cstg not in stopts:
        stopts = [cstg] + stopts
    nstg = e2.selectbox("Stage", stopts, index=stopts.index(cstg) if cstg in stopts else 0,
                        key=f"op_dstg_{iid}")
    if nstg != cstg:
        try:
            data_sources.op_set_status(iid, nstg)
            o["stage"] = nstg
            st.toast(f"{o.get('order_no')} · stage → {nstg or '(cleared)'}")
        except Exception as ex:  # noqa: BLE001
            st.toast("Stage didn't save: " + str(ex)[:60])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Customer**")
        st.markdown("  \n".join(_esc(x) for x in
                                [o.get("customer"), o.get("phone"), o.get("cust_email")] if x)
                    or "—")
    with c2:
        st.markdown("**Deliver to** — Shopify shipping address")
        ship = _ship(sid) if sid else None
        if ship and ship.get("lines"):
            body = "  \n".join(_esc(l) for l in ship["lines"])
            if ship.get("phone"):
                body += f"  \n☎ {_esc(ship.get('phone'))}"
            st.markdown(body)
            if _addr_changed(o.get("address"), ship):
                st.warning("⚠ This differs from the address on Monday — the customer may have "
                           "**changed the delivery address**. Update Monday and re-issue the PO.")
        elif o.get("address"):
            st.markdown(_esc(o.get("address"))
                        + "  \n*(from Monday — live Shopify address unavailable)*")
        else:
            st.markdown("—")

    items = _parse_monday_items(o.get("items"))
    if items:
        st.markdown("**Order items**")
        st.dataframe(
            pd.DataFrame(items)[["Item", "SKU", "Qty"]], hide_index=True, use_container_width=True,
            column_config={"Item": st.column_config.TextColumn("Item", width="large"),
                           "SKU": st.column_config.TextColumn("SKU", width="medium"),
                           "Qty": st.column_config.TextColumn("Qty", width="small")})

    # ---- Routing suggestion (from the 'Suggest' button) ----
    res = st.session_state.get("_op_routes", {}).get(iid)
    if res is not None:
        st.markdown("**Routing suggestion**")
        if res.get("error"):
            st.caption("Couldn't route: " + res["error"])
        elif not res.get("lines"):
            st.caption("No lines to route.")
        else:
            if res.get("split"):
                st.markdown("⚠ **Split order** — routes to more than one supplier:")
                for rt, lns in res["groups"].items():
                    st.markdown(f"- **{rt}** — " + ", ".join(
                        (l.get("sku") or l.get("title") or "")[:26] for l in lns))
                st.caption("Processing this order splits it automatically. To split it by hand "
                           "(choose which line goes to which supplier), use **✂️ Split this order "
                           "across suppliers** below.")
            elif res.get("overall_supplier"):
                _br = res.get("branch")
                st.markdown(f"→ **{res['overall_supplier']}**"
                            + (f" · **{_br}**" if _br else "")
                            + f" · suggested stage **{res['stage']}**")
                if res.get("branch_email"):
                    st.caption(f"Branch email: {_esc(res['branch_email'])}")
                applbl = f"Apply {res['overall_supplier']}" + (f" ({_br})" if _br else "") \
                    + f" + {res['stage']}"
                if st.button(":material/check: " + applbl + " to Monday", key=f"op_apply_{iid}"):
                    try:
                        data_sources.op_set_supplier(iid, res["overall_supplier"])
                        o["supplier"] = res["overall_supplier"]
                        data_sources.op_set_status(iid, res["stage"])
                        o["stage"] = res["stage"]
                        if _br or res.get("branch_email") or res.get("branch_phone"):
                            data_sources.op_set_branch(iid, branch=_br,
                                                       email=res.get("branch_email"),
                                                       phone=res.get("branch_phone"))
                            if _br:
                                o["branch"] = _br
                            if res.get("branch_email"):
                                o["branch_email"] = res["branch_email"]
                        st.success("Applied — supplier, branch & stage set on Monday.")
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't apply: " + str(e)[:150])
            else:
                st.markdown(f"→ **{res.get('route')}** — in-house / pick (no supplier to set)")
            # Eurocell / Travis Perkins: nearest physical branch needs their live locator.
            _sup = res.get("overall_supplier") or ""
            _pc = (_ship(sid) or {}).get("zip") if sid else None
            if _sup == "Eurocell":
                _u = f"https://www.eurocell.co.uk/branch-finder?postcode={_pc or ''}"
                st.caption(f"⚠ Pick the nearest **Eurocell** branch: [branch finder]({_u}) → "
                           "put its name in Branch and `branchname@eurocell.co.uk` in Branch email.")
            elif _sup == "Travis Perkins":
                _u = f"https://www.travisperkins.co.uk/branch-locator?searchTerm={_pc or ''}"
                st.caption(f"⚠ Pick the nearest **Travis Perkins** branch: [branch locator]({_u}) → "
                           "put its name in Branch and its email in Branch email.")
            elif res.get("needs_branch"):
                st.caption("⚠ Postcode not clearly on the Hardie map — confirm the branch.")
            st.dataframe(
                pd.DataFrame([{"Item": l.get("title"), "SKU": l.get("sku") or "",
                               "Qty": l.get("qty"),
                               "Routes to": (l.get("supplier") or l.get("route")),
                               "Why": l.get("reason")} for l in res["lines"]]),
                hide_index=True, use_container_width=True,
                column_config={"Routes to": st.column_config.TextColumn(
                    "Routes to", help="The supplier this line is sent to. 'PICK' = couldn't "
                    "identify — choose a supplier in the grid.")})

    # ---- Manual split — assign each line to a supplier, then split the order across them ----
    if sid and st.checkbox("✂️ Split this order across suppliers", key=f"op_msplit_{iid}"):
        st.caption("Set the supplier for each line, then Split. Lines with the SAME supplier become "
                   "one part; each part gets its own Monday item (30xxx-1, -2 …) and its own PO. "
                   "No need to delete anything — just assign suppliers.")
        try:
            slines = (st.session_state.get("_op_routes", {}).get(iid, {}) or {}).get("lines") \
                or data_sources.fetch_order_lines_with_vendor(sid)
        except Exception:  # noqa: BLE001
            slines = []
        supopts = [s for s in _supplier_labels() if s]
        if not slines:
            st.caption("Couldn't read the order lines to split.")
        else:
            sdf = pd.DataFrame([{"Item": (l.get("title") or "")[:70], "SKU": l.get("sku") or "",
                                 "Qty": l.get("qty"),
                                 "Supplier": (l.get("supplier") if l.get("supplier") in supopts
                                              else None)} for l in slines])
            sedit = st.data_editor(
                sdf, hide_index=True, use_container_width=True, key=f"op_msplit_ed_{iid}",
                disabled=["Item", "SKU", "Qty"],
                column_config={"Supplier": st.column_config.SelectboxColumn(
                    "Supplier", options=supopts, required=False,
                    help="Who fulfils THIS line. Lines sharing a supplier are combined.")})
            assigned = [(str(s).strip() if pd.notna(s) else "") for s in list(sedit["Supplier"])]
            distinct = [s for s in dict.fromkeys(assigned) if s]
            if not all(assigned):
                st.caption("⚠ Assign a supplier to every line before splitting.")
            if st.button(f"✂️ Split into {len(distinct)} part(s)", key=f"op_msplitgo_{iid}",
                         type="primary", disabled=not (all(assigned) and len(distinct) >= 2)):
                lines2 = [{**l, "supplier": s, "route": s, "branch": None, "branch_email": None}
                          for l, s in zip(slines, assigned)]
                groups = {}
                for l in lines2:
                    groups.setdefault(l["supplier"], []).append(l)
                with st.spinner("Splitting…"):
                    msg = _process_split(o, {"groups": groups, "lines": lines2, "split": True})
                st.success("Split done — " + msg + ". Hit ↻ Refresh to see the parts.")
                for _k in ("_op_orders", "_op_detail", "_op_routes", "_op_fcounts"):
                    st.session_state.pop(_k, None)

    # Live-from-Shopify: the Monday items above are a snapshot from when the order synced. This
    # pulls the CURRENT order (in case it was edited) and adds unit prices, variants + fulfilments.
    if sid and st.button(":material/sync: Refresh from Shopify (live items, address & fulfilments)",
                         key=f"op_live_{iid}",
                         help="Monday shows the order as it first synced. This re-fetches the "
                              "current order from Shopify — items, prices, the fulfilment split, "
                              "AND the shipping address — in case anything was changed."):
        st.session_state[f"op_liveon_{iid}"] = True
        st.session_state.get("_op_detail", {}).pop(sid, None)     # bust caches → truly re-fetch
        st.session_state.get("_op_ship", {}).pop(sid, None)
        st.rerun()
    if sid and st.session_state.get(f"op_liveon_{iid}"):
        d = _live_detail(sid)
        if d.get("error"):
            st.caption("Couldn't read Shopify: " + d["error"])
        if d.get("lines"):
            st.dataframe(pd.DataFrame([{"SKU": ln.get("sku") or "", "Item": ln.get("title"),
                                        "Qty": ln.get("qty"), "Unit £": ln.get("price")}
                                       for ln in d["lines"]]),
                         hide_index=True, use_container_width=True)
        locs = sorted(set((d.get("split") or {}).values()))
        if locs:
            st.markdown(f"**Fulfilments:** {len(locs)} — " + ", ".join(_esc(l) for l in locs))
            for l in locs:
                st.caption(f"• {l}: " + ", ".join(s for s, loc in d["split"].items() if loc == l))
        else:
            st.caption("**Fulfilments:** 1 (not split)")

    st.divider()
    st.markdown("**PO / document**")
    for a in (o.get("po_assets") or []):
        if a.get("url"):
            st.markdown(f"📄 [{_esc(a.get('name'))}]({a['url']})")

    # ---- Override: process this one order using the supplier YOU picked (no re-routing) ----
    cur_sup = (o.get("supplier") or "").strip()
    if cur_sup:
        st.caption(f"To **override**: set the Supplier in the grid, then process this order as that "
                   f"supplier here (it won't re-route). Currently **{cur_sup}**.")
        if st.button(f":material/bolt: Process this order as {cur_sup}", key=f"op_proc1_{iid}"):
            with st.spinner("Processing…"):
                msg = _process_current(o)
            st.success("Processed → " + msg + ". Hit ↻ Refresh to see the board.")
            st.session_state["_op_orders"] = None

    # ---- Reprocess as TO POST — we bring it in and post it ourselves (deliver to OUR address) ----
    _tp_sup = (o.get("supplier") or "").strip()
    if st.button("📮 Reprocess as TO POST (deliver to us; order from Derby for EC/GAP/TP, else head "
                 "office)", key=f"op_topost_{iid}",
                 help="Marks the order TO POST, sets the delivery address to ours, points Eurocell/"
                      "GAP/Travis Perkins/UPB at the Derby branch (head-office suppliers keep their "
                      "head-office email), and regenerates the PO."):
        with st.spinner("Marking TO POST + regenerating the PO…"):
            try:
                _force_to_post(iid, _tp_sup, o)
                kind, doc = _build_doc(o)
                pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
                    doc, date_str=datetime.date.today().strftime("%d %B %Y"))
                nm = f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_" \
                     "Trade_Superstore_Online.pdf"
                r = data_sources.op_upload_po(iid, pdf, nm)
                _write_po_total(iid, kind, doc)
                st.success(f"TO POST set (Branch = TO POST, delivers to us) + {kind.upper()} "
                           "regenerated. " + ("Attached ✓" if r.get("ok") else "attach unverified"))
                st.session_state["_op_orders"] = None
            except Exception as e:  # noqa: BLE001
                st.error("Marked TO POST, but couldn't regenerate the PO: " + str(e)[:150])

    # ---- Adjust anything before generating (fix a missed qty / address / price, add a line) ----
    # A checkbox, not an expander — this whole panel already renders inside the order's expander,
    # and Streamlit forbids nesting expanders.
    items_override = address_override = delivery_override = notes_extra = None
    if st.checkbox("✏️ Adjust the PO before generating — fix qty / address / prices, add a line",
                   key=f"op_adjust_{iid}"):
        st.caption("Edit anything the automation missed, then Generate. Changes here only affect "
                   "the PO document (not the Monday/Shopify order).")
        default_addr = "\n".join((_ship(sid) or {}).get("lines") or
                                 [x.strip() for x in (o.get("address") or "").split(",")
                                  if x.strip()])
        addr_txt = st.text_area("Delivery address (one line per row)", value=default_addr,
                                key=f"op_addr_{iid}", height=110)
        sup_now = (o.get("supplier") or "")
        base = _parse_monday_items(o.get("items"))
        edf = pd.DataFrame([{"Description": it["Item"], "SKU": it["SKU"],
                             "Qty": it["Qty"] or "1", "Unit cost £": _line_cost(it["SKU"], sup_now)}
                            for it in base]) if base else pd.DataFrame(
            columns=["Description", "SKU", "Qty", "Unit cost £"])
        edited_lines = st.data_editor(
            edf, num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"op_lines_{iid}",
            column_config={"Unit cost £": st.column_config.NumberColumn("Unit cost £",
                                                                        format="%.2f")})
        c_ov1, c_ov2 = st.columns(2)
        ov = c_ov1.checkbox("Override delivery charge", key=f"op_ovck_{iid}")
        dov = c_ov2.number_input("Delivery £ (ex VAT)", min_value=0.0, step=1.0, value=0.0,
                                 key=f"op_dov_{iid}", disabled=not ov)
        note = st.text_input("Extra note on the PO (optional)", key=f"op_note_{iid}")
        if ov:
            delivery_override = float(dov)
        if note.strip():
            notes_extra = [note]
        _addr = [ln.strip() for ln in addr_txt.splitlines() if ln.strip()]
        if _addr and _addr != ((_ship(sid) or {}).get("lines") or []):
            address_override = _addr
        try:
            rows = [{"SKU": (r.get("SKU") or ""), "Item": (r.get("Description") or ""),
                     "Qty": str(r.get("Qty") or ""),
                     "Cost": (float(r["Unit cost £"]) if pd.notna(r.get("Unit cost £")) else None)}
                    for _, r in edited_lines.iterrows()
                    # skip blanked-out rows so deleting a line's text just removes it (no empty-line error)
                    if str(r.get("SKU") or "").strip() or str(r.get("Description") or "").strip()]
            if rows != [{"SKU": it["SKU"], "Item": it["Item"], "Qty": it["Qty"] or "1",
                         "Cost": (_line_cost(it["SKU"], sup_now))} for it in base]:
                items_override = rows
        except Exception:  # noqa: BLE001
            pass

    # ---- Generate the branded PO / packing slip (validation gate; prices from the feed) ----
    if st.button(":material/description: Generate PO / packing slip", key=f"op_gen_{iid}"):
        try:
            kind, doc = _build_doc(o, delivery_override=delivery_override, notes_extra=notes_extra,
                                   items_override=items_override, address_override=address_override)
            date_str = datetime.date.today().strftime("%d %B %Y")
            pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
                doc, date_str=date_str)
            st.session_state[f"op_gen_pdf_{iid}"] = {
                "bytes": pdf, "kind": kind, "total": doc.get("total"),
                "unpriced": doc.get("unpriced") or [],
                "name": f"{'PO' if kind == 'po' else 'PackingSlip'}_{doc['order']}_"
                        "Trade_Superstore_Online.pdf"}
        except ValueError as e:      # the validation gate blocked it — show exactly what's missing
            st.session_state.pop(f"op_gen_pdf_{iid}", None)
            st.error("Can't generate yet — " + str(e))
        except Exception as e:  # noqa: BLE001
            st.session_state.pop(f"op_gen_pdf_{iid}", None)
            st.error("Couldn't build the document: " + str(e)[:200])
    gen = st.session_state.get(f"op_gen_pdf_{iid}")
    if gen:
        st.success(f"Built a **{'Purchase Order' if gen['kind'] == 'po' else 'Packing Slip'}** — "
                   "download to check it, or attach it to Monday.")
        if gen.get("unpriced"):          # for YOU only — not printed on the supplier's document
            st.caption("ℹ️ No price on file for: " + "; ".join(gen["unpriced"])
                       + " — fill these in on the supplier's confirmation.")
        g1, g2 = st.columns(2)
        g1.download_button(":material/download: Download", gen["bytes"], file_name=gen["name"],
                           mime="application/pdf", key=f"op_gendl_{iid}", use_container_width=True)
        if g2.button(":material/attach_file: Attach this to Monday", key=f"op_genatt_{iid}",
                     use_container_width=True):
            with st.spinner("Uploading + verifying…"):
                try:
                    r = data_sources.op_upload_po(iid, gen["bytes"], gen["name"])
                    if r.get("ok"):
                        _write_po_total(iid, gen.get("kind"), gen)   # numbers6 = PO inc-VAT total
                        st.success(f"Attached & verified ({r['size']:,} bytes).")
                        st.session_state["_op_orders"] = None
                    else:
                        st.error(f"Upload didn't verify — {r.get('n_assets')} asset(s), none "
                                 "matched. Try again.")
                except Exception as e:  # noqa: BLE001
                    st.error("Upload failed: " + str(e)[:180])

    up = st.file_uploader("…or upload / replace the PO manually (PDF)", type=["pdf"],
                          key=f"op_po_{iid}")
    if up is not None and st.button(":material/attach_file: Attach to Monday (replaces latest)",
                                    key=f"op_poset_{iid}"):
        with st.spinner("Uploading + verifying…"):
            try:
                res = data_sources.op_upload_po(iid, up.getvalue(), up.name)
                if res.get("ok"):
                    st.success(f"Attached & verified ({res['size']:,} bytes).")
                    st.session_state["_op_orders"] = None
                else:
                    st.error(f"Upload didn't verify — {res.get('n_assets')} asset(s) on the item, "
                             "none matched the exact size. Try again.")
            except Exception as e:  # noqa: BLE001
                st.error("Upload failed: " + str(e)[:180])


def _quote_to_po(orders, sup_opts):
    """Build a PO from a supplier's QUOTE — for when one supplier quotes a whole order (e.g. Molan
    quoting a Storm+Molan mix). Enter the order number, pick the supplier, type the quoted unit
    prices, generate a branded PO to download or attach. Prices come from YOU (the quote), not the
    feed, so it works even for lines that supplier doesn't normally price."""
    with st.expander("📝 Quote → PO — a supplier quoted the whole order? Build its PO here"):
        st.caption("Enter the order number, choose who quoted, type the quoted **ex-VAT unit price** "
                   "on each line, then Generate. Prices come from your quote — not the pricelist — "
                   "so a supplier can quote lines they don't normally stock. (For a split order, "
                   "Merge the parts to that supplier first, then quote the whole thing here.)")
        c1, c2 = st.columns(2)
        ono = c1.text_input("Order number", key="qpo_ono", placeholder="e.g. 30348").strip()
        sup = c2.selectbox("Supplier that quoted", [""] + list(sup_opts),
                           format_func=lambda s: s or "— choose —", key="qpo_sup")
        match = next((o for o in orders if (o.get("order_no") or "").strip() == ono
                      or (o.get("name") or "").strip() == ono), None) if ono else None
        if ono and not match:
            st.warning(f"No order “{ono}” in the current list — check the number or hit Refresh.")
        if not (match and sup):
            return
        sid = (match.get("shopify_id") or "").strip()
        try:
            sl = data_sources.fetch_order_line_items(sid) if sid else []
        except Exception:  # noqa: BLE001
            sl = []
        base = ([{"Description": (l.get("title") or ""), "SKU": (l.get("sku") or ""),
                  "Qty": l.get("qty") or 1} for l in sl]
                or [{"Description": it["Item"], "SKU": it["SKU"], "Qty": it["Qty"] or "1"}
                    for it in _parse_monday_items(match.get("items"))])
        for r in base:
            r["Quoted unit £ (ex VAT)"] = _line_cost(r["SKU"], sup)     # prefill if known, else blank
        edit = st.data_editor(
            pd.DataFrame(base), num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"qpo_lines_{ono}",
            column_config={"Quoted unit £ (ex VAT)":
                           st.column_config.NumberColumn("Quoted unit £ (ex VAT)", format="%.2f")})
        addr0 = "\n".join((_ship(sid) or {}).get("lines") or
                          [x.strip() for x in (match.get("address") or "").split(",") if x.strip()])
        a = st.text_area("Delivery address", value=addr0, key=f"qpo_addr_{ono}", height=95)
        d1, d2 = st.columns(2)
        dov = d1.number_input("Delivery £ (ex VAT) from the quote", min_value=0.0, step=1.0,
                              value=0.0, key=f"qpo_dov_{ono}")
        note = d2.text_input("Quote ref / note on the PO", key=f"qpo_note_{ono}")
        if st.button(f":material/description: Generate PO for {ono} → {sup}",
                     key=f"qpo_gen_{ono}", type="primary"):
            rows = [{"SKU": (r.get("SKU") or ""), "Item": (r.get("Description") or ""),
                     "Qty": str(r.get("Qty") or "1"),
                     "Cost": (float(r["Quoted unit £ (ex VAT)"])
                              if pd.notna(r.get("Quoted unit £ (ex VAT)")) else None)}
                    for _, r in edit.iterrows() if (r.get("Description") or r.get("SKU"))]
            qo = {"order_no": ono, "name": ono, "supplier": sup, "shopify_id": sid,
                  "customer": match.get("customer"), "phone": match.get("phone"),
                  "items": match.get("items")}
            try:
                kind, doc = _build_doc(
                    qo, items_override=rows,
                    address_override=[ln.strip() for ln in a.splitlines() if ln.strip()] or None,
                    delivery_override=float(dov),
                    notes_extra=([f"Against our quote {note}"] if note.strip() else None))
                pdf = (order_docs.build_po_pdf if kind == "po" else order_docs.build_slip_pdf)(
                    doc, date_str=datetime.date.today().strftime("%d %B %Y"))
                st.session_state["qpo_pdf"] = {
                    "bytes": pdf, "kind": kind, "total": doc.get("total"), "iid": match["item_id"],
                    "sup": sup, "ono": ono, "name": f"PO_{ono}_Trade_Superstore_Online.pdf"}
            except ValueError as e:
                st.session_state.pop("qpo_pdf", None)
                st.error("Can't generate yet — " + str(e))
            except Exception as e:  # noqa: BLE001
                st.session_state.pop("qpo_pdf", None)
                st.error("Couldn't build the PO: " + str(e)[:200])
        qp = st.session_state.get("qpo_pdf")
        if qp and qp.get("ono") == ono:
            if qp["kind"] != "po":
                st.warning("Some lines have no price, so this came out as a packing slip — fill in "
                           "every quoted unit price to get a PO.")
            g1, g2 = st.columns(2)
            g1.download_button(":material/download: Download PO", qp["bytes"], file_name=qp["name"],
                               mime="application/pdf", key="qpo_dl", use_container_width=True)
            if g2.button(":material/attach_file: Attach to Monday + set supplier",
                         key="qpo_att", use_container_width=True):
                with st.spinner("Uploading + verifying…"):
                    try:
                        r = data_sources.op_upload_po(qp["iid"], qp["bytes"], qp["name"])
                        if r.get("ok"):
                            data_sources.op_set_supplier(qp["iid"], qp["sup"])
                            _fix_po_email(qp["iid"], qp["sup"])   # lock supplier's PO email (e.g. Vista)
                            _write_po_total(qp["iid"], qp["kind"], qp)
                            st.success("Attached, supplier set to " + qp["sup"] + ". ↻ Refresh.")
                            st.session_state["_op_orders"] = None
                        else:
                            st.error("Upload didn't verify — try again.")
                    except Exception as e:  # noqa: BLE001
                        st.error("Upload failed: " + str(e)[:180])


def render():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Order Processing</span></span></div>""",
        unsafe_allow_html=True)

    # Blocky (Bebas Neue) styling, scoped to the primary action buttons (Process ALL / SELECTED).
    st.markdown(
        "<style>.stButton>button[kind=\"primary\"],"
        ".stButton>button[data-testid=\"baseButton-primary\"],"
        ".stButton>button[data-testid=\"stBaseButton-primary\"]{"
        "font-family:'Bebas Neue',sans-serif!important;text-transform:uppercase;"
        "letter-spacing:.09em;font-size:18px;}</style>",
        unsafe_allow_html=True)

    try:
        orders = _orders()
    except Exception as e:  # noqa: BLE001
        st.error("Couldn't read the orders board: " + str(e)[:200])
        return
    sup_labels = _supplier_labels()

    # Top row: Refresh / Splits on the left, Process ALL / SELECTED on the right.
    tc = st.columns([1.0, 1.0, 2.6, 1.3, 1.7])
    if tc[0].button(":material/refresh: Refresh"):
        for k in ("_op_orders", "_op_detail", "_op_fcounts", "_op_routes", "_op_ship",
                  "_op_results", "_op_split_pending", "_op_suppliers"):
            st.session_state.pop(k, None)
        st.rerun()
    load_fc = tc[1].button(
        ":material/call_split: Refresh Fulfil #",
        help="Re-reads how many separate Shopify fulfilments each order has. Fills automatically; "
             "use this to refresh after splitting.")
    do_all = tc[3].button("Process all", type="primary", use_container_width=True)
    do_sel = tc[4].button("Process selected", type="primary", use_container_width=True)

    st.caption(f"**{len(orders)}** order(s) in *NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)* · "
               "editing **Supplier** or **Stage** writes to Monday **instantly** — no Save needed.")

    _suggestion_box()

    if load_fc or "_op_fcounts" not in st.session_state:      # auto-fill on first load / Refresh
        with st.spinner("Reading Shopify fulfilments…"):
            fc = {}
            for o in orders:
                sid = (o.get("shopify_id") or "").strip()
                if not sid:
                    continue
                try:
                    fc[o["item_id"]] = data_sources.fetch_order_fulfillment_count(sid)
                except Exception:  # noqa: BLE001
                    fc[o["item_id"]] = None
            st.session_state["_op_fcounts"] = fc

    # Dropdown option sets must include every value currently present, or the grid errors.
    sup_opts = list(dict.fromkeys([s for s in sup_labels if s]
                                  + [o.get("supplier") for o in orders if o.get("supplier")]))
    stage_opts = [_stage_disp(s) for s in
                  list(dict.fromkeys(data_sources.OP_STAGES
                                     + [o.get("stage") for o in orders if o.get("stage")]))]
    _quote_to_po(orders, sup_opts)
    fcounts = st.session_state.get("_op_fcounts", {})
    store = (data_sources.get_secret("SHOPIFY_STORE") or "").strip()

    def _order_url(sid):
        return f"https://{store}/admin/orders/{sid}" if (store and sid) else None

    # Build the board grid — column order: Select, Order, Open, Fulfil #, then the rest.
    rows = []
    for o in orders:
        rows.append({
            "Select": False,
            "Order": _order_label(o),
            "Open": _order_url((o.get("shopify_id") or "").strip()),
            "Fulfil": fcounts.get(o["item_id"], None),
            "Customer": o.get("customer") or "",
            "Supplier": o.get("supplier") or None,
            "Branch email": o.get("branch_email") or "",
            "Stage": _stage_disp(o.get("stage")),
            "£ to us": o.get("sell") or "",
            "£ supplier": o.get("cost_supplier") or "",
        })
    df = pd.DataFrame(rows)

    edited = st.data_editor(
        df, hide_index=True, use_container_width=True, key="op_board",
        column_order=["Select", "Order", "Open", "Fulfil", "Customer", "Supplier",
                      "Branch email", "Stage", "£ to us", "£ supplier"],
        column_config={
            "Select": st.column_config.CheckboxColumn("✓", width="small"),
            "Order": st.column_config.TextColumn("Order", width="small",
                                                 help="Click the cell and Ctrl+C to copy the "
                                                      "number; use ↗ to open it in Shopify."),
            "Open": st.column_config.LinkColumn("↗", width="small", display_text="Open ↗",
                                                help="Open this order in Shopify admin"),
            "Fulfil": st.column_config.NumberColumn(
                "Fulfil #", width="small",
                help="Fulfillment No. — how many separate Shopify fulfilments the order has "
                     "(2+ means it's split across suppliers). Fills automatically."),
            "Customer": st.column_config.TextColumn("Customer", width="medium"),
            "Branch email": st.column_config.TextColumn("Branch email", width="medium"),
            "Supplier": st.column_config.SelectboxColumn("Supplier", options=sup_opts,
                                                         width="medium"),
            "Stage": st.column_config.SelectboxColumn("Stage", options=stage_opts, width="medium"),
            "£ to us": st.column_config.TextColumn("£ to us", width="small"),
            "£ supplier": st.column_config.TextColumn("£ supplier", width="small"),
        },
        disabled=["Order", "Open", "Fulfil", "Customer", "Branch email",
                  "£ to us", "£ supplier"])

    # ---- Auto-sync every Supplier / Stage edit straight to Monday (no Save button) ----
    # Handles CLEARING a cell too (empty → clears it on Monday), not just choosing a new value.
    for i, o in enumerate(orders):
        try:
            raw_sup = edited.iloc[i]["Supplier"]
            new_sup = raw_sup.strip() if isinstance(raw_sup, str) and raw_sup.strip() else None
            if new_sup != (o.get("supplier") or None):
                data_sources.op_set_supplier(o["item_id"], new_sup or "")   # "" clears the dropdown
                o["supplier"] = new_sup or ""
                st.toast(f"{o.get('order_no')} · supplier → {new_sup or '(cleared)'}")
            raw_stage = _stage_plain(edited.iloc[i]["Stage"])
            new_stage = raw_stage.strip() if isinstance(raw_stage, str) and raw_stage.strip() \
                else None
            if new_stage != (o.get("stage") or None):
                data_sources.op_set_status(o["item_id"], new_stage or "")   # "" clears the status
                o["stage"] = new_stage or ""
                st.toast(f"{o.get('order_no')} · stage → {new_stage or '(cleared)'}")
        except Exception as e:  # noqa: BLE001
            st.toast(f"{o.get('order_no')} · didn't save: {str(e)[:70]}")

    # Which rows are ticked — drives both "Process selected" and the expand-detail panels below.
    ticked = [i for i in range(len(orders)) if bool(edited.iloc[i]["Select"])]

    # ---- Process = one click: run non-splits straight away; pause only to confirm splits ----
    if do_all or do_sel:
        tgt = list(range(len(orders))) if do_all else ticked
        if not tgt:
            st.warning("No orders ticked — use the ✓ column to pick which to process.")
        else:
            by_id = {o["item_id"]: o for o in orders}
            rts = st.session_state.setdefault("_op_routes", {})
            with st.spinner("Routing & processing…"):
                for i in tgt:                                  # route Place Order orders only
                    o = orders[i]
                    if (o.get("stage") or "").strip() != PLACE_ORDER:
                        continue
                    iid, sid = o["item_id"], (o.get("shopify_id") or "").strip()
                    if rts.get(iid) is None and sid:
                        try:
                            lines = data_sources.fetch_order_lines_with_vendor(sid)
                            try:
                                pc = (data_sources.fetch_order_shipping(sid) or {}).get("postcode")
                            except Exception:  # noqa: BLE001
                                pc = None
                            rts[iid] = order_routing.route_order(lines, postcode=pc, sku_supplier=_sole_feed_supplier)
                        except Exception as e:  # noqa: BLE001
                            rts[iid] = {"error": str(e)[:100], "lines": []}
                run_ids, results = [], []
                for i in tgt:
                    o = orders[i]
                    iid = o["item_id"]
                    if (o.get("stage") or "").strip() != PLACE_ORDER:
                        results.append({"Order": o.get("order_no") or o.get("name"),
                                        "Supplier": o.get("supplier") or "",
                                        "Result": f"already {(o.get('stage') or '—')} — skipped"})
                    else:
                        run_ids.append(iid)          # splits included — no confirm, straight through
                prog = st.progress(0.0, text="Processing…") if run_ids else None
                for n, iid in enumerate(run_ids):
                    results.append(_process_one(by_id[iid]))
                    if prog:
                        prog.progress((n + 1) / len(run_ids), text=f"Processed {n + 1}/{len(run_ids)}")
                if prog:
                    prog.empty()
            st.session_state["_op_results"] = results
            # No TradeHub approval step: everything writes straight to Monday, then the board
            # auto-refreshes so the new Supplier / Stage / PO populate onto the table at once.
            for k in ("_op_orders", "_op_detail", "_op_fcounts", "_op_routes", "_op_ship",
                      "_op_split_pending"):
                st.session_state.pop(k, None)
            st.rerun()

    results = st.session_state.get("_op_results")
    if results:
        st.markdown("##### Processed")
        st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
        st.caption("Supplier / branch / stage set on Monday and a PO or packing slip attached, per "
                   "order — **splits included** (a Monday part per supplier + the Shopify fulfilment "
                   "split). The table above has refreshed from Monday. **Only orders at stage "
                   "*Place Order* are processed.** Nothing was emailed to a supplier — that stays the "
                   "team's send step. **Review on Monday and amend anything if needed.**")

    # ---- Merge split parts (one supplier can cover another part's items → one delivery) ----
    split_groups = {}
    for o in orders:
        sp = _split_parts(o, orders)
        if len(sp) >= 2:
            split_groups[(o.get("order_no") or "").strip()] = sp
    if split_groups:
        st.divider()
        st.markdown("##### 🔗 Merge split parts")
        st.caption("If one supplier can fulfil another part's items too, merge them into a single "
                   "order + PO (one delivery instead of two). The absorbed part is **archived** on "
                   "Monday (recoverable), and the surviving part's PO is regenerated with all the "
                   "lines. The Shopify fulfilment split isn't changed.")
        for ono, sp in split_groups.items():
            with st.expander(f"{ono} — split into {len(sp)} parts"):
                for p in sp:
                    isum = "; ".join(i["Item"] for i in _parse_monday_items(p.get("items")))
                    st.markdown(f"**{p.get('name')}** · {p.get('supplier') or '—'} — "
                                f"<span style='color:var(--text-color,#888)'>{isum[:110]}</span>",
                                unsafe_allow_html=True)
                names = [p.get("name") for p in sp]
                pick = st.multiselect("Parts to merge (pick 2 or more)", names,
                                      key=f"mrg_pick_{ono}")
                picked = [p for p in sp if p.get("name") in pick]
                # Blank first option forces an explicit choice — the selectbox must NOT silently
                # default to the first picked part's supplier (that merged 30376 to Eurocell when
                # UPB was intended). Merge stays disabled until a real supplier is chosen.
                sup_choices = [""] + list(dict.fromkeys(
                    [p.get("supplier") for p in picked if p.get("supplier")] + sup_opts))
                tgt = st.selectbox("Fulfil the merged part with", sup_choices,
                                   format_func=lambda s: s or "— choose supplier —",
                                   key=f"mrg_sup_{ono}")
                if st.button(f"Merge {len(pick)} part(s) → {tgt or '?'}", key=f"mrg_go_{ono}",
                             type="primary", disabled=len(pick) < 2 or not tgt):
                    with st.spinner("Merging…"):
                        msg = _merge_parts(picked, tgt, sp)
                    st.success(msg)
                    for k in ("_op_orders", "_op_detail", "_op_routes", "_op_ship", "_op_fcounts"):
                        st.session_state.pop(k, None)
                    st.rerun()

    # Expand each ticked order right off the table — no dropdown. One ticked → opens fully.
    st.divider()
    if not ticked:
        st.caption("Tick an order's **✓** to open its full detail & PO here.")
    else:
        only_one = len(ticked) == 1
        for i in ticked:
            o = orders[i]
            with st.expander(f"{_order_label(o)} · {o.get('customer') or '—'}",
                             expanded=only_one):
                _order_detail(o)
