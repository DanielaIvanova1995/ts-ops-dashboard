# TradeHub — Platform Plan (pick up any time)

*Written 2026-08-11, revised 2026-08-16. A roadmap to turn TradeHub from a click-driven Streamlit
app into a reliable, always-on platform that runs the ops **automatically** for a growing team,
surfacing to people only for review and decisions.*

---

## The goal (in Daniela's words)
> "We are a growing team… I hope the platform does a lot for us automatically rather than us
> having to be too involved."

So the target is **hands-off automation + multi-user**, not a prettier manual tool — **on hosting
that doesn't fall over.**

## The key realisation
TradeHub today = **one Streamlit app on a free host** that (a) only does anything while a person has
the page open and (b) crashes/sleeps under load. To get to "the platform does it automatically and
stays up", we need two moves: **reliable hosting first**, then split the app into **two layers**:

1. **The Engine (always-on backend)** — runs jobs on a **schedule** and reacts to **events**
   (new order, statement email, invoice arrives), with **no human needed**. *The whole point.*
2. **The Cockpit (UI)** — people **review, approve, and handle exceptions**. Streamlit is fine for
   this for now; it just becomes a review queue instead of a place you do everything by hand.

> Streamlit can't run things on a timer or react to events by itself — that's why the engine is the
> missing piece, not "a nicer front-end".

## Recommended stack
- **Always-on host (Render)** = where the app (and later the engine) actually runs — dedicated
  memory, never sleeps. **This is Step A and the fix for the outages.**
- **Supabase** = the backbone: a real **database** (Postgres), **logins & roles**, **file storage**
  (POs/statements), realtime, and built-in **scheduled functions** (pg_cron) + webhook endpoints.
  Fixes the current hacks (tokens stored on Monday, wiped disk, config.yaml logins).
- **An always-on Python worker** = the **automation engine**: a small service (FastAPI + scheduler)
  on the same host, running jobs server-side on schedule/events, writing to Supabase + Monday, and
  flagging a human only when needed.
- **UI = Streamlit for now** (reads Supabase, shows review queues, approve buttons). A **React
  front-end on Vercel** is *optional, much later*, only if the UI itself becomes the bottleneck.
- **The Python engine code already built** (routing rulebook, pricing, invoice checker, statement
  reconciliation, PO generation) stays — it just gets **called by the scheduler/engine**, not only
  by a Streamlit click. **None of it is wasted.**

## Recommended order (revised 2026-08-16 — reliability first)

### ✅ Groundwork — DONE (2026-08-16)
Memory optimisation: bounded the app's high-cardinality caches so RAM stays in check on any host.
*(Deployed to the live app.)*

### ▶ Step A — Reliable hosting *(do first — fixes the crashes)*
Move the **current** Streamlit app (unchanged — same screens, logins, features) onto an **always-on
host with dedicated memory** so it stops crashing and sleeping. The app already reads secrets from
environment variables, so no code change is needed. **Prepared and ready on branch
`platform/hosting`** (`Dockerfile` + step-by-step in `DEPLOY_HOSTING.md`).
- *Daniela's bit (~20 min, Phase 0):* create a **Render** account, pick **Standard (2 GB, ~£20/mo)**,
  copy the 13 secrets in as env vars, deploy from `platform/hosting`, test alongside the live app.
- *Then:* merge to `main`, switch the link over, add the new URL to the Shopify/QBO/Microsoft OAuth
  redirect allow-lists.

### Phase 1 — Database backbone *(biggest state-reliability win, low risk)*
Move durable state off the Monday-item hacks / wiped disk into **Supabase tables**: QuickBooks
tokens, saved reconciliations (real history, not one snapshot per supplier), order-processing state,
learned statement→vendor mappings, and an **audit log** (who/what/when). Streamlit keeps working —
it just reads/writes Supabase. *Good first slice: saved reconciliations.*

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
A **React app on Vercel** for a fast, multi-user, board-style cockpit — only once the team size / UI
limits genuinely justify it. The engine + Supabase stay exactly as they are underneath.

## Rough cost
- Always-on host (Render): ~£20/mo (2 GB, comfortable headroom).
- Supabase: free tier → ~$25/mo (Pro) when you outgrow it.
- Vercel (only if/when Phase 5): ~$20/mo.
- **≈ £20–40/month** for a proper always-on, automated, multi-user platform — vs today's £0 fragile
  setup that sleeps, loses state, and went down.

## Guardrails to keep no matter what (unchanged rules)
- **Human-gated sends** — never auto-email a supplier or customer without a review step.
- **Confirmed financial writes** — QuickBooks/payments stay behind an explicit confirm; never
  auto-pay.
- **Secrets only in the secrets store** — never in the repo or in chat; regenerate, don't paste.
- **Never auto-cancel an order** — flag for a manager to find a way to fulfil it.

## How to start
**Step A is ready now.** Follow `DEPLOY_HOSTING.md` to create the Render account and deploy — that's
the only bit that needs Daniela. Once it's live and stable, say the word and Claude begins **Phase 1
(Supabase DB backbone)** on a branch, no risk to the running app.
