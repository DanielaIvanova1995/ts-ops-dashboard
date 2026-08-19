# Move TradeHub to an always-on host (reliability fix)

*Goal: get TradeHub off Streamlit's free Community Cloud (which crashed and sleeps) onto a host
with **dedicated memory that never sleeps**. Nothing about the app changes — same screens, same
logins, same features. This is Step A of the platform plan and the fix for the outage.*

**The live app stays running the whole time.** We stand the new one up alongside it, test it, and
only switch over once it's proven. Zero risk to what the team uses today.

---

## What you need to do (Daniela) — one-off, ~20 minutes

Everything below is account setup + copying secrets. **Never paste any secret/token into chat** —
you enter them straight into the host's dashboard, same rule as always.

### 1. Pick the host + size
Recommended: **Render** (simplest dashboard). Sizing matters — the crash was memory, so we want
headroom:

| Plan | RAM | ~Cost | Verdict |
|---|---|---|---|
| Render **Standard** | 2 GB | ~£20/mo | ✅ Recommended — comfortable headroom for the whole team |
| Render Starter | 512 MB | ~£6/mo | ❌ Smaller than the free tier — would crash sooner |

(Railway or Fly.io also work with the same `Dockerfile` and can be a little cheaper with tuning —
tell me if you'd prefer one of those and I'll adjust the steps.)

### 2. Create the service
1. Sign up at **render.com** (log in with the GitHub account that owns the repo).
2. **New → Web Service** → connect the repo **`DanielaIvanova1995/ts-ops-dashboard`**.
3. Render detects the **`Dockerfile`** → Runtime = **Docker** (leave build/start commands blank —
   the Dockerfile handles them).
4. Instance type = **Standard (2 GB)**.
5. **Health Check Path** = `/_stcore/health`  ← important so Render knows when it's ready.
6. Branch = **`platform/hosting`** for the first test build. Once we're happy, we merge it into
   `main` and switch Render to `main`.

### 3. Add the secrets (Environment tab)
Copy each value from your **current** Streamlit Cloud secrets (Manage app → Settings → Secrets) into
Render's **Environment → Add Environment Variable**. Same names, same values:

```
COOKIE_KEY
MONDAY_API_TOKEN
SHOPIFY_ADMIN_TOKEN
SHOPIFY_STORE
SHOPIFY_STORE_DOMAIN
SHOPIFY_CLIENT_ID
SHOPIFY_CLIENT_SECRET
MS_CLIENT_ID
MS_CLIENT_SECRET
MS_TENANT_ID
QBO_CLIENT_ID
QBO_CLIENT_SECRET
ANTHROPIC_API_KEY
```

(Not every one is required — but copy across whatever you already have set. The app reads env vars
first, so these just work.)

### 4. Deploy + test
Render builds and gives you a URL like `https://tradehub-xxxx.onrender.com`. Sign in and check a few
pages (Daily Ops, Order Processing). The old app is still live in parallel — nothing lost.

### 5. Switch over (only once happy)
- Point your usual link/bookmark to the new URL, **or** set up a custom domain in Render
  (e.g. `tradehub.tradesuperstoreonline.co.uk`) — I'll walk you through the DNS.
- **Redirect URIs:** Shopify/QuickBooks/Microsoft OAuth apps list the old Streamlit URL as an allowed
  redirect. Add the new URL there too (I'll give you the exact list when we switch).

---

## What Claude has prepared (no action needed)
- `Dockerfile` + `.dockerignore` — turnkey container build for any of the hosts above.
- The app already reads secrets from environment variables, so it's portable as-is.

## What stays exactly the same
- The whole app, all logins, all features, Monday/Shopify/Airtable integrations.
- The guardrails: human-gated sends, confirmed financial writes, secrets only in the secrets store.

---

*After this, the next platform steps (Supabase backend for durable state + real logins, then the
automation engine) build on top — see `PLATFORM_PLAN.md`.*
