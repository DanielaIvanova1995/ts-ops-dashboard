"""Order Processing cockpit (Phase 1).

Reads the "NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)" group on the Monday Orders board and
lets whoever is processing orders see the full order, the fulfilment breakdown, change the
Order Process Stage and the routed Supplier (both written straight back to Monday), download or
replace the PO, and send a suggestion to Daniela. Monday stays the source of truth.

Phase 2 (routing engine from the supplier rulebook) and Phase 3 (PO/packing-slip generation +
verified attach) plug into the `Process` buttons, which are stubbed here.
"""
import html

import streamlit as st

import data_sources

DANIELA = "daniela@tradesuperstoreonline.co.uk"
FROM_MAILBOX = "accounts@tradesuperstoreonline.co.uk"


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
    """Lazy-load (and cache) the live Shopify line items + fulfilment split for one order."""
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
    with st.expander("💡 Suggestion / report a problem (emails Daniela)"):
        st.caption("Anything that doesn't work, or would help you process orders faster — this "
                   "goes straight to Daniela.")
        who = st.text_input("Your name", value="Natasha", key="op_sugg_who")
        msg = st.text_area("What's up?", key="op_sugg_msg", height=110,
                           placeholder="e.g. the supplier dropdown is missing X, or the PO for "
                                       "order 29xxx has the wrong branch…")
        if st.button("✉ Send to Daniela", key="op_sugg_send", type="primary",
                     disabled=not msg.strip()):
            subj = f"TradeHub Order Processing — suggestion from {who or 'the team'}"
            body = (f"From: {who or 'the team'}\n\n{msg.strip()}\n\n"
                    "— sent from TradeHub Order Processing")
            try:
                data_sources.send_supplier_email(FROM_MAILBOX, DANIELA, subj, body)
                st.success("Sent to Daniela — thank you!")
                st.session_state["op_sugg_msg"] = ""
            except Exception:  # noqa: BLE001
                try:
                    link = data_sources.create_supplier_draft(FROM_MAILBOX, DANIELA, subj, body)
                    st.success("Saved as a draft to send." + (f" [Open]({link})" if link else ""))
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't send: " + str(e)[:150])


def _order_card(o, sup_labels):
    iid = o["item_id"]
    stage = o.get("stage") or ""
    supplier = o.get("supplier") or ""
    title = f"{o.get('name') or o.get('order_no') or iid} · {o.get('customer') or '—'}"
    badge = f"  ·  {stage}" if stage else ""
    with st.expander(title + badge):
        pick = st.checkbox("Select to process", key=f"op_pick_{iid}")

        det, ctrl = st.columns([3, 2])
        with det:
            st.markdown(f"**Order:** {_esc(o.get('order_no') or o.get('name'))}  \n"
                        f"**Customer:** {_esc(o.get('customer'))} · {_esc(o.get('phone'))} · "
                        f"{_esc(o.get('cust_email'))}  \n"
                        f"**Deliver to:** {_esc(o.get('address'))}", unsafe_allow_html=True)
            if o.get("items"):
                st.markdown("**Order items (Monday):**")
                st.text(o["items"][:2000])
            sid = (o.get("shopify_id") or "").strip()
            if sid:
                if st.button("🔎 Load live Shopify detail (variants + fulfilments)",
                             key=f"op_live_{iid}"):
                    st.session_state[f"op_liveon_{iid}"] = True
                if st.session_state.get(f"op_liveon_{iid}"):
                    d = _live_detail(sid)
                    if d.get("error"):
                        st.caption("Couldn't read Shopify: " + d["error"])
                    if d.get("lines"):
                        import pandas as pd
                        df = pd.DataFrame([{"SKU": ln.get("sku") or "", "Item": ln.get("title"),
                                            "Qty": ln.get("qty"),
                                            "Unit £": ln.get("price")} for ln in d["lines"]])
                        st.dataframe(df, hide_index=True, use_container_width=True)
                    split = d.get("split") or {}
                    locs = sorted(set(split.values()))
                    if locs:
                        st.markdown(f"**Fulfilments:** {len(locs)} — " + ", ".join(_esc(l)
                                    for l in locs))
                        for l in locs:
                            skus = [s for s, loc in split.items() if loc == l]
                            st.caption(f"• {l}: {', '.join(skus)}")
                    else:
                        st.caption("**Fulfilments:** 1 (not split)")
            else:
                st.caption("No Shopify Order ID on this Monday item — live detail unavailable.")

        with ctrl:
            # ---- Order Process Stage (writes to Monday) ----
            stages = data_sources.OP_STAGES
            si = stages.index(stage) if stage in stages else 0
            new_stage = st.selectbox("Order Process Stage", stages, index=si,
                                     key=f"op_stage_{iid}")
            if st.button("Set stage on Monday", key=f"op_stageset_{iid}",
                         disabled=(new_stage == stage)):
                try:
                    data_sources.op_set_status(iid, new_stage)
                    o["stage"] = new_stage
                    st.success(f"Stage → {new_stage}")
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't set stage: " + str(e)[:150])

            # ---- Supplier (writes to Monday) ----
            # Keep the order's current supplier first even if it's not in the board's label list.
            opts = list(dict.fromkeys([supplier] + (sup_labels or []))) if supplier else \
                (sup_labels or [])
            if opts:
                idx = opts.index(supplier) if supplier in opts else 0
                new_sup = st.selectbox("Supplier", opts, index=idx, key=f"op_sup_{iid}")
                if st.button("Set supplier on Monday", key=f"op_supset_{iid}",
                             disabled=(new_sup == supplier)):
                    try:
                        data_sources.op_set_supplier(iid, new_sup)
                        o["supplier"] = new_sup
                        st.success(f"Supplier → {new_sup}")
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't set supplier: " + str(e)[:150])
            else:
                st.caption("Couldn't load the supplier list.")

            # ---- PO file (download / replace) ----
            st.markdown("**PO / document**")
            for a in (o.get("po_assets") or []):
                url = a.get("url")
                if url:
                    st.markdown(f"📄 [{_esc(a.get('name'))}]({url})")
            up = st.file_uploader("Replace / attach PO (PDF)", type=["pdf"],
                                  key=f"op_po_{iid}", label_visibility="collapsed")
            if up is not None and st.button("Attach to Monday (replaces latest)",
                                            key=f"op_poset_{iid}"):
                with st.spinner("Uploading + verifying…"):
                    try:
                        res = data_sources.op_upload_po(iid, up.getvalue(), up.name)
                        if res.get("ok"):
                            st.success(f"Attached & verified ({res['size']:,} bytes).")
                            st.session_state["_op_orders"] = None
                        else:
                            st.error(f"Upload didn't verify — {res.get('n_assets')} asset(s) on "
                                     "the item, none matched the exact size. Try again.")
                    except Exception as e:  # noqa: BLE001
                        st.error("Upload failed: " + str(e)[:180])
        return pick


def render():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Order Processing</span></span></div>""",
        unsafe_allow_html=True)

    top = st.columns([1, 1, 2])
    if top[0].button("↻ Refresh"):
        for k in ("_op_orders", "_op_detail"):
            st.session_state.pop(k, None)
    try:
        orders = _orders()
    except Exception as e:  # noqa: BLE001
        st.error("Couldn't read the orders board: " + str(e)[:200])
        return
    sup_labels = _supplier_labels()
    st.caption(f"**{len(orders)}** order(s) in *NEW ORDERS TO SEND OUT TO SUPPLIERS (NATASHA)* · "
               "changes to Stage, Supplier and the PO write straight back to Monday.")

    _suggestion_box()

    # Process controls (routing + PO generation land here in Phase 2/3).
    pcols = st.columns([1, 1, 3])
    do_all = pcols[0].button("⚙ Process all", type="primary")
    do_sel = pcols[1].button("⚙ Process selected")

    picks = []
    for o in orders:
        if _order_card(o, sup_labels):
            picks.append(o["item_id"])

    if do_all or do_sel:
        targets = [o["item_id"] for o in orders] if do_all else picks
        if not targets:
            st.warning("No orders selected — tick 'Select to process' on the ones you want.")
        else:
            st.info(f"**Routing + PO generation for {len(targets)} order(s) is the next phase.** "
                    "For now, set the Supplier and Stage on each order above (both sync to "
                    "Monday), and attach/replace the PO. The automatic route → price → build → "
                    "verify-attach flow is being built next.")
