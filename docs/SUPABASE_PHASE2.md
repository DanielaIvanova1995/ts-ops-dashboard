# Platform Phase 2 — Per-user logins + per-module access control

Replaces the single shared access code (and the Statements 6-digit passcode) with **per-person
logins**, where each person is allowed exactly the modules you tick. Built **feature-flagged**: the
app keeps using the shared access code until you switch logins on, so nothing breaks mid-rollout.

Decisions (2026-11-03): **admin sets/resets passwords** (no email reset); **Statements is a module
permission** (no separate passcode once logins are on).

## 1. Create the users table (Supabase → SQL editor)

Run this once. (Same `service_role` grant gotcha as Phase 1 — auto-expose is OFF on this project.)

```sql
create extension if not exists pgcrypto;         -- for gen_random_uuid()

create table if not exists public.tradehub_users (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  name          text,
  password_hash text not null,
  role          text not null default 'staff',    -- 'admin' | 'staff'
  modules       jsonb not null default '[]'::jsonb, -- ["orders","quotes",...]
  active        boolean not null default true,
  last_login    timestamptz,
  created_at    timestamptz not null default now()
);

grant all on public.tradehub_users to service_role;
alter default privileges in schema public grant all on tables to service_role;
```

Module keys: `orders, quotes, invoices, recon, pricing, triage, payments, assistant`
(admins implicitly get all of them).

## 2. Add two secrets on Render (the API service)

- `TRADEHUB_AUTH_SECRET` — a long random string used to sign login tokens. Keep it secret; if you
  ever change it, everyone is simply logged out and signs in again. (Generate e.g. a 40+ char random.)
- `TRADEHUB_AUTH` — leave **unset** for now. Setting it to `1` is the switch that turns logins on.

With `TRADEHUB_AUTH` unset, the new code is inert and the shared access code keeps working.

## 3. Turn it on (when the hub's login screen is deployed)

1. Set `TRADEHUB_AUTH=1` on Render and let it redeploy.
2. Open the hub — it now shows **"Create the first admin"** (because logins are on but no users exist
   yet). Enter the current **shared access code**, your email, your name and a password → you're the
   admin. (This one-time screen is backed by `POST /auth/bootstrap`, which only works while there are
   zero users and only for someone who knows the shared code.)
3. Go to **Users** (admin-only) and add each staff member: name, email, a password you set, and tick
   the modules they can open. Deactivate anyone instantly with the Active toggle.

To roll back at any point: unset `TRADEHUB_AUTH` on Render — the hub reverts to the shared access
code. The users table is left intact for when you turn it back on.

## API (for reference)

- `GET /auth/status` — `{enabled, has_users}`; the hub uses this to pick login vs shared-code vs the
  create-first-admin screen.
- `POST /auth/login` `{email,password}` → `{token, user}`. The hub stores the token and sends it as
  `Authorization: Bearer <token>` on every request.
- `GET /auth/me` — the signed-in user. `GET /auth/modules` — module keys→labels for the tick-boxes.
- `POST /auth/bootstrap` — first admin only (shared code + zero users).
- Admin-only: `GET/POST /auth/users`, `PATCH /auth/users/{id}`, `POST /auth/users/{id}/password`,
  `DELETE /auth/users/{id}`.

Guards: when `enabled()`, every endpoint checks the signed-in user is active and allowed the module
its path maps to (`auth_core.module_for_path`); cross-section actions allow any signed-in user. When
not enabled, the old `TRADEHUB_ACCESS_KEY` / `TRADEHUB_STATEMENTS_KEY` behaviour is unchanged.
