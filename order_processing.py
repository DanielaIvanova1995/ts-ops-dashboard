"""Order Processing cockpit (Phase 1) — board-style grid.

Reads the "NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)" group on the Monday Orders board and
shows it like the Monday board itself: one editable row per order with inline Supplier and
Order-Process-Stage dropdowns and a Select tick. Edits are written back to Monday on Save
(Monday stays the source of truth). A detail panel below shows the full order + live Shopify
lines/fulfilments and handles PO download/replace.

Phase 2 (routing engine) and Phase 3 (PO/packing-slip generation + verified attach) plug into
the Process buttons, which are stubbed here.
"""
import html

import pandas as pd
import streamlit as st

import data_sources

DANIELA = "daniela@tradesuperstoreonline.co.uk"
FROM_MAILBOX = "accounts@tradesuperstoreonline.co.uk"

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

    # Live-from-Shopify: the Monday items above are a snapshot from when the order synced. This
    # pulls the CURRENT order (in case it was edited) and adds unit prices, variants + fulfilments.
    if sid and st.button(":material/sync: Refresh from Shopify (live items, prices & fulfilments)",
                         key=f"op_live_{iid}",
                         help="Monday shows the order as it first synced. This fetches the current "
                              "order straight from Shopify — in case it was edited — and adds unit "
                              "prices, variants and the fulfilment split."):
        st.session_state[f"op_liveon_{iid}"] = True
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
    up = st.file_uploader("Replace / attach PO (PDF)", type=["pdf"], key=f"op_po_{iid}")
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

    # Top row: Refresh + Splits on the left, Process ALL / SELECTED tight together on the right.
    tc = st.columns([1.1, 1.2, 3.0, 1.3, 1.7])
    if tc[0].button(":material/refresh: Refresh"):
        for k in ("_op_orders", "_op_detail", "_op_fcounts"):
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
            "Branch email": o.get("branch_email") or "",
            "Supplier": o.get("supplier") or None,
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
        disabled=["Order", "Open", "Fulfil", "Customer", "Branch email", "£ to us", "£ supplier"])

    # ---- Auto-sync every Supplier / Stage edit straight to Monday (no Save button) ----
    for i, o in enumerate(orders):
        try:
            new_sup = edited.iloc[i]["Supplier"]
            if new_sup and new_sup != (o.get("supplier") or None):
                data_sources.op_set_supplier(o["item_id"], new_sup)
                o["supplier"] = new_sup
                st.toast(f"{o.get('order_no')} · supplier → {new_sup}")
            new_stage = _stage_plain(edited.iloc[i]["Stage"])
            if new_stage and new_stage != (o.get("stage") or None):
                data_sources.op_set_status(o["item_id"], new_stage)
                o["stage"] = new_stage
                st.toast(f"{o.get('order_no')} · stage → {new_stage}")
        except Exception as e:  # noqa: BLE001
            st.toast(f"{o.get('order_no')} · didn't save: {str(e)[:70]}")

    # Which rows are ticked — drives both "Process selected" and the expand-detail panels below.
    ticked = [i for i in range(len(orders)) if bool(edited.iloc[i]["Select"])]

    if do_all or do_sel:
        targets = list(range(len(orders))) if do_all else ticked
        if not targets:
            st.warning("No orders ticked — use the ✓ column to pick which to process.")
        else:
            st.info(f"**Routing + PO generation for {len(targets)} order(s) is the next phase.** "
                    "For now, set Supplier/Stage inline (auto-saves to Monday) and attach POs in "
                    "the order panel below. The automatic route → price → build → verify-attach "
                    "flow is next.")

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
