# TradeHub — Order Processing rebuild (Phase 1 of the proper web app)

*Written 2026-10-12. The first screen of the "proper web app" — a fast, live order-processing board
that reuses the existing Python logic and runs ALONGSIDE the current Streamlit TradeHub with zero
disruption. Builds on [PLATFORM_PLAN.md](PLATFORM_PLAN.md).*

---

## The promise (read this first)
- **Your current TradeHub keeps running, untouched**, on `tradehub-mntu.onrender.com`. You use it every
  day exactly as now while this is built.
- The new order-processing board is built as a **separate app at its own URL**. Both read/write the
  **same Monday + Shopify**, so the data is identical — there's no second copy of your orders.
- You switch over **only when you've used the new one and agreed it's better.** We retire the old
  order screen then — nothing before.
- **Nothing in this build touches the live Streamlit app.**

## Why it will feel "fast fast fast" (the whole reason we're doing this)
Streamlit re-runs the whole page on every click. The new app doesn't. It will have:
- **Instant select-all / clear-all / ticking** — no page reload, just the board updates.
- **Live validation as you type** — order number checked instantly; margin shown and colour-warned
  as you type a price.
- **Optimistic updates** — change a supplier and it reflects immediately while saving to Monday in
  the background.
- **No cold starts, no "lost my work"** — a real web front-end with proper state.

## What the board does (feature parity with today, then better)
Everything the current Natasha order screen does, rebuilt live:
1. **List the NEW ORDERS group** from Monday (order no, customer, supplier, stage, £ to us, £ supplier).
2. **Open an order in Shopify** / show its lines + shipping address.
3. **Route an order** (same `order_routing` rules) → suggested supplier, branch, stage, PO email.
4. **Edit Supplier / Stage** inline → writes to Monday instantly (optimistic).
5. **Generate the PO / packing slip PDF** (same `order_docs`) and attach it to the Monday item.
6. **Process all / selected** — in safe batches, with a live progress bar (already chunked today).
7. **Splits** — show fulfilment counts on demand; handle split parts; merge parts.
8. **Fulfilment count** per order, on demand (kept lazy — it's a Shopify call per order).

## Guardrails baked in from day one (non-negotiable — carried from the current rules)
- **PO delivery address is NEVER the billing address** — only the Shopify *shipping* address, a typed
  override, or our office. Block/flag if shipping is unreadable. *(Carried from the 31641 fix.)*
- **A supplier's PO/cost uses ONLY that supplier's own price** — never another supplier's.
- **Human-gated sends** — the app never emails a supplier automatically; a person reviews/sends.
- **Confirmed financial writes** — nothing auto-pays or auto-writes to QuickBooks.
- **Monday stays the source of truth** for orders; the app reads/writes it, doesn't replace it.
- **Secrets only in the host's env store** — never in the repo or chat.

## The stack (reuses your existing work — nothing wasted)
- **Backend API — FastAPI (Python).** Wraps the **existing** modules: `order_routing.py`,
  `data_sources.py` (Monday + Shopify calls), `order_docs.py` (PO/slip PDFs). The business brain is
  reused as-is; we just expose it as web endpoints instead of Streamlit calls.
- **Front-end — Next.js (React).** The fast, live board. Hosted on **Vercel** (this is the one place
  Vercel is genuinely the right tool — it's built for React).
- **Supabase** — logins/roles + an audit trail (who changed what). *Optional for the first usable
  version* — order processing can read/write Monday + Shopify without it, so we can get you something
  live sooner and add real logins right after.
- **Hosting:** backend = a **new Render service** on your Pro workspace (separate from the live app);
  front-end = **Vercel** (free to start). The live Streamlit app is a third, untouched service.

## Where the code lives
A new folder in this repo (so the backend can import the existing Python directly):
```
/api   → FastAPI backend (imports order_routing, data_sources, order_docs)
/web   → Next.js front-end (the live board)
```
The existing Streamlit app (`app.py` + modules) stays exactly where it is and keeps running.

## API surface (first cut)
- `GET  /orders` — the NEW ORDERS group from Monday (+ cached Shopify bits)
- `GET  /orders/{id}/lines` — Shopify line items + shipping address
- `POST /orders/{id}/route` — run routing → suggestion
- `POST /orders/{id}/supplier` — set supplier (+ branch/email) on Monday
- `POST /orders/{id}/stage` — set stage on Monday
- `POST /orders/{id}/po` — build PO/slip PDF + attach to Monday
- `POST /orders/{id}/process` — full route→write→PO for one order
- `GET  /orders/{id}/fulfilment` — fulfilment count (on demand)
- `POST /orders/merge` — merge split parts

## Build order (each step is usable on its own)
1. **Backend skeleton** — FastAPI service that imports the existing modules and serves `GET /orders`
   from live Monday. Deploy to a new Render service. *(Proves reuse + live data.)*
2. **Read-only board** — Next.js board on Vercel showing the live orders, fast. You can look at it
   next to the old one and compare.
3. **Inline edits** — Supplier/Stage edits write to Monday (optimistic), instant select/clear.
4. **Routing + PO** — route an order, generate + attach the PO, with the shipping-address guardrail.
5. **Process all/selected** — batched, live progress.
6. **Splits + merge + fulfilment counts.**
7. **Live niceties** — order-number check + live margin warning as you type.
8. **Supabase logins & roles** — real per-person accounts, audit trail. Then cut over from the old
   screen.

## What I need from you
- **Go-ahead on the stack** (FastAPI + Next.js on Vercel + Supabase for logins).
- **Supabase**: is the project ready? If not, I'll start on steps 1–6 without it and add logins at
  step 8.
- A **new Render service** for the backend and a **Vercel account** — I'll give you exact click-by-click
  when we reach deploy (same hand-holding as the Render upgrade). Nothing needed from you until then.

## Rough extra cost (on top of today's ~£44/mo)
- Backend on Render (can start on a small Standard/Starter): ~£7–20/mo.
- Vercel front-end: **free** to start (Hobby is fine for an internal tool; Pro only if needed later).
- Supabase: **free** tier to start.
- So roughly **£7–20/mo more** while building; still well within the platform-plan budget.

## Cutover (when it's ready)
Use both side by side → once you're happy the new order board is faster and correct → we point your
team at the new URL for order processing and retire the old screen. The other screens (invoice
checker, reconciliation, quotes, triage) stay on the current TradeHub until we rebuild each in turn.
