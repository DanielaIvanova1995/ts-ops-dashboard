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


@st.cache_data(ttl=300, show_spinner=False)
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


_SKU_HEAD = ('<th style="padding:7px 12px">SKU / product</th><th style="padding:7px 12px">Supplier</th>'
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
        sell, m, nm = it.get("sell"), it.get("margin"), (it.get("name") or "")[:55]
        out.append(
            f'<tr style="border-top:1px solid var(--line)">'
            f'<td style="padding:7px 12px"><b>{it["sku"]}</b>'
            f'<div style="color:var(--muted);font-size:11px">{nm}</div></td>'
            f'<td style="padding:7px 12px;font-size:12px">{sup or "—"}</td>'
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


@st.cache_data(ttl=21600, show_spinner=False)
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
            if part in _TOK_STOP or len(part) < 2:
                continue
            out.add(part)
    return out


@st.cache_data(ttl=900, show_spinner=False)
def _shopify_order_lines(order_id):
    """Live Shopify order line items (cached). None if orders aren't readable."""
    try:
        return data_sources.fetch_order_line_items(order_id)
    except Exception:  # noqa: BLE001 — fall back to Monday's copy of the order
        return None


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
                out[key] = {"sku": sku or (l.get("title") or "(no SKU)"),
                            "qty": l.get("qty"), "name": l.get("title")}
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


def _order_common_tokens(order):
    """Tokens shared across MOST order lines — typically the colour (e.g. 'Sail Cloth'),
    identical on every line and so useless for telling one product from another. We ignore
    these when name-matching, so a screw doesn't match a board just because both are that
    colour. Only applied for orders of 3+ lines."""
    from collections import Counter
    if len(order) < 3:
        return set()
    c = Counter()
    for v in order.values():
        c.update(_title_tokens(v.get("name")))
    thresh = max(2, (len(order) + 1) // 2)   # appears in roughly half the lines or more
    return {t for t, cnt in c.items() if cnt >= thresh}


def _name_pair_score(dt, ot, common):
    """Score an invoice-line vs order-line NAME match on its DISTINCTIVE shared words
    (colour / order-wide common words removed), weighted by word length so a specific word
    like 'ventilation' outweighs a generic one like 'profile'. 0 if not a credible match —
    needs 2+ distinctive shared words AND ≥40% overlap of the shorter side."""
    shared = dt & ot
    distinctive = shared - common
    if len(distinctive) < 2:
        return 0.0
    if not dt or not ot or len(shared) / min(len(dt), len(ot)) < 0.4:
        return 0.0
    return float(sum(len(t) for t in distinctive))


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
MARGIN_PUSH_MIN = 5.0           # defaults — editable in the Invoice Check settings box
MARGIN_PUSH_MAX = 35.0


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


def _push_decision(matched, is_cn, live_margin, supplier=None):
    """(label, action) for a checked invoice. action: 'push' | 'hold' | 'flag' | None.
    Supplier rules can override the push floor and the high-margin flag."""
    lo, hi = _thresholds()
    rule = SUPPLIER_RULES.get(_norm_code(supplier), {}) if supplier else {}
    lo = rule.get("push_min", lo)
    flag_high = rule.get("flag_high", True)
    if not matched:
        return None, None
    if live_margin is None or live_margin < lo:
        return MATCHED_LABEL, "hold"          # low / unknown margin → hold for review
    if flag_high and live_margin > hi:
        return DISCREPANCY_LABEL, "flag"      # suspiciously high → flag for review
    return (CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL), "push"


@st.cache_data(ttl=600, show_spinner=False)
def invoices_by_status(key):
    label_ids, lim = INVOICE_STATUS[key]
    try:
        return data_sources.fetch_invoices_by_status(label_ids, limit=lim)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@st.cache_data(ttl=600, show_spinner=False)
def invoice_count(key):
    label_ids, _lim = INVOICE_STATUS[key]
    try:
        return data_sources.fetch_invoice_count(label_ids)
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=900, show_spinner=False)
def _order_discounts(order_ids):
    """{shopify_order_id: {amount, codes}} — customer discounts. {} if unavailable."""
    if not order_ids:
        return {}
    try:
        return data_sources.fetch_order_discounts(list(order_ids))
    except Exception:  # noqa: BLE001 — Shopify orders not readable → no discount column
        return {}


@st.cache_data(ttl=86400, show_spinner=False)
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
    "pjh": {"name": "PJH", "flat": 25.0},
    "travisperkins": {"name": "Travis Perkins", "flat": 25.0, "free_over": 100.0},
    "nbp": {"name": "NBP", "flat": 17.0, "free_over": 250.0},
    "upb": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
    "up": {"name": "UPB", "flat": 15.0, "free_over": 100.0},
}

# Default email address for supplier discrepancy chases, keyed by normalised supplier
# name (_norm_code). Used as the 'To' default before the order's own email field.
SUPPLIER_EMAILS = {
    "upb": "janetwitt@upbuildingproducts.com",
    "up": "janetwitt@upbuildingproducts.com",
    "upbuildingproducts": "janetwitt@upbuildingproducts.com",
}

# Per-supplier overrides. no_pricelist = don't price-check vs the pricelist (we
# don't hold one); push_min = margin % to push above (else hold); flag_high =
# whether to flag suspiciously-high margins.
SUPPLIER_RULES = {
    "travisperkins": {"name": "Travis Perkins", "no_pricelist": True,
                      "push_min": 10.0, "flag_high": False},
}


def _expected_delivery(supplier, goods_value):
    """Expected ex-VAT delivery charge for a supplier given the order's goods value,
    or None if there's no rule on file."""
    rule = DELIVERY_CHARGES.get(supplier)
    if not rule:
        return None
    free_over = rule.get("free_over")
    if free_over is not None and goods_value is not None and goods_value >= free_over:
        return 0.0
    return float(rule.get("flat", 0.0))


def _is_delivery(text):
    t = (text or "").lower()
    return any(w in t for w in ("deliver", "carriage", "freight", "shipping",
                                "postage", "haulage", "transport"))


def _check_invoice(parsed, meta, pidx, tol=0.01):
    """3-way match: each invoice line vs the supplier's pricelist cost and vs the
    order's SKUs/quantities. Known supplier delivery charges are recognised."""
    supplier = _norm_code(meta.get("supplier"))
    no_pl = SUPPLIER_RULES.get(supplier, {}).get("no_pricelist", False)
    tidx = _supplier_title_index() if not no_pl else None
    cidx = _supplier_code_index() if not no_pl else None
    order = _order_candidates(meta)
    parsed_lines = parsed.get("lines") or []

    def _line_total(l):
        if isinstance(l.get("line_total"), (int, float)):
            return l["line_total"]
        u, q = l.get("unit_price"), l.get("qty")
        return u * q if isinstance(u, (int, float)) and isinstance(q, (int, float)) else 0

    goods_value = sum(_line_total(l) for l in parsed_lines
                      if not (_is_delivery(l.get("sku")) or _is_delivery(l.get("description"))))

    common = _order_common_tokens(order)
    lines, invoiced, pending = [], set(), []

    def _qty_note(rec, k):
        exp = order[k]["qty"]
        if exp is not None and rec["qty"] is not None:
            try:
                if int(rec["qty"]) != exp:
                    rec["issues"].append(("qty", f"invoiced {rec['qty']} vs order {exp}"))
            except (TypeError, ValueError):
                pass

    for ln in parsed_lines:
        sku_raw = ln.get("sku") or ""
        desc = ln.get("description") or ""
        qty, unit = ln.get("qty"), ln.get("unit_price")

        # Delivery / carriage line — check against the supplier's expected charge.
        if _is_delivery(sku_raw) or _is_delivery(desc):
            known = _expected_delivery(supplier, goods_value)
            amt = unit if isinstance(unit, (int, float)) else ln.get("line_total")
            dissues = []
            if isinstance(amt, (int, float)):
                if known is not None:
                    if amt > known + tol:        # only flag if charged MORE (less is fine)
                        dissues.append(("delivery", f"delivery £{amt:,.2f} vs expected £{known:,.2f}"))
                else:
                    dissues.append(("delivery", f"delivery £{amt:,.2f} — no agreed rate on file"))
            lines.append({"sku": sku_raw or "Delivery", "desc": desc, "qty": qty,
                          "unit": unit, "cost": known, "issues": dissues})
            continue

        sk = _norm_code(sku_raw)
        issues = []
        supcosts = pidx.get(sk) or {}
        cost = supcosts.get(supplier)                 # strictly the SKU's cost for this supplier
        title_note = None
        # If this supplier's SKU isn't on our pricelist, first look for THIS SUPPLIER's
        # own pricelist code printed in the line (e.g. UPB's VL7 in the description) — a
        # strict code match, the most reliable fallback…
        if cost is None and not no_pl and cidx:
            c2, mc = _supplier_code_cost(sku_raw, desc, supplier, cidx)
            if c2 is not None:
                cost, title_note = c2, f"code {mc}"
        # …then fall back to matching THIS SUPPLIER's product title (their codes differ
        # from ours, but they name products consistently — e.g. UPB). Scoped to one supplier.
        if cost is None and not no_pl and tidx:
            c2, mt = _supplier_title_cost(desc, supplier, tidx)
            if c2 is not None:
                cost, title_note = c2, mt
        if not no_pl:                                 # suppliers with no pricelist: skip price check
            if isinstance(unit, (int, float)) and isinstance(cost, (int, float)):
                if unit > cost + tol:
                    via = f" (vs '{title_note}' on the pricelist)" if title_note else ""
                    issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                            f"(+£{unit - cost:,.2f}){via}"))
                elif title_note:
                    issues.append(("name", f"price checked vs '{title_note}' on the pricelist"))
            elif isinstance(unit, (int, float)) and cost is None:
                issues.append(("noprice", "no pricelist cost for this supplier/SKU"))
        rec = {"sku": sku_raw, "desc": ln.get("description"), "qty": qty,
               "unit": unit, "cost": cost, "issues": issues}
        lines.append(rec)

        # Order match. Exact SKU and embedded-code matches are certain, so assign them now.
        # A fuzzy NAME match is DEFERRED — all name matches are then resolved together,
        # strongest first, so a weak colour-only overlap can't steal a line the right line
        # needs (see _assign below).
        if sk in order and sk not in invoiced:
            invoiced.add(sk)
            _qty_note(rec, sk)
            issues.append(("name", f"matched to order line {order[sk]['sku']} — SKU matches "
                                   "exactly"))
        else:
            ck = _code_match(sk, order, invoiced)
            if ck:
                invoiced.add(ck)
                _qty_note(rec, ck)
                issues.append(("name", f"matched to order line {order[ck]['sku']} by product "
                                       "code (in our SKU)"))
            else:
                pending.append(rec)                  # resolve by name after the loop

    # Resolve deferred name matches: score every (invoice line, unused order line) pair on
    # their distinctive shared words, then assign the strongest pairs first (each order line
    # used once). This stops the greedy "first line wins" mis-assignments.
    scored = []
    for idx, rec in enumerate(pending):
        dt = _title_tokens(rec["desc"])
        for k, v in order.items():
            if k in invoiced:
                continue
            s = _name_pair_score(dt, _title_tokens(v.get("name")), common)
            if s > 0:
                scored.append((s, idx, k))
    scored.sort(key=lambda x: (-x[0], x[1]))          # best score first, then earliest line
    done = set()
    for _s, idx, k in scored:
        if idx in done or k in invoiced:
            continue
        done.add(idx)
        invoiced.add(k)
        rec = pending[idx]
        _qty_note(rec, k)
        rec["issues"].append(("name", f"matched to order line {order[k]['sku']} by product "
                                      "name (invoice SKU differs)"))
    for idx, rec in enumerate(pending):
        if idx not in done:
            rec["issues"].append(("notorder", "not on the order"))

    missing = [order[s]["sku"] for s in order if s not in invoiced]
    # "name" notes are informational (a successful title fallback), not discrepancies.
    n_issues = sum(1 for l in lines for t, _ in l["issues"] if t != "name") + len(missing)
    return {"lines": lines, "missing": missing, "n_issues": n_issues}


def _verdict(res):
    """{order, price} for a check result. 'order' is a pass/fail bool. 'price' is
    tri-state: True (checked, all OK), False (a price/delivery mismatch), or None
    (couldn't check — at least one line had no pricelist cost). None must NOT read as a
    pass, so the table shows a grey '?' rather than a green tick."""
    order_issue = any(t in ("qty", "notorder") for l in res["lines"] for t, _ in l["issues"])
    price_issue = any(t in ("price", "delivery") for l in res["lines"] for t, _ in l["issues"])
    price_unchecked = any(t == "noprice" for l in res["lines"] for t, _ in l["issues"])
    price = False if price_issue else (None if price_unchecked else True)
    return {"order": not order_issue and not res["missing"], "price": price}


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
    st.session_state.setdefault("inv_verdict", {})[inv["sub_id"]] = v
    return res, om


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
    for sku in res.get("missing", []):
        r = f"{sku} missing from invoice"
        if r not in seen:
            seen.add(r)
            reasons.append(r)
    reason = "; ".join(reasons[:6]) or "see invoice"
    head = f"Awaiting credit note from {inv.get('supplier') or 'supplier'}"
    if credit > 0:
        head += f" of £{credit:,.2f}"
    return f"{head} — invoice {inv.get('invoice_no')}, order {inv.get('order_no')}: {reason}."


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
    for sku in res.get("missing", []):
        lines.append(f"- {sku}: on our order but not shown on this invoice — please confirm.")
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

    if st.button("Re-run check", key=f"recheck_btn_{sub}",
                 help="Reads the invoice PDF again and re-runs the match (a few pence)."):
        st.session_state[f"recheck_n_{sub}"] = nonce + 1
        st.rerun()

    res, om = _check_and_store(inv, parsed, lbsku, _pricelist_index())
    matched = res["n_issues"] == 0

    if matched:
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

    it_total, mt = parsed.get("total"), inv.get("total")
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
        chips.append(_tot_chip("Monday total", f"£{mt:,.2f}", "recorded on the order", "#6b7280"))
    if chips:
        st.markdown('<div style="display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 12px">'
                    + "".join(chips) + "</div>", unsafe_allow_html=True)

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
    if not qmiss and not res["missing"]:
        oc = ("Order check", "Match", "#16a34a", "check",
              f"All {len(order)} order line(s) match order {onum} on SKU & quantity.")
    else:
        extra = (f"; {len(res['missing'])} ordered but not invoiced "
                 f"({', '.join(res['missing'])})" if res["missing"] else "")
        oc = ("Order check", "Review", "#dc2626", "warn",
              f"{len(qmiss)} line(s) don't match order {onum}{extra}.")

    sup = inv.get("supplier") or "supplier"
    if SUPPLIER_RULES.get(_norm_code(inv.get("supplier")), {}).get("no_pricelist"):
        pc = ("Price check", "Not checked", "#6b7280", "invoice",
              f"No pricelist held for {sup} — the order margin is the reference (not flagged).")
    else:
        priced = [l for l in res["lines"] if isinstance(l.get("cost"), (int, float))]
        pissues = [l for l in priced if any(t == "price" for t, _ in l["issues"])]
        nopl = [l for l in res["lines"] if any(t == "noprice" for t, _ in l["issues"])]
        if not priced:
            pc = ("Price check", "No pricelist", "#ea580c", "warn",
                  f"No {sup} pricelist cost found — price not checked. Add {sup}'s pricelist.")
        elif pissues:
            pc = ("Price check", "Over pricelist", "#dc2626", "warn",
                  f"{len(pissues)} line(s) invoiced above {sup}'s pricelist.")
        elif nopl:
            pc = ("Price check", "Partly checked", "#ea580c", "warn",
                  f"{len(priced)} line(s) match {sup}'s pricelist, but {len(nopl)} couldn't be "
                  f"checked — no pricelist cost found. Review those before approving.")
        else:
            pc = ("Price check", "Match", "#16a34a", "check",
                  f"All {len(priced)} priced line(s) match {sup}'s pricelist.")

    st.markdown('<div style="display:flex;gap:10px;flex-wrap:wrap;margin:4px 0 8px">'
                + _check_card(*oc) + _check_card(*pc) + "</div>", unsafe_allow_html=True)

    # Recommendation + write-back to Monday's Payment Status.
    st.write("")
    is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
    push_label = CN_APPROVED_QB_LABEL if is_cn else APPROVED_QB_LABEL
    rule = SUPPLIER_RULES.get(_norm_code(inv.get("supplier")), {})
    lo = rule.get("push_min", _thresholds()[0])
    hi = _thresholds()[1]
    _label, action = _push_decision(matched, is_cn, live, inv.get("supplier"))
    livetxt = f"{live:.1f}%" if live is not None else "—"
    if action == "push":
        rec, head, col = "push", "READY TO APPROVE", "#16a34a"
        msg = f"Fully matched and order margin {livetxt} — ready to push to QuickBooks."
    elif action == "flag":
        rec, head, col = "disc", "FLAG — CHECK FIRST", "#dc2626"
        msg = (f"Matched, but order margin {livetxt} is unusually high (>{hi:.0f}%) — likely a "
               "missing invoice or credit note. Flag it and check before pushing.")
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
    if ca.button("Push credit note to QB" if is_cn else "Push to QB",
                 key=f"push_{inv['sub_id']}", use_container_width=True,
                 type=("primary" if rec == "push" else "secondary")):
        _apply_status(inv, push_label)
    if cb.button("Mark Matched (hold)", key=f"matched_{inv['sub_id']}", use_container_width=True,
                 type=("primary" if rec == "hold" else "secondary")):
        _apply_status(inv, MATCHED_LABEL)
    if cc.button("Flag discrepancy", key=f"disc_{inv['sub_id']}", use_container_width=True,
                 type=("primary" if rec == "disc" else "secondary")):
        _apply_status(inv, DISCREPANCY_LABEL)

    # Chase the supplier by email (discrepancies only) — saves to Outlook Drafts.
    if res["n_issues"] > 0:
        sub = inv["sub_id"]
        if st.toggle("Draft an email to the supplier about this", key=f"emailtog_{sub}"):
            subj0, body0 = _discrepancy_email(inv, res)
            default_to = (SUPPLIER_EMAILS.get(_norm_code(inv.get("supplier")))
                          or inv.get("supplier_email") or "")
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
            st.caption(f"Saves a **draft** in {SUPPLIER_FROM_MAILBOX} (PDF attached) for you to "
                       "review and send from Outlook, writes the note to Monday, and marks the "
                       "invoice **Discrepancy**.")
            if not inv.get("supplier_email"):
                st.caption("No supplier email on this order in Monday — type one in above.")
            if st.button("Draft to supplier & flag", key=f"esend_{sub}", type="primary",
                         disabled=not st.session_state.get(f"eto_{sub}", "").strip()):
                to = st.session_state[f"eto_{sub}"].strip()
                draft_link = None
                drafted = False
                try:
                    pdf_url = (data_sources.monday_asset_url(inv["asset_id"])
                               if inv.get("asset_id") else None)
                    pdf_name = inv.get("file_name") or f"invoice-{inv.get('invoice_no')}.pdf"
                    draft_link = data_sources.create_supplier_draft(
                        SUPPLIER_FROM_MAILBOX, to, st.session_state[f"esub_{sub}"],
                        st.session_state[f"ebod_{sub}"], pdf_url=pdf_url, pdf_name=pdf_name)
                    drafted = True
                except Exception as e:  # noqa: BLE001
                    st.error("Couldn't create the draft: " + str(e)[:200]
                             + " — if it mentions permission/scope, the app needs **Mail.ReadWrite** "
                             "for accounts@ (or accounts@ is outside its access policy).")
                if drafted:
                    # Draft created — now record it on Monday: the note + Discrepancy status.
                    try:
                        data_sources.set_subitem_text(
                            sub, "text_mm3gh2za", st.session_state[f"enote_{sub}"].strip())
                        data_sources.set_invoice_status(sub, DISCREPANCY_LABEL)
                        invoices_by_status.clear()
                        for kk in ("review", "matched", "recent", "discrepancy"):
                            st.session_state.pop(f"sel_{kk}", None)
                        link = f" [Open the draft]({draft_link})" if draft_link else ""
                        st.session_state["inv_flash"] = (
                            f"Draft to {to} saved in {SUPPLIER_FROM_MAILBOX} Drafts (review & send "
                            f"in Outlook). Noted on Monday and marked Discrepancy.{link}")
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.warning(f"Draft to {to} created, but couldn't fully update Monday: "
                                   + str(e)[:180] + " — set the status/note manually if needed.")


def _apply_status(inv, label):
    """Write the Payment Status back to Monday, refresh the queues, and flash."""
    try:
        data_sources.set_invoice_status(inv["sub_id"], label)
    except Exception as e:  # noqa: BLE001
        st.error("Couldn't update Monday: " + str(e)[:200])
        return
    invoices_by_status.clear()                       # refetch queue + logs
    for kk in ("review", "matched", "recent", "discrepancy"):  # reset row selections
        st.session_state.pop(f"sel_{kk}", None)
    st.session_state["inv_flash"] = f"Invoice {inv.get('invoice_no')} marked “{label}” on Monday."
    st.rerun()


def _bulk_check(invs, lbsku):
    """Read + 3-way check every invoice (cached), then auto-process: fully matched
    with order margin ≥5% → pushed to QB; matched but below 5% → held as Matched;
    discrepancies left for review. Reruns when done."""
    pidx = _pricelist_index()
    n = len(invs)
    _, hi = _thresholds()
    prog = st.progress(0.0, text="Reading, checking & processing invoices…")
    pushed = held = flagged = unmatched = fail = 0
    for i, inv in enumerate(invs, 1):
        parsed = _read_invoice(inv["asset_id"], inv["sub_id"])
        if parsed.get("error"):
            fail += 1
        else:
            res, _om = _check_and_store(inv, parsed, lbsku, pidx)
            matched = res["n_issues"] == 0
            is_cn = isinstance(parsed.get("total"), (int, float)) and parsed["total"] < 0
            label, action = _push_decision(matched, is_cn, inv.get("order_margin_live"),
                                           inv.get("supplier"))
            if action in ("push", "hold", "flag"):
                try:
                    data_sources.set_invoice_status(inv["sub_id"], label)
                    pushed += action == "push"
                    held += action == "hold"
                    flagged += action == "flag"
                except Exception:  # noqa: BLE001
                    pass
            else:
                unmatched += 1
        prog.progress(i / n, text=f"Processed {i}/{n}")
    prog.empty()
    invoices_by_status.clear()
    st.session_state["inv_flash"] = (
        f"Processed {n}: pushed {pushed} to QB, held {held} as Matched, flagged {flagged} "
        f"(margin >{hi:.0f}%), {unmatched} left for manual review"
        + (f", {fail} unreadable" if fail else "") + ".")
    st.rerun()


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
                   "— click a row to see its summary and check results.")
    if not fil:
        st.info("No invoices match that filter/search.")
        return

    # Customer discounts on the Shopify orders (annotate each invoice). Keyed off the
    # rows we'll actually show (fil), so the Recent tab doesn't fan out 800 Shopify calls.
    disc = _order_discounts(tuple(sorted({i["shopify_order_id"] for i in fil
                                          if i.get("shopify_order_id")})))
    for i in fil:
        i["_discount"] = (disc.get(i.get("shopify_order_id")) or {}).get("amount")

    verdicts = st.session_state.get("inv_verdict", {})

    def _icon_pass(b):  # True → check, False → cross, None → blank
        return _INV_ICON["check"] if b is True else (_INV_ICON["cross"] if b is False else None)

    lbsku = _lookup_by_sku()

    # Bulk-check & auto-process (To-check tab only; writes to QB, so always confirm).
    if key == "review":
        checkable = [i for i in fil if i.get("asset_id")]
        pend = f"bulk_pending_{key}"
        bc1, bc2 = st.columns([1, 2])
        if bc1.button(f"Bulk-check & process {len(checkable)}", key=f"bulk_{key}",
                      disabled=not checkable, use_container_width=True,
                      help="Checks every invoice shown, then pushes matched (≥5% margin) to QB and "
                           "holds the rest as Matched."):
            st.session_state[pend] = True
        done = [i for i in fil if i["sub_id"] in verdicts]
        if done:
            mt = sum(1 for i in done
                     if verdicts[i["sub_id"]]["order"] and verdicts[i["sub_id"]]["price"])
            bc2.markdown(f"<div style='padding-top:7px;font-size:13px'>Checked "
                         f"<b>{len(done)}</b>/{len(fil)} &nbsp;·&nbsp; {_inv_inline('check', 16)} "
                         f"{mt} matched &nbsp;·&nbsp; {_inv_inline('warn', 16)} "
                         f"{len(done) - mt} discrepancy</div>", unsafe_allow_html=True)
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

    rows = []
    for inv in fil:
        v = verdicts.get(inv["sub_id"]) if is_queue else None
        is_cn = isinstance(inv.get("total"), (int, float)) and inv["total"] < 0
        row = {"Type": _INV_ICON["crn_badge"] if is_cn else _INV_ICON["inv_badge"]}
        if is_queue:
            row["Status"] = (_INV_ICON["check"] if (v and v["order"] and v["price"])
                             else _INV_ICON["warn"] if v else None)
        row["Invoice"] = inv.get("invoice_no") or ""
        row["Order"] = inv.get("order_no") or ""
        row["Supplier"] = inv.get("supplier") or ""
        if is_recent:
            row["Result"] = _recent_result(inv.get("status"))
        row["Inv £"] = inv.get("total")
        if is_queue:
            row["Invoice margin"] = (v or {}).get("margin")
        row["Order margin"] = inv.get("order_margin_live")
        row["Discount"] = inv.get("_discount") if inv.get("_discount") else None
        if is_queue:
            row["vs Shopify"] = _icon_pass(v["order"]) if v else None
            # price is tri-state: None = couldn't check → grey '?', never a green tick.
            row["vs Pricelist"] = (None if not v else _INV_ICON["qmark"]
                                   if v["price"] is None else _icon_pass(v["price"]))
        else:
            row["Date"] = (_fmt_actioned(inv.get("actioned_at")) if is_recent
                           else inv.get("date") or "")
        row["PDF"] = inv.get("file_url")
        rows.append(row)

    colcfg = {
        "Type": st.column_config.ImageColumn("Type", width="small",
                                             help="Invoice or credit note"),
        "Inv £": st.column_config.NumberColumn(format="£%.2f", width="small"),
        "Order margin": st.column_config.NumberColumn(
            format="%.1f%%", width="small",
            help="OVERALL margin for this whole order from Monday — across ALL invoices and "
                 "credit notes relating to the order. Use this to be sure the order is profitable "
                 "before approving (catches duplicate/extra invoices)."),
        "Discount": st.column_config.NumberColumn(
            format="£%.2f", width="small",
            help="Customer discount used on the Shopify order (reduces margin). Blank = none. "
                 "Check this when the margin is low."),
        "PDF": st.column_config.LinkColumn(
            "PDF", display_text="OPEN", width="small", help="Open the invoice PDF"),
    }
    if is_recent:
        colcfg["Result"] = st.column_config.TextColumn(
            "Result", width="medium", help="What Trade Hub last did with this invoice")
        colcfg["Date"] = st.column_config.TextColumn(
            "When", width="small", help="When this invoice was last actioned")
    if is_queue:
        colcfg["Status"] = st.column_config.ImageColumn("Status", width="small",
                                                        help="Matched or discrepancy")
        colcfg["Invoice margin"] = st.column_config.NumberColumn(
            format="%d%%", width="small",
            help="Margin on THIS individual invoice (its own lines vs your ex-VAT sell price). "
                 "Shows once the invoice has been checked.")
        colcfg["vs Shopify"] = st.column_config.ImageColumn(
            "vs Shopify", width="small", help="SKUs & quantities match the order")
        colcfg["vs Pricelist"] = st.column_config.ImageColumn(
            "vs Pricelist", width="small",
            help="Green tick = all line prices checked and match the pricelist. Red cross = a "
                 "price is wrong. Grey ? = couldn't check (no pricelist cost matched) — treat as "
                 "a discrepancy to review, NOT a pass.")

    df = pd.DataFrame(rows)
    for c in ("Inv £", "Invoice margin", "Order margin", "Discount"):  # None → blank
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    event = st.dataframe(df, hide_index=True, use_container_width=True,
                         key=f"sel_{key}", on_select="rerun", selection_mode="multi-row",
                         column_config=colcfg)

    # NOTHING runs on a row click — ticking rows only selects them. The user then presses
    # "Check & open selected" to actually read/open them, so the AI (which costs money) is
    # never triggered just by clicking. The chosen ids live in session so the panels — and
    # their buttons (e.g. Push to QB) — survive the reruns those buttons cause.
    picked = event.selection.rows if (event and event.selection) else []
    picked_ids = [fil[i]["sub_id"] for i in picked]
    show_key = f"inv_show_{key}"

    if picked_ids:
        n_uncheck = sum(1 for sid in picked_ids if sid not in verdicts)
        if n_uncheck:
            lbl = f"Check & open selected ({len(picked_ids)})"
            hlp = (f"{n_uncheck} not checked yet — reads those PDFs now "
                   f"(~£{n_uncheck * 0.01:.2f}–£{n_uncheck * 0.04:.2f}). "
                   "Already-checked ones are free (cached).")
        else:
            lbl = f"Open selected ({len(picked_ids)})"
            hlp = "All selected are already checked — opening them is free (cached)."
        if st.button(lbl, key=f"opensel_{key}", type="primary", help=hlp):
            # Run each check now (cached reads) so verdicts exist — the panels then open
            # COLLAPSED with an accurate matched/discrepancy header, rather than all blowing
            # open at once. The user opens the ones they want to inspect.
            pidx = _pricelist_index()
            with st.spinner(f"Checking {len(picked_ids)} invoice(s)…"):
                for sid in picked_ids:
                    iv = next((i for i in fil if i["sub_id"] == sid), None)
                    if iv and iv.get("asset_id"):
                        parsed = _read_invoice(iv["asset_id"], iv["sub_id"])
                        if not parsed.get("error"):
                            _check_and_store(iv, parsed, lbsku, pidx)
            st.session_state[show_key] = picked_ids
            st.rerun()
    else:
        st.caption("Tick one or more invoices above, then click **Check & open selected** — "
                   "nothing runs (or costs) until you press it. They then list closed, each "
                   "clearly marked matched or discrepancy — open the ones you want to check.")

    show_ids = [sid for sid in st.session_state.get(show_key, [])
                if any(i["sub_id"] == sid for i in fil)]  # drop any that left this queue

    def _is_disc(sid):
        v = verdicts.get(sid)
        return bool(v) and not (v.get("order") and v.get("price"))

    chosen = [i for i in fil if i["sub_id"] in show_ids]
    flagged = [i for i in fil if is_queue and _is_disc(i["sub_id"]) and i["sub_id"] not in show_ids]
    # Open a single pick for convenience; keep a batch of picks (and all flagged) CLOSED so
    # the screen stays readable — the header tells you which is which; open what you want.
    solo = len(chosen) == 1 and not flagged
    review = [(i, solo) for i in chosen] + [(i, False) for i in flagged[:15]]

    def _outcome_tag(inv):
        v = verdicts.get(inv["sub_id"])
        if not v:
            return "▸ not checked yet — opens & checks (a few pence)"
        if v.get("order") and v.get("price") is True:
            m = v.get("margin")
            return f"✅ MATCHED — ready to approve{f' · {m}% margin' if m is not None else ''}"
        if v.get("order") and v.get("price") is None:
            return "❓ PRICE NOT CHECKED — review (no pricelist cost)"
        return "⚠ DISCREPANCY — review"

    if review:
        st.markdown("##### Review — checked invoices (closed; open the ones you want)")
        st.caption("Each line shows its result in the title: ✅ matched & ready to approve, "
                   "⚠ discrepancy, or ❓ price couldn't be checked. Opening a checked one is free "
                   "(cached 24h) — only an unchecked invoice or **Re-run check** uses the AI.")
        for inv, expanded in review:
            is_cn = isinstance(inv.get("total"), (int, float)) and inv["total"] < 0
            head = (f"{'CRN' if is_cn else 'INV'}   {inv.get('invoice_no')}   ·   "
                    f"{inv.get('supplier') or '—'}   ·   order {inv.get('order_no') or '—'}"
                    f"   —   {_outcome_tag(inv)}")
            with st.expander(head, expanded=expanded):
                _run_one_invoice(inv, lbsku)
        if len(flagged) > 15:
            st.caption(f"+{len(flagged) - 15} more discrepancies — filter by supplier to narrow.")

        # Bulk-approve: push the checked, fully-matched invoices to QuickBooks together —
        # no need to open each and click Push. Discrepancies and not-fully-checked ones are
        # excluded (they need review first). Each is pre-ticked only if it's within the
        # auto-push margin range; the rest are shown but left for you to tick deliberately.
        pushable = [i for i in chosen
                    if (verdicts.get(i["sub_id"]) or {}).get("order")
                    and (verdicts.get(i["sub_id"]) or {}).get("price") is True]
        if pushable:
            st.markdown("---")
            st.markdown("##### Approve matched invoices → push to QuickBooks in bulk")
            for i in pushable:
                sidp = i["sub_id"]
                is_cn = isinstance(i.get("total"), (int, float)) and i["total"] < 0
                om = i.get("order_margin_live")
                _, action = _push_decision(True, is_cn, om, i.get("supplier"))
                note = ("" if action == "push"
                        else " — below target, review" if action == "hold"
                        else " — margin high, review" if action == "flag" else "")
                st.session_state.setdefault(f"pushpick_{key}_{sidp}", action == "push")
                st.checkbox(
                    f"{'CRN' if is_cn else 'INV'} {i.get('invoice_no')} · "
                    f"{i.get('supplier') or '—'} · order {i.get('order_no') or '—'}"
                    + (f" · order margin {om:.0f}%" if isinstance(om, (int, float)) else "")
                    + note,
                    key=f"pushpick_{key}_{sidp}")
            ticked = [i for i in pushable if st.session_state.get(f"pushpick_{key}_{i['sub_id']}")]
            pend = f"bulkpush_pending_{key}"
            if st.button(f"Push {len(ticked)} to QuickBooks", key=f"bulkpushbtn_{key}",
                         type="primary", disabled=not ticked):
                st.session_state[pend] = [i["sub_id"] for i in ticked]
            if st.session_state.get(pend):
                ids = st.session_state[pend]
                st.warning(f"Push **{len(ids)}** matched invoice(s) to QuickBooks? This marks each "
                           "**Approved (To QB)** (credit notes → **CN Approved (To QB)**) on Monday.")
                yc, nc = st.columns(2)
                if yc.button("Yes — push to QuickBooks", key=f"bulkpushyes_{key}", type="primary",
                             use_container_width=True):
                    st.session_state.pop(pend, None)
                    byid = {i["sub_id"]: i for i in pushable}
                    ok = fail = 0
                    prog = st.progress(0.0, text="Pushing to QuickBooks…")
                    for n, sid in enumerate(ids, 1):
                        inv2 = byid.get(sid)
                        if inv2:
                            is_cn2 = isinstance(inv2.get("total"), (int, float)) and inv2["total"] < 0
                            lab = CN_APPROVED_QB_LABEL if is_cn2 else APPROVED_QB_LABEL
                            try:
                                data_sources.set_invoice_status(sid, lab)
                                ok += 1
                            except Exception:  # noqa: BLE001
                                fail += 1
                        prog.progress(n / len(ids))
                    invoices_by_status.clear()
                    for kk in ("review", "matched", "recent", "discrepancy"):
                        st.session_state.pop(f"sel_{kk}", None)
                    for sid in ids:
                        st.session_state.pop(f"pushpick_{key}_{sid}", None)
                    st.session_state["inv_flash"] = (
                        f"Pushed {ok} invoice(s) to QuickBooks."
                        + (f" {fail} failed — check Monday." if fail else ""))
                    st.rerun()
                if nc.button("Cancel", key=f"bulkpushno_{key}", use_container_width=True):
                    st.session_state.pop(pend, None)
                    st.rerun()


def render_invoice_check():
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

    for col, (key, label, _q) in zip(st.columns(len(tabs)), tabs):
        active = st.session_state["inv_tab"] == key
        btn_label = label if key == "recent" else f"{label} ({_count(key)})"
        if col.button(btn_label, key=f"itab_{key}", use_container_width=True,
                      type="primary" if active else "secondary"):
            st.session_state["inv_tab"] = key
            st.rerun()
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
# Bump this whenever the parse/quote logic changes — stale cached quotes in a live
# session then auto-recompute instead of showing old results.
QUOTE_PARSE_VERSION = 6


@st.cache_data(ttl=300, show_spinner=False)
def _quote_emails():
    try:
        return {"emails": data_sources.fetch_quote_emails(QUOTE_MAILBOX, QUOTE_FOLDER, limit=25)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
_FOLLOWUP_RE = re.compile(r"^\s*(re|fw|fwd)\s*:", re.I)


def _parse_one_quote(email):
    """Thread fetch + ONE AI extraction (the single source of truth for both the
    overview table and the quote build) + postcode backstop. Plain function — calls
    only data_sources (no st.*), so it is safe to run in a worker thread. Returns the
    parsed dict, or {'error': ...}."""
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
    try:
        parsed = data_sources.extract_quote_items(thread)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    parsed["thread"] = thread
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


def _ensure_parsed(emails):
    """Parse every email once (uncached ones in parallel). Returns the {id: parsed}
    cache so the table and the build share exactly the same extraction."""
    import concurrent.futures as _cf
    cache = _quote_cache()
    todo = [e for e in emails if not _parse_is_current(cache.get(e["id"]))]
    if todo:
        with st.spinner(f"Reading {len(todo)} quote email(s)…"):
            with _cf.ThreadPoolExecutor(max_workers=8) as ex:
                done = list(ex.map(lambda e: (e["id"], _parse_one_quote(e)), todo))
        for eid, parsed in done:
            cache[eid] = parsed
    return cache


def _email_cladding_takeoff(clad):
    """Turn a Hardie cladding email enquiry (area-based) into board + accessory lines —
    so '15 m²' becomes the right number of boards, not 15 boards. Returns (raw_lines,
    caveats). raw_lines: [{description, qty, search}]."""
    import math
    product = clad.get("product") or "Hardie Plank"
    cov = 0.72 if "vl" in product.lower() else 0.54  # lap HardiePlank = 0.54 m²/board
    gross = clad.get("gross_area_m2") or 0
    openings = clad.get("openings_m2") or 0
    net = max(0.0, gross - openings)
    if net <= 0:
        return None, None
    boards = math.ceil(net / cov * 1.10)  # +10% waste
    colour = (clad.get("colour") or "").strip()
    board_desc = f"{product} cladding" + (f" — {colour}" if colour else "")
    raw = [{"description": board_desc, "qty": boards,
            "search": f"{product} {colour}".strip()}]
    batten_lm = net / 0.6
    if clad.get("wants_screws"):
        raw.append({"description": "James Hardie cladding screws (box of 250)",
                    "qty": max(1, math.ceil(boards * 7 / 250)),
                    "search": "James Hardie cladding fixing screws"})
    if clad.get("wants_epdm"):
        raw.append({"description": "EPDM joint tape (20m roll)",
                    "qty": max(1, math.ceil(batten_lm / 20)),
                    "search": "James Hardie EPDM tape 20m"})
    cav = [f"Boards worked out from {net:.1f} m² to clad "
           f"({gross:.1f} m² less {openings:.1f} m² of openings) ÷ {cov} m²/board "
           f"+ 10% waste = {boards} boards."]
    if not colour:
        cav.append("Colour/finish not confirmed — please let us know which colour you'd like.")
    if clad.get("wants_trims"):
        cav.append("Trims (starter/top vent, corner and window trims): these are sized from the "
                   "elevation widths and corner count, which we don't have yet — send those and "
                   "we'll add the exact trim pack.")
    return raw, cav


def _build_quote(email):
    """Full build for ONE email: reuse the shared parse, then lazily add Shopify
    matching and the composed clarify email (computed once, stored on the parse)."""
    cache = _quote_cache()
    parsed = cache.get(email["id"])
    if not _parse_is_current(parsed):
        parsed = _parse_one_quote(email)
        cache[email["id"]] = parsed
    if parsed.get("error"):
        return parsed
    if "lines" not in parsed:
        clad = parsed.get("cladding") or {}
        raw_clad, clad_cav = (None, None)
        if clad.get("is_cladding") and (clad.get("gross_area_m2") or 0) > 0:
            raw_clad, clad_cav = _email_cladding_takeoff(clad)
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
    # Only fall back to a pure "ask for details" email when there is genuinely nothing we
    # can price. If we found any priceable item we quote provisionally and flag the gaps.
    has_priceable = any(l.get("match") and l["match"].get("price") is not None
                        for l in parsed["lines"])
    if not has_priceable and "clarify_email" not in parsed:
        qs = parsed.get("questions") or (
            [parsed["missing_info"]] if parsed.get("missing_info") else [])
        qs = [str(x).strip() for x in qs if x and str(x).strip()]
        parsed["questions"] = qs
        # Fallback: search our catalogue for the products the customer described.
        parsed["suggestions"] = _quote_suggestions(parsed)
        parsed["delivery_note"] = _delivery_note(parsed)
        try:
            parsed["clarify_email"] = data_sources.compose_customer_email(
                parsed.get("thread", ""), "clarify",
                {"customer_name": parsed.get("customer_name"), "questions": qs,
                 "suggestions": parsed["suggestions"], "delivery_note": parsed["delivery_note"]})
        except Exception:  # noqa: BLE001 — no AI key etc.; render falls back to a template
            parsed["clarify_email"] = None
    return parsed


def _delivery_note(parsed):
    """Standard stock/delivery-by-postcode note, with the internal-doors caveat when the
    enquiry involves doors."""
    note = ("Please note that stock availability and delivery charges can vary depending on the "
            "delivery postcode — if you let us know your postcode we'll confirm both.")
    text = " ".join(str(parsed.get(k) or "") for k in ("product_range", "summary")).lower()
    text += " " + " ".join(str(it.get("description") or "")
                           for it in (parsed.get("items") or [])).lower()
    if "door" in text:
        note += (" Internal doors in particular cannot be quoted for delivery until we have a "
                 "delivery postcode.")
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
    return (f"Hi {name},\n\nThanks for your enquiry. To put your quote together, could you "
            "please confirm:\n\n" + bullets + sugg_txt +
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
    with st.spinner("Reading the conversation and pricing from Shopify…"):
        q = _build_quote(email)
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
            prod = (f'{_esc(m.get("title") or "?")}<div style="color:var(--muted);font-size:11px">'
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


def render_finance():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Finance</span></span></div>""",
        unsafe_allow_html=True,
    )
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
    all_modules = ("Daily Ops", "Daily Activity", "Quotes", "Pricing", "Invoice Check", "Finance")
    staff_modules = ("Daily Ops", "Daily Activity", "Quotes", "Pricing")
    if role == "office":
        menu = ("Daily Ops",)
    elif role in ("admin", "manager"):
        menu = all_modules
    else:
        menu = staff_modules
    if "module" not in st.session_state or st.session_state.module not in menu:
        st.session_state.module = "Daily Ops"
    for _m in menu:
        if st.button(_m, key=f"nav_{_m}", use_container_width=True,
                     type=("primary" if st.session_state.module == _m else "secondary")):
            st.session_state.module = _m
            st.rerun()
        if _m == "Daily Ops" and st.session_state.module == "Daily Ops":
            st.radio("Daily Ops view", ["Live board", "Summary dashboard"],
                     key="ops_view", label_visibility="collapsed")
        if _m == "Pricing" and st.session_state.module == "Pricing":
            st.radio("Pricing view", ["Pricing", "Supplier rules"],
                     key="pricing_view", label_visibility="collapsed")
    module = st.session_state.module

    st.write("")

    # --- Data & connections (one collapsible) ---
    with st.expander("Data & connections"):
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
    render_invoice_check()
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
