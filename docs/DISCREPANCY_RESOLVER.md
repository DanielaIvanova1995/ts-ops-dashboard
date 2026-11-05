# Discrepancy Resolver — automation engine component (spec)

Goal: stop the manual chasing/updating of invoice discrepancies. Read supplier **replies** to our
discrepancy queries and update the record automatically, and **watch for the credit note**: when one
arrives that matches what we should have been charged, settle it — auto‑approving only when it's a
clean match **and** the order margin is in that supplier's normal band; otherwise hand it to a human.

Decisions (Daniela, 2026‑11‑05):
- **On a clean CN match → auto‑approve to QuickBooks only if the resulting order margin is in the
  supplier's band** (SUPPLIER_RULES push_min/push_max). Anything else → manual approval.
- **Replies are forwarded by the team** into a dedicated place (she'll forward wherever we specify) —
  see "Inbox" below.
- **Built as one piece of the Supabase automation engine** (Platform Plan Phase 3), not a one‑off.

## What already exists (reuse, don't rebuild)
- Discrepancy queries are sent from **accounts@**; replies thread back there.
- TradeHub‑written discrepancy notes already carry the **expected credit in a fixed format**:
  `Awaiting credit note from <supplier> of £<amount> — invoice <inv>, order <order>: <reasons>` —
  parseable to seed a watcher with its target amount.
- **Credit notes import as subitems** (negative total) and attach to the **same order** as the invoice
  (invoice_import). Each invoice subitem has **Progress** (`long_text_mm8jcvz3`), a **reason/query note**
  (`text_mm3gh2za`), an **action marker** (`text_mm3gjrap`, "Queried…"), and **Payment Status**
  (`status7__1`; Discrepancy = label 4, Matched = 9, Needs Review = 3).
- `invoice_core.push_decision` already encodes the per‑supplier auto‑approve margin bands.
- Scheduler + Claude triage classifier + Monday writes + `qbo_create_bill` all exist.

## Inbox (where replies/CNs are read from)
**Primary — automatic, no forwarding.** Our discrepancy queries are sent from **accounts@**, so supplier
replies come back **on the same thread in accounts@**. The engine records each query's Outlook
`conversationId` when it sends it, then reads replies on those threads automatically — the team does
nothing. (It can also match by invoice/order number in the subject/body as a backstop.)

**Fallback — a forward folder for strays.** Only for replies that land somewhere else (a personal
mailbox, or a query someone sent by hand outside TradeHub): the team forwards *those* into a dedicated
folder, proposed **`accounts@ → Discrepancy Replies`**, which the engine also reads. So forwarding is
the exception, not the routine. (Confirm the exact folder name before build; it only needs creating if
we want the fallback.)

## State — Supabase table `discrepancy_watchers`
One row per queried discrepancy:
`sub_id, order_item_id, supplier, invoice_no, order_no, invoice_total, expected_credit,
status (open|agreed|settled|manual|dropped), cn_sub_id, matched_amount, last_reply_at, note, created_at,
updated_at`. Seeded from the existing "Awaiting credit note…" notes on the current Discrepancy queue,
then kept up to date by the two components below. Every change also writes to `audit_log`.

## Component 1 — Reply reader (scheduled)
1. Scan `Discrepancy Replies` for unread/forwarded messages.
2. Match each reply to a watcher by **invoice number / order number** in the subject or body (Claude
   extracts them; fall back to the email thread when we sent the original).
3. **Claude classifies** the reply into: `credit_agreed` (+ amount + CN number if present),
   `disputed` (supplier says the price/charge is correct), `info_needed`, `credit_later`.
4. Act:
   - `credit_agreed` → set `expected_credit` (use the supplier's figure if it differs), status `agreed`,
     append to Progress ("Supplier agreed £X credit on DD — CN <no>"), arm the watcher.
   - `disputed` → status `manual`, flag on Monday ("Needs review — supplier pushback"), Progress note.
   - `info_needed` / `credit_later` → Progress note, keep `open`.
5. Mark the reply handled (move/stamp) so it isn't re‑read. Never auto‑reply to the supplier.

## Component 2 — Credit‑note watcher + settle (on CN import + scheduled sweep)
1. When a credit note imports (hook `invoice_import`) **or** on a periodic sweep, find the matching
   open/agreed watcher by **supplier + order** (then amount ≈ `expected_credit`).
2. Compute: `net = invoice_total − |CN|`; recompute the order's would‑be margin at that net.
3. Decide:
   - **CN ≈ expected_credit (±£0.02 / tiny %) AND margin in the supplier's band** → **auto‑approve**
     the invoice **and** the CN to QuickBooks (`qbo_create_bill` ×2), set both subitems Approved,
     `resync_order_inv_slots`, watcher `settled`, audit it.
   - **CN matches but margin out of band, OR CN ≠ expected (partial/over/under), OR no expected amount
     on file** → watcher `manual`; surface in the checker as **"Ready to approve — check me"** with the
     numbers laid out (invoice, CN, expected, net, margin) for one‑click human approval.
4. Credit notes with **no matching watcher** are left as today (attached to the order, Needs Review).

## Guardrails
- Auto‑approve is the **only** automated financial write, and only under the clean‑match + in‑band rule
  above. Everything else is human‑gated (unchanged platform guardrail).
- Never auto‑reply to a supplier; never auto‑delete; never cross a supplier's price with another's.
- Full audit trail (who/what/when, "engine" as actor) in `audit_log`.

## UI (hub)
A **Discrepancy resolver** view: the watcher list (supplier, invoice, order, expected credit, status,
matched CN), a **"Ready to approve"** queue (the manual ones) with the numbers pre‑laid‑out and a
one‑click Approve, and the auto‑settled history. The existing Discrepancy list links through to it.

## Build order (inside the engine)
1. `discrepancy_watchers` table + seed from current "Awaiting credit note…" notes (read‑only to start).
2. Component 2 settle logic in **report‑only mode** (show what it *would* approve) → verify against real
   CNs for a week.
3. Turn on auto‑approve (clean match + in band).
4. Component 1 reply reader (forward folder) → auto‑update Progress/status.
5. Hub "Discrepancy resolver" view.

## Open questions to confirm at build time
- Exact forward‑folder name + mailbox.
- Tolerance for "matches" (fixed pence vs small %); how to treat VAT on the credit.
- Multi‑invoice orders: match the CN to the specific invoice, not just the order.
- Whether a supplier "agreed" reply with **no** CN yet should pre‑approve on the promise (default: no —
  wait for the actual CN).
