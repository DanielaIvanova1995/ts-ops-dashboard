-- TradeHub — complete Supabase schema. Paste the whole thing into Supabase → SQL Editor and Run.
-- Safe to re-run (every statement is "if not exists"). Covers all 13 tables the app uses, plus the
-- service_role grants (Supabase has "auto-expose new tables" off, so writes 401 without them).

-- 1. Saved statement reconciliations (history)
create table if not exists reconciliations (
  id         bigint generated always as identity primary key,
  vendor_id  text not null,
  supplier   text,
  saved_at   timestamptz not null default now(),
  snapshot   jsonb not null
);
create index if not exists reconciliations_vendor_idx on reconciliations (vendor_id, saved_at desc);

-- 2. QuickBooks OAuth token (single row)
create table if not exists qbo_tokens (
  id         int primary key default 1,
  tokens     jsonb not null,
  updated_at timestamptz not null default now()
);

-- 3. Learned statement-supplier -> QuickBooks vendor mapping
create table if not exists vendor_map (
  supplier_key text primary key,
  vendor_id    text not null,
  vendor_name  text,
  updated_at   timestamptz not null default now()
);

-- 4. Append-only audit log
create table if not exists audit_log (
  id      bigint generated always as identity primary key,
  at      timestamptz not null default now(),
  actor   text, action text, detail text, ref text
);

-- 5. Invoice importer: de-dup + outcome log
create table if not exists invoice_imports (
  internet_id text primary key,
  status      text not null,
  supplier    text, order_no text, invoice_no text, subitem_id text,
  total       numeric, detail text,
  at          timestamptz not null default now()
);
create index if not exists invoice_imports_status_idx on invoice_imports (status, at desc);

-- 6. Small key/value config store (schedules, folder picks, last-run status)
create table if not exists app_config (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);

-- 7. Durable invoice-PDF parse cache (so a checked invoice is never re-read by Claude)
create table if not exists invoice_parses (
  key    text primary key,
  parsed jsonb not null,
  at     timestamptz not null default now()
);

-- 8. Scheduled invoice-check log
create table if not exists invoice_check_log (
  sub_id     text primary key,
  outcome    text not null,
  invoice_no text, order_no text, supplier text, reason text,
  at         timestamptz not null default now()
);
create index if not exists invoice_check_log_outcome_idx on invoice_check_log (outcome, at desc);

-- 9. Email triage: de-dup + outcome log
create table if not exists email_triage (
  internet_id text primary key,
  status      text not null,
  subject text, sender text, category text, owner text, folder text, detail text,
  at          timestamptz not null default now()
);
create index if not exists email_triage_status_idx on email_triage (status, at desc);

-- 10. Quote-queue triage: de-dup + outcome log
create table if not exists quote_triage (
  internet_id text primary key,
  status      text not null,
  subject text, sender text, category text, folder text, detail text,
  at          timestamptz not null default now()
);
create index if not exists quote_triage_status_idx on quote_triage (status, at desc);

-- 11. Invoice-check verdicts (rehydrate the checker after a reconnect)
create table if not exists invoice_verdicts (
  sub_id  text primary key,
  verdict jsonb not null,
  at      timestamptz not null default now()
);

-- 12. Claude API usage / cost log (the running-cost display)
create table if not exists llm_usage (
  id            bigint generated always as identity primary key,
  at            timestamptz not null default now(),
  day           date not null,
  model         text, feature text,
  input_tokens  int, output_tokens int,
  cost_usd      numeric
);
create index if not exists llm_usage_day_idx on llm_usage (day desc);

-- 13. Supplier assignment / change log (routing override-rate)
create table if not exists supplier_change_log (
  id           bigint generated always as identity primary key,
  item_id      text,
  order_no     text,
  old_supplier text,
  new_supplier text,
  source       text,   -- 'auto' | 'manual'
  conf         text,
  stage        text,
  actor        text,
  at           timestamptz not null default now()
);
create index if not exists supplier_change_log_at_idx on supplier_change_log (at desc);

-- Grant every table to the service role (the app connects as service_role).
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
