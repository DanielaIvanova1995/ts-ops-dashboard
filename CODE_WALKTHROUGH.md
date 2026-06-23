# Trade Hub — Code Walkthrough

Developer hand-off: every function in plain English. Two files do the work —
`data_sources.py` (talks to external services) and `app.py` (UI + business logic).
See `BLUEPRINT.md` for the product overview.

---

## `data_sources.py` — integrations

### Secrets & auth
- `_secrets_file_exists()` — true if a local Streamlit secrets file is present (local vs cloud).
- `get_secret(name)` — read a secret from Streamlit Secrets, falling back to env vars.
- `get_token()` — the Monday.com API token (`MONDAY_API_TOKEN`).
- `_to_number(raw)` — parse a number out of messy text, or `None`.
- `_age_days(iso_ts)` — whole days between an ISO timestamp and now.
- `_monday_headers(token)` — standard Monday API request headers.
- `ms_token()` — Microsoft Graph **app-only** access token (client-credentials grant).
- `shopify_products_token()` — Shopify Admin API token (client-credentials, cached in-process).
- `shopify_configured()` — true if the Shopify secrets are all present.

### Monday — KPIs & activity
- `fetch_live_counts(board_id, token)` — live counts from the summary KPI board.
- `merge_live(kpis, live)` — overlay live counts onto the KPI policy list from `kpis.json`.
- `fetch_orders_group_counts(group_map)` — item count + oldest age per Orders-board group (stage KPIs).
- `fetch_filtered_count(board_id, column_id, compare_values)` — count items matching a status value (e.g. subitem "Needs Review").
- `fetch_booked_split(board_id, group_id, date_col, today)` — split "booked for delivery" into overdue vs future by date.
- `fetch_board_activity(board_id, from_iso, to_iso)` — raw Monday `activity_logs` for a time window, paginated.
- `fetch_group_names(board_id)` — `{group_id: title}` for a board's groups.
- `fetch_user_names(ids)` — `{user_id: name}` for Monday users.

### Shopify
- `shopify_variant_price(sku)` — live price / vendor / store URL for a SKU.
- `shopify_variant_barcode(sku)` — the EAN/barcode for a SKU.
- `fetch_order_discounts(order_ids)` — customer discount + codes per Shopify order (batched via `nodes`).
- `fetch_shopify_chargebacks(token, domain)` — count of active disputes/chargebacks.
- `fetch_sales_pulse(token)` — today's takings vs the same time yesterday.

### Outlook / Microsoft Graph
- `_graph_children(mailbox, folder_id, token)` — child mail folders of a folder.
- `_norm(s)` — normalise a string (case/space/punctuation) for fuzzy folder matching.
- `_find_folder(mailbox, folder_name, token)` — locate a mail folder by (fuzzy) name.
- `fetch_outlook_folder_count(mailbox, folder_name)` — message count of an Outlook folder (KPI source).
- `fetch_folder_messages(mailbox, folder_name, limit)` — recent messages as `{subject, preview}`.
- `send_supplier_email(mailbox, to, subject, body, pdf_url)` — send an email (and attach the invoice PDF) via Graph `sendMail`; needs Mail.Send.

### Invoices (Monday subitems)
- `fetch_invoices_by_status(label_ids, limit)` — all invoices at the given Payment-Status labels, **paginated**, each with its parent order's data (supplier, order items, agreed price, Shopify id, branch email, live margin).
- `monday_asset_url(asset_id)` — a temporary signed download URL for a Monday file.
- `set_invoice_status(sub_id, label)` — write the subitem's Payment Status back to Monday.

### Claude (Anthropic) AI
- `read_invoice_pdf(pdf_url)` — Claude reads the invoice PDF → structured `{lines, totals}`.
- `research_competitors(title, code, vendor, your_price)` — Claude web-searches UK competitor prices (ex-VAT).
- `find_kind_words(emails)` — Claude picks the single nicest customer email.
- `analyze_customer_mood(emails)` — Claude scores overall customer mood + themes.

---

## `app.py` — UI & logic

### Setup, auth, KPI helpers
- `now_uk()` — current Europe/London time.
- `logo_uri()` — brand logo as an inline data URI.
- `status_of(k)` — `green` / `amber` / `red` / `info` for a KPI (count & age vs thresholds).
- `display_owners(k)` — owner display names for a KPI.
- `source_icon(src)` / `target_text(k)` — small UI helpers (source icon, "healthy at N or below").
- `_excluded(pairing)` — usernames to exclude from workload/pairing (managers, opted-out).
- `workload(kpis, pairing)` — per-person weighted workload (count + age) across owned KPIs.
- `mood(kpis)` — backlog-based customer-mood proxy (fallback for the Team Lift card).
- `load_kpis()` — load `kpis.json`, merge all live sources (Monday/Outlook/Shopify), cached.
- `load_pricing()` / `load_lookup()` — read the pricing feed JSONs.
- `_live_price(sku)` — live Shopify sell price for a SKU (cached).
- `_search_payload()` / `_hl(text, ql)` — data + highlight for the instant product search.

### Daily Activity
- `_activity_category(event, dd)` — which work category an activity entry belongs to.
- `_activity_change(event, dd, group_names)` — `(human-readable label, is-low-signal)` for an entry.
- `daily_activity(day_iso, meaningful)` — per-person "who did what" for a day, grouped, cached.
- `render_daily_activity()` — the Daily Activity page.

### Pricing
- `render_product_search()` — the in-browser instant product search widget.
- `_mcol(m)` / `_ptable(...)` / `_sku_rows(...)` — pricing table styling/builders.
- `_find_product(items, q)` — best lookup match for a typed SKU/name.
- `competitor_research(...)` — cached wrapper around the AI competitor lookup.
- `_render_competitor_check(items)` — the competitor-price-check UI.
- `_rules_table(headers, rows)` — HTML table builder for the rules page.
- `render_supplier_rules()` — the **Supplier rules** sub-view (margin + delivery rules).
- `render_pricing()` — the **Pricing** page (tiles, search, lists).

### Invoice Check — core logic
- `_norm_code(s)` — normalise a SKU/supplier (lowercase, alphanumerics).
- `_parse_order_items(text)` — parse Monday's order-items text → `{sku: {sku, qty}}`.
- `_pricelist_index()` — `{sku: {supplier: cost}}` from the pricing lookup.
- `_lookup_by_sku()` — `{sku: {sell, cost, name}}` from the pricing lookup.
- `_order_margin(order_items, lbsku, cost_override)` — margin on an order's items (sell vs cost).
- `_thresholds()` — the current push-margin min/max (from the editable settings box).
- `_is_delivery(text)` — is a line a delivery/carriage/freight line?
- `_expected_delivery(supplier, goods_value)` — expected ex-VAT delivery charge (flat or free-over).
- `_push_decision(matched, is_cn, live_margin, supplier)` — returns `push` / `hold` / `flag` / `None` per the rule (+ supplier overrides).
- `_check_invoice(parsed, meta, pidx)` — the **3-way match**: each line vs pricelist + order, recognises delivery, returns issues.
- `_verdict(res)` — `{order, price}` pass/fail booleans from a check result.
- `_check_and_store(inv, parsed, lbsku, pidx)` — run the check + invoice margin, store the verdict in session.

### Invoice Check — data & rendering
- `invoices_by_status(key)` — cached fetch of invoices for a tab (review/matched/pushed/discrepancy).
- `_order_discounts(order_ids)` — cached Shopify discount lookup for the queue.
- `_read_invoice(asset_id, sub_id, nonce)` — cached PDF read (the `nonce` busts the cache for **Re-run check**).
- `_inv_inline(name, size)` / `_INV_SVG` / `_INV_ICON` — the professional inline SVG icons & INV/CRN badges.
- `_discrepancy_email(inv, res)` — build the supplier chase email (subject + body) from the discrepancy.
- `_run_one_invoice(inv, lbsku)` — render one invoice's full detail: banner, margins, discount, line table, the two checks, action buttons, re-run, and the email-supplier panel.
- `_apply_status(inv, label)` — write a status to Monday, refresh the queues, flash a confirmation.
- `_bulk_check(invs, lbsku)` — read + check every invoice, then auto-process (push / hold / flag) with a progress bar.
- `_invoice_tab(key, is_queue)` — render one tab: supplier filter + search, the table, bulk-check (To-check only), and the expandable review sub-items.
- `render_invoice_check()` — the **Invoice Check** page: counts strip + the four tabs + the editable thresholds box.

### Per-supplier configuration (the bits you tune)
- `DELIVERY_CHARGES` — `{supplier: {name, flat, free_over?}}` known delivery charges.
- `SUPPLIER_RULES` — `{supplier: {name, no_pricelist, push_min, flag_high}}` overrides (e.g. Travis Perkins).
- `INVOICE_STATUS` — maps each tab key to its Monday Payment-Status label ids + fetch limit.
- `MARGIN_PUSH_MIN` / `MARGIN_PUSH_MAX` — default push band (5 / 35), overridable in the UI.

### Summary dashboard & Team Lift
- `_summary_section(k)` — which summary section a KPI belongs to (Emails / Orders / Customer care / Invoices).
- `render_summary_dashboard()` — the one-screen Summary dashboard (headline tiles, email bars, KPI tiles with targets).
- `joke_of_the_day()` — deterministic daily joke.
- `kind_words_cached()` — cached "kind words from a customer" (AI).
- `leaderboard_today()` — live "who did what today" leaderboard from the Monday activity log.
- `_distinct_winners(winners, users_cfg, top)` — assign one badge per person, busiest first.
- `_change_password_dialog()` — the change-password modal.

### Module-level (runs top-to-bottom, not in functions)
- CSS/theme block; authentication; the **sidebar menu** (role-gated, with the Daily-Ops and
  Pricing sub-radios); the **module dispatch** (`if module == ... : render_...(); st.stop()`);
  and the inline **Daily Ops Live board** (greeting, "Today at a glance" Team Lift / pairing /
  workload, the action queue, and All-KPIs-by-category).

---

## Patterns worth knowing
- **Caching:** heavy/external reads use `@st.cache_data(ttl=...)`; clearing or a `nonce` arg
  forces a refresh.
- **Cost control:** anything calling Claude is cached and (for bulk) gated behind a confirmation.
- **Writes to Monday/QuickBooks** go through `set_invoice_status` and are always user-initiated
  or confirmed.
- **Adding a supplier rule** is a one-line edit to `DELIVERY_CHARGES` / `SUPPLIER_RULES`.
