"""
Trade Hub — Trade Superstore management system (Streamlit)
==========================================================
A login-protected, hosted management system for the team. First module:
Daily Ops — KPIs, customer mood, staff workload and the action queue.

• Individual logins per person (see config.yaml) — passwords are bcrypt-hashed.
• "Today at a glance": auto customer-mood score, staff workload, smart pairing.
• Action queue that prompts people to clear outstanding items, with each
  person's own tasks highlighted first when they log in.
• KPI data lives in kpis.json (edit it, or wire load_kpis() to live
  Monday / Shopify / Outlook data — see the function near the bottom).

Run locally:   streamlit run app.py
Deploy free:   push this folder to GitHub → share.streamlit.io → New app.
"""

import base64
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

BASE = Path(__file__).parent
LOGO_PATH = BASE / "assets" / "tso-logo.png"

APP_NAME = "Trade Hub"
TAGLINE = "We build better together"


@lru_cache(maxsize=1)
def logo_uri() -> str:
    """Return the brand logo as a data URI for inline HTML (empty if missing)."""
    try:
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Page config + styling
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=f"{APP_NAME} · Trade Superstore",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap');
  :root{
    --brand:#F26A21; --brand-dark:#D9551A; --ink:#21242B; --muted:#6B7280;
    --line:#E5E7EB; --bg:#F4F5F7; --card:#FFFFFF;
    --red:#DC2626; --red-bg:#FEE2E2; --gold:#C9870A; --gold-bg:#FCF1D6;
    --green:#15803D; --green-bg:#DCFCE7; --blue:#2563EB; --blue-bg:#DBEAFE;
  }
  .stApp {background:var(--bg);}
  .block-container {padding-top: 1.2rem; max-width: 1320px;}
  h1,h2,h3,h4 {color:var(--ink);}
  /* Brand header bar */
  .ts-brandbar {display:flex; align-items:center; gap:16px; background:var(--card);
     border:1px solid var(--line); border-radius:16px; padding:14px 20px; margin-bottom:18px;
     box-shadow:0 1px 3px rgba(16,24,40,.06); border-top:4px solid var(--brand);}
  .ts-brandbar img {height:42px; width:auto;}
  .ts-brandbar .wm {font-size:22px; font-weight:800; letter-spacing:-.3px; color:var(--ink);}
  .ts-brandbar .wm b {color:var(--brand);}
  .ts-brandbar .sct {margin-left:auto; font-size:12px; color:var(--muted); text-align:right;}
  .ts-brandbar .sct b {color:var(--ink);}
  /* Cards */
  .ts-card {background:var(--card); border:1px solid var(--line); border-radius:16px;
     padding:16px 18px; box-shadow:0 1px 3px rgba(16,24,40,.06); height:100%;}
  .ts-card.kpi {border-left:5px solid var(--muted);}
  .ts-eyebrow {font-size:11px; letter-spacing:.1em; text-transform:uppercase;
     color:var(--muted); margin:0 0 8px; font-weight:700;}
  .ts-num {font-size:30px; font-weight:800; line-height:1;}
  .ts-name {font-weight:700; font-size:14px; line-height:1.25; color:var(--ink);}
  .ts-meta {color:var(--muted); font-size:12px; margin-top:6px;}
  .ts-prompt {font-size:12.5px; color:#374151; margin-top:9px; padding-top:9px;
     border-top:1px dashed var(--line);}
  .ts-pill {display:inline-block; font-size:11px; font-weight:700; padding:3px 9px;
     border-radius:999px; letter-spacing:.03em;}
  .red  {color:var(--red);   background:var(--red-bg);}
  .amber{color:var(--gold);  background:var(--gold-bg);}
  .green{color:var(--green); background:var(--green-bg);}
  .blue {color:var(--blue);  background:var(--blue-bg);}
  .stripe-red{border-left-color:var(--red) !important;}
  .stripe-amber{border-left-color:var(--gold) !important;}
  .stripe-green{border-left-color:var(--green) !important;}
  .stripe-blue{border-left-color:var(--blue) !important;}
  .mood-face {font-size:52px; line-height:1;}
  .mood-label{font-size:26px; font-weight:800; margin:0;}
  .bar {height:12px; background:#EEF0F3; border-radius:7px; overflow:hidden;}
  .bar > span {display:block; height:100%; border-radius:7px;}
  .ts-action {display:flex; justify-content:space-between; align-items:center; gap:14px;
     background:var(--card); border:1px solid var(--line); border-left-width:6px;
     border-radius:12px; padding:12px 16px; margin-bottom:10px; box-shadow:0 1px 2px rgba(16,24,40,.05);}
  .ts-action .big {font-size:24px; font-weight:800; line-height:1; text-align:right;}
  .mine {box-shadow:0 0 0 2px rgba(242,106,33,.45);}
  .yourbadge{font-size:10px; font-weight:800; color:#fff; background:var(--brand);
     padding:2px 8px; border-radius:999px; margin-left:8px; letter-spacing:.03em;}
  /* Login */
  .ts-login {display:flex; align-items:center; gap:22px; text-align:left; margin:8px 0 18px;}
  .ts-login img {height:120px; width:auto;}
  .ts-login .wm {font-family:'Bebas Neue',sans-serif; font-size:64px; line-height:.92;
     letter-spacing:1.5px; text-transform:uppercase; color:var(--ink);}
  .ts-login .wm b {color:var(--brand); font-weight:400;}
  .ts-login .tag {color:var(--muted); font-size:14px; margin-top:4px; letter-spacing:.3px;
     text-align:justify; text-align-last:justify;}
  /* Sidebar */
  [data-testid="stSidebar"] {background:#FFFFFF; border-right:1px solid var(--line);}
  .ts-mod {display:block; padding:9px 12px; border-radius:10px; font-weight:600; font-size:14px;
     color:var(--ink); margin-bottom:6px; border:1px solid var(--line);}
  .ts-mod.active {background:rgba(242,106,33,.10); border-color:rgba(242,106,33,.35); color:var(--brand-dark);}
  .ts-mod.soon {color:#9CA3AF; border-style:dashed;}
  /* Streamlit buttons → brand */
  .stButton>button {border-radius:10px; border:1px solid var(--line); font-weight:600;}
  /* Bordered text inputs (login + elsewhere) */
  .stTextInput div[data-baseweb="input"]{border:1px solid #C3C9D4 !important;
     border-radius:8px !important; background:#fff !important;}
  .stTextInput div[data-baseweb="input"]:focus-within{border-color:var(--brand) !important;
     box-shadow:0 0 0 2px rgba(242,106,33,.15) !important;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
with open(BASE / "config.yaml") as f:
    config = yaml.load(f, Loader=SafeLoader)

# The cookie signing key is a real secret — read it from Streamlit Secrets
# (or an env var) in production so it never lives in the public repo. Falls
# back to the placeholder in config.yaml only for local development.
import data_sources

cookie_key = data_sources.get_secret("COOKIE_KEY") or config["cookie"]["key"]

authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    cookie_key,
    config["cookie"]["expiry_days"],
)

# Login screen branding
_logo = logo_uri()
_logo_img = f"<img src='{_logo}' alt='Trade Superstore'>" if _logo else ""
if not st.session_state.get("authentication_status"):
    st.markdown(
        f"""<div class="ts-login">
          {_logo_img}
          <div>
            <div class="wm">Trade <b>Hub</b></div>
            <div class="tag">{TAGLINE}</div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

try:
    authenticator.login(location="main", fields={"Form name": "Sign in to continue"})
except Exception as e:  # noqa: BLE001
    st.error(f"Login error: {e}")

auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    st.error("❌ Username or password is incorrect.")
    st.stop()
if auth_status is None:
    st.info("👋 Enter your username and password. The manager has your personal login — "
            "you can change your password any time from the sidebar after signing in.")
    st.stop()

# --- Authenticated from here on -------------------------------------------
username = st.session_state.get("username")
name = st.session_state.get("name")
role = config["credentials"]["usernames"].get(username, {}).get("role", "staff")

# ---------------------------------------------------------------------------
# Status engine
# ---------------------------------------------------------------------------
COL = {"red": "#ef4444", "amber": "#f97316", "green": "#10b981", "info": "#3b82f6"}
LABEL = {"red": "Act now", "amber": "Keep an eye", "green": "Under control", "info": "Info"}
SEV = {"red": 0, "amber": 1, "green": 2, "info": 3}


def status_of(k: dict) -> str:
    if k.get("info"):
        return "info"
    s = "green"
    if k["count"] > k["target"]:
        s = "amber"
    if k["count"] > k["amber_max"]:
        s = "red"
    if k["oldest_age_days"] >= k["age_amber"] and s == "green":
        s = "amber"
    if k["oldest_age_days"] >= k["age_red"] and s != "green":
        s = "red"
    return s


def display_owners(k: dict) -> str:
    users = config["credentials"]["usernames"]
    names = [users.get(o, {}).get("name", o) for o in k.get("owners", [])]
    return " / ".join(names) if names else "— unassigned —"


def workload(kpis: list) -> dict:
    load: dict = {}
    for k in kpis:
        if k.get("info") or not k.get("owners"):
            continue
        share = len(k["owners"])
        weight = (k["count"] + k["oldest_age_days"] * 0.4) / share
        for o in k["owners"]:
            load[o] = load.get(o, 0) + weight
    return load


def mood(kpis: list) -> dict:
    items = [k for k in kpis if k.get("mood_impact") and not k.get("info")]
    stress = max_stress = 0.0
    for k in items:
        s = status_of(k)
        w = 3 if s == "red" else 1.5 if s == "amber" else 0.3
        stress += w + min(k["oldest_age_days"], 10) * 0.15
        max_stress += 3 + 1.5
    pct = min(100, round((stress / max_stress) * 100)) if max_stress else 0
    if pct < 25:
        face, label, col, desc = "😊", "Happy", "#10b981", "Few open issues and nothing ageing — customers are well looked after."
    elif pct < 50:
        face, label, col, desc = "🙂", "Calm", "#65a30d", "A normal day. A handful of open queries but nothing out of control."
    elif pct < 70:
        face, label, col, desc = "😐", "Mixed", "#f59e0b", "Pressure building — some complaints and overdue deliveries need attention."
    elif pct < 85:
        face, label, col, desc = "😟", "Tense", "#ea580c", "Several frustrated customers and ageing issues. Prioritise the red items now."
    else:
        face, label, col, desc = "😠", "Stressed", "#ef4444", "High frustration risk — overdue deliveries and complaints stacking up. All hands on the red queue."
    open_issues = len([k for k in items if status_of(k) != "green"])
    return {"pct": pct, "face": face, "label": label, "col": col, "desc": desc, "open": open_issues}


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load_kpis() -> dict:
    """Load KPI policy from kpis.json, then overlay LIVE count + age from the
    Monday 'Daily KPI Tracker' board. Falls back to the saved snapshot if the
    Monday token is missing or the API call fails. Cached for 5 minutes."""
    with open(BASE / "kpis.json", encoding="utf-8") as f:
        data = json.load(f)

    data["live"] = False
    try:
        import data_sources

        live = data_sources.fetch_live_counts(data.get("monday_board_id", 18416416116))
        data["kpis"] = data_sources.merge_live(data["kpis"], live)
        data["live"] = True
        data["updated"] = datetime.now().strftime("%d %b %Y · %H:%M")
    except Exception as e:  # noqa: BLE001 — stay up on any data-source hiccup
        data["live_error"] = str(e)
    return data


data = load_kpis()
KPIS = data["kpis"]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    if _logo:
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px'>"
            f"<img src='{_logo}' style='height:34px'><span style='font-weight:800;font-size:18px'>"
            f"Trade<span style='color:#F26A21'>Hub</span></span></div>",
            unsafe_allow_html=True,
        )
    st.caption(f"👤 {name} · {role}")
    authenticator.logout("Log out", location="sidebar")

    st.markdown("###### Modules")
    st.markdown('<div class="ts-mod active">📊 Daily Ops</div>', unsafe_allow_html=True)
    st.markdown('<div class="ts-mod soon">➕ More coming soon</div>', unsafe_allow_html=True)
    st.divider()
    if data.get("live"):
        st.markdown("🟢 **Live** — connected to Monday")
    else:
        st.markdown("🟡 **Snapshot** — saved numbers")
        if data.get("live_error"):
            st.caption(f"({data['live_error']})")
    st.caption(f"🔄 Updated: {data.get('updated','—')}")
    if st.button("↻ Refresh now", use_container_width=True):
        load_kpis.clear()
        st.rerun()
    st.divider()
    with st.expander("🔑 Change my password"):
        try:
            if authenticator.reset_password(username, location="sidebar"):
                with open(BASE / "config.yaml", "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
                st.success("Password changed ✅")
        except Exception as e:  # noqa: BLE001
            st.warning(str(e))
    st.divider()
    st.caption("Sources: Monday.com · Shopify · Outlook")

# ---------------------------------------------------------------------------
# Greeting
# ---------------------------------------------------------------------------
# Branded header bar
live_chip = ("🟢 Live" if data.get("live") else "🟡 Snapshot")
st.markdown(
    f"""<div class="ts-brandbar">
      {_logo_img}
      <span class="wm">Trade<b>Hub</b></span>
      <span class="sct"><b>Daily Ops</b> · {live_chip}<br>updated {data.get('updated','—')}</span>
    </div>""",
    unsafe_allow_html=True,
)

hour = datetime.now().hour
greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
my_kpis = [k for k in KPIS if username in k.get("owners", [])]
my_open = [k for k in my_kpis if not k.get("info") and status_of(k) != "green"]
st.markdown(f"### {greet}, {name.split()[0]} 👋")
if role == "staff":
    if my_open:
        st.markdown(
            f"You have **{len(my_open)}** item{'s' if len(my_open)!=1 else ''} needing attention today — "
            "they’re highlighted below.")
    else:
        st.success("You’re all clear — nothing outstanding on your KPIs right now. 🎉")

# ---------------------------------------------------------------------------
# Today at a glance: Mood / Pairing / Workload
# ---------------------------------------------------------------------------
m = mood(KPIS)
load = workload(KPIS)
ranked = sorted(load.items(), key=lambda x: x[1], reverse=True)
users_cfg = config["credentials"]["usernames"]

c1, c2, c3 = st.columns([1.15, 1, 1])

with c1:
    st.markdown(
        f"""<div class="ts-card">
          <p class="ts-eyebrow">Today at a glance — Customer mood</p>
          <div style="display:flex;align-items:center;gap:16px">
            <div class="mood-face">{m['face']}</div>
            <div><p class="mood-label" style="color:{m['col']}">{m['label']}</p></div>
          </div>
          <div class="bar" style="margin-top:12px"><span style="width:{m['pct']}%;background:{m['col']}"></span></div>
          <p class="ts-meta">{m['desc']} ({m['open']} customer-facing issue{'s' if m['open']!=1 else ''} open)</p>
        </div>""",
        unsafe_allow_html=True,
    )

with c2:
    if len(ranked) >= 2:
        busy_u, busy_v = ranked[0]
        quiet_u, quiet_v = ranked[-1]
        busy_name = users_cfg.get(busy_u, {}).get("name", busy_u)
        quiet_name = users_cfg.get(quiet_u, {}).get("name", quiet_u)
        busy_kpis = sorted(
            [k for k in KPIS if not k.get("info") and busy_u in k.get("owners", [])],
            key=lambda k: SEV[status_of(k)],
        )
        handover = busy_kpis[0]["name"] if busy_kpis else "a task"
        handover_n = busy_kpis[0]["count"] if busy_kpis else 0
        st.markdown(
            f"""<div class="ts-card">
              <p class="ts-eyebrow">Smart pairing — who helps who</p>
              <div style="margin-bottom:10px">
                <span class="ts-pill red">🔴 Busiest · {busy_name}</span>
                &nbsp;←&nbsp;
                <span class="ts-pill green">🟢 Quietest · {quiet_name}</span>
              </div>
              <div style="background:rgba(59,130,246,.12);border-left:4px solid #3b82f6;
                   border-radius:8px;padding:11px 13px;font-size:13px;line-height:1.5;color:#dbe3ff">
                Suggest <b>{quiet_name}</b> takes <b>“{handover}”</b> ({handover_n} open) off
                <b>{busy_name}</b> today. When it’s cleared, {busy_name.split()[0]} returns the favour
                on the next spike.
              </div>
            </div>""",
            unsafe_allow_html=True,
        )

with c3:
    rows = ""
    mx = max(load.values()) if load else 1
    for u, v in ranked:
        pct = round(v / mx * 100)
        col = "#ef4444" if pct > 75 else "#f97316" if pct > 45 else "#10b981"
        nm = users_cfg.get(u, {}).get("name", u).split()[0]
        rows += (
            f'<div style="margin-bottom:11px"><div style="display:flex;justify-content:space-between;'
            f'font-size:13px;margin-bottom:4px"><span style="font-weight:600">{nm}</span>'
            f'<span style="color:#9aa1c7">{v:.0f}</span></div>'
            f'<div class="bar"><span style="width:{pct}%;background:{col}"></span></div></div>'
        )
    st.markdown(
        f'<div class="ts-card"><p class="ts-eyebrow">Staff workload (volume + age)</p>{rows}</div>',
        unsafe_allow_html=True,
    )

st.write("")

# ---------------------------------------------------------------------------
# Action queue
# ---------------------------------------------------------------------------
queue = sorted(
    [k for k in KPIS if not k.get("info") and status_of(k) != "green"],
    key=lambda k: (SEV[status_of(k)], -k["oldest_age_days"]),
)
# Put the logged-in person's own items first
if role == "staff":
    queue.sort(key=lambda k: username not in k.get("owners", []))

reds = len([k for k in queue if status_of(k) == "red"])
ambers = len([k for k in queue if status_of(k) == "amber"])
st.markdown(
    f"### ⚡ Act now — outstanding items "
    f"<span class='ts-pill red'>{reds} red</span> "
    f"<span class='ts-pill amber'>{ambers} amber</span>",
    unsafe_allow_html=True,
)

for k in queue:
    s = status_of(k)
    mine = role == "staff" and username in k.get("owners", [])
    yb = "<span class='yourbadge'>YOUR TASK</span>" if mine else ""
    st.markdown(
        f"""<div class="ts-action stripe-{s} {'mine' if mine else ''}">
          <div>
            <div class="ts-name">{k['name']}{yb}</div>
            <div class="ts-meta">Owner: <b style="color:#cbd2f5">{display_owners(k)}</b> · {k['source']}</div>
            <div class="ts-prompt" style="border:none;padding:0;margin-top:6px">→ {k['action']}</div>
          </div>
          <div style="text-align:right;white-space:nowrap">
            <div class="big" style="color:{COL[s]}">{k['count']}</div>
            <div class="ts-meta">oldest {k['oldest_age_days']}d</div>
            <span class="ts-pill {s}" style="margin-top:6px;display:inline-block">{LABEL[s]}</span>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )
if not queue:
    st.success("🎉 Nothing outstanding — every KPI is under control.")

# ---------------------------------------------------------------------------
# All KPIs by category
# ---------------------------------------------------------------------------
st.write("")
st.markdown("### 📊 All KPIs")
ICONS = {"Orders & Fulfilment": "📦", "Customer Care": "💬", "Finance & Risk": "💷"}
for cat in dict.fromkeys(k["cat"] for k in KPIS):
    st.markdown(f"#### {ICONS.get(cat,'📊')} {cat}")
    cards = [k for k in KPIS if k["cat"] == cat]
    cols = st.columns(3)
    for i, k in enumerate(cards):
        s = status_of(k)
        with cols[i % 3]:
            age = f" · oldest {k['oldest_age_days']}d" if k["oldest_age_days"] else ""
            st.markdown(
                f"""<div class="ts-card kpi stripe-{s}" style="margin-bottom:14px">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
                    <div class="ts-name">{k['name']}</div>
                    <div class="ts-num" style="color:{COL[s]}">{k['count']}</div>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
                    <span class="ts-meta">Owner: <b style="color:#cbd2f5">{display_owners(k)}</b></span>
                    <span class="ts-pill {s}">{LABEL[s]}</span>
                  </div>
                  <div class="ts-meta">{k['source']}{age}</div>
                  <div class="ts-prompt">{k['action']}</div>
                </div>""",
                unsafe_allow_html=True,
            )

st.caption(
    "Numbers are the latest snapshot from kpis.json. Wire load_kpis() to Monday / Shopify / "
    "Outlook for a fully automatic live feed. Thresholds and owners are editable in kpis.json."
)
