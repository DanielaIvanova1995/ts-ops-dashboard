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
from zoneinfo import ZoneInfo

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
with st.sidebar:
    if _logo:
        st.markdown(
            f"<img src='{_logo}' style='width:100%;display:block;margin:2px 0 14px'>",
            unsafe_allow_html=True,
        )

    # --- Menu ---
    if "module" not in st.session_state:
        st.session_state.module = "Daily Ops"
    for _m in ("Daily Ops", "Pricing"):
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

    # --- Settings (one collapsible) ---
    with st.expander("Settings"):
        st.caption(f"Signed in as {name} · {role}")
        st.markdown("**Change password**")
        try:
            if authenticator.reset_password(username, location="sidebar"):
                with open(BASE / "config.yaml", "w") as f:
                    yaml.dump(config, f, default_flow_style=False)
                st.success("Password changed ✅")
        except Exception as e:  # noqa: BLE001
            st.warning(str(e))

    st.divider()
    authenticator.logout("Sign out", location="sidebar")

# ---------------------------------------------------------------------------
# Module dispatch — Pricing renders here and stops before the Daily Ops view.
# ---------------------------------------------------------------------------
if module == "Pricing":
    render_pricing()
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
m = mood(KPIS)
load = workload(KPIS)  # workload bars — everyone (incl. Malyeka), excl. managers
ranked = sorted(load.items(), key=lambda x: x[1], reverse=True)
pair_ranked = sorted(workload(KPIS, pairing=True).items(), key=lambda x: x[1], reverse=True)
users_cfg = config["credentials"]["usernames"]

_glance = st.expander("📊  Today at a glance", expanded=True)
c1, c2, c3 = _glance.columns([1.15, 1, 1])

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
