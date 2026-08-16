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
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

import delivery_rules

BASE = Path(__file__).parent
LOGO_PATH = BASE / "assets" / "tso-logo.png"

APP_NAME = "Trade Hub"
TAGLINE = "We build better together"

# Streamlit Cloud runs in UTC — show UK time (auto-handles BST/GMT).
UK_TZ = ZoneInfo("Europe/London")


def now_uk() -> datetime:
    return datetime.now(UK_TZ)


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
  /* Tighter, slicker vertical spacing between elements */
  [data-testid="stVerticalBlock"]{gap:0.55rem;}
  h1,h2,h3,h4 {color:var(--ink);}
  /* Brand header bar */
  .ts-brandbar {display:flex; align-items:center; gap:16px; background:var(--card);
     border:1px solid var(--line); border-radius:4px; padding:14px 20px; margin-bottom:16px;
     border-top:3px solid var(--brand);}
  .ts-brandbar img {height:42px; width:auto;}
  .ts-brandbar .wm {font-family:'Bebas Neue',sans-serif; font-size:42px; line-height:1;
     letter-spacing:1px; text-transform:uppercase; color:var(--ink);}
  .ts-brandbar .wm b {color:var(--brand); font-weight:400;}
  .ts-brandbar .wm .sec {color:var(--muted);}
  .ts-brandbar .sct {margin-left:auto; font-size:12px; color:var(--muted); text-align:right;}
  .ts-brandbar .sct b {color:var(--ink);}
  /* Cards */
  .ts-card {background:var(--card); border:1px solid var(--line); border-radius:4px;
     padding:16px 18px; height:100%;}
  .ts-card.kpi {border-left:3px solid var(--muted);}
  /* Table cards: table sits flush to the edges, corners clipped → slick + uniform */
  .ts-tbl {padding:0 !important; overflow:hidden;}
  .ts-tbl table {width:100%; border-collapse:collapse;}
  .ts-eyebrow {font-size:11px; letter-spacing:.1em; text-transform:uppercase;
     color:var(--muted); margin:0 0 8px; font-weight:700;}
  .ts-num {font-size:30px; font-weight:800; line-height:1;}
  .ts-name {font-weight:700; font-size:14px; line-height:1.25; color:var(--ink);}
  .ts-meta {color:var(--muted); font-size:12px; margin-top:6px;}
  .ts-prompt {font-size:12.5px; color:#374151; margin-top:9px; padding-top:9px;
     border-top:1px solid var(--line);}
  .ts-pill {display:inline-block; font-size:11px; font-weight:700; padding:3px 8px;
     border-radius:3px; letter-spacing:.03em;}
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
  .bar {height:10px; background:#EEF0F3; border-radius:2px; overflow:hidden;}
  .bar > span {display:block; height:100%; border-radius:2px;}
  .ts-action {display:flex; justify-content:space-between; align-items:center; gap:14px;
     background:var(--card); border:1px solid var(--line); border-left-width:4px;
     border-radius:4px; padding:12px 16px; margin-bottom:8px;}
  .ts-action .big {font-size:24px; font-weight:800; line-height:1; text-align:right;}
  .mine {box-shadow:0 0 0 2px rgba(242,106,33,.45);}
  .yourbadge{font-size:10px; font-weight:800; color:#fff; background:var(--brand);
     padding:2px 7px; border-radius:3px; margin-left:8px; letter-spacing:.03em;}
  /* Login */
  .ts-login {display:flex; align-items:center; gap:22px; text-align:left; margin:8px 0 18px;}
  .ts-login img {height:120px; width:auto;}
  .ts-login .wm {font-family:'Bebas Neue',sans-serif; font-size:64px; line-height:.92;
     letter-spacing:1.5px; text-transform:uppercase; color:var(--ink);}
  .ts-login .wm b {color:var(--brand); font-weight:400;}
  .ts-login .tag {color:var(--muted); font-size:20px; font-weight:600; margin-top:6px;
     letter-spacing:.2px;}
  /* Sidebar */
  [data-testid="stSidebar"] {background:#FFFFFF; border-right:1px solid var(--line);}
  .ts-mod {display:block; padding:9px 12px; border-radius:10px; font-weight:600; font-size:14px;
     color:var(--ink); margin-bottom:6px; border:1px solid var(--line);}
  .ts-mod.active {background:rgba(242,106,33,.10); border-color:rgba(242,106,33,.35); color:var(--brand-dark);}
  .ts-mod.soon {color:#9CA3AF; border-style:dashed;}
  /* Streamlit buttons → brand */
  .stButton>button {border-radius:4px; border:1px solid var(--line); font-weight:600;}
  /* Sidebar menu: left-aligned, menu-like */
  [data-testid="stSidebar"] .stButton>button {justify-content:flex-start; text-align:left;}
  /* Collapsible section titles → look like real titles */
  [data-testid="stExpander"] summary p {font-size:17px !important; font-weight:700 !important;
     color:var(--ink) !important; margin:0;}
  [data-testid="stExpander"] summary {font-weight:700;}
  /* Bordered text inputs (login + elsewhere) */
  .stTextInput div[data-baseweb="input"]{border:1px solid #C3C9D4 !important;
     border-radius:4px !important; background:#fff !important;}
  .stTextInput div[data-baseweb="input"]:focus-within{border-color:var(--brand) !important;
     box-shadow:0 0 0 2px rgba(242,106,33,.15) !important;}
  /* ---- Squared, polished look (edgy corners everywhere, no pills) ---- */
  .stButton>button{border-radius:2px !important;}
  [data-testid="stExpander"]{border-radius:2px !important;}
  [data-testid="stExpander"] details{border-radius:2px !important;}
  [data-baseweb="select"]>div{border-radius:2px !important;}
  [data-baseweb="input"]{border-radius:2px !important;}
  .stTextInput div[data-baseweb="input"]{border-radius:2px !important;}
  [data-testid="stDataFrame"],[data-testid="stTable"]{border-radius:2px !important;}
  [data-testid="stVerticalBlockBorderWrapper"]{border-radius:2px !important;}
  .ts-brandbar,.ts-card,.ts-action,.ts-mod{border-radius:2px !important;}
  .ts-pill,.stCheckbox{border-radius:2px;}
  /* ---- Invoice grid (inline expandable rows) ---- */
  .thg-head{background:#F6F7F8;border:1px solid var(--line);border-bottom:none;
     font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);
     font-weight:700;padding:7px 4px;}
  .thg-cell{font-size:12.5px;color:var(--ink);line-height:1.3;padding:3px 0;
     white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .thg-cell b{font-weight:700;}
  .thg-sub{color:var(--muted);}
  .thg-badge{display:inline-block;height:19px;vertical-align:-4px;margin-right:5px;}
  .thg-mg-hi{color:var(--green);font-weight:700;}
  .thg-mg-lo{color:#EA580C;font-weight:700;}
  .thg-mg-vh{color:var(--red);font-weight:700;}
  .thg-mg-na{color:#AAB0B8;}
  .thg-open{border-left:3px solid var(--brand);background:#FCFDFC;padding:2px 0 12px 16px;
     margin:0 0 6px;}
  .thg-dupe{background:var(--red);color:#fff;font-size:9.5px;font-weight:700;padding:1px 5px;
     border-radius:2px;margin-left:6px;letter-spacing:.5px;}
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
# Read the display name fresh from config (not the auth cookie) so name changes
# take effect immediately without needing a re-login.
name = config["credentials"]["usernames"].get(username, {}).get("name") \
    or st.session_state.get("name")
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


def source_icon(src: str) -> str:
    """A small icon making each KPI's data source obvious at a glance."""
    s = (src or "").lower()
    if "outlook" in s:
        return "📧"  # email folder
    if "shopify" in s:
        return "🛒"  # Shopify
    if "monday" in s:
        return "📋"  # Monday board
    return "•"


def target_text(k: dict) -> str:
    """Where this KPI should sit — the healthy target staff are aiming for."""
    if k.get("info"):
        return ""
    t = k["target"]
    return f"🎯 Healthy at {t} or below" if t > 0 else "🎯 Target: 0 (none should be open)"


# Managers/admins are left out of the busiest/quietest ranking and pairing.
EXCLUDED_PAIRING_ROLES = {"admin", "manager"}


def _excluded(pairing: bool) -> set:
    """Managers/admins are always out of the staff-workload view. Additionally,
    when computing the pairing (busiest/quietest), people flagged
    exclude_from_pairing (e.g. Malyeka — works solo) are left out too, while
    still appearing in the workload bars."""
    users = config["credentials"]["usernames"]
    out = set()
    for u, info in users.items():
        if info.get("role") in EXCLUDED_PAIRING_ROLES:
            out.add(u)
        elif pairing and info.get("exclude_from_pairing"):
            out.add(u)
    return out


def workload(kpis: list, pairing: bool = False) -> dict:
    excluded = _excluded(pairing)
    load: dict = {}
    for k in kpis:
        if k.get("info"):
            continue
        owners = [o for o in k.get("owners", []) if o not in excluded]
        if not owners:
            continue
        weight = (k["count"] + k["oldest_age_days"] * 0.4) / len(owners)
        for o in owners:
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
@st.cache_data(ttl=600, show_spinner=False)
def load_kpis() -> dict:
    """Load KPI policy from kpis.json, then overlay LIVE count + age from the
    Monday 'Daily KPI Tracker' board. Falls back to the saved snapshot if the
    Monday token is missing or the API call fails. Cached for 5 minutes."""
    with open(BASE / "kpis.json", encoding="utf-8") as f:
        data = json.load(f)

    import concurrent.futures as _cf
    import data_sources

    data["live"] = False
    try:
        live = data_sources.fetch_live_counts(data.get("monday_board_id", 18416416116))
        data["kpis"] = data_sources.merge_live(data["kpis"], live)
        data["live"] = True
        data["updated"] = now_uk().strftime("%d %b %Y · %H:%M")
    except Exception as e:  # noqa: BLE001 — stay up on any data-source hiccup
        data["live_error"] = str(e)

    by_id = {k["id"]: k for k in data["kpis"]}
    group_map = {k["id"]: k["orders_group_id"] for k in data["kpis"] if k.get("orders_group_id")}
    today = now_uk().date()
    outlook_kpis = [k for k in data["kpis"] if k.get("outlook")]
    mailboxes = {k["outlook"]["mailbox"] for k in outlook_kpis}

    # Each task returns (kind, value, error) so it can run independently in a thread.
    def _safe(kind, fn):
        try:
            return (kind, fn(), None)
        except Exception as e:  # noqa: BLE001
            return (kind, None, str(e))

    tasks = [
        lambda: _safe("groups", lambda: data_sources.fetch_orders_group_counts(group_map)),
        lambda: _safe("booked", lambda: data_sources.fetch_booked_split(
            1786542990, "group_mkv7t11j", "date", today)),
        lambda: _safe("invoices", lambda: data_sources.fetch_filtered_count(
            3547638043, "status7__1", [3])),
        lambda: _safe("discrepancies", lambda: data_sources.fetch_filtered_count(
            3547638043, "status7__1", [4])),
        lambda: _safe("complaints", lambda: data_sources.fetch_filtered_count(
            1786542990, "color_mktyyf7w", [8])),
        lambda: _safe("chargebacks", lambda: data_sources.fetch_shopify_chargebacks()),
    ]
    if outlook_kpis:
        def _outlook():
            tok = data_sources.ms_token()
            return {mb: data_sources.fetch_all_folder_counts(mb, tok) for mb in mailboxes}
        tasks.append(lambda: _safe("outlook", _outlook))

    res = {}
    with _cf.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        for kind, val, err in ex.map(lambda t: t(), tasks):
            res[kind] = val
            if err:
                data[f"{kind}_error"] = err

    if group_map and res.get("groups"):
        for kid, info in res["groups"].items():
            if kid in by_id:
                by_id[kid]["count"], by_id[kid]["oldest_age_days"] = info["count"], info["age"]
        data["orders_live"] = True

    if res.get("booked"):
        bs = res["booked"]
        if "booked_overdue" in by_id:
            by_id["booked_overdue"]["count"] = bs["overdue"]["count"]
            by_id["booked_overdue"]["oldest_age_days"] = bs["overdue"]["age"]
            by_id["booked_overdue"]["source"] = "Monday · Orders board (live)"
        if "booked_future" in by_id:
            by_id["booked_future"]["count"], by_id["booked_future"]["oldest_age_days"] = \
                bs["future"]["count"], 0
            by_id["booked_future"]["source"] = "Monday · Orders board (live)"

    for kid in ("invoices", "discrepancies"):
        if res.get(kid) and kid in by_id:
            by_id[kid]["count"], by_id[kid]["oldest_age_days"] = res[kid]["count"], res[kid]["age"]
            by_id[kid]["source"] = "Monday · subitems (live)"

    if res.get("complaints") and "complaints" in by_id:
        by_id["complaints"]["count"] = res["complaints"]["count"]
        by_id["complaints"]["oldest_age_days"] = res["complaints"]["age"]
        by_id["complaints"]["source"] = "Monday · Customer Stage = Complaint (live)"

    if outlook_kpis and res.get("outlook") is not None:
        data["outlook_live"] = True
        for k in outlook_kpis:
            spec = k["outlook"]
            fmap = res["outlook"].get(spec["mailbox"], {})
            hit = data_sources.match_folder(fmap, spec["folder"])
            if hit:
                k["count"], k["oldest_age_days"], k["unread"] = hit["count"], 0, hit["unread"]
            else:
                k["folder_error"] = "folder not found"

    if res.get("chargebacks") and "chargebacks" in by_id:
        by_id["chargebacks"]["count"] = res["chargebacks"]["count"]
        by_id["chargebacks"]["oldest_age_days"] = res["chargebacks"]["age"]
        by_id["chargebacks"]["source"] = "Shopify · Live disputes"
        data["shopify_live"] = True
    return data


# Only the Daily Ops board + Summary use the live KPI fetch. Skip it on the other
# modules so Quotes / Pricing / Finance / Invoice Check / Activity don't wait on Monday.
_kpi_modules = ("Daily Ops",)
if st.session_state.get("module", "Daily Ops") in _kpi_modules:
    data = load_kpis()
else:
    data = {"kpis": [], "updated": "—", "_lazy": True}
KPIS = data.get("kpis", [])


# ---------------------------------------------------------------------------
# Pricing module — reads the compact pricing_summary.json produced by the
# daily supplier-pricing refresh (loss warnings, supplier margins, multi-supplier).
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_pricing():
    path = BASE / "pricing_summary.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=600)
def load_lookup():
    path = BASE / "pricing_lookup.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=300, show_spinner=False, max_entries=512)
def _live_price(sku):
    """Current Shopify price for a SKU. dict=sold, 'notsold'=confirmed not on
    Shopify, 'unavailable'=Shopify not configured / error (use daily fallback)."""
    try:
        res = data_sources.shopify_variant_price(sku)
        return res if res is not None else "notsold"
    except Exception:  # noqa: BLE001
        return "unavailable"


@st.cache_data(ttl=600)
def _search_payload():
    """Compact, interned lookup for the in-browser instant search widget."""
    lk = load_lookup()
    if not lk:
        return None
    sup_list, sup_idx, items = [], {}, []
    for it in lk["items"]:
        enc = []
        for o in sorted(it.get("offers", []), key=lambda o: o["c"]):
            s = o["s"]
            if s not in sup_idx:
                sup_idx[s] = len(sup_list)
                sup_list.append(s)
            enc.append([sup_idx[s], o["c"]])
        items.append([it["sku"], (it.get("name") or "")[:55],
                      it.get("sell"), it.get("margin"), enc])
    return json.dumps({"s": sup_list, "i": items}, separators=(",", ":")).replace("</", "<\\/")


_SEARCH_WIDGET = """
<style>
  *{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;}
  html,body{margin:0;padding:0;}
  #q{width:100%;padding:11px 14px;font-size:15px;border:1px solid #C3C9D4;border-radius:4px;outline:none;}
  #q:focus{border-color:#F26A21;box-shadow:0 0 0 2px rgba(242,106,33,.15);}
  #cnt{color:#6B7280;font-size:12px;margin:8px 2px;}
  .card{display:flex;gap:16px;align-items:flex-start;background:#fff;border:1px solid #E5E7EB;border-radius:4px;padding:12px 16px;margin-bottom:8px;}
  .L{flex:1;min-width:0;}.R{text-align:right;min-width:120px;}
  .sku{font-weight:700;color:#21242B;font-size:14px;}.nm{color:#6B7280;font-weight:400;font-size:13px;}
  table{margin-top:6px;border-collapse:collapse;font-size:13px;}td{padding:3px 10px 3px 0;}
  .big{font-size:28px;font-weight:500;line-height:1;}.mg{font-size:14px;font-weight:700;}
  .badge{display:inline-block;margin-top:6px;font-size:10px;font-weight:500;padding:3px 8px;border-radius:3px;}
  .sell{color:#15803d;background:#dcfce7;}.no{color:#dc2626;background:#fee2e2;}
  .save{font-size:12px;color:#374151;margin-top:4px;}
  mark{background:#ffe0c7;color:#b3460f;border-radius:3px;padding:0 1px;}
</style>
<input id="q" placeholder="Type a SKU or product name…" autocomplete="off">
<div id="cnt"></div><div id="out"></div>
<script>
const D=__DATA__, SUP=D.s, ITEMS=D.i;
const q=document.getElementById('q'),out=document.getElementById('out'),cnt=document.getElementById('cnt');
function esc(s){return (s==null?'':(''+s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function hl(t,ql){t=t==null?'':''+t;const i=t.toLowerCase().indexOf(ql);if(i<0)return esc(t);return esc(t.slice(0,i))+'<mark>'+esc(t.slice(i,i+ql.length))+'</mark>'+esc(t.slice(i+ql.length));}
function mcol(m){return (m==null||m<=0)?'#dc2626':(m<20?'#c9870a':'#15803d');}
function setH(h){try{var f=window.frameElement;if(f){f.style.height=h+'px';if(f.parentElement&&f.parentElement.style)f.parentElement.style.height=h+'px';}}catch(e){}}
function fit(){setH(document.documentElement.scrollHeight);}
function render(){
  const ql=q.value.trim().toLowerCase();
  if(!ql){out.innerHTML='';cnt.textContent='';setH(50);return;}
  const res=[];
  for(let k=0;k<ITEMS.length;k++){const it=ITEMS[k];if(it[0].toLowerCase().indexOf(ql)>=0||(it[1]||'').toLowerCase().indexOf(ql)>=0){res.push(it);if(res.length>=60)break;}}
  cnt.textContent=res.length?(res.length+(res.length>=60?'+':'')+' result'+(res.length===1?'':'s')):'No matches';
  out.innerHTML=res.map(it=>{
    const sku=it[0],name=it[1],sell=it[2],margin=it[3],offs=it[4];
    const matched=sell!=null&&sell>0;
    let sup='';for(let j=0;j<offs.length;j++){const ch=j===0&&offs.length>1;sup+='<tr><td>'+esc(SUP[offs[j][0]])+(ch?' <span style="color:#15803d;font-weight:700">cheapest</span>':'')+'</td><td style="text-align:right;font-weight:'+(j===0?700:400)+';color:'+(ch?'#15803d':'#21242B')+'">\\u00A3'+offs[j][1]+'</td></tr>';}
    let save='';if(offs.length>1){const s=Math.round((offs[offs.length-1][1]-offs[0][1])*100)/100;if(s>0)save='<div class="save">save <b style="color:#15803d">\\u00A3'+s+'/unit</b> via '+esc(SUP[offs[0][0]])+'</div>';}
    const price=matched?('<div class="big" style="color:#15803d">\\u00A3'+sell+'</div><div class="mg" style="color:'+mcol(margin)+'">'+margin+'% margin</div><span class="badge sell">WE SELL</span>'):('<div class="big" style="color:#dc2626;font-size:18px">NOT SOLD</div><span class="badge no">not on Shopify</span>');
    return '<div class="card"><div class="L"><div class="sku">'+hl(sku,ql)+' <span class="nm">'+hl(name,ql)+'</span></div><table>'+sup+'</table>'+save+'</div><div class="R">'+price+'</div></div>';
  }).join('');
  fit();
}
q.addEventListener('input',render);
window.addEventListener('resize',fit);
setTimeout(function(){q.focus();render();},150);
</script>
"""


def _hl(text, ql):
    """HTML-escape and wrap the matched substring in <mark>."""
    import html as _h
    t = "" if text is None else str(text)
    i = t.lower().find(ql)
    if i < 0:
        return _h.escape(t)
    return _h.escape(t[:i]) + "<mark style='background:#ffe0c7;color:#b3460f;border-radius:2px'>" \
        + _h.escape(t[i:i + len(ql)]) + "</mark>" + _h.escape(t[i + len(ql):])


# ---------------------------------------------------------------------------
# Monday boards + the people behind each account id. Shared by the live
# leaderboard and the Daily Activity page.
# ---------------------------------------------------------------------------
ORDERS_BOARD = 1786542990
SUBITEMS_BOARD = 3547638043
MONDAY_USERS = {  # Monday account id → dashboard username
    "39640612": "natasha", "25324062": "megan", "72043860": "melissa",
    "100183278": "malyeka", "25296593": "daniela",
}


# Work categories — group each person's changes so a long list reads at a glance.
ACTIVITY_CATS = [  # (name, emoji, column ids that belong to this category)
    ("Deliveries", "📦", {"color_mktyhmf3", "color_mm06fnhe", "date_mkny3amy"}),
    ("ETAs", "🔎", {"color_mm06spvx", "date_mkzd2jyv", "date", "date__1",
                    "date1__1", "date10__1"}),
    ("Invoices", "🧾", {"color_mktydktf", "numeric_mm3dc5fs", "numeric_mm3dn836",
                        "numeric_mm3d6jn5", "numeric_mm3d9t22", "numeric_mm3d31gp",
                        "text_mm22k2j7", "date6", "status7__1", "numbers4", "date_mm3d1ear"}),
    ("Customer care", "🤝", {"color_mktyyf7w", "status_1__1", "status_18", "color_mkpesmf3"}),
    ("Orders", "💬", {"color_mktyje8e", "color_mkzs8q63", "text_mkv6z0nt", "date1",
                      "hour_mkzvayd7"}),
]
_CAT_BY_COL = {c: name for name, _, cols in ACTIVITY_CATS for c in cols}
CAT_EMOJI = {name: emoji for name, emoji, _ in ACTIVITY_CATS}
CAT_EMOJI["Other"] = "✏️"
CAT_ORDER = [name for name, _, _ in ACTIVITY_CATS] + ["Other"]


def _activity_category(event: str, dd: dict) -> str:
    """Which work category a change belongs to."""
    if event == "move_pulse_from_group":
        dest = dd.get("dest_group")
        tl = ((dest.get("title") if isinstance(dest, dict) else "") or "").lower()
        if any(w in tl for w in ("aftersales", "refund", "return", "cancel", "chargeback")):
            return "Customer care"
        if any(w in tl for w in ("paid", "posted", "deliver")):
            return "Deliveries"
        return "Orders"
    if event in ("create_pulse", "delete_pulse"):
        return "Invoices" if (dd.get("board_id") == SUBITEMS_BOARD
                              or dd.get("is_subtasks_action")) else "Orders"
    return _CAT_BY_COL.get(dd.get("column_id"), "Other")


def _activity_change(event: str, dd: dict, group_names: dict):
    """(label, low_signal) for one Monday activity entry. low_signal flags noise
    (file upload, link edit, subitem auto-linking) so it can be filtered."""
    if event == "create_pulse":
        return "created", False
    if event == "delete_pulse":
        return "deleted", False
    if event == "move_pulse_from_group":
        dest = dd.get("dest_group")
        title = dest.get("title") if isinstance(dest, dict) else group_names.get(dest)
        title = (title or "another group").split(" (")[0].strip()  # drop long notes
        return f"moved → {title}", False
    ct = dd.get("column_title") or dd.get("column_id") or "a field"
    low = dd.get("column_type") in ("file", "link", "subtasks")
    val = dd.get("value")
    if isinstance(val, dict):
        if val.get("files"):
            return f"{ct} added", True
        if "linkedPulseIds" in val:
            return f"{ct} linked", True
        lv = val.get("label")
        if isinstance(lv, dict) and lv.get("text"):
            return f"{ct} → {lv['text']}", low
        if isinstance(lv, str) and lv:
            return f"{ct} → {lv}", low
        if val.get("date"):
            return f"{ct}: {val['date']}", low
        v = val.get("value")
        if isinstance(v, (int, float)):
            return f"{ct}: {v}", low
        if val.get("text"):
            return f"{ct}: {str(val['text'])[:40]}", low
    return ct, low


@st.cache_data(ttl=1800, show_spinner=False)
def daily_activity(day_iso: str, meaningful: bool = True):
    """Per-person 'who did what' on the given YYYY-MM-DD (UK day), across the
    Orders board and its subitems. Each person's items are grouped by work
    category. With meaningful=True, low-signal noise is filtered. Cached 30 min."""
    try:
        y, mo, d = (int(x) for x in day_iso.split("-"))
        start = datetime(y, mo, d, tzinfo=UK_TZ)
        f_iso = start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        t_iso = (start + timedelta(days=1)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        logs = []
        for bid, is_sub in ((ORDERS_BOARD, False), (SUBITEMS_BOARD, True)):
            for ev in data_sources.fetch_board_activity(bid, f_iso, t_iso):
                ev["_sub"] = is_sub
                logs.append(ev)
    except Exception as e:  # noqa: BLE001
        return {"people": [], "auto_changes": 0, "hidden": 0, "error": str(e)}

    group_names = {}  # dest_group already carries its title in the activity data
    cfg = config["credentials"]["usernames"]
    ids = {str(ev.get("user_id")) for ev in logs}
    unknown = [i for i in ids if i.isdigit() and i not in MONDAY_USERS]
    extra = data_sources.fetch_user_names(unknown) if unknown else {}

    def who(uid):
        uid = str(uid)
        un = MONDAY_USERS.get(uid)
        if un:
            return cfg.get(un, {}).get("name", un)
        return extra.get(uid)

    people: dict = {}
    auto = hidden = 0
    for ev in logs:
        nm = who(ev.get("user_id"))
        if not nm:  # automation / system actor
            auto += 1
            continue
        try:
            dd = json.loads(ev.get("data") or "{}")
        except Exception:  # noqa: BLE001
            continue
        change, low = _activity_change(ev.get("event"), dd, group_names)
        if meaningful and low:  # low-signal noise → skip
            hidden += 1
            continue
        pid = dd.get("pulse_id")
        pname = dd.get("pulse_name")
        if not pname and isinstance(dd.get("pulse"), dict):
            pname = dd["pulse"].get("name")  # move events carry the order no. here
        pname = str(pname or pid or "?")
        cat = _activity_category(ev.get("event"), dd)
        it = people.setdefault(nm, {}).setdefault(
            pid, {"name": pname, "sub": ev.get("_sub", False), "changes": [], "cats": set()})
        it["cats"].add(cat)
        if change not in it["changes"]:
            it["changes"].append(change)

    out = []
    for nm, items in people.items():
        ilist = list(items.values())
        # primary category = highest-priority category the item touched
        for it in ilist:
            it["cat"] = next((c for c in CAT_ORDER if c in it["cats"]), "Other")
        ilist.sort(key=lambda i: (CAT_ORDER.index(i["cat"]), i["sub"], i["name"]))
        cat_counts = {}
        for it in ilist:
            cat_counts[it["cat"]] = cat_counts.get(it["cat"], 0) + 1
        out.append({"name": nm, "n_items": len(ilist),
                    "n_changes": sum(len(i["changes"]) for i in ilist),
                    "cat_counts": cat_counts, "items": ilist})
    out.sort(key=lambda p: p["n_changes"], reverse=True)
    return {"people": out, "auto_changes": auto, "hidden": hidden, "error": None}


def render_daily_activity():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Daily Activity</span></span></div>""",
        unsafe_allow_html=True,
    )
    c_date, c_tog = st.columns([1, 1.4])
    with c_date:
        sel = st.date_input("Day", value=now_uk().date(), max_value=now_uk().date(),
                            format="DD/MM/YYYY")
    with c_tog:
        st.write("")
        meaningful = st.toggle("Meaningful changes only", value=True,
                               help="Hide file uploads, link edits and subitem auto-linking.")
    res = daily_activity(sel.isoformat(), meaningful)
    if res.get("error"):
        st.warning("Couldn't read Monday activity: " + str(res["error"])[:200])
        return
    people = res["people"]
    label = "today" if sel == now_uk().date() else sel.strftime("%d %b %Y")
    if not people:
        st.info(f"No team activity recorded {label}.")
        return

    total_items = sum(p["n_items"] for p in people)
    total_changes = sum(p["n_changes"] for p in people)
    st.caption(f"{len(people)} people active {label} · {total_items} items touched "
               f"· {total_changes} changes")

    # --- Per-person daily totals (summary) ---
    trows = "".join(
        f'<tr style="border-top:1px solid var(--line)">'
        f'<td style="padding:6px 12px"><b>{p["name"]}</b></td>'
        f'<td style="padding:6px 12px;text-align:right">{p["n_items"]}</td>'
        f'<td style="padding:6px 12px;text-align:right">{p["n_changes"]}</td></tr>'
        for p in people)
    st.markdown(
        '<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:6px">'
        '<tr style="text-align:left;color:var(--muted)">'
        '<th style="padding:6px 12px">Person</th>'
        '<th style="padding:6px 12px;text-align:right">Items</th>'
        '<th style="padding:6px 12px;text-align:right">Changes</th></tr>'
        f'{trows}</table>',
        unsafe_allow_html=True,
    )

    # --- CSV export of the full detail ---
    csv_lines = ["Date,Person,Item,Type,Category,Changes"]
    for p in people:
        for it in p["items"]:
            ch = " | ".join(it["changes"]).replace('"', "'")
            csv_lines.append(f'{sel.isoformat()},"{p["name"]}","{it["name"]}",'
                             f'{"subitem" if it["sub"] else "order"},{it["cat"]},"{ch}"')
    st.download_button("⬇ Download CSV", "\n".join(csv_lines),
                       file_name=f"daily-activity-{sel.isoformat()}.csv", mime="text/csv")
    st.write("")
    # Collapsible category sections (native <details>; Streamlit forbids nested expanders).
    st.markdown(
        "<style>details.cat>summary{list-style:none;outline:none}"
        "details.cat>summary::-webkit-details-marker{display:none}"
        'details.cat>summary::before{content:"▸";color:#94a3b8;display:inline-block;'
        "width:1em;transition:transform .15s}"
        "details.cat[open]>summary::before{transform:rotate(90deg)}</style>",
        unsafe_allow_html=True,
    )
    PER_CAT = 60  # rows shown per category (each section is collapsible)
    for idx, p in enumerate(people):
        with st.expander(f'{p["name"]} — {p["n_items"]} items · {p["n_changes"]} changes',
                         expanded=(idx == 0)):
            blocks = []
            for c in CAT_ORDER:
                cat_items = [it for it in p["items"] if it["cat"] == c]
                if not cat_items:
                    continue
                rows = []
                for it in cat_items[:PER_CAT]:
                    tag = ('<span style="background:#eef2f7;color:#64748b;border-radius:3px;'
                           'padding:0 5px;font-size:10px;margin-left:5px">subitem</span>'
                           if it["sub"] else "")
                    label_i = ("Inv " if it["sub"] else "#") + it["name"]
                    rows.append(
                        f'<tr style="border-top:1px solid var(--line)">'
                        f'<td style="padding:5px 10px;white-space:nowrap;vertical-align:top;'
                        f'width:1%"><b>{label_i}</b>{tag}</td>'
                        f'<td style="padding:5px 10px;color:#334155">'
                        f'{"; ".join(it["changes"])}</td></tr>')
                extra = len(cat_items) - PER_CAT
                more = (f'<tr><td colspan="2" style="padding:5px 10px;color:var(--muted)">'
                        f'+{extra} more…</td></tr>' if extra > 0 else "")
                blocks.append(
                    f'<details class="cat" style="border-top:1px solid var(--line)">'
                    f'<summary style="cursor:pointer;font-weight:700;color:#0f172a;padding:8px 2px">'
                    f' {CAT_EMOJI.get(c, "")} {c} '
                    f'<span style="color:var(--muted);font-weight:400">({len(cat_items)})</span>'
                    f'</summary>'
                    f'<table style="width:100%;border-collapse:collapse;font-size:12.5px;'
                    f'margin:0 0 10px">' + "".join(rows) + more + "</table></details>")
            st.markdown("".join(blocks), unsafe_allow_html=True)
    notes = []
    if res.get("hidden"):
        notes.append(f'{res["hidden"]} low-signal changes hidden (file uploads, links)')
    if res.get("auto_changes"):
        notes.append(f'{res["auto_changes"]} automated / system changes')
    if notes:
        st.caption("Not shown: " + " · ".join(notes) + ".")


def render_product_search():
    """Instant, as-you-type product search (in-browser iframe): substring match
    on SKU/name with the typed text highlighted, every supplier (cheapest
    flagged), the sell price / margin and whether we sell it. The widget
    auto-resizes — 50px when empty, growing only while showing results."""
    st.markdown("#### Find a product, its cheapest supplier &amp; price")
    payload = _search_payload()
    if not payload:
        st.info("Product lookup data not loaded yet.")
        return
    components.html(_SEARCH_WIDGET.replace("__DATA__", payload), height=50, scrolling=False)


def _mcol(m) -> str:
    if m is None or m <= 0:
        return "#dc2626"   # loss
    if m < 20:
        return "#c9870a"   # below target
    return "#15803d"       # healthy


def _ptable(header_cells: str, body_rows: str, note: str = "") -> str:
    return (f'<div class="ts-card ts-tbl"><table style="width:100%;border-collapse:collapse">'
            f'<tr style="text-align:left;color:var(--muted);font-size:11px">{header_cells}</tr>'
            f'{body_rows}</table>{note}</div>')


# 'Buy from (cheapest)' = the supplier we ORDER from at the lowest cost. 'Sold as (Shopify
# vendor)' = the brand the product is LISTED UNDER on our own website. They are not always
# the same, so both are shown to avoid confusing who we buy from with who we sell it as.
_SKU_HEAD = ('<th style="padding:7px 12px">SKU / product</th>'
             '<th style="padding:7px 12px">Buy from (cheapest supplier)</th>'
             '<th style="padding:7px 12px">Sold as (Shopify vendor)</th>'
             '<th style="padding:7px 12px;text-align:right">Cost</th>'
             '<th style="padding:7px 12px;text-align:right">Sell</th>'
             '<th style="padding:7px 12px;text-align:right">Margin</th>')


def _sku_rows(items, supplier=None):
    out = []
    for it in items:
        if supplier:
            cost = next((o["c"] for o in it.get("offers", []) if o["s"] == supplier), None)
            sup = supplier
        else:
            cost = it.get("cheapest_cost")
            sup = it.get("cheapest")
        vendor = it.get("vendor")           # who we SELL it as (Shopify vendor)
        sell, m, nm = it.get("sell"), it.get("margin"), (it.get("name") or "")[:55]
        out.append(
            f'<tr style="border-top:1px solid var(--line)">'
            f'<td style="padding:7px 12px"><b>{it["sku"]}</b>'
            f'<div style="color:var(--muted);font-size:11px">{nm}</div></td>'
            f'<td style="padding:7px 12px;font-size:12px">{sup or "—"}</td>'
            f'<td style="padding:7px 12px;font-size:12px">{vendor or "—"}</td>'
            f'<td style="padding:7px 12px;text-align:right">{"£"+format(cost, ".2f") if cost is not None else "—"}</td>'
            f'<td style="padding:7px 12px;text-align:right">{"£"+format(sell, ".2f") if sell else "—"}</td>'
            f'<td style="padding:7px 12px;text-align:right;font-weight:700;color:{_mcol(m)}">'
            f'{format(m, ".1f")+"%" if m is not None else "—"}</td></tr>')
    return "".join(out)


def _find_product(items, q):
    """Best lookup match for a typed SKU or product name."""
    q = (q or "").strip().lower()
    if not q:
        return None
    for it in items:                                    # exact SKU first
        if (it.get("sku") or "").lower() == q:
            return it
    for it in items:                                    # substring on SKU or title
        if q in (it.get("sku") or "").lower() or q in (it.get("name") or "").lower():
            return it
    return None


@st.cache_data(ttl=21600, show_spinner=False, max_entries=128)
def competitor_research(sku, title, code, vendor, your_price):
    """Cached AI competitor lookup (6 h) keyed on the product, to avoid re-billing."""
    try:
        return data_sources.research_competitors(title, code, vendor, your_price)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _render_competitor_check(items):
    with st.expander("🔍 Competitor price check (beta)"):
        st.caption("Pull a product's code and see what other UK retailers charge for the "
                   "same item — all prices shown **ex-VAT** to match your costs. Uses live web "
                   "search (needs your Anthropic key); a few pence per check, results cached.")
        q = st.text_input("Product SKU or name", key="comp_q",
                          placeholder="e.g. FRO607AG  or  anthracite gutter")
        if not (st.button("Check competitors", key="comp_go", type="primary") and q.strip()):
            return
        prod = _find_product(items, q)
        if not prod:
            st.warning("No matching product found in the pricing data.")
            return
        sku, sell = prod.get("sku"), prod.get("sell")
        title = prod.get("name") or sku
        head = f"**{title}**  ·  SKU `{sku}`"
        if sell is not None:
            head += f"  ·  you sell at **£{sell:,.2f} ex VAT**"
        st.markdown(head)

        with st.spinner("Searching competitor sites…"):
            res = competitor_research(sku, title, sku, prod.get("vendor"), sell)
        if res.get("error"):
            if "ANTHROPIC_API_KEY" in res["error"]:
                st.info("Add your **ANTHROPIC_API_KEY** in Settings → Secrets to enable "
                        "competitor search.")
            else:
                st.error("Couldn't run competitor search: " + res["error"][:200])
            return
        comps = [c for c in (res.get("competitors") or []) if c.get("retailer")]
        if not comps:
            st.warning("No competitor listings found for this exact product. "
                       + (res.get("summary") or ""))
            return

        prices = [c["price"] for c in comps if isinstance(c.get("price"), (int, float))]
        cheapest = min(prices) if prices else None
        rows = ""
        if sell is not None:
            rows += ('<tr style="background:#fff7f2"><td style="padding:7px 12px">'
                     '<b>Trade Superstore (you)</b></td>'
                     f'<td style="padding:7px 12px;text-align:right"><b>£{sell:,.2f}</b></td></tr>')
        for c in sorted(comps, key=lambda c: c["price"] if isinstance(c.get("price"),
                                                                      (int, float)) else 9e9):
            pr = c.get("price")
            prs = f"£{pr:,.2f}" if isinstance(pr, (int, float)) else "—"
            oos = "" if c.get("in_stock", True) else (' <span style="color:#ef4444;'
                                                      'font-size:11px">out of stock</span>')
            conv = (' <span style="color:#94a3b8;font-size:10px" title="site showed inc-VAT; '
                    'converted to ex-VAT">↓ from inc-VAT</span>' if c.get("listed_inc_vat") else "")
            name = c.get("retailer") or "Unknown"
            url = c.get("url") or ""
            cell = f'<a href="{url}" target="_blank">{name}</a>' if url else name
            rows += (f'<tr style="border-top:1px solid var(--line)">'
                     f'<td style="padding:7px 12px">{cell}{oos}</td>'
                     f'<td style="padding:7px 12px;text-align:right">{prs}{conv}</td></tr>')
        st.markdown('<table style="width:100%;border-collapse:collapse;font-size:13px">'
                    '<tr style="text-align:left;color:var(--muted)">'
                    '<th style="padding:7px 12px">Retailer</th>'
                    '<th style="padding:7px 12px;text-align:right">Price (ex VAT)</th></tr>'
                    + rows + "</table>", unsafe_allow_html=True)

        if sell is not None and cheapest is not None:
            if sell <= cheapest:
                st.success(f"You're the cheapest — £{sell:,.2f} vs cheapest competitor "
                           f"£{cheapest:,.2f}. Possible headroom to raise the price.")
            else:
                st.warning(f"A competitor is cheaper by £{sell - cheapest:,.2f} "
                           f"(you £{sell:,.2f} vs £{cheapest:,.2f}).")
        if res.get("summary"):
            st.caption(res["summary"])


def _norm_code(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _norm_inv_no(inv, supplier=None):
    """Normalise an invoice number for statement <-> QuickBooks/Monday matching. PJH statements
    print a leading 'I' (e.g. I11656210) that our records almost always omit (11656210) — strip a
    leading 'i' for PJH so both sides match whichever way round it was entered."""
    s = _norm_code(inv)
    if s and s[0] == "i" and supplier and _norm_code(supplier).startswith("pjh"):
        s = s[1:]
    return s


def _parse_order_items(text):
    """Order line text → {key: {sku, qty, name}}. Keyed by normalised SKU when the line has
    one, else a synthetic key so a product that's on the order but has NO SKU set is still a
    candidate (matched by name). The product name (text before 'Quantity:'/'SKU:') lets us
    match a line even when the supplier's invoice SKU differs from ours."""
    out = {}
    for i, line in enumerate((text or "").split("\n")):
        skum = re.search(r"SKU:\s*([^\s|]+)", line)
        qtym = re.search(r"Quantity:\s*(\d+)", line)
        if not skum and not qtym:
            continue  # header / blank / non-product line
        # Product name = text before the 'Quantity:'/'SKU:' tokens (whichever comes first).
        name = re.split(r"\|?\s*(?:Quantity:|SKU:)", line)[0].strip(" |-\t")
        if not skum and not name:
            continue
        key = _norm_code(skum.group(1)) if skum else f"line{i}:{_norm_code(name)}"
        out[key] = {"sku": skum.group(1) if skum else (name or "(no SKU)"),
                    "qty": int(qtym.group(1)) if qtym else None,
                    "name": name}
    return out


# Supplier shorthand → full word, so an abbreviated invoice line ('Ali Ext Corner')
# matches the spelled-out pricelist title ('External Aluminium Corner'). Deterministic;
# extend as new shorthand turns up.
# Supplier shorthand → full word(s). Multi-word expansions (e.g. hplank → 'hardie plank')
# split into separate tokens, and 'hardieplank' is normalised the same way so the joined
# and spaced forms line up. Extend as new shorthand turns up.
_TOK_ABBREV = {
    "ali": "aluminium", "alu": "aluminium", "alum": "aluminium",
    "ext": "external", "int": "internal",
    "hplank": "hardie plank", "hplk": "hardie plank", "hardieplank": "hardie plank",
    "hardieseal": "hardie seal",
    "galvan": "galvanised", "galv": "galvanised",
    "conn": "connector", "vert": "vertical", "horiz": "horizontal",
    "vent": "ventilation", "qty": "", "pk": "pack",
}
# Noise words to ignore (so 'WINDOW AND VERTICAL' doesn't carry the filler 'and').
_TOK_STOP = {"and", "the", "for", "with", "mm", "cm", "to", "of", "in", "on", "at", "by", "or"}


def _title_tokens(s):
    # Split letter↔digit boundaries so '3600mm' matches '3600'. Expand supplier shorthand,
    # drop noise words, and keep 2+ char tokens (so short but meaningful codes like 'VL'
    # survive). Dimensions (25, 38, 180, 3600) are strong signals and are kept.
    s = (s or "").lower()
    s = re.sub(r"(?<=\d)(?=[a-z])", " ", s)
    s = re.sub(r"(?<=[a-z])(?=\d)", " ", s)
    out = set()
    for w in re.findall(r"[a-z0-9]+", s):
        for part in _TOK_ABBREV.get(w, w).split():
            # Keep single DIGITS — on painting/cladding orders the size is often the only
            # difference between two otherwise identical products ('4" roller' vs '9"
            # roller'), and dropping it made them impossible to tell apart. Single letters
            # are still dropped as noise.
            if part in _TOK_STOP or (len(part) < 2 and not part.isdigit()):
                continue
            out.add(part)
    return out


@st.cache_data(ttl=900, show_spinner=False, max_entries=256)
def _shopify_order_lines(order_id):
    """Live Shopify order line items (cached). None if orders aren't readable."""
    try:
        return data_sources.fetch_order_line_items(order_id)
    except Exception:  # noqa: BLE001 — fall back to Monday's copy of the order
        return None


@st.cache_data(ttl=900, show_spinner=False, max_entries=256)
def _shopify_order_ship(order_id):
    """Live Shopify delivery postcode + country (cached), for Carron zone delivery. None
    if unreadable."""
    try:
        return data_sources.fetch_order_shipping(order_id)
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=900, show_spinner=False, max_entries=256)
def _shopify_fulfillment_split(order_id):
    """{norm_sku: fulfilment location name} for split (multi-supplier drop-ship) orders.
    Empty if the order isn't split or fulfilment orders aren't readable."""
    try:
        raw = data_sources.fetch_order_fulfillment_split(order_id)
        return {_norm_code(k): v for k, v in (raw or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def _loc_matches_supplier(loc, supplier):
    """Whether a Shopify fulfilment location name refers to this supplier (e.g. location
    'Eurocell' ↔ supplier 'eurocell'). Substring both ways to tolerate 'Eurocell Dropship'."""
    s = _norm_code(loc)
    return bool(supplier) and bool(s) and (supplier in s or s in supplier)


def _order_candidates(meta):
    """The order lines to check the invoice against. Prefers the LIVE Shopify order (the
    source of truth — Monday's cached order list can be stale or miss lines), and falls
    back to Monday's order_items text if Shopify can't be read."""
    sid = meta.get("shopify_order_id")
    if sid:
        lines = _shopify_order_lines(sid)
        if lines:
            out = {}
            for i, l in enumerate(lines):
                sku = l.get("sku")
                key = _norm_code(sku) if sku else f"shop{i}:{_norm_code(l.get('title'))}"
                # The SAME SKU can appear on several order lines — Shopify variants that
                # share a SKU (e.g. the 1L and 2.5L pots of one paint). Keyed on SKU alone
                # the later line OVERWRITES the earlier one and it vanishes from the order,
                # so its invoice line could never match ('not on the order'). Suffix
                # duplicates to keep every line; the NAME (variant is folded in) then decides
                # which is which.
                if key in out:
                    key = f"{key}#{i}"
                out[key] = {"sku": sku or (l.get("title") or "(no SKU)"),
                            "qty": l.get("qty"), "name": l.get("title"),
                            "price": l.get("price")}   # our ex-VAT line price (for Decor8)
            if out:
                return out
    return _parse_order_items(meta.get("order_items"))


def _code_match(sk, order, used):
    """Match a supplier's numeric manufacturer code to an order line whose SKU EMBEDS it
    — e.g. UPB invoice '5420121' → our SKU 'JHHPK5420121'. Deterministic (the full code
    must appear as a substring), not fuzzy. Only fires for 6+ digit codes."""
    if not (sk and sk.isdigit() and len(sk) >= 6):
        return None
    for k in order:
        if k not in used and sk in k:
            return k
    return None


# Known product equivalences — force-match a supplier's invoice line to our order line when
# they can't be linked automatically: the supplier uses a different NAME *and* a different
# CODE (so name matching finds only the colour in common, and SKU matching finds nothing).
# Each rule matches the INVOICE line (by SKU and/or name fragments) and the ORDER line (by
# our SKU and/or name fragments — needed when the order line has no SKU). Add one whenever a
# genuine rename turns up. Checked BEFORE SKU and name matching. All fragments are ANDed.
PRODUCT_EQUIV = [
    # Eurocell '40MM PANEL JOINT IRISH OAK' (PJ40WLO1) = our 'Hollow Soffit H-Trim' (GHSIO)
    {"inv_sku": "PJ40WLO1", "order_sku": "GHSIO"},
    # UPB 'Hardiepanel Screws (Timber)' (5300303) = our 'James Hardie VL ... Fixing Screws'
    # (the order line carries no SKU, so target it by name).
    {"supplier": "upb", "inv_sku": "5300303", "order_name_has": ["fixing", "screws"]},
]


def _sku_keys(sk, order):
    """Order keys an invoice SKU could refer to — the plain key plus any '#n' duplicates
    (the same SKU on several order lines, e.g. 1L and 2.5L variants sharing a SKU)."""
    if not sk:
        return []
    pre = sk + "#"
    return [k for k in order if k == sk or k.startswith(pre)]


def _equiv_match(supplier, sk, desc, order, hit):
    """Order key an invoice line is a KNOWN equivalent of (deterministic supplier-rename
    table, PRODUCT_EQUIV), or None. Works even when the order line has no SKU (targets it by
    name). Skips an order line that's already been matched."""
    dl = (desc or "").lower()
    for r in PRODUCT_EQUIV:
        if r.get("supplier") and r["supplier"] != supplier:
            continue
        if not (r.get("inv_sku") or r.get("inv_name_has")):
            continue
        if r.get("inv_sku") and _norm_code(r["inv_sku"]) != sk:
            continue
        if r.get("inv_name_has") and not all(w.lower() in dl for w in r["inv_name_has"]):
            continue
        # invoice side matched → find the order line
        if r.get("order_sku"):
            for k in _sku_keys(_norm_code(r["order_sku"]), order):
                if k not in hit:
                    return k
        for frags in ([r["order_name_has"]] if r.get("order_name_has") else []):
            for k, v in order.items():
                if k in hit:
                    continue
                nm = (v.get("name") or "").lower()
                if all(w.lower() in nm for w in frags):
                    return k
    return None


def _order_common_tokens(order):
    """Tokens shared across MOST order lines — typically the colour (e.g. 'Sail Cloth'),
    identical on every line and so useless for telling one product from another. We ignore
    these when name-matching, so a screw doesn't match a board just because both are that
    colour. Applied for orders of 2+ lines."""
    from collections import Counter
    if len(order) < 2:
        return set()
    c = Counter()
    for v in order.values():
        c.update(_title_tokens(v.get("name")))
    thresh = max(2, (len(order) + 1) // 2)   # appears in roughly half the lines or more
    return {t for t, cnt in c.items() if cnt >= thresh}


def _names_ok(desc, order_name, common):
    """A code match must still make name sense: the invoice line and the order line it matched
    (by an embedded code) must share at least one DISTINCTIVE word (not just the brand/colour).
    Stops e.g. a 'Hardieplank' board matching a 'Paint' line that only shares a colour code."""
    shared = _title_tokens(desc) & _title_tokens(order_name)
    return bool(shared - common)


def _name_pair_score(dt, ot, common):
    """Score an invoice-line vs order-line NAME match on its DISTINCTIVE shared words
    (colour / order-wide common words removed), weighted by word length so a specific word
    like 'ventilation' outweighs a generic one like 'profile'. Normally needs 2+ distinctive
    shared words AND ≥40% overlap of the shorter side; a single genuinely specific word
    (8+ chars, e.g. 'guillotine') is allowed for one-word products. 0 if not credible."""
    if not dt or not ot:
        return 0.0
    shared = dt & ot
    if not shared:
        return 0.0
    distinctive = shared - common
    # How alike are the two names overall (1.0 = identical token sets)?
    overlap = len(shared) / max(len(dt), len(ot))
    # NEAR-IDENTICAL NAMES ALWAYS MATCH. On an order of near-identical products (e.g. four
    # Hamilton rollers/frames) almost every word is 'common' across the order, which used to
    # leave nothing distinctive and scored even a character-for-character identical
    # description as 0 ('not on the order'). When the two names are >=80% the same tokens,
    # skip the distinctive-word requirement — the colour-collision risk it guards against
    # can't apply to names this alike.
    if overlap < 0.8:
        if len(distinctive) < 2 and not (len(distinctive) == 1
                                         and len(next(iter(distinctive))) >= 8):
            return 0.0
        if len(shared) / min(len(dt), len(ot)) < 0.4:
            return 0.0
    # Length-weighted distinctive words, plus an exactness bonus so the CLOSEST name wins
    # (an exact '4"' line beats the otherwise identical '9"' line).
    return float(sum(len(t) for t in distinctive)) + 12.0 * overlap


@st.cache_data(ttl=600, show_spinner=False)
def _supplier_title_index():
    """{norm_supplier: [(title_tokens, title, cost)]} from the feed's per-supplier
    product titles — for price-checking a supplier's invoice by the product TITLE it
    prints when its SKU codes differ from ours (e.g. UPB)."""
    lk = load_lookup()
    st_map = (lk or {}).get("supplier_titles") or {}
    out = {}
    for sup, pairs in st_map.items():
        lst = []
        for t, c in pairs:
            toks = _title_tokens(t)
            if toks and c is not None:
                lst.append((toks, t, c))
        if lst:
            out[_norm_code(sup)] = lst
    return out


def _supplier_title_cost(desc, supplier, tidx):
    """Cost of the line in `supplier`'s OWN pricelist whose product title best matches
    the invoice description. Scoped to that one supplier's catalogue (small, their own
    consistent naming) — not a cross-catalogue guess. Returns (cost, matched title)."""
    cands = tidx.get(supplier)
    if not cands:
        return None, None
    dt = _title_tokens(desc)
    if not dt:
        return None, None
    best, best_score, best_title = None, 0.0, None
    for toks, title, cost in cands:
        shared = dt & toks
        n = len(shared)
        if n == 0:
            continue
        mn = min(len(dt), len(toks))
        # Normally require 2+ shared words. Exception: a single distinctive (8+ char) word
        # that IS the whole shorter title — for one-word supplier products like 'Guillotine',
        # which can never reach two shared words.
        if n < 2 and not (mn == 1 and len(next(iter(shared))) >= 8):
            continue
        ratio = n / mn
        if ratio >= 0.5 and (n + ratio) > best_score:
            best, best_score, best_title = cost, n + ratio, title
    return best, best_title


@st.cache_data(ttl=3600, show_spinner=False)
def _pricelist_index():
    """{norm_sku: {norm_supplier: cost}} from the pricing lookup offers."""
    lk = load_lookup()
    idx = {}
    for it in (lk["items"] if lk else []):
        sk = _norm_code(it.get("sku"))
        if not sk:
            continue
        for o in (it.get("offers") or []):
            sup = _norm_code(o.get("s"))
            if sup and o.get("c") is not None:
                idx.setdefault(sk, {})[sup] = o.get("c")
    return idx


def _is_code(tok):
    """A token that looks like a product code (so it won't false-match plain words or
    bare pack sizes): letter+digit mix of 3+ chars (VL7, HP3600) or a 5+ digit number
    (5300436)."""
    has_d = any(c.isdigit() for c in tok)
    has_a = any(c.isalpha() for c in tok)
    return (len(tok) >= 3 and has_d and has_a) or (len(tok) >= 5 and tok.isdigit())


@st.cache_data(ttl=3600, show_spinner=False)
def _supplier_code_index():
    """{norm_supplier: {code_sku: cost}} of each supplier's code-like pricelist SKUs.
    Lets us price a line when the supplier prints its OWN code (e.g. UPB's VL7) in the
    invoice description rather than the SKU field — their codes differ from ours."""
    out = {}
    for sku, supmap in _pricelist_index().items():
        if not _is_code(sku):
            continue
        for sup, cost in supmap.items():
            if cost is not None:
                out.setdefault(sup, {})[sku] = cost
    return out


def _supplier_code_cost(sku_raw, desc, supplier, cidx):
    """If one of `supplier`'s own pricelist codes appears as a whole token anywhere in
    the invoice line (SKU or description), return (cost, matched code). Strict equality
    on the code token — no fuzzy guessing. Else (None, None)."""
    codes = cidx.get(supplier)
    if not codes:
        return None, None
    toks = {t for t in re.findall(r"[a-z0-9]+", f"{sku_raw} {desc}".lower()) if _is_code(t)}
    for t in toks:
        if t in codes:
            return codes[t], t.upper()
    return None, None


INVOICE_STATUS = {            # key → (Monday status7__1 label ids, fetch limit)
    "review": ([3], 1500),          # Needs Review — pull them ALL (paginated)
    "matched": ([9], 500),          # Matched (TradeHub) — checked, held (NOT pushed)
    "pushed": ([0, 1, 2, 8], 500),  # Approved (To QB)/CN Approved (To QB)/etc → pushed to QB
    "discrepancy": ([4], 500),
    # Cross-cutting "what's happened lately" view: every actioned status, newest first.
    "recent": ([0, 1, 2, 8, 9, 4], 800),
}
MATCHED_LABEL = "Matched (TradeHub)"
APPROVED_QB_LABEL = "Approved (To QB)"
CN_APPROVED_QB_LABEL = "CN Approved (To QB)"
DISCREPANCY_LABEL = "Discrepancy"
MARGIN_PUSH_MIN = 10.0          # default lowest margin to auto-approve (Decor8 overridden to 5%
MARGIN_PUSH_MAX = 35.0          # in SUPPLIER_RULES) — editable in the Invoice Check settings box


def _thresholds():
    return (float(st.session_state.get("inv_margin_min", MARGIN_PUSH_MIN)),
            float(st.session_state.get("inv_margin_max", MARGIN_PUSH_MAX)))


def _recent_result(status_text):
    """Short, readable label for the Recent-activity 'Result' column, from the
    Monday Payment Status."""
    s = (status_text or "").lower()
    if "cn approved" in s:
        return "✅ CN pushed to QB"
    if "approved" in s:
        return "✅ Pushed to QB"
    if "matched" in s:
        return "🟡 Held (matched)"
    if "discrepancy" in s:
        return "🔴 Discrepancy"
    return status_text or "—"


def _fmt_actioned(iso):
    """Monday status-change timestamp (UTC ISO) → 'DD Mon HH:MM' in UK local time, for the
    Recent-activity 'When' column."""
    if not iso:
        return ""
    try:
        return (datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
                .astimezone(UK_TZ).strftime("%d %b %H:%M"))
    except Exception:  # noqa: BLE001
        return str(iso)[:16].replace("T", " ")


def _push_decision(matched, is_cn, live_margin, supplier=None, has_discount=False):
    """(label, action) for a checked invoice. action: 'push' | 'hold' | 'flag' | None.
    Supplier rules can override the push floor (a lower floor when the customer used a discount
    code), the high-margin flag, and whether a below-floor margin is held or flagged for review."""
    lo, hi = _thresholds()
    rule = SUPPLIER_RULES.get(_norm_code(supplier), {}) if supplier else {}
    lo = rule.get("push_min", lo)
    if has_discount and rule.get("push_min_discount") is not None:
        lo = rule["push_min_discount"]       # customer used a discount code → lower floor allowed
    flag_high = rule.get("flag_high", True)
    if not matched:
        return None, None
    if live_margin is None or live_margin < lo:
        # Below the floor: most suppliers hold as Matched for review; some (Toolbank) want it
        # left in Needs Review as a discrepancy to check rather than silently held.
        if rule.get("flag_below"):
            return DISCREPANCY_LABEL, "flag"
        return MATCHED_LABEL, "hold"
    if flag_high and live_margin > hi:
        return DISCREPANCY_LABEL, "flag"      # suspiciously high → flag for review
    return (CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL), "push"


# Suppliers to skip in the invoice checker entirely (substrings of the normalised supplier
# name). MB Decor is paid in advance, so nothing needs checking — remove from here to switch
# it back on.
EXCLUDED_SUPPLIER_KEYS = ("mbdecor",)


def _is_excluded_supplier(supplier):
    s = _norm_code(supplier)
    return any(x in s for x in EXCLUDED_SUPPLIER_KEYS)


@st.cache_data(ttl=600, show_spinner=False)
def invoices_by_status(key):
    label_ids, lim = INVOICE_STATUS[key]
    try:
        data = data_sources.fetch_invoices_by_status(label_ids, limit=lim)
        data["invoices"] = [i for i in (data.get("invoices") or [])
                            if not _is_excluded_supplier(i.get("supplier"))]
        return data
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@st.cache_data(ttl=600, show_spinner=False)
def invoice_count(key):
    label_ids, _lim = INVOICE_STATUS[key]
    try:
        return data_sources.fetch_invoice_count(label_ids)
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=900, show_spinner=False, max_entries=128)
def _order_discounts(order_ids):
    """{shopify_order_id: {amount, codes}} — customer discounts. {} if unavailable."""
    if not order_ids:
        return {}
    try:
        return data_sources.fetch_order_discounts(list(order_ids))
    except Exception:  # noqa: BLE001 — Shopify orders not readable → no discount column
        return {}


@st.cache_data(ttl=86400, show_spinner=False, max_entries=48)
def _read_invoice(asset_id, sub_id, nonce=0):
    """Read + cache one invoice's parsed PDF (keyed per asset/sub; nonce busts the
    cache to force a fresh re-read)."""
    try:
        url = data_sources.monday_asset_url(asset_id)
        if not url:
            return {"error": "Couldn't get a download link for the PDF."}
        return data_sources.read_invoice_pdf(url)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@st.cache_data(ttl=3600, show_spinner=False)
def _lookup_by_sku():
    """{norm_sku: {sell, cost, name}} from the pricing lookup (your ex-VAT sell
    price + cheapest supplier cost)."""
    lk = load_lookup()
    idx = {}
    for it in (lk["items"] if lk else []):
        sk = _norm_code(it.get("sku"))
        if sk:
            idx[sk] = {"sell": it.get("sell"), "cost": it.get("cheapest_cost"),
                       "name": it.get("name")}
    return idx


def _order_margin(order_items_text, lbsku, cost_override=None):
    """Margin we make on the order's items: revenue (our ex-VAT sell) vs cost.
    cost_override = {norm_sku: actual invoice unit cost}; otherwise falls back to
    the cheapest pricelist cost. Returns {margin, rev, cost, matched, total} or None."""
    order = _parse_order_items(order_items_text)
    rev = cost = 0.0
    matched = 0
    for sk, info in order.items():
        rec = lbsku.get(sk)
        if not rec or rec.get("sell") is None:
            continue
        qty = info["qty"] or 1
        c = (cost_override or {}).get(sk)
        if c is None:
            c = rec.get("cost")
        if c is None:
            continue
        rev += rec["sell"] * qty
        cost += c * qty
        matched += 1
    if rev <= 0:
        return None
    return {"margin": (rev - cost) / rev * 100, "rev": rev, "cost": cost,
            "matched": matched, "total": len(order)}


# Per-supplier delivery / carriage charges (ex-VAT £) so legitimate delivery lines
# aren't flagged. Each rule: {name, flat, free_over?}. free_over = free above that
# goods value. Keys are normalised supplier names.
DELIVERY_CHARGES = {
    "molan": {"name": "Molan", "flat": 23.74},
    "pjh": {"name": "PJH", "flat": 37.50, "free_over": 1000.0},   # from 1 Jul 2026
    "travisperkins": {"name": "Travis Perkins", "flat": 25.0, "free_over": 100.0},
    "nbp": {"name": "NBP", "flat": 17.0, "free_over": 250.0},
    "upb": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
    "up": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
    "eurocell": {"name": "Eurocell", "flat": 12.50, "free_over": 100.0},
    "gap": {"name": "GAP", "flat": 20.83, "free_over": 150.0},   # <£150 net → £20.83 + VAT
    "deanta": {"name": "Deanta", "flat": 8.0},                   # £8 carriage (confirmed)
    "decor8": {"name": "Decor8", "flat": 5.99, "free_over": 50.0},
    # Chase Hardware: £5 under 2kg, £10 above — but we don't hold weights yet, so accept either
    # (flat £10 ceiling = anything up to £10 passes; only >£10 flags). Tighten once we have weights.
    "chasehardware": {"name": "Chase Hardware", "flat": 10.0},
    # JB Kind delivery is by NUMBER OF DOORS, not goods value — handled separately below.
}

# --- JB Kind: delivery priced by the number of DOORS in the consignment (ex-VAT). Each split
# delivery is a separate consignment priced on its own door count, so this works per-invoice.
# Ironmongery-only delivery is £15. Excluded (POA) postcodes can't be priced. From May 2026.
JBKIND_DOOR_DELIVERY = {1: 42.0, 2: 47.0, 3: 52.0, 4: 57.0}     # 5+ doors → £62
JBKIND_5PLUS = 62.0
JBKIND_IRONMONGERY = 15.0
# JB Kind lines that are NOT a door (so they don't inflate the door count).
_JBKIND_IRONMONGERY_WORDS = (
    "hinge", "handle", "latch", "knob", "pull", "bolt", "escutcheon", "spindle", "screw",
    "fixing", "lock", "catch", "stay", "hook", "numeral", "letterplate", "letter plate",
    "doorstop", "door stop", "tubular", "mortice", "cylinder", "keep", "strike", "ironmongery")
# POA (price-on-application) postcode areas + district ranges — delivery not in standard pricing.
_JBKIND_EXCLUDED_AREAS = {"BT", "GY", "HS", "IM", "IV", "JE", "KW", "ZE"}
_JBKIND_EXCLUDED_RANGES = {"KA": (27, 28), "PA": (20, 80), "PH": (39, 44),
                           "PO": (30, 41), "TR": (21, 25)}


def _is_jbkind(supplier):
    return (supplier or "").startswith("jbkind")


def _jbkind_excluded(ship):
    """True if the delivery postcode is a JB Kind POA (excluded) area — can't be priced."""
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    m = re.match(r"([A-Z]{1,2})(\d{1,2})", pc)
    if not m:
        return False
    area, dist = m.group(1), int(m.group(2))
    if area in _JBKIND_EXCLUDED_AREAS:
        return True
    if area in _JBKIND_EXCLUDED_RANGES:
        lo, hi = _JBKIND_EXCLUDED_RANGES[area]
        return lo <= dist <= hi
    return False


def _jbkind_doors(lines):
    """(door_count, has_ironmongery) on the invoice. Doors = total qty of product lines that
    aren't ironmongery/carriage; ironmongery lines are counted separately (for the £15 rate)."""
    doors, iron = 0, False
    for l in (lines or []):
        s, d = l.get("sku") or "", l.get("description") or ""
        if _is_delivery(s) or _is_delivery(d) or _is_surcharge(s) or _is_surcharge(d):
            continue
        q = l.get("qty") if isinstance(l.get("qty"), (int, float)) else 1
        if any(w in d.lower() for w in _JBKIND_IRONMONGERY_WORDS):
            iron = True
        else:
            doors += q
    return int(round(doors)), iron


def _jbkind_expected(lines, ship=None):
    """Expected ex-VAT JB Kind carriage from the door count. None = POA postcode or can't tell
    (so the caller leaves it as an un-checked note rather than a false discrepancy)."""
    if ship and _jbkind_excluded(ship):
        return None
    doors, iron = _jbkind_doors(lines)
    if doors <= 0:
        return JBKIND_IRONMONGERY if iron else None
    if doors >= 5:
        return JBKIND_5PLUS
    return JBKIND_DOOR_DELIVERY.get(doors)


# --- LPD (Leeds Plywood & Doors): delivery is priced PER DELIVERY by the NUMBER OF DOORS (ex-VAT):
# £40 for 1 door, then +£5 per extra door, capped at £80 (9+ doors). Hardware-only deliveries are
# £15 (1-10 packs) / £20 (11+). Scotland & island postcodes add a per-delivery surcharge; London
# congestion outward codes add £15. Some postcodes are POA / non-deliverable (can't price). We hold
# the MAX legit charge, so charging that or LESS is fine — only an over-charge flags. Flyer 2025.
LPD_DOOR_BASE = 40.0
LPD_DOOR_STEP = 5.0
LPD_DOOR_CAP = 80.0
LPD_HARDWARE_LO, LPD_HARDWARE_HI = 15.0, 20.0          # 1-10 packs / 11+ packs
_LPD_CONGESTION = {"W1", "NW1", "WC1", "WC2", "EC1", "EC2", "EC3", "EC4", "E1", "SE1", "SE11"}


def _is_lpd(supplier):
    return (supplier or "").startswith("lpd")


def _lpd_pc_parts(ship):
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    m = re.match(r"([A-Z]{1,2})(\d{1,2})", pc)
    if not m:
        return None, None, None
    outward = pc.split(" ")[0] if " " in pc else (pc[:-3] if len(pc) > 3 else pc)
    return m.group(1), int(m.group(2)), outward.strip()


def _lpd_surcharge(ship):
    """(surcharge £, poa). poa True = LPD can't price it (POA / non-deliverable). Includes the
    £15 London congestion add-on where the outward code matches."""
    area, dist, outward = _lpd_pc_parts(ship)
    if area is None:
        return 0.0, False
    if area in ("GY", "IM", "JE"):
        return 0.0, True
    if (area == "IV" and dist == 40) or (area == "TR" and 21 <= dist <= 25) \
            or (area == "PO" and 30 <= dist <= 40):
        return 0.0, True
    s = 0.0
    if area == "AB":
        s = 37.0
    elif area == "BT":
        s = 70.0
    elif area == "DD":
        s = 42.0
    elif area == "HS":
        s = 95.0
    elif area == "IV":
        s = 40.0
    elif area == "KY":
        s = 37.0
    elif area == "PH":
        s = 40.0
    elif area == "ZE":
        s = 95.0
    elif area == "KW":
        s = 40.0 if dist <= 14 else 95.0
    elif area == "PA":
        s = 37.0 if dist <= 19 else 67.50
    elif area == "KA" and 27 <= dist <= 28:
        s = 95.0
    elif area == "FK" and 8 <= dist <= 21:
        s = 20.0
    elif area == "G" and (dist == 63 or 82 <= dist <= 84):
        s = 20.0
    if f"{area}{dist}" in _LPD_CONGESTION:      # congestion codes are area+district (e.g. EC1)
        s += 15.0
    return s, False


def _lpd_doors(lines):
    """(door_count, hardware_packs) on the invoice. Doors = qty of product lines that aren't
    ironmongery/hardware or delivery; ironmongery/hardware lines count as packs."""
    doors, packs = 0, 0
    for l in (lines or []):
        s, d = l.get("sku") or "", l.get("description") or ""
        if _is_delivery(s) or _is_delivery(d) or _is_surcharge(s) or _is_surcharge(d):
            continue
        q = l.get("qty") if isinstance(l.get("qty"), (int, float)) else 1
        if any(w in d.lower() for w in _JBKIND_IRONMONGERY_WORDS):
            packs += q
        else:
            doors += q
    return int(round(doors)), int(round(packs))


def _lpd_expected(lines, ship=None):
    """Expected (max legit) ex-VAT LPD carriage: door-count band (or hardware rate) + postcode
    surcharge. None = POA/non-deliverable postcode or can't tell (noted, not flagged)."""
    surcharge, poa = _lpd_surcharge(ship)
    if poa:
        return None
    doors, packs = _lpd_doors(lines)
    if doors > 0:
        base = min(LPD_DOOR_BASE + (doors - 1) * LPD_DOOR_STEP, LPD_DOOR_CAP)
    elif packs > 0:
        base = LPD_HARDWARE_LO if packs <= 10 else LPD_HARDWARE_HI
    else:
        return None
    return base + surcharge


# --- Southern Sheeting: delivery priced by the delivery postcode's colour ZONE (ex-VAT):
# White/Purple £50, Blue £80, Green/Orange £115. The full postcode→zone map (1,469 outward
# codes) is bundled as southern_zones.json {outward: £}. We hold the MAX zone price per postcode
# across their product sheets, so charging that or LESS is fine — only an over-charge flags.
@st.cache_data(show_spinner=False)
def _southern_zones():
    try:
        with open(BASE / "southern_zones.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _is_southern(supplier):
    return (supplier or "").startswith("southern")


def _southern_expected(ship):
    """Expected (max legit) ex-VAT Southern Sheeting carriage for the delivery postcode's zone.
    None if the postcode isn't in their zone list (then it's noted, not flagged)."""
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    if not pc:
        return None
    if " " in pc:                       # 'AL1 2BC' → outward 'AL1'
        outward = pc.split(" ")[0]
    elif len(pc) > 3:                    # 'AL12BC' → drop the 3-char inward code
        outward = pc[:-3]
    else:
        outward = pc
    return _southern_zones().get(outward.strip())

# Decor8 don't give us a cost pricelist — they invoice at ~12% OFF OUR OWN sell price. So we
# check what we paid per unit ≈ (our ex-VAT Shopify sell price − 12%), rather than vs a cost.
DECOR8_DISCOUNT = 0.12       # expected discount off our own price
DECOR8_MIN_DISCOUNT = 0.10   # accept 10%+ off; flag if the discount is smaller (we overpaid)


def _is_decor8(supplier):
    return (supplier or "").startswith("decor8") or (supplier or "").startswith("decor")

# Temporary per-supplier surcharge (fraction) applied on top of the pricelist cost, so a
# line billed at pricelist + surcharge is EXPECTED (not flagged). Eurocell added a temporary
# 5% surcharge from 1 June 2026 (Middle East supply-chain costs) — remove this line when
# they drop it.
SUPPLIER_SURCHARGE = {
    "eurocell": 0.05,
}

# --- Carron: zone-based delivery, priced on the DELIVERY POSTCODE (ex-VAT, per pallet).
# Zone 1 (UK mainland) is free over £250 ex-VAT, else £25 large / £10 small. Zones 2-6 are
# per-zone surcharges. We can't tell 'large' from 'small' (Carron say "ask sales"), so we
# check against the LARGER (max legitimate) charge and only flag a genuine overcharge. ---
CARRON_FREE_OVER = 250.0
CARRON_ZONES = {
    1: {"name": "UK Mainland", "large": 25.0, "small": 10.0},
    2: {"name": "Scotland", "large": 50.0, "small": 20.0},
    3: {"name": "Scottish Highlands", "large": 85.0, "small": 25.0},
    4: {"name": "Northern Ireland", "large": 65.0, "small": 25.0},
    5: {"name": "Republic of Ireland", "large": None, "small": None},   # rates TBC
    6: {"name": "Isles", "large": 105.0, "small": 25.0},
}
# Postcode AREA (leading letters) → zone. Anything not listed = Zone 1 (mainland). This is
# approximate (from Carron's zone map) — edit freely if a postcode lands in the wrong zone.
CARRON_AREA_ZONE = {
    "AB": 2, "DD": 2, "DG": 2, "EH": 2, "FK": 2, "G": 2, "KA": 2, "KY": 2,
    "ML": 2, "PA": 2, "TD": 2,                                # Zone 2 — Scotland
    "IV": 3, "KW": 3, "PH": 3,                                # Zone 3 — Highlands
    "BT": 4,                                                  # Zone 4 — N. Ireland
    "HS": 6, "ZE": 6, "IM": 6,                                # Zone 6 — Isles
}


def _is_carron(supplier):
    return (supplier or "").startswith("carron")


def _carron_zone(ship):
    """Carron delivery zone (1-6) for a Shopify shipping address {postcode, country}.
    Defaults to Zone 1 (mainland) when the address can't be read."""
    if not ship:
        return 1
    country = (ship.get("country") or "").strip().upper()
    if country in ("IE", "IRL", "IRELAND", "REPUBLIC OF IRELAND", "EIRE"):
        return 5
    pc = re.sub(r"[^A-Z0-9]", "", (ship.get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    return CARRON_AREA_ZONE.get(area, 1)


def _carron_zone_label(ship):
    z = _carron_zone(ship)
    pc = (ship or {}).get("postcode") or "no postcode"
    return f"Carron Zone {z} — {CARRON_ZONES[z]['name']}, {pc}"


def _carron_expected(goods_value, ship):
    """Max legitimate ex-VAT Carron delivery for the zone (None if unknown/TBC)."""
    z = _carron_zone(ship)
    zc = CARRON_ZONES[z]
    if z == 1 and goods_value is not None and goods_value >= CARRON_FREE_OVER:
        return 0.0                                            # free over £250 ex-VAT, mainland
    return zc["large"]                                        # None for Zone 5 (ROI, TBC)

# Default email address for supplier discrepancy chases, keyed by normalised supplier
# name (_norm_code). Used as the 'To' default before the order's own email field.
SUPPLIER_EMAILS = {
    "upb": "janetwitt@upbuildingproducts.com",
    "up": "janetwitt@upbuildingproducts.com",
    "upbuildingproducts": "janetwitt@upbuildingproducts.com",
    "pjh": "accounts@pjh.uk",
    "gap": "carrie.morris@gap.uk.com",
    "decor8": "amanda.clarkson@decor8northern.co.uk",   # Amanda Clarkson
    "eurocell": "karla.turner@eurocell.co.uk",          # Karla Turner (+ branch email from invoice)
}

# Per-supplier overrides. no_pricelist = don't price-check vs the pricelist (we
# don't hold one); push_min = margin % to push above (else hold); flag_high =
# whether to flag suspiciously-high margins.
SUPPLIER_RULES = {
    "travisperkins": {"name": "Travis Perkins", "no_pricelist": True,
                      "push_min": 10.0, "flag_high": False},
    # Decor8 auto-approve floor is 5%.
    "decor8": {"name": "Decor8", "push_min": 5.0},
    # Toolbank: no agreed delivery rate, so the ORDER MARGIN is the safeguard. Approve a matched
    # invoice (right products at the right prices) when order margin ≥ 12% — or ≥ 8% if the
    # customer used a discount code. Below that → leave for review (don't silently hold), and
    # don't flag a high margin (approve at 12%+ regardless of ceiling).
    "toolbank": {"name": "Toolbank", "push_min": 12.0, "push_min_discount": 8.0,
                 "flag_high": False, "flag_below": True},
}


def _is_toolbank(supplier):
    return (supplier or "").startswith("toolbank")

# Suppliers that re-code the same product, so their invoice SKU often differs slightly from ours.
# For these we match on the exact SKU FIRST, then fall back to a lenient name/code match (rather
# than saying 'not on the order'). Decor8 is handled separately — it has no SKUs at all.
LENIENT_NAME_SUPPLIERS = ("eurocell", "gap", "jbkind")


# Ctie (C TIE) zone-based delivery: UK mainland £7 under £100 (free over); Northern Ireland
# (BT postcodes) £13 under £250 (free over). Priced on the delivery postcode, like Carron.
CTIE_UK = {"flat": 7.0, "free_over": 100.0}
CTIE_NI = {"flat": 13.0, "free_over": 250.0}


def _is_ctie(supplier):
    return (supplier or "").startswith("ctie")


def _ctie_expected(goods_value, ship):
    pc = re.sub(r"[^A-Z0-9]", "", ((ship or {}).get("postcode") or "").upper())
    area = (re.match(r"[A-Z]+", pc) or [""])[0] if pc else ""
    country = ((ship or {}).get("country") or "").strip().upper()
    is_ni = area == "BT" or country in ("GB-NIR", "NORTHERN IRELAND")
    rule = CTIE_NI if is_ni else CTIE_UK
    if goods_value is not None and goods_value >= rule["free_over"]:
        return 0.0
    return rule["flat"]


# --- Nuie/Roxor: delivery priced by the delivery postcode ZONE and the product's shipping
# category (Parcel / Oversized Parcel / A-Frame / Pallet / Double Pallet). One charge per
# consignment = the BIGGEST item's rate. Rates below ALREADY include Nuie's +10%. The SKU→
# category map is bundled as nuie_ship.json (7,148 SKUs; 'Multi Carton' = Pallet). ---
NUIE_RATES = {                       # category: (Zone 1 mainland, Zone 2 offshore) — inc. +10%
    "parcel": (16.50, 16.50),
    "os_parcel": (30.80, 44.00),
    "aframe": (59.95, 110.00),
    "pallet": (59.95, 110.00),       # includes 'Multi Carton'
    "dbl_pallet": (110.00, 192.50),
}


@st.cache_data(show_spinner=False)
def _nuie_ship_map():
    try:
        with open(BASE / "nuie_ship.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _is_nuie(supplier):
    return (supplier or "").startswith("nuie")


def _nuie_zone(ship):
    """1 (UK mainland) or 2 (offshore islands/Highlands) for the delivery postcode. None if no
    postcode is known."""
    pc = ((ship or {}).get("postcode") or "").upper().strip()
    if not pc:
        return None
    out = pc.split(" ")[0] if " " in pc else (pc[:-3] if len(pc) > 3 else pc)
    m = re.match(r"([A-Z]{1,2})(\d+)", out.strip())
    if not m:
        return 1
    area, dist = m.group(1), int(m.group(2))
    if area in ("BT", "IM", "IV", "HS", "KW", "ZE"):
        return 2
    z2 = ((area == "AB" and (31 <= dist <= 38 or 41 <= dist <= 56))
          or (area == "KA" and dist in (27, 28))
          or (area == "PA" and 20 <= dist <= 78)
          or (area == "PH" and 15 <= dist <= 99)
          or (area == "PO" and 30 <= dist <= 41)
          or (area == "TR" and (21 <= dist <= 25 or 3 <= dist <= 6 or 10 <= dist <= 20)))
    return 2 if z2 else 1


def _nuie_expected(lines, ship):
    """Expected ex-VAT Nuie carriage — the BIGGEST item's rate for the delivery zone. None if none
    of the invoice's SKUs are in the shipping map (then it's noted, not flagged). Unknown postcode
    → Zone 2 (the higher rate) so we never false-flag."""
    zone = _nuie_zone(ship)
    idx = 0 if zone == 1 else 1            # zone None -> Zone 2 ceiling
    smap = _nuie_ship_map()
    cats = {smap.get(_norm_code(l.get("sku"))) for l in (lines or [])}
    cats = {c for c in cats if c in NUIE_RATES}
    if not cats:
        return None
    return max(NUIE_RATES[c][idx] for c in cats)


def _expected_delivery(supplier, goods_value, ship=None, lines=None):
    """Expected (max legitimate) ex-VAT delivery charge for a supplier given the order's goods
    value (Carron/Ctie/Nuie use the delivery address; JB Kind uses the door count from `lines`).
    None if no rule on file / can't be priced."""
    if _is_carron(supplier):
        return _carron_expected(goods_value, ship)
    if _is_ctie(supplier):
        return _ctie_expected(goods_value, ship)
    if _is_jbkind(supplier):
        return _jbkind_expected(lines, ship)
    if _is_lpd(supplier):
        return _lpd_expected(lines, ship)
    if _is_southern(supplier):
        return _southern_expected(ship)
    if _is_nuie(supplier):
        return _nuie_expected(lines, ship)
    if (supplier or "").startswith("vista"):
        return delivery_rules.vista_expected(goods_value, lines)
    rule = DELIVERY_CHARGES.get(supplier)
    if not rule:
        return None
    free_over = rule.get("free_over")
    if free_over is not None and goods_value is not None and goods_value >= free_over:
        return 0.0
    return float(rule.get("flat", 0.0))


def _is_delivery(text):
    t = (text or "").lower()
    return any(w in t for w in ("deliver", "carriage", "carrier", "courier", "freight",
                                "shipping", "postage", "haulage", "transport"))


def _is_surcharge(text):
    t = (text or "").lower()
    return "surcharge" in t or "uplift" in t


# Other AGREED supplier charges that legitimately appear on an invoice or returns credit
# but are never on the Shopify order (so they must not be flagged 'not on the order').
# 'amount' = the max legitimate ex-VAT £; omit it when the charge is a % we can't verify.
# Matched BEFORE the delivery rule, so a 'redelivery' line isn't mistaken for carriage.
SUPPLIER_CHARGES = {
    "gap": (
        {"keywords": ("redeliver", "re-deliver", "failed delivery"),
         "label": "redelivery (failed delivery)", "amount": 45.0},
        {"keywords": ("collection charge", "carriage collection", "returns collection",
                      "collection fee"),
         "label": "returns collection", "amount": 35.0},
        # 10% of the returned value — we don't reliably know that value, so recognise
        # the line (don't flag it) rather than guess.
        {"keywords": ("restock", "re-stock"), "label": "restocking (10%)"},
    ),
}


def _ancillary_charge(supplier, sku_raw, desc):
    """Match a line to a known non-carriage supplier charge (redelivery, returns
    collection, restocking). Returns the rule dict, or None."""
    t = f"{sku_raw} {desc}".lower()
    for rule in SUPPLIER_CHARGES.get(supplier, ()):
        if any(k in t for k in rule["keywords"]):
            return rule
    return None


def _check_invoice(parsed, meta, pidx, tol=0.01):
    """3-way match: each invoice line vs the supplier's pricelist cost and vs the
    order's SKUs/quantities. Known supplier delivery charges are recognised."""
    supplier = _norm_code(meta.get("supplier"))
    no_pl = SUPPLIER_RULES.get(supplier, {}).get("no_pricelist", False)
    tidx = _supplier_title_index() if not no_pl else None
    cidx = _supplier_code_index() if not no_pl else None
    order = _order_candidates(meta)
    # Split orders (Shopify drop-ship across suppliers, e.g. part Eurocell / part GAP): hold THIS
    # invoice's supplier responsible ONLY for the lines assigned to its fulfilment location. Lines
    # fulfilled by another supplier's location aren't 'missing' from this invoice, so they don't
    # trigger a false under-delivery. Only filters when the order is genuinely split AND we can
    # identify this supplier's location; otherwise the full order is used (safe fallback).
    _sid = meta.get("shopify_order_id")
    if _sid and order:
        _fsplit = _shopify_fulfillment_split(_sid)
        _locs = set(_fsplit.values())
        if len(_locs) >= 2:
            _sup_locs = {L for L in _locs if _loc_matches_supplier(L, supplier)}
            if _sup_locs:
                order = {k: v for k, v in order.items()
                         if (_fsplit.get(_norm_code(v.get("sku"))) or _fsplit.get(k)) is None
                         or (_fsplit.get(_norm_code(v.get("sku"))) or _fsplit.get(k)) in _sup_locs}
    parsed_lines = parsed.get("lines") or []
    # Carron & Ctie delivery is priced by the delivery postcode — fetch it once.
    carron_ship = (_shopify_order_ship(meta["shopify_order_id"])
                   if (_is_carron(supplier) or _is_ctie(supplier) or _is_jbkind(supplier)
                       or _is_southern(supplier) or _is_nuie(supplier))
                   and meta.get("shopify_order_id") else None)

    def _line_total(l):
        if isinstance(l.get("line_total"), (int, float)):
            return l["line_total"]
        u, q = l.get("unit_price"), l.get("qty")
        return u * q if isinstance(u, (int, float)) and isinstance(q, (int, float)) else 0

    def _is_charge_line(l):  # delivery or surcharge — not a product line
        return (_is_delivery(l.get("sku")) or _is_delivery(l.get("description"))
                or _is_surcharge(l.get("sku")) or _is_surcharge(l.get("description")))

    goods_value = sum(_line_total(l) for l in parsed_lines if not _is_charge_line(l))

    # For Decor8, the free-delivery threshold (£50) is on OUR retail value, not their
    # discounted invoice total. It must be judged on what THIS invoice actually delivered:
    # on a part-shipment the supplier legitimately charges the £5.99 even when the FULL order
    # is over £50. Using the whole order's retail over-stated a part delivery and wrongly
    # flagged a valid carriage line. Their invoice is ~12% off our retail, so gross this
    # invoice's own goods back up to retail.
    delivery_goods = goods_value
    if _is_decor8(supplier) and goods_value:
        delivery_goods = goods_value / max(0.01, 1.0 - DECOR8_DISCOUNT)

    common = _order_common_tokens(order)
    lines, pending, hit = [], [], set()
    saw_delivery = False
    inv_qty = {}   # order key → TOTAL invoiced qty (a product split across invoice lines sums)

    def _hit(rec, k):
        rec["_okey"] = k
        hit.add(k)
        q = rec.get("qty")
        if isinstance(q, (int, float)):
            inv_qty[k] = inv_qty.get(k, 0) + q

    for ln in parsed_lines:
        sku_raw = ln.get("sku") or ""
        desc = ln.get("description") or ""
        qty, unit = ln.get("qty"), ln.get("unit_price")

        # Other agreed supplier charge (redelivery / returns collection / restocking).
        # Legitimate and never on the Shopify order. Checked BEFORE delivery so that a
        # 'redelivery' line isn't read as carriage and compared to the carriage rate.
        chg = _ancillary_charge(supplier, sku_raw, desc)
        if chg:
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            cap = chg.get("amount")
            aissues = []
            if cap is not None and isinstance(amt, (int, float)) and abs(amt) > cap + tol:
                aissues.append(("price", f"{chg['label']} £{abs(amt):,.2f} vs agreed "
                                         f"£{cap:,.2f}"))
            lines.append({"sku": sku_raw or chg["label"], "desc": desc or chg["label"],
                          "qty": qty, "unit": unit, "cost": cap, "issues": aissues})
            continue

        # Delivery / carriage line — check against the supplier's expected charge.
        if _is_delivery(sku_raw) or _is_delivery(desc):
            saw_delivery = True
            known = _expected_delivery(supplier, delivery_goods, carron_ship, parsed_lines)
            zinfo = f" ({_carron_zone_label(carron_ship)})" if _is_carron(supplier) else ""
            if _is_jbkind(supplier):
                _dn, _ = _jbkind_doors(parsed_lines)
                zinfo = f" ({_dn} door{'s' if _dn != 1 else ''})" if _dn else " (ironmongery)"
            elif _is_lpd(supplier):
                _dn, _hp = _lpd_doors(parsed_lines)
                zinfo = (f" ({_dn} door{'s' if _dn != 1 else ''})" if _dn
                         else f" ({_hp} hardware pack{'s' if _hp != 1 else ''})" if _hp else "")
            elif _is_southern(supplier) and known is not None:
                zinfo = f" ({(carron_ship or {}).get('postcode', '')} zone)"
            elif _is_nuie(supplier) and known is not None:
                zinfo = f" (Zone {_nuie_zone(carron_ship) or '?'})"
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            dissues = []
            if isinstance(amt, (int, float)):
                if known is not None:
                    if amt > known + tol:        # only flag if charged MORE (less is fine)
                        dissues.append(("delivery", f"delivery £{amt:,.2f} vs expected "
                                                    f"£{known:,.2f}{zinfo}"))
                elif _is_carron(supplier):
                    dissues.append(("delivery", f"delivery £{amt:,.2f} —{zinfo} rate is TBC, "
                                                "can't check"))
                elif _is_jbkind(supplier):
                    dissues.append(("name", f"delivery £{amt:,.2f} — JB Kind POA postcode / door "
                                            "count unclear; not auto-checked"))
                elif _is_lpd(supplier):
                    dissues.append(("name", f"delivery £{amt:,.2f} — LPD POA postcode / door count "
                                            "unclear; not auto-checked"))
                elif _is_toolbank(supplier):
                    dissues.append(("name", f"delivery £{amt:,.2f} — Toolbank (no set rate; "
                                            "checked via the order margin instead)"))
                elif _is_southern(supplier):
                    dissues.append(("name", f"delivery £{amt:,.2f} — Southern Sheeting postcode "
                                            "not in the zone list; not auto-checked"))
                elif _is_nuie(supplier):
                    dissues.append(("name", f"delivery £{amt:,.2f} — Nuie: no shipping category "
                                            "for these SKUs; not auto-checked"))
                else:
                    dissues.append(("delivery", f"delivery £{amt:,.2f} — no agreed rate on file"))
            lines.append({"sku": sku_raw or "Delivery", "desc": desc, "qty": qty,
                          "unit": unit, "cost": known, "issues": dissues})
            continue

        # Surcharge line (e.g. Eurocell's temporary 5%). It's on the invoice but NEVER on the
        # Shopify order, so it must NOT be flagged 'not on the order'. If we know the supplier's
        # surcharge rate, check the amount is ~that % of goods; otherwise just accept it.
        if _is_surcharge(sku_raw) or _is_surcharge(desc):
            sur = SUPPLIER_SURCHARGE.get(supplier, 0.0)
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            sissues = []
            if sur and isinstance(amt, (int, float)) and goods_value:
                exp = goods_value * sur
                if amt > exp + tol:              # only flag an OVER-applied surcharge
                    sissues.append(("price", f"surcharge £{amt:,.2f} vs expected "
                                             f"{sur * 100:.0f}% of goods (£{exp:,.2f})"))
                else:
                    sissues.append(("name", f"{sur * 100:.0f}% surcharge £{amt:,.2f} — expected, "
                                            "not on the Shopify order"))
            else:
                sissues.append(("name", "surcharge — expected, not on the Shopify order"))
            lines.append({"sku": sku_raw or "Surcharge", "desc": desc, "qty": qty,
                          "unit": unit, "cost": None, "issues": sissues})
            continue

        sk = _norm_code(sku_raw)
        issues = []
        cost = None
        title_note = None
        if _is_decor8(supplier):
            # Decor8 have NO SKUs and no cost pricelist — priced vs OUR OWN price, taken from the
            # Shopify order line they match by NAME. Resolved after the order match, below.
            pass
        else:
            supcosts = pidx.get(sk) or {}
            cost = supcosts.get(supplier)             # strictly the SKU's cost for this supplier
            # If this supplier's SKU isn't on our pricelist, first look for THIS SUPPLIER's own
            # pricelist code printed in the line (e.g. UPB's VL7 in the description)…
            if cost is None and not no_pl and cidx:
                c2, mc = _supplier_code_cost(sku_raw, desc, supplier, cidx)
                if c2 is not None:
                    cost, title_note = c2, f"code {mc}"
            # …then fall back to matching THIS SUPPLIER's product title (e.g. UPB).
            if cost is None and not no_pl and tidx:
                c2, mt = _supplier_title_cost(desc, supplier, tidx)
                if c2 is not None:
                    cost, title_note = c2, mt
            if not no_pl:                             # suppliers with no pricelist: skip price check
                if isinstance(unit, (int, float)) and isinstance(cost, (int, float)):
                    sur = SUPPLIER_SURCHARGE.get(supplier, 0.0)   # e.g. Eurocell temporary 5%
                    allowed = cost * (1 + sur)                    # pricelist + expected surcharge
                    via = f" (vs '{title_note}' on the pricelist)" if title_note else ""
                    if unit > allowed + tol:
                        if sur:
                            issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                                    f"+{sur * 100:.0f}% surcharge (£{allowed:,.2f}) — "
                                                    f"still over by £{unit - allowed:,.2f}{via}"))
                        else:
                            issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                                    f"(+£{unit - cost:,.2f}){via}"))
                    elif sur and unit > cost + tol:               # within surcharge band — expected
                        issues.append(("name", f"£{unit:,.2f} = pricelist £{cost:,.2f} + "
                                               f"{sur * 100:.0f}% surcharge{via}"))
                    elif title_note:
                        issues.append(("name", f"price checked vs '{title_note}' on the pricelist"))
                elif isinstance(unit, (int, float)) and cost is None:
                    issues.append(("noprice", "no pricelist cost for this supplier/SKU"))
        rec = {"sku": sku_raw, "desc": ln.get("description"), "qty": qty,
               "unit": unit, "line_total": ln.get("line_total"), "cost": cost,
               "issues": issues, "_okey": None}
        lines.append(rec)

        # Order match. Exact SKU and embedded-code matches are certain, so assign them now.
        # A fuzzy NAME match is DEFERRED — all name matches are then resolved together,
        # strongest first, so a weak colour-only overlap can't steal a line the right line
        # needs. Exact SKU does NOT consume the order line — the same product can appear on
        # several invoice lines and we sum their quantities (checked after the loop).
        eq = _equiv_match(supplier, sk, desc, order, hit)
        skc = _sku_keys(sk, order)
        if eq:
            _hit(rec, eq)
            issues.append(("name", f"matched to order line {order[eq]['sku']} — known product "
                                   "equivalence (supplier names it differently)"))
        elif len(skc) == 1:
            _hit(rec, skc[0])
            issues.append(("name", f"matched to order line {order[skc[0]]['sku']} — SKU matches "
                                   "exactly"))
        elif len(skc) > 1:
            # One SKU, several order lines (variants sharing a SKU) — the SKU alone can't say
            # which, so defer to the name match below where the size/variant decides.
            pending.append(rec)
        else:
            ck = _code_match(sk, order, hit)
            if ck and _names_ok(desc, order[ck].get("name"), common):
                _hit(rec, ck)
                issues.append(("name", f"matched to order line {order[ck]['sku']} by product "
                                       "code (in our SKU)"))
            else:
                pending.append(rec)                  # no/ambiguous code → resolve by name below

    # Carriage/delivery shown in the invoice TOTALS (not as a line) — e.g. Decor8's 'Carriage
    # Net'. Check it against the supplier's expected delivery, unless a delivery line was already
    # seen above (avoid double-counting).
    carriage = parsed.get("carriage")
    if isinstance(carriage, (int, float)) and carriage > tol and not saw_delivery:
        known = _expected_delivery(supplier, delivery_goods, carron_ship, parsed_lines)
        cissues = []
        if known is not None:
            if carriage > known + tol:
                zinfo = f" ({_carron_zone_label(carron_ship)})" if _is_carron(supplier) else ""
                if _is_jbkind(supplier):
                    _dn, _ = _jbkind_doors(parsed_lines)
                    zinfo = f" ({_dn} door{'s' if _dn != 1 else ''})" if _dn else " (ironmongery)"
                elif _is_lpd(supplier):
                    _dn, _hp = _lpd_doors(parsed_lines)
                    zinfo = (f" ({_dn} door{'s' if _dn != 1 else ''})" if _dn
                             else f" ({_hp} hardware pack{'s' if _hp != 1 else ''})" if _hp else "")
                elif _is_southern(supplier):
                    zinfo = f" ({(carron_ship or {}).get('postcode', '')} zone)"
                elif _is_nuie(supplier):
                    zinfo = f" (Zone {_nuie_zone(carron_ship) or '?'})"
                cissues.append(("delivery", f"carriage £{carriage:,.2f} vs expected "
                                            f"£{known:,.2f}{zinfo}"))
        elif _is_jbkind(supplier):
            cissues.append(("name", f"carriage £{carriage:,.2f} — JB Kind POA postcode / door "
                                    "count unclear; not auto-checked"))
        elif _is_lpd(supplier):
            cissues.append(("name", f"carriage £{carriage:,.2f} — LPD POA postcode / door count "
                                    "unclear; not auto-checked"))
        elif _is_toolbank(supplier):
            cissues.append(("name", f"carriage £{carriage:,.2f} — Toolbank (no set rate; "
                                    "checked via the order margin instead)"))
        elif _is_southern(supplier):
            cissues.append(("name", f"carriage £{carriage:,.2f} — Southern Sheeting postcode "
                                    "not in the zone list; not auto-checked"))
        elif _is_nuie(supplier):
            cissues.append(("name", f"carriage £{carriage:,.2f} — Nuie: no shipping category for "
                                    "these SKUs; not auto-checked"))
        elif not _is_carron(supplier):
            cissues.append(("delivery", f"carriage £{carriage:,.2f} — no agreed rate on file"))
        lines.append({"sku": "Carriage", "desc": "Carriage (from invoice totals)", "qty": None,
                      "unit": carriage, "cost": known, "issues": cissues})

    # Resolve deferred name matches: score every (invoice line, unused order line) pair on
    # their distinctive shared words, then assign the strongest pairs first (each order line
    # used once). This stops the greedy "first line wins" mis-assignments.
    scored = []
    for idx, rec in enumerate(pending):
        dt = _title_tokens(rec["desc"])
        for k, v in order.items():
            if k in hit:
                continue
            s = _name_pair_score(dt, _title_tokens(v.get("name")), common)
            if s > 0:
                scored.append((s, idx, k))
    scored.sort(key=lambda x: (-x[0], x[1]))          # best score first, then earliest line
    done = set()
    for _s, idx, k in scored:
        if idx in done or k in hit:
            continue
        done.add(idx)
        _hit(pending[idx], k)
        pending[idx]["issues"].append(("name", f"matched to order line {order[k]['sku']} by "
                                               "product name (invoice SKU differs)"))
    # Lenient leftover pass for suppliers whose invoice SKU often differs from ours: Decor8 (no
    # SKUs at all) and Eurocell/GAP (they re-code the same product). Exact SKU is always tried
    # FIRST (above); this only runs on what's left, pairing each still-unmatched invoice line to
    # the remaining order line it most resembles — by shared distinctive product words OR a long
    # shared SKU prefix — so we don't falsely say 'not on the order'.
    if _is_decor8(supplier) or supplier in LENIENT_NAME_SUPPLIERS:
        d8 = _is_decor8(supplier)
        lscored = []
        for idx in range(len(pending)):
            if idx in done:
                continue
            dt = _title_tokens(pending[idx]["desc"])
            isk = _norm_code(pending[idx].get("sku"))
            for k, v in order.items():
                if k in hit:
                    continue
                shared = dt & _title_tokens(v.get("name"))
                # Real shared WORDS (4+ chars) — not a size digit like '5' (5L vs 2.5L), which
                # must never link two unrelated products.
                longsh = [t for t in shared if len(t) >= 4]
                # Code similarity: a long shared SKU prefix (SILILMNRO vs SILILMN...) or one code
                # fully contained in the other. Strong, distinctive signal for re-coded products.
                osk = _norm_code(v.get("sku"))
                pfx = 0
                if isk and osk:
                    m = min(len(isk), len(osk))
                    while pfx < m and isk[pfx] == osk[pfx]:
                        pfx += 1
                code_ok = pfx >= 5 or (isk and osk and min(len(isk), len(osk)) >= 5
                                       and (isk in osk or osk in isk))
                # Decor8 (no SKU): a single shared 4+ word is enough. Eurocell/GAP have SKUs, so
                # ask for a stronger name signal (a 5+ word or two 4+ words) OR a code match.
                name_ok = (bool(longsh) if d8
                           else any(len(t) >= 5 for t in longsh) or len(longsh) >= 2)
                if name_ok or code_ok:
                    lscored.append((len(longsh) * 2 + pfx, idx, k))
        lscored.sort(key=lambda x: (-x[0], x[1]))
        for _ov, idx, k in lscored:
            if idx in done or k in hit:
                continue
            done.add(idx)
            _hit(pending[idx], k)
            why = ("Decor8 — no SKU, so name-matched" if d8
                   else "invoice SKU differs slightly — matched by product name/code")
            pending[idx]["issues"].append(
                ("name", f"matched to order line {order[k]['sku']} — {why}"))
    for idx, rec in enumerate(pending):
        if idx not in done:
            rec["issues"].append(("notorder", "not on the order"))

    # Quantity check on the TOTAL invoiced per order line. A product split across invoice lines
    # that sums to the ordered qty is fine. A SHORTFALL (invoiced < ordered) is NOT a discrepancy
    # on its own — the rest may be on the order's other invoice(s); it's recorded in `short` and
    # reconciled across the order's invoices later. Only an OVER-invoice (invoiced > ordered) on a
    # single invoice is a hard quantity discrepancy here. One note per order line.
    short = {}   # order key → (invoiced_here, ordered)  when this invoice is short on that line
    for k in hit:
        exp, tot = order[k]["qty"], inv_qty.get(k)
        if exp is None or tot is None or int(round(tot)) == exp:
            continue
        recs = [r for r in lines if r.get("_okey") == k]
        td = int(tot) if float(tot).is_integer() else tot
        if tot > exp:                                    # over-invoiced → real discrepancy
            if recs:
                extra = f" (across {len(recs)} invoice lines)" if len(recs) > 1 else ""
                recs[0]["issues"].append(("qty", f"invoiced {td}{extra} vs order {exp}"))
        else:                                            # short → reconcile across invoices
            short[k] = (tot, exp)

    # Decor8 price check (deferred): they have no SKUs/cost pricelist, so use OUR OWN price —
    # the ex-VAT line price from the Shopify order line they matched by NAME — less ~12%. Also
    # flag a reminder to eyeball the SIZE, as Decor8 name different pot sizes very similarly.
    if _is_decor8(supplier):
        for rec in lines:
            okey = rec.get("_okey")
            if okey is None:                          # charge line or not matched to the order
                continue
            rec["issues"].append(("name", "⚠ check the SIZE matches (Decor8 name different "
                                          "pot sizes very similarly)"))
            our_sell = order[okey].get("price")       # our ex-VAT price on the Shopify order line
            q, lt = rec.get("qty"), rec.get("line_total")
            paid = (lt / q if isinstance(lt, (int, float)) and isinstance(q, (int, float)) and q
                    else rec.get("unit"))
            if our_sell and isinstance(paid, (int, float)):
                rec["cost"] = paid
                disc = (1 - paid / our_sell) * 100
                if paid > our_sell * (1 - DECOR8_MIN_DISCOUNT) + tol:
                    rec["issues"].append(("price", f"paid £{paid:,.2f}/unit vs our price "
                                                   f"£{our_sell:,.2f} — only {disc:.1f}% off "
                                                   f"(expect ~{DECOR8_DISCOUNT * 100:.0f}%)"))
                else:
                    rec["issues"].append(("name", f"£{paid:,.2f} = our price £{our_sell:,.2f} "
                                                  f"less {disc:.1f}%"))
            elif isinstance(paid, (int, float)):
                rec["issues"].append(("noprice", "matched by name, but that Shopify order line "
                                                 "has no price to compare"))

    missing = [order[s]["sku"] for s in order if s not in hit]
    # Items on the order but not on THIS invoice (or short on it) don't make it a discrepancy —
    # they're expected on the order's other invoice(s). We call it an INCOMPLETE (not failed)
    # invoice: still approvable, reconciled across the order's invoices. 'name' notes are info.
    n_issues = sum(1 for l in lines for t, _ in l["issues"] if t != "name")   # missing NOT counted
    incomplete = (bool(missing) or bool(short)) and n_issues == 0   # under (missing/short), else fine
    return {"lines": lines, "missing": missing, "n_issues": n_issues, "incomplete": incomplete,
            "covered": set(hit), "order_map": {s: order[s]["sku"] for s in order},
            "inv_qty": {k: inv_qty.get(k) for k in hit},          # invoiced qty per line, THIS invoice
            "ord_qty": {s: order[s].get("qty") for s in order},   # ordered qty per order line
            "short": short}


def _verdict(res):
    """{order, price, incomplete} for a check result. 'order' pass/fail (missing items do NOT
    fail it — that's 'incomplete', not a discrepancy). 'price' is tri-state: True (all OK),
    False (a mismatch), None (couldn't check — grey '?'). 'incomplete' = clean but missing
    some ordered items (expected on another invoice)."""
    order_issue = any(t in ("qty", "notorder") for l in res["lines"] for t, _ in l["issues"])
    price_issue = any(t in ("price", "delivery") for l in res["lines"] for t, _ in l["issues"])
    price_unchecked = any(t == "noprice" for l in res["lines"] for t, _ in l["issues"])
    price = False if price_issue else (None if price_unchecked else True)
    return {"order": not order_issue, "price": price, "incomplete": bool(res.get("incomplete"))}


def _check_and_store(inv, parsed, lbsku, pidx):
    """Run the 3-way check + this-invoice margin, store the verdict (incl. margin)
    in session, and return (res, om)."""
    res = _check_invoice(parsed, inv, pidx)
    inv_costs = {_norm_code(l.get("sku")): l.get("unit_price")
                 for l in (parsed.get("lines") or [])
                 if isinstance(l.get("unit_price"), (int, float))}
    om = _order_margin(inv.get("order_items"), lbsku, cost_override=inv_costs)
    v = _verdict(res)
    v["margin"] = round(om["margin"]) if om else None
    v["missing"] = res.get("missing") or []          # for the incomplete-invoice note on Monday
    st.session_state.setdefault("inv_verdict", {})[inv["sub_id"]] = v
    # Record what THIS invoice covers of the order — covered lines AND invoiced quantity per line —
    # keyed by order, so the order's invoices build a combined picture with no re-parsing.
    if inv.get("order_no"):
        st.session_state.setdefault("inv_cov", {}).setdefault(inv["order_no"], {})[inv["sub_id"]] = {
            "covered": res.get("covered") or set(),
            "omap": res.get("order_map") or {},
            "inv_qty": res.get("inv_qty") or {},
            "ord_qty": res.get("ord_qty") or {},
            "n": inv.get("n_invoices") or 1,
        }
        _reconcile_and_adjust(inv["order_no"])
    return res, om


def _order_reconcile(order_no):
    """Aggregate invoiced quantity per order line across the order's CHECKED invoices.
    Returns (status, detail) where status is 'exact' | 'under' | 'over' | 'none', and detail is
    {line_key: {"sku", "ordered", "invoiced", "short"}}. 'over' = some line invoiced beyond the
    order across invoices (a real discrepancy); 'exact' = every line met; 'under' = still short."""
    cov = st.session_state.get("inv_cov", {}).get(order_no, {})
    if not cov:
        return "none", {}
    agg, ordq, skus = {}, {}, {}
    for rec in cov.values():
        if not isinstance(rec, dict):
            continue          # stale pre-upgrade entry (old tuple format) — refreshed on re-check
        for k, m in (rec.get("omap") or {}).items():
            skus[k] = m
        for k, q in (rec.get("inv_qty") or {}).items():
            if q is not None:
                agg[k] = agg.get(k, 0) + q
        for k, q in (rec.get("ord_qty") or {}).items():
            if q is not None:
                ordq[k] = q
    detail = {}
    over = under = False
    for k, oq in ordq.items():
        iv = agg.get(k, 0)
        detail[k] = {"sku": skus.get(k, k), "ordered": oq, "invoiced": iv,
                     "short": max(0, oq - iv)}
        if iv > oq + 0.001:
            over = True
        elif int(round(iv)) < oq:
            under = True
    status = "over" if over else ("under" if under else "exact")
    return status, detail


def _reconcile_and_adjust(order_no):
    """After (re)checking an invoice on a multi-invoice order, reconcile the whole order and
    update every checked invoice's verdict: over→discrepancy, exact→matched, under→approvable."""
    status, _detail = _order_reconcile(order_no)
    cov = st.session_state.get("inv_cov", {}).get(order_no, {})
    verds = st.session_state.get("inv_verdict", {})
    for sid in cov:
        v = verds.get(sid)
        if not v or v.get("price") is False:
            continue                     # a price/charge problem is a discrepancy regardless
        # A line genuinely not on the order (notorder) or over-invoiced on THIS invoice already
        # set order=False in _verdict; only relax/adjust the quantity picture here.
        if status == "over":
            v["order"] = False
            v["reconciled"] = False
            v["under"] = False
        elif status == "exact":
            v["reconciled"] = True
            v["under"] = False
            v["incomplete"] = False
        elif status == "under":
            v["reconciled"] = False
            v["under"] = True
    return status


# Professional inline SVG icons (no emojis) for the Invoice Check views.
_INV_SVG = {
    "check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" '
             'r="11" fill="#16a34a"/><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#fff" '
             'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "warn": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.5l10.5 18.5'
            'H1.5z" fill="#dc2626"/><rect x="11" y="9" width="2" height="6" rx="1" fill="#fff"/>'
            '<circle cx="12" cy="17.6" r="1.25" fill="#fff"/></svg>',
    "cross": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" '
             'r="11" fill="#dc2626"/><path d="M8 8l8 8M16 8l-8 8" stroke="#fff" stroke-width="2.4" '
             'stroke-linecap="round"/></svg>',
    # Grey "?" — price couldn't be checked (no pricelist cost matched). NOT a pass.
    "qmark": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" '
             'r="11" fill="#94a3b8"/><path d="M9 9.2a3 3 0 1 1 4 2.8c-.8.5-1 .9-1 1.8" fill="none" '
             'stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
             '<circle cx="12" cy="17.3" r="1.3" fill="#fff"/></svg>',
    "invoice": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               'stroke="#475569" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/><path d="M9 13h6M9 17h6"/></svg>',
    "credit": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
              'stroke="#ea580c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
              '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/><path d="M9 14h6"/></svg>',
    "inv_badge": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 40">'
                 '<rect x="13" y="10" width="46" height="20" rx="4" fill="#F26A21"/>'
                 '<text x="36" y="24.5" text-anchor="middle" fill="#fff" font-size="13" '
                 'font-weight="700" letter-spacing="1.5" '
                 "font-family=\"Bebas Neue,'Arial Narrow',Arial,sans-serif\">INV</text></svg>",
    "crn_badge": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 40">'
                 '<rect x="13" y="10" width="46" height="20" rx="4" fill="#21242B"/>'
                 '<text x="36" y="24.5" text-anchor="middle" fill="#fff" font-size="13" '
                 'font-weight="700" letter-spacing="1.5" '
                 "font-family=\"Bebas Neue,'Arial Narrow',Arial,sans-serif\">CRN</text></svg>",
    "file_o": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
              '<path d="M6 2.5h7.5L18 7v14.5H6z" fill="#F26A21"/>'
              '<path d="M13.2 2.7v4.3h4.3z" fill="#fff" fill-opacity="0.45"/>'
              '<path d="M9 12.5h6M9 16h4.5" stroke="#fff" stroke-width="1.5" '
              'stroke-linecap="round"/></svg>',
    "ext": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           'stroke="#F26A21" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
           '<path d="M14 4h6v6"/><path d="M20 4 10 14"/>'
           '<path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/></svg>',
}
_INV_ICON = {k: "data:image/svg+xml;base64," + base64.b64encode(v.encode()).decode()
             for k, v in _INV_SVG.items()}


def _inv_inline(name, size=18):
    return _INV_SVG[name].replace(
        "<svg ", f'<svg width="{size}" height="{size}" style="vertical-align:-4px" ', 1)


SUPPLIER_FROM_MAILBOX = "accounts@tradesuperstoreonline.co.uk"  # supplier chases sent from here
HELLO_MAILBOX = "hello@tradesuperstoreonline.co.uk"            # internal team inbox (chase deliveries)


def _underdelivery_email(inv, rec_detail, n_total):
    """Internal note to the team (hello@) that an order has been under-delivered so far, listing
    what's still outstanding, so they can chase the supplier for the rest."""
    onum = inv.get("order_no") or "?"
    sup = inv.get("supplier") or "the supplier"
    shorts = [d for d in rec_detail.values() if d["short"] > 0]
    body = [f"Order {onum} ({sup}) has been under-delivered so far."]
    if n_total >= 2:
        body.append(f"This is a further delivery — {n_total} invoices have come in for this order "
                    "and together they are still short of what was ordered:")
    else:
        body.append("This invoice covers fewer items than were ordered:")
    body.append("")
    for d in shorts:
        body.append(f"  - {d['sku']}: ordered {d['ordered']}, invoiced "
                    f"{int(round(d['invoiced']))} so far, {d['short']} still to come")
    body.append("")
    body.append(f"Please chase {sup} for the outstanding items.")
    return f"Order {onum} under-delivered — please chase {sup}", "\n".join(body)


def _expected_credit(res):
    """Total £ we expect the supplier to credit back = overcharges + not-ordered items
    across the discrepancy lines. Best-effort; 0 if nothing quantifiable."""
    import re as _re
    total = 0.0
    for l in res["lines"]:
        unit, qty, cost = l.get("unit"), l.get("qty"), l.get("cost")
        for t, msg in l["issues"]:
            if t == "price" and isinstance(unit, (int, float)) and isinstance(cost, (int, float)):
                q = qty if isinstance(qty, (int, float)) else 1
                total += max(0.0, unit - cost) * q
            elif t == "delivery" and isinstance(cost, (int, float)) \
                    and isinstance(unit, (int, float)) and unit > cost:
                total += unit - cost
            elif t == "notorder" and isinstance(unit, (int, float)):
                q = qty if isinstance(qty, (int, float)) else 1
                total += unit * q
            elif t == "qty" and isinstance(unit, (int, float)):
                m = _re.search(r"invoiced\s+(\d+)\s+vs\s+order\s+(\d+)", msg or "")
                if m and int(m.group(1)) > int(m.group(2)):
                    total += (int(m.group(1)) - int(m.group(2))) * unit
    return round(total, 2)


def _discrepancy_note(inv, res):
    """Short note for Monday's text_mm3gh2za — awaiting credit note, the expected
    credit total, and a brief reason."""
    credit = _expected_credit(res)
    reasons, seen = [], set()
    for l in res["lines"]:
        sku = l.get("sku") or "item"
        for t, _msg in l["issues"]:
            r = ({"price": f"{sku} overcharged", "delivery": "delivery overcharged",
                  "notorder": f"{sku} not on order", "qty": f"{sku} qty wrong"}).get(t)
            if r and r not in seen:
                seen.add(r)
                reasons.append(r)
    # Missing-from-this-invoice items are excluded — they normally fall on other invoices.
    reason = "; ".join(reasons[:6]) or "see invoice"
    head = f"Awaiting credit note from {inv.get('supplier') or 'supplier'}"
    if credit > 0:
        head += f" of £{credit:,.2f}"
    return f"{head} — invoice {inv.get('invoice_no')}, order {inv.get('order_no')}: {reason}."


def _duplicate_email(inv, other_no):
    """(subject, body) telling the supplier's accounts team they've invoiced one order twice."""
    amt = inv.get("total")
    amt_txt = f"£{amt:,.2f}" if isinstance(amt, (int, float)) else "the same amount"
    subject = f"Duplicate invoice — order {inv.get('order_no')} appears to have been billed twice"
    body = (f"Hi,\n\nWe've received two invoices charging {amt_txt} for the same order "
            f"({inv.get('order_no')}):\n\n"
            f"- Invoice {inv.get('invoice_no')}\n- Invoice {other_no}\n\n"
            "These look like a duplicate — the order has been invoiced twice. Please could you "
            "confirm and cancel one / issue a credit note for the duplicate?\n\n"
            "Many thanks,\nTrade Superstore Online")
    return subject, body


def _discrepancy_reason(inv, res):
    """One-line reason for the Discrepancy LOG (saved to Monday on flag, so the log can show
    what was wrong later without re-checking the invoice). No 'awaiting credit note' wording
    — that's only added once the supplier has actually been queried."""
    reasons, seen = [], set()
    for l in res["lines"]:
        sku = l.get("sku") or "item"
        for t, _m in l["issues"]:
            r = ({"price": f"{sku} overcharged", "delivery": "delivery overcharged",
                  "notorder": f"{sku} not on order", "qty": f"{sku} qty wrong"}).get(t)
            if r and r not in seen:
                seen.add(r)
                reasons.append(r)
    txt = "; ".join(reasons[:6]) or "see invoice"
    credit = _expected_credit(res)
    if credit > 0:
        txt += f" (expected credit £{credit:,.2f})"
    return "TradeHub: " + txt


def _discrepancy_email(inv, res):
    """(subject, body) for a supplier chase email built from the discrepancy."""
    lines = []
    for l in res["lines"]:
        sku = l.get("sku") or "item"
        for t, _msg in l["issues"]:
            if t == "price" and isinstance(l.get("unit"), (int, float)) and \
                    isinstance(l.get("cost"), (int, float)):
                lines.append(f"- {sku}: invoiced at £{l['unit']:.2f}, but our agreed price is "
                             f"£{l['cost']:.2f} (overcharged £{l['unit'] - l['cost']:.2f} per unit).")
            elif t == "qty":
                lines.append(f"- {sku}: invoiced quantity doesn't match our order ({_msg}).")
            elif t == "notorder":
                lines.append(f"- {sku}: this item was not on our order.")
            elif t == "noprice":
                lines.append(f"- {sku}: please confirm the agreed price.")
            elif t == "delivery":
                lines.append(f"- Delivery/carriage: {_msg}.")
    # NB: items on the order but not on this invoice are deliberately NOT included — they
    # normally fall on the order's other invoices, so we don't query them with the supplier.
    detail = "\n".join(lines) or "- please see the attached invoice."
    credit = _expected_credit(res)
    ask = ("Please could you check and confirm, or issue a credit note where appropriate?"
           if credit <= 0 else
           f"Please could you check and confirm, and issue a credit note for "
           f"£{credit:,.2f} where appropriate?")
    subject = f"Invoice query – Invoice {inv.get('invoice_no')} (our order {inv.get('order_no')})"
    body = (f"Hi,\n\nWe're reviewing invoice {inv.get('invoice_no')} relating to our order "
            f"{inv.get('order_no')} and have the following query:\n\n{detail}\n\n"
            f"{ask}\n\nMany thanks,\nTrade Superstore Online")
    return subject, body


def _run_one_invoice(inv, lbsku):
    """Read one invoice's PDF, run the 3-way match, and render the result with
    the margin we make and explicit pricelist + order checks."""
    if not inv.get("asset_id"):
        st.warning("No PDF is attached to this invoice on Monday — nothing to read.")
        return
    sub = inv["sub_id"]
    nonce = st.session_state.get(f"recheck_n_{sub}", 0)
    with st.spinner("Reading the invoice and matching…"):
        parsed = _read_invoice(inv["asset_id"], sub, nonce)
    if parsed.get("error"):
        if "ANTHROPIC_API_KEY" in parsed["error"]:
            st.info("Add your **ANTHROPIC_API_KEY** in Settings → Secrets to read invoices.")
        else:
            st.error("Couldn't read the invoice: " + parsed["error"][:200])
        return

    # Possible duplicate by AMOUNT — the same £ appears in 2+ of the order's INV columns, i.e.
    # another invoice on this order has the same total (the supplier may have billed it twice
    # under a different number). Amber warning; the user decides (numbers differ, so not deleted).
    _amt = inv.get("total")
    _cols = [v for v in (inv.get("inv_columns") or {}).values() if isinstance(v, (int, float))]
    _amt_dup = bool(inv.get("_dup_amt")) or (
        isinstance(_amt, (int, float)) and sum(1 for v in _cols if abs(v - _amt) <= 0.01) >= 2)
    if _amt_dup and not inv.get("_dup"):
        _other = inv.get("_dup_amt") or "the other invoice on this order"
        st.markdown(
            '<div style="background:#fef3c7;border:1px solid #fde68a;color:#92400e;'
            'font-weight:700;font-size:14px;padding:9px 14px;border-radius:6px;margin:2px 0 8px">'
            f'&#9888; POSSIBLE DUPLICATE — £{_amt:,.2f} appears twice on order '
            f'{inv.get("order_no") or "?"} (this invoice and invoice {_other}). The supplier may '
            'have billed this order twice — check before approving.</div>', unsafe_allow_html=True)
        _dsub = inv["sub_id"]
        if st.toggle("Email the supplier that they've charged twice", key=f"duptog_{_dsub}"):
            dsubj, dbody = _duplicate_email(inv, _other)
            _dto = (SUPPLIER_EMAILS.get(_norm_code(inv.get("supplier")))
                    or inv.get("supplier_email") or "")
            st.session_state.setdefault(f"dto_{_dsub}", _dto)
            st.session_state.setdefault(f"dsub_{_dsub}", dsubj)
            st.session_state.setdefault(f"dbod_{_dsub}", dbody)
            st.text_input("To", key=f"dto_{_dsub}")
            st.text_input("Subject", key=f"dsub_{_dsub}")
            st.text_area("Message", key=f"dbod_{_dsub}", height=200)
            st.caption(f"Sends from {SUPPLIER_FROM_MAILBOX} (falls back to a draft if sending "
                       "isn't enabled yet). Delete the duplicate copy from Monday separately.")
            if st.button("Send duplicate query", key=f"dupsend_{_dsub}", type="primary",
                         disabled=not st.session_state.get(f"dto_{_dsub}", "").strip()):
                to = st.session_state[f"dto_{_dsub}"].strip()
                subj, body = st.session_state[f"dsub_{_dsub}"], st.session_state[f"dbod_{_dsub}"]
                pdf_url = (data_sources.monday_asset_url(inv["asset_id"])
                           if inv.get("asset_id") else None)
                sent = drafted = False
                dlink = None
                try:
                    data_sources.send_supplier_email(SUPPLIER_FROM_MAILBOX, to, subj, body,
                                                     pdf_url=pdf_url)
                    sent = True
                except Exception:  # noqa: BLE001
                    try:
                        dlink = data_sources.create_supplier_draft(SUPPLIER_FROM_MAILBOX, to, subj,
                                                                   body, pdf_url=pdf_url)
                        drafted = True
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't send or draft: " + str(e)[:200])
                if sent or drafted:
                    link = f" [Open the draft]({dlink})" if dlink else ""
                    st.session_state["inv_flash"] = (
                        f"Duplicate query {'sent to' if sent else 'drafted for'} {to}"
                        + ("" if sent else " (sending needs Mail.Send)") + "." + link)
                    st.rerun()

    # Duplicate invoice — same invoice number logged more than once on this order. Flag it
    # red and offer to delete THIS subitem from Monday (destructive → confirm first).
    if inv.get("_dup"):
        st.markdown(
            '<div style="background:#fee2e2;border:1px solid #fecaca;color:#991b1b;'
            'font-weight:700;font-size:14px;padding:9px 14px;border-radius:6px;margin:2px 0 8px">'
            '&#9940; DUPLICATE INVOICE — this invoice number is logged more than once on order '
            f'{inv.get("order_no") or "?"}. Delete the extra copy so the order is not '
            'double-counted.</div>', unsafe_allow_html=True)
        dpend = f"delpend_{sub}"
        if not st.session_state.get(dpend):
            st.button("🗑 Delete this duplicate from Monday", key=f"del_{sub}",
                      on_click=_ss_set, args=(dpend, True))
        else:
            st.warning(f"Permanently delete invoice **{inv.get('invoice_no')}** (this Monday "
                       "subitem)? This can't be undone.")
            dy, dn = st.columns(2)
            dy.button("Yes — delete from Monday", key=f"delyes_{sub}", type="primary",
                      use_container_width=True, on_click=_confirm_delete,
                      args=(sub, inv.get("invoice_no"), dpend, inv))
            dn.button("Cancel", key=f"delno_{sub}", use_container_width=True,
                      on_click=_ss_pop, args=(dpend,))

    # Copy-friendly order/invoice numbers. Selecting text from the expander header
    # collapses the panel, so put one-click copy fields here (st.code has a hover
    # copy icon and copying doesn't rerun, so the box stays open).
    cc1, cc2 = st.columns(2)
    with cc1:
        st.caption("Order number — hover, click the copy icon")
        st.code(inv.get("order_no") or "—", language=None)
    with cc2:
        st.caption("Invoice number")
        st.code(inv.get("invoice_no") or "—", language=None)

    st.button("Re-run check", key=f"recheck_btn_{sub}", on_click=_ss_set,
              args=(f"recheck_n_{sub}", nonce + 1),
              help="Reads the invoice PDF again and re-runs the match (a few pence).")

    res, om = _check_and_store(inv, parsed, lbsku, _pricelist_index())
    # Monday's order-margin formula (formula_mkn9918j) is often blank (e.g. Carron); without a
    # margin a MATCHED invoice can never clear the push floor and gets held forever. Fall back to
    # the margin _check_and_store just computed from the order items + this invoice's costs.
    if inv.get("order_margin_live") is None and om:
        inv["order_margin_live"] = om["margin"]
    matched = res["n_issues"] == 0

    if res.get("incomplete"):
        st.markdown(f'<div style="display:flex;align-items:center;gap:8px;background:#fff7ed;'
                    f'color:#9a3412;font-weight:700;padding:8px 12px;border-radius:4px;margin:2px 0 8px">'
                    f'&#9203; INCOMPLETE INVOICE — prices &amp; quantities are correct, but not all '
                    f'ordered items are on it. Approvable; expect a further invoice.</div>',
                    unsafe_allow_html=True)
    elif matched:
        st.markdown(f'<div style="display:flex;align-items:center;gap:8px;background:#dcfce7;'
                    f'color:#166534;font-weight:700;padding:8px 12px;border-radius:4px;margin:2px 0 8px">'
                    f'{_inv_inline("check", 20)} FULLY MATCHED — prices and order all correct</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="display:flex;align-items:center;gap:8px;background:#fee2e2;'
                    f'color:#991b1b;font-weight:700;padding:8px 12px;border-radius:4px;margin:2px 0 8px">'
                    f'{_inv_inline("warn", 20)} DISCREPANCY — {res["n_issues"]} thing(s) to review</div>',
                    unsafe_allow_html=True)
    links = ""
    if inv.get("file_url"):
        links += (f'<a href="{inv["file_url"]}" target="_blank" style="display:inline-flex;'
                  f'align-items:center;gap:7px;color:#F26A21;text-decoration:none;'
                  f"font-family:'Bebas Neue',sans-serif;font-size:19px;letter-spacing:1px\">"
                  f'{_inv_inline("file_o", 18)} OPEN INVOICE PDF</a>')
    if inv.get("order_url"):
        links += (f'<a href="{inv["order_url"]}" target="_blank" style="display:inline-flex;'
                  f'align-items:center;gap:7px;color:#F26A21;text-decoration:none;margin-left:22px;'
                  f"font-family:'Bebas Neue',sans-serif;font-size:19px;letter-spacing:1px\">"
                  f'{_inv_inline("ext", 17)} VIEW ORDER ON SHOPIFY</a>')
    if links:
        st.markdown(f'<div style="margin:2px 0 6px">{links}</div>', unsafe_allow_html=True)

    it_total = parsed.get("total")
    # 'Monday total' = the whole-order invoiced figure = sum of INV1..INV5 + numeric_mm511b9c
    # recorded on the order, so it reflects everything invoiced against the order across all
    # its invoices — not just this single invoice's total. Fall back to this invoice's own
    # total only if the order-level columns are all blank.
    mt = inv.get("order_invoiced_total")
    if not isinstance(mt, (int, float)):
        mt = inv.get("total")
    # 'Sale total (to us)' = Monday '£ to us' (the customer paid) — Shopify total is
    # wrong for mixed orders, so use the figure recorded on Monday.
    sale_total = inv.get("to_us")

    def _tot_chip(label, value, sub, color):
        return (f'<div style="background:var(--card);border:1px solid var(--line);'
                f'border-top:3px solid {color};border-radius:7px;padding:9px 16px;min-width:150px">'
                f'<div style="font-size:11px;color:var(--muted);font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.6px">{label}</div>'
                f'<div style="font-size:22px;font-weight:800;color:var(--ink);line-height:1.15">'
                f'{value}</div>'
                f'<div style="font-size:11px;color:var(--muted)">{sub}</div></div>')

    chips = []
    if isinstance(it_total, (int, float)):
        chips.append(_tot_chip("Invoice total", f"£{it_total:,.2f}",
                               "ex-VAT · billed by supplier", "#F26A21"))
    if isinstance(sale_total, (int, float)):
        chips.append(_tot_chip("Sale total (to us)", f"£{sale_total:,.2f}",
                               "what the customer pays us", "#16a34a"))
    if isinstance(mt, (int, float)):
        chips.append(_tot_chip("Monday total", f"£{mt:,.2f}",
                               "all invoices on the order (INV1–5)", "#6b7280"))
    if chips:
        st.markdown('<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 12px">'
                    + "".join(chips) + "</div>", unsafe_allow_html=True)

    # Heads-up when the order is split across several invoices/credit notes — the order
    # margin below is for the WHOLE order, so don't read this one invoice in isolation.
    n_inv = inv.get("n_invoices") or 0
    if n_inv >= 2:
        st.markdown(
            f'<div style="display:inline-flex;align-items:center;gap:7px;background:#fff7ed;'
            f'border:1px solid #fed7aa;color:#9a3412;font-weight:700;font-size:13px;'
            f'padding:6px 12px;border-radius:999px;margin:2px 0 8px">&#129534; MULTIPLE INVOICES '
            f'— order {inv.get("order_no") or "?"} has {n_inv} invoices/credit notes. The order '
            f'margin below covers all of them; check they aren\'t duplicated.</div>',
            unsafe_allow_html=True)

    # Live order margin from Monday (whole order, across all its invoices/credit
    # notes) — the safeguard against approving a duplicate or extra invoice.
    live = inv.get("order_margin_live")
    if live is not None:
        lcol = "#dc2626" if live < 15.01 else "#ea580c" if live <= 18 else "#16a34a"
        warn = ""
        if live < 15.01:
            warn = ('<div style="font-size:13px;color:#dc2626;font-weight:600;margin-top:5px">'
                    '&#9888; Below target — check for a duplicate or extra invoice / credit note '
                    'on this order before approving.</div>')
        st.markdown(
            f'<div style="background:var(--card);border:1px solid var(--line);border-left:6px solid '
            f'{lcol};border-radius:8px;padding:11px 16px;margin:4px 0 8px">'
            f'<div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">'
            f'<span style="font-size:12px;font-weight:800;color:var(--muted);'
            f'text-transform:uppercase;letter-spacing:.6px">Order margin · Monday (live)</span>'
            f'<span style="font-size:24px;font-weight:800;color:{lcol};line-height:1">'
            f'{live:.1f}%</span></div>'
            f'<div style="font-size:12px;color:var(--muted);margin-top:2px">the whole order on '
            f'Monday, across all its invoices &amp; credit notes</div>'
            f'{warn}</div>', unsafe_allow_html=True)

    dval = inv.get("_discount")
    if dval and dval > 0:
        st.warning(f"Customer used a discount on this Shopify order: £{dval:,.2f} — this lowers "
                   f"the order margin.")

    if om:
        cov = "" if om["matched"] == om["total"] else f" · {om['matched']}/{om['total']} lines priced"
        col = "#16a34a" if om["margin"] >= 18 else "#ea580c" if om["margin"] >= 0 else "#dc2626"
        st.markdown(
            f'<div style="font-size:13.5px;margin:2px 0 8px;color:var(--muted)">Invoice margin '
            f'(this invoice only): <b style="color:{col}">{om["margin"]:.0f}%</b> — sell '
            f'£{om["rev"]:,.2f} vs cost £{om["cost"]:,.2f} ex-VAT{cov}</div>',
            unsafe_allow_html=True)

    agreed = inv.get("agreed_cost")
    if agreed is not None:
        extra = f" · invoice total £{it_total:,.2f}" if isinstance(it_total, (int, float)) else ""
        st.caption(f"Agreed price at point of ordering (Monday £ to Supplier): £{agreed:,.2f}{extra}")

    badge = {"price": "#ef4444", "qty": "#ea580c", "notorder": "#ef4444",
             "noprice": "#94a3b8", "delivery": "#ea580c", "name": "#16a34a"}
    td = "padding:9px 12px;vertical-align:top"
    rows = ""
    for l in res["lines"]:
        u = f"£{l['unit']:,.2f}" if isinstance(l["unit"], (int, float)) else "—"
        c = f"£{l['cost']:,.2f}" if isinstance(l["cost"], (int, float)) else "—"
        flags = "".join(
            f'<span style="display:inline-block;background:{badge.get(t, "#94a3b8")};color:#fff;'
            f'border-radius:4px;padding:2px 8px;font-size:11.5px;font-weight:600;'
            f'margin:1px 4px 1px 0">{_esc(msg)}</span>'
            for t, msg in l["issues"]) or (
            f'<span style="display:inline-flex;align-items:center;gap:5px;color:#16a34a;'
            f'font-weight:700;font-size:12.5px"><img src="{_INV_ICON["check"]}" '
            f'style="width:16px;height:16px"> OK</span>')
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="{td}"><b style="font-size:13.5px">{_esc(l["sku"] or "—")}</b>'
                 f'<div style="color:var(--muted);font-size:12px;margin-top:1px">'
                 f'{_esc((l.get("desc") or "")[:70])}</div></td>'
                 f'<td style="{td};text-align:center">{l["qty"] if l["qty"] is not None else "—"}</td>'
                 f'<td style="{td};text-align:right">{u}</td>'
                 f'<td style="{td};text-align:right">{c}</td>'
                 f'<td style="{td}">{flags}</td></tr>')
    th = ('color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;'
          'letter-spacing:.4px;padding:8px 12px')
    st.markdown(
        '<table style="width:100%;border-collapse:collapse;font-size:13.5px;'
        'border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:2px 0 10px">'
        f'<tr style="background:var(--card);text-align:left">'
        f'<th style="{th}">SKU</th><th style="{th};text-align:center">Qty</th>'
        f'<th style="{th};text-align:right">Invoiced</th>'
        f'<th style="{th};text-align:right">Pricelist</th>'
        f'<th style="{th}">Check</th></tr>' + rows + "</table>",
        unsafe_allow_html=True)

    # Two explicit checks, shown as cards so it's clear both ran (order + price).
    def _check_card(title, status, color, icon, msg):
        return (f'<div style="flex:1;min-width:250px;background:var(--card);'
                f'border:1px solid var(--line);border-left:5px solid {color};border-radius:7px;'
                f'padding:10px 14px">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">'
                f'<img src="{_INV_ICON[icon]}" style="width:18px;height:18px">'
                f'<span style="font-weight:800;font-size:13.5px">{title}</span>'
                f'<span style="margin-left:auto;font-size:11px;font-weight:800;color:{color};'
                f'text-transform:uppercase;letter-spacing:.5px">{_esc(status)}</span></div>'
                f'<div style="font-size:13px;color:var(--ink);line-height:1.4">{_esc(msg)}</div></div>')

    order = _order_candidates(inv)  # same source the check used (live Shopify, else Monday)
    onum = inv.get("order_no") or "?"
    qmiss = [l for l in res["lines"] if any(t in ("qty", "notorder") for t, _ in l["issues"])]
    missing = res.get("missing") or []
    short = res.get("short") or {}
    n_total = inv.get("n_invoices") or 1
    qtxt = (f"{len(qmiss)} invoice line{'s' if len(qmiss) != 1 else ''} "
            f"{'do not' if len(qmiss) != 1 else 'does not'} match the order (wrong item or over-quantity)")
    miss_str = ", ".join(missing)

    # Reconcile invoiced quantities across ALL of the order's checked invoices (split deliveries).
    rec_status, rec_detail = _order_reconcile(onum)
    still_short = [f"{d['sku']} (invoiced {int(round(d['invoiced']))} of {d['ordered']})"
                   for d in rec_detail.values() if d["short"] > 0]

    if qmiss:
        # Wrong item, or over-invoiced on THIS invoice → a real discrepancy.
        parts = [qtxt]
        if missing:
            parts.append(f"{len(missing)} ordered item{'s' if len(missing) != 1 else ''} not on "
                         f"this invoice ({miss_str})")
        oc = ("Order check", "Review", "#dc2626", "warn", f"Order {onum}: " + "; ".join(parts) + ".")
    elif rec_status == "over":
        # Across the order's invoices you've been billed for MORE than was ordered.
        overs = [f"{d['sku']} (invoiced {int(round(d['invoiced']))} vs order {d['ordered']})"
                 for d in rec_detail.values() if d["invoiced"] > d["ordered"] + 0.001]
        oc = ("Order check", "Over-invoiced across invoices", "#dc2626", "warn",
              f"Order {onum}: across its {n_total} invoices you've been invoiced MORE than ordered "
              f"— {', '.join(overs)}. Review.")
    elif not missing and not short:
        oc = ("Order check", "Match", "#16a34a", "check",
              f"All {len(order)} order line(s) match order {onum} on SKU & quantity.")
    elif rec_status == "exact":
        # Missing/short on THIS invoice, but the order's invoices TOGETHER cover it exactly.
        oc = ("Order check", "Complete across invoices", "#16a34a", "check",
              f"This invoice is partial, but ALL of order {onum}'s items and quantities are "
              f"invoiced across its {n_total} invoices — reconciled, fine to approve.")
    else:
        # UNDER-delivered — nothing wrong, just short of the order (email hello@ to chase).
        sh = "; ".join(still_short) if still_short else (miss_str or "some items")
        if n_total >= 2:
            oc = ("Order check", "Under-delivered (reconciled)", "#ea580c", "invoice",
                  f"Order {onum}'s {n_total} invoices together are still SHORT of the order — {sh}. "
                  "Nothing over-invoiced or wrong, so approvable; email hello@ so the team can chase "
                  "the rest (this is a further delivery).")
        else:
            oc = ("Order check", "Under-delivered — chase rest", "#ea580c", "invoice",
                  f"This invoice is short of order {onum} — {sh}. Prices are right, so approve for "
                  "what's been delivered and email hello@ so the team can chase the rest.")

    sup = inv.get("supplier") or "supplier"
    is_d8 = _is_decor8(_norm_code(inv.get("supplier")))
    # Decor8 aren't checked against a cost pricelist — they're checked vs OUR own price less
    # ~12%. Word the card accordingly (and 'couldn't check' = no Shopify sell price on file).
    ref = "our price less ~12%" if is_d8 else f"{sup}'s pricelist"
    nocost_why = ("that Shopify order line has no price to compare against"
                  if is_d8 else "no pricelist cost found")
    if SUPPLIER_RULES.get(_norm_code(inv.get("supplier")), {}).get("no_pricelist"):
        pc = ("Price check", "Not checked", "#6b7280", "invoice",
              f"No pricelist held for {sup} — the order margin is the reference (not flagged).")
    else:
        priced = [l for l in res["lines"] if isinstance(l.get("cost"), (int, float))]
        pissues = [l for l in priced if any(t == "price" for t, _ in l["issues"])]
        nopl = [l for l in res["lines"] if any(t == "noprice" for t, _ in l["issues"])]
        if not priced:
            pc = ("Price check", "Not checked", "#ea580c", "warn",
                  (f"Couldn't check any line vs {ref} — {nocost_why}." if is_d8
                   else f"No {sup} pricelist cost found — price not checked. Add {sup}'s pricelist."))
        elif pissues:
            pc = ("Price check", "Over" if not is_d8 else "Under discount", "#dc2626", "warn",
                  (f"{len(pissues)} line(s) got less than the expected discount off our price."
                   if is_d8 else f"{len(pissues)} line(s) invoiced above {sup}'s pricelist."))
        elif nopl:
            pc = ("Price check", "Partly checked", "#ea580c", "warn",
                  f"{len(priced)} line(s) match {ref}, but {len(nopl)} couldn't be "
                  f"checked — {nocost_why}. Review those before approving.")
        else:
            pc = ("Price check", "Match", "#16a34a", "check",
                  f"All {len(priced)} line(s) match {ref}.")

    st.markdown('<div style="display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 8px">'
                + _check_card(*oc) + _check_card(*pc) + "</div>", unsafe_allow_html=True)

    # Recommendation + write-back to Monday's Payment Status.
    st.write("")
    is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
    push_label = CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL
    rule = SUPPLIER_RULES.get(_norm_code(inv.get("supplier")), {})
    has_disc = bool(inv.get("_discount"))
    lo = rule.get("push_min", _thresholds()[0])
    if has_disc and rule.get("push_min_discount") is not None:
        lo = rule["push_min_discount"]
    hi = _thresholds()[1]
    _label, action = _push_decision(matched, is_cn, live, inv.get("supplier"),
                                    has_discount=has_disc)
    livetxt = f"{live:.1f}%" if live is not None else "—"
    disc_note = (" (discount code used → floor lowered)"
                 if has_disc and rule.get("push_min_discount") is not None else "")
    if action == "push":
        rec, head, col = "push", "READY TO APPROVE", "#16a34a"
        msg = f"Fully matched and order margin {livetxt} — ready to push to QuickBooks."
    elif action == "flag" and live is not None and live > hi:
        rec, head, col = "disc", "FLAG — CHECK FIRST", "#dc2626"
        msg = (f"Matched, but order margin {livetxt} is unusually high (>{hi:.0f}%) — likely a "
               "missing invoice or credit note. Flag it and check before pushing.")
    elif action == "flag":
        rec, head, col = "disc", "REVIEW — BELOW MARGIN", "#dc2626"
        msg = (f"Matched, but order margin {livetxt} is below the {lo:.0f}% floor{disc_note} — "
               "review as a discrepancy before approving.")
    elif action == "hold":
        rec, head, col = "hold", "HOLD — REVIEW", "#ea580c"
        if rule.get("no_pricelist"):
            mtxt = f"order margin {livetxt}" if live is not None else "the order margin couldn't be read"
            msg = (f"Matched ({mtxt}, at/under {lo:.0f}%) — held as Matched. Consider raising the "
                   "selling price on the website to improve the margin.")
        else:
            mtxt = (f"order margin {livetxt} is below {lo:.0f}%" if live is not None
                    else "the order margin couldn't be read")
            msg = f"Matched, but {mtxt} — review before pushing. Holding as Matched is recommended."
    else:
        rec, head, col = "disc", "DISCREPANCY", "#dc2626"
        msg = "Discrepancy found (see above) — flag it, or fix it on Monday and re-check."
    st.markdown(
        f'<div style="background:var(--card);border:1px solid var(--line);border-left:6px solid '
        f'{col};border-radius:8px;padding:12px 16px;margin:4px 0 10px">'
        f'<div style="font-size:13px;font-weight:800;color:{col};text-transform:uppercase;'
        f'letter-spacing:1px">{head}</div>'
        f'<div style="font-size:14px;color:var(--ink);margin-top:3px;line-height:1.4">'
        f'{_esc(msg)}</div></div>', unsafe_allow_html=True)
    ca, cb, cc = st.columns(3)
    _sid, _no = inv["sub_id"], inv.get("invoice_no")
    # The Push button is ALWAYS available for a fully-matched invoice, even when the margin is
    # below the auto-push floor (rec == "hold"). Holding is only a *suggestion* — the final call
    # is yours, so a matched invoice always gets the clear green Push button.
    push_primary = rec == "push" or (matched and rec != "disc")
    ca.button("Push credit note to QB" if is_cn else "Push to QB",
              key=f"push_{_sid}", use_container_width=True,
              type=("primary" if push_primary else "secondary"),
              on_click=_queue_action, args=(_sid, push_label, _no),
              help="Approves this invoice and pushes it to QuickBooks. Always available for a "
                   "matched invoice — the HOLD/FLAG note above is only advice, not a lock.")
    cb.button("Mark Matched (hold)", key=f"matched_{_sid}", use_container_width=True,
              type=("primary" if rec == "hold" else "secondary"),
              on_click=_queue_action, args=(_sid, MATCHED_LABEL, _no))
    cc.button("Flag discrepancy", key=f"disc_{_sid}", use_container_width=True,
              type=("primary" if rec == "disc" else "secondary"),
              on_click=_flag_discrepancy, args=(_sid, _no, _discrepancy_reason(inv, res)))
    if matched and rec != "push":
        st.caption("↑ This invoice matches the order and pricelist, so you can **Push to QB** "
                   "whenever you're happy with it — even if the margin note suggests holding.")

    # Under-delivered order → tell the team (hello@) to chase the rest. Not a supplier query,
    # and it does NOT flag the invoice — the invoice stays approvable.
    if rec_status == "under":
        subh = inv["sub_id"]
        if st.toggle("Email hello@ that this order is under-delivered (chase the rest)",
                     key=f"udtog_{subh}"):
            usubj, ubody = _underdelivery_email(inv, rec_detail, n_total)
            st.session_state.setdefault(f"udto_{subh}", HELLO_MAILBOX)
            st.session_state.setdefault(f"udsub_{subh}", usubj)
            st.session_state.setdefault(f"udbod_{subh}", ubody)
            st.text_input("To", key=f"udto_{subh}")
            st.text_input("Subject", key=f"udsub_{subh}")
            st.text_area("Message", key=f"udbod_{subh}", height=200)
            st.caption(f"Sends from {SUPPLIER_FROM_MAILBOX} to the team so they can chase the "
                       "outstanding items. Falls back to a draft if sending isn't enabled yet. "
                       "This does NOT flag the invoice — it stays approvable.")
            if st.button("Send to hello@", key=f"udsend_{subh}", type="primary",
                         disabled=not st.session_state.get(f"udto_{subh}", "").strip()):
                to = st.session_state[f"udto_{subh}"].strip()
                subj, body = st.session_state[f"udsub_{subh}"], st.session_state[f"udbod_{subh}"]
                pdf_url = (data_sources.monday_asset_url(inv["asset_id"])
                           if inv.get("asset_id") else None)
                sent = drafted = False
                dlink = None
                try:
                    data_sources.send_supplier_email(SUPPLIER_FROM_MAILBOX, to, subj, body,
                                                     pdf_url=pdf_url)
                    sent = True
                except Exception:  # noqa: BLE001
                    try:
                        dlink = data_sources.create_supplier_draft(SUPPLIER_FROM_MAILBOX, to, subj,
                                                                   body, pdf_url=pdf_url)
                        drafted = True
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't send or draft: " + str(e)[:200])
                if sent or drafted:
                    link = f" [Open the draft]({dlink})" if dlink else ""
                    st.session_state["inv_flash"] = (
                        f"Under-delivery note {'sent to' if sent else 'drafted for'} {to}"
                        + ("" if sent else " (sending needs Mail.Send)") + "." + link)
                    st.rerun()

    # Chase the supplier by email (discrepancies only) — saves to Outlook Drafts.
    if res["n_issues"] > 0:
        sub = inv["sub_id"]
        if st.toggle("Email the supplier about this", key=f"emailtog_{sub}"):
            subj0, body0 = _discrepancy_email(inv, res)
            _supn = _norm_code(inv.get("supplier"))
            _mapped = SUPPLIER_EMAILS.get(_supn)
            if _supn == "eurocell":
                # Eurocell: the branch that raised the invoice + Karla Turner (area contact).
                _branch = (parsed.get("branch_email") or inv.get("supplier_email") or "").strip()
                default_to = ", ".join(dict.fromkeys([e for e in (_branch, _mapped) if e]))
            else:
                default_to = _mapped or inv.get("supplier_email") or ""
            st.session_state.setdefault(f"eto_{sub}", default_to)
            st.session_state.setdefault(f"esub_{sub}", subj0)
            st.session_state.setdefault(f"ebod_{sub}", body0)
            st.session_state.setdefault(f"enote_{sub}", _discrepancy_note(inv, res))
            st.text_input("To", key=f"eto_{sub}")
            st.text_input("Subject", key=f"esub_{sub}")
            st.text_area("Message", key=f"ebod_{sub}", height=230)
            st.text_area("Monday note (awaiting credit note)", key=f"enote_{sub}", height=80,
                         help="Saved to the invoice's note column on Monday when you send. "
                              "Includes the expected credit-note total.")
            st.caption(f"**Sends** the email to the supplier (PDF attached) from "
                       f"{SUPPLIER_FROM_MAILBOX}, writes the note to Monday, and marks the invoice "
                       "**Discrepancy**. If sending isn't permitted yet it falls back to a draft.")
            if not inv.get("supplier_email"):
                st.caption("No supplier email on this order in Monday — type one in above.")
            if st.button("Send to supplier & flag", key=f"esend_{sub}", type="primary",
                         disabled=not st.session_state.get(f"eto_{sub}", "").strip()):
                to = st.session_state[f"eto_{sub}"].strip()
                subj, body = st.session_state[f"esub_{sub}"], st.session_state[f"ebod_{sub}"]
                pdf_url = (data_sources.monday_asset_url(inv["asset_id"])
                           if inv.get("asset_id") else None)
                pdf_name = inv.get("file_name") or f"invoice-{inv.get('invoice_no')}.pdf"
                sent = drafted = False
                draft_link = None
                try:
                    data_sources.send_supplier_email(SUPPLIER_FROM_MAILBOX, to, subj, body,
                                                     pdf_url=pdf_url, pdf_name=pdf_name)
                    sent = True
                except Exception:  # noqa: BLE001 — sending blocked (no Mail.Send)? fall back to draft
                    try:
                        draft_link = data_sources.create_supplier_draft(
                            SUPPLIER_FROM_MAILBOX, to, subj, body, pdf_url=pdf_url, pdf_name=pdf_name)
                        drafted = True
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't send or draft the email: " + str(e)[:200]
                                 + f" — the app needs Mail.Send (to send) or Mail.ReadWrite (to "
                                 f"draft) for {SUPPLIER_FROM_MAILBOX}.")
                if sent or drafted:
                    # Record it on Monday: the note, the 'Queried' marker, and Discrepancy status.
                    try:
                        data_sources.set_subitem_text(
                            sub, "text_mm3gh2za", st.session_state[f"enote_{sub}"].strip())
                        try:
                            data_sources.set_subitem_text(
                                sub, "text_mm3gjrap",
                                f"Queried {inv.get('supplier') or 'supplier'} "
                                f"{datetime.now(UK_TZ):%d %b %Y}")
                        except Exception:  # noqa: BLE001
                            pass
                        data_sources.set_invoice_status(sub, DISCREPANCY_LABEL)
                        st.session_state.setdefault("inv_gone", set()).add(str(sub))
                        for kk in ("review", "matched", "recent", "discrepancy"):
                            st.session_state.pop(f"sel_{kk}", None)
                        if sent:
                            st.session_state["inv_flash"] = (
                                f"Sent to {to} from {SUPPLIER_FROM_MAILBOX}. Noted on Monday and "
                                "marked Discrepancy.")
                        else:
                            link = f" [Open the draft]({draft_link})" if draft_link else ""
                            st.session_state["inv_flash"] = (
                                f"Sending isn't enabled yet (needs Mail.Send) — saved a DRAFT to "
                                f"{SUPPLIER_FROM_MAILBOX} Drafts for you to send. Noted on Monday "
                                f"and marked Discrepancy.{link}")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"Email {'sent' if sent else 'drafted'} to {to}, but couldn't "
                                   "fully update Monday: " + str(e)[:180]
                                   + " — set the status/note manually if needed.")


def _queue_action(sub_id, label, inv_no):
    """Button on_click callback — stash a Push/Matched/Flag action. Callbacks ALWAYS fire on
    click (unlike an 'if st.button(): …' inside the dynamically-rendered detail panel, which
    can miss a click and need pressing twice). Applied at the top of the next render."""
    st.session_state["inv_action"] = ("status", str(sub_id), label, inv_no)


def _queue_delete(sub_id, inv_no):
    """on_click callback to delete a (duplicate) subitem from Monday."""
    st.session_state["inv_action"] = ("delete", str(sub_id), None, inv_no)


def _flag_discrepancy(sub_id, inv_no, reason):
    """on_click: flag as Discrepancy AND persist the reason to Monday so the Discrepancy log
    can show it later without re-checking the invoice."""
    st.session_state["inv_action"] = ("status", str(sub_id), DISCREPANCY_LABEL, inv_no)
    st.session_state["inv_disc_note"] = (str(sub_id), reason)


def _refresh_invoices():
    """on_click: pull fresh data from Monday — clears the cache and the optimistic-hide set."""
    invoices_by_status.clear()
    invoice_count.clear()
    st.session_state.pop("inv_gone", None)


def _ss_set(key, val=True):
    st.session_state[key] = val


def _ss_pop(key):
    st.session_state.pop(key, None)


def _confirm_delete(sub_id, inv_no, pend_key, inv=None):
    st.session_state.pop(pend_key, None)
    _queue_delete(sub_id, inv_no)
    # Also blank the duplicate's amount from the order's INV1..INV5 columns (like the bulk
    # dedup) so the order total isn't double-counted after the subitem is deleted.
    if inv and inv.get("order_item_id") and isinstance(inv.get("total"), (int, float)):
        st.session_state["inv_del_clear"] = (
            inv["order_item_id"], inv["total"], dict(inv.get("inv_columns") or {}))


def _incomplete_note_if_approved(sub_id, label):
    """When an INCOMPLETE invoice is approved (pushed to QB), record on Monday (text_mm51m8ee)
    that it's incomplete and which ordered items to expect on a further invoice."""
    if label not in (APPROVED_QB_LABEL, CN_APPROVED_QB_LABEL):
        return
    v = st.session_state.get("inv_verdict", {}).get(str(sub_id)) \
        or st.session_state.get("inv_verdict", {}).get(sub_id) or {}
    if v.get("incomplete") and v.get("missing"):
        try:
            data_sources.set_subitem_text(
                sub_id, "text_mm51m8ee",
                "Incomplete invoice — expect a further invoice for: " + ", ".join(v["missing"]))
        except Exception:  # noqa: BLE001
            pass


def _process_pending_action():
    """Apply a queued action to Monday at the very top of the Invoice Check render, so a single
    click always lands. Uses OPTIMISTIC hide (drop the invoice from the view immediately) rather
    than wiping the whole Monday cache and re-fetching every page — that's what made each action
    feel slow. The cache still refreshes on its TTL or the manual Refresh button."""
    act = st.session_state.pop("inv_action", None)
    disc = st.session_state.pop("inv_disc_note", None)
    del_clear = st.session_state.pop("inv_del_clear", None)
    if not act:
        return
    kind, sub_id, label, inv_no = act
    try:
        if kind == "delete":
            data_sources.delete_subitem(sub_id)
            extra = ""
            if del_clear:
                pid, amt, cols = del_clear
                col = next((c for c, v in cols.items()
                            if isinstance(v, (int, float)) and abs(v - amt) <= 0.01), None)
                if col:
                    try:
                        data_sources.set_order_number(pid, col, None)
                        extra = " and cleared its INV column"
                    except Exception:  # noqa: BLE001
                        pass
            msg = f"Deleted duplicate invoice {inv_no} from Monday{extra}."
        else:
            data_sources.set_invoice_status(sub_id, label)
            _incomplete_note_if_approved(sub_id, label)
            # Persist the discrepancy reason so the Discrepancy log shows it without a re-check.
            if disc and disc[0] == str(sub_id) and disc[1]:
                try:
                    data_sources.set_subitem_text(sub_id, "text_mm3gh2za", disc[1][:1500])
                except Exception:  # noqa: BLE001
                    pass
            msg = f"Invoice {inv_no} marked “{label}”."
        st.session_state.setdefault("inv_gone", set()).add(str(sub_id))   # hide instantly
        for kk in ("review", "matched", "recent", "discrepancy"):
            st.session_state.pop(f"sel_{kk}", None)                       # reset row selections
        st.session_state["inv_flash"] = msg
    except Exception as e:  # noqa: BLE001
        st.session_state["inv_flash_err"] = "Couldn't update Monday: " + str(e)[:200]


def _dup_identity(i):
    """Identity for exact-duplicate detection: the SAME supplier + invoice number + total is the
    same invoice logged twice — a duplicate — WHATEVER order it's filed under (the number no
    longer has to share an order). Including the total protects a genuine invoice that spans two
    orders (same number, but a different amount on each) from being treated as a duplicate."""
    no = (i.get("invoice_no") or "").strip().upper()
    t = i.get("total")
    return (_norm_code(i.get("supplier")), no, round(t, 2) if isinstance(t, (int, float)) else None)


def _auto_dedup(invs, tol=0.01):
    """Remove duplicate invoices before checking (Eurocell send two copies of each). When 2+
    subitems share the SAME supplier + invoice number + total, keep the first and DELETE the
    rest from Monday — AND blank the duplicate's amount from the order's INV1..INV5 columns so
    the order total isn't double-counted. Returns (kept, n_deleted, n_cleared)."""
    seen, kept, dups = {}, [], []
    for i in invs:
        no = (i.get("invoice_no") or "").strip().upper()
        k = _dup_identity(i)
        if no and k in seen:
            dups.append(i)                 # a later copy of an already-seen invoice
        else:
            if no:
                seen[k] = i
            kept.append(i)
    if not dups:
        return invs, 0, 0
    gone = st.session_state.setdefault("inv_gone", set())
    order_state, deleted, cleared = {}, 0, 0
    for d in dups:
        try:
            data_sources.delete_subitem(d.get("sub_id"))
        except Exception:  # noqa: BLE001
            continue
        deleted += 1
        gone.add(str(d.get("sub_id")))
        # Clear ONE INV column on the parent that holds this duplicate's amount (leaving the
        # original's copy intact). Track per-order so a 3rd copy clears a different column.
        pid, amt = d.get("order_item_id"), d.get("total")
        if pid and isinstance(amt, (int, float)):
            cols = order_state.setdefault(pid, dict(d.get("inv_columns") or {}))
            col = next((c for c, v in cols.items()
                        if isinstance(v, (int, float)) and abs(v - amt) <= tol), None)
            if col:
                try:
                    data_sources.set_order_number(pid, col, None)
                    cols[col] = None
                    cleared += 1
                except Exception:  # noqa: BLE001
                    pass
    return kept, deleted, cleared


def _amount_dup_ids(invs):
    """sub_ids of invoices that share the SAME order + SAME total as another invoice with a
    DIFFERENT invoice number — a likely double-invoice (e.g. Decor8 billing one order twice
    under two numbers). NOT auto-deleted (different numbers ⇒ could rarely be legit, so it's
    flagged for a human). Returns {sub_id: other_invoice_no}."""
    from collections import defaultdict
    groups = defaultdict(list)
    for i in invs:
        t = i.get("total")
        if isinstance(t, (int, float)) and (i.get("order_no") or "").strip():
            groups[(i.get("order_no"), round(t, 2))].append(i)
    out = {}
    for g in groups.values():
        nums = {(x.get("invoice_no") or "").strip().upper() for x in g if x.get("invoice_no")}
        if len(g) >= 2 and len(nums) >= 2:            # 2+ invoices, same £, different numbers
            for x in g:
                others = [y.get("invoice_no") for y in g if y.get("sub_id") != x.get("sub_id")]
                out[str(x["sub_id"])] = next((o for o in others if o), "another invoice")
    return out


def _read_pdf_plain(asset_id):
    """Read + parse an invoice PDF with NO Streamlit cache — safe to call from worker threads
    (st.cache_data isn't). Bulk-check uses this to read many PDFs in parallel."""
    try:
        url = data_sources.monday_asset_url(asset_id)
        if not url:
            return {"error": "Couldn't get a download link for the PDF."}
        return data_sources.read_invoice_pdf(url)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _bulk_check(invs, lbsku):
    """De-duplicate (delete Eurocell's second copy + clear its INV column), then read +
    3-way check every remaining invoice (cached) and auto-process: fully matched with order
    margin ≥5% → pushed to QB; matched but below 5% → held as Matched; discrepancies left
    for review. Reruns when done."""
    invs, n_dup, n_col = _auto_dedup(invs)
    amt_dups = _amount_dup_ids(invs)                  # same order + same £, different inv no
    dupflag = 0
    pidx = _pricelist_index()
    n = len(invs)
    _, hi = _thresholds()
    goneset = st.session_state.setdefault("inv_gone", set())
    # Read the invoice PDFs in PARALLEL up front (the slow AI step) — the big speed-up vs
    # reading one at a time. Cached per session by asset id, so a re-run is instant.
    pcache = st.session_state.setdefault("_inv_pdf_cache", {})
    need = [inv for inv in invs if str(inv["sub_id"]) not in amt_dups
            and inv.get("asset_id") and inv["asset_id"] not in pcache]
    if need:
        import concurrent.futures as _cf
        with st.spinner(f"Reading {len(need)} invoice(s) in parallel…"):
            with _cf.ThreadPoolExecutor(max_workers=6) as _ex:
                for _aid, _p in _ex.map(
                        lambda iv: (iv["asset_id"], _read_pdf_plain(iv["asset_id"])), need):
                    pcache[_aid] = _p
    prog = st.progress(0.0, text="Checking…")
    pushed = held = flagged = unmatched = fail = 0
    # Pass 1 — read + 3-way check EVERYTHING first, so a multi-invoice order is fully reconciled
    # across its invoices before any push decision is made (a split delivery that sums to the
    # order is matched; one that sums to MORE is caught as over-invoiced).
    checked = []
    for i, inv in enumerate(invs, 1):
        # Suspected double-invoice (same order + same £ as another invoice, different number).
        # Never auto-approve/hold it — leave it in Needs Review with a note.
        if str(inv["sub_id"]) in amt_dups:
            dupflag += 1
            try:
                data_sources.set_subitem_text(
                    inv["sub_id"], "text_mm3gh2za",
                    f"POSSIBLE DUPLICATE — same £{inv.get('total')} as invoice "
                    f"{amt_dups[str(inv['sub_id'])]} on this order (different invoice number). "
                    "Check you're not paying twice before approving.")
            except Exception:  # noqa: BLE001
                pass
            continue
        parsed = pcache.get(inv.get("asset_id")) or {"error": "no PDF attached"}
        if parsed.get("error"):
            fail += 1
            continue
        res, om = _check_and_store(inv, parsed, lbsku, pidx)
        # Fall back to the computed margin when Monday's formula margin is blank, so a fully
        # matched invoice (e.g. Carron) can actually clear the push floor instead of being held.
        if inv.get("order_margin_live") is None and om:
            inv["order_margin_live"] = om["margin"]
        checked.append((inv, parsed, res))
        prog.progress(i / n, text=f"Checked {i}/{n}")
    # Pass 2 — decide with the FINAL reconciled verdicts. Only auto-APPROVE or auto-HOLD; never
    # auto-mark Discrepancy (that's set by hand after you've emailed the supplier).
    verds = st.session_state.get("inv_verdict", {})
    for inv, parsed, res in checked:
        v = verds.get(inv["sub_id"], {})
        matched = res["n_issues"] == 0 and v.get("order") is not False   # reconciled over → not matched
        is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
        label, action = _push_decision(matched, is_cn, inv.get("order_margin_live"),
                                       inv.get("supplier"), has_discount=bool(inv.get("_discount")))
        if action in ("push", "hold"):
            try:
                data_sources.set_invoice_status(inv["sub_id"], label)
                _incomplete_note_if_approved(inv["sub_id"], label)
                goneset.add(str(inv["sub_id"]))
                pushed += action == "push"
                held += action == "hold"
            except Exception:  # noqa: BLE001
                pass
        elif action == "flag":
            flagged += 1
        else:
            unmatched += 1
    prog.empty()
    dupmsg = ""
    if n_dup:
        dupmsg = (f"Deleted {n_dup} duplicate invoice(s)"
                  + (f" and cleared {n_col} INV column(s)" if n_col else "") + ". ")
    dupwarn = (f"⚠ {dupflag} possible duplicate(s) (same £ invoiced twice on an order) held for "
               "you to check. ") if dupflag else ""
    st.session_state["inv_flash"] = (
        dupmsg + dupwarn
        + f"Processed {n}: pushed {pushed} to QB, held {held} as Matched. "
        f"{flagged + unmatched} left in Needs Review for you ({flagged} high margin >{hi:.0f}%, "
        f"{unmatched} to check)"
        + (f", {fail} unreadable" if fail else "")
        + ". Nothing was auto-marked Discrepancy — flag those yourself after emailing the supplier.")
    st.rerun()


# ---------------------------------------------------------------------------
# Invoice check helpers — cached parallel checking + push, shared by the
# selection buttons (Check selected / Push selected), above and below the list.
# ---------------------------------------------------------------------------
def _grid_check(invs, lbsku):
    """Check a list of invoices with cached parallel PDF reads; store verdicts. No pushing.
    Reads are cached 24h, so re-checking an already-seen invoice is free."""
    pidx = _pricelist_index()
    pcache = st.session_state.setdefault("_inv_pdf_cache", {})
    todo = [iv for iv in invs if iv.get("asset_id")]
    need = [iv for iv in todo if iv["asset_id"] not in pcache]
    if need:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=6) as _ex:
            for _aid, _p in _ex.map(
                    lambda iv: (iv["asset_id"], _read_pdf_plain(iv["asset_id"])), need):
                pcache[_aid] = _p
    n = 0
    for iv in todo:
        parsed = pcache.get(iv["asset_id"])
        if parsed and not parsed.get("error"):
            _check_and_store(iv, parsed, lbsku, pidx)
            n += 1
    return n


def _grid_is_matched(sid):
    v = st.session_state.get("inv_verdict", {}).get(sid)
    return bool(v and v.get("order") and v.get("price"))


def _grid_push(inv):
    """Push one already-checked, matched invoice to QuickBooks (Approved / CN Approved)."""
    is_cn = isinstance(inv.get("total"), (int, float)) and inv["total"] < 0
    lbl = CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL
    data_sources.set_invoice_status(inv["sub_id"], lbl)
    _incomplete_note_if_approved(inv["sub_id"], lbl)
    st.session_state.setdefault("inv_gone", set()).add(str(inv["sub_id"]))


def _selection_bar(picked_ids, key, pos):
    """Two selection actions (Check selected / Push selected) shown above AND below the list."""
    n = len(picked_ids)
    b = st.columns([1, 1, 2.4])
    if b[0].button(f"Check selected ({n})", key=f"chksel_{key}_{pos}", disabled=not n,
                   use_container_width=True,
                   help="Reads & checks the ticked invoices (cached reads are free), fills in the "
                        "table columns and opens them below to review."):
        st.session_state[f"do_check_{key}"] = True
    if b[1].button(f"Push selected ({n})", key=f"pushsel_{key}_{pos}", type="primary",
                   disabled=not n, use_container_width=True,
                   help="Checks any not-yet-checked ticked invoices, then pushes the fully-matched "
                        "ones straight to QuickBooks."):
        st.session_state[f"do_push_{key}"] = list(picked_ids)


def _invoice_tab(key, is_queue):
    data = invoices_by_status(key)
    if data.get("error"):
        msg = data["error"]
        if "MONDAY" in msg:
            st.warning("Monday isn't connected: " + msg[:160])
        else:
            st.error(msg[:200])
        return
    invs = data.get("invoices", [])
    gone = st.session_state.get("inv_gone")            # optimistically hidden (just actioned)
    if gone:
        invs = [i for i in invs if str(i.get("sub_id")) not in gone]
    if not invs:
        st.caption("Nothing here right now.")
        return

    suppliers = sorted({i.get("supplier") for i in invs if i.get("supplier")})
    c1, c2 = st.columns([1, 1.4])
    sup = c1.selectbox("Supplier", ["All suppliers"] + suppliers, key=f"sup_{key}")
    q = c2.text_input("Search invoice / order / supplier", key=f"q_{key}").strip().lower()

    def keep(i):
        if sup != "All suppliers" and i.get("supplier") != sup:
            return False
        if q:
            hay = " ".join(str(i.get(x) or "") for x in ("invoice_no", "order_no", "supplier")).lower()
            if q not in hay:
                return False
        return True

    fil = [i for i in invs if keep(i)]
    is_recent = (key == "recent")
    if is_recent:
        # Newest action first, by the FULL status-change timestamp so same-day actions
        # order by time too (falls back to the date if a timestamp is missing).
        fil.sort(key=lambda i: i.get("actioned_at") or i.get("date") or "", reverse=True)
        fil = fil[:60]
        st.caption("The most recently actioned invoices — pushed to QB, held or flagged — "
                   "newest first. Search above to find a specific one.")
    else:
        st.caption(f"{len(fil)} of {len(invs)}{'+' if data.get('more') else ''} invoices "
                   "— tick the ones you want, then use Check / Push selected (above and below "
                   "the list).")
    if not fil:
        st.info("No invoices match that filter/search.")
        return

    # Customer discounts on the Shopify orders (annotate each invoice). Keyed off the
    # rows we'll actually show (fil), so the Recent tab doesn't fan out 800 Shopify calls.
    disc = _order_discounts(tuple(sorted({i["shopify_order_id"] for i in fil
                                          if i.get("shopify_order_id")})))
    for i in fil:
        i["_discount"] = (disc.get(i.get("shopify_order_id")) or {}).get("amount")

    # Duplicate detection: the SAME invoice number logged twice on the SAME order = a
    # duplicate subitem to delete. Counted across this tab PLUS the Discrepancy queue, so a
    # copy sitting in Discrepancy is caught even when we're looking at another tab.
    from collections import Counter as _Counter
    def _dupkey(i):
        return _dup_identity(i)
    dup_pool = {i["sub_id"]: i for i in invs}
    if key != "discrepancy":
        for i in (invoices_by_status("discrepancy").get("invoices") or []):
            dup_pool.setdefault(i["sub_id"], i)
    _dupc = _Counter(_dupkey(i) for i in dup_pool.values() if (i.get("invoice_no") or "").strip())
    _amtdup = _amount_dup_ids(list(dup_pool.values()))   # same order + same £, different number
    for i in fil:
        i["_dup"] = _dupc.get(_dupkey(i), 0) >= 2
        # amount-duplicate (the other invoice's number), unless it's already an exact duplicate
        i["_dup_amt"] = None if i["_dup"] else _amtdup.get(str(i.get("sub_id")))

    # One-click clean-up: exact-duplicate copies (same invoice number logged more than once on
    # an order) can be deleted in one go — keeps one of each, deletes the extras and clears
    # their INV amount. (Bulk-check does this automatically; this is for ones checked one-by-one.)
    _extras = sum(c - 1 for c in _dupc.values() if c >= 2)
    if _extras:
        cda, cdb = st.columns([1, 2])
        if cda.button(f"🗑 Delete {_extras} duplicate cop{'y' if _extras == 1 else 'ies'}",
                      key=f"deldups_{key}", type="primary", use_container_width=True):
            _, ndel, ncol = _auto_dedup(list(dup_pool.values()))
            invoices_by_status.clear()
            invoice_count.clear()
            st.session_state["inv_flash"] = (
                f"Deleted {ndel} duplicate cop{'y' if ndel == 1 else 'ies'} from Monday"
                + (f" and cleared {ncol} INV column(s)" if ncol else "") + ".")
            st.rerun()
        cdb.caption("Removes the extra copy of any invoice logged twice on its order (keeping "
                    "one) and clears its amount from the order total.")

    verdicts = st.session_state.get("inv_verdict", {})

    def _icon_pass(b):  # True → check, False → cross, None → blank
        return _INV_ICON["check"] if b is True else (_INV_ICON["cross"] if b is False else None)

    lbsku = _lookup_by_sku()

    # Bulk-check & auto-process the WHOLE queue (To-check tab only; writes to QB, so confirm).
    # Per-row and ticked-selection actions live in the grid below — this is the "do it all" button.
    if key == "review":
        checkable = [i for i in fil if i.get("asset_id")]
        pend = f"bulk_pending_{key}"
        lo0, hi0 = _thresholds()
        if st.button(f"Bulk-check & auto-process all {len(checkable)}", key=f"bulk_{key}",
                     disabled=not checkable, use_container_width=True,
                     help=f"Checks every invoice shown, then pushes matched invoices (order "
                          f"margin {lo0:.0f}–{hi0:.0f}%) to QuickBooks and holds the rest as "
                          "Matched. Or use the per-row buttons below for full control."):
            st.session_state[pend] = True
        if st.session_state.get(pend):
            n = len(checkable)
            lo, hi = _thresholds()
            st.warning(f"This will check **{n}** invoices (~£{n * 0.01:.2f}–£{n * 0.04:.2f}) and then "
                       f"automatically **push fully-matched invoices with order margin {lo:.0f}–"
                       f"{hi:.0f}% to QuickBooks**, hold under-{lo:.0f}% as Matched (TradeHub), flag "
                       f"over-{hi:.0f}% as a discrepancy, and leave mismatches for review. "
                       "Already-checked reads are free (cached).")
            yc, nc = st.columns([1, 1])
            if yc.button(f"Yes — check & process {n}", key=f"bulkyes_{key}", type="primary",
                         use_container_width=True):
                st.session_state.pop(pend, None)
                _bulk_check(checkable, lbsku)
            if nc.button("Cancel", key=f"bulkno_{key}", use_container_width=True):
                st.session_state.pop(pend, None)
                st.rerun()

    # Selection action buttons appear both ABOVE and BELOW the list.
    top_slot = st.container()

    # ---- the list: all the columns as before, plus a tick column to select rows ----
    rows = []
    for inv in fil:
        v = verdicts.get(inv["sub_id"]) if is_queue else None
        is_cn = isinstance(inv.get("total"), (int, float)) and inv["total"] < 0
        row = {"Type": _INV_ICON["crn_badge"] if is_cn else _INV_ICON["inv_badge"]}
        if is_queue:
            row["Status"] = (_INV_ICON["check"] if (v and v["order"] and v["price"])
                             else _INV_ICON["warn"] if v else None)
        row["Invoice"] = inv.get("invoice_no") or ""
        omark = ("  · DUPLICATE" if inv.get("_dup")
                 else f"  · ×{inv['n_invoices']}" if (inv.get("n_invoices") or 0) >= 2 else "")
        row["Order"] = (inv.get("order_no") or "") + omark
        row["Supplier"] = inv.get("supplier") or ""
        if is_recent:
            row["Result"] = _recent_result(inv.get("status"))
        row["Date"] = inv.get("created") or ""
        row["Inv £"] = inv.get("total")
        if is_queue:
            row["Invoice margin"] = (v or {}).get("margin")
        row["Order margin"] = inv.get("order_margin_live")
        row["Discount"] = inv.get("_discount") if inv.get("_discount") else None
        if is_queue:
            row["vs Shopify"] = _icon_pass(v["order"]) if v else None
            row["vs Pricelist"] = (None if not v else _INV_ICON["qmark"]
                                   if v["price"] is None else _icon_pass(v["price"]))
        if is_recent:
            row["When"] = _fmt_actioned(inv.get("actioned_at"))
        row["PDF"] = inv.get("file_url")
        rows.append(row)

    colcfg = {
        "Type": st.column_config.ImageColumn("Type", width="small", help="Invoice or credit note"),
        "Date": st.column_config.TextColumn("Date", width="small",
                                            help="Invoice date — when it was logged on Monday"),
        "Inv £": st.column_config.TextColumn("Inv £", width="small"),
        "Order margin": st.column_config.NumberColumn(
            format="%.1f%%", width="small",
            help="OVERALL margin for this whole order from Monday — across ALL invoices and credit "
                 "notes relating to the order (catches duplicate/extra invoices)."),
        "Discount": st.column_config.TextColumn(
            "Discount", width="small",
            help="Customer discount used on the Shopify order (reduces margin). Blank = none."),
        "PDF": st.column_config.LinkColumn("PDF", display_text="OPEN", width="small",
                                           help="Open the invoice PDF"),
    }
    if is_recent:
        colcfg["Result"] = st.column_config.TextColumn(
            "Result", width="medium", help="What Trade Hub last did with this invoice")
        colcfg["When"] = st.column_config.TextColumn(
            "When", width="small", help="When this invoice was last actioned")
    if is_queue:
        colcfg["Status"] = st.column_config.ImageColumn("Status", width="small",
                                                        help="Matched or discrepancy")
        colcfg["Invoice margin"] = st.column_config.NumberColumn(
            format="%d%%", width="small",
            help="Margin on THIS individual invoice. Shows once the invoice has been checked.")
        colcfg["vs Shopify"] = st.column_config.ImageColumn(
            "vs Shopify", width="small", help="SKUs & quantities match the order")
        colcfg["vs Pricelist"] = st.column_config.ImageColumn(
            "vs Pricelist", width="small",
            help="Green tick = all line prices match the pricelist. Red cross = a price is wrong. "
                 "Grey ? = couldn't check — treat as a discrepancy to review, NOT a pass.")

    df = pd.DataFrame(rows)
    for c in ("Invoice margin", "Order margin"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("Inv £", "Discount"):        # money → thousands-separated text
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").map(_gbp)
    df.insert(0, "✓", False)
    colcfg["✓"] = st.column_config.CheckboxColumn(
        "Select", width="small", help="Tick invoices, then use Check / Push selected above or below")
    edited = st.data_editor(
        df, hide_index=True, use_container_width=True, key=f"sel_{key}",
        column_config=colcfg, disabled=[c for c in df.columns if c != "✓"])
    ticks = edited["✓"] if "✓" in edited.columns else []
    picked_ids = [fil[i]["sub_id"] for i in range(len(fil)) if bool(ticks.iloc[i])]
    show_key = f"inv_show_{key}"

    if not is_recent:
        # Same two buttons BELOW the list and ABOVE it (into the placeholder made earlier).
        _selection_bar(picked_ids, key, "bot")
        with top_slot:
            _selection_bar(picked_ids, key, "top")
        if not picked_ids:
            st.caption("Tick the invoices you want, then use **Check selected** or **Push "
                       "selected** — the buttons sit both above and below the list.")

        # Check the ticked invoices (cached parallel reads) and open them below to review.
        if st.session_state.pop(f"do_check_{key}", False) and picked_ids:
            sel_invs = [i for i in fil if i["sub_id"] in picked_ids and i.get("asset_id")]
            with st.spinner(f"Checking {len(sel_invs)} invoice(s)…"):
                _grid_check(sel_invs, lbsku)
            st.session_state[show_key] = picked_ids
            st.session_state.pop(f"sel_{key}", None)
            st.rerun()

        # Push the ticked, matched invoices (checking any not yet checked first).
        if st.session_state.get(f"do_push_{key}"):
            ids = st.session_state[f"do_push_{key}"]
            st.warning(f"Push the fully-matched invoices among **{len(ids)}** selected straight to "
                       "QuickBooks? Any not yet checked are checked first (cached reads are free); "
                       "discrepancies are left for you to review.")
            yc, nc = st.columns(2)
            if yc.button("Yes — push matched", key=f"dopushyes_{key}", type="primary",
                         use_container_width=True):
                st.session_state.pop(f"do_push_{key}", None)
                sel_invs = [i for i in fil if i["sub_id"] in ids and i.get("asset_id")]
                with st.spinner("Checking and pushing…"):
                    _grid_check(sel_invs, lbsku)
                    pushed = 0
                    for i in sel_invs:
                        if _grid_is_matched(i["sub_id"]):
                            try:
                                _grid_push(i)
                                pushed += 1
                            except Exception:  # noqa: BLE001
                                pass
                st.session_state.pop(f"sel_{key}", None)
                st.session_state["inv_flash"] = (
                    f"Pushed {pushed} matched invoice(s) to QuickBooks."
                    + (f" {len(ids) - pushed} weren't clean matches — left for review."
                       if pushed < len(ids) else ""))
                st.rerun()
            if nc.button("Cancel", key=f"dopushno_{key}", use_container_width=True):
                st.session_state.pop(f"do_push_{key}", None)
                st.rerun()

    # ---- review panels: opened (via Check selected) + any flagged discrepancies ----
    show_ids = [sid for sid in st.session_state.get(show_key, [])
                if any(i["sub_id"] == sid for i in fil)]

    def _is_disc(sid):
        v = verdicts.get(sid)
        return bool(v) and not (v.get("order") and v.get("price"))

    chosen = [i for i in fil if i["sub_id"] in show_ids]
    flagged = [i for i in fil if is_queue and _is_disc(i["sub_id"]) and i["sub_id"] not in show_ids]
    solo = len(chosen) == 1 and not flagged
    review = [(i, solo) for i in chosen] + [(i, False) for i in flagged[:15]]

    def _outcome_tag(inv):
        v = verdicts.get(inv["sub_id"])
        if not v:
            return "not checked yet"
        if v.get("order") and v.get("price") is not False and v.get("incomplete"):
            return "INCOMPLETE — expect another invoice (approvable)"
        if v.get("order") and v.get("price") is True:
            m = v.get("margin")
            return f"MATCHED — ready to approve{f' · {m}% margin' if m is not None else ''}"
        if v.get("order") and v.get("price") is None:
            return "PRICE NOT CHECKED — review (no pricelist cost)"
        return "DISCREPANCY — review"

    if review:
        st.markdown("##### Review — opened invoices")
        st.caption("Opening a checked invoice is free (cached 24h). Each panel has its own "
                   "Push / Mark matched / Flag buttons.")
        for inv, expanded in review:
            sid = inv["sub_id"]
            expanded = (expanded or bool(st.session_state.get(f"emailtog_{sid}"))
                        or bool(st.session_state.get(f"delpend_{sid}")))
            is_cn = isinstance(inv.get("total"), (int, float)) and inv["total"] < 0
            mark = ("   ·   DUPLICATE" if inv.get("_dup")
                    else f"   ·   ×{inv['n_invoices']}" if (inv.get("n_invoices") or 0) >= 2 else "")
            head = (f"{'CRN' if is_cn else 'INV'}   {inv.get('invoice_no')}   ·   "
                    f"{inv.get('supplier') or '—'}   ·   order {inv.get('order_no') or '—'}"
                    f"{mark}   —   {_outcome_tag(inv)}")
            with st.expander(head, expanded=expanded):
                _run_one_invoice(inv, lbsku)
        if len(flagged) > 15:
            st.caption(f"+{len(flagged) - 15} more discrepancies — filter by supplier to narrow.")


@st.cache_data(ttl=300, show_spinner=False)
def _matched_weekly(days):
    try:
        return {"rows": data_sources.fetch_matched_marked(days=days)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def render_matched_weekly():
    """List every invoice/CN MARKED 'Matched (TradeHub)' in the window — from Monday's
    activity log, so it stays listed even after a colleague moves it on to Approved."""
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Matched — weekly</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.caption("Everything marked **Matched (TradeHub)** in the window, read from Monday's "
               "activity log — so it's still here even after it's been moved on to "
               "**Approved (To QB)**. These fully match the order and pricelist and are due "
               "to be paid.")
    c1, c2 = st.columns([4, 1])
    days = c1.radio("Window", [7, 14, 30], horizontal=True,
                    format_func=lambda d: f"Last {d} days", label_visibility="collapsed")
    if c2.button("↻ Refresh", use_container_width=True):
        _matched_weekly.clear()
        st.rerun()

    d = _matched_weekly(days)
    if d.get("error"):
        st.warning("Couldn't read the activity log: " + d["error"][:200])
        return
    rows = d["rows"]
    if not rows:
        st.success(f"Nothing marked Matched (TradeHub) in the last {days} days.")
        return
    tot = sum(r["total"] for r in rows if isinstance(r.get("total"), (int, float)))
    still = sum(1 for r in rows if "Matched" in (r.get("current_status") or ""))
    st.markdown(f"**{len(rows)}** invoice(s) marked · **£{tot:,.2f}** to suppliers · "
                f"{len(rows) - still} already moved on, {still} still Matched")

    def _pill(s):
        s = s or ""
        col = "#16a34a" if "Approved" in s else "#ea580c" if "Matched" in s else "#6b7280"
        return f'<span style="color:{col};font-weight:600">{_esc(s or "—")}</span>'

    body = "".join(
        '<tr style="border-top:1px solid var(--line)">'
        f'<td style="padding:7px 12px"><b>{_esc(r["invoice_no"] or "—")}</b></td>'
        f'<td style="padding:7px 12px">{_esc(r["order_no"] or "—")}</td>'
        f'<td style="padding:7px 12px">{_esc(r["supplier"] or "—")}</td>'
        f'<td style="padding:7px 12px;text-align:right">'
        f'{("£"+format(r["total"], ",.2f")) if isinstance(r.get("total"), (int, float)) else "—"}</td>'
        f'<td style="padding:7px 12px;font-size:12px">{_esc(r["marked_at"])}</td>'
        f'<td style="padding:7px 12px;font-size:12px">{_esc(r["marked_by"])}</td>'
        f'<td style="padding:7px 12px">{_pill(r["current_status"])}</td></tr>'
        for r in rows)
    head = ('<th style="padding:7px 12px">Invoice</th><th style="padding:7px 12px">Order</th>'
            '<th style="padding:7px 12px">Supplier</th>'
            '<th style="padding:7px 12px;text-align:right">£ to supplier</th>'
            '<th style="padding:7px 12px">Marked</th><th style="padding:7px 12px">By</th>'
            '<th style="padding:7px 12px">Current status</th>')
    st.markdown(_ptable(head, body), unsafe_allow_html=True)

    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["Invoice", "Order", "Supplier", "£ to supplier", "Marked", "By",
                "Current status"])
    for r in rows:
        w.writerow([r["invoice_no"], r["order_no"], r["supplier"], r["total"],
                    r["marked_at"], r["marked_by"], r["current_status"]])
    dl, em = st.columns(2)
    dl.download_button("⬇ Download CSV", buf.getvalue(),
                       file_name=f"matched_last_{days}_days.csv", mime="text/csv",
                       use_container_width=True)
    # Email it to the signed-in user. This creates a DRAFT in their Outlook (Mail.ReadWrite,
    # which works where send is blocked) — they review and press send.
    to_addr = _signed_in_email()
    if em.button(f"📧 Email this list to {to_addr}", use_container_width=True,
                 disabled=not to_addr):
        try:
            subj = f"Matched (TradeHub) — last {days} days: {len(rows)} invoices, £{tot:,.2f}"
            link = data_sources.create_supplier_draft(to_addr, to_addr, subj,
                                                       _matched_email_body(rows, days, tot))
            st.success(f"Draft created in {to_addr}'s Outlook — open **Drafts**, review and "
                       "send it.")
            if link:
                st.markdown(f"[Open the draft in Outlook]({link})")
        except Exception as e:  # noqa: BLE001
            st.error("Couldn't create the draft: " + str(e)[:200])


def _signed_in_email():
    """Email of the signed-in user (from the auth config), for the 'email me this' action."""
    try:
        u = (config.get("credentials", {}).get("usernames", {}).get(username, {}) or {})
        return (u.get("email") or "").strip() or "daniela@tradesuperstoreonline.co.uk"
    except Exception:  # noqa: BLE001
        return "daniela@tradesuperstoreonline.co.uk"


def _matched_email_body(rows, days, tot):
    """Plain-text body listing the marked-Matched invoices, for the email draft."""
    still = sum(1 for r in rows if "Matched" in (r.get("current_status") or ""))
    lines = [
        f"Invoices marked 'Matched (TradeHub)' in the last {days} days.",
        f"{len(rows)} invoice(s) · £{tot:,.2f} to suppliers · "
        f"{len(rows) - still} already moved on to Approved, {still} still Matched.",
        "These fully match the order and pricelist and are due to be paid.",
        "",
        f"{'Invoice':<20}{'Order':<9}{'Supplier':<16}{'£ to sup':>9}  {'Marked':<13}"
        f"{'By':<14}Current status",
        "-" * 96,
    ]
    for r in rows:
        amt = f"£{r['total']:,.2f}" if isinstance(r.get("total"), (int, float)) else "—"
        lines.append(
            f"{str(r.get('invoice_no') or '—')[:19]:<20}{str(r.get('order_no') or '—')[:8]:<9}"
            f"{str(r.get('supplier') or '—')[:15]:<16}{amt:>9}  {str(r.get('marked_at') or ''):<13}"
            f"{str(r.get('marked_by') or '—')[:13]:<14}{r.get('current_status') or ''}")
    lines += ["", "— Sent from Trade Hub · Invoice Check › Matched (weekly)"]
    return "\n".join(lines)


def render_discrepancy_log():
    """A durable list of every invoice TradeHub flagged as a Discrepancy, with the reason
    saved on Monday — so open discrepancies can be worked without re-checking each invoice.
    'Not sent' = the supplier hasn't been queried yet (no Action recorded)."""
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Discrepancies — log</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.caption("Every invoice flagged as a **Discrepancy**, with the reason saved — so you can "
               "see what was wrong **without re-checking**. **Not sent** = the supplier hasn't "
               "been queried yet; **Queried** = a chase email has been drafted.")
    if st.button("↻ Refresh", key="disc_refresh"):
        invoices_by_status.clear()
        st.rerun()
    data = invoices_by_status("discrepancy")
    if data.get("error"):
        st.warning("Couldn't read discrepancies: " + data["error"][:200])
        return
    gone = st.session_state.get("inv_gone", set())
    rows = [r for r in (data.get("invoices") or []) if str(r.get("sub_id")) not in gone]
    if not rows:
        st.success("No open discrepancies. 🎉")
        return
    not_sent = [r for r in rows if not (r.get("action_note") or "").strip()]
    sent = [r for r in rows if (r.get("action_note") or "").strip()]
    tot_ns = sum(r["total"] for r in not_sent if isinstance(r.get("total"), (int, float)))

    def _rowhtml(r, with_action):
        reason = (r.get("query_note") or "").strip() or \
            '<span style="color:var(--muted)">(reason not saved — open the invoice to see)</span>'
        amt = (f"£{r['total']:,.2f}" if isinstance(r.get("total"), (int, float)) else "—")
        cells = [
            f'<td style="padding:7px 12px"><b>{_esc(r.get("invoice_no") or "—")}</b></td>',
            f'<td style="padding:7px 12px">{_esc(r.get("order_no") or "—")}</td>',
            f'<td style="padding:7px 12px">{_esc(r.get("supplier") or "—")}</td>',
            f'<td style="padding:7px 12px;text-align:right">{amt}</td>',
            f'<td style="padding:7px 12px;font-size:12px">'
            f'{reason if reason.startswith("<") else _esc(reason)}</td>',
            f'<td style="padding:7px 12px;font-size:12px">'
            f'{_esc(_fmt_actioned(r.get("actioned_at")))}</td>',
        ]
        if with_action:
            cells.append(f'<td style="padding:7px 12px;font-size:12px;color:#16a34a">'
                         f'{_esc((r.get("action_note") or "").strip())}</td>')
        return '<tr style="border-top:1px solid var(--line)">' + "".join(cells) + "</tr>"

    base_head = ('<th style="padding:7px 12px">Invoice</th><th style="padding:7px 12px">Order</th>'
                 '<th style="padding:7px 12px">Supplier</th>'
                 '<th style="padding:7px 12px;text-align:right">£</th>'
                 '<th style="padding:7px 12px">Reason</th><th style="padding:7px 12px">Flagged</th>')

    st.markdown(f"### ⚠️ Not sent to supplier yet — {len(not_sent)} · £{tot_ns:,.2f}")
    if not_sent:
        st.markdown(_ptable(base_head, "".join(_rowhtml(r, False) for r in not_sent)),
                    unsafe_allow_html=True)
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["Invoice", "Order", "Supplier", "£", "Reason", "Flagged"])
        for r in not_sent:
            w.writerow([r.get("invoice_no"), r.get("order_no"), r.get("supplier"),
                        r.get("total"), r.get("query_note"), _fmt_actioned(r.get("actioned_at"))])
        dl, em = st.columns(2)
        dl.download_button("⬇ Download CSV", buf.getvalue(), file_name="discrepancies_to_send.csv",
                           mime="text/csv", use_container_width=True)
        to_addr = _signed_in_email()
        if em.button(f"📧 Email this list to {to_addr}", use_container_width=True,
                     disabled=not to_addr, key="disc_email"):
            try:
                body = ["Discrepancies TradeHub found that have NOT been sent to the supplier yet.",
                        f"{len(not_sent)} invoice(s) · £{tot_ns:,.2f}.", ""]
                for r in not_sent:
                    a = (f"£{r['total']:,.2f}" if isinstance(r.get("total"), (int, float)) else "—")
                    body.append(f"- {r.get('invoice_no')} (order {r.get('order_no')}, "
                                f"{r.get('supplier')}, {a}): {r.get('query_note') or 'see invoice'}")
                link = data_sources.create_supplier_draft(
                    to_addr, to_addr, f"Discrepancies to send — {len(not_sent)} (£{tot_ns:,.2f})",
                    "\n".join(body))
                st.success(f"Draft created in {to_addr}'s Outlook — review and send from Drafts.")
                if link:
                    st.markdown(f"[Open the draft in Outlook]({link})")
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't create the draft: " + str(e)[:200])
    else:
        st.caption("Everything flagged has been queried with the supplier. 🎉")

    with st.expander(f"Already queried — {len(sent)}"):
        if sent:
            st.markdown(_ptable(base_head + '<th style="padding:7px 12px">Sent</th>',
                                "".join(_rowhtml(r, True) for r in sent)), unsafe_allow_html=True)
        else:
            st.caption("None queried yet.")


def render_invoice_check():
    _process_pending_action()   # apply any queued Push/Matched/Flag before rendering
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Invoice Check</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("inv_margin_min", MARGIN_PUSH_MIN)
    st.session_state.setdefault("inv_margin_max", MARGIN_PUSH_MAX)
    lo, hi = _thresholds()
    st.caption(f"Check supplier invoices from Monday (price vs pricelist, SKUs/qty vs the Shopify "
               f"order, margins). Fully-matched with **order margin {lo:.0f}–{hi:.0f}%** → pushed "
               f"to QuickBooks; **under {lo:.0f}%** → held as Matched; **over {hi:.0f}%** → flagged "
               "(likely a missing invoice/credit). Uses your Anthropic key — pennies per invoice.")

    with st.expander("Auto-push margin thresholds"):
        sa, sb = st.columns(2)
        sa.number_input("Push to QB when order margin is at least (%)", min_value=0.0,
                        max_value=100.0, step=1.0, key="inv_margin_min",
                        help="Below this, a matched invoice is held as Matched for review.")
        sb.number_input("…and no more than (%)", min_value=0.0, max_value=100.0, step=1.0,
                        key="inv_margin_max",
                        help="Above this, a matched invoice is flagged as a discrepancy.")
        st.caption("Applies to single and bulk processing. Resets to 5 / 35 when the app reboots — "
                   "tell me if you'd like different permanent defaults.")

    flash = st.session_state.pop("inv_flash", None)
    if flash:
        st.success(flash)
    flash_err = st.session_state.pop("inv_flash_err", None)
    if flash_err:
        st.error(flash_err)

    # Lightweight counts (id-only) + render ONLY the selected tab — far faster than
    # st.tabs (which builds all four every run) and fetching full data to count.
    tabs = [("review", "To check", True), ("matched", "Matched (held)", True),
            ("recent", "Recent activity", False), ("discrepancy", "Discrepancies", False)]
    if st.session_state.get("inv_tab") not in {k for k, _, _ in tabs}:
        st.session_state["inv_tab"] = "review"

    def _count(k):
        c = invoice_count(k)
        if not c:
            return "—"
        return f"{c['count']}{'+' if c.get('more') else ''}"

    cols = st.columns(len(tabs) + 1)
    for col, (key, label, _q) in zip(cols, tabs):
        active = st.session_state["inv_tab"] == key
        btn_label = label if key == "recent" else f"{label} ({_count(key)})"
        col.button(btn_label, key=f"itab_{key}", use_container_width=True,
                   type="primary" if active else "secondary",
                   on_click=_ss_set, args=("inv_tab", key))
    cols[-1].button("🔄", key="inv_refresh", use_container_width=True,
                    help="Refresh from Monday (pick up new invoices / others' changes)",
                    on_click=_refresh_invoices)
    st.write("")

    active = st.session_state["inv_tab"]
    is_queue = {k: q for k, _, q in tabs}[active]
    _invoice_tab(active, is_queue=is_queue)


SUMMARY_STATUS_COL = {"green": "#10b981", "amber": "#f59e0b", "red": "#ef4444", "info": "#94a3b8"}
SUMMARY_SECTIONS = [("Orders & deliveries", "📦"), ("Customer care", "🤝"), ("Invoices", "🧾")]


def _summary_section(k):
    src = (k.get("source") or "").lower()
    if "outlook" in src:
        return "Emails"
    if "subitem" in src:
        return "Invoices"
    if "shopify" in src or "customer stage" in src:
        return "Customer care"
    return "Orders & deliveries"


def render_summary_dashboard():
    st.markdown(
        f"""<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Daily Ops · Summary</span></span>
        <span class="sct">updated {data.get('updated', '—')}</span></div>""",
        unsafe_allow_html=True)

    active = [k for k in KPIS if not k.get("info")]
    reds = sum(1 for k in active if status_of(k) == "red")
    ambers = sum(1 for k in active if status_of(k) == "amber")
    by_sec = {}
    for k in active:
        by_sec.setdefault(_summary_section(k), []).append(k)
    emails = by_sec.get("Emails", [])
    email_total = sum(k["count"] for k in emails)
    orders_total = sum(k["count"] for k in by_sec.get("Orders & deliveries", []))
    inv_total = sum(k["count"] for k in by_sec.get("Invoices", []))

    head = [("Needs attention", reds + ambers,
             "#ef4444" if reds else "#f59e0b" if ambers else "#10b981"),
            ("Emails outstanding", email_total, "#3b82f6"),
            ("Orders to action", orders_total, "#8b5cf6"),
            ("Invoices to approve", inv_total, "#f59e0b")]
    cells = "".join(
        f'<div style="flex:1;min-width:130px;background:var(--card);border:1px solid var(--line);'
        f'border-top:3px solid {col};border-radius:5px;padding:10px 13px">'
        f'<div style="font-size:30px;font-weight:800;line-height:1;color:var(--ink)">{val}</div>'
        f'<div style="font-size:11.5px;color:var(--muted);margin-top:4px">{lbl}</div></div>'
        for lbl, val, col in head)
    st.markdown(f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">{cells}</div>',
                unsafe_allow_html=True)
    st.caption(f"🔴 {reds} red · 🟡 {ambers} amber · ✅ {len(active) - reds - ambers} healthy "
               f"across {len(active)} measures.")

    if emails:
        st.markdown("#### 📧 Emails")
        mx = max((k["count"] for k in emails), default=1) or 1
        bars = ""
        for k in sorted(emails, key=lambda k: -k["count"]):
            col = SUMMARY_STATUS_COL[status_of(k)]
            w = int(k["count"] / mx * 100)
            tgt = f"≤{k['target']}" if k.get("target", 0) > 0 else "0"
            bars += (f'<div style="display:flex;align-items:center;gap:10px;margin:4px 0">'
                     f'<div style="width:200px;font-size:12.5px">{k["name"]}</div>'
                     f'<div style="flex:1;background:#eef2f7;border-radius:3px;height:18px;overflow:hidden">'
                     f'<div style="width:{w}%;min-width:2px;background:{col};height:18px"></div></div>'
                     f'<div style="width:78px;text-align:right"><b>{k["count"]}</b>'
                     f'<span style="color:var(--muted);font-size:11px"> ({tgt})</span></div></div>')
        st.markdown(bars, unsafe_allow_html=True)

    for title, emoji in SUMMARY_SECTIONS:
        ks = by_sec.get(title, [])
        if not ks:
            continue
        st.markdown(f"#### {emoji} {title}")
        tiles = ""
        for k in sorted(ks, key=lambda k: -k["count"]):
            col = SUMMARY_STATUS_COL[status_of(k)]
            tgt = f"≤{k['target']}" if k.get("target", 0) > 0 else "0"
            tiles += (f'<div style="background:var(--card);border:1px solid var(--line);'
                      f'border-left:5px solid {col};border-radius:5px;padding:10px 12px">'
                      f'<div style="line-height:1;color:var(--ink)">'
                      f'<span style="font-size:26px;font-weight:800">{k["count"]}</span>'
                      f'<span style="font-size:12px;color:var(--muted);font-weight:600"> ({tgt})</span></div>'
                      f'<div style="font-size:11.5px;color:var(--muted);margin-top:4px">'
                      f'{k["name"]}</div></div>')
        st.markdown('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));'
                    f'gap:8px;margin-bottom:6px">{tiles}</div>', unsafe_allow_html=True)


QUOTE_MAILBOX = "hello@tradesuperstoreonline.co.uk"
QUOTE_FOLDER = "New Orders & Quotes"
QUOTE_CAT_QUOTED = "Quoted"          # Outlook category stamped when a quote is drafted
QUOTE_CAT_INFO = "Awaiting info"     # Outlook category stamped when we ask for details
# Standard reply wording when a customer asks about a trade/bulk discount. We never quote a
# discount automatically — we say one may be possible and gather what/how many/where so the
# team can decide manually.
_TRADE_DISCOUNT_NOTE = (
    "We may be able to offer a discount depending on the product, the quantities and the "
    "overall size of the order. To look into that for you, please let us know exactly what "
    "you need, how many, and the delivery postcode, and we'll review it and come back to you.")
# Bump this whenever the parse/quote logic changes — stale cached quotes in a live
# session then auto-recompute instead of showing old results.
QUOTE_PARSE_VERSION = 10


@st.cache_data(ttl=300, show_spinner=False)
def _quote_emails():
    try:
        return {"emails": data_sources.fetch_quote_emails(
            QUOTE_MAILBOX, QUOTE_FOLDER, days=14, limit=200)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
_FOLLOWUP_RE = re.compile(r"^\s*(re|fw|fwd)\s*:", re.I)


def _parse_one_quote(email, manual_note=None):
    """Thread fetch + ONE AI extraction (the single source of truth for both the
    overview table and the quote build) + postcode backstop. Plain function — calls
    only data_sources (no st.*), so it is safe to run in a worker thread. Returns the
    parsed dict, or {'error': ...}.

    manual_note: optional free text typed by our team to add/correct details the AI
    missed (extra products, quantities, colours). It's appended to the thread as
    authoritative so the extraction includes it."""
    thread = email.get("body") or ""
    cid = email.get("conversationId")
    if cid:
        try:
            msgs = data_sources.fetch_conversation(QUOTE_MAILBOX, cid)
            froms = {(m.get("from") or "").strip().lower() for m in (msgs or []) if m.get("from")}
            # Only merge the thread when it's a GENUINE back-and-forth (2+ distinct senders).
            # Shopify form submissions all share one sender + a subject-based conversation, so
            # Outlook lumps unrelated customers (Lee, Michael…) into one "thread" — merging
            # them makes the AI grab the wrong name. In that case use just this one email.
            if msgs and len(msgs) > 1 and len(froms) > 1:
                thread = "\n\n".join(
                    f"[{m['received']} · {m['from_name'] or m['from'] or '?'}]\n{m['body']}"
                    for m in msgs)
        except Exception:  # noqa: BLE001
            pass
    manual_note = (manual_note or "").strip()
    if manual_note:
        thread = (thread + "\n\n[Additional details from our team — treat as authoritative; "
                  "use these products, quantities and specifics]:\n" + manual_note)
    # If the customer attached a photo / basket screenshot / spec, read it too (vision).
    attachments = []
    if email.get("hasAttachments"):
        try:
            attachments = data_sources.fetch_message_attachments(QUOTE_MAILBOX, email["id"])
        except Exception:  # noqa: BLE001 — attachments are a bonus; text still parses
            attachments = []
    try:
        parsed = data_sources.extract_quote_items(thread, attachments=attachments or None)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    parsed["thread"] = thread
    parsed["_had_attachments"] = bool(attachments)
    parsed["_manual_note"] = manual_note or None
    parsed["_v"] = QUOTE_PARSE_VERSION
    # Strict web-form fields ('Name :', 'Email :', …) override AI guesses, and the real
    # customer email comes from the BODY — form emails are sent FROM the form app, not
    # the customer, so the sender is only used when it's clearly a real person.
    ff = _form_fields(email.get("body") or "")
    if ff.get("customer_name"):
        parsed["customer_name"] = ff["customer_name"].title()
    if ff.get("customer_email"):
        parsed["customer_email"] = ff["customer_email"]
    elif email.get("from") and not _is_automated_sender(email.get("from")):
        parsed["customer_email"] = email["from"]
    if ff.get("customer_phone"):
        parsed["customer_phone"] = ff["customer_phone"]
    if ff.get("postcode"):
        parsed["postcode"] = ff["postcode"]
    if not parsed.get("postcode"):
        m = _UK_POSTCODE.search(thread or "")
        parsed["postcode"] = m.group(1).upper() if m else None
    return parsed


_AUTOMATED_SENDERS = ("notification@", "noreply", "no-reply", "donotreply", "do-not-reply",
                      "pifyapp.com", "mailer-daemon", "@shopify")


def _is_automated_sender(addr):
    a = (addr or "").lower()
    return any(s in a for s in _AUTOMATED_SENDERS)


def _form_fields(body):
    """Pull the customer's details from a web-form submission body ('Name : …',
    'Email : …', 'Phone : …', 'Postcode : …'). Strict regex on the form's own fields —
    no guessing. Returns only the fields actually present."""
    # Stop a field value at the next bullet or the next KNOWN form label (works whether
    # the form separates fields with bullets or spaces). Postcode is left as-is so non-UK
    # ones (e.g. Irish Eircodes like 'H91 RY22') aren't lost.
    labels = (r"Name|Email|Phone|Mobile|Delivery\s*Postcode|Postcode|Address|Company|Are\s*you|"
              r"Notes|Required|Which|Approximate|Dimensions|Window|Door|Quantity|SKU")
    end = rf"(?=\s*(?:[•·*|]|(?:{labels})\b[^:]{{0,15}}:|$))"
    out, text = {}, (body or "")
    m = re.search(r"\bEmail\s*:\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text, re.I)
    if m:
        out["customer_email"] = m.group(1).strip()
    m = re.search(r"\bName\s*:\s*([A-Za-z][A-Za-z .'\-]*?)" + end, text, re.I)
    if m and m.group(1).strip():
        out["customer_name"] = m.group(1).strip()
    m = re.search(r"\bPhone\s*:\s*([+(]?\d[\d ()\-+]{6,})", text, re.I)
    if m:
        out["customer_phone"] = m.group(1).strip()
    m = re.search(r"\bPostcode\s*:\s*([A-Za-z0-9][A-Za-z0-9 ]*?)" + end, text, re.I)
    if m and m.group(1).strip():
        out["postcode"] = m.group(1).strip().upper()
    return out


def _parse_is_current(p):
    return bool(p) and not p.get("error") and p.get("_v") == QUOTE_PARSE_VERSION


def _quote_cache():
    return st.session_state.setdefault("quote_parse", {})


def _quote_manual():
    """Per-email free-text our team adds to correct/supplement the AI extraction
    (extra products, quantities, colours). Keyed by email id, kept for the session."""
    return st.session_state.setdefault("quote_manual", {})


def _ensure_parsed(emails):
    """Parse every email once (uncached ones in parallel). Returns the {id: parsed}
    cache so the table and the build share exactly the same extraction."""
    import concurrent.futures as _cf
    cache = _quote_cache()
    manual = _quote_manual()          # read in the main thread (no st.* inside workers)
    todo = [e for e in emails if not _parse_is_current(cache.get(e["id"]))]
    if todo:
        with st.spinner(f"Reading {len(todo)} quote email(s)…"):
            with _cf.ThreadPoolExecutor(max_workers=8) as ex:
                done = list(ex.map(
                    lambda e: (e["id"], _parse_one_quote(e, manual.get(e["id"]))), todo))
        for eid, parsed in done:
            cache[eid] = parsed
    return cache


def _email_cladding_takeoff(clad):
    """Turn a James Hardie cladding email (area-based) into a FULL priced take-off:
    boards + starter/top/corner/window trims + battens + EPDM + screws + paint/edge
    seal — sizing every accessory from the counts and dimensions given, or from
    sensible assumptions each flagged as a caveat (we calculate rather than punt).
    Returns (raw_lines, caveats). raw_lines: [{description, qty, search}]."""
    import math
    is_vl = "vl" in (clad.get("product") or "").lower()
    product = clad.get("product") or ("Hardie VL Plank" if is_vl else "Hardie Plank")
    cov = 0.72 if is_vl else 0.54          # VL Plank ~0.72 m²/board; lap HardiePlank 0.54
    gross = clad.get("gross_area_m2") or 0
    openings = clad.get("openings_m2") or 0
    net = max(0.0, gross - openings)
    if net <= 0:
        return None, None
    colour = (clad.get("colour") or "").strip()
    cav = []

    boards = math.ceil(net / cov * 1.10)   # +10% waste
    board_desc = f"{product} cladding board" + (f" — {colour}" if colour else "")
    raw = [{"description": board_desc, "qty": boards,
            "search": f"{product} {colour}".strip()}]
    cav.append(f"Boards: {net:.1f} m² to clad ({gross:.1f} m² less {openings:.1f} m² openings) "
               f"÷ {cov} m²/board + 10% waste = {boards} boards.")
    if not colour:
        cav.append("Colour/finish not confirmed — please let us know which colour you'd like.")

    # Geometry for trim sizing: use stated height/width, else derive from the area with a
    # sensible height assumption (flagged) so we can still size the starter/top/corner trims.
    height = clad.get("wall_height_m") or 0
    width = clad.get("total_width_m") or 0
    if not height and width:
        height = net / width if width else 0
    if not height:
        height = 2.4
        cav.append(f"Assumed a cladding height of {height:.1f} m (not stated) to size the trims — "
                   "confirm the run height and we'll refine.")
    if not width:
        width = net / height
        cav.append(f"Assumed ~{width:.1f} m total run width (area ÷ height) to size the "
                   "starter/top trims — confirm the elevation widths and we'll refine.")

    def L3(lm):                            # trims come in 3 m lengths, round up
        return max(1, math.ceil(lm / 3.0))

    if clad.get("wants_trims"):
        ext = clad.get("external_corners")
        if ext is None:
            ext = 4
            cav.append("Assumed 4 external corner trims (not confirmed) — tell us the exact number "
                       "of external corners and we'll adjust.")
        if ext:
            raw.append({"description": f"{product} external corner trim"
                                       f"{(' — ' + colour) if colour else ''} "
                                       f"({ext} corners × {height:.1f} m)",
                        "qty": L3(ext * height),
                        "search": f"James Hardie {product} external corner trim {colour}".strip()})
        intc = clad.get("internal_corners") or 0
        if intc:
            raw.append({"description": f"{product} internal corner trim"
                                       f"{(' — ' + colour) if colour else ''} "
                                       f"({intc} corners × {height:.1f} m)",
                        "qty": L3(intc * height),
                        "search": f"James Hardie {product} internal corner trim {colour}".strip()})
        raw.append({"description": "James Hardie starter / base vent strip", "qty": L3(width),
                    "search": "James Hardie starter track vent strip"})
        raw.append({"description": "James Hardie top vent strip", "qty": L3(width),
                    "search": "James Hardie top vent strip"})
        nwin = clad.get("num_windows")
        if nwin is None and openings > 0:
            nwin = max(1, round(openings / 1.5))
            cav.append(f"Assumed {nwin} window/opening(s) to trim (from {openings:.1f} m² of "
                       "openings) — confirm the number/size and we'll refine.")
        if nwin:
            raw.append({"description": f"HardieTrim NT3 window/door trim"
                                       f"{(' — ' + colour) if colour else ''} ({nwin} opening(s))",
                        "qty": L3(nwin * 5.0),
                        "search": f"James Hardie HardieTrim NT3 {colour}".strip()})
        cav.append("Trim pack sized from the corners, run width and openings above (all 3 m "
                   "lengths, rounded up). Send exact elevation widths / corner counts to tighten it.")

    batten_lm = net / 0.6
    if clad.get("wants_battens"):
        raw.append({"description": "Treated timber battens (25×50, per 3 m length)",
                    "qty": max(1, math.ceil(batten_lm / 3.0)),
                    "search": "treated timber batten 25 x 50"})
    if clad.get("wants_screws"):
        raw.append({"description": "James Hardie cladding screws (box of 250)",
                    "qty": max(1, math.ceil(boards * 7 / 250)),
                    "search": f"James Hardie cladding fixing screws {colour}".strip()})
    if clad.get("wants_epdm"):
        raw.append({"description": "EPDM joint tape (20 m roll)",
                    "qty": max(1, math.ceil(batten_lm / 20)),
                    "search": "James Hardie EPDM tape 20m"})
    if clad.get("wants_paint"):
        raw.append({"description": f"James Hardie touch-up paint"
                                   f"{(' — ' + colour) if colour else ''}",
                    "qty": 1, "search": f"James Hardie touch up paint {colour}".strip()})
        raw.append({"description": "James Hardie edge sealer (cut edges)", "qty": 1,
                    "search": "James Hardie edge sealer"})
        cav.append("Included 1 touch-up paint" + (f" in {colour}" if colour else "")
                   + " and 1 edge sealer for cut edges — tell us if you need more.")
    return raw, cav


# Brand / filler tokens that must NOT, on their own, justify a fallback match — so a
# 'James Hardie top vent strip' can't match a 'James Hardie plank board' just on the brand.
# Passed as the invoice scorer's `common` set (same role as order-wide colour words there).
_QUOTE_BRAND_COMMON = {"james", "hardie", "hardieplank", "cedral", "molan", "millboard",
                       "cladco", "durasid", "eurocell", "marley", "brand", "new"}


def _email_kerrafront_takeoff(clad):
    """Vox Kerrafront cladding take-off. Boards (FS-302, 0.97 m²/board) + FS-222 corners
    (one profile for BOTH internal & external) + FS-211 starter + FS-251 finishing trim +
    A2 stainless fixings (9/m² double board, 15/m² single) + battens at 400 mm centres.
    Sizes everything from area and counts, with sensible assumptions each flagged as a
    caveat. Returns (raw_lines, caveats). raw_lines: [{description, qty, search}]."""
    import math
    gross = clad.get("gross_area_m2") or 0
    openings = clad.get("openings_m2") or 0
    net = max(0.0, gross - openings)
    if net <= 0:
        return None, None
    colour = (clad.get("colour") or "").strip()
    cav = []

    COV = 0.97                              # FS-302 double board coverage per panel (Vox spec)
    boards = math.ceil(net / COV * 1.10)    # +10% waste
    raw = [{"description": "Kerrafront FS-302 cladding board" + (f" — {colour}" if colour else ""),
            "qty": boards, "search": f"Kerrafront 302 {colour}".strip()}]
    cav.append(f"Boards: {net:.1f} m² ÷ 0.97 m²/board (FS-302) + 10% waste = {boards} boards.")
    if not colour:
        cav.append("Colour/finish not confirmed — let us know which Kerrafront colour you'd like.")

    height = clad.get("wall_height_m") or 0
    width = clad.get("total_width_m") or 0
    if not height and width:
        height = net / width if width else 0
    if not height:
        height = 2.4
        cav.append(f"Assumed a cladding height of {height:.1f} m (not stated) to size the trims — "
                   "confirm the run height and we'll refine.")
    if not width:
        width = net / height
        cav.append(f"Assumed ~{width:.1f} m total run width (area ÷ height) to size the "
                   "starter/finishing trims — confirm the elevation widths and we'll refine.")

    def L3(lm):                             # Kerrafront trims come in 3.0 m lengths, round up
        return max(1, math.ceil(lm / 3.0))

    if clad.get("wants_trims"):
        ext = clad.get("external_corners")
        intc = clad.get("internal_corners") or 0
        if ext is None:
            ext = 4
            cav.append("Assumed 4 corners (not confirmed) — Kerrafront uses one FS-222 profile for "
                       "both internal and external corners; tell us the exact count to adjust.")
        corners = (ext or 0) + intc
        if corners:
            raw.append({"description": f"Kerrafront FS-222 2-part universal corner"
                                       f"{(' — ' + colour) if colour else ''} "
                                       f"({corners} corners × {height:.1f} m)",
                        "qty": L3(corners * height),
                        "search": f"Kerrafront FS-222 universal corner {colour}".strip()})
        raw.append({"description": "Kerrafront FS-211 starter trim (base)", "qty": L3(width),
                    "search": "Kerrafront FS-211 starter trim"})
        nwin = clad.get("num_windows")
        if nwin is None and openings > 0:
            nwin = max(1, round(openings / 1.5))
            cav.append(f"Assumed {nwin} opening(s) for finishing trim (from {openings:.1f} m² of "
                       "openings) — confirm the number/size and we'll refine.")
        if nwin:
            raw.append({"description": f"Kerrafront FS-251 universal finishing/edge trim"
                                       f"{(' — ' + colour) if colour else ''} ({nwin} opening(s))",
                        "qty": L3(nwin * 5.0),
                        "search": f"Kerrafront FS-251 universal trim {colour}".strip()})
        if height > 2.95:
            cav.append("The run is taller than one 2.95 m board — Kerrafront connectors are needed at "
                       "the horizontal joins; send the exact heights and we'll add the connector count.")
        cav.append("Trim pack sized from the corners, run width and openings above (3 m lengths, "
                   "rounded up). FS-222 covers both internal and external corners.")

    # Fixings — A2 stainless, 9/m² for the double FS-302 board, 15/m² for single boards.
    if clad.get("wants_screws", True):
        rate = 15 if clad.get("single_board") else 9
        boxes = max(1, math.ceil(net * rate / 250))
        raw.append({"description": f"A2 stainless fixings (box of 250, ~{rate}/m²)"
                                   + (f" — {colour}" if colour else ""),
                    "qty": boxes, "search": f"Polytop stainless steel fixing nails {colour}".strip()})
        cav.append(f"Fixings: {rate}/m² ({'single' if clad.get('single_board') else 'double'} board) "
                   f"× {net:.1f} m² ≈ {boxes} box(es) of 250. Fix into battens at ≤400 mm centres, in "
                   "the centre of the slots and left slightly proud so the cladding can move.")
    if colour and any(d in colour.lower() for d in ("anthracite", "graphite", "black", "grey")):
        cav.append("For a dark colour leave a ~15 mm expansion gap at board ends (more than a pale "
                   "colour needs) — Kerrafront moves with temperature.")
    if clad.get("wants_battens"):
        raw.append({"description": "Treated timber battens (per 3 m length, ≤400 mm centres)",
                    "qty": max(1, math.ceil((net / 0.4) / 3.0)),
                    "search": "treated timber batten 25 x 50"})
    return raw, cav


def _quote_fallback_match(description):
    """For a requested line the primary matcher couldn't price, search Shopify more broadly
    and pick the best candidate using the INVOICE CHECKER's token scorer (_name_pair_score:
    distinctive shared words, length-weighted, credibility-gated) rather than Shopify's own
    search ranking. Returns a priced variant dict or None — only ever a credible match, so a
    'no match' stays a 'no match' rather than becoming a wrong one."""
    desc = (description or "").strip()
    dt = _title_tokens(desc)
    if not dt:
        return None
    # Two passes: the full phrase, then a key-tokens query (helps when the exact phrase
    # returns nothing) — deduped by variant id.
    queries = [desc]
    key_tokens = " ".join(sorted(dt, key=len, reverse=True)[:5])
    if key_tokens and key_tokens.lower() != desc.lower():
        queries.append(key_tokens)
    seen, cands = set(), []
    for q in queries:
        try:
            for c in data_sources.shopify_search_variants(q, first=15):
                vid = c.get("variant_id")
                if vid and vid not in seen:
                    seen.add(vid)
                    cands.append(c)
        except Exception:  # noqa: BLE001
            pass
    best, best_key = None, (0.0, False, False)
    for c in cands:
        if c.get("price") is None:
            continue
        score = _name_pair_score(dt, _title_tokens(c.get("title")), _QUOTE_BRAND_COMMON)
        if score <= 0:
            continue
        key = (score, bool(c.get("available")), True)   # score, then in-stock, then priced
        if key > best_key:
            best, best_key = c, key
    return best


def _build_quote(email):
    """Full build for ONE email: reuse the shared parse, then lazily add Shopify
    matching and the composed clarify email (computed once, stored on the parse)."""
    cache = _quote_cache()
    parsed = cache.get(email["id"])
    if not _parse_is_current(parsed):
        parsed = _parse_one_quote(email, _quote_manual().get(email["id"]))
        cache[email["id"]] = parsed
    if parsed.get("error"):
        return parsed
    if "lines" not in parsed:
        clad = parsed.get("cladding") or {}
        raw_clad, clad_cav = (None, None)
        if clad.get("is_cladding") and (clad.get("gross_area_m2") or 0) > 0:
            sys_ = (clad.get("system") or "").lower()
            is_kerra = sys_ == "kerrafront" or "kerrafront" in (clad.get("product") or "").lower()
            raw_clad, clad_cav = (_email_kerrafront_takeoff(clad) if is_kerra
                                  else _email_cladding_takeoff(clad))
        if raw_clad:
            # Cladding: quote by converting area to boards (+ requested accessories).
            lines = []
            for it in raw_clad:
                try:
                    match = data_sources.match_quote_variant(None, it["search"])
                except Exception:  # noqa: BLE001
                    match = None
                lines.append({"description": it["description"], "qty": it["qty"], "match": match})
            parsed["lines"] = lines
            parsed["caveats"] = (parsed.get("caveats") or []) + (clad_cav or [])
            parsed["can_quote"] = True
        else:
            lines = []
            for it in (parsed.get("items") or []):
                try:
                    match = data_sources.match_quote_variant(it.get("code"), it.get("description"))
                except Exception:  # noqa: BLE001
                    match = None
                lines.append({"description": it.get("description"), "qty": it.get("qty") or 1,
                              "match": match})
            parsed["lines"] = lines
        # Any line the primary matcher couldn't price → retry with the invoice-checker's
        # token scorer over a broader Shopify search (matches on distinctive shared words).
        for l in parsed["lines"]:
            m = l.get("match")
            if not (m and m.get("price") is not None):
                fb = _quote_fallback_match(l.get("description"))
                if fb and fb.get("price") is not None:
                    l["match"] = fb
                    l["_fallback"] = True
    # Only fall back to a pure "ask for details" email when there is genuinely nothing we
    # can price. If we found any priceable item we quote provisionally and flag the gaps.
    has_priceable = any(l.get("match") and l["match"].get("price") is not None
                        for l in parsed["lines"])
    # Scotland delivery: flag a possible surcharge to confirm before proceeding (shows on the
    # quote's assumptions and flows into the composed email via the delivery note).
    if _is_scotland_postcode(parsed.get("postcode")):
        cav = parsed.get("caveats") or []
        note = _scotland_delivery_note(parsed.get("postcode"))
        if note not in cav:
            cav.append(note)
        parsed["caveats"] = cav
    # Trade-discount enquiry: note we might offer one, and (if they've been quoted) flag it
    # as something for us to review manually rather than applying anything automatically.
    if parsed.get("trade_discount") and has_priceable:
        cav = parsed.get("caveats") or []
        cav.append("You asked about a trade discount — we may be able to offer one depending on "
                   "the final products, quantities and overall order size; let us know and we'll "
                   "review it for you.")
        parsed["caveats"] = cav
    if not has_priceable and "clarify_email" not in parsed:
        qs = parsed.get("questions") or (
            [parsed["missing_info"]] if parsed.get("missing_info") else [])
        qs = [str(x).strip() for x in qs if x and str(x).strip()]
        # Trade-discount enquiry with nothing to price → ask what / how many / where so we can
        # review a discount manually, and lead with the "we may be able to offer" line.
        discount_note = None
        if parsed.get("trade_discount"):
            discount_note = _TRADE_DISCOUNT_NOTE
            for want in ("which products you're after", "how many of each you need",
                         "the delivery postcode"):
                if not any(want.split()[1] in q.lower() for q in qs):
                    qs.append("Could you let us know " + want + "?")
        parsed["questions"] = qs
        # Fallback: search our catalogue for the products the customer described.
        parsed["suggestions"] = _quote_suggestions(parsed)
        parsed["delivery_note"] = _delivery_note(parsed)
        try:
            parsed["clarify_email"] = data_sources.compose_customer_email(
                parsed.get("thread", ""), "clarify",
                {"customer_name": parsed.get("customer_name"), "questions": qs,
                 "suggestions": parsed["suggestions"], "delivery_note": parsed["delivery_note"],
                 "discount_note": discount_note})
        except Exception:  # noqa: BLE001 — no AI key etc.; render falls back to a template
            parsed["clarify_email"] = None
    return parsed


# Scottish mainland + islands postcode areas — delivery to these often carries a surcharge,
# so we confirm the delivery cost before proceeding rather than quoting it blind.
_SCOTLAND_AREAS = {"AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML",
                   "PA", "PH", "TD", "ZE"}


def _is_scotland_postcode(pc):
    m = re.match(r"\s*([A-Za-z]{1,2})\d", pc or "")
    return bool(m) and m.group(1).upper() in _SCOTLAND_AREAS


def _scotland_delivery_note(pc):
    return (f"As delivery is to Scotland ({(pc or '').upper()}), there may be a delivery "
            "surcharge — we'll confirm the exact delivery cost for you. Please let us know if "
            "you'd like to proceed and we'll firm that up.")


def _delivery_note(parsed):
    """Standard stock/delivery-by-postcode note, with the internal-doors caveat when the
    enquiry involves doors and a Scotland surcharge note for Scottish postcodes."""
    note = ("Please note that stock availability and delivery charges can vary depending on the "
            "delivery postcode — if you let us know your postcode we'll confirm both.")
    text = " ".join(str(parsed.get(k) or "") for k in ("product_range", "summary")).lower()
    text += " " + " ".join(str(it.get("description") or "")
                           for it in (parsed.get("items") or [])).lower()
    if "door" in text:
        note += (" Internal doors in particular cannot be quoted for delivery until we have a "
                 "delivery postcode.")
    if _is_scotland_postcode(parsed.get("postcode")):
        note += " " + _scotland_delivery_note(parsed.get("postcode"))
    return note


def _quote_suggestions(parsed, limit=5):
    """As a fallback for vague enquiries, search our catalogue for product titles matching
    what the customer described. Returns up to `limit` distinct titles."""
    terms = [(it.get("description") or "").strip()
             for it in (parsed.get("items") or []) if (it.get("description") or "").strip()]
    if not terms:
        for f in ("summary", "product_range"):
            v = (parsed.get(f) or "").strip()
            if v and v.lower() != "unclear":
                terms.append(v)
                break
    titles, seen = [], set()
    for t in terms[:3]:
        try:
            cands = data_sources.shopify_search_variants(t, first=5)
        except Exception:  # noqa: BLE001
            cands = []
        for c in cands:
            ti = (c.get("title") or "").strip()
            if ti and ti.lower() not in seen:
                seen.add(ti.lower())
                titles.append(ti)
            if len(titles) >= limit:
                return titles
    return titles


def _first_name(*candidates):
    for c in candidates:
        if c and str(c).strip():
            return str(c).strip().split()[0]
    return "there"


def _quote_clarify_body(q, email):
    """A clean, customer-facing 'we need a bit more info' reply."""
    qs = q.get("questions") or ([q["missing_info"]] if q.get("missing_info") else [])
    qs = [x.strip() for x in qs if x and str(x).strip()]
    if not qs:
        qs = ["Could you confirm the exact products and quantities you need?"]
    bullets = "\n".join(f"- {x if x.endswith('?') else x + '?'}" for x in qs)
    name = _first_name(q.get("customer_name"), email.get("from_name"))
    sugg = [s for s in (q.get("suggestions") or []) if s and str(s).strip()]
    sugg_txt = ""
    if sugg:
        sugg_txt = ("\n\nFrom what you've described, these from our range may suit — let us know "
                    "which you'd like:\n" + "\n".join(f"- {s}" for s in sugg))
    note = q.get("delivery_note") or _delivery_note(q)
    disc = (_TRADE_DISCOUNT_NOTE + "\n\n") if q.get("trade_discount") else ""
    return (f"Hi {name},\n\nThanks for your enquiry. " + disc +
            "To put your quote together, could you please confirm:\n\n" + bullets + sugg_txt +
            f"\n\n{note}\n\nOnce we have that we'll send your quote straight over.\n\n"
            "Kind regards,\nTrade Superstore Online")


def _mark_quote_progress(email, category):
    """Stamp the source email in Outlook (category + read) so progress is durable and
    visible to the team, and update the in-memory copy so the table updates at once."""
    try:
        data_sources.tag_message(QUOTE_MAILBOX, email["id"],
                                 add_categories=[category], mark_read=True)
        cats = email.setdefault("categories", [])
        if category not in cats:
            cats.append(category)
        email["isRead"] = True
    except Exception as e:  # noqa: BLE001
        st.caption("⚠️ Couldn't tag the email in Outlook (" + str(e)[:120] + ").")


def _render_quote_block(email):
    """Build + render one email's quote: the priced table + create buttons, or a
    clarify draft if we can't quote yet. Safe to call inside a loop/expander."""
    eid = email["id"]
    manual = _quote_manual()
    # Manual add / correct: type extra products, quantities or colours the email didn't
    # make clear; it's fed to the AI as authoritative and the quote recomputes.
    with st.expander("✏️ Add or correct details" + (" · applied" if manual.get(eid) else ""),
                     expanded=bool(manual.get(eid))):
        txt = st.text_area(
            "Extra details for this quote", value=manual.get(eid, ""),
            key=f"qman_txt_{eid}", height=90,
            placeholder="e.g. 39 lengths Millboard Envello Golden Oak, 4 external corner trims, "
                        "deliver to LE3 6DA",
            label_visibility="collapsed")
        b1, b2 = st.columns(2)
        if b1.button("Apply & rebuild", key=f"qman_apply_{eid}", type="primary",
                     use_container_width=True):
            new = (txt or "").strip()
            if new:
                manual[eid] = new
            else:
                manual.pop(eid, None)
            _quote_cache().pop(eid, None)      # force a fresh parse that includes the note
            st.rerun()
        if manual.get(eid) and b2.button("Clear", key=f"qman_clear_{eid}",
                                         use_container_width=True):
            manual.pop(eid, None)
            _quote_cache().pop(eid, None)
            st.rerun()
    with st.spinner("Reading the conversation and pricing from Shopify…"):
        q = _build_quote(email)
    if q.get("_had_attachments"):
        st.caption("📎 Read the customer's attachment(s) as well as the email text.")
    if q.get("error"):
        if "ANTHROPIC_API_KEY" in q["error"]:
            st.info("Add your **ANTHROPIC_API_KEY** in Settings → Secrets to read quote emails.")
        else:
            st.error("Couldn't read the email: " + q["error"][:200])
        return

    lines = q.get("lines") or []
    matched = [l for l in lines if l["match"] and l["match"].get("price") is not None]
    caveats = [c for c in (q.get("caveats") or []) if c and str(c).strip()]

    # Nothing we can price → draft a polite "what we need" email instead.
    if not matched:
        st.warning("Nothing we can price yet — drafted a reply asking for what's needed.")
        body = q.get("clarify_email") or _quote_clarify_body(q, email)
        st.text_area("Draft reply", value=body, height=240, key=f"qclar_{email['id']}")
        if st.button("Create Outlook draft (ask for details)", key=f"qclarbtn_{email['id']}"):
            try:
                subj = f"RE: {email['subject']}"
                link = data_sources.create_reply_draft(
                    QUOTE_MAILBOX, email["id"], st.session_state[f"qclar_{email['id']}"],
                    subject=subj, as_html=True, to_email=q.get("customer_email"))
                _mark_quote_progress(email, QUOTE_CAT_INFO)
                st.success("Draft reply created in Outlook — review and send from there. "
                           "Marked **Info requested**.")
                if link:
                    st.markdown(f"[Open the draft in Outlook]({link})")
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't create the draft: " + str(e)[:200])
        return

    # We can quote — provisional if the request was incomplete or had assumptions.
    provisional = (not q.get("can_quote")) or (len(matched) < len(lines)) or bool(caveats)
    total = sum(l["match"]["price"] * l["qty"] for l in matched)
    rows = ""
    for l in lines:
        m = l["match"]
        if m and m.get("price") is not None:
            tag = ('<span style="color:#d97706"> · ≈ name match, check</span>'
                   if l.get("_fallback") else "")
            prod = (f'{_esc(m.get("title") or "?")}{tag}'
                    f'<div style="color:var(--muted);font-size:11px">'
                    f'SKU {_esc(m.get("sku") or "—")}</div>')
            unit = f"£{m['price']:,.2f}"
            line = f"£{m['price'] * l['qty']:,.2f}"
        else:
            prod = '<span style="color:#ef4444">no match — add manually</span>'
            unit = line = "—"
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:6px 10px;overflow-wrap:break-word">{_esc(l["description"] or "—")}</td>'
                 f'<td style="padding:6px 10px;text-align:center">{l["qty"]}</td>'
                 f'<td style="padding:6px 10px;overflow-wrap:break-word">{prod}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{unit}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{line}</td></tr>')
    st.markdown(f"### Quote for {q.get('customer_name') or email.get('from_name') or 'customer'}")
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:12.5px">'
                '<tr style="text-align:left;color:var(--muted)">'
                '<th style="padding:6px 10px">Requested</th>'
                '<th style="padding:6px 10px;text-align:center">Qty</th>'
                '<th style="padding:6px 10px">Matched product</th>'
                '<th style="padding:6px 10px;text-align:right">Unit</th>'
                '<th style="padding:6px 10px;text-align:right">Line</th></tr>'
                + rows + "</table>", unsafe_allow_html=True)
    st.markdown(f"**Subtotal (matched lines): £{total:,.2f}**")

    # Customer-facing caveats: the AI's assumptions + any items we couldn't price.
    all_caveats = list(caveats)
    unmatched = [l for l in lines if not (l["match"] and l["match"].get("price") is not None)]
    if unmatched:
        names = "; ".join((l["description"] or "item") for l in unmatched)
        all_caveats.append("We couldn't price these from our catalogue yet so they're not on the "
                           f"quote — please confirm and we'll add them: {names}.")
    if provisional:
        st.info("Goes out as a **provisional** quote — the email explains what it's based on and "
                "asks the customer to confirm.")
    if all_caveats:
        st.markdown("**The email will ask the customer to check these:**")
        st.markdown("\n".join(f"- {c}" for c in all_caveats))

    btn = ("Create provisional quote (draft order + reply)" if provisional
           else "Create Shopify draft order + Outlook draft reply")
    if st.button(btn, type="primary", key=f"qcreate_{email['id']}"):
        # The customer's real details (form body), NOT the form app's sender address.
        cust_email = q.get("customer_email")
        cust_name = q.get("customer_name")
        cust_phone = q.get("customer_phone")
        note = f"Quote for {cust_name or 'customer'} — from: {email['subject']}"
        # 1) Try the Shopify draft order (needs write_draft_orders) — but don't block on it.
        do, draft_err = None, None
        try:
            li = [{"variantId": l["match"]["variant_id"], "quantity": l["qty"]} for l in matched]
            do = data_sources.create_draft_order(li, email=cust_email, note=note,
                                                 name=cust_name, phone=cust_phone)
        except Exception as e:  # noqa: BLE001
            draft_err = str(e)
        ref = do["name"] if do else None
        url = do["invoiceUrl"] if do else None
        total_amt = do["total"] if do else total

        # 2) Compose the quote email from the priced lines (works with or without the draft).
        #    No payment/quote link is included in the customer email.
        dnote = _delivery_note(q)
        cdata = {"customer_name": q.get("customer_name"),
                 "lines": [{"qty": l["qty"], "title": l["match"]["title"],
                            "unit": l["match"]["price"],
                            "line": l["match"]["price"] * l["qty"]} for l in matched],
                 "total": total_amt, "ref": ref,
                 "caveats": all_caveats, "provisional": provisional, "delivery_note": dnote}
        try:
            body = data_sources.compose_customer_email(q.get("thread", ""), "quote", cdata)
        except Exception:  # noqa: BLE001
            body_lines = "\n".join(f"- {l['qty']} x {l['match']['title']} "
                                   f"@ £{l['match']['price']:,.2f}" for l in matched)
            cav_txt = (("\n\nA few things to check:\n"
                        + "\n".join(f"- {c}" for c in all_caveats)) if all_caveats else "")
            ref_txt = f" (ref {ref})" if ref else ""
            body = (f"Hi {_first_name(q.get('customer_name'), email.get('from_name'))},\n\n"
                    f"Thank you for your enquiry. Based on the details provided, here is your "
                    f"quote{ref_txt}:\n\n{body_lines}\n\nTotal (ex-VAT): £{total_amt:,.2f}"
                    f"{cav_txt}\n\n{dnote}\n\nPlease do check it over and confirm it is all "
                    "correct, and let us know if anything needs adding or amending.\n\n"
                    "Kind regards,\nTrade Superstore Online")

        # 3) Create the Outlook draft reply and mark progress.
        link = None
        try:
            subj = (f"Your quote {ref} – RE: {email['subject']}" if ref
                    else f"Your quote – RE: {email['subject']}")
            link = data_sources.create_reply_draft(QUOTE_MAILBOX, email["id"], body,
                                                   subject=subj, as_html=True, to_email=cust_email)
            _mark_quote_progress(email, QUOTE_CAT_QUOTED)
        except Exception as e:  # noqa: BLE001
            st.error("Couldn't create the Outlook draft: " + str(e)[:200])

        # 4) Report.
        if do:
            st.success(f"Created Shopify draft order **{ref}** (£{total_amt:,.2f}) and an Outlook "
                       "draft reply — review and send from Outlook. Marked **✓ Quoted**.")
        else:
            st.warning("Couldn't create the Shopify draft order — the **write_draft_orders** scope "
                       "is missing (see fix below). I drafted the quote **email** from the priced "
                       f"lines instead (total £{total_amt:,.2f}). Marked **✓ Quoted**.")
            if draft_err:
                st.caption("Shopify said: " + draft_err[:180])
        bits = []
        if url:
            bits.append(f"[Open the Shopify draft order]({url})")
        if link:
            bits.append(f"[Open the Outlook draft]({link})")
        if bits:
            st.markdown(" · ".join(bits))


def _qbadge(text, bg, fg="#fff"):
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:10px;'
            f'font-size:11px;font-weight:700;white-space:nowrap">{text}</span>')


def _esc(v):
    """HTML-escape any cell value so AI/customer text (e.g. 'Fascia & soffit', a stray
    '<') can't break the table markup and distort the layout."""
    import html as _html
    return _html.escape("" if v is None else str(v))


def _quote_progress_badge(email):
    """Durable progress, read back from the Outlook message (categories + read flag).
    Returns the HTML badge for the Progress column."""
    cats = [str(c).lower() for c in (email.get("categories") or [])]
    if QUOTE_CAT_QUOTED.lower() in cats:
        return _qbadge("✓ Quoted", "#15803D")
    if QUOTE_CAT_INFO.lower() in cats:
        return _qbadge("✓ Info requested", "#7C3AED")
    if email.get("isRead"):
        return _qbadge("Opened", "#6B7280")
    return _qbadge("New", "#94A3B8")


def _quote_legend():
    items = [
        ("New", "#2563EB", "Brand-new enquiry (first contact)"),
        ("Follow-up", "#B45309", "Part of an existing conversation"),
        ("Ready", "#16A34A", "Has products + quantities — quote now"),
        ("Needs info", "#6B7280", "Missing detail — ask the customer first"),
        ("URGENT", "#DC2626", "Customer needs it quickly / by a date"),
    ]
    progress = [
        ("✓ Quoted", "#15803D", "Quote drafted & saved to Outlook"),
        ("✓ Info requested", "#7C3AED", "We've drafted a reply asking for detail"),
        ("Opened", "#6B7280", "Seen / read, not yet actioned"),
    ]
    def line(its):
        return "".join(
            '<span style="display:inline-flex;align-items:center;gap:6px;margin:2px 14px 2px 0">'
            f'{_qbadge(lbl, bg)}<span style="font-size:11.5px;color:var(--muted)">{desc}</span>'
            '</span>' for lbl, bg, desc in its)
    st.markdown(f'<div style="margin:2px 0 2px">{line(items)}</div>'
                f'<div style="margin:0 0 8px">{line(progress)}</div>', unsafe_allow_html=True)


def _render_quote_overview(emails, cache):
    """Render the overview table for the given (already-parsed) emails. 'Ready' comes
    straight from the same extraction the build uses, so they can never disagree."""
    errs = [(cache.get(e["id"]) or {}).get("error") for e in emails]
    errs = [x for x in errs if x]
    if errs and len(errs) == len(emails):
        if "ANTHROPIC_API_KEY" in errs[0]:
            st.info("Add your **ANTHROPIC_API_KEY** in Settings → Secrets to see the overview.")
        else:
            st.warning("Couldn't read the emails: " + errs[0][:160])
        return
    _quote_legend()

    n_new = n_fu = n_ready = n_urgent = 0
    rows = ""
    for e in emails:
        p = cache.get(e["id"]) or {}
        if p.get("error"):
            continue
        is_fu = bool(_FOLLOWUP_RE.match(e.get("subject") or ""))
        ready = bool(p.get("can_quote"))
        urgent = (p.get("urgency") == "urgent")
        n_fu += is_fu
        n_new += (not is_fu)
        n_ready += ready
        n_urgent += urgent
        cust = p.get("customer_name") or e.get("from_name") or e.get("from") or "—"
        typ = _qbadge("Follow-up", "#B45309") if is_fu else _qbadge("New", "#2563EB")
        status = _qbadge("Ready", "#16A34A") if ready else _qbadge("Needs info", "#6B7280")
        urg = (" " + _qbadge("URGENT", "#DC2626")) if urgent else ""
        td = ('padding:7px 10px;overflow:hidden;text-overflow:ellipsis;'
              'overflow-wrap:break-word;vertical-align:top')
        rows += (
            '<tr style="border-top:1px solid var(--line)">'
            f'<td style="{td};white-space:nowrap;color:var(--muted)">{_esc(e.get("received") or "—")}</td>'
            f'<td style="{td};font-weight:600">{_esc(cust)}</td>'
            f'<td style="{td}">{typ}</td>'
            f'<td style="{td}">{_esc(p.get("product_range") or "—")}</td>'
            f'<td style="{td};white-space:nowrap">{_esc(p.get("postcode") or "—")}</td>'
            f'<td style="{td}">{_esc(p.get("summary") or "—")}</td>'
            f'<td style="{td}">{status}{urg}</td>'
            f'<td style="{td}">{_quote_progress_badge(e)}</td></tr>')

    cols = [("Received", "8%"), ("Customer", "14%"), ("Type", "8%"), ("Product range", "13%"),
            ("Postcode", "9%"), ("What they want", "26%"), ("Status", "12%"), ("Progress", "10%")]
    colgroup = "".join(f'<col style="width:{w}">' for _, w in cols)
    head = "".join(f'<th style="text-align:left;padding:7px 10px;color:var(--muted);'
                   f'font-weight:600">{h}</th>' for h, _ in cols)
    st.markdown(
        '<div style="width:100%;overflow-x:auto">'
        '<table style="width:100%;table-layout:fixed;border-collapse:collapse;font-size:12.5px;'
        'border:1px solid var(--line);border-radius:6px">'
        f'<colgroup>{colgroup}</colgroup>'
        f'<tr style="background:var(--card)">{head}</tr>{rows}</table></div>',
        unsafe_allow_html=True)
    st.caption(f"**{len(emails)}** request(s) · {n_new} new · {n_fu} follow-up · "
               f"{n_ready} ready to quote · {n_urgent} urgent. "
               "Summaries are AI-generated (cached).")


# James Hardie cladding take-off — mirrors the official calculator (boards from area
# using TRUE 0.54 m² coverage, not the 0.65 gross figure) + the trim/accessory pack.
HARDIE_PRODUCTS = {
    "Hardie Plank — horizontal lap (150mm cover)": {"coverage": 0.54, "search": "Hardie Plank"},
    "Hardie VL Plank — horizontal": {"coverage": 0.72, "search": "Hardie VL Plank"},
    "Hardie VL Plank — vertical": {"coverage": 0.72, "search": "Hardie VL Plank"},
}
HARDIE_TEXTURES = ["Cedar", "Smooth"]
BATTEN_CENTRES = {"600 mm (standard)": 600, "450 mm": 450, "300 mm": 300}


def _fixings_per_board(batten_mm, board_len_mm=3600):
    return round(board_len_mm / batten_mm) + 1 if batten_mm else 0


def _cladding_takeoff(inp):
    """Pure calc: inputs -> (take-off lines, meta). Trims priced as 3m lengths."""
    import math
    net = max(0.0, inp["gable"] + inp["other"] - inp["openings"])
    cov = inp["coverage"] or 0.54
    boards = math.ceil((net / cov) * (1 + inp["waste_pct"] / 100.0)) if net else 0
    bc = inp["batten_mm"]
    batten_lm = net / (bc / 1000.0) if (net and bc) else 0.0
    fpb = _fixings_per_board(bc)
    fixings = boards * fpb
    pcs = lambda lm: math.ceil(lm / 3.0) if lm > 0 else 0  # noqa: E731 — 3m trim lengths
    lines = [
        ("board", f"{inp['product_label'].split(' —')[0]} board (3.6m)", boards, "board",
         inp["board_search"]),
        ("starter", "Starter / base ventilation profile (3m)", pcs(inp["base_lm"]), "length",
         "Hardie starter base vent profile"),
        ("top", "Top ventilation profile (3m)", pcs(inp["top_lm"]), "length",
         "Hardie top vent profile"),
        ("extcorner", "External corner trim (3m)", pcs(inp["ext_corner_lm"]), "length",
         "Hardie external corner trim"),
        ("intcorner", "Internal corner trim (3m)", pcs(inp["int_corner_lm"]), "length",
         "Hardie internal corner trim"),
        ("hardietrim", "HardieTrim NT3 around openings (3m)", pcs(inp["opening_lm"]), "length",
         "HardieTrim NT3"),
        ("epdm", "EPDM joint tape (20m roll)", math.ceil(batten_lm / 20) if batten_lm else 0,
         "roll", "EPDM joint tape"),
        ("seal", "HardieSeal edge coat (1L)", max(1, math.ceil(net / 150)) if net else 0, "tub",
         "HardieSeal edge coat"),
        ("fixings", f"Cladding fixings (~{fpb}/board, ~{fixings} total)",
         math.ceil(fixings / 250) if fixings else 0, "box of 250", "Hardie cladding fixings screws"),
    ]
    out = [{"key": k, "item": it, "qty": q, "unit": u, "search": s}
           for k, it, q, u, s in lines if q > 0]
    return out, {"net": net, "boards": boards, "batten_lm": batten_lm, "fixings": fixings, "fpb": fpb}


def render_cladding_calc():
    st.markdown("### 🧱 James Hardie cladding calculator")
    st.caption("Boards are worked out from area using the **true 0.54 m² coverage** (not the 0.65 m² "
               "gross figure on product pages — that under-orders by ~17%). Add the trim runs for the "
               "accessory pack, then price from Shopify. Quantities include waste.")

    with st.form("clad"):
        c1, c2, c3 = st.columns(3)
        product_label = c1.selectbox("Product", list(HARDIE_PRODUCTS))
        texture = c2.selectbox("Texture", HARDIE_TEXTURES)
        colour = c3.text_input("Colour", placeholder="e.g. Arctic White")
        c4, c5, c6 = st.columns(3)
        coverage = c4.number_input("Coverage m²/board", min_value=0.10,
                                   value=float(HARDIE_PRODUCTS[product_label]["coverage"]),
                                   step=0.01, format="%.2f",
                                   help="Auto-set per product. Lap HardiePlank = 0.54. Confirm VL Plank.")
        batten_label = c5.selectbox("Batten centres", list(BATTEN_CENTRES))
        waste_pct = c6.number_input("Waste %", min_value=0, max_value=30, value=10, step=1,
                                    help="10% standard; 15% for lots of gables, diagonal cuts or short runs.")
        st.markdown("**Areas** (measure each elevation w×h; gable = w×h÷2)")
        a1, a2, a3 = st.columns(3)
        gable = a1.number_input("Gable area m²", min_value=0.0, value=0.0, step=0.5)
        other = a2.number_input("Other cladding area m²", min_value=0.0, value=0.0, step=0.5)
        openings = a3.number_input("Openings to deduct m²", min_value=0.0, value=0.0, step=0.5)
        st.markdown("**Trim runs** — linear metres (the trim pack is driven by building shape, not area)")
        t1, t2, t3 = st.columns(3)
        base_lm = t1.number_input("Base / starter run (m)", min_value=0.0, value=0.0, step=0.5)
        top_lm = t2.number_input("Top run + under sills (m)", min_value=0.0, value=0.0, step=0.5)
        opening_lm = t3.number_input("Openings perimeter (m)", min_value=0.0, value=0.0, step=0.5)
        t4, t5 = st.columns(2)
        ext_corner_lm = t4.number_input("External corners total (m)", min_value=0.0, value=0.0, step=0.5)
        int_corner_lm = t5.number_input("Internal corners total (m)", min_value=0.0, value=0.0, step=0.5)
        go = st.form_submit_button("Calculate take-off", type="primary")

    if go:
        st.session_state["clad_calc"] = {
            "product_label": product_label, "texture": texture, "colour": colour.strip(),
            "coverage": coverage, "batten_mm": BATTEN_CENTRES[batten_label], "waste_pct": waste_pct,
            "gable": gable, "other": other, "openings": openings,
            "base_lm": base_lm, "top_lm": top_lm, "opening_lm": opening_lm,
            "ext_corner_lm": ext_corner_lm, "int_corner_lm": int_corner_lm,
            "board_search": (f"{HARDIE_PRODUCTS[product_label]['search']} {texture} {colour}").strip(),
        }
        st.session_state.pop("clad_priced", None)

    data = st.session_state.get("clad_calc")
    if not data:
        return
    lines, meta = _cladding_takeoff(data)
    st.markdown(f"**Net area to clad: {meta['net']:,.1f} m² → {meta['boards']} boards** "
                f"(at {data['coverage']:.2f} m²/board + {data['waste_pct']}% waste · "
                f"~{meta['fpb']} fixings/board).")

    priced = st.session_state.get("clad_priced")
    rows, total = "", 0.0
    for l in lines:
        m = (priced or {}).get(l["key"]) if priced else None
        if m and m.get("price") is not None:
            prod = (f'{_esc(m.get("title") or "?")}<div style="color:var(--muted);font-size:11px">'
                    f'SKU {_esc(m.get("sku") or "—")}</div>')
            unit = f"£{m['price']:,.2f}"
            line_tot = m["price"] * l["qty"]
            total += line_tot
            line = f"£{line_tot:,.2f}"
        elif priced:
            prod = '<span style="color:#ef4444">no match — add manually</span>'
            unit = line = "—"
        else:
            prod = unit = line = "—"
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:6px 10px">{l["item"]}</td>'
                 f'<td style="padding:6px 10px;text-align:center">{l["qty"]}</td>'
                 f'<td style="padding:6px 10px">{l["unit"]}</td>'
                 f'<td style="padding:6px 10px">{prod}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{unit}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{line}</td></tr>')
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:12.5px">'
                '<tr style="text-align:left;color:var(--muted)">'
                '<th style="padding:6px 10px">Item</th>'
                '<th style="padding:6px 10px;text-align:center">Qty</th>'
                '<th style="padding:6px 10px">Unit</th>'
                '<th style="padding:6px 10px">Matched product</th>'
                '<th style="padding:6px 10px;text-align:right">Unit £</th>'
                '<th style="padding:6px 10px;text-align:right">Line £</th></tr>'
                + rows + "</table>", unsafe_allow_html=True)
    if priced:
        st.markdown(f"**Materials subtotal (matched lines, ex-VAT): £{total:,.2f}**")

    b1, b2 = st.columns(2)
    if b1.button("Price from Shopify", key="clad_price"):
        out = {}
        with st.spinner("Pricing from Shopify…"):
            for l in lines:
                try:
                    out[l["key"]] = data_sources.match_quote_variant(None, l["search"])
                except Exception:  # noqa: BLE001
                    out[l["key"]] = None
        st.session_state["clad_priced"] = out
        st.rerun()

    if priced:
        matched = [l for l in lines if priced.get(l["key"])
                   and priced[l["key"]].get("variant_id")]
        if matched and b2.button("Build Shopify draft order", type="primary", key="clad_draft"):
            try:
                li = [{"variantId": priced[l["key"]]["variant_id"], "quantity": l["qty"]}
                      for l in matched]
                do = data_sources.create_draft_order(
                    li, note=f"James Hardie cladding take-off — {data['product_label']} "
                    f"{data['texture']} {data['colour']} — {meta['net']:.1f} m²")
                st.success(f"Created Shopify draft order **{do['name']}** (£{do['total']:,.2f}).")
                st.markdown(f"[Open the Shopify draft order]({do['invoiceUrl']})")
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't create the draft: " + str(e)[:240] + " — Shopify may need the "
                         "**write_draft_orders** scope.")
        if len(matched) < len(lines):
            st.caption(f"{len(lines) - len(matched)} line(s) had no Shopify match — add them to the "
                       "draft manually, or tell me the exact product names and I'll map them.")


# Polycarbonate roof take-off — Molan range only (vendor-locked). Glazing bars run with
# the slope, one more than the number of sheets; sealing tape top, vented tape bottom.
POLY_SHEETS = {
    "10mm Twinwall": "Twinwall", "16mm Multiwall": "Multiwall", "25mm Multiwall": "Multiwall",
    "32mm Multiwall": "Multiwall", "35mm Multiwall": "Multiwall",
}
POLY_COLOURS = ["Clear", "Opal", "Bronze", "Heatguard Opal", "Bronze on Opal"]
POLY_WIDTHS = {"700 mm": 700, "1050 mm": 1050, "1200 mm": 1200, "2100 mm": 2100}
POLY_SYSTEMS = {
    "Self-Supported (16/35mm)": {"end": "Self Supported End Bar",
                                 "inter": "Self Supported Intermediate Bar",
                                 "wallplate": "Wallplate Assembly", "eaves": None},
    "Artisan": {"end": "Artisan Edge Bar + End Cap", "inter": "Artisan Intermediate Bar + End Cap",
                "wallplate": "Artisan Full Wallplate", "eaves": "Artisan Eaves Beam"},
}
POLY_BAR_LENGTHS = [2, 3, 4, 6]


def _poly_takeoff(inp):
    """Roof dimensions + sheet/system choice -> Molan take-off lines. Each line carries
    a 'search' string matched against Molan products only."""
    import math
    width, rake = inp["width"], inp["rake"]
    sw_m = inp["sheet_width_mm"] / 1000.0
    sheets = math.ceil(width / sw_m) if (width and sw_m) else 0
    barlen = next((b for b in POLY_BAR_LENGTHS if b >= rake), 6) if rake else 0
    inter = max(0, sheets - 1)
    ends = 2 if sheets else 0
    sysd = POLY_SYSTEMS[inp["system"]]
    bc = inp["bar_colour"]
    kind = POLY_SHEETS[inp["sheet_type"]]
    thick = inp["sheet_type"].split("mm")[0] + "mm"
    colour = inp["colour"]
    pieces = lambda run, plen: math.ceil(run / plen) if run > 0 else 0  # noqa: E731
    lines = [
        ("sheet", f"{thick} {colour} {kind} sheet — {inp['sheet_width_mm']}mm × {rake:.1f}m",
         sheets, "sheet", f"{thick} {colour} {kind} Polycarbonate Sheet"),
        ("inter", f"{inp['system']} intermediate bar {bc} — {barlen}m", inter, "bar",
         f"{sysd['inter']} {bc} {barlen}m"),
        ("end", f"{inp['system']} end/edge bar {bc} — {barlen}m", ends, "bar",
         f"{sysd['end']} {bc} {barlen}m"),
        ("wallplate", f"Wallplate {bc} (top, along {width:.1f}m)", pieces(width, 4), "length",
         f"{sysd['wallplate']} {bc} 4m"),
    ]
    if sysd["eaves"]:
        lines.append(("eaves", f"Eaves beam {bc} (front, along {width:.1f}m)", pieces(width, 4),
                      "length", f"{sysd['eaves']} {bc} 4m"))
    if inp["include_acc"]:
        lines += [
            ("antidust", "Anti-dust tape (seals sheet tops)", max(1, pieces(width, 33)), "roll",
             "Anti Dust Tape"),
            ("foil", "Vented foil tape (sheet bottoms)", max(1, pieces(width, 33)), "roll",
             "Aluminium Foil Blanking Tape"),
        ]
    out = [{"key": k, "item": it, "qty": q, "unit": u, "search": s}
           for k, it, q, u, s in lines if q > 0]
    note = ""
    if rake > 6:
        note = (f"Slope is {rake:.1f}m — longer than a 6m bar/sheet, so bars and sheets will "
                "need joining (extra H-section/joints not yet added).")
    return out, {"sheets": sheets, "bars": inter + ends, "barlen": barlen, "note": note}


EZGLAZE_COLOURS = {
    "Clear": ("EZ Glaze Clear", "CLR"),
    "Breeze Blue": ("EZ Glaze Breeze Blue", "BREEZE"),
    "Solar Ice": ("EZ Glaze Solar Ice", "SOLARICE"),
    "Beehive Clear": ("Beehive EZ Glaze", "BEEHIVECLR"),
}
EZGLAZE_LENGTHS = [2.5, 3, 3.5, 4, 6, 7]


def _ezglaze_takeoff(inp):
    """EZ Glaze corrugated roof → Molan take-off. Sheets are SKU-exact; accessory
    quantities are estimates to confirm."""
    import math
    width, slope, cover = inp["width"], inp["slope"], inp["cover"]
    sheets = math.ceil(width / cover) if (width and cover) else 0
    length = next((L for L in EZGLAZE_LENGTHS if L >= slope), 7) if slope else 0
    cname, ccode = EZGLAZE_COLOURS[inp["colour"]]
    # length suffix in the SKU (2.5 is written "25" for most, "2.5" for Breeze)
    suffixes = (["25", "2.5"] if length == 2.5 else
                [("%g" % length)])
    sheet_skus = [f"EZGLAZE{ccode}-{s}" for s in suffixes]
    lines = [
        {"key": "sheet", "item": f"{cname} corrugated sheet — {length:g}m",
         "qty": sheets, "unit": "sheet", "skus": sheet_skus, "search": cname},
        {"key": "foam", "item": "EZ Glaze foam sealing strip (eaves/ridge)",
         "qty": max(1, sheets), "unit": "strip", "skus": ["EZGLAZEFOAM"], "search": "EZ Glaze Foam"},
        {"key": "screws", "item": "EZ Glaze screws & washers (50 pack)",
         "qty": max(1, math.ceil(sheets / 3)), "unit": "pack", "skus": ["EZGLAZESCREW50"],
         "search": "EZ Glaze Screw 50"},
        {"key": "wallconn", "item": f"EZ Glaze 60mm wall connector (2m, along {width:.1f}m)",
         "qty": max(1, math.ceil(width / 2)) if width else 0, "unit": "length",
         "skus": ["EZGLAZEW-CONN2M"], "search": "EZ Glaze Wall Connector"},
    ]
    out = [l for l in lines if l["qty"] > 0]
    return out, {"sheets": sheets, "length": length}


def _render_ezglaze_calc():
    st.caption("EZ Glaze corrugated roof, **Molan only**. Sheets are matched to the exact "
               "EZ Glaze length; accessory quantities are estimates — confirm against the job.")
    with st.form("ezg"):
        c1, c2, c3 = st.columns(3)
        colour = c1.selectbox("Colour", list(EZGLAZE_COLOURS))
        cover = c2.number_input("Sheet cover width m", min_value=0.3, value=1.0, step=0.05,
                                help="EZ Glaze corrugated cover width — confirm for your profile.")
        c3.markdown("&nbsp;")
        a1, a2 = st.columns(2)
        width = a1.number_input("Roof width m", min_value=0.0, value=0.0, step=0.1)
        slope = a2.number_input("Slope length m (eaves→ridge)", min_value=0.0, value=0.0, step=0.1)
        go = st.form_submit_button("Calculate take-off", type="primary")
    if go:
        st.session_state["ezg_calc"] = {"colour": colour, "cover": cover,
                                        "width": width, "slope": slope}
        st.session_state.pop("ezg_priced", None)
    data = st.session_state.get("ezg_calc")
    if not data:
        return
    lines, meta = _ezglaze_takeoff(data)
    if not lines:
        st.info("Enter the roof width and slope length to calculate.")
        return
    st.markdown(f"**{meta['sheets']} sheets across, each {meta['length']:g}m long**")
    priced = st.session_state.get("ezg_priced")
    rows, total = "", 0.0
    for l in lines:
        m = (priced or {}).get(l["key"]) if priced else None
        if m and m.get("price") is not None:
            prod = (f'{_esc(m.get("title") or "?")}<div style="color:var(--muted);font-size:11px">'
                    f'SKU {_esc(m.get("sku") or "—")}</div>')
            unit = f"£{m['price']:,.2f}"
            lt = m["price"] * l["qty"]
            total += lt
            line = f"£{lt:,.2f}"
        elif priced:
            prod = '<span style="color:#ef4444">no Molan match — add manually</span>'
            unit = line = "—"
        else:
            prod = unit = line = "—"
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:6px 10px">{_esc(l["item"])}</td>'
                 f'<td style="padding:6px 10px;text-align:center">{l["qty"]}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{unit}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{line}</td>'
                 f'<td style="padding:6px 10px">{prod}</td></tr>')
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:12.5px">'
                '<tr style="text-align:left;color:var(--muted)">'
                '<th style="padding:6px 10px">Item</th><th style="padding:6px 10px;text-align:center">Qty</th>'
                '<th style="padding:6px 10px;text-align:right">Unit £</th>'
                '<th style="padding:6px 10px;text-align:right">Line £</th>'
                '<th style="padding:6px 10px">Matched Molan product</th></tr>'
                + rows + "</table>", unsafe_allow_html=True)
    if priced:
        st.markdown(f"**Materials subtotal (matched, ex-VAT): £{total:,.2f}**")
    b1, b2 = st.columns(2)
    if b1.button("Price from Molan", key="ezg_price"):
        out = {}
        with st.spinner("Pricing from Molan…"):
            for l in lines:
                hit = None
                for sku in l["skus"]:
                    try:
                        hit = data_sources.match_quote_variant(sku, l["search"], brand="Molan")
                    except Exception:  # noqa: BLE001
                        hit = None
                    if hit:
                        break
                out[l["key"]] = hit
        st.session_state["ezg_priced"] = out
        st.rerun()
    if priced:
        matched = [l for l in lines if priced.get(l["key"]) and priced[l["key"]].get("variant_id")]
        if matched and b2.button("Build Shopify draft order", type="primary", key="ezg_draft"):
            try:
                li = [{"variantId": priced[l["key"]]["variant_id"], "quantity": l["qty"]}
                      for l in matched]
                do = data_sources.create_draft_order(
                    li, note=f"EZ Glaze roof (Molan) — {data['colour']} — "
                    f"{data['width']}×{data['slope']}m")
                st.success(f"Created Shopify draft order **{do['name']}** (£{do['total']:,.2f}).")
                st.markdown(f"[Open the Shopify draft order]({do['invoiceUrl']})")
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't create the draft: " + str(e)[:240])
        if len(matched) < len(lines):
            st.caption(f"{len(lines) - len(matched)} line(s) had no Molan match — tell me the exact "
                       "product name/SKU and I'll map it.")


def render_poly_calc():
    st.markdown("### 🪟 Polycarbonate roof calculator — Molan")
    rtype = st.radio("Roof type", ["Multiwall + glazing bars", "EZ Glaze corrugated"],
                     horizontal=True, key="poly_rtype")
    if rtype.startswith("EZ"):
        _render_ezglaze_calc()
        return
    _render_multiwall_poly()


def _render_multiwall_poly():
    st.caption("Works out sheets, glazing bars, wallplate/eaves and tapes for a polycarbonate "
               "roof, **priced from Molan products only**. Glazing bars run with the slope "
               "(one more than the number of sheets).")
    with st.form("poly"):
        c1, c2, c3 = st.columns(3)
        sheet_type = c1.selectbox("Sheet", list(POLY_SHEETS))
        colour = c2.selectbox("Colour", POLY_COLOURS)
        sheet_width_label = c3.selectbox("Sheet width", list(POLY_WIDTHS), index=1)
        c4, c5, c6 = st.columns(3)
        system = c4.selectbox("Glazing system", list(POLY_SYSTEMS))
        bar_colour = c5.selectbox("Bar colour", ["White", "Brown"])
        include_acc = c6.checkbox("Include tapes", value=True)
        st.markdown("**Roof size** (width = along the wall; slope = eaves-to-ridge length)")
        a1, a2 = st.columns(2)
        width = a1.number_input("Roof width m", min_value=0.0, value=0.0, step=0.1)
        rake = a2.number_input("Slope length m", min_value=0.0, value=0.0, step=0.1)
        go = st.form_submit_button("Calculate take-off", type="primary")

    if go:
        st.session_state["poly_calc"] = {
            "sheet_type": sheet_type, "colour": colour,
            "sheet_width_mm": POLY_WIDTHS[sheet_width_label], "system": system,
            "bar_colour": bar_colour, "include_acc": include_acc, "width": width, "rake": rake}
        st.session_state.pop("poly_priced", None)

    data = st.session_state.get("poly_calc")
    if not data:
        return
    lines, meta = _poly_takeoff(data)
    if not lines:
        st.info("Enter the roof width and slope length to calculate.")
        return
    st.markdown(f"**{meta['sheets']} sheets across · {meta['bars']} glazing bars "
                f"({meta['barlen']}m)**")
    if meta["note"]:
        st.warning(meta["note"])

    priced = st.session_state.get("poly_priced")
    rows, total = "", 0.0
    for l in lines:
        m = (priced or {}).get(l["key"]) if priced else None
        if m and m.get("price") is not None:
            prod = (f'{_esc(m.get("title") or "?")}<div style="color:var(--muted);font-size:11px">'
                    f'SKU {_esc(m.get("sku") or "—")}</div>')
            unit = f"£{m['price']:,.2f}"
            lt = m["price"] * l["qty"]
            total += lt
            line = f"£{lt:,.2f}"
        elif priced:
            prod = '<span style="color:#ef4444">no Molan match — add manually</span>'
            unit = line = "—"
        else:
            prod = unit = line = "—"
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:6px 10px">{_esc(l["item"])}</td>'
                 f'<td style="padding:6px 10px;text-align:center">{l["qty"]}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{unit}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{line}</td>'
                 f'<td style="padding:6px 10px">{prod}</td></tr>')
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:12.5px">'
                '<tr style="text-align:left;color:var(--muted)">'
                '<th style="padding:6px 10px">Item</th>'
                '<th style="padding:6px 10px;text-align:center">Qty</th>'
                '<th style="padding:6px 10px;text-align:right">Unit £</th>'
                '<th style="padding:6px 10px;text-align:right">Line £</th>'
                '<th style="padding:6px 10px">Matched Molan product</th></tr>'
                + rows + "</table>", unsafe_allow_html=True)
    if priced:
        st.markdown(f"**Materials subtotal (matched, ex-VAT): £{total:,.2f}**")

    b1, b2 = st.columns(2)
    if b1.button("Price from Molan", key="poly_price"):
        out = {}
        with st.spinner("Pricing from Molan…"):
            for l in lines:
                try:
                    out[l["key"]] = data_sources.match_quote_variant(None, l["search"], brand="Molan")
                except Exception:  # noqa: BLE001
                    out[l["key"]] = None
        st.session_state["poly_priced"] = out
        st.rerun()
    if priced:
        matched = [l for l in lines if priced.get(l["key"]) and priced[l["key"]].get("variant_id")]
        if matched and b2.button("Build Shopify draft order", type="primary", key="poly_draft"):
            try:
                li = [{"variantId": priced[l["key"]]["variant_id"], "quantity": l["qty"]}
                      for l in matched]
                do = data_sources.create_draft_order(
                    li, note=f"Polycarbonate roof (Molan) — {data['sheet_type']} {data['colour']} "
                    f"— {data['width']}×{data['rake']}m")
                st.success(f"Created Shopify draft order **{do['name']}** (£{do['total']:,.2f}).")
                st.markdown(f"[Open the Shopify draft order]({do['invoiceUrl']})")
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't create the draft: " + str(e)[:240])
        if len(matched) < len(lines):
            st.caption(f"{len(lines) - len(matched)} line(s) had no Molan match — tell me the exact "
                       "Molan product names and I'll map them.")


def render_quotes():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Quotes</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.caption("Reads the New Orders & Quotes emails, prices them from Shopify, and prepares a "
               "**Shopify draft order** + an **Outlook draft reply** (with the draft-order number in "
               "the subject) for you to review and send. Uses your Anthropic key.")

    with st.expander("🔧 Shopify connection check (run if quotes won't price or draft)"):
        if st.button("Run Shopify check", key="shopdiag"):
            static = bool(data_sources.get_secret("SHOPIFY_ADMIN_TOKEN"))
            st.write("**Token source:**",
                     "Static SHOPIFY_ADMIN_TOKEN" if static else "client-credentials (Client ID/Secret)")
            cid = data_sources.get_secret("SHOPIFY_CLIENT_ID") or ""
            st.write("**Client ID in use:**", (cid[:10] + "…") if cid else "(none)")
            try:
                info = data_sources.shopify_token_scopes()
                st.write("**App this token belongs to:**", info.get("app") or "(unknown)")
                scopes = info.get("scopes") or []
                st.write("**Scopes this token actually has:**", scopes or "(none)")
                need = ["read_products", "read_orders", "write_draft_orders"]
                missing = [s for s in need if s not in scopes]
                if missing:
                    st.error("MISSING scopes: " + ", ".join(missing)
                             + " — the token predates the version that granted them; "
                             "generate a NEW token after releasing and update the secret.")
                else:
                    st.success("All required scopes present ✓")
            except Exception as e:  # noqa: BLE001
                st.error("Token/auth failed: " + str(e)[:300]
                         + " — the token is invalid or not installed.")
            try:
                v = data_sources.shopify_search_variants("Hardie Plank", first=1)
                st.write("**Product read test:**", "OK ✓" if v else "no results", (v or [])[:1])
            except Exception as e:  # noqa: BLE001
                st.error("Product read failed: " + str(e)[:300])

    mode = st.radio("View", ["📧 Email requests", "🧱 Hardie cladding calculator",
                             "🪟 Polycarbonate calculator"],
                    horizontal=True, label_visibility="collapsed")
    if mode.startswith("🧱"):
        render_cladding_calc()
        return
    if mode.startswith("🪟"):
        render_poly_calc()
        return

    data = _quote_emails()
    if data.get("error"):
        msg = data["error"]
        st.warning("Couldn't read the quotes folder: " + msg[:160]
                   + (" — is Outlook connected?" if "token" in msg.lower() else ""))
        return
    emails = data["emails"]
    if not emails:
        st.success("No quote emails in the folder right now.")
        return

    by_id = {e["id"]: e for e in emails}
    cache = _ensure_parsed(emails)

    st.markdown("#### Quote requests")
    c1, c2 = st.columns([4, 1])
    query = c1.text_input(
        "Search", label_visibility="collapsed", key="qsearch",
        placeholder="🔍 Search by customer, product, postcode or subject…").strip().lower()
    if c2.button("↻ Refresh", use_container_width=True):
        st.session_state.pop("quote_parse", None)
        _quote_emails.clear()
        st.rerun()

    def _hay(e):
        p = cache.get(e["id"]) or {}
        return " ".join(str(x) for x in [
            e.get("from_name"), e.get("from"), e.get("subject"), e.get("preview"),
            p.get("customer_name"), p.get("product_range"), p.get("postcode"),
            p.get("summary")] if x).lower()

    shown = [e for e in emails if query in _hay(e)] if query else emails
    if query and not shown:
        st.info("No requests match your search.")
        return

    _render_quote_overview(shown, cache)
    st.divider()

    def _picker_label(e):
        p = cache.get(e["id"]) or {}
        name = p.get("customer_name") or e.get("from_name") or e.get("from") or "?"
        pr = p.get("product_range")
        bits = [e["received"], name]
        if pr and pr.lower() != "unclear":
            bits.append(pr)
        bits.append(e["subject"])
        return " · ".join(str(b) for b in bits if b)

    lbl = {e["id"]: _picker_label(e) for e in emails}
    picks = st.multiselect(
        "Pick one or more quote requests to build (type to search by name, product or subject)",
        [e["id"] for e in shown], format_func=lambda eid: lbl.get(eid, eid))
    st.caption(f"Selected **{len(picks)}**. Building reads each email with AI (~1p each, cached) "
               "and prices it from Shopify. Nothing is sent — you get a draft to review.")

    if st.button("Read & build quote(s)", type="primary", disabled=not picks):
        st.session_state["quote_built"] = list(picks)

    built = [eid for eid in (st.session_state.get("quote_built") or []) if eid in by_id]
    if not built:
        return

    if len(built) == 1:
        e = by_id[built[0]]
        st.caption(e["preview"])
        _render_quote_block(e)
    else:
        for eid in built:
            e = by_id[eid]
            tag = e["from_name"] or e["from"] or "?"
            with st.expander(f"{tag} — {e['subject']}", expanded=True):
                st.caption(e["preview"])
                _render_quote_block(e)


def _rules_table(headers, rows):
    th = "".join(f'<th style="text-align:left;padding:7px 12px;color:var(--muted);'
                 f'font-weight:600">{h}</th>' for h in headers)
    trs = "".join('<tr style="border-top:1px solid var(--line)">'
                  + "".join(f'<td style="padding:7px 12px">{c}</td>' for c in row) + "</tr>"
                  for row in rows)
    return (f'<table style="width:100%;border-collapse:collapse;font-size:13px;'
            f'border:1px solid var(--line);border-radius:6px;overflow:hidden;margin:2px 0 10px">'
            f'<tr style="background:var(--card)">{th}</tr>{trs}</table>')


# --- Finance (admin-only) -------------------------------------------------
_RANGE_RULES = [
    ("Polycarbonate", ("polycarbonate", "twinwall", "multiwall", "ezglaze", "ez glaze",
                       "ez-glaze", "glazing bar", "wallplate", "eaves beam", "f-section",
                       "h profile", "h-section", "corrugated poly")),
    ("Doors", ("door", "deanta", "latch", "hinge", "handle", "architrave")),
    ("Roofline & Cladding", ("fascia", "soffit", "cladding", "hardie", "bargeboard",
                             "roofline", "capping", "shiplap")),
    ("Guttering", ("gutter", "downpipe", "hopper", "running outlet", "guttering")),
    ("Roofing", ("flashing", "ridge", "roof sheet", "felt", "tile", "slate", "verge", "purlin")),
    ("Bathroom", ("basin", "toilet", "bath", "shower", "ceramic", "suite", "pedestal",
                  "cistern", "tap", "wc")),
    ("Insulation", ("insulation", "celotex", "kingspan", "rockwool", "pir board")),
    ("PVC & Trims", ("pvc", "packer", "trim", "sheeting")),
]


def _classify_range(text):
    t = (text or "").lower()
    for name, kws in _RANGE_RULES:
        if any(k in t for k in kws):
            return name
    return "Other"


@st.cache_data(ttl=3600, show_spinner=False)
def _sku_name_index():
    lk = load_lookup()
    return {_norm_code(it.get("sku")): (it.get("name") or "")
            for it in (lk["items"] if lk else [])}


def _order_range(order_items_text):
    idx = _sku_name_index()
    ranges = []
    for nk, d in _parse_order_items(order_items_text).items():
        ranges.append(_classify_range(idx.get(nk) or d.get("sku") or ""))
    distinct = {r for r in ranges if r != "Other"}
    if len(distinct) == 1:
        return distinct.pop()
    if len(distinct) > 1:
        return "Mixed"
    return "Other"


def _order_anomalies(o):
    flags = []
    if o.get("margin") is None:
        flags.append("no margin")
    elif o["margin"] < 0:
        flags.append("loss-making")
    elif o["margin"] > 50:
        flags.append("margin >50% (check cost/credit note)")
    if not o.get("agreed_cost"):
        flags.append("no agreed cost")
    if not o.get("supplier"):
        flags.append("no supplier")
    if not o.get("has_invoice"):
        flags.append("no invoice")
    return flags


def _est_margin_gbp(o):
    """Approx £ margin from agreed cost + live margin % (assumes margin-on-sell)."""
    m, c = o.get("margin"), o.get("agreed_cost")
    if m is None or c is None or m >= 100:
        return None
    return c * (m / 100.0) / (1 - m / 100.0)


@st.cache_data(ttl=1800, show_spinner=False)
def _finance_data():
    try:
        data = data_sources.fetch_finance_orders()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    # Enrich once per cache period (not on every rerun): range, £ estimate, anomalies.
    for o in data.get("orders", []):
        o["range"] = _order_range(o.get("order_items"))
        o["est_gbp"] = _est_margin_gbp(o)
        o["flags"] = _order_anomalies(o)
    return data


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


_MONTH_NAMES = ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


def _month_label(m):
    """'2026-05' -> 'MAY 2026'."""
    if not m or len(str(m)) < 7:
        return m or "—"
    try:
        return f"{_MONTH_NAMES[int(str(m)[5:7])]} {str(m)[:4]}"
    except (ValueError, IndexError):
        return m


def _render_qbo_panel():
    """QuickBooks connection (read-only) — Connect / status / Disconnect. Used by Finance."""
    flash = st.session_state.pop("qbo_flash", None)
    if flash:
        st.success(flash)
    ferr = st.session_state.pop("qbo_flash_err", None)
    if ferr:
        st.error(ferr)
    try:
        connected = data_sources.qbo_is_connected()
    except Exception as e:  # noqa: BLE001
        st.warning("Couldn't reach the QuickBooks token store on Monday: " + str(e)[:160])
        return
    if connected:
        co = data_sources.qbo_company_name()
        st.success(f"QuickBooks is connected{f' — **{co}**' if co else ''} · read-only.")
        if st.button("Disconnect QuickBooks"):
            try:
                data_sources.qbo_disconnect()
                st.session_state["qbo_flash"] = "Disconnected from QuickBooks."
            except Exception as e:  # noqa: BLE001
                st.session_state["qbo_flash_err"] = str(e)[:200]
            st.rerun()
        return
    import secrets as _secrets
    try:
        state = st.session_state.get("qbo_state") or _secrets.token_urlsafe(24)
        st.session_state["qbo_state"] = state
        url = data_sources.qbo_auth_url(state)
        st.link_button("Connect QuickBooks", url, type="primary", use_container_width=False)
        st.caption("Read-only. You'll sign in to QuickBooks, choose your company and approve — then "
                   "you're brought back here. Needed for statement reconciliation & payment planning.")
        st.caption(f"If the button does nothing, open this link directly: {url}")
    except Exception as e:  # noqa: BLE001
        st.warning(str(e)[:200] + "  · Add QBO_CLIENT_ID and QBO_CLIENT_SECRET in "
                   "Settings → Secrets, then reload.")


def _qbo_connected_quiet():
    try:
        return data_sources.qbo_is_connected()
    except Exception:  # noqa: BLE001
        return False


def _due_label(due_str):
    """'in 12 days' / 'due today' / 'OVERDUE 3 days' from a YYYY-MM-DD due date; '' if none."""
    if not due_str:
        return ""
    try:
        from datetime import date
        d = date.fromisoformat(str(due_str)[:10])
    except Exception:  # noqa: BLE001
        return ""
    days = (d - now_uk().date()).days
    if days < 0:
        return f"⚠ overdue {abs(days)} day{'s' if abs(days) != 1 else ''}"
    if days == 0:
        return "due today"
    return f"in {days} day{'s' if days != 1 else ''}"


class _PulledFile:
    """Minimal stand-in for a Streamlit uploaded file, so a statement pulled from the accounts@
    inbox flows through the exact same reconcile pipeline as a manual upload."""
    def __init__(self, name, data):
        self.name = name or "statement.pdf"
        self._data = data or b""
        self.size = len(self._data)

    def getvalue(self):
        return self._data


def _gbp(x):
    """Money as a string with thousands separators, e.g. 1000 -> '£1,000.00'. Blank/NaN -> ''."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return x if x not in (None, "") else ""
    if x != x:            # NaN (e.g. a missing value pandas turned into NaN) -> blank, not '£nan'
        return ""
    return f"£{x:,.2f}"


def _subnav(key, options):
    """Slick sidebar sub-menu — vertical full-width buttons (one per line), matching the main
    nav. Highlights the active view and mirrors the choice onto st.session_state[key] so the rest
    of the app reads it exactly as it did with st.radio."""
    cur = st.session_state.get(key)
    if cur not in options:
        cur = options[0]
        st.session_state[key] = cur
    for opt in options:
        _pad, _btn = st.columns([0.06, 0.94])
        with _btn:
            if st.button(opt, key=f"_sb_{key}_{opt}", use_container_width=True,
                         type=("primary" if cur == opt else "secondary")):
                if opt != cur:
                    st.session_state[key] = opt
                    st.rerun()


def _remittance_text(sup, lines, total, ref):
    """Plain-text remittance advice for the selected invoices."""
    body = [f"  {p['inv']}"
            + (f"  (order {p['order']})" if p.get("order") else "")
            + (f"  £{p['amt']:,.2f}" if isinstance(p.get("amt"), (int, float)) else "")
            for p in lines]
    return (f"REMITTANCE ADVICE\n\nTo: {sup}\nReference: {ref}\n\n"
            "Please find below the invoices included in this payment:\n\n" + "\n".join(body)
            + f"\n\nTotal paid: £{total:,.2f}\n\nKind regards,\nTrade Superstore Online\nAccounts")


def _review_reminder_email(sup, action_rows):
    """Body of the 'please review these' nudge to a colleague, for a statement's unapproved lines."""
    tot = sum(r["amt"] for r in action_rows if isinstance(r["amt"], (int, float)))
    lines = [f"  - {r['inv']}"
             + (f"  (order {r['order']})" if r["order"] else "")
             + (f"  £{r['amt']:,.2f}" if isinstance(r["amt"], (int, float)) else "")
             for r in action_rows]
    body = (f"Hi,\n\nThese {sup} invoices are on the latest statement but still need reviewing on "
            "Monday (they haven't been approved to QuickBooks yet). Please review each one and "
            "either approve it or raise a query, ASAP, so they're ready for payment:\n\n"
            + "\n".join(lines)
            + f"\n\nTotal: £{tot:,.2f}\n\nThanks")
    return f"{sup}: {len(action_rows)} invoice(s) need reviewing on Monday", body


def _statement_file_text(up):
    """Extract text from an Excel/CSV statement so the AI can parse it like a PDF."""
    if up.name.lower().endswith(".csv"):
        return up.getvalue().decode("utf-8", "ignore")
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(up.getvalue()), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"=== SHEET: {ws.title} ===")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(c.strip() for c in cells):
                out.append(" | ".join(cells))
    return "\n".join(out)


def _pay_workflow(sup, vid, pay_lines, key, live_verify=False):
    """Tick invoices → build a remittance → send it → mark paid in QuickBooks. Reused by both a
    fresh reconciliation and a reopened saved one, so you never reconcile a statement twice.
    live_verify re-checks each line against QuickBooks first, so a bill that's been paid or cleared
    since the statement was reconciled drops off before you'd pay it again."""
    if live_verify and vid:
        try:
            fresh = {str(b["id"]): b for b in data_sources.qbo_vendor_bills(vid)}
            keep, dropped = [], 0
            for p in pay_lines:
                b = fresh.get(str(p.get("bill_id")))
                if b is None or b.get("paid"):
                    dropped += 1
                else:
                    keep.append(p)
            pay_lines = keep
            if dropped:
                st.caption(f"↻ {dropped} invoice(s) have since been paid or cleared in QuickBooks — "
                           "removed from this list.")
        except Exception:  # noqa: BLE001
            pass
    if not pay_lines:
        st.info("Nothing left ready to pay for this supplier.")
        return
    _pk = key
    st.markdown("##### 💷 Pay these — tick, build a remittance, send it")
    pay_df = pd.DataFrame([{"Pay": True, "Invoice": p["inv"], "Order": p["order"],
                            "Amount": _gbp(p["amt"]), "Due": p.get("due", ""),
                            "Approved": "✅ Approved" if p.get("bill_id") else "⚠ NOT approved"}
                           for p in pay_lines])
    edited = st.data_editor(
        pay_df, hide_index=True, use_container_width=True, key=f"payedit_{_pk}",
        disabled=[c for c in pay_df.columns if c != "Pay"],
        column_config={"Pay": st.column_config.CheckboxColumn("Pay"),
                       "Approved": st.column_config.TextColumn(
                           "Approved",
                           help="Approved & entered in QuickBooks. Only approved invoices reach "
                                "this list — this column is just a safety check.")})
    if any(not p.get("bill_id") for p in pay_lines):
        st.warning("⚠ Something here isn't approved in QuickBooks — untick it before paying.")
    try:
        ticks = edited["Pay"]
        picked_lines = [pay_lines[i] for i in range(len(pay_lines)) if bool(ticks.iloc[i])]
    except Exception:  # noqa: BLE001
        picked_lines = list(pay_lines)
    rem_total = sum(p["amt"] for p in picked_lines if isinstance(p["amt"], (int, float)))
    st.markdown(f"**{len(picked_lines)} invoice(s) selected · £{rem_total:,.2f}**")
    # Short supplier name in front of the B-date so two same-day remittances don't collide on the
    # QuickBooks Ref no. (DocNumber must be unique per bill payment), e.g. "PJH B160826".
    ref = st.text_input("Remittance / payment reference (also the QuickBooks Ref no.)",
                        key=f"remref_{_pk}",
                        value=f"{sup.split()[0] if sup else 'REM'} B{now_uk().strftime('%d%m%y')}")
    # Build the remittance-advice PDF the supplier receives (QuickBooks-style document).
    pdf_lines = [{"bill_no": p.get("bill_no") or p.get("inv"), "bill_date": p.get("bill_date"),
                  "due_date": p.get("due_date"),
                  "original": p.get("original") if p.get("original") is not None else p.get("amt"),
                  "balance": p.get("balance") if p.get("balance") is not None else p.get("amt"),
                  "payment": p.get("amt")} for p in picked_lines]
    pdf_bytes = None
    if picked_lines:
        try:
            pdf_bytes = data_sources.build_remittance_pdf(
                sup, ref, now_uk().strftime("%d/%m/%Y"), pdf_lines, rem_total)
        except Exception as e:  # noqa: BLE001
            st.caption("Couldn't build the remittance PDF: " + str(e)[:160])
    pdf_name = ("Remittance_Advice_" + re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_")
                + "_from_Trade_Superstore_Online.pdf")
    if pdf_bytes:
        st.download_button("⬇ Preview / download remittance PDF", pdf_bytes, file_name=pdf_name,
                           mime="application/pdf", key=f"rempdf_{_pk}")
    cover = (f"Hi,\n\nPlease find attached our remittance advice ({ref}) for a total of "
             f"£{rem_total:,.2f}.\n\nKind regards,\nTrade Superstore Online\nAccounts")
    e1, e2 = st.columns([2, 1])
    rem_to = e1.text_input("Send remittance to (supplier accounts email)",
                           value=SUPPLIER_EMAILS.get(_norm_code(sup), ""), key=f"remto_{_pk}")
    if e2.button("✉ Send remittance", key=f"remsend_{_pk}", type="primary",
                 use_container_width=True,
                 disabled=not (rem_to.strip() and picked_lines)):
        subj = f"Remittance Advice — {ref}"
        sent = drafted = False
        dlink = None
        try:
            data_sources.send_supplier_email(SUPPLIER_FROM_MAILBOX, rem_to.strip(), subj, cover,
                                             pdf_bytes=pdf_bytes, pdf_name=pdf_name)
            sent = True
        except Exception:  # noqa: BLE001
            try:
                dlink = data_sources.create_supplier_draft(SUPPLIER_FROM_MAILBOX, rem_to.strip(),
                                                           subj, cover, pdf_bytes=pdf_bytes,
                                                           pdf_name=pdf_name)
                drafted = True
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't send or draft: " + str(e)[:200])
        if sent or drafted:
            link = f" [Open the draft]({dlink})" if dlink else ""
            st.success(f"Remittance PDF {'sent to' if sent else 'drafted for'} "
                       f"{rem_to.strip()}." + link)
    # ---- Mark paid in QuickBooks (writes a BillPayment). Confirmed, never automatic. ----
    st.markdown("**Mark paid in QuickBooks**")
    try:
        banks = data_sources.qbo_bank_accounts()
    except Exception as e:  # noqa: BLE001
        banks = []
        st.caption("Couldn't read your QuickBooks bank accounts: " + str(e)[:150])
    if banks:
        bmap = {b["name"]: b["id"] for b in banks}
        bank = st.selectbox("Pay from (QuickBooks bank account)", list(bmap.keys()), key=f"bank_{_pk}")
        mpend = f"markpend_{_pk}"
        if st.button(f"Mark {len(picked_lines)} paid in QuickBooks", key=f"markpaid_{_pk}",
                     disabled=not picked_lines):
            st.session_state[mpend] = True
        if st.session_state.get(mpend):
            st.warning(f"Record a **£{rem_total:,.2f}** bill payment in QuickBooks from **{bank}**, "
                       f"settling **{len(picked_lines)}** invoice(s), reference **{ref}**? This "
                       "writes to QuickBooks and marks them paid. You still pay the money via your "
                       "bank separately.")
            yy, nn = st.columns(2)
            if yy.button("Yes — mark paid in QuickBooks", key=f"markyes_{_pk}", type="primary"):
                st.session_state.pop(mpend, None)
                try:
                    data_sources.qbo_pay_bills(
                        vid, bmap[bank],
                        [{"bill_id": p["bill_id"], "amount": p["amt"]} for p in picked_lines],
                        memo=ref, doc_no=ref, date=now_uk().strftime("%Y-%m-%d"))
                    st.success(f"✅ Marked {len(picked_lines)} invoice(s) paid in QuickBooks "
                               f"(ref {ref}). Now pay £{rem_total:,.2f} via your bank.")
                    st.session_state.pop("_stmt_bills_cache", None)
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't mark paid: " + str(e)[:250])
            if nn.button("Cancel", key=f"markno_{_pk}"):
                st.session_state.pop(mpend, None)
                st.rerun()


@st.cache_data(ttl=86400, show_spinner=False, max_entries=64)
def _parse_statement(content_hash, _pdf_bytes=None, _text=None):
    """Read a statement with Claude, cached by CONTENT hash so the same statement is never parsed
    twice — the parse is the slow, paid step of reconciliation. (_pdf_bytes/_text are underscore-
    prefixed so Streamlit keys the cache on the hash alone, not the raw bytes.)"""
    return data_sources.read_statement_pdf(pdf_bytes=_pdf_bytes, text=_text)


def _bulk_reconcile_one(s, limits):
    """Headless reconcile of ONE pulled statement → saves a snapshot. Returns a short status line.
    A quick first pass: matches statement invoices to QuickBooks bills by number (no Monday
    cross-check — open the supplier individually for that). Only bills that are open in QuickBooks
    become payable, so nothing unapproved can slip into the pay list."""
    nm, by = data_sources.fetch_statement_attachment(
        SUPPLIER_FROM_MAILBOX, s["message_id"], s["attachment_id"])
    if not by:
        return f"⚠ {s.get('supplier', '?')}: couldn't download the statement"
    import hashlib
    if (nm or "").lower().endswith(".pdf"):
        stmt = _parse_statement(hashlib.sha1(by).hexdigest(), _pdf_bytes=by)
    else:
        _txt = _statement_file_text(_PulledFile(nm, by))
        stmt = _parse_statement(hashlib.sha1(_txt.encode("utf-8", "ignore")).hexdigest(), _text=_txt)
    sup = stmt.get("supplier") or s.get("supplier") or "?"
    # Resolve the QuickBooks vendor: learned mapping first, then auto-match by name.
    try:
        mp = (data_sources.qbo_vendor_map_load() or {}).get(_norm_code(sup))
    except Exception:  # noqa: BLE001
        mp = None
    vid = mp["id"] if mp else None
    if not vid:
        auto = data_sources.qbo_find_vendor(sup)
        vid = auto["id"] if auto else None
    if not vid:
        return f"⚠ {sup}: no QuickBooks vendor match — open it manually to pick one"
    bills = data_sources.qbo_vendor_bills(vid)
    try:
        paymap = data_sources.qbo_vendor_payments(vid)
    except Exception:  # noqa: BLE001
        paymap = {}
    bmap = {_norm_inv_no(b["doc_no"], sup): b for b in bills if b.get("doc_no")}
    rows, pay_lines = [], []
    to_pay = stmt_total = 0.0
    n_pay = n_paid = n_missing = 0
    for ln in (stmt.get("lines") or []):
        if (ln.get("type") or "").lower() != "invoice":
            continue
        try:
            amt = float(ln.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt <= 0:
            continue
        inv = str(ln.get("invoice_no") or "").strip()
        try:
            val = float(ln.get("unpaid")) if ln.get("unpaid") is not None else amt
        except (TypeError, ValueError):
            val = amt
        stmt_total += amt
        b = bmap.get(_norm_inv_no(inv, sup))
        paid_ref = ""
        if b and b.get("paid"):
            pm = paymap.get(str(b["id"]))
            paid_ref = pm.get("ref", "") if pm else ""
            status, n_paid = "✅ Paid", n_paid + 1
        elif b:
            status, n_pay = "✅ Approved — ready for payment", n_pay + 1
            to_pay += val
            pay_lines.append({"inv": inv, "order": ln.get("order_ref") or "", "amt": round(val, 2),
                              "bill_id": b["id"], "due": _due_label(b.get("due")),
                              "bill_no": b.get("doc_no") or inv, "bill_date": b.get("date"),
                              "due_date": b.get("due"), "original": b.get("total"),
                              "balance": b.get("balance")})
        else:
            status, n_missing = "🔴 Not found in QuickBooks", n_missing + 1
        rows.append({"Invoice": inv, "Order": ln.get("order_ref") or "",
                     "Date": ln.get("date") or "", "Amount": amt, "Unpaid": val,
                     "Paid under": paid_ref, "vs QuickBooks": status})
    cl = limits.get(_norm_code(sup)) or (limits.get(_norm_code(mp["name"])) if mp else None)
    stated = stmt.get("balance")
    on_stmt = stated if isinstance(stated, (int, float)) and stated > 0 else stmt_total
    parts = [f"**{n_pay}** ready to pay (£{to_pay:,.2f})"]
    if n_missing:
        parts.append(f"**{n_missing}** not in QuickBooks")
    if n_paid:
        parts.append(f"{n_paid} paid")
    snap = {"supplier": sup, "vid": vid, "saved_at": now_uk().strftime("%d %b %Y %H:%M"),
            "statement_date": stmt.get("statement_date"), "summary": " · ".join(parts),
            "to_pay": round(to_pay, 2), "stmt_total": round(on_stmt, 2), "credit_limit": cl,
            "rows": rows, "pay_lines": pay_lines, "statement_asset": None}
    try:
        snap["statement_asset"] = data_sources.recon_upload_statement(by, nm or s["attachment_name"])
    except Exception:  # noqa: BLE001
        pass
    data_sources.recon_save(f"v{vid}", snap)
    tail = f", {n_missing} not in QB" if n_missing else ""
    return f"{sup}: {n_pay} ready to pay (£{to_pay:,.0f}){tail}"


def _render_statement_recon():
    """Upload a supplier statement → match every invoice line against QuickBooks bills."""
    if not data_sources.qbo_is_connected():
        st.info("Connect QuickBooks above first — reconciliation reads your bills from it.")
        return

    # Saved reconciliations — visible on login without re-uploading.
    try:
        saved = data_sources.recon_load_all()
    except Exception:  # noqa: BLE001
        saved = {}
    jump = st.session_state.pop("_open_saved_pay", None)   # arrived here from Payables "Pay"
    if saved:
        st.markdown("##### 📌 Saved reconciliations")
        st.caption("Every statement you reconcile is kept here so you can come back and pay it off "
                   "later — no need to re-upload. Amounts are re-checked against QuickBooks when you "
                   "open one to pay.")
        for _k, snap in sorted(saved.items(), key=lambda kv: kv[1].get("saved_at", ""),
                               reverse=True):
            paytog = f"paytog_{_k}"
            if jump == _k:
                st.session_state[paytog] = True
            with st.expander(f"{snap.get('supplier', '?')} · statement "
                             f"{snap.get('statement_date') or '—'} · ready to pay "
                             f"£{snap.get('to_pay', 0):,.2f} · saved {snap.get('saved_at', '')}",
                             expanded=(jump == _k)):
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Ready to pay", f"£{snap.get('to_pay', 0):,.2f}")
                m2.metric("Statement date", snap.get("statement_date") or "—")
                _cl = snap.get("credit_limit")
                m3.metric("Credit limit", f"£{_cl:,.0f}" if _cl else "—")
                m4.metric("Available credit",
                          f"£{_cl - (snap.get('stmt_total') or 0):,.2f}" if _cl else "—")
                if snap.get("statement_asset"):
                    try:
                        _surl = data_sources.monday_asset_url(snap["statement_asset"])
                        if _surl:
                            st.link_button("📄 Open statement", _surl)
                    except Exception:  # noqa: BLE001
                        pass
                if snap.get("summary"):
                    st.markdown(snap["summary"])
                if snap.get("rows"):
                    _sdf = pd.DataFrame(snap["rows"])
                    for _c in ("Amount", "Unpaid"):
                        if _c in _sdf.columns:
                            _sdf[_c] = _sdf[_c].map(_gbp)
                    st.dataframe(_sdf, hide_index=True, use_container_width=True)
                # Pay it off straight from the saved copy (re-checked live against QuickBooks).
                if snap.get("pay_lines") and snap.get("vid"):
                    if st.toggle("💷 Pay this off", key=paytog):
                        _pay_workflow(snap["supplier"], snap["vid"], snap["pay_lines"],
                                      f"saved_{_k}", live_verify=True)
                elif snap.get("to_pay"):
                    st.caption("Reconcile this statement once more to enable paying it off from here "
                               "(it was saved before that feature existed).")
        st.markdown("---")

    # ---- Pull the latest statement per supplier straight from the accounts@ inbox ----
    with st.expander("📥 Pull latest statements from your accounts@ inbox"):
        st.caption(f"Reads the **Statement** folder in **{SUPPLIER_FROM_MAILBOX}** (where your "
                   "mailbox rule files them) and picks the most recent statement from each supplier "
                   "(last ~4 months). Nothing is sent — it just fetches them so you can reconcile. "
                   "Hit **Reconcile** on one to run it through below.")
        if st.button("Fetch latest statements", key="pull_stmts"):
            with st.spinner("Reading the accounts@ inbox…"):
                try:
                    st.session_state["_pulled_list"] = \
                        data_sources.fetch_supplier_statements(SUPPLIER_FROM_MAILBOX)
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't read the inbox: " + str(e)[:220])
        plist = st.session_state.get("_pulled_list")
        if plist == []:
            st.info("No statement-looking emails found in the last few months. (I look for PDF/Excel "
                    "attachments whose name or subject mentions ‘statement’, ‘SOA’, etc.)")
        elif plist:
            rc1, rc2 = st.columns([3, 1])
            rc1.caption(f"**{len(plist)}** statements found. Reconcile them all in one go (each is "
                        "read by AI — a small cost — so this takes a minute or two), or do them one "
                        "at a time. Results are saved to **Saved reconciliations** above to review "
                        "and pay.")
            if rc2.button(f"⚡ Reconcile all {len(plist)}", key="pull_recall",
                          use_container_width=True):
                limits = {}
                try:
                    limits = {_norm_code(k): v for k, v
                              in (data_sources.fetch_supplier_credit_limits() or {}).items()}
                except Exception:  # noqa: BLE001
                    pass
                prog = st.progress(0.0, text="Reconciling…")
                results = []
                for i, s in enumerate(plist):
                    try:
                        results.append(_bulk_reconcile_one(s, limits))
                    except Exception as e:  # noqa: BLE001
                        results.append(f"⚠ {s.get('supplier', '?')}: {str(e)[:70]}")
                    prog.progress((i + 1) / len(plist), text=f"Reconciled {i + 1}/{len(plist)}")
                prog.empty()
                st.success("Done — all saved to **Saved reconciliations** above. Open each to "
                           "review and pay. (Bulk is a quick first pass; open one for the full "
                           "Monday cross-check.)")
                for r in results:
                    st.write("• " + r)
            st.markdown("")
            for i, s in enumerate(plist):
                c1, c2 = st.columns([4, 1])
                c1.markdown(
                    f"**{_esc(s['supplier'])}** · {s['received']} · {_esc(s['attachment_name'])}  \n"
                    f"<span style='color:#7a7d85;font-size:12px'>{_esc(s['subject'])[:110]}</span>",
                    unsafe_allow_html=True)
                if c2.button("Reconcile", key=f"recpull_{i}", use_container_width=True):
                    with st.spinner("Fetching the statement…"):
                        try:
                            nm, by = data_sources.fetch_statement_attachment(
                                SUPPLIER_FROM_MAILBOX, s["message_id"], s["attachment_id"])
                            st.session_state["_pulled_stmt"] = {"name": nm or s["attachment_name"],
                                                                "data": by}
                            st.rerun()
                        except Exception as e:  # noqa: BLE001
                            st.error("Couldn't fetch that statement: " + str(e)[:200])

    up = st.file_uploader("…or upload a supplier statement (PDF, Excel or CSV)",
                          type=["pdf", "xlsx", "xls", "csv"], key="stmt_pdf")
    pulled = st.session_state.get("_pulled_stmt")
    if up is None and pulled:
        up = _PulledFile(pulled["name"], pulled["data"])
        pc1, pc2 = st.columns([4, 1])
        pc1.info(f"📥 Reconciling **{pulled['name']}** pulled from accounts@.")
        if pc2.button("Use a different file", key="clear_pulled", use_container_width=True):
            st.session_state.pop("_pulled_stmt", None)
            st.rerun()
    if not up:
        st.caption("Pull a statement from the inbox above, or upload one, and I'll match every line "
                   "against QuickBooks — what's entered, paid, still owing, or missing.")
        return
    import hashlib
    with st.spinner("Reading the statement…"):
        try:
            if up.name.lower().endswith(".pdf"):
                raw = up.getvalue()
                stmt = _parse_statement(hashlib.sha1(raw).hexdigest(), _pdf_bytes=raw)
            else:
                _txt = _statement_file_text(up)
                stmt = _parse_statement(hashlib.sha1(_txt.encode("utf-8", "ignore")).hexdigest(),
                                        _text=_txt)
        except Exception as e:  # noqa: BLE001
            st.error("Couldn't read the statement: " + str(e)[:200])
            return
    sup = stmt.get("supplier") or "?"
    st.markdown(f"**{_esc(sup)}** · statement {stmt.get('statement_date') or ''} · "
                f"outstanding **£{(stmt.get('balance') or 0):,.2f}**")

    # Pick the QuickBooks vendor — auto-match by name, but let you override (names often differ).
    try:
        vres = data_sources.qbo_query("select Id, DisplayName from Vendor MAXRESULTS 1000")
        vendors = sorted([(v.get("DisplayName"), v.get("Id"))
                          for v in (vres.get("Vendor") or []) if v.get("DisplayName")])
    except Exception as e:  # noqa: BLE001
        st.error("Couldn't read QuickBooks vendors: " + str(e)[:200])
        return
    if not vendors:
        st.warning("No vendors found in QuickBooks.")
        return
    names = [n for n, _ in vendors]
    # Prefer a previously-learned mapping for this supplier; else auto-match by name.
    sup_key = _norm_code(sup)
    try:
        vmap = data_sources.qbo_vendor_map_load()
    except Exception:  # noqa: BLE001
        vmap = {}
    mapped = vmap.get(sup_key)
    if mapped:
        default_i = next((i for i, (n, vid) in enumerate(vendors) if vid == mapped["id"]), 0)
    else:
        auto = data_sources.qbo_find_vendor(sup)
        default_i = next((i for i, (n, vid) in enumerate(vendors) if auto and vid == auto["id"]), 0)
    if mapped:
        st.caption(f"Auto-selected **{mapped['name']}** (remembered for “{sup}”).")
    picked = st.selectbox(f"QuickBooks vendor (statement says “{sup}”)", names, index=default_i,
                          key="stmt_vendor")
    vid = {n: i for n, i in vendors}[picked]
    # Learn/refresh the mapping whenever the chosen vendor differs from what's stored.
    if not mapped or mapped.get("id") != vid:
        try:
            data_sources.qbo_vendor_map_save(sup_key, vid, picked)
        except Exception:  # noqa: BLE001
            pass
    with st.spinner("Reading QuickBooks bills & payments…"):
        try:
            bills = data_sources.qbo_vendor_bills(vid)
        except Exception as e:  # noqa: BLE001
            st.error("Couldn't read QuickBooks bills: " + str(e)[:200])
            return
        try:
            paymap = data_sources.qbo_vendor_payments(vid)   # bill id → {ref, date}
        except Exception:  # noqa: BLE001
            paymap = {}
        try:
            _cl = {_norm_code(k): v
                   for k, v in (data_sources.fetch_supplier_credit_limits() or {}).items()}
            credit_limit = _cl.get(_norm_code(sup)) or _cl.get(_norm_code(picked))
        except Exception:  # noqa: BLE001
            credit_limit = None

    with st.expander(f"🔍 What QuickBooks returned for {picked} ({len(bills)} bills)"):
        if bills:
            st.dataframe(pd.DataFrame([{"Bill no (DocNumber)": b["doc_no"], "Date": b["date"],
                                        "Total": _gbp(b["total"]), "Balance": _gbp(b["balance"])}
                                       for b in bills[:25]]), hide_index=True,
                         use_container_width=True)
            st.caption("If the **Bill no** column doesn't match the statement's invoice numbers, "
                       "tell me what it holds instead and I'll match on that.")
        else:
            st.caption("No bills came back for this vendor — pick a different vendor above, or the "
                       "bills may be under a different vendor name.")

    # Missing-from-QB invoices: cross-check Monday — a Discrepancy there = awaiting a credit note.
    def _mon_nos(key):
        try:
            return {_norm_inv_no(i.get("invoice_no"), sup)
                    for i in (invoices_by_status(key).get("invoices") or []) if i.get("invoice_no")}
        except Exception:  # noqa: BLE001
            return set()
    disc_nos = _mon_nos("discrepancy")
    action_nos = _mon_nos("review") | _mon_nos("matched")   # on Monday but not yet approved to QB
    approved_nos = _mon_nos("pushed")                       # Approved (To QB) — on Monday, approved

    bill_by_doc = {}
    for b in bills:
        if b["doc_no"]:
            bill_by_doc.setdefault(_norm_inv_no(b["doc_no"], sup), b)

    rows, action_rows, pay_lines = [], [], []
    n_pay = n_paid = n_missing = n_disc = n_action = 0
    to_pay = paid_total = disc_total = missing_total = action_total = stmt_total = 0.0
    used = set()
    for ln in (stmt.get("lines") or []):
        if (ln.get("type") or "").lower() != "invoice":
            continue
        inv = (ln.get("invoice_no") or "").strip()
        amt, unpaid = ln.get("amount"), ln.get("unpaid")
        val = (unpaid if isinstance(unpaid, (int, float))
               else (amt if isinstance(amt, (int, float)) else 0.0))
        stmt_total += val
        b = bill_by_doc.get(_norm_inv_no(inv, sup))
        if not b:                    # fallback: an unused bill with the same amount
            b = next((x for x in bills if x["id"] not in used
                      and isinstance(x["total"], (int, float)) and isinstance(amt, (int, float))
                      and abs(x["total"] - amt) < 0.01), None)
        if b:
            used.add(b["id"])
        paid_ref = ""
        if b and b["paid"]:
            # On the statement but already paid in QB — keep it (supplier may not have cleared it).
            paid_ref = (paymap.get(b["id"]) or {}).get("ref") or ""
            status = (f"🔵 Paid in QB — under payment {paid_ref}" if paid_ref
                      else "🔵 Marked paid in QB")
            n_paid += 1
            paid_total += val
        elif not b:
            _k = _norm_inv_no(inv, sup)
            if _k in disc_nos:
                status, n_disc = "🟣 Discrepancy (Monday) — awaiting credit note", n_disc + 1
                disc_total += val
            elif _k in approved_nos:
                status, n_action = ("🟢 On Monday & approved — not yet matched to a QuickBooks "
                                    "bill (check the invoice no.)"), n_action + 1
                action_total += val
                action_rows.append({"inv": inv, "order": ln.get("order_ref") or "", "amt": amt})
            elif _k in action_nos:
                status, n_action = "🟠 On Monday, not yet approved — review/approve ASAP", n_action + 1
                action_total += val
                action_rows.append({"inv": inv, "order": ln.get("order_ref") or "", "amt": amt})
            else:
                status, n_missing = "🔴 Missing from Monday — not input yet", n_missing + 1
                missing_total += val
        else:
            status, n_pay = "✅ Approved — ready for payment", n_pay + 1
            to_pay += val
            pay_lines.append({"inv": inv, "order": ln.get("order_ref") or "", "amt": round(val, 2),
                              "bill_id": b["id"], "due": _due_label(b.get("due")),
                              "bill_no": b.get("doc_no") or inv, "bill_date": b.get("date"),
                              "due_date": b.get("due"), "original": b.get("total"),
                              "balance": b.get("balance")})
        rows.append({"Invoice": inv, "Order": ln.get("order_ref") or "",
                     "Date": ln.get("date") or "", "Amount": amt, "Unpaid": unpaid,
                     "Due": (_due_label(b.get("due")) if b and not b["paid"] else ""),
                     "Paid under": paid_ref, "vs QuickBooks": status})

    parts = [f"**{n_pay}** ready to pay (£{to_pay:,.2f})"]
    if n_action:
        parts.append(f"**{n_action}** to review/approve")
    if n_disc:
        parts.append(f"**{n_disc}** awaiting credit note")
    if n_missing:
        parts.append(f"**{n_missing}** missing from Monday")
    if n_paid:
        parts.append(f"{n_paid} paid")
    st.markdown(" · ".join(parts))
    if rows:
        df = pd.DataFrame(rows)
        for _c in ("Amount", "Unpaid"):
            df[_c] = df[_c].map(_gbp)
        st.dataframe(df, hide_index=True, use_container_width=True)

    # "On the statement" = the balance the statement itself states (what we actually owe), NOT the
    # sum of every invoice line — a full/aged statement lists already-paid items too, which would
    # over-count. Fall back to the line-sum only if the statement gives no balance.
    stated = stmt.get("balance")
    on_stmt = stated if isinstance(stated, (int, float)) and stated > 0 else stmt_total
    st.markdown("---")
    t1, t2, t3 = st.columns(3)
    t1.metric("On the statement", f"£{on_stmt:,.2f}")
    t2.metric("Ready to pay in QuickBooks", f"£{to_pay:,.2f}")
    t3.metric("Not yet payable", f"£{max(on_stmt - to_pay, 0):,.2f}")
    st.caption(
        f"‘On the statement’ is the balance the statement itself states. The invoice lines I read "
        f"add up to £{stmt_total:,.2f} (higher when the statement also lists already-paid or aged "
        f"items). What I matched: £{to_pay:,.2f} ready to pay ({n_pay}), £{action_total:,.2f} to "
        f"review/approve ({n_action}), £{disc_total:,.2f} awaiting credit note ({n_disc}), "
        f"£{missing_total:,.2f} missing from Monday ({n_missing}), £{paid_total:,.2f} already "
        f"paid ({n_paid}).")

    c1, c2, c3 = st.columns(3)
    c1.metric("Statement date", stmt.get("statement_date") or "—")
    c2.metric("Credit limit", f"£{credit_limit:,.0f}" if credit_limit else "—")
    c3.metric("Available credit", f"£{credit_limit - on_stmt:,.2f}" if credit_limit else "—")
    if not credit_limit:
        st.caption("No credit limit found for this supplier on the Monday Suppliers board.")

    # ---- Build a remittance from the ready-to-pay invoices, email it, mark paid in QB ----
    if pay_lines:
        _pay_workflow(sup, vid, pay_lines, _norm_code(sup))

    # ---- Keep it for later: auto-save this reconciliation (once per statement) so you can come
    # back in a day or two and pay off it without re-uploading. ----
    snap = {"supplier": sup, "vid": vid, "saved_at": now_uk().strftime("%d %b %Y %H:%M"),
            "statement_date": stmt.get("statement_date"), "summary": " · ".join(parts),
            "to_pay": round(to_pay, 2), "stmt_total": round(on_stmt, 2),
            "credit_limit": credit_limit, "rows": rows, "pay_lines": pay_lines,
            "statement_asset": None}
    _saved_set = st.session_state.setdefault("_recon_autosaved", {})
    if sig not in _saved_set:
        try:
            with st.spinner("Keeping this reconciliation…"):
                try:
                    snap["statement_asset"] = data_sources.recon_upload_statement(up.getvalue(),
                                                                                  up.name)
                except Exception:  # noqa: BLE001
                    pass    # save even if the file upload fails
                data_sources.recon_save(f"v{vid}", snap)
            _saved_set[sig] = snap.get("statement_asset")
            st.caption("💾 Kept — you'll find this under **Saved reconciliations** at the top, ready "
                       "to pay whenever you are (no need to re-upload).")
        except Exception as e:  # noqa: BLE001
            st.caption("Couldn't keep this reconciliation automatically: " + str(e)[:120])
    else:
        snap["statement_asset"] = _saved_set.get(sig)
        st.caption("💾 Kept under **Saved reconciliations** at the top.")

    if n_missing:
        st.warning(f"⚠ {n_missing} invoice(s) are on the statement but **not on Monday at all** — "
                   "they've never been input. (Mailbox search + supplier-chase draft coming next.)")

    if n_action:
        st.info(f"🟠 {n_action} invoice(s) are on Monday but not yet approved to QuickBooks — "
                "review and approve (or query) these ASAP so they're ready to pay.")
        subh = _norm_code(sup)
        if st.toggle("✉ Email a colleague to review these", key=f"revtog_{subh}"):
            rsubj, rbody = _review_reminder_email(sup, action_rows)
            st.session_state.setdefault(f"rto_{subh}", "")
            st.session_state.setdefault(f"rsub_{subh}", rsubj)
            st.session_state.setdefault(f"rbod_{subh}", rbody)
            st.text_input("To (colleague's email)", key=f"rto_{subh}")
            st.text_input("Subject", key=f"rsub_{subh}")
            st.text_area("Message", key=f"rbod_{subh}", height=200)
            st.caption(f"Sends from {SUPPLIER_FROM_MAILBOX}. Falls back to a draft if sending isn't "
                       "enabled yet.")
            if st.button("Send reminder", key=f"rsend_{subh}", type="primary",
                         disabled=not st.session_state.get(f"rto_{subh}", "").strip()):
                to = st.session_state[f"rto_{subh}"].strip()
                subj, body = st.session_state[f"rsub_{subh}"], st.session_state[f"rbod_{subh}"]
                sent = drafted = False
                dlink = None
                try:
                    data_sources.send_supplier_email(SUPPLIER_FROM_MAILBOX, to, subj, body)
                    sent = True
                except Exception:  # noqa: BLE001
                    try:
                        dlink = data_sources.create_supplier_draft(SUPPLIER_FROM_MAILBOX, to, subj,
                                                                   body)
                        drafted = True
                    except Exception as e:  # noqa: BLE001
                        st.error("Couldn't send or draft: " + str(e)[:200])
                if sent or drafted:
                    link = f" [Open the draft]({dlink})" if dlink else ""
                    st.success(f"Review reminder {'sent to' if sent else 'drafted for'} {to}"
                               + ("" if sent else " (sending needs Mail.Send)") + "." + link)


def _render_payables_live():
    """Live all-suppliers payables from QuickBooks open bills + Monday credit limits."""
    if not _qbo_connected_quiet():
        with st.expander("QuickBooks connection (read-only)", expanded=True):
            _render_qbo_panel()
        return
    if st.button("↻ Refresh", key="pay_refresh"):
        st.session_state.pop("_payables", None)
    data = st.session_state.get("_payables")
    if data is None:
        with st.spinner("Reading QuickBooks open bills…"):
            try:
                vres = data_sources.qbo_query(
                    "select Id, DisplayName, Balance from Vendor MAXRESULTS 1000")
                vendors = {v.get("Id"): {"name": v.get("DisplayName"), "balance": v.get("Balance")}
                           for v in (vres.get("Vendor") or [])}
                bres = data_sources.qbo_query(
                    "select VendorRef, DueDate, Balance from Bill MAXRESULTS 1000")
                bills = bres.get("Bill") or []
            except Exception as e:  # noqa: BLE001
                st.error("Couldn't read QuickBooks: " + str(e)[:200])
                return
            try:
                raw_limits = data_sources.fetch_supplier_credit_limits()
            except Exception:  # noqa: BLE001
                raw_limits = {}
            data = {"vendors": vendors, "bills": bills, "limits": raw_limits}
            st.session_state["_payables"] = data

    from datetime import date
    vendors, bills = data["vendors"], data["bills"]
    limits = {_norm_code(k): v for k, v in (data["limits"] or {}).items()}
    today = now_uk().date()
    # Saved reconciliations, keyed by QuickBooks vendor id — lets Payables show the statement date
    # and jump you straight into paying one off.
    try:
        saved = data_sources.recon_load_all() or {}
    except Exception:  # noqa: BLE001
        saved = {}
    vid_snap = {s["vid"]: (k, s) for k, s in saved.items() if s.get("vid")}
    # Owed per supplier is derived straight from the OPEN bills (Balance > 0) — more reliable than
    # the Vendor.Balance field, which QuickBooks often returns as 0 in a query.
    per = {}
    for b in bills:
        bal = b.get("Balance")
        if not (isinstance(bal, (int, float)) and bal > 0.005):
            continue
        vid = (b.get("VendorRef") or {}).get("value")
        p = per.setdefault(vid, {"owed": 0.0, "overdue": 0.0, "next": None})
        p["owed"] += bal
        due = b.get("DueDate")
        if due:
            try:
                dd = date.fromisoformat(str(due)[:10])
            except Exception:  # noqa: BLE001
                dd = None
            if dd:
                if dd < today:
                    p["overdue"] += bal
                if p["next"] is None or dd < p["next"]:
                    p["next"] = dd

    st.caption(f"{len(vendors)} QuickBooks vendors · {len(bills)} bills pulled · "
               f"{len(per)} supplier(s) with an open balance.")
    rows, tot_owed, tot_over = [], 0.0, 0.0
    for vid, p in per.items():
        owed = p["owed"]
        name = (vendors.get(vid) or {}).get("name") or f"Vendor {vid}"
        lim = limits.get(_norm_code(name))
        nd = p.get("next")
        _snap = vid_snap.get(vid)
        rows.append({"Supplier": name, "Owed": round(owed, 2),
                     "Overdue": round(p.get("overdue", 0.0), 2),
                     "Next due": (_due_label(nd.isoformat()) if nd else ""),
                     "Statement date": (_snap[1].get("statement_date") if _snap else "") or "",
                     "Credit limit": lim,
                     "Available credit": (round(lim - owed, 2) if isinstance(lim, (int, float))
                                          else None),
                     "_due": nd or date.max, "_vid": vid})
        tot_owed += owed
        tot_over += p.get("overdue", 0.0)

    if not rows:
        st.info("No open supplier bills came back from QuickBooks. If you know there are unpaid "
                "bills, they may be beyond the first 1,000 pulled — tell me and I'll page through "
                "all of them.")
        return
    rows.sort(key=lambda r: r["_due"])   # oldest owing (earliest due date) first
    st.markdown(f"**{len(rows)} suppliers** owing · total **£{tot_owed:,.2f}** · overdue "
                f"**£{tot_over:,.2f}**")
    pdf = pd.DataFrame(rows).drop(columns=["_due", "_vid"])

    def _avail_colour(row):
        # Green = plenty of headroom, amber = getting close, red = at/over the credit limit.
        # Worked out from how much of the credit limit is used (Owed ÷ Credit limit).
        styles = [""] * len(row)
        lim, owed = row.get("Credit limit"), row.get("Owed")
        if (isinstance(lim, (int, float)) and lim == lim and lim > 0
                and isinstance(owed, (int, float)) and owed == owed):
            pct = owed / lim * 100
            if pct >= 90:
                css = "background-color:#fbe3e4;color:#8a1c1c;font-weight:600"   # red
            elif pct >= 75:
                css = "background-color:#fff4d6;color:#7a5b00;font-weight:600"   # amber
            else:
                css = "background-color:#e3f4e4;color:#125b1a;font-weight:600"   # green
            styles[row.index.get_loc("Available credit")] = css
        return styles

    fmt = {"Owed": _gbp, "Overdue": _gbp, "Available credit": _gbp,
           "Credit limit": lambda v: f"£{v:,.0f}" if isinstance(v, (int, float)) and v == v else ""}
    styled = pdf.style.apply(_avail_colour, axis=1).format(fmt)
    st.dataframe(styled, hide_index=True, use_container_width=True)
    st.caption("Live from QuickBooks open bills · overdue = past due date · credit limits come from "
               "your Monday Suppliers board · **sorted oldest-first** (earliest due date at the "
               "top). Statement date shows if you've reconciled their statement. **Available "
               "credit** is 🟢 plenty · 🟠 getting close (75%+ used) · 🔴 at/over the limit (90%+).")

    # ---- Jump straight into paying off a supplier whose statement you've reconciled ----
    jumpable = []
    seen = set()
    for r in rows:   # already oldest-first
        _s = vid_snap.get(r["_vid"])
        if _s and _s[1].get("pay_lines") and r["_vid"] not in seen:
            seen.add(r["_vid"])
            jumpable.append((f"{r['Supplier']} · statement {_s[1].get('statement_date') or '—'} · "
                             f"ready £{_s[1].get('to_pay', 0):,.2f}", _s[0]))
    if jumpable:
        st.markdown("##### 💷 Pay one off")
        st.caption("Pick a supplier you've reconciled (oldest first) and open it to build a "
                   "remittance and mark it paid.")
        j1, j2 = st.columns([3, 1])
        choice = j1.selectbox("Supplier to pay", [lbl for lbl, _ in jumpable],
                              key="pay_jump_pick", label_visibility="collapsed")
        if j2.button("Open to pay →", key="pay_jump_go", type="primary",
                     use_container_width=True):
            st.session_state["_open_saved_pay"] = dict(jumpable)[choice]
            st.session_state["fin_view"] = "Statement Reconciliation"
            st.rerun()


def render_finance():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Finance</span></span></div>""",
        unsafe_allow_html=True,
    )
    # Views chosen from the sidebar toggle.
    _fv = st.session_state.get("fin_view")
    if _fv == "Payables (Live)":
        _render_payables_live()
        return
    if _fv == "Statement Reconciliation":
        with st.expander("QuickBooks connection (read-only)",
                         expanded=not _qbo_connected_quiet()):
            _render_qbo_panel()
        _render_statement_recon()
        return
    st.caption("Live actual margin from the Orders board **Paid & Delivered** group(s) — per "
               "month, per supplier, with loss-making, missing-invoice and anomaly flags. "
               "Admin only.")

    c1, c2 = st.columns([4, 1])
    c1.caption("Margin is the live order-margin % from Monday. £ figures are estimates from the "
               "agreed supplier cost + that margin.")
    if c2.button("↻ Refresh", use_container_width=True):
        _finance_data.clear()
        st.rerun()

    data = _finance_data()
    if data.get("error"):
        st.error("Couldn't load orders: " + str(data["error"])[:200])
        return
    if not data.get("groups"):
        st.warning("Couldn't find a 'Paid & Delivered' group on the Orders board. Groups found: "
                   + ", ".join(f"`{t}`" for t in (data.get("all_groups") or {}).values()))
        st.caption("Tell me the exact group name(s) to use and I'll point Finance at them.")
        return

    orders = data["orders"]
    st.caption("Reading group(s): " + ", ".join(f"**{t}**" for t in data["groups"])
               + (" · ⚠️ more orders exist than were pulled (showing the most recent)"
                  if data.get("more") else ""))

    # Filters — default to the current year only.
    years = sorted({o["month"][:4] for o in orders if o["month"]}, reverse=True)
    this_year = now_uk().strftime("%Y")
    f0, f1, f2 = st.columns([1, 2, 2])
    year = f0.selectbox("Year", years or [this_year],
                        index=(years.index(this_year) if this_year in years else 0))
    yorders = [o for o in orders if o["month"] and o["month"].startswith(year)]
    months = sorted({o["month"] for o in yorders}, reverse=True)
    sups = sorted({o["supplier"] for o in yorders if o["supplier"]})
    msel = f1.multiselect("Months", months, default=months, format_func=_month_label)
    ssel = f2.multiselect("Suppliers", sups, default=[])
    rows = [o for o in yorders
            if (not msel or o["month"] in msel) and (not ssel or o["supplier"] in ssel)]
    if not rows:
        st.info("No orders match the filters.")
        return

    # Headline tiles
    losses = [o for o in rows if o.get("margin") is not None and o["margin"] < 0]
    no_inv = [o for o in rows if not o.get("has_invoice")]
    flagged = [o for o in rows if o.get("flags")]
    t = st.columns(5)
    t[0].metric("Orders", len(rows))
    am = _avg([o.get("margin") for o in rows])
    t[1].metric("Avg margin", f"{am:.1f}%" if am is not None else "—")
    t[2].metric("Loss-making", len(losses))
    t[3].metric("No invoice", len(no_inv))
    t[4].metric("Flagged", len(flagged))

    def agg(items):
        ms = [o["margin"] for o in items if o.get("margin") is not None]
        cost = sum(o["agreed_cost"] or 0 for o in items)
        egbp = sum(o["est_gbp"] or 0 for o in items)
        nloss = sum(1 for o in items if o.get("margin") is not None and o["margin"] < 0)
        ninv = sum(1 for o in items if not o.get("has_invoice"))
        return len(items), (_avg(ms)), nloss, ninv, cost, egbp

    def mcell(v):
        return f"{v:.1f}%" if v is not None else "—"

    store = data_sources.get_secret("SHOPIFY_STORE")

    def _olink(o):
        oid = o.get("shopify_order_id")
        label = _esc(o.get("order_no") or o.get("name") or "order")
        if store and oid:
            return f'<a href="https://{store}/admin/orders/{oid}">{label}</a>'
        return label

    def mcolor(m):
        if m is None:
            return "var(--muted)"
        return "#DC2626" if m < 0 else ("#B45309" if m < 10 else "#16A34A")

    def pills(n, avgm, nloss, ninv, cost):
        p = (f'<span class="fpill" style="color:{mcolor(avgm)}">{mcell(avgm)}</span>'
             f'<span class="fsub">{n} orders</span><span class="fsub">£{cost:,.0f}</span>')
        if nloss:
            p += f'<span class="fbad">{nloss} loss</span>'
        if ninv:
            p += f'<span class="fwarn">{ninv} no inv</span>'
        return p

    # Month → Supplier → Orders drill-down (native <details> = instant, no reload).
    by_m = {}
    for o in rows:
        by_m.setdefault(o["month"] or "—", {}).setdefault(o["supplier"] or "—", []).append(o)

    css = """<style>
    .findd details{border:1px solid var(--line);border-radius:10px;margin:8px 0;background:var(--card);overflow:hidden}
    .findd details details{margin:8px 10px}
    .findd summary{display:flex;align-items:center;gap:12px;cursor:pointer;list-style:none;padding:11px 15px}
    .findd summary::-webkit-details-marker{display:none}
    .findd summary::before{content:'▸';color:var(--muted);font-size:12px}
    .findd details[open]>summary::before{content:'▾'}
    .findd summary:hover{background:rgba(242,106,33,.06)}
    .findd .fttl{font-weight:800;font-size:16px;margin-right:auto}
    .findd .fttl2{font-weight:700;font-size:13.5px;margin-right:auto}
    .findd .fsub{color:var(--muted);font-size:12px}
    .findd .fpill{font-weight:800}
    .findd .fbad{background:#DC2626;color:#fff;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:700}
    .findd .fwarn{background:#B45309;color:#fff;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:700}
    .findd table{width:100%;border-collapse:collapse;font-size:12.5px;margin:0 4px 8px}
    .findd th{color:var(--muted);font-weight:600;text-align:left;padding:6px 12px}
    .findd td{padding:6px 12px;border-top:1px solid var(--line)}
    </style>"""
    parts = [css, '<div class="findd">']
    for mth in sorted(by_m, reverse=True):
        m_orders = [o for s in by_m[mth].values() for o in s]
        n, avgm, nloss, ninv, cost, egbp = agg(m_orders)
        parts.append(f'<details><summary><span class="fttl">{_esc(_month_label(mth))}</span>'
                     f'{pills(n, avgm, nloss, ninv, cost)}</summary>')
        for sup in sorted(by_m[mth], key=lambda s: agg(by_m[mth][s])[4], reverse=True):
            items = by_m[mth][sup]
            n2, avgm2, nloss2, ninv2, cost2, egbp2 = agg(items)
            parts.append(f'<details><summary><span class="fttl2">{_esc(sup)}</span>'
                         f'{pills(n2, avgm2, nloss2, ninv2, cost2)}</summary>')
            trs = ('<table><tr><th>Order</th><th>Range</th><th>Margin</th>'
                   '<th style="text-align:right">Cost</th><th style="text-align:right">Est £</th>'
                   '<th style="text-align:center">Inv</th><th>Flags</th></tr>')
            for o in sorted(items, key=lambda x: (x["margin"] if x.get("margin") is not None else 999)):
                inv = ('✓' if o.get("has_invoice")
                       else '<span style="color:#DC2626;font-weight:700">✗</span>')
                est = f"£{o['est_gbp']:,.0f}" if o.get("est_gbp") else "—"
                trs += (f'<tr><td>{_olink(o)}</td><td>{_esc(o["range"])}</td>'
                        f'<td style="color:{mcolor(o.get("margin"))};font-weight:700">{mcell(o.get("margin"))}</td>'
                        f'<td style="text-align:right">£{(o.get("agreed_cost") or 0):,.0f}</td>'
                        f'<td style="text-align:right">{est}</td>'
                        f'<td style="text-align:center">{inv}</td>'
                        f'<td style="color:var(--muted);font-size:11px">{_esc(", ".join(o["flags"]))}</td></tr>')
            parts.append(trs + '</table></details>')
        parts.append('</details>')
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)

    # By product range (cross-cutting quick view)
    with st.expander("📦 By product range"):
        byrange = {}
        for o in rows:
            byrange.setdefault(o["range"], []).append(o)
        rrows = []
        for rg in sorted(byrange, key=lambda r: agg(byrange[r])[4], reverse=True):
            n, avgm, nloss, ninv, cost, egbp = agg(byrange[rg])
            rrows.append((_esc(rg), str(n), mcell(avgm), str(nloss) if nloss else "—",
                          f"£{cost:,.0f}", f"£{egbp:,.0f}"))
        st.markdown(_rules_table(
            ["Product range", "Orders", "Avg margin", "Losses", "Cost £", "Est. margin £"],
            rrows), unsafe_allow_html=True)
        st.caption("Range inferred from the order's SKUs — 'Mixed' = multiple ranges, "
                   "'Other' = couldn't classify.")

    # Loss-making detail
    with st.expander(f"⚠️ Loss-making orders ({len(losses)})"):
        lr = [(_olink(o), _esc(o.get("supplier") or "—"), _esc(o["range"]),
               mcell(o.get("margin")), f"£{o['est_gbp']:,.0f}" if o.get("est_gbp") else "—",
               _month_label(o.get("month"))) for o in sorted(losses, key=lambda x: x.get("margin") or 0)]
        st.markdown(_rules_table(["Order", "Supplier", "Range", "Margin", "Est. £", "Month"], lr)
                    if lr else "None 🎉", unsafe_allow_html=True)

    # No-invoice detail
    with st.expander(f"🧾 Paid & Delivered but no invoice ({len(no_inv)})"):
        nr = [(_olink(o), _esc(o.get("supplier") or "—"), _esc(o["range"]),
               mcell(o.get("margin")), _month_label(o.get("month")))
              for o in sorted(no_inv, key=lambda x: x.get("month") or "", reverse=True)]
        st.markdown(_rules_table(["Order", "Supplier", "Range", "Margin", "Month"], nr)
                    if nr else "None — all have invoices 🎉", unsafe_allow_html=True)

    # Anomalies
    with st.expander(f"🚩 Anomalies to check ({len(flagged)})"):
        ar = [(_olink(o), _esc(o.get("supplier") or "—"), mcell(o.get("margin")),
               _esc(", ".join(o["flags"])), _month_label(o.get("month")))
              for o in sorted(flagged, key=lambda x: x.get("month") or "", reverse=True)]
        st.markdown(_rules_table(["Order", "Supplier", "Margin", "Flags", "Month"], ar)
                    if ar else "Nothing flagged 🎉", unsafe_allow_html=True)


def render_supplier_rules():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Supplier rules</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.caption("How invoices are auto-checked and processed per supplier (used by Invoice Check).")
    lo, hi = _thresholds()

    st.markdown("#### Margin &amp; auto-push rules")
    mrows = [("All others (default)", "Yes", f"{lo:.0f}–{hi:.0f}%", "Hold as Matched",
              f"Flag (&gt; {hi:.0f}%)")]
    for k, r in SUPPLIER_RULES.items():
        mrows.append((
            r.get("name", k),
            "No — order/Shopify only" if r.get("no_pricelist") else "Yes",
            f"&ge; {r.get('push_min', lo):.0f}%",
            "Hold — suggest raising website price" if r.get("no_pricelist") else "Hold as Matched",
            "—" if not r.get("flag_high", True) else f"Flag (&gt; {hi:.0f}%)",
        ))
    st.markdown(_rules_table(
        ["Supplier", "Pricelist check", "Push when margin", "Below range", "Above range"], mrows),
        unsafe_allow_html=True)

    st.markdown("#### Delivery charges (ex-VAT)")
    drows = []
    for k, r in DELIVERY_CHARGES.items():
        rule = (f"£{r['flat']:.2f} for orders under £{r['free_over']:.0f}, free over"
                if r.get("free_over") is not None else f"£{r['flat']:.2f} flat")
        drows.append((r.get("name", k), rule))
    st.markdown(_rules_table(["Supplier", "Delivery rule"], drows), unsafe_allow_html=True)
    st.caption("A matching or lower delivery charge is accepted; only a higher amount is flagged. "
               "To add or change a rule, tell me the supplier and the rule.")


def render_pricing():
    p = load_pricing()
    st.markdown(
        f"""<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b> <span class="sec">Pricing</span></span>
        <span class="sct">{('updated '+p['generated_at']) if p else 'no data yet'}</span></div>""",
        unsafe_allow_html=True,
    )
    if not p:
        st.warning("No pricing data yet. Run the supplier-pricing refresh to create "
                   "`pricing_summary.json`, push it, and it'll appear here.")
        return

    st.caption("**Buy from (cheapest supplier)** = who we order from at the lowest cost · "
               "**Sold as (Shopify vendor)** = the brand it's listed under on our website. "
               "These aren't always the same.")

    render_product_search()

    _lk = load_lookup()
    _render_competitor_check(_lk["items"] if _lk else [])

    # Clickable tiles → pick which list to view.
    k = p["kpis"]
    tiles = [("Loss-making", k["losses"]), ("Below target", k["below_target"]),
             ("Multi-supplier", k["multi"]), ("Unmatched", k["unmatched"]),
             ("Supplier margins", len(p["supplier_summary"])), ("Pricelists", None)]
    if "pview" not in st.session_state:
        st.session_state.pview = "Loss-making"
    for col, (label, cnt) in zip(st.columns(len(tiles)), tiles):
        lbl = f"{label}\n\n{cnt:,}" if cnt is not None else f"{label}\n\n—"
        if col.button(lbl, key=f"pv_{label}", use_container_width=True,
                      type="primary" if st.session_state.pview == label else "secondary"):
            st.session_state.pview = label
            st.rerun()
    st.write("")

    view = st.session_state.pview
    lk = load_lookup()
    items = lk["items"] if lk else []
    CAP = 300

    if view == "Supplier margins":
        sr = "".join(
            f'<tr style="border-top:1px solid var(--line)">'
            f'<td style="padding:7px 12px"><b>{s["supplier"]}</b>'
            f'<div style="color:var(--muted);font-size:11px">{("as of " + s["pricelist_date"]) if s.get("pricelist_date") else "no date"}</div></td>'
            f'<td style="padding:7px 12px;text-align:right">{s.get("skus_sold"):,}</td>'
            f'<td style="padding:7px 12px;text-align:right;font-weight:800;color:{_mcol(s.get("avg_margin"))}">{s.get("avg_margin")}%</td>'
            f'<td style="padding:7px 12px;text-align:right">{s.get("below_target")}</td>'
            f'<td style="padding:7px 12px;text-align:right;color:{"#dc2626" if s.get("loss") else "var(--muted)"}">{s.get("loss")}</td></tr>'
            for s in p["supplier_summary"])
        st.markdown(_ptable(
            '<th style="padding:7px 12px">Supplier / pricelist date</th><th style="padding:7px 12px;text-align:right">SKUs sold</th>'
            '<th style="padding:7px 12px;text-align:right">Avg margin</th><th style="padding:7px 12px;text-align:right">Below target</th>'
            '<th style="padding:7px 12px;text-align:right">Loss</th>', sr), unsafe_allow_html=True)

    elif view == "Pricelists":
        suppliers = [s["supplier"] for s in p["supplier_summary"]]
        sup = st.selectbox("Supplier", suppliers, key="pl_sup")
        rows = sorted((it for it in items if any(o["s"] == sup for o in it.get("offers", []))),
                      key=lambda it: it["sku"])
        st.caption(f"{len(rows):,} SKUs from {sup}"
                   + (f" — showing first {CAP}, use the search above to find a specific one" if len(rows) > CAP else ""))
        st.markdown(_ptable(_SKU_HEAD, _sku_rows(rows[:CAP], supplier=sup)), unsafe_allow_html=True)

    else:
        if view == "Loss-making":
            rows = sorted((it for it in items if it.get("status") == "loss"),
                          key=lambda it: (it.get("margin") if it.get("margin") is not None else 0))
        elif view == "Below target":
            rows = sorted((it for it in items if it.get("status") == "below-target"),
                          key=lambda it: (it.get("margin") if it.get("margin") is not None else 999))
        elif view == "Multi-supplier":
            rows = sorted((it for it in items if len(it.get("offers", [])) > 1),
                          key=lambda it: -(it.get("saving") or 0))
        elif view == "Unmatched":
            rows = sorted((it for it in items if not it.get("sell")), key=lambda it: it["sku"])
        else:
            rows = []
        st.caption(f"{len(rows):,} SKUs"
                   + (f" — showing first {CAP}, use the search above to find a specific one" if len(rows) > CAP else ""))
        st.markdown(_ptable(_SKU_HEAD, _sku_rows(rows[:CAP])), unsafe_allow_html=True)

    st.caption(f"Snapshot from the daily refresh ({p['generated_at']}). "
               "Click a tile above to switch lists; use the search to find any SKU.")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
@st.dialog("Change password")
def _change_password_dialog():
    try:
        if authenticator.reset_password(
                username, location="main",
                fields={"Form name": "", "Reset": "Update password"}):
            with open(BASE / "config.yaml", "w") as f:
                yaml.dump(config, f, default_flow_style=False)
            st.success("Password changed ✅ — you can close this.")
    except Exception as e:  # noqa: BLE001
        st.warning(str(e))


@st.cache_data(ttl=1800, show_spinner=False)
def _server_ip():
    """Trade Hub's current outbound/server IP — shown in the sidebar for the QuickBooks app
    profile's 'where your app is hosted' field."""
    import urllib.request
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode().strip()
    except Exception:  # noqa: BLE001
        return "unavailable"


with st.sidebar:
    if _logo:
        st.markdown(
            f"<img src='{_logo}' style='width:100%;display:block;margin:2px 0 14px'>",
            unsafe_allow_html=True,
        )

    # --- Menu (role-gated) ---
    #   admin / manager : everything, including Invoice Check
    #   office          : Daily Ops only
    #   staff (others)  : Daily Ops, Daily Activity, Quotes, Pricing (no Invoice Check)
    # A per-user `modules:` list in config.yaml overrides the role default for that one person
    # (e.g. Natasha = Daily Ops + Order Processing only). It can only ever NARROW/pick from the
    # full module set — never grants Invoice Check/Finance unless listed explicitly.
    all_modules = ("Daily Ops", "Daily Activity", "Quotes", "Pricing", "Invoice Check",
                   "Order Processing", "Finance")
    staff_modules = ("Daily Ops", "Daily Activity", "Quotes", "Pricing")
    if role == "office":
        menu = ("Daily Ops",)
    elif role in ("admin", "manager"):
        menu = all_modules
    else:
        menu = staff_modules
    user_modules = config["credentials"]["usernames"].get(username, {}).get("modules")
    if user_modules:                                   # explicit per-user allow-list
        _want = set(user_modules)
        menu = tuple(m for m in all_modules if m in _want) or ("Daily Ops",)
    if "module" not in st.session_state or st.session_state.module not in menu:
        st.session_state.module = "Daily Ops"
    for _m in menu:
        if st.button(_m, key=f"nav_{_m}", use_container_width=True,
                     type=("primary" if st.session_state.module == _m else "secondary")):
            st.session_state.module = _m
            st.rerun()
        if _m == "Daily Ops" and st.session_state.module == "Daily Ops":
            _subnav("ops_view", ["Live board", "Summary dashboard"])
        if _m == "Pricing" and st.session_state.module == "Pricing":
            _subnav("pricing_view", ["Pricing", "Supplier rules"])
        if _m == "Invoice Check" and st.session_state.module == "Invoice Check":
            _subnav("ic_view", ["Check invoices", "Matched (weekly)", "Discrepancy log"])
        if _m == "Finance" and st.session_state.module == "Finance":
            _subnav("fin_view",
                    ["Payables (Live)", "Statement Reconciliation", "Margins"])
    module = st.session_state.module

    st.write("")

    # --- Data & connections (one collapsible) ---
    with st.expander("Data & connections"):
        _ip = _server_ip()
        st.markdown(f"**Server IP** (for QuickBooks setup): `{_ip}`")
        st.caption("Paste this into Intuit's “where your app is hosted” IP box · Country: "
                   "United States · Single IP address.")
        st.divider()
        if data.get("_lazy"):
            st.caption("Live connection status loads on the **Daily Ops** page (kept off other "
                       "pages for speed).")
            if st.button("Check now", use_container_width=True):
                data = load_kpis()
        st.markdown("**Monday** — " + ("🟢 live" if data.get("live") else "🟡 snapshot"))
        if not data.get("live") and data.get("live_error"):
            st.caption(data["live_error"][:200])
        st.caption("Order KPIs — " + ("live from Orders board" if data.get("orders_live")
                                      else "summary fallback"))
        if data.get("orders_error"):
            st.caption(data["orders_error"][:160])
        st.caption("Chargebacks — " + ("live from Shopify" if data.get("shopify_live") else "via Monday"))
        st.caption("Email folders — " + ("live from Outlook" if data.get("outlook_live")
                                         else "not connected"))
        if data.get("outlook_error"):
            st.caption(data["outlook_error"][:160])
        st.caption(f"Updated: {data.get('updated','—')}")
        if st.button("Check Shopify fulfilment permission", use_container_width=True):
            try:
                sc = data_sources.shopify_token_scopes()
                can_split = any("fulfillment_orders" in s for s in sc.get("scopes", []))
                st.caption(("🟢 Can split fulfilments" if can_split else
                            "🔴 CANNOT split fulfilments — add a `write_..._fulfillment_orders` "
                            "scope to the Shopify app and regenerate the token")
                           + f" · app: {sc.get('app') or '?'}")
            except Exception as e:  # noqa: BLE001
                st.caption(f"Couldn't read Shopify scopes: {str(e)[:120]}")
        if st.button("Refresh data", use_container_width=True):
            load_kpis.clear()
            st.rerun()

    st.divider()
    # --- Settings (bottom) ---
    with st.expander("Settings"):
        st.caption(f"Signed in as {name} · {role}")
        if st.button("Change password", use_container_width=True):
            _change_password_dialog()
    authenticator.logout("Sign out", location="sidebar")

# ---------------------------------------------------------------------------
# Module dispatch — Pricing renders here and stops before the Daily Ops view.
# ---------------------------------------------------------------------------
# Role guards (enforced even if session state is tampered):
#   office → Daily Ops only · only admin/manager may open Invoice Check.
if role == "office":
    module = "Daily Ops"
elif role not in ("admin", "manager") and module in ("Invoice Check", "Finance"):
    module = "Daily Ops"
if user_modules and module not in menu:            # per-user allow-list, enforced server-side
    module = menu[0] if menu else "Daily Ops"

# --- QuickBooks OAuth callback: Intuit redirects back to the app with ?code&state&realmId ---
# One-shot (guarded) so it never re-processes the code and spins a redirect/rerun loop.
_qp = st.query_params
if _qp.get("code") and _qp.get("realmId") and not st.session_state.get("_qbo_cb_done"):
    st.session_state["_qbo_cb_done"] = True
    _stored = st.session_state.get("qbo_state")
    try:
        if _stored and _qp.get("state") != _stored:      # verify state when the session kept it
            raise RuntimeError("Security check failed (state mismatch) — click Connect again.")
        data_sources.qbo_exchange_code(_qp.get("code"), _qp.get("realmId"))
        st.session_state["qbo_flash"] = "✅ QuickBooks connected."
    except Exception as _qe:  # noqa: BLE001
        st.session_state["qbo_flash_err"] = "QuickBooks connect failed: " + str(_qe)[:300]
    st.session_state.module = "Finance"
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass
    module = "Finance"

if module == "Pricing":
    if st.session_state.get("pricing_view") == "Supplier rules":
        render_supplier_rules()
    else:
        render_pricing()
    st.stop()

if module == "Daily Activity":
    render_daily_activity()
    st.stop()

if module == "Quotes":
    render_quotes()
    st.stop()

if module == "Invoice Check":
    _ic_view = st.session_state.get("ic_view")
    if _ic_view == "Matched (weekly)":
        render_matched_weekly()
    elif _ic_view == "Discrepancy log":
        render_discrepancy_log()
    else:
        render_invoice_check()
    st.stop()

if module == "Order Processing":
    import order_processing
    order_processing.render()
    st.stop()

if module == "Finance":
    render_finance()
    st.stop()

if module == "Daily Ops" and st.session_state.get("ops_view") == "Summary dashboard":
    render_summary_dashboard()
    st.stop()

# ---------------------------------------------------------------------------
# Greeting
# ---------------------------------------------------------------------------
# Branded header bar
live_chip = ("🟢 Live" if data.get("live") else "🟡 Snapshot")
st.markdown(
    f"""<div class="ts-brandbar">
      <span class="wm">Trade<b>Hub</b> <span class="sec">Daily Ops</span></span>
      <span class="sct">{live_chip}<br>updated {data.get('updated','—')}</span>
    </div>""",
    unsafe_allow_html=True,
)

hour = now_uk().hour
greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
is_manager = role in ("admin", "manager")
my_kpis = [k for k in KPIS if username in k.get("owners", [])]
my_open = [k for k in my_kpis if not k.get("info") and status_of(k) != "green"]
st.markdown(f"### {greet}, {name.split()[0]} 👋")

if is_manager:
    # Manager view — team overview rather than a personal task list.
    team_open = [k for k in KPIS if not k.get("info") and status_of(k) != "green"]
    n_red = len([k for k in team_open if status_of(k) == "red"])
    n_amb = len([k for k in team_open if status_of(k) == "amber"])
    load_now = workload(KPIS)
    busiest_u = max(load_now, key=load_now.get) if load_now else None
    busiest_nm = (config["credentials"]["usernames"].get(busiest_u, {}).get("name", busiest_u)
                  if busiest_u else "—")
    st.markdown(
        f"**Manager view** — across the team right now: "
        f"<span class='ts-pill red'>{n_red} red</span> "
        f"<span class='ts-pill amber'>{n_amb} amber</span> "
        f"&nbsp; busiest: <b>{busiest_nm}</b>.",
        unsafe_allow_html=True,
    )
elif role == "staff":
    if my_open:
        st.markdown(
            f"You have **{len(my_open)}** item{'s' if len(my_open)!=1 else ''} needing attention today — "
            "they’re highlighted below.")
    else:
        st.success("You’re all clear — nothing outstanding on your KPIs right now. 🎉")

# ---------------------------------------------------------------------------
# Today at a glance: Mood / Pairing / Workload
# ---------------------------------------------------------------------------
# --- Team lift: a daily morale card (joke + kind words from a real customer +
# today's takings vs yesterday). Each layer degrades gracefully if a data
# source isn't configured, so the card always shows at least the joke. ---
TEAM_JOKES = [
    "Why did the scaffolder bring a pencil to work? In case he needed to draw up some plans.",
    "I told my mate the timber joke was on the house. He said the roof one was better.",
    "Why don't bricklayers ever get lost? They always follow the mortar board.",
    "I used to be a banker, but I lost interest. Now I sell cement — business is concrete.",
    "Our cheapest screws are a real steal. Don't worry, they're fully bolted down.",
    "Why did the spirit level go to therapy? It couldn't find any balance in life.",
    "I asked the joiner for advice. He said, 'Don't take it personally, but you're a bit edgy.'",
    "What do you call a builder who's lost his van? A contractor without a leg to stand on.",
    "The tape measure quit its job. It said the work just didn't measure up.",
    "Why was the cement mixer so calm? Nothing ever rattled it.",
    "I bought a boomerang made of plywood. Spent all week trying to throw the old one away.",
    "Why did the electrician keep getting promoted? He was a real live wire.",
    "The plasterer's jokes are a bit rough, but they smooth over eventually.",
    "What's a plumber's favourite kind of music? Anything with a good flow.",
    "I told the hammer to take it easy. It just couldn't stop hitting the nail on the head.",
    "Why did the ladder get an award? It really stepped up this year.",
    "Our delivery driver is so reliable, even the sat-nav asks him for directions.",
    "What do you call a tidy building site? A clean break.",
    "The drill and the screwdriver had an argument. It got a bit heated, then they bonded.",
    "Why are roofers great at parties? They always raise the bar.",
    "I tried to catch some fog at the yard this morning. Mist.",
    "Why did the paint blush? It saw the wall undressing… of its old coat.",
    "Our forklift driver lifts everyone's spirits — and a fair few pallets too.",
    "What did the nut say to the bolt? 'You complete me.'",
    "Why don't bricks ever lie? They're always on the level.",
    "The saw told a joke at break. It absolutely cut everyone up.",
    "Why was the wheelbarrow so good at its job? It was easily pushed in the right direction.",
    "I knocked over the toolbox and the spanners all argued. Total wrench in the works.",
    "Why did the customer love our quotes? They were always upfront and never wooden.",
    "Monday motivation: be like a tape measure — always pulling your weight.",
]


def joke_of_the_day():
    return TEAM_JOKES[now_uk().timetuple().tm_yday % len(TEAM_JOKES)]


KIND_FOLDERS = [("hello@tradesuperstoreonline.co.uk", n) for n in ("Inbox", "Aftersales")]


@st.cache_data(ttl=1800, show_spinner=False)
def kind_words_cached():
    """Nicest real customer message right now, or None. Cached 30 min."""
    try:
        token = data_sources.ms_token()
    except Exception:  # noqa: BLE001 — M365 not configured
        return None
    try:
        emails = []
        for mb, fname in KIND_FOLDERS:
            try:
                emails += data_sources.fetch_folder_messages(mb, fname, limit=15, token=token)
            except Exception:  # noqa: BLE001 — skip a folder that errors
                continue
        if not emails:
            return None
        return data_sources.find_kind_words(emails)
    except Exception:  # noqa: BLE001 — no AI key / API error → hide the line
        return None


# Live "done today" leaderboard — playful badges awarded from real Monday
# throughput: each lane goes to whoever did the most of that work TODAY (status
# changes attributed to the person who made them). Distinct people, busiest
# first. Falls back to the workload board if Monday is unreachable.
# (badge, column_id(s), allowed target labels or None = any change to the column)
LEADERBOARD_LANES = [
    ("📦 Delivery Dynamo", "color_mktyhmf3",
     {"Delivered", "Posted", "Out For Delivery", "AM Out For Delivery",
      "PM Out For Delivery", "Midday Delivery", "Customer Collection",
      "With Courier", "Route Planned"}),
    ("💬 Order Processor", "color_mktyje8e",
     {"Processed", "PO Sent", "Signed Off", "Place Order", "Sent for Quote"}),
    ("🔎 ETA Chaser-in-Chief", "color_mm06spvx", None),
    ("🤝 Customer Whisperer", "color_mktyyf7w", None),
    ("🕵️ Detail Detective",
     {"color_mktydktf", "numeric_mm3dc5fs", "numeric_mm3dn836", "numeric_mm3d6jn5",
      "numeric_mm3d9t22", "numeric_mm3d31gp", "text_mm22k2j7", "date6"}, None),
]


@st.cache_data(ttl=1800, show_spinner=False)
def leaderboard_today():
    """[(badge, first_name, count)] from today's real Monday throughput, or None
    if Monday can't be reached. Cached 30 min."""
    try:
        start = now_uk().replace(hour=0, minute=0, second=0, microsecond=0)
        f_iso = start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        t_iso = now_uk().astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        logs = data_sources.fetch_board_activity(ORDERS_BOARD, f_iso, t_iso)
    except Exception:  # noqa: BLE001 — Monday down / not configured → caller falls back
        return None

    tallies = {badge: {} for badge, _, _ in LEADERBOARD_LANES}
    for ev in logs:
        if ev.get("event") != "update_column_value":
            continue
        u = MONDAY_USERS.get(str(ev.get("user_id")))
        if not u or u == "daniela":  # skip automation & the manager
            continue
        try:
            dd = json.loads(ev.get("data") or "{}")
        except Exception:  # noqa: BLE001
            continue
        cid = dd.get("column_id")
        val = dd.get("value")
        lab = None
        if isinstance(val, dict):
            lv = val.get("label")
            lab = lv.get("text") if isinstance(lv, dict) else lv
        for badge, cols, labels in LEADERBOARD_LANES:
            cset = cols if isinstance(cols, set) else {cols}
            if cid in cset and (labels is None or lab in labels):
                tallies[badge][u] = tallies[badge].get(u, 0) + 1

    winners = {}
    for badge, _, _ in LEADERBOARD_LANES:
        t = tallies[badge]
        if t:
            u = max(t, key=t.get)
            winners[badge] = (u, t[u])
    return winners or None


def _distinct_winners(winners, users_cfg, top=4):
    """winners = {badge: (username, count)} → [(badge, first_name, count)],
    one badge per person, biggest first."""
    out, used = [], set()
    for badge, (u, n) in sorted(winners.items(), key=lambda kv: kv[1][1], reverse=True):
        if u in used:
            continue
        used.add(u)
        out.append((badge, users_cfg.get(u, {}).get("name", u).split()[0], n))
        if len(out) >= top:
            break
    return out


# Fallback when Monday is unreachable — "carrying the most" from open workload.
WORKLOAD_AWARDS = [
    ("💬 Order Processor", {"new_orders", "to_post", "quotes"}),
    ("🔎 ETA Chaser-in-Chief", {"unconfirmed", "eta_chasers", "supplier_etas", "supplier_no_eta"}),
    ("📦 Delivery Dynamo", {"booked_overdue", "booked_future", "difficult"}),
    ("🤝 Customer Whisperer",
     {"complaints", "aftersales", "return_requests", "returns", "pre_delivery", "cancellations"}),
    ("🕵️ Detail Detective", {"invoices", "discrepancies"}),
]


def workload_titles(kpis, users_cfg, top=4):
    """Fallback badges from open workload (carrying the most, not done today)."""
    mgrs = {u for u, i in users_cfg.items() if i.get("role") in ("admin", "manager")}
    winners = {}
    for badge, ids in WORKLOAD_AWARDS:
        s: dict = {}
        for k in kpis:
            if k.get("info") or k.get("id") not in ids:
                continue
            owners = [o for o in k.get("owners", []) if o not in mgrs]
            if not owners:
                continue
            w = (k.get("count", 0) + k.get("oldest_age_days", 0) * 0.4) / len(owners)
            for o in owners:
                s[o] = s.get(o, 0) + w
        if s:
            u = max(s, key=s.get)
            if s[u] > 0:
                winners[badge] = (u, round(s[u]))
    return _distinct_winners(winners, users_cfg, top)


load = workload(KPIS)  # workload bars — everyone (incl. Malyeka), excl. managers
ranked = sorted(load.items(), key=lambda x: x[1], reverse=True)
pair_ranked = sorted(workload(KPIS, pairing=True).items(), key=lambda x: x[1], reverse=True)
users_cfg = config["credentials"]["usernames"]

_glance = st.expander("📊  Today at a glance", expanded=True)
c1, c2, c3 = _glance.columns([1.15, 1, 1])

with c1:
    joke = joke_of_the_day()
    kw = kind_words_cached()
    live = leaderboard_today()
    if live:
        titles = _distinct_winners(live, users_cfg)
        lead_label = "🏆 Today\'s leaderboard"
    else:
        titles = workload_titles(KPIS, users_cfg)
        lead_label = "🏆 Carrying the most today"
    blocks = []

    if titles:
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'font-size:13px;padding:4px 0;border-top:1px solid var(--line)">'
            f'<span>{badge}</span><span><b style="color:#334155">{nm}</b>'
            f'<span style="color:var(--muted);font-size:11px">&nbsp;·&nbsp;{cnt}</span>'
            f'</span></div>'
            for badge, nm, cnt in titles)
        blocks.append(f'<p class="ts-eyebrow">{lead_label}</p>{rows}')

    if kw and kw.get("quote"):
        about = f' · {kw["about"]}' if kw.get("about") else ""
        blocks.append(
            f'<p class="ts-eyebrow" style="margin-top:14px">💚 Kind words from a customer{about}</p>'
            f'<p style="font-size:13.5px;font-style:italic;line-height:1.45;margin:2px 0 0">'
            f'“{kw["quote"]}”</p>'
        )

    blocks.append(
        f'<p class="ts-eyebrow" style="margin-top:14px">😄 Joke &amp; banter of the day</p>'
        f'<p style="font-size:13.5px;line-height:1.45;margin:2px 0 0">{joke}</p>'
    )

    st.markdown(
        '<div class="ts-card">'
        '<p style="font-family:\'Bebas Neue\',sans-serif;letter-spacing:.06em;'
        'font-size:20px;color:var(--brand);margin:0 0 6px">TEAM LIFT</p>'
        + "".join(blocks) + "</div>",
        unsafe_allow_html=True,
    )

with c2:
    if len(pair_ranked) >= 2:
        busy_u, busy_v = pair_ranked[0]
        quiet_u, quiet_v = pair_ranked[-1]
        busy_name = users_cfg.get(busy_u, {}).get("name", busy_u)
        quiet_name = users_cfg.get(quiet_u, {}).get("name", quiet_u)
        # Skip tasks nobody can help with (e.g. invoice approval = Malyeka only)
        # and only suggest handing over something that's actually outstanding.
        busy_kpis = sorted(
            [k for k in KPIS if not k.get("info") and not k.get("no_help")
             and busy_u in k.get("owners", []) and status_of(k) != "green"],
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
              <div style="background:rgba(59,130,246,.10);border-left:4px solid #3b82f6;
                   border-radius:8px;padding:11px 13px;font-size:13px;line-height:1.5;color:#1f2430">
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
_act_exp = st.expander(f"⚡  Act now — {reds} red · {ambers} amber outstanding", expanded=True)

_arows = ""
for k in queue:
    s = status_of(k)
    mine = role == "staff" and username in k.get("owners", [])
    yb = " <span class='yourbadge'>YOU</span>" if mine else ""
    age = f" · {k['oldest_age_days']}d" if k.get("oldest_age_days") else ""
    _arows += (
        f'<tr style="border-top:1px solid var(--line)">'
        f'<td style="padding:7px 10px;border-left:4px solid {COL[s]}">'
        f'<b>{k["name"]}</b>{yb}'
        f'<div style="color:#475569;font-size:11.5px">→ {k["action"]}</div></td>'
        f'<td style="padding:7px 10px;color:var(--muted);font-size:12px;white-space:nowrap">'
        f'{source_icon(k["source"])} {display_owners(k)}</td>'
        f'<td style="padding:7px 10px;text-align:right;white-space:nowrap;font-weight:800;font-size:18px;color:{COL[s]}">{k["count"]}'
        f'<div style="color:var(--muted);font-size:11px;font-weight:400">aim ≤{k["target"]}{age}</div></td>'
        f'<td style="padding:7px 10px;text-align:right"><span class="ts-pill {s}">{LABEL[s]}</span></td>'
        f'</tr>'
    )
if _arows:
    _act_exp.markdown(
        f'<div class="ts-card ts-tbl"><table style="width:100%;border-collapse:collapse">{_arows}</table></div>',
        unsafe_allow_html=True,
    )
if not queue:
    _act_exp.success("🎉 Nothing outstanding — every KPI is under control.")

# ---------------------------------------------------------------------------
# All KPIs by category
# ---------------------------------------------------------------------------
st.write("")
st.markdown("### 📊 All KPIs")
ICONS = {"Orders & Fulfilment": "📦", "Customer Care": "💬", "Finance & Risk": "💷",
         "Email folders": "📧"}
for cat in dict.fromkeys(k["cat"] for k in KPIS):
    cards = [k for k in KPIS if k["cat"] == cat]
    _exp = st.expander(f"{ICONS.get(cat,'📊')}  {cat}", expanded=True)

    # Email folders render as one compact table (concise, fits on screen).
    if cat == "Email folders":
        rows = ""
        for k in sorted(cards, key=lambda x: SEV[status_of(x)]):
            s = status_of(k)
            unread = f" · {k['unread']} unread" if k.get("unread") else ""
            err = " ⚠️ folder not found" if k.get("folder_error") else ""
            rows += (
                f'<tr style="border-top:1px solid var(--line)">'
                f'<td style="padding:7px 10px"><b>{k["name"]}</b><div style="color:var(--muted);font-size:11px">{display_owners(k)}{err}</div></td>'
                f'<td style="padding:7px 10px;text-align:right;font-weight:800;font-size:18px;color:{COL[s]}">{k["count"]}'
                f'<div style="color:var(--muted);font-size:11px;font-weight:400">aim ≤ {k["target"]}{unread}</div></td>'
                f'<td style="padding:7px 10px;text-align:right"><span class="ts-pill {s}">{LABEL[s]}</span></td>'
                f'</tr>'
            )
        _exp.markdown(
            f'<div class="ts-card ts-tbl"><table style="width:100%;border-collapse:collapse">{rows}</table></div>',
            unsafe_allow_html=True,
        )
        continue

    cols = _exp.columns(3)
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
                    <span class="ts-meta">Owner: <b style="color:#334155">{display_owners(k)}</b></span>
                    <span class="ts-pill {s}">{LABEL[s]}</span>
                  </div>
                  <div class="ts-meta">{source_icon(k['source'])} {k['source']}{age}</div>
                  {f'<div class="ts-meta" style="color:#15803d;font-weight:600">{target_text(k)}</div>' if target_text(k) else ''}
                  <div class="ts-prompt">{k['action']}</div>
                </div>""",
                unsafe_allow_html=True,
            )

st.caption(
    "Numbers are the latest snapshot from kpis.json. Wire load_kpis() to Monday / Shopify / "
    "Outlook for a fully automatic live feed. Thresholds and owners are editable in kpis.json."
)
