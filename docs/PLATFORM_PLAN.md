# TradeHub — Platform Plan (pick up any time)

*Written 2026-08-11. A roadmap to turn TradeHub from a click-driven Streamlit app into an
always-on platform that runs the ops **automatically** for a growing team, surfacing to people
only for review and decisions.*

---

## The goal (in Daniela's words)
> "We are a growing team… I hope the platform does a lot for us automatically rather than us
> having to be too involved."

So the target is **hands-off automation + multi-user**, not a prettier manual tool.

## The key realisation
TradeHub today = **one Streamlit app** that only does anything while a person has the page open.
For "the platform does it automatically", split it into **two layers**:

1. **The Engine (always-on backend)** — runs jobs on a **schedule** and reacts to **events**
   (new order, statement email, invoice arrives), with **no human needed**. *This is the new
   investment and the whole point.*
2. **The Cockpit (UI)** — people **review, approve, and handle exceptions**. Streamlit is fine
   for this for now; it just becomes a review queue instead of a place you do everything by hand.

> Streamlit can't run things on a timer or react to events by itself — that's why the engine is
> the missing piece, not "a nicer front-end".

## Recommended stack (best fit for automation + a growing team)
- **Supabase** = the backbone: a real **database** (Postgres), **logins & roles**, **file
  storage** (POs/statements), realtime, and built-in **scheduled functions** (pg_cron) + webhook
  endpoints. Fixes the current hacks (tokens stored on Monday, wiped disk, config.yaml logins).
- **An always-on Python worker** = the **automation engine**: a small service (FastAPI + a
  scheduler) on a cheap always-on host (Railway / Render / Fly.io / a VPS) that runs the jobs
  server-side on schedule/events, writes results to Supabase + Monday, and emails/flags a human
  only when needed.
- **UI** = **Streamlit for now** (reads Supabase, shows review queues, approve buttons). Move to a
  **React front-end on Vercel** *later*, only if/when the UI itself becomes the bottleneck.
- **The Python engine code already built** (routing rulebook, pricing, invoice checker, statement
  reconciliation, PO generation) stays — it just gets **called by the scheduler/engine**, not only
  by a Streamlit click. **None of it is wasted.**

## Phased roadmap — each phase is independent, reversible, and done on a branch (live app untouched)

### Phase 0 — Setup *(Daniela, ~15 min, one-off)*
Create a **Supabase** project and an **always-on host** account; put the keys into **Streamlit
Secrets** (never in chat — same rule as QuickBooks/Monday tokens). Then Claude does the code.

### Phase 1 — Database backbone *(biggest reliability win, low risk)*
Move durable state off the Monday-item hacks / wiped disk into **Supabase tables**: QuickBooks
tokens, saved reconciliations (with real history, not one snapshot per supplier), order-processing
state, learned statement→vendor mappings, and an **audit log** (who/what/when). Streamlit keeps
working — it just reads/writes Supabase. *Good first slice: saved reconciliations.*

### Phase 2 — Real logins & roles *(for the growing team)*
**Supabase Auth** replaces the config.yaml bcrypt logins: per-person accounts, roles
(admin / manager / office / processor), password resets, and a proper trail of who did what.

### Phase 3 — The automation engine *(the main prize)*
Stand up the always-on worker + scheduler and move the jobs you already run into it, server-side:
statement pulls from accounts@, invoice checking, PO email dispatch + watchdog, remittance prep,
refund/ETA chasers. They run on a timer, log to Supabase, push to Monday, and only **flag a human
for review** — the team stops doing them by hand. (Replaces the Make.com / Cowork / scheduled-task
patchwork with one owned engine.)

### Phase 4 — Event-driven *(the hands-off endgame)*
**Webhooks** from Shopify/Monday hit the engine so things react **instantly** instead of polling:
e.g. new order → auto-route + draft PO → lands in the review queue; supplier statement arrives →
auto-reconciled and waiting for a pay decision.

### Phase 5 — Polished front-end *(optional, later)*
A **React app on Vercel** for a fast, multi-user, board-style cockpit — only once the team size /
UI limits genuinely justify it. The engine + Supabase stay exactly as they are underneath.

## Rough cost
- Supabase: free tier → ~$25/mo (Pro) when you outgrow it.
- Always-on host: ~$5–20/mo.
- Vercel (only if/when Phase 5): ~$20/mo.
- **≈ £20–40/month** for a proper always-on, automated, multi-user platform — vs today's £0
  fragile setup that sleeps and loses state.

## Guardrails to keep no matter what (unchanged rules)
- **Human-gated sends** — never auto-email a supplier or customer without a review step.
- **Confirmed financial writes** — QuickBooks/payments stay behind an explicit confirm; never
  auto-pay.
- **Secrets only in the secrets store** — never in the repo or in chat; regenerate, don't paste.
- **Never auto-cancel an order** — flag for a manager to find a way to fulfil it.

## How to start (any day)
Say **"let's start the Supabase backend"** and Claude begins on a branch with **Phase 1**
(no risk to the live app). Phase 0 (the ~15-min signup) is the only bit that needs you first.
