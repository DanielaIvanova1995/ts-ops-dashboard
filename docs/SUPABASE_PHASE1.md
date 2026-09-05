# Platform Phase 1 — Database backbone (Supabase)

*Move durable state off the fragile Monday-item hacks / wiped disk into a real Postgres database, so
nothing is lost on a restart and we get proper history + an audit trail. The app keeps working
exactly the same — it just reads/writes Supabase underneath. **Feature-flagged**: inactive until
`SUPABASE_URL` + `SUPABASE_SERVICE_KEY` are set, so `main`/the live apps are untouched until we flip
it on.*

## Daniela's bit (~15 min, one-off)
1. Sign up at **supabase.com** (free tier is fine to start).
2. **New project** → name `tradehub`, region **EU (London or Frankfurt)**, set a strong DB password
   (save it in your password manager).
3. When it's built: **Project Settings → API** — copy the **Project URL** and the **`service_role`**
   key. (Don't paste them in chat.)
4. In **Render → `tradehub` service → Environment**, add two variables (no quotes):
   - `SUPABASE_URL` = the Project URL (e.g. `https://abcd1234.supabase.co`)
   - `SUPABASE_SERVICE_KEY` = the `service_role` key
   Save (it redeploys).
5. In Supabase → **SQL Editor**, paste and run the **schema below** once.

Then tell Claude — the saved-reconciliations slice gets switched on and verified, with the current
Monday storage kept as a fallback.

## Schema (run once in Supabase SQL Editor)
```sql
-- Saved statement reconciliations (history, not one snapshot per supplier)
create table if not exists reconciliations (
  id         bigint generated always as identity primary key,
  vendor_id  text not null,
  supplier   text,
  saved_at   timestamptz not null default now(),
  snapshot   jsonb not null
);
create index if not exists reconciliations_vendor_idx on reconciliations (vendor_id, saved_at desc);

-- QuickBooks OAuth token (single row), off the Monday-item hack
create table if not exists qbo_tokens (
  id         int primary key default 1,
  tokens     jsonb not null,
  updated_at timestamptz not null default now()
);

-- Learned statement-supplier -> QuickBooks vendor mapping
create table if not exists vendor_map (
  supplier_key text primary key,
  vendor_id    text not null,
  vendor_name  text,
  updated_at   timestamptz not null default now()
);

-- Append-only audit log (who did what, when)
create table if not exists audit_log (
  id      bigint generated always as identity primary key,
  at      timestamptz not null default now(),
  actor   text,
  action  text,
  detail  text,
  ref     text
);
```

## Code
- `supabase_db.py` — the client + helpers, all gated on `configured()` and best-effort (a Supabase
  hiccup never breaks the app). Uses the `supabase` Python client (added to `requirements.txt`).
- **First slice to wire:** saved reconciliations — `recon_save`/`recon_latest`/`recon_history`,
  with the existing Monday storage kept as a fallback so there's zero risk during changeover.
- Then: QBO token storage, the vendor map, and the audit log.

## Rollout (safe, incremental)
1. On the `platform/supabase` branch, wire one slice at a time to use Supabase **when configured**,
   else the current storage. Merge to `main` only once verified — both hosts stay safe throughout.
2. When all slices are on Supabase and proven, retire the Monday-item hacks.

## Guardrails (unchanged)
Human-gated sends · confirmed financial writes · secrets only in the host's env (never the repo) ·
never auto-cancel an order.
