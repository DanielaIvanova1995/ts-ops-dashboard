# Trade Hub — System Blueprint

A login-protected Streamlit web portal for **Trade Superstore Online**, deployed on
Streamlit Cloud (auto-deploys from GitHub `DanielaIvanova1995/ts-ops-dashboard`).
Branded orange `#F26A21` / charcoal `#21242B`, Bebas Neue headings.

> Living document — kept up to date as the portal grows.

---

## 🔐 Access & logins

- Individual logins (bcrypt-hashed in `config.yaml`): Daniela (admin), Natasha, Megan,
  Melissa, Malyeka, Lorena.
- **`office`** login — role `office`, restricted to **Daily Ops only** (the other modules
  are hidden in the menu *and* blocked at dispatch, even if session state is tampered).
- Sidebar: logo, menu, "Data & connections" status, "Settings" (change password), Sign out.
- Cookie signing key + all API secrets live in **Streamlit Secrets** (never in the repo).

---

## 📋 Modules

### 1. Daily Ops  *(sub-views: Live board / Summary dashboard)*
- **Live board** — KPIs from Monday/Outlook/Shopify with red/amber/green status; the
  **Team Lift** card (live leaderboard from real "done today" Monday activity + kind words
  from a customer via AI + joke of the day); smart pairing (busiest ↔ quietest); staff
  workload bars; an "Act now" action queue; all KPIs grouped by category.
- **Summary dashboard** — one-screen, mostly-numbers overview: headline tiles
  (needs attention / emails / orders / invoices), an Emails bar chart, and colour-coded
  KPI tiles per section, each showing **count (target)**.

### 2. Daily Activity
"Who did what" for a chosen day from the Monday activity log (orders board **and**
subitems): per-person totals, grouped into work categories (Deliveries, ETAs, Invoices,
Customer care, Orders), collapsible per category, CSV export, and a "meaningful changes
only" filter (hides file uploads / link edits).

### 3. Pricing  *(sub-views: Pricing / Supplier rules)*
- **Pricing** — supplier pricing built from Airtable + Shopify: cheapest supplier,
  loss-making, below-target, multi-supplier, unmatched, per-supplier pricelists, and an
  instant in-browser product search. Plus a **Competitor price check** (Claude web search,
  ex-VAT, on demand).
- **Supplier rules** — read-only tables of per-supplier margin/push rules and delivery
  charges (so the team can see exactly how each supplier is handled).

### 4. Invoice Check
The supplier-invoice reconciliation workflow (see next section).

---

## 🧾 Invoice Check (detail)

Reads supplier invoices on Monday's **Subitems of Orders** board (id `3547638043`) and
runs a 3-way check on each.

**Tabs** (with live counts, pulls *all* invoices via pagination):
`To check` (Needs Review) · `Matched (held)` · `Pushed to QB` · `Discrepancies`.

**Per invoice** (click a row, or Bulk-check):
- Reads the PDF with Claude → line items (SKU, qty, unit price, totals).
- **3-way match:** price vs the supplier's **pricelist**, SKUs & quantities vs the
  **Shopify order**, and recognises known **delivery charges**.
- Shows: **INV/CRN** badge, **Invoice margin** (this invoice) + **Order margin** (Monday,
  whole order), **customer discount** (Shopify), **agreed price** (Monday £-to-Supplier),
  line-by-line table with flags, PDF + "View order on Shopify" links.

**Auto-rule (per checked invoice):**
- Fully matched + order margin **5–35%** → **pushed to QuickBooks** (Approved To QB / CN).
- Matched + **< 5%** → **held as Matched (TradeHub)** for review.
- Matched + **> 35%** → **flagged as Discrepancy** (likely a missing invoice/credit note).
- 3-way mismatch → left in *To check* for manual handling.
- Thresholds editable in a Settings box (defaults 5 / 35).

**Actions:** Push to QB / Mark Matched / Flag discrepancy (recommended highlighted) ·
**Re-run check** · **Email supplier** (sends directly from `accounts@` with the PDF
attached, body auto-built from the discrepancy) · **Bulk-check & process** (whole filtered
queue, always confirms with a cost estimate).

**Supplier overrides** (`SUPPLIER_RULES`):
- **Travis Perkins** — no pricelist (order/Shopify check only), push if margin **≥ 10%**
  else hold and suggest raising the website price, no high-margin flag.

**Delivery charges** (`DELIVERY_CHARGES`, ex-VAT; only flagged if charged *more*):
- Molan £23.74 flat · PJH £25 flat · Travis Perkins £25 under £100, free over.

---

## 🔌 Integrations

| Source | Used for |
|---|---|
| **Monday.com** | Orders board `1786542990` (KPIs, activity, leaderboard); Subitems board `3547638043` (invoices); Payment-status write-back |
| **Shopify** | Live prices, chargebacks, customer discounts, order links, daily sales |
| **Microsoft Graph (Outlook)** | Email-folder counts, reading customer emails, sending supplier chases |
| **Airtable** | Supplier pricelists (consumed by the daily refresh) |
| **Anthropic (Claude)** | Invoice reading, competitor search, kind words, customer mood |

Key Monday `status7__1` (subitem Payment Status) label ids: Needs Review = 3,
Discrepancy = 4, Approved (To QB) = 2, CN Approved (To QB) = 0, Matched (TradeHub) = 9.

---

## 🔄 Daily pricing refresh

Runs **6am on the office PC** via a Windows scheduled task → `build-dashboard.ps1`:
pulls Airtable + Shopify, rebuilds the pricing feeds (`pricing_summary.json`,
`pricing_lookup.json`), copies them into this repo and pushes (Streamlit redeploys).
Hardened: keeps the PC awake, retries the export, never pushes stale data, paginates
(~16 suppliers / ~38k SKUs).

---

## 💷 Costs

Everything is **free except the AI** (your Anthropic key), and only when used:
- Invoice read ≈ **1–4p** each (cached) · Competitor check ≈ **2–5p** · Kind words/mood **< 1p**.
- **Bulk-check** is the only thing that adds up — it confirms with an estimate first.
- Recommended: set a monthly usage cap in the Anthropic console.

Free: all dashboards, Monday/Shopify/Outlook reads, the daily refresh, order links,
discount lookups.

---

## 🗂 Key files

- `app.py` — all UI + logic (modules, Invoice Check, supplier rules).
- `data_sources.py` — every integration (Monday, Shopify, Graph, Anthropic).
- `config.yaml` — logins/roles · `kpis.json` — KPI policy · `.streamlit/config.toml` — theme.
- `pricing_summary.json` / `pricing_lookup.json` — pricing feeds (regenerated daily).
- `requirements.txt` — dependencies.
- `../supplier-pricing-dashboard/` — the daily refresh: `dashboard.py`, `export_summary.py`,
  `build-dashboard.ps1`.
