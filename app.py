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
        data["updated"] = now_uk().strftime("%d %b %Y · %H:%M")
    except Exception as e:  # noqa: BLE001 — stay up on any data-source hiccup
        data["live_error"] = str(e)

    # Live counts straight from the real Orders board (overrides the stale
    # summary-board figures for the stage-group KPIs).
    group_map = {k["id"]: k["orders_group_id"] for k in data["kpis"] if k.get("orders_group_id")}
    if group_map:
        try:
            gc = data_sources.fetch_orders_group_counts(group_map)
            for k in data["kpis"]:
                if k["id"] in gc:
                    k["count"] = gc[k["id"]]["count"]
                    k["oldest_age_days"] = gc[k["id"]]["age"]
            data["orders_live"] = True
        except Exception as e:  # noqa: BLE001 — fall back to summary board figures
            data["orders_error"] = str(e)

    # Booked overdue/future — split the booked group by Customer ETA date.
    try:
        bs = data_sources.fetch_booked_split(1786542990, "group_mkv7t11j", "date", now_uk().date())
        for k in data["kpis"]:
            if k["id"] == "booked_overdue":
                k["count"], k["oldest_age_days"] = bs["overdue"]["count"], bs["overdue"]["age"]
                k["source"] = "Monday · Orders board (live)"
            elif k["id"] == "booked_future":
                k["count"], k["oldest_age_days"] = bs["future"]["count"], 0
                k["source"] = "Monday · Orders board (live)"
    except Exception as e:  # noqa: BLE001
        data["booked_error"] = str(e)

    # Invoices & discrepancies — live subitem Payment Status counts.
    for kid, label_id in (("invoices", 3), ("discrepancies", 4)):
        try:
            r = data_sources.fetch_filtered_count(3547638043, "status7__1", [label_id])
            for k in data["kpis"]:
                if k["id"] == kid:
                    k["count"], k["oldest_age_days"] = r["count"], r["age"]
                    k["source"] = "Monday · subitems (live)"
        except Exception as e:  # noqa: BLE001
            data[f"{kid}_error"] = str(e)

    # Complaints — live count of Orders with Customer Stage = Complaint.
    try:
        r = data_sources.fetch_filtered_count(1786542990, "color_mktyyf7w", [8])
        for k in data["kpis"]:
            if k["id"] == "complaints":
                k["count"], k["oldest_age_days"] = r["count"], r["age"]
                k["source"] = "Monday · Customer Stage = Complaint (live)"
    except Exception as e:  # noqa: BLE001
        data["complaints_error"] = str(e)

    # Outlook folders (read + unread) via Microsoft Graph.
    outlook_kpis = [k for k in data["kpis"] if k.get("outlook")]
    if outlook_kpis:
        try:
            tok = data_sources.ms_token()
            data["outlook_live"] = True
        except Exception as e:  # noqa: BLE001 — M365 not configured / unreachable
            tok = None
            data["outlook_error"] = str(e)
        if tok:
            for k in outlook_kpis:
                try:
                    spec = k["outlook"]
                    res = data_sources.fetch_outlook_folder_count(spec["mailbox"], spec["folder"], token=tok)
                    k["count"], k["oldest_age_days"] = res["count"], 0
                    k["unread"] = res["unread"]
                except Exception as e:  # noqa: BLE001 — folder not found etc.
                    k["folder_error"] = str(e)

    # Chargebacks straight from Shopify (overrides the Monday-mirrored figure).
    try:
        cb = data_sources.fetch_shopify_chargebacks()
        for k in data["kpis"]:
            if k["id"] == "chargebacks":
                k["count"] = cb["count"]
                k["oldest_age_days"] = cb["age"]
                k["source"] = "Shopify · Live disputes"
        data["shopify_live"] = True
    except Exception as e:  # noqa: BLE001 — fall back to the Monday number
        data["shopify_error"] = str(e)
    return data


data = load_kpis()
KPIS = data["kpis"]


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
    """Order line text → {norm_sku: {sku, qty}}."""
    out = {}
    for line in (text or "").split("\n"):
        skum = re.search(r"SKU:\s*([^\s|]+)", line)
        if not skum:
            continue
        qtym = re.search(r"Quantity:\s*(\d+)", line)
        out[_norm_code(skum.group(1))] = {"sku": skum.group(1),
                                          "qty": int(qtym.group(1)) if qtym else None}
    return out


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


INVOICE_STATUS = {            # key → (Monday status7__1 label ids, fetch limit)
    "review": ([3], 80),
    "approved": ([0, 1, 2, 8], 200),
    "discrepancy": ([4], 200),
}


@st.cache_data(ttl=600, show_spinner=False)
def invoices_by_status(key):
    label_ids, lim = INVOICE_STATUS[key]
    try:
        return data_sources.fetch_invoices_by_status(label_ids, limit=lim)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@st.cache_data(ttl=86400, show_spinner=False)
def _read_invoice(asset_id, sub_id):
    """Read + cache one invoice's parsed PDF (keyed per asset/sub so it's billed once)."""
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


def _check_invoice(parsed, meta, pidx, tol=0.01):
    """3-way match: each invoice line vs the supplier's pricelist cost and vs the
    order's SKUs/quantities."""
    supplier = _norm_code(meta.get("supplier"))
    order = _parse_order_items(meta.get("order_items"))
    lines, invoiced = [], set()
    for ln in (parsed.get("lines") or []):
        sku_raw = ln.get("sku") or ""
        sk = _norm_code(sku_raw)
        invoiced.add(sk)
        qty, unit = ln.get("qty"), ln.get("unit_price")
        issues = []
        supcosts = pidx.get(sk) or {}
        cost = supcosts.get(supplier)
        if isinstance(unit, (int, float)) and isinstance(cost, (int, float)):
            if unit > cost + tol:
                issues.append(("price", f"£{unit:,.2f} vs pricelist £{cost:,.2f} "
                                        f"(+£{unit - cost:,.2f})"))
        elif isinstance(unit, (int, float)) and cost is None:
            issues.append(("noprice", "no pricelist cost for this supplier/SKU"))
        if sk and sk not in order:
            issues.append(("notorder", "not on the order"))
        elif sk in order:
            exp = order[sk]["qty"]
            if exp is not None and qty is not None and int(qty) != exp:
                issues.append(("qty", f"invoiced {qty} vs order {exp}"))
        lines.append({"sku": sku_raw, "desc": ln.get("description"), "qty": qty,
                      "unit": unit, "cost": cost, "issues": issues})
    missing = [order[s]["sku"] for s in order if s not in invoiced]
    n_issues = sum(len(l["issues"]) for l in lines) + len(missing)
    return {"lines": lines, "missing": missing, "n_issues": n_issues}


def _run_one_invoice(inv, lbsku):
    """Read one invoice's PDF, run the 3-way match, and render the result with
    the margin we make and explicit pricelist + order checks."""
    if not inv.get("asset_id"):
        st.warning("No PDF is attached to this invoice on Monday — nothing to read.")
        return
    with st.spinner("Reading the invoice and matching…"):
        parsed = _read_invoice(inv["asset_id"], inv["sub_id"])
    if parsed.get("error"):
        if "ANTHROPIC_API_KEY" in parsed["error"]:
            st.info("Add your **ANTHROPIC_API_KEY** in Settings → Secrets to read invoices.")
        else:
            st.error("Couldn't read the invoice: " + parsed["error"][:200])
        return

    res = _check_invoice(parsed, inv, _pricelist_index())
    inv_costs = {_norm_code(l.get("sku")): l.get("unit_price")
                 for l in (parsed.get("lines") or [])
                 if isinstance(l.get("unit_price"), (int, float))}
    om = _order_margin(inv.get("order_items"), lbsku, cost_override=inv_costs)

    it_total, mt = parsed.get("total"), inv.get("total")
    bits = []
    if isinstance(it_total, (int, float)):
        bits.append(f"Invoice total **£{it_total:,.2f}** ex-VAT")
    if isinstance(mt, (int, float)):
        bits.append(f"Monday total £{mt:,.2f}")
    if bits:
        st.caption(" · ".join(bits))

    if om:
        cov = "" if om["matched"] == om["total"] else f" · {om['matched']}/{om['total']} lines priced"
        col = "#10b981" if om["margin"] >= 18 else "#ea580c" if om["margin"] >= 0 else "#ef4444"
        st.markdown(
            f'<div style="font-size:15px;margin:2px 0 8px">Margin we make on this order: '
            f'<b style="color:{col}">{om["margin"]:.0f}%</b> '
            f'<span style="color:var(--muted);font-size:12px">— sell £{om["rev"]:,.2f} vs '
            f'cost £{om["cost"]:,.2f} ex-VAT (using this invoice&#39;s costs){cov}</span></div>',
            unsafe_allow_html=True)

    badge = {"price": "#ef4444", "qty": "#ea580c", "notorder": "#ef4444", "noprice": "#94a3b8"}
    rows = ""
    for l in res["lines"]:
        u = f"£{l['unit']:,.2f}" if isinstance(l["unit"], (int, float)) else "—"
        c = f"£{l['cost']:,.2f}" if isinstance(l["cost"], (int, float)) else "—"
        flags = "".join(
            f'<span style="background:{badge.get(t, "#94a3b8")};color:#fff;border-radius:3px;'
            f'padding:0 5px;font-size:10px;margin-right:4px">{msg}</span>'
            for t, msg in l["issues"]) or '<span style="color:#10b981">✓</span>'
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:6px 10px"><b>{l["sku"] or "—"}</b>'
                 f'<div style="color:var(--muted);font-size:11px">{(l.get("desc") or "")[:60]}</div></td>'
                 f'<td style="padding:6px 10px;text-align:center">{l["qty"] if l["qty"] is not None else "—"}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{u}</td>'
                 f'<td style="padding:6px 10px;text-align:right">{c}</td>'
                 f'<td style="padding:6px 10px">{flags}</td></tr>')
    st.markdown('<table style="width:100%;border-collapse:collapse;font-size:12.5px">'
                '<tr style="text-align:left;color:var(--muted)">'
                '<th style="padding:6px 10px">SKU</th><th style="padding:6px 10px;text-align:center">Qty</th>'
                '<th style="padding:6px 10px;text-align:right">Invoiced</th>'
                '<th style="padding:6px 10px;text-align:right">Pricelist</th>'
                '<th style="padding:6px 10px">Check</th></tr>' + rows + "</table>",
                unsafe_allow_html=True)

    # Two explicit checks, stated separately so it's clear both ran.
    order = _parse_order_items(inv.get("order_items"))
    onum = inv.get("order_no") or "?"
    qmiss = [l for l in res["lines"] if any(t in ("qty", "notorder") for t, _ in l["issues"])]
    if not qmiss and not res["missing"]:
        st.success(f"✓ Checked against Shopify order {onum}: all {len(order)} order line(s) "
                   f"match on SKU & quantity.")
    else:
        extra = (f", {len(res['missing'])} ordered but not invoiced ({', '.join(res['missing'])})"
                 if res["missing"] else "")
        st.warning(f"⚠ Checked against Shopify order {onum}: {len(qmiss)} line(s) don't match"
                   f"{extra}.")
    sup = inv.get("supplier") or "supplier"
    pissues = [l for l in res["lines"] if any(t == "price" for t, _ in l["issues"])]
    if pissues:
        st.warning(f"⚠ Checked against {sup} pricelist: {len(pissues)} line(s) above pricelist.")
    else:
        st.success(f"✓ Checked against {sup} pricelist: all priced lines match.")


def _invoice_tab(key, checkable):
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
    st.caption(f"{len(fil)} of {len(invs)}{'+' if data.get('more') else ''} invoices.")
    if not fil:
        st.info("No invoices match that filter/search.")
        return

    lbsku = _lookup_by_sku()
    rows = []
    for inv in fil:
        om = _order_margin(inv.get("order_items"), lbsku)
        base = {"Invoice": inv.get("invoice_no") or "", "Order": inv.get("order_no") or "",
                "Supplier": inv.get("supplier") or "", "Invoice £": inv.get("total"),
                "Margin %": (round(om["margin"]) if om else None)}
        if checkable:
            rows.append({"Check": False, **base, "PDF": "yes" if inv.get("asset_id") else "—"})
        else:
            rows.append({**base, "Date": inv.get("date") or ""})
    df = pd.DataFrame(rows)
    colcfg = {
        "Invoice £": st.column_config.NumberColumn(format="£%.2f"),
        "Margin %": st.column_config.NumberColumn(
            format="%d%%", help="Estimated from cheapest cost; exact margin shows when checked"),
    }
    if checkable:
        colcfg["Check"] = st.column_config.CheckboxColumn("✓", help="Tick the invoices to check")
        edited = st.data_editor(df, hide_index=True, use_container_width=True, key=f"tbl_{key}",
                                column_config=colcfg,
                                disabled=[c for c in df.columns if c != "Check"])
        picked = [idx for idx, v in enumerate(list(edited["Check"])) if v]
        if st.button(f"Check {len(picked)} selected invoice(s)", type="primary",
                     disabled=(len(picked) == 0), key=f"go_{key}"):
            for idx in picked:
                inv = fil[idx]
                with st.expander(f"{inv.get('invoice_no')} — {inv.get('supplier') or ''} · "
                                 f"order {inv.get('order_no') or '?'}", expanded=True):
                    _run_one_invoice(inv, lbsku)
    else:
        st.dataframe(df, hide_index=True, use_container_width=True, column_config=colcfg)


def render_invoice_check():
    st.markdown(
        """<div class="ts-brandbar"><span class="wm">Trade<b>Hub</b>
        <span class="sec">Invoice Check</span></span></div>""",
        unsafe_allow_html=True,
    )
    st.caption("Check supplier invoices from Monday: prices vs the supplier's pricelist, SKUs & "
               "quantities vs the Shopify order, and the margin you make. Uses your Anthropic key "
               "— a few pence per invoice, cached. Read-only for now.")

    counts = {}
    for k in ("review", "approved", "discrepancy"):
        d = invoices_by_status(k)
        counts[k] = (None if d.get("error") else len(d.get("invoices", [])), d.get("more"))

    def _c(k):
        n, more = counts[k]
        return "—" if n is None else f"{n}{'+' if more else ''}"

    st.markdown(
        '<div style="display:flex;gap:20px;margin:2px 0 10px;font-size:14px">'
        f'<span>🔎 <b>{_c("review")}</b> to check</span>'
        f'<span>✅ <b>{_c("approved")}</b> approved</span>'
        f'<span>⚠️ <b>{_c("discrepancy")}</b> discrepancies</span></div>',
        unsafe_allow_html=True)

    t1, t2, t3 = st.tabs(["🔎 To check", "✅ Matched & approved", "⚠️ Discrepancies"])
    with t1:
        _invoice_tab("review", checkable=True)
    with t2:
        _invoice_tab("approved", checkable=False)
    with t3:
        _invoice_tab("discrepancy", checkable=False)


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

    # --- Menu ---
    if "module" not in st.session_state:
        st.session_state.module = "Daily Ops"
    for _m in ("Daily Ops", "Daily Activity", "Pricing", "Invoice Check"):
        if st.button(_m, key=f"nav_{_m}", use_container_width=True,
                     type=("primary" if st.session_state.module == _m else "secondary")):
            st.session_state.module = _m
            st.rerun()
    module = st.session_state.module

    st.write("")

    # --- Data & connections (one collapsible) ---
    with st.expander("Data & connections"):
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
if module == "Pricing":
    render_pricing()
    st.stop()

if module == "Daily Activity":
    render_daily_activity()
    st.stop()

if module == "Invoice Check":
    render_invoice_check()
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
