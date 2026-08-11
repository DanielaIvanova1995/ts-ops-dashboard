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
    if st.session_state.get("_op_suppliers") is None:
        try:
            st.session_state["_op_suppliers"] = data_sources.op_board_supplier_labels()
        except Exception:  # noqa: BLE001
            st.session_state["_op_suppliers"] = []
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
    with st.expander("💡 Suggestion / report a problem"):
        st.caption("Anything that doesn't work, or would help you process orders faster — this "
                   "goes straight to Daniela.")
        who = st.text_input("Your name", value="Natasha", key="op_sugg_who")
        msg = st.text_area("What's up?", key="op_sugg_msg", height=110,
                           placeholder="e.g. the supplier dropdown is missing X, or the PO for "
                                       "order 30xxx has the wrong branch…")
        if st.button(":material/send: Send to Daniela", key="op_sugg_send",
                     disabled=not msg.strip()):
            subj = f"TradeHub Order Processing — suggestion from {who or 'the team'}"
            body = f"From: {who or 'the team'}\n\n{msg.strip()}\n\n— sent from TradeHub Order Processing"
            try:
                data_sources.send_supplier_email(FROM_MAILBOX, DANIELA, subj, body)
                st.success("Sent to Daniela — thank you!")
            except Exception:  # noqa: BLE001
                try:
                    link = data_sources.create_supplier_draft(FROM_MAILBOX, DANIELA, subj, body)
                    st.success("Saved as a draft to send." + (f" [Open]({link})" if link else ""))
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't send: " + str(e)[:150])


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


@st.cache_data(show_spinner=False)
def _pricing():
    """{normalised SKU: {supplier_norm: cost}} from the pricing feed (Airtable-derived)."""
    try:
        d = json.load(open("pricing_lookup.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for it in d.get("items", []):
        sku = re.sub(r"[^a-z0-9]", "", (it.get("sku") or "").lower())
        if sku:
            out[sku] = {re.sub(r"[^a-z0-9]", "", (o.get("s") or "").lower()): o.get("c")
                        for o in (it.get("offers") or [])}
    return out


def _line_cost(sku, supplier):
    """The routed supplier's cost for a SKU from the pricing feed, or None (→ 'confirm' on the PO;
    never guessed — matches the rulebook)."""
    key = re.sub(r"[^a-z0-9]", "", (sku or "").lower())
    sup = re.sub(r"[^a-z0-9]", "", (supplier or "").lower())
    offers = _pricing().get(key) or {}
    c = offers.get(sup)
    return c if isinstance(c, (int, float)) else None


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
    dl = address_override or (ship or {}).get("lines") or \
        [x.strip() for x in (o.get("address") or "").split(",") if x.strip()]
    order_no = o.get("order_no") or o.get("name") or ""
    contact = f"{o.get('customer') or ''}".strip()
    phone = (ship or {}).get("phone") or o.get("phone") or ""
    notes = [f"Kerbside delivery to: {contact}" + (f", {phone}" if phone else "") + ".",
             f"Quote TSO order {order_no} on all paperwork."]
    if notes_extra:
        notes += [n for n in notes_extra if n and str(n).strip()]

    items = items_override if items_override is not None else _parse_monday_items(o.get("items"))
    is_portal = supplier in order_routing.PORTAL
    in_house = supplier in ("", "SAMPLES", "CLEARANCE")
    kind = "slip" if (is_portal or in_house) else "po"

    if kind == "slip":
        lines = [[(it.get("SKU") or "-"), it.get("Item") or "", (it.get("Qty") or "1")]
                 for it in items]
        return "slip", {"order": order_no, "po": order_no, "supplier": supplier, "dl": dl,
                        "lines": lines,
                        "notes": (["Portal order - place on the supplier portal."] if is_portal
                                  else ["In-house — post / fulfil from Head Office."]) + notes,
                        "contact": (contact + (f" - {phone}" if phone else "")) or "TSO"}

    lines, goods, any_confirm = [], 0.0, False
    for it in items:
        qty = it.get("Qty") or "1"
        cost = it.get("Cost") if isinstance(it.get("Cost"), (int, float)) \
            else _line_cost(it.get("SKU"), supplier)
        try:
            q = float(qty)
        except (TypeError, ValueError):
            q = 1
        if cost is None:
            lines.append([(it.get("SKU") or "-"), it.get("Item") or "", qty, "confirm", "confirm"])
            any_confirm = True
        else:
            lt = round(cost * q, 2)
            goods += lt
            lines.append([(it.get("SKU") or "-"), it.get("Item") or "", qty, _money(cost),
                          _money(lt)])
    dlines = [{"sku": it.get("SKU"), "description": it.get("Item"),
               "qty": (float(it.get("Qty")) if str(it.get("Qty") or "").replace(".", "", 1)
                       .isdigit() else 1)}
              for it in items]
    ship_pc = {"postcode": (ship or {}).get("zip"), "country": (ship or {}).get("country")}
    if delivery_override is not None:
        deliv, deliv_known = float(delivery_override), True
        deliv_label = _money(deliv)
    else:
        _d = delivery_rules.expected_delivery(supplier, goods, ship_pc, dlines)
        deliv = _d if isinstance(_d, (int, float)) else 0.0
        deliv_known = _d is not None
        deliv_label = _money(deliv) + ("" if deliv_known else " (rate not on file — confirm on OC)")
    if any_confirm:
        sums = [["Goods (ex VAT)", "confirm on OC", False], ["Delivery", deliv_label, False],
                ["VAT @20%", "confirm", False], ["Total (inc VAT)", "confirm on OC", True]]
    else:
        vat = round((goods + deliv) * 0.20, 2)
        sums = [["Goods (ex VAT)", _money(goods), False], ["Delivery (ex VAT)", deliv_label, False],
                ["VAT @20%", _money(vat), False],
                ["Total (inc VAT)", _money(goods + deliv + vat), True]]
    return "po", {"order": order_no, "po": order_no, "supplier": supplier, "dl": dl,
                  "acct": order_docs.account_for(supplier), "lines": lines, "sums": sums,
                  "notes": notes, "contact": (contact + (f" - {phone}" if phone else "")) or "TSO"}


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
                if glines[0].get("branch") or glines[0].get("branch_email"):
                    data_sources.op_set_branch(pid, branch=glines[0].get("branch"),
                                               email=glines[0].get("branch_email"))
            else:
                data_sources.op_set_branch(pid, branch=route)
            data_sources.op_set_status(pid, order_routing._stage_for(
                gsup, route, glines[0].get("quote"), glines[0].get("portal")))
            if psell is not None:
                data_sources.set_order_number(pid, OP["sell"], psell)
            if pcost is not None:
                data_sources.set_order_number(pid, OP["cost_supplier"], pcost)
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


def _resolve_branch(supplier, postcode):
    """(branch, email) for a chosen supplier + postcode: nearest branch for Eurocell/Travis
    Perkins, the UPB Hardie depot for UPB, else (None, None)."""
    if not postcode:
        return None, None
    if supplier in ("Eurocell", "Travis Perkins"):
        nb = branch_finder.nearest_branch(postcode, supplier)
        if nb and nb.get("branch_name"):
            return nb["branch_name"], nb["email"]
    if supplier == "UPB":
        hr = order_routing.hardie_route(postcode)
        return hr.get("branch"), hr.get("branch_email")
    return None, None


def _stage_for_supplier(supplier):
    if supplier in order_routing.PORTAL:
        return "Go To Portal"
    if supplier in order_routing.QUOTE_FIRST:
        return "Needs Quote"
    return "Needs Review"


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
    br, em = _resolve_branch(supplier, pc)
    stage = _stage_for_supplier(supplier)
    try:
        data_sources.op_set_supplier(iid, supplier)
        if br or em:
            data_sources.op_set_branch(iid, branch=br, email=em)
            if br:
                o["branch"] = br
            if em:
                o["branch_email"] = em
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
            res = order_routing.route_order(lines, postcode=pc)
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
            if res.get("branch") or res.get("branch_email"):
                data_sources.op_set_branch(iid, branch=res.get("branch"),
                                           email=res.get("branch_email"))
                if res.get("branch"):
                    o["branch"] = res["branch"]
                if res.get("branch_email"):
                    o["branch_email"] = res["branch_email"]
        else:                                    # SAMPLES / CLEARANCE
            data_sources.op_set_branch(iid, branch=route)
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
                st.caption("Splitting an order (duplicate the Monday item + split the Shopify "
                           "fulfilment) is the next piece of the build — for now set the main "
                           "supplier and note the split.")
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
                        if _br or res.get("branch_email"):
                            data_sources.op_set_branch(iid, branch=_br,
                                                       email=res.get("branch_email"))
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
                    for _, r in edited_lines.iterrows()]
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
                "bytes": pdf, "kind": kind,
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
        g1, g2 = st.columns(2)
        g1.download_button(":material/download: Download", gen["bytes"], file_name=gen["name"],
                           mime="application/pdf", key=f"op_gendl_{iid}", use_container_width=True)
        if g2.button(":material/attach_file: Attach this to Monday", key=f"op_genatt_{iid}",
                     use_container_width=True):
            with st.spinner("Uploading + verifying…"):
                try:
                    r = data_sources.op_upload_po(iid, gen["bytes"], gen["name"])
                    if r.get("ok"):
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
                  "_op_results", "_op_split_pending"):
            st.session_state.pop(k, None)
        st.rerun()
    load_fc = tc[1].button(
        ":material/call_split: Splits",
        help="Fills the Fulfil # column — how many separate Shopify fulfilments each order splits "
             "into (one lookup per order, so it loads on demand).")
    do_all = tc[3].button("Process all", type="primary", use_container_width=True)
    do_sel = tc[4].button("Process selected", type="primary", use_container_width=True)

    st.caption(f"**{len(orders)}** order(s) in *NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)* · "
               "editing **Supplier** or **Stage** writes to Monday **instantly** — no Save needed.")

    _suggestion_box()

    if load_fc:
        with st.spinner("Reading Shopify fulfilments…"):
            fc = {}
            for o in orders:
                sid = (o.get("shopify_id") or "").strip()
                if not sid:
                    continue
                try:
                    split = data_sources.fetch_order_fulfillment_split(sid)
                    fc[o["item_id"]] = len(set(split.values())) or 1
                except Exception:  # noqa: BLE001
                    fc[o["item_id"]] = None
            st.session_state["_op_fcounts"] = fc

    # Dropdown option sets must include every value currently present, or the grid errors.
    sup_opts = list(dict.fromkeys([s for s in sup_labels if s]
                                  + [o.get("supplier") for o in orders if o.get("supplier")]))
    stage_opts = [_stage_disp(s) for s in
                  list(dict.fromkeys(data_sources.OP_STAGES
                                     + [o.get("stage") for o in orders if o.get("stage")]))]
    fcounts = st.session_state.get("_op_fcounts", {})
    store = (data_sources.get_secret("SHOPIFY_STORE") or "").strip()

    def _order_url(sid):
        return f"https://{store}/admin/orders/{sid}" if (store and sid) else None

    # Build the board grid — column order: Select, Order, Open, Fulfil #, then the rest.
    rows = []
    for o in orders:
        rows.append({
            "Select": False,
            "Order": o.get("order_no") or o.get("name") or "",
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
                help="Fulfillment No. — how many separate Shopify fulfilments the order splits "
                     "into (press the 'Splits' button to fill; 2+ means route to more than one "
                     "supplier)."),
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
                            rts[iid] = order_routing.route_order(lines, postcode=pc)
                        except Exception as e:  # noqa: BLE001
                            rts[iid] = {"error": str(e)[:100], "lines": []}
                now_ids, split_ids, results = [], [], []
                for i in tgt:
                    o = orders[i]
                    iid = o["item_id"]
                    if (o.get("stage") or "").strip() != PLACE_ORDER:
                        results.append({"Order": o.get("order_no") or o.get("name"),
                                        "Supplier": o.get("supplier") or "",
                                        "Result": f"already {(o.get('stage') or '—')} — skipped"})
                    elif (rts.get(iid) or {}).get("split"):
                        split_ids.append(iid)                  # splits wait for a confirm
                    else:
                        now_ids.append(iid)
                prog = st.progress(0.0, text="Processing…") if now_ids else None
                for n, iid in enumerate(now_ids):
                    results.append(_process_one(by_id[iid]))
                    if prog:
                        prog.progress((n + 1) / len(now_ids), text=f"Processed {n + 1}/{len(now_ids)}")
                if prog:
                    prog.empty()
            st.session_state["_op_results"] = results
            st.session_state["_op_split_pending"] = split_ids

    results = st.session_state.get("_op_results")
    if results:
        st.markdown("##### Processed")
        st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)
        st.caption("Supplier / branch / stage set on Monday and a PO or packing slip attached, per "
                   "order. **Only orders at stage *Place Order* are processed.** Nothing was emailed "
                   "to a supplier — that stays the team's send step. Hit **↻ Refresh** to see the "
                   "updated board.")

    pend = [i for i in (st.session_state.get("_op_split_pending") or [])
            if i in {o["item_id"] for o in orders}]
    if pend:
        rts = st.session_state.get("_op_routes", {})
        by_id = {o["item_id"]: o for o in orders}
        srows = [{"Order": by_id[i].get("order_no") or by_id[i].get("name"),
                  "Split into": order_routing.summary(rts.get(i) or {})} for i in pend]
        st.warning(f"**{len(srows)} split order(s)** need a quick confirm — a split creates a "
                   "Monday part per supplier **and** restructures the Shopify fulfilment (harder to "
                   "undo than a normal order).")
        st.dataframe(pd.DataFrame(srows), hide_index=True, use_container_width=True)
        s1, s2, _ = st.columns([1.4, 1, 3])
        if s1.button(f"Confirm & split {len(srows)}", type="primary", key="op_splitconfirm"):
            with st.spinner("Splitting…"):
                extra = [_process_one(by_id[i]) for i in pend]
            st.session_state["_op_results"] = (st.session_state.get("_op_results") or []) + extra
            st.session_state.pop("_op_split_pending", None)
            st.rerun()
        if s2.button("Skip splits", key="op_splitskip"):
            st.session_state.pop("_op_split_pending", None)
            st.rerun()

    # Expand each ticked order right off the table — no dropdown. One ticked → opens fully.
    st.divider()
    if not ticked:
        st.caption("Tick an order's **✓** to open its full detail & PO here.")
    else:
        only_one = len(ticked) == 1
        for i in ticked:
            o = orders[i]
            with st.expander(f"{o.get('order_no') or o.get('name')} · {o.get('customer') or '—'}",
                             expanded=only_one):
                _order_detail(o)
