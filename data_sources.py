"""
Live data — pulls current KPI numbers from the Monday.com "Daily KPI Tracker"
board (id 18416416116) and overlays them onto the policy in kpis.json.

How it works
------------
kpis.json holds each KPI's *policy* (display category, thresholds, mood flag,
owners, action text) plus a `monday_item_id`. This module fetches the live
`Count` and `Oldest age (days)` columns for those items and returns the merged
list. If no Monday token is configured, the caller falls back to the saved
numbers in kpis.json so the dashboard still works offline.

Setup (once)
------------
1. In Monday: avatar → Developers → My Access Tokens → copy your personal token.
2. On Streamlit Cloud: app → Settings → Secrets, add:
       MONDAY_API_TOKEN = "your_token_here"
   Locally you can instead set an environment variable of the same name, or
   create  .streamlit/secrets.toml  with that line (already in .gitignore).
"""

from __future__ import annotations

import os

import requests

MONDAY_API = "https://api.monday.com/v2"
KPI_BOARD_ID = 18416416116

# Column ids on the Daily KPI Tracker board (from get_board_info)
COL_COUNT = "numeric_mm40pm9s"      # Count
COL_AGE = "numeric_mm40r6d2"        # Oldest age (days)


def _secrets_file_exists() -> bool:
    """True if a Streamlit secrets.toml is present in a standard location.
    Checked first so we never trigger Streamlit's noisy 'No secrets found'
    error just by probing st.secrets when the app runs without one."""
    from pathlib import Path

    candidates = [
        Path.cwd() / ".streamlit" / "secrets.toml",
        Path(__file__).parent / ".streamlit" / "secrets.toml",
        Path.home() / ".streamlit" / "secrets.toml",
    ]
    return any(p.exists() for p in candidates)


def get_secret(name: str) -> str | None:
    """Read a secret from the environment first, then Streamlit secrets (only if
    a secrets file exists, so we never trigger the 'No secrets found' error).
    Returns None if unset."""
    env = os.environ.get(name)
    if env:
        return env
    if _secrets_file_exists():
        try:
            import streamlit as st  # lazy so this module is testable standalone

            return st.secrets.get(name)
        except Exception:  # noqa: BLE001
            return None
    return None


def get_token() -> str | None:
    """Monday API token (MONDAY_API_TOKEN). None if unset."""
    return get_secret("MONDAY_API_TOKEN")


def _to_number(raw: str | None):
    if raw in (None, ""):
        return None
    try:
        return float(raw) if "." in str(raw) else int(raw)
    except (TypeError, ValueError):
        return None


def fetch_live_counts(board_id: int = KPI_BOARD_ID, token: str | None = None) -> dict:
    """Return {monday_item_id: {'count': int, 'age': int|None}} for the board.

    Raises requests.HTTPError / RuntimeError on failure so the caller can fall
    back to the saved snapshot.
    """
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")

    query = """
    query ($board: [ID!]) {
      boards (ids: $board) {
        items_page (limit: 100) {
          items {
            id
            column_values (ids: ["%s", "%s"]) { id text }
          }
        }
      }
    }
    """ % (COL_COUNT, COL_AGE)

    resp = requests.post(
        MONDAY_API,
        json={"query": query, "variables": {"board": [str(board_id)]}},
        headers={"Authorization": token, "API-Version": "2024-10"},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")

    boards = payload.get("data", {}).get("boards", [])
    if not boards:
        raise RuntimeError("Board not found or token lacks access")

    out: dict[int, dict] = {}
    for item in boards[0]["items_page"]["items"]:
        cols = {c["id"]: c["text"] for c in item["column_values"]}
        out[int(item["id"])] = {
            "count": _to_number(cols.get(COL_COUNT)),
            "age": _to_number(cols.get(COL_AGE)),
        }
    return out


def merge_live(kpis: list[dict], live: dict) -> list[dict]:
    """Overlay live count / age onto the policy list (matched by monday_item_id)."""
    for k in kpis:
        row = live.get(k.get("monday_item_id"))
        if not row:
            continue
        if row.get("count") is not None:
            k["count"] = int(row["count"])
        if row.get("age") is not None:
            k["oldest_age_days"] = int(row["age"])
    return kpis


# ---------------------------------------------------------------------------
# Shopify — active chargebacks (Shopify Payments disputes), read directly.
# Needs a Shopify Admin API token with the `read_shopify_payments_accounts`
# scope in Secrets as SHOPIFY_ADMIN_TOKEN. Store domain defaults below but can
# be overridden with SHOPIFY_STORE_DOMAIN.
# ---------------------------------------------------------------------------
SHOPIFY_DOMAIN_DEFAULT = "trade-superstore.myshopify.com"
SHOPIFY_API_VERSION = "2024-10"
# A chargeback is "active" while it still needs us to act / is being reviewed.
ACTIVE_DISPUTE_STATUSES = {"NEEDS_RESPONSE", "UNDER_REVIEW"}


def _age_days(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:  # noqa: BLE001
        return None


def fetch_shopify_chargebacks(token: str | None = None, domain: str | None = None) -> dict:
    """Return {'count': int, 'age': int} for active Shopify Payments disputes.
    Raises on missing token / no payments account / API error so the caller can
    fall back to the Monday-mirrored number."""
    token = token or get_secret("SHOPIFY_ADMIN_TOKEN")
    if not token:
        raise RuntimeError("No SHOPIFY_ADMIN_TOKEN configured")
    domain = domain or get_secret("SHOPIFY_STORE_DOMAIN") or SHOPIFY_DOMAIN_DEFAULT

    url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    query = """
    query {
      shopifyPaymentsAccount {
        disputes(first: 100) {
          edges { node { status initiatedAt } }
        }
      }
    }
    """
    resp = requests.post(
        url,
        json={"query": query},
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify API error: {payload['errors']}")

    account = (payload.get("data") or {}).get("shopifyPaymentsAccount")
    if not account:
        raise RuntimeError("Shopify Payments not enabled or disputes not accessible")

    nodes = [e["node"] for e in account["disputes"]["edges"]]
    active = [n for n in nodes if n.get("status") in ACTIVE_DISPUTE_STATUSES]
    ages = [a for a in (_age_days(n.get("initiatedAt")) for n in active) if a is not None]
    return {"count": len(active), "age": max(ages) if ages else 0}


# ---------------------------------------------------------------------------
# Shopify live product price (read_products) — used by the Pricing module's
# product search to show the *current* sell price per SKU. Auth via the pricing
# app's client-credentials grant: SHOPIFY_STORE / SHOPIFY_CLIENT_ID /
# SHOPIFY_CLIENT_SECRET in Secrets.
# ---------------------------------------------------------------------------
_SHOP_TOK = {"token": None}


def shopify_configured() -> bool:
    return all(get_secret(s) for s in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"))


def shopify_products_token() -> str:
    if _SHOP_TOK["token"]:
        return _SHOP_TOK["token"]
    store = get_secret("SHOPIFY_STORE")
    cid = get_secret("SHOPIFY_CLIENT_ID")
    csec = get_secret("SHOPIFY_CLIENT_SECRET")
    if not (store and cid and csec):
        raise RuntimeError("Shopify products auth not configured")
    r = requests.post(
        f"https://{store}/admin/oauth/access_token",
        data={"grant_type": "client_credentials", "client_id": cid, "client_secret": csec},
        timeout=20,
    )
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError("Shopify client-credentials returned no access_token")
    _SHOP_TOK["token"] = tok
    return tok


def shopify_variant_price(sku: str) -> dict | None:
    """Live current Shopify price for a SKU (tries the bare SKU and a leading
    'TSO' prefix). Returns {price, vendor, url} if sold, or None if not on
    Shopify. Raises RuntimeError if Shopify isn't configured / errors."""
    store = get_secret("SHOPIFY_STORE")
    token = shopify_products_token()
    forms = [sku, f"TSO{sku}"]
    qstr = " OR ".join(f"sku:{s}" for s in forms)
    query = ("query ($q: String!) { productVariants(first: 10, query: $q) "
             "{ edges { node { sku price product { vendor onlineStoreUrl } } } } }")
    r = requests.post(
        f"https://{store}/admin/api/2024-10/graphql.json",
        json={"query": query, "variables": {"q": qstr}},
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify error: {payload['errors']}")
    edges = payload.get("data", {}).get("productVariants", {}).get("edges", [])
    nodes = {(e["node"].get("sku") or ""): e["node"] for e in edges}
    for want in forms:                      # prefer exact, then TSO-prefixed
        n = nodes.get(want)
        if n and n.get("price") is not None:
            prod = n.get("product") or {}
            return {"price": float(n["price"]), "vendor": prod.get("vendor"),
                    "url": prod.get("onlineStoreUrl")}
    return None


# ---------------------------------------------------------------------------
# Live counts straight from the real Orders board (id 1786542990), counting
# items per stage group. This is genuinely live (unlike the summary "Daily KPI
# Tracker" board, which only refreshes when its script runs).
# ---------------------------------------------------------------------------
ORDERS_BOARD_ID = 1786542990


def fetch_orders_group_counts(group_map: dict, token: str | None = None,
                              board_id: int = ORDERS_BOARD_ID) -> dict:
    """group_map = {kpi_id: orders_group_id}. Returns {kpi_id: {count, age}}
    where count is the live number of items in that stage group and age is the
    oldest item's age in days. Raises on token/API failure (caller falls back)."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")

    group_ids = sorted(set(group_map.values()))
    headers = {"Authorization": token, "API-Version": "2024-10"}
    query = """
    query ($board: [ID!], $groups: [String!]) {
      boards(ids: $board) {
        groups(ids: $groups) {
          id
          items_page(limit: 500) { cursor items { created_at } }
        }
      }
    }
    """
    resp = requests.post(
        MONDAY_API,
        json={"query": query, "variables": {"board": [str(board_id)], "groups": group_ids}},
        headers=headers, timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    boards = payload.get("data", {}).get("boards", [])
    if not boards:
        raise RuntimeError("Orders board not found or not accessible")

    by_group: dict[str, dict] = {}
    for g in boards[0]["groups"]:
        items = list(g["items_page"]["items"])
        cursor = g["items_page"]["cursor"]
        while cursor:  # paginate groups larger than 500 (rare for action stages)
            nq = "query ($c: String!) { next_items_page(cursor: $c, limit: 500) { cursor items { created_at } } }"
            r2 = requests.post(MONDAY_API, json={"query": nq, "variables": {"c": cursor}},
                               headers=headers, timeout=30)
            r2.raise_for_status()
            page = r2.json()["data"]["next_items_page"]
            items += page["items"]
            cursor = page["cursor"]
        ages = [a for a in (_age_days(i.get("created_at")) for i in items) if a is not None]
        by_group[g["id"]] = {"count": len(items), "age": max(ages) if ages else 0}

    return {kpi_id: by_group[gid] for kpi_id, gid in group_map.items() if gid in by_group}


def _monday_headers(token: str | None):
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    return {"Authorization": token, "API-Version": "2024-10"}


def fetch_filtered_count(board_id: int, column_id: str, compare_values: list,
                         token: str | None = None) -> dict:
    """Count items on a board where a status column matches compare_values
    (any_of). Paginates. Returns {count, age}. Works for main-board items and
    subitem boards alike (e.g. invoices/discrepancies on the subitems board)."""
    headers = _monday_headers(token)
    cv = "[" + ",".join(str(int(v)) for v in compare_values) + "]"
    items: list = []
    cursor = None
    first = True
    while first or cursor:
        if cursor:
            q = "query ($c: String!) { next_items_page(cursor: $c, limit: 500) { cursor items { created_at } } }"
            body = {"query": q, "variables": {"c": cursor}}
        else:
            q = ('query { boards(ids: [%d]) { items_page(limit: 500, query_params: '
                 '{rules: [{column_id: "%s", compare_value: %s, operator: any_of}]}) '
                 '{ cursor items { created_at } } } }' % (int(board_id), column_id, cv))
            body = {"query": q, "variables": {}}
        resp = requests.post(MONDAY_API, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        d = resp.json()
        if "errors" in d:
            raise RuntimeError(f"Monday API error: {d['errors']}")
        page = d["data"]["next_items_page"] if cursor else d["data"]["boards"][0]["items_page"]
        items += page["items"]
        cursor = page["cursor"]
        first = False
    ages = [a for a in (_age_days(i.get("created_at")) for i in items) if a is not None]
    return {"count": len(items), "age": max(ages) if ages else 0}


def fetch_booked_split(board_id: int, group_id: str, date_col: str, today,
                       token: str | None = None) -> dict:
    """Split a booked group by a customer-ETA date column into overdue (ETA in
    the past) and future (today or later / no date). Returns
    {overdue: {count, age}, future: {count, age}}."""
    from datetime import date as _date

    headers = _monday_headers(token)
    items: list = []
    cursor = None
    first = True
    while first or cursor:
        if cursor:
            q = ('query ($c: String!) { next_items_page(cursor: $c, limit: 500) '
                 '{ cursor items { column_values(ids: ["%s"]) { text } } } }' % date_col)
            body = {"query": q, "variables": {"c": cursor}}
        else:
            q = ('query { boards(ids: [%d]) { groups(ids: ["%s"]) { items_page(limit: 500) '
                 '{ cursor items { column_values(ids: ["%s"]) { text } } } } } }'
                 % (int(board_id), group_id, date_col))
            body = {"query": q, "variables": {}}
        resp = requests.post(MONDAY_API, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        d = resp.json()
        if "errors" in d:
            raise RuntimeError(f"Monday API error: {d['errors']}")
        page = d["data"]["next_items_page"] if cursor else d["data"]["boards"][0]["groups"][0]["items_page"]
        items += page["items"]
        cursor = page["cursor"]
        first = False

    overdue = future = 0
    overdue_ages: list = []
    for it in items:
        cvs = it.get("column_values") or []
        txt = (cvs[0].get("text") if cvs else "") or ""
        try:
            eta = _date.fromisoformat(txt[:10]) if txt else None
        except ValueError:
            eta = None
        if eta and eta < today:
            overdue += 1
            overdue_ages.append((today - eta).days)
        else:
            future += 1  # today, future, or no ETA set
    return {"overdue": {"count": overdue, "age": max(overdue_ages) if overdue_ages else 0},
            "future": {"count": future, "age": 0}}


# ---------------------------------------------------------------------------
# Microsoft 365 / Outlook — count items in a mail folder (read + unread) via
# Microsoft Graph, app-only client credentials. Needs MS_TENANT_ID /
# MS_CLIENT_ID / MS_CLIENT_SECRET in Secrets, with Mail.Read (admin-consented).
# ---------------------------------------------------------------------------
GRAPH = "https://graph.microsoft.com/v1.0"


def ms_token() -> str:
    tenant = get_secret("MS_TENANT_ID")
    client = get_secret("MS_CLIENT_ID")
    secret = get_secret("MS_CLIENT_SECRET")
    if not (tenant and client and secret):
        raise RuntimeError("Microsoft 365 not configured (MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET)")
    r = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={"grant_type": "client_credentials", "client_id": client,
              "client_secret": secret, "scope": "https://graph.microsoft.com/.default"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _graph_children(mailbox: str, folder_id: str | None, token: str) -> list:
    url = (f"{GRAPH}/users/{mailbox}/mailFolders/{folder_id}/childFolders" if folder_id
           else f"{GRAPH}/users/{mailbox}/mailFolders")
    params = {"$top": "100", "$select": "id,displayName,childFolderCount,totalItemCount,unreadItemCount"}
    out: list = []
    while url:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
        r.raise_for_status()
        j = r.json()
        out += j.get("value", [])
        url = j.get("@odata.nextLink")
        params = None
    return out


def _norm(s: str) -> str:
    """Lowercase, keep only letters/digits — so 'Megan - After Sales' and
    'Aftersales' match regardless of spaces, dashes or punctuation."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def fetch_outlook_folder_count(mailbox: str, folder_name: str, token: str | None = None) -> dict:
    """Recursively search a mailbox's folders for one whose (normalised) name
    matches folder_name (exact preferred, else contains) and return its total
    item count (read + unread) plus unread. Raises if not found / not configured."""
    token = token or ms_token()
    target = _norm(folder_name)
    queue = _graph_children(mailbox, None, token)
    contains_match = None
    visited = 0
    while queue and visited < 800:
        visited += 1
        f = queue.pop(0)
        nm = _norm(f.get("displayName"))
        if nm == target:
            return {"count": f.get("totalItemCount", 0), "unread": f.get("unreadItemCount", 0)}
        if contains_match is None and target and target in nm:
            contains_match = f
        if f.get("childFolderCount", 0) > 0:
            queue += _graph_children(mailbox, f["id"], token)
    if contains_match:
        return {"count": contains_match.get("totalItemCount", 0),
                "unread": contains_match.get("unreadItemCount", 0)}
    raise RuntimeError(f"Folder matching '{folder_name}' not found in {mailbox}")


# ---------------------------------------------------------------------------
# Customer mood from real email sentiment (Outlook content + Anthropic AI).
# Reads the subject + first line of outstanding emails in the customer folders
# and asks a fast model to judge the overall mood and the top themes.
# ---------------------------------------------------------------------------
def _find_folder(mailbox: str, folder_name: str, token: str):
    """Return the folder object (with id) matching folder_name, or None."""
    target = _norm(folder_name)
    queue = _graph_children(mailbox, None, token)
    contains = None
    visited = 0
    while queue and visited < 800:
        visited += 1
        f = queue.pop(0)
        nm = _norm(f.get("displayName"))
        if nm == target:
            return f
        if contains is None and target and target in nm:
            contains = f
        if f.get("childFolderCount", 0) > 0:
            queue += _graph_children(mailbox, f["id"], token)
    return contains


def fetch_folder_messages(mailbox: str, folder_name: str, limit: int = 12,
                          token: str | None = None) -> list:
    """Most-recent messages in a folder as [{subject, preview}]. [] if not found."""
    token = token or ms_token()
    f = _find_folder(mailbox, folder_name, token)
    if not f:
        return []
    r = requests.get(
        f"{GRAPH}/users/{mailbox}/mailFolders/{f['id']}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"$top": str(limit), "$select": "subject,bodyPreview,receivedDateTime",
                "$orderby": "receivedDateTime desc"},
        timeout=25,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("value", []):
        out.append({"subject": (m.get("subject") or "").strip(),
                    "preview": (m.get("bodyPreview") or "").strip()[:280]})
    return out


ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
SENTIMENT_MODEL = "claude-haiku-4-5-20251001"


def analyze_customer_mood(emails: list) -> dict:
    """Judge overall customer mood + top themes from outstanding emails.
    Returns {mood, score, summary, themes:[{theme,count}]}. Raises if the
    ANTHROPIC_API_KEY isn't set or the call fails."""
    import json as _json
    import re

    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")
    if not emails:
        raise RuntimeError("No emails to analyse")

    block = "\n".join(
        f"{i}. SUBJECT: {e['subject']}\n   PREVIEW: {e['preview']}"
        for i, e in enumerate(emails[:60], 1))
    prompt = (
        "You are reading the outstanding customer-support emails (subject + first line) of a UK "
        "building-supplies retailer. Judge the OVERALL customer mood from the tone of what they wrote "
        "and what they are asking for. Reply with ONLY a JSON object, no other text:\n"
        '{"mood":"Happy|Calm|Mixed|Tense|Stressed","score":<0-100>,'
        '"summary":"one short sentence on how customers feel right now",'
        '"themes":[{"theme":"short phrase","count":<int>}]}\n'
        "score = how frustrated/stressed customers are (0 = happy/calm, 100 = very angry). "
        "themes = the top 3-5 things customers want or are frustrated about, each with how many emails relate to it.\n\n"
        f"EMAILS ({len(emails)} shown):\n{block}"
    )
    r = requests.post(
        ANTHROPIC_API,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": SENTIMENT_MODEL, "max_tokens": 700,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=45,
    )
    r.raise_for_status()
    txt = r.json()["content"][0]["text"].strip()
    match = re.search(r"\{.*\}", txt, re.S)
    if not match:
        raise RuntimeError("AI returned no JSON")
    return _json.loads(match.group(0))
