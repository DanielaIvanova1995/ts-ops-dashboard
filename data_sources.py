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


def fetch_outlook_folder_count(mailbox: str, folder_name: str, token: str | None = None) -> dict:
    """Recursively search a mailbox's folders for one whose name matches
    folder_name (exact preferred, else contains) and return its total item
    count (read + unread) plus unread. Raises if not found / not configured."""
    token = token or ms_token()
    target = folder_name.strip().lower()
    queue = _graph_children(mailbox, None, token)
    contains_match = None
    visited = 0
    while queue and visited < 800:
        visited += 1
        f = queue.pop(0)
        nm = (f.get("displayName") or "").strip().lower()
        if nm == target:
            return {"count": f.get("totalItemCount", 0), "unread": f.get("unreadItemCount", 0)}
        if contains_match is None and target in nm:
            contains_match = f
        if f.get("childFolderCount", 0) > 0:
            queue += _graph_children(mailbox, f["id"], token)
    if contains_match:
        return {"count": contains_match.get("totalItemCount", 0),
                "unread": contains_match.get("unreadItemCount", 0)}
    raise RuntimeError(f"Folder matching '{folder_name}' not found in {mailbox}")
