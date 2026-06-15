# Trade Hub — Trade Superstore management system

*We build better together.*

**Trade Hub** is the team's login-protected management system. Its first module,
**Daily Ops**, shows the daily KPIs, an auto-calculated **customer mood**,
**staff workload**, a **quietest-helps-busiest pairing** suggestion, and an
**action queue** that highlights each person's own outstanding tasks when they log in.

Built with Streamlit. Once deployed it has a real URL you can open from any phone
or computer — no files to open, no installs for the team. New modules slot in
alongside Daily Ops as you build them out.

---

## What each file is

| File | What it does |
|------|--------------|
| `app.py` | The Trade Hub app (Daily Ops module). |
| `data_sources.py` | Pulls live numbers from the Monday "Daily KPI Tracker" board. |
| `config.yaml` | The login accounts (passwords are bcrypt-hashed, never plain text). |
| `kpis.json` | KPI policy + fallback numbers (thresholds, owners, action prompts). |
| `set_password.py` | Set or reset someone's password from the command line. |
| `assets/tso-logo.png` | The Trade Superstore logo used on the login + header. |
| `requirements.txt` | The libraries the app needs (used automatically when deploying). |
| `.streamlit/config.toml` | The brand theme (orange + charcoal on white). |

---

## The logins

Each person has their **own password** (handed out separately by the manager).
They can change it any time from the sidebar → *Change my password*. To set or
reset one: `python set_password.py username "new password"`.

| Username | Person | Role |
|----------|--------|------|
| `admin` | Daniel (Manager) | admin |
| `natasha` | Natasha Stewart | staff |
| `megan` | Megan Steer | staff |
| `melissa` | Mel Duffy | staff |
| `malyeka` | Malyeka Najib | staff |
| `daniela` | Daniela | staff |
| `lorena` | Lorena | staff |

> ⚠️ Please change the temporary password and the `cookie.key` value in
> `config.yaml` before you share the link widely.

---

## Put it online (≈ 5 minutes, free)

You only do this once.

1. **Create a free GitHub account** at <https://github.com> (skip if you have one).
2. **Create a new repository** — name it e.g. `ts-ops-dashboard`, set it to
   **Private**, and upload every file in this folder (GitHub's *“uploading an
   existing file”* drag-and-drop is fine — include `kpis.json`, `config.yaml`,
   `app.py`, `data_sources.py`, `requirements.txt` and the `.streamlit` folder).
3. **Go to <https://share.streamlit.io>** and sign in with that GitHub account.
4. Click **“Create app” → “Deploy a public app from GitHub”**, choose your repo,
   set **Main file path** to `app.py`, and click **Deploy**.
5. **Turn on live data:** in the app's **Settings → Secrets**, paste this one line
   and save (get the token from Monday → your avatar → *Developers* → *My Access
   Tokens*):

   ```toml
   MONDAY_API_TOKEN = "paste-your-monday-token-here"
   ```

   The sidebar will switch from 🟡 *Snapshot* to 🟢 *Live — connected to Monday*.
6. After a minute you'll get a URL like `https://ts-ops-dashboard.streamlit.app`.
   **That's the link you send the team.** Bookmark it on the shop screens.

---

## Where the numbers come from

The dashboard reads the **Monday “Daily KPI Tracker” board** (id `18416416116`)
live — the `Count` and `Oldest age (days)` columns for each KPI — and refreshes
every 5 minutes (or instantly via the sidebar **↻ Refresh now**). So whenever
that board updates, the dashboard moves on its own.

- **No token set?** The app falls back to the saved numbers in `kpis.json` and
  shows a 🟡 *Snapshot* badge — still fully usable.
- **Thresholds, owners, action prompts and the red/amber limits** live in
  `kpis.json` (each KPI is matched to its Monday row by `monday_item_id`). Edit
  there to retune what counts as “Act now”.

> The Monday board itself is refreshed by your existing dashboard script. The web
> app is as live as that board — point the script at a shorter interval if you
> want the underlying counts to update more often.

---

## Adding or removing people

- **Add a person:** add a block under `usernames` in `config.yaml`, then run
  `python set_password.py their_username "their password"`. Commit the change.
- **Reset a forgotten password:** `python set_password.py natasha "NewPassword1"`.

> Note: password changes made *inside the app* on Streamlit Cloud are only
> temporary (the cloud resets the file when the app sleeps). The permanent way
> to set passwords is `set_password.py` + commit, or move the credentials into
> Streamlit's **Secrets** (Settings → Secrets) for the manager to control.

---

## Run it on your own PC first (optional)

```powershell
cd C:\Users\danie\ts-ops-dashboard
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Then open <http://localhost:8501>.

---

## Going further (optional)

Live Monday data is already wired (`data_sources.py`). Optional next steps:

- **Pull chargebacks straight from Shopify** instead of via the Monday mirror —
  add a `fetch_shopify_chargebacks()` to `data_sources.py` using a Shopify Admin
  API token in Secrets.
- **Outlook folder counts** (pre-delivery queries, quotes) — these currently come
  through the Monday board. Reading them directly needs a Microsoft Graph app
  registration; the Monday mirror is the simpler route and already works.
- **Always-on (no sleep)** — upgrade the Streamlit app to a paid tier, or host on
  a small always-on server.
