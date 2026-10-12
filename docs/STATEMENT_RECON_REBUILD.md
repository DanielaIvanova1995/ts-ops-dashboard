# TradeHub web app — Statement Reconciliation (scope + plan)

*Written 2026-10-12. The second screen to rebuild on the new web app (after Order Processing).
Same approach: reuse the existing Python; build a fast React screen; run alongside the live app.*

## What it does (parity target)
Upload/pull a supplier **statement** → parse it → match each invoice to **QuickBooks** bills →
show what's **outstanding vs paid vs missing**, flag **overdue** (red) and **credit notes**, then
build an **oldest-first remittance** ("pay these") and record it. Saved reconciliations keep a
history.

## What's already built & reusable (the good news)
- **QuickBooks: CONNECTED and healthy** (token refreshed 2026-10-12). Tokens live in Monday (+
  Supabase), refresh is automatic — so the new API reuses the QB layer **as-is, no OAuth work**:
  `qbo_vendor_bills`, `qbo_vendor_payments`, `qbo_find_vendor`, `qbo_vendor_map_load/save`,
  `qbo_query`, `qbo_create_*` (for marking paid), `qbo_valid_access` (auto-refresh).
- **Statement parsing**: `read_statement_pdf` (Claude) + `_statement_file_text` (xlsx/csv) — reusable.
- **The matching engine**: the logic in `_bulk_reconcile_one` (match statement invoices → QB bills by
  number, per-supplier invoice-number normalisation `_norm_inv_no`, open-only = payable, paid refs) —
  headless, extract into a shared function.
- **Overdue / credit-note / payments-already-made** logic (`_is_overdue`, the pay-workflow rules) —
  reusable.
- **Supabase** store: `recon_save` / `recon_latest` / `recon_history`, `qbo_vendor_map`,
  `qbo_tokens` — for saved history + durability.

## What's new to build
1. **Backend (FastAPI, reusing the above):**
   - `POST /recon/parse` — upload a statement PDF/CSV (file upload) → parsed lines.
   - `POST /recon` — parse + match to QuickBooks → reconciliation result (matched / outstanding /
     paid / missing, overdue flags, credit notes, statement balance vs ready-to-pay).
   - `GET /recon/saved` + `GET /recon/history/{vendor}` — saved reconciliations (Supabase).
   - `POST /recon/pay` — record an oldest-first remittance: mark the chosen bills **paid in
     QuickBooks** (financial write — **confirm-gated**) and draft the remittance email (**human-gated
     send**, never automatic).
   - `GET /recon/qb-status` — show QB connected + company name.
2. **Front-end (React):** upload/drop a statement; the reconciliation table (overdue in red, credits,
   matched/paid/missing, totals); **select-all**; the "pay these" remittance panel with the oldest-
   first list and a clear confirm; saved-history view.

## Guardrails (carried over)
- **Confirmed financial writes** — marking a bill paid / recording a payment in QuickBooks is behind
  an explicit confirm; nothing auto-pays.
- **Human-gated sends** — remittance emails are drafted for review, never sent automatically.
- **A supplier's own figures only** — never cross suppliers.
- Locked behind the same access code as the order board.

## Dependencies / the one thing to confirm
- **QuickBooks** ✅ connected (verified today) — no action.
- **Supabase**: needed for **saved history + vendor-map durability**. The core flow (upload →
  reconcile → pay) works without it in-session; history/persistence needs Supabase connected (it was
  being set up). Not a blocker for a first usable version.

## Rough timing (QB being connected removes the big unknown)
- **Phase A — reconcile & view** (upload → parse → match QB → table with overdue/credits/totals):
  **~1–2 focused sessions.**
- **Phase B — pay / remittance** (oldest-first, mark paid in QB behind a confirm, draft remittance):
  **~1 session** (careful — it touches money).
- **Phase C — saved history** (Supabase) + optional **auto-pull statements from accounts@**:
  **~1 session.**
- **Total ≈ 2–3 sessions** to full parity.

## How to start
Say go and I begin **Phase A**: a backend `/recon` endpoint reusing the parser + QB matching, and a
read-only reconciliation screen you can point at a statement and see it reconcile — alongside the
live app, no risk. Then Phase B (pay) and C (history).
