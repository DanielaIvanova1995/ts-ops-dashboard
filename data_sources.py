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
    store = get_secret("SHOPIFY_STORE")
    has_static = bool(get_secret("SHOPIFY_ADMIN_TOKEN"))
    has_oauth = bool(get_secret("SHOPIFY_CLIENT_ID") and get_secret("SHOPIFY_CLIENT_SECRET"))
    return bool(store and (has_static or has_oauth))


def shopify_products_token() -> str:
    if _SHOP_TOK["token"]:
        return _SHOP_TOK["token"]
    # Prefer a static Admin API token (e.g. the app's automation token) if provided —
    # it carries the app's granted scopes directly, sidestepping client-credentials.
    static = get_secret("SHOPIFY_ADMIN_TOKEN")
    if static:
        _SHOP_TOK["token"] = static
        return static
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


def shopify_token_scopes() -> dict:
    """Which app the CURRENT token belongs to + the scopes it actually carries — the
    definitive check of what the live app can do. Raises on auth failure."""
    store = get_secret("SHOPIFY_STORE")
    token = shopify_products_token()
    q = "{ currentAppInstallation { app { title } accessScopes { handle } } }"
    r = requests.post(
        f"https://{store}/admin/api/2024-10/graphql.json",
        json={"query": q},
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"]))
    inst = (payload.get("data") or {}).get("currentAppInstallation") or {}
    return {"app": (inst.get("app") or {}).get("title"),
            "scopes": [s["handle"] for s in (inst.get("accessScopes") or [])]}


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


def fetch_order_discounts(order_ids, token: str | None = None) -> dict:
    """{shopify_order_id(str): {amount, codes}} — customer discounts applied on each
    Shopify order. Batched. Raises if Shopify orders aren't readable (caller falls back)."""
    store = get_secret("SHOPIFY_STORE")
    token = token or shopify_products_token()
    gids = [f"gid://shopify/Order/{str(i).strip()}" for i in order_ids if i]
    out = {}
    query = ("query ($ids: [ID!]!) { nodes(ids: $ids) { ... on Order { id "
             "totalDiscountsSet { shopMoney { amount } } discountCodes } } }")
    for k in range(0, len(gids), 50):
        r = requests.post(
            f"https://{store}/admin/api/2024-10/graphql.json",
            json={"query": query, "variables": {"ids": gids[k:k + 50]}},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=25,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise RuntimeError(f"Shopify error: {payload['errors']}")
        for n in payload.get("data", {}).get("nodes", []) or []:
            if not n or not n.get("id"):
                continue
            money = (n.get("totalDiscountsSet") or {}).get("shopMoney") or {}
            out[n["id"].split("/")[-1]] = {"amount": float(money.get("amount") or 0),
                                           "codes": n.get("discountCodes") or []}
    return out


def shopify_variant_barcode(sku: str) -> str | None:
    """The product's barcode/EAN on Shopify (tries bare SKU then 'TSO' prefix),
    used to match the exact product at competitors. None if not found."""
    store = get_secret("SHOPIFY_STORE")
    token = shopify_products_token()
    forms = [sku, f"TSO{sku}"]
    qstr = " OR ".join(f"sku:{s}" for s in forms)
    query = ("query ($q: String!) { productVariants(first: 10, query: $q) "
             "{ edges { node { sku barcode } } } }")
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
    for want in forms:
        n = nodes.get(want)
        if n and n.get("barcode"):
            return n["barcode"].strip()
    for e in edges:                          # fallback: any barcode in the match set
        bc = e["node"].get("barcode")
        if bc:
            return bc.strip()
    return None


# ---------------------------------------------------------------------------
# Live counts straight from the real Orders board (id 1786542990), counting
# items per stage group. This is genuinely live (unlike the summary "Daily KPI
# Tracker" board, which only refreshes when its script runs).
# ---------------------------------------------------------------------------
ORDERS_BOARD_ID = 1786542990


def fetch_board_activity(board_id: int, from_iso: str, to_iso: str,
                         token: str | None = None, page_limit: int = 500,
                         max_pages: int = 20) -> list:
    """Raw Monday activity_logs for a board within [from_iso, to_iso]. Returns a
    list of {event, user_id, data} (data is a JSON string). Paginates until a
    short page. Raises on token/API failure (caller falls back)."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    headers = {"Authorization": token, "API-Version": "2024-10"}
    query = """
    query ($b: [ID!], $f: ISO8601DateTime, $t: ISO8601DateTime, $p: Int, $l: Int) {
      boards(ids: $b) {
        activity_logs(from: $f, to: $t, page: $p, limit: $l) { event user_id data }
      }
    }
    """
    out: list = []
    for page in range(1, max_pages + 1):
        r = requests.post(
            MONDAY_API,
            json={"query": query, "variables": {"b": [str(board_id)], "f": from_iso,
                                                "t": to_iso, "p": page, "l": page_limit}},
            headers=headers, timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            raise RuntimeError(f"Monday API error: {payload['errors']}")
        boards = payload.get("data", {}).get("boards", [])
        logs = boards[0].get("activity_logs", []) if boards else []
        out += logs
        if len(logs) < page_limit:
            break
    return out


def fetch_group_names(board_id: int, token: str | None = None) -> dict:
    """{group_id: title} for a board's groups. {} on failure."""
    token = token or get_token()
    if not token:
        return {}
    try:
        r = requests.post(
            MONDAY_API,
            json={"query": "query($b:[ID!]){boards(ids:$b){groups{id title}}}",
                  "variables": {"b": [str(board_id)]}},
            headers={"Authorization": token, "API-Version": "2024-10"}, timeout=20,
        )
        r.raise_for_status()
        boards = r.json().get("data", {}).get("boards", [])
        return {g["id"]: g["title"] for g in (boards[0]["groups"] if boards else [])}
    except Exception:  # noqa: BLE001
        return {}


def fetch_user_names(ids: list, token: str | None = None) -> dict:
    """{user_id(str): name} for the given Monday user ids. {} on failure."""
    ids = [str(i) for i in ids if str(i).isdigit()]
    if not ids:
        return {}
    token = token or get_token()
    if not token:
        return {}
    try:
        r = requests.post(
            MONDAY_API,
            json={"query": "query($ids:[ID!]){users(ids:$ids){id name}}",
                  "variables": {"ids": ids}},
            headers={"Authorization": token, "API-Version": "2024-10"}, timeout=20,
        )
        r.raise_for_status()
        users = r.json().get("data", {}).get("users", []) or []
        return {str(u["id"]): u["name"] for u in users}
    except Exception:  # noqa: BLE001
        return {}


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


def fetch_all_folder_counts(mailbox: str, token: str | None = None) -> dict:
    """Walk the mailbox's folder tree ONCE and return {normalised_name: {count,
    unread, name}} for every folder. Use this instead of calling
    fetch_outlook_folder_count once per folder (one walk, not N)."""
    token = token or ms_token()
    out: dict = {}
    queue = _graph_children(mailbox, None, token)
    visited = 0
    while queue and visited < 1500:
        visited += 1
        f = queue.pop(0)
        nm = _norm(f.get("displayName"))
        if nm and nm not in out:
            out[nm] = {"count": f.get("totalItemCount", 0),
                       "unread": f.get("unreadItemCount", 0), "name": f.get("displayName")}
        if f.get("childFolderCount", 0) > 0:
            queue += _graph_children(mailbox, f["id"], token)
    return out


def match_folder(folder_map: dict, folder_name: str):
    """Resolve a folder by name from a fetch_all_folder_counts map (exact, else
    contains). Returns the folder dict or None."""
    t = _norm(folder_name)
    if t in folder_map:
        return folder_map[t]
    for nm, v in folder_map.items():
        if t and t in nm:
            return v
    return None


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
COMPETITOR_MODEL = "claude-sonnet-4-6"  # stronger model for live web-search research


def research_competitors(title: str, code: str | None, vendor: str | None,
                         your_price) -> dict:
    """Use Claude with live web search to find current UK competitor prices for a
    product. Returns {competitors:[{retailer,price,url,in_stock}], cheapest,
    summary, your_price}. Raises if ANTHROPIC_API_KEY isn't set or the call fails."""
    import json as _json
    import re

    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")

    ident = f'"{title}"'
    if vendor:
        ident += f" by {vendor}"
    if code:
        ident += f" (product code / SKU {code})"
    prompt = (
        "You are a pricing analyst for a UK building-supplies retailer (Trade Superstore "
        f"Online). Find the current price of this exact product at COMPETING UK online "
        f"retailers (not Trade Superstore itself): {ident}.\n"
        "Search the web by the product code / SKU and product name, open real product listings, "
        "and read the actual price shown. Match the SAME product — prefer an exact match on the "
        "manufacturer product code / SKU.\n"
        "IMPORTANT — report every price EXCLUDING VAT (ex-VAT), in GBP. UK consumer/retail sites "
        "usually display prices INCLUDING 20% VAT: convert those to ex-VAT by dividing by 1.2. "
        "Trade/merchant sites often already show ex-VAT prices — use those as-is. Reply with "
        "ONLY a JSON object, no other text:\n"
        '{"competitors":[{"retailer":"shop name","price":<number, GBP EX-VAT>,'
        '"listed_inc_vat":true|false,"url":"listing url","in_stock":true|false}],'
        '"cheapest":{"retailer":"name","price":<number ex-VAT>},'
        '"summary":"one sentence on where this product sits in the market"}\n'
        "price MUST be the ex-VAT figure. listed_inc_vat = whether the site originally showed the "
        "price inc VAT (so you converted it). Include up to 6 genuine listings you actually found "
        "and read. If you cannot find the exact product, return an empty competitors list and "
        "explain in summary. Never invent prices or retailers."
    )
    body = {
        "model": COMPETITOR_MODEL,
        "max_tokens": 1800,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        ANTHROPIC_API,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json=body, timeout=120,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    match = re.search(r"\{.*\}", txt, re.S)
    if not match:
        raise RuntimeError("No result returned from competitor search")
    data = _json.loads(match.group(0))
    data["your_price"] = your_price
    data["code"] = code
    return data


# ---------------------------------------------------------------------------
# Invoice check — pull supplier invoices sitting in "Needs Review" on the Monday
# subitems board, read the PDF with Claude, and match against the order + the
# supplier's pricelist.
# ---------------------------------------------------------------------------
SUBITEMS_BOARD_ID = 3547638043
NEEDS_REVIEW_LABEL_ID = 3            # status7__1 "Needs Review" (Monday label id)
INVOICE_MODEL = "claude-sonnet-4-6"  # reads the PDF (documents need a capable model)


def fetch_invoices_by_status(label_ids, limit: int = 100, token: str | None = None) -> dict:
    """Subitems on the Subitems board whose Payment Status is any of label_ids.
    Returns {invoices:[{sub_id, invoice_no, total, asset_id, file_name, order_no,
    supplier, order_items, order_margin_live, status, date}], more: bool}.
    Raises on token/API failure."""
    import json as _json
    import re
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    store = get_secret("SHOPIFY_STORE")
    headers = {"Authorization": token, "API-Version": "2024-10"}
    vals = ", ".join(str(int(i)) for i in label_ids)
    item_fields = """
            id name
            column_values(ids: ["file_mm38gx3j", "numbers4", "status7__1"]) { id value text }
            parent_item { name
              column_values(ids: ["text_mkv6z0nt", "dropdown_mkyqdeqd", "order_items0",
                "text_mm04tmac", "email", "numbers6", "numbers48", "formula_mkn9918j"]) {
                id text ... on FormulaValue { display_value } } }
    """
    first_q = ("query ($board: [ID!], $limit: Int!) { boards(ids: $board) { "
               'items_page(limit: $limit, query_params: {rules: [{column_id: "status7__1", '
               "compare_value: [%s], operator: any_of}]}) { cursor items { %s } } } }"
               % (vals, item_fields))
    next_q = ("query ($c: String!, $limit: Int!) { next_items_page(cursor: $c, limit: $limit) "
              "{ cursor items { %s } } }" % item_fields)

    def _parse(it):
        cv = {c["id"]: c for c in it.get("column_values", [])}
        asset_id = file_name = None
        fv = cv.get("file_mm38gx3j", {}) or {}
        if fv.get("value"):
            try:
                files = _json.loads(fv["value"]).get("files", [])
                if files:
                    asset_id, file_name = files[0].get("assetId"), files[0].get("name")
            except Exception:  # noqa: BLE001
                pass
        try:
            total = float((cv.get("numbers4", {}) or {}).get("text") or "")
        except Exception:  # noqa: BLE001
            total = None
        date = None
        sv = cv.get("status7__1", {}) or {}
        if sv.get("value"):
            try:
                ca = _json.loads(sv["value"]).get("changed_at")
                date = ca[:10] if ca else None
            except Exception:  # noqa: BLE001
                pass
        parent = it.get("parent_item") or {}
        pcv, margin_live = {}, None
        for c in (parent.get("column_values") or []):
            if c.get("id") == "formula_mkn9918j":
                m = re.search(r"-?\d+(?:\.\d+)?", c.get("display_value") or "")
                margin_live = float(m.group()) if m else None
            else:
                pcv[c["id"]] = c.get("text")
        sid = (pcv.get("text_mm04tmac") or "").strip() or None
        try:
            agreed_cost = float(pcv.get("numbers6"))
        except (TypeError, ValueError):
            agreed_cost = None
        try:
            to_us = float(pcv.get("numbers48"))      # Monday '£ to us' (customer paid)
        except (TypeError, ValueError):
            to_us = None
        return {
            "sub_id": it["id"], "invoice_no": it.get("name"), "total": total,
            "to_us": to_us,
            "asset_id": asset_id, "file_name": file_name,
            "file_url": (cv.get("file_mm38gx3j", {}) or {}).get("text") or None,
            "order_no": pcv.get("text_mkv6z0nt") or parent.get("name"),
            "supplier": pcv.get("dropdown_mkyqdeqd"),
            "order_items": pcv.get("order_items0") or "",
            "order_margin_live": margin_live,
            "agreed_cost": agreed_cost,
            "shopify_order_id": sid,
            "order_url": f"https://{store}/admin/orders/{sid}" if (store and sid) else None,
            "supplier_email": (pcv.get("email") or "").strip() or None,
            "status": sv.get("text"), "date": date,
        }

    out, page_size = [], min(limit, 500)
    r = requests.post(MONDAY_API, json={"query": first_q,
                      "variables": {"board": [str(SUBITEMS_BOARD_ID)], "limit": page_size}},
                      headers=headers, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    boards = payload.get("data", {}).get("boards", [])
    page = boards[0]["items_page"] if boards else {"items": [], "cursor": None}
    out.extend(_parse(it) for it in page.get("items", []))
    cursor, pages = page.get("cursor"), 1
    while cursor and len(out) < limit and pages < 15:    # follow pagination → ALL of them
        r = requests.post(MONDAY_API, json={"query": next_q,
                          "variables": {"c": cursor, "limit": page_size}},
                          headers=headers, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            break
        np = (payload.get("data") or {}).get("next_items_page") or {}
        out.extend(_parse(it) for it in np.get("items", []))
        cursor = np.get("cursor")
        pages += 1
    return {"invoices": out[:limit], "more": bool(cursor)}


def fetch_finance_orders(token: str | None = None, group_keywords=("paid",),
                         page_size: int = 500, max_pages: int = 30) -> dict:
    """Every order in the Orders board's 'Paid & Delivered' group(s), for the Finance
    view. Returns {orders:[{id, order_no, supplier, margin, agreed_cost, order_items,
    shopify_order_id, created, month, has_invoice, group}], groups:[titles used],
    all_groups:{id:title}, more:bool}. margin is the live order margin % (or None).
    Groups are matched by title keyword so we don't hardcode a fragile group id."""
    import re
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    headers = {"Authorization": token, "API-Version": "2024-10"}
    all_groups = fetch_group_names(ORDERS_BOARD_ID, token)
    target_ids = [gid for gid, t in all_groups.items()
                  if any(k in (t or "").lower() for k in group_keywords)]
    if not target_ids:
        return {"orders": [], "groups": [], "all_groups": all_groups, "more": False}

    item_fields = """
        id name created_at group { title }
        subitems { id }
        column_values(ids: ["dropdown_mkyqdeqd", "order_items0", "numbers6",
            "formula_mkn9918j", "text_mkv6z0nt", "text_mm04tmac"]) {
            id text ... on FormulaValue { display_value } }
    """
    first_q = ("query ($board:[ID!], $grp:[String!], $limit:Int!) { boards(ids:$board) { "
               "groups(ids:$grp) { title items_page(limit:$limit) { cursor items { %s } } } } }"
               % item_fields)
    next_q = ("query ($c:String!, $limit:Int!) { next_items_page(cursor:$c, limit:$limit) "
              "{ cursor items { %s } } }" % item_fields)

    def _parse(it):
        pcv, margin = {}, None
        for c in (it.get("column_values") or []):
            if c.get("id") == "formula_mkn9918j":
                m = re.search(r"-?\d+(?:\.\d+)?", c.get("display_value") or "")
                margin = float(m.group()) if m else None
            else:
                pcv[c["id"]] = c.get("text")
        try:
            cost = float(pcv.get("numbers6"))
        except (TypeError, ValueError):
            cost = None
        created = (it.get("created_at") or "")[:10]
        return {
            "id": it["id"], "name": it.get("name"),
            "order_no": (pcv.get("text_mkv6z0nt") or it.get("name") or "").strip(),
            "supplier": (pcv.get("dropdown_mkyqdeqd") or "").strip() or None,
            "margin": margin, "agreed_cost": cost,
            "order_items": pcv.get("order_items0") or "",
            "shopify_order_id": (pcv.get("text_mm04tmac") or "").strip() or None,
            "created": created, "month": created[:7] if created else None,
            "has_invoice": bool(it.get("subitems")),
            "group": (it.get("group") or {}).get("title"),
        }

    orders, used_titles, cursors = [], [], []
    r = requests.post(MONDAY_API, json={"query": first_q, "variables": {
        "board": [str(ORDERS_BOARD_ID)], "grp": target_ids, "limit": page_size}},
        headers=headers, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    boards = (payload.get("data") or {}).get("boards") or []
    for g in (boards[0].get("groups", []) if boards else []):
        used_titles.append(g.get("title"))
        ip = g.get("items_page") or {}
        orders.extend(_parse(it) for it in ip.get("items", []))
        if ip.get("cursor"):
            cursors.append(ip["cursor"])

    pages = 1
    while cursors and pages < max_pages:
        c = cursors.pop(0)
        r = requests.post(MONDAY_API, json={"query": next_q,
                          "variables": {"c": c, "limit": page_size}}, headers=headers, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            break
        np = (payload.get("data") or {}).get("next_items_page") or {}
        orders.extend(_parse(it) for it in np.get("items", []))
        if np.get("cursor"):
            cursors.append(np["cursor"])
        pages += 1
    return {"orders": orders, "groups": used_titles, "all_groups": all_groups,
            "more": bool(cursors)}


def fetch_invoice_count(label_ids, cap: int = 2000, token: str | None = None) -> dict:
    """Fast id-only count of subitems at the given Payment-Status labels (no parent
    data). Returns {count, more}. Much lighter than fetch_invoices_by_status."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    headers = {"Authorization": token, "API-Version": "2024-10"}
    vals = ", ".join(str(int(i)) for i in label_ids)
    first_q = ("query ($board: [ID!], $limit: Int!) { boards(ids: $board) { "
               'items_page(limit: $limit, query_params: {rules: [{column_id: "status7__1", '
               "compare_value: [%s], operator: any_of}]}) { cursor items { id } } } }" % vals)
    next_q = ("query ($c: String!, $limit: Int!) { next_items_page(cursor: $c, limit: $limit) "
              "{ cursor items { id } } }")
    n, page_size = 0, 500
    r = requests.post(MONDAY_API, json={"query": first_q,
                      "variables": {"board": [str(SUBITEMS_BOARD_ID)], "limit": page_size}},
                      headers=headers, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    boards = payload.get("data", {}).get("boards", [])
    page = boards[0]["items_page"] if boards else {"items": [], "cursor": None}
    n += len(page.get("items", []))
    cursor, pages = page.get("cursor"), 1
    while cursor and n < cap and pages < 8:
        r = requests.post(MONDAY_API, json={"query": next_q,
                          "variables": {"c": cursor, "limit": page_size}},
                          headers=headers, timeout=30)
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            break
        np = (payload.get("data") or {}).get("next_items_page") or {}
        n += len(np.get("items", []))
        cursor = np.get("cursor")
        pages += 1
    return {"count": n, "more": bool(cursor)}


def send_supplier_email(mailbox: str, to_email: str, subject: str, body: str,
                        pdf_url: str | None = None, pdf_name: str = "invoice.pdf",
                        token: str | None = None) -> bool:
    """Send an email from `mailbox` to to_email (optionally attaching the PDF at
    pdf_url). Sends immediately and saves to Sent Items. Needs Mail.Send. Raises."""
    import base64
    token = token or ms_token()
    if not (to_email or "").strip():
        raise RuntimeError("No recipient email address.")
    msg = {"subject": subject, "body": {"contentType": "Text", "content": body},
           "toRecipients": [{"emailAddress": {"address": to_email.strip()}}]}
    if pdf_url:
        # Best-effort attachment: if the PDF can't be fetched (expired link, auth),
        # still send the email rather than failing the whole chase.
        try:
            pdf = requests.get(pdf_url, timeout=40)
            pdf.raise_for_status()
            msg["attachments"] = [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": pdf_name, "contentType": "application/pdf",
                "contentBytes": base64.b64encode(pdf.content).decode(),
            }]
        except Exception:  # noqa: BLE001
            pass
    r = requests.post(
        f"{GRAPH}/users/{mailbox}/sendMail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": msg, "saveToSentItems": True}, timeout=45,
    )
    r.raise_for_status()
    return True


def fetch_quote_emails(mailbox: str, folder_name: str, limit: int = 15,
                       token: str | None = None) -> list:
    """Full messages in a folder for quoting: [{id, subject, from, from_name,
    received, preview, body}]. body is plain text (HTML stripped)."""
    import re as _re
    token = token or ms_token()
    f = _find_folder(mailbox, folder_name, token)
    if not f:
        return []
    r = requests.get(
        f"{GRAPH}/users/{mailbox}/mailFolders/{f['id']}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"$top": str(limit), "$orderby": "receivedDateTime desc",
                "$select": "subject,from,receivedDateTime,bodyPreview,body,categories,isRead"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("value", []):
        body = m.get("body") or {}
        content = body.get("content") or m.get("bodyPreview") or ""
        if body.get("contentType") == "html":
            content = _re.sub(r"<[^>]+>", " ", content)
        content = _re.sub(r"\s+", " ", content).strip()
        ea = ((m.get("from") or {}).get("emailAddress") or {})
        out.append({"id": m.get("id"), "subject": m.get("subject") or "(no subject)",
                    "from": ea.get("address"), "from_name": ea.get("name"),
                    "conversationId": m.get("conversationId"),
                    "received": (m.get("receivedDateTime") or "")[:10],
                    "categories": m.get("categories") or [],
                    "isRead": bool(m.get("isRead")),
                    "preview": (m.get("bodyPreview") or "").strip()[:200],
                    "body": content[:6000]})
    return out


def tag_message(mailbox: str, message_id: str, add_categories=None, mark_read=None,
                token: str | None = None) -> list | None:
    """Stamp an Outlook message with categories (merged with existing) and/or mark it
    read — used to record quote progress durably in the mailbox. Needs Mail.ReadWrite.
    Returns the message's categories after the update."""
    token = token or ms_token()
    patch = {}
    if add_categories:
        g = requests.get(f"{GRAPH}/users/{mailbox}/messages/{message_id}",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"$select": "categories"}, timeout=20)
        g.raise_for_status()
        cur = g.json().get("categories") or []
        patch["categories"] = list(dict.fromkeys([*cur, *add_categories]))
    if mark_read is not None:
        patch["isRead"] = bool(mark_read)
    if not patch:
        return None
    r = requests.patch(f"{GRAPH}/users/{mailbox}/messages/{message_id}",
                       headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"},
                       json=patch, timeout=20)
    r.raise_for_status()
    return patch.get("categories")


def fetch_conversation(mailbox: str, conversation_id: str, token: str | None = None,
                       limit: int = 25) -> list:
    """All messages in a conversation thread (across folders), oldest first, as
    [{from, from_name, received, body}] with HTML stripped. For quote context."""
    import re as _re
    if not conversation_id:
        return []
    token = token or ms_token()
    cid = conversation_id.replace("'", "''")
    r = requests.get(
        f"{GRAPH}/users/{mailbox}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"$filter": f"conversationId eq '{cid}'", "$top": str(limit),
                "$select": "subject,from,receivedDateTime,body,bodyPreview"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("value", []):
        body = m.get("body") or {}
        content = body.get("content") or m.get("bodyPreview") or ""
        if body.get("contentType") == "html":
            content = _re.sub(r"<[^>]+>", " ", content)
        content = _re.sub(r"\s+", " ", content).strip()
        ea = ((m.get("from") or {}).get("emailAddress") or {})
        out.append({"from": ea.get("address"), "from_name": ea.get("name"),
                    "received": (m.get("receivedDateTime") or "")[:16].replace("T", " "),
                    "body": content[:3000]})
    out.sort(key=lambda x: x["received"])
    return out


def compose_customer_email(context: str, kind: str, data: dict) -> str:
    """AI writes a polished, customer-facing email body (plain text, ready to review
    and send). kind='quote' presents priced items; kind='clarify' asks for missing
    details. 'context' is the conversation thread so the email stays relevant.
    Raises if no ANTHROPIC_API_KEY (caller falls back to a template)."""
    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")
    name = (data.get("customer_name") or "").strip()
    greet = f"the customer by first name ('{name}')" if name else "the customer with 'Hello'"
    # Standard note for every quote/clarify email: stock + delivery vary by postcode.
    delivery_note = (data.get("delivery_note") or
                     "Please note that stock availability and delivery charges can vary "
                     "depending on the delivery postcode — let us know your postcode and we'll "
                     "confirm both.")
    if kind == "quote":
        facts = ("QUOTED ITEMS (use these EXACT prices and figures, never change a number):\n"
                 + "\n".join(f"- {l['qty']} x {l['title']} @ GBP {l['unit']:.2f} "
                             f"= GBP {l['line']:.2f}" for l in data["lines"])
                 + f"\nTotal (ex-VAT): GBP {data['total']:.2f}")
        if data.get("ref"):
            facts += f"\nQuote reference: {data['ref']}"
        cav = [c for c in (data.get("caveats") or []) if c and str(c).strip()]
        if cav:
            facts += ("\n\nASSUMPTIONS / THINGS FOR THE CUSTOMER TO CHECK (mention these clearly):\n"
                      + "\n".join(f"- {c}" for c in cav))
        facts += "\n\nINCLUDE THIS NOTE (reword naturally): " + delivery_note
        prov = bool(data.get("provisional"))
        task = (
            "Write a warm, professional email presenting this quote. Acknowledge their enquiry "
            "using the conversation for context. "
            "ALWAYS include a short, clearly-labelled explanation of WHAT THE QUOTE IS BASED ON — "
            "the products, the quantities, and any areas or assumptions used to work it out — so "
            "the customer can see how we got there. Present the items and prices as a clear "
            "bulleted list and state the total. Note prices exclude VAT. "
            "Do NOT include or mention any online payment/quote link. "
            "Include the stock/delivery-by-postcode note near the end. "
            "Then ALWAYS ask the customer to check the quote over and confirm everything is "
            "correct, and to let us know if anything needs amending or adding. If any assumptions "
            "or things-to-check are listed, spell them out kindly — and where trims or accessories "
            "were not specified, explicitly ask them to tell us if they need any so we can include "
            "them. "
            + ("Make clear this is based on the information provided so far, that some details may "
               "still need confirming, and that the final figure could change once we have "
               "everything. " if prov else "")
            + "Offer to help with anything else.")
    else:
        facts = ("DETAILS WE STILL NEED BEFORE WE CAN QUOTE:\n"
                 + "\n".join(f"- {q}" for q in (data.get("questions") or [])))
        sugg = [s for s in (data.get("suggestions") or []) if s and str(s).strip()]
        if sugg:
            facts += ("\n\nPRODUCTS FROM OUR RANGE THAT MAY MATCH WHAT THEY DESCRIBED (offer these "
                      "as suggestions to confirm):\n" + "\n".join(f"- {s}" for s in sugg))
        facts += "\n\nINCLUDE THIS NOTE (reword naturally): " + delivery_note
        task = ("Write a warm, professional email asking the customer for the missing details so "
                "we can prepare their quote. Acknowledge their enquiry / our previous messages "
                "using the conversation for context. Ask the questions politely as a short "
                "bulleted list. If suggested products from our range are listed, mention them as "
                "options and ask the customer to confirm which they'd like. Do NOT restate "
                "measurements or information they already gave. Include the stock/delivery-by-"
                "postcode note. Do NOT include any online payment/quote link.")
    prompt = (
        "You write on behalf of Trade Superstore Online, a UK building-supplies retailer. "
        "British English, warm and professional, concise. Address " + greet + ". " + task + "\n"
        "Structure it as a proper email: a greeting line, a short opening sentence, the body "
        "(use '- ' for any bulleted list), a courteous closing line, then the sign-off exactly:\n"
        "Kind regards,\nTrade Superstore Online\n"
        "Return ONLY the email body text - no subject line, no notes, no preamble.\n\n"
        "CONVERSATION SO FAR (most recent last):\n" + (context or "(no prior messages)")[:5000]
        + "\n\n" + facts
    )
    r = requests.post(
        ANTHROPIC_API,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": SENTIMENT_MODEL, "max_tokens": 900,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def extract_quote_items(email_text: str) -> dict:
    """AI reads a quote-request email/thread and returns one object used for BOTH the
    overview table and the quote build: {customer_name, can_quote, items:[{description,
    qty, code}], questions, product_range, postcode, summary, urgency}. Raises if no
    key/failure."""
    import json as _json
    import re

    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")
    prompt = (
        "Read this customer email/conversation to a UK building-supplies retailer (Trade "
        "Superstore). Work out what they want quoted. Reply with ONLY JSON:\n"
        '{"customer_name":"the person\'s name if you can tell, else null",'
        '"can_quote":true|false,'
        '"items":[{"description":"the product as they described it","qty":<int>,'
        '"code":"any product code/SKU they gave, else null"}],'
        '"questions":["short, polite, customer-facing question for each missing detail"],'
        '"caveats":["short customer-facing note on any assumption or missing detail to check"],'
        '"cladding":{"is_cladding":true|false,"product":"Hardie Plank|Hardie VL Plank|null",'
        '"gross_area_m2":<number or null>,"openings_m2":<number or null>,"colour":"... or null",'
        '"wants_trims":true|false,"wants_epdm":true|false,"wants_screws":true|false},'
        '"product_range":"the product category in 1-3 words (e.g. Guttering, Fascia & soffit, '
        'Roofing, Cladding, Insulation, Drainage, Doors, Mixed) or Unclear",'
        '"postcode":"UK delivery postcode if mentioned anywhere, else null",'
        '"summary":"one short line on what they want quoted",'
        '"urgency":"normal|urgent"}\n'
        "JAMES HARDIE CLADDING: if this is a Hardie Plank / Hardie VL Plank cladding enquiry, set "
        "cladding.is_cladding=true and fill it: product, gross_area_m2 = the area to clad "
        "INCLUDING windows/doors (use the stated area; if only width×height dimensions are given, "
        "multiply them), openings_m2 = total window/door area to deduct, colour, and whether they "
        "asked for trims / EPDM tape / screws. CRITICAL: cladding is quoted by converting AREA to "
        "boards (the system does this) — NEVER put an area figure as an item quantity, and leave "
        "items EMPTY for cladding jobs.\n"
        "ALWAYS populate items with EVERY product you can identify, even if the request is "
        "incomplete — we prefer to quote for what we can and flag the rest. If a quantity is "
        "missing, assume a sensible quantity and add a caveat saying it was assumed. Only leave "
        "items empty when you genuinely cannot identify any product to price.\n"
        "can_quote is true ONLY when specific product(s) AND quantities are clearly given (a firm "
        "quote). Otherwise can_quote=false, but STILL fill items with what you found.\n"
        "RULES for caveats (customer-facing): list anything they should check or that we assumed — "
        "e.g. \"We've assumed 10 lengths - let us know the exact quantity\", \"Trims/accessories "
        "weren't specified - tell us if you need any\", \"Colour/finish not confirmed\", "
        "\"Measurements were unclear so this is approximate\". Keep each short and friendly.\n"
        "RULES for questions: write each as a short, friendly question you could send straight "
        "to the customer. Do NOT restate or analyse what they already told you, do NOT write in "
        "the third person. urgency is 'urgent' only if they say they need it quickly or by a "
        "date. Never invent products.\n\nEMAIL:\n"
        + (email_text or "")[:6000]
    )
    r = requests.post(
        ANTHROPIC_API,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": SENTIMENT_MODEL, "max_tokens": 1200,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    txt = r.json()["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("AI returned no JSON")
    return _json.loads(m.group(0))


def shopify_search_variants(query: str, first: int = 5, token: str | None = None) -> list:
    """Search Shopify variants → [{variant_id, sku, price, title, vendor, available}]."""
    store = get_secret("SHOPIFY_STORE")
    token = token or shopify_products_token()
    q = ("query ($q: String!, $n: Int!) { productVariants(first: $n, query: $q) { edges { node "
         "{ id sku price availableForSale title product { title vendor } } } } }")
    r = requests.post(
        f"https://{store}/admin/api/2024-10/graphql.json",
        json={"query": q, "variables": {"q": query, "n": first}},
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify error: {payload['errors']}")
    out = []
    for e in payload.get("data", {}).get("productVariants", {}).get("edges", []):
        n = e["node"]
        prod = n.get("product") or {}
        out.append({"variant_id": n["id"], "sku": n.get("sku"),
                    "price": float(n["price"]) if n.get("price") is not None else None,
                    "available": n.get("availableForSale"),
                    "vendor": prod.get("vendor"),
                    "title": prod.get("title") or n.get("title")})
    return out


# Product-category brand locks: if a requested line matches the keywords, ONLY quote
# products from the given brand/vendor (never anything else). Add rules here to extend.
QUOTE_BRAND_LOCKS = [
    {"brand": "Molan",
     "keywords": ["polycarbonate", "poly carbonate", "multiwall", "multi-wall", "multi wall",
                  "twinwall", "twin wall", "ezglaze", "ez glaze", "ez-glaze", "solid sheet",
                  "solid polycarbonate"]},
]


def _brand_lock_for(text: str):
    """Return the brand a requested line is locked to (e.g. polycarbonate → Molan), or None."""
    t = (text or "").lower()
    for rule in QUOTE_BRAND_LOCKS:
        if any(k in t for k in rule["keywords"]):
            return rule["brand"]
    return None


def _match_branded(code: str, desc: str, brand: str, token: str):
    """Find the best matching variant restricted to a single brand/vendor. Returns None
    if nothing from that brand matches (so we never quote a different brand)."""
    bl = brand.lower()

    def is_brand(c):
        return bl in ((c.get("vendor") or "") + " " + (c.get("title") or "")).lower()

    # Exact SKU within the brand wins (e.g. a specific EZ Glaze length variant).
    if code:
        try:
            cands = shopify_search_variants(f"sku:{code}", first=10, token=token)
        except Exception:  # noqa: BLE001
            cands = []
        nc = _norm_sku(code)
        exact = next((c for c in cands if _norm_sku(c.get("sku")) == nc and is_brand(c)), None)
        if exact:
            return exact

    seen = {}
    queries = []
    if code:
        queries.append(f"sku:{code}")
    queries.append(f"{brand} {desc}".strip())
    queries.append((desc or code or brand).strip())
    for qy in queries:
        if not qy:
            continue
        try:
            for c in shopify_search_variants(qy, first=20, token=token):
                seen[c["variant_id"]] = c
        except Exception:  # noqa: BLE001
            pass
    branded = [c for c in seen.values()
               if bl in ((c.get("vendor") or "") + " " + (c.get("title") or "")).lower()]
    return _best_title_match(branded, desc or code) if branded else None


def _norm_sku(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _best_title_match(cands: list, query: str):
    """Pick the candidate whose title best overlaps the query words; tie-break on
    having a price and being in stock."""
    import re as _re
    qwords = {w for w in _re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) > 2}

    def score(c):
        twords = set(_re.findall(r"[a-z0-9]+", (c.get("title") or "").lower()))
        return (len(qwords & twords), c.get("price") is not None, bool(c.get("available")))

    return max(cands, key=score) if cands else None


def match_quote_variant(code: str | None, description: str | None,
                        token: str | None = None, brand: str | None = None):
    """Match a requested line to a Shopify variant. SKU first: try the given code as
    an exact SKU; if there's no code or no SKU hit, fall back to the best title match
    in the product range. Pass brand=... to force a brand/vendor (e.g. 'Molan').
    Returns a variant dict or None."""
    token = token or shopify_products_token()
    code = (code or "").strip()
    desc = (description or "").strip()

    # 0) Brand lock — explicit (brand=...) or detected (polycarbonate → Molan). When
    #    locked, only that brand/vendor can be quoted.
    brand = brand or _brand_lock_for(f"{code} {desc}")
    if brand:
        return _match_branded(code, desc, brand, token)

    # 1) SKU first — exact code wins.
    if code:
        try:
            cands = shopify_search_variants(f"sku:{code}", first=5, token=token)
        except Exception:  # noqa: BLE001
            cands = []
        nc = _norm_sku(code)
        exact = next((c for c in cands if _norm_sku(c.get("sku")) == nc), None)
        if exact:
            return exact
        if cands:  # close SKU hit (e.g. variant suffix)
            return cands[0]

    # 2) Best title match in the range.
    query = desc or code
    if not query:
        return None
    try:
        cands = shopify_search_variants(query, first=10, token=token)
    except Exception:  # noqa: BLE001
        cands = []
    return _best_title_match(cands, query)


def create_draft_order(line_items, email=None, note=None, token: str | None = None,
                       name=None, phone=None) -> dict:
    """Create a Shopify draft order from line_items [{variantId, quantity}]. Shopify
    prices it. Returns {id, name, invoiceUrl, total}. Needs write_draft_orders.
    `email`/`name`/`phone` are the CUSTOMER's (from the form body, not the sender).
    Retries once with a freshly-minted token if the cached one lacks the scope (so a
    just-granted scope works without rebooting the app)."""
    store = get_secret("SHOPIFY_STORE")
    mutation = ("mutation ($input: DraftOrderInput!) { draftOrderCreate(input: $input) { "
                "draftOrder { id name invoiceUrl totalPriceSet { shopMoney { amount } } } "
                "userErrors { field message } } }")
    inp = {"lineItems": [{"variantId": li["variantId"], "quantity": int(li["quantity"])}
                         for li in line_items]}
    if email:
        inp["email"] = email
    if note:
        inp["note"] = note
    if phone:
        inp["phone"] = phone
    if name:
        parts = name.strip().split(None, 1)
        inp["billingAddress"] = {"firstName": parts[0],
                                 "lastName": parts[1] if len(parts) > 1 else ""}

    def _attempt(tok):
        r = requests.post(
            f"https://{store}/admin/api/2024-10/graphql.json",
            json={"query": mutation, "variables": {"input": inp}},
            headers={"X-Shopify-Access-Token": tok, "Content-Type": "application/json"},
            timeout=25)
        r.raise_for_status()
        return r.json()

    tok = token or shopify_products_token()
    payload = _attempt(tok)
    errs = payload.get("errors")
    denied = errs and any("access denied" in str(e.get("message", "")).lower() for e in errs)
    if denied and not token:
        # Cached token may predate a scope change — mint a fresh one and try again.
        _SHOP_TOK["token"] = None
        payload = _attempt(shopify_products_token())
        errs = payload.get("errors")
    if errs:
        raise RuntimeError(f"Shopify error: {errs}")
    res = payload["data"]["draftOrderCreate"]
    if res["userErrors"]:
        raise RuntimeError(res["userErrors"][0]["message"])
    d = res["draftOrder"]
    d["total"] = float((d.get("totalPriceSet") or {}).get("shopMoney", {}).get("amount") or 0)
    return d


def _plain_to_html(text: str) -> str:
    """Turn a plain-text email body into tidy HTML: paragraphs, bullet lists, and
    clickable links — so the Outlook draft reads like a real email, not a note."""
    import html as _html
    import re as _re

    def esc_link(s: str) -> str:
        parts = _re.split(r"(https?://[^\s]+)", s)
        return "".join(f'<a href="{p}">{p}</a>' if i % 2 else _html.escape(p)
                       for i, p in enumerate(parts))

    out, in_ul = [], False
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if s.startswith("- ") or s.startswith("• "):
            if not in_ul:
                out.append("<ul style='margin:6px 0;padding-left:20px'>")
                in_ul = True
            out.append(f"<li>{esc_link(s[2:].strip())}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append("<br>" if s == "" else f"{esc_link(s)}<br>")
    if in_ul:
        out.append("</ul>")
    return ("<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
            "color:#21242B;line-height:1.5\">" + "".join(out) + "</div>")


def create_reply_draft(mailbox: str, message_id: str, body: str, subject: str | None = None,
                       token: str | None = None, as_html: bool = False,
                       to_email: str | None = None) -> str | None:
    """Create a *draft reply* to a message (lands in Drafts, threaded). Optionally
    override the subject, send as formatted HTML, and re-address it to `to_email` (the
    real customer — form-submission emails come FROM the form app, not the customer, so
    a plain reply would go back to the form). Returns the draft's webLink. Mail.ReadWrite."""
    token = token or ms_token()
    r = requests.post(f"{GRAPH}/users/{mailbox}/messages/{message_id}/createReply",
                      headers={"Authorization": f"Bearer {token}"}, timeout=25)
    r.raise_for_status()
    draft = r.json()
    did = draft.get("id")
    if as_html:
        patch = {"body": {"contentType": "HTML", "content": _plain_to_html(body)}}
    else:
        patch = {"body": {"contentType": "Text", "content": body}}
    if subject:
        patch["subject"] = subject
    if to_email:
        patch["toRecipients"] = [{"emailAddress": {"address": to_email}}]
    r2 = requests.patch(f"{GRAPH}/users/{mailbox}/messages/{did}",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json=patch, timeout=25)
    r2.raise_for_status()
    return draft.get("webLink")


def monday_asset_url(asset_id, token: str | None = None) -> str | None:
    """Temporary signed download URL for a Monday file asset."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    r = requests.post(MONDAY_API,
                      json={"query": "query($ids:[ID!]!){assets(ids:$ids){id public_url}}",
                            "variables": {"ids": [str(asset_id)]}},
                      headers={"Authorization": token, "API-Version": "2024-10"}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    assets = payload.get("data", {}).get("assets", []) or []
    return assets[0]["public_url"] if assets else None


def read_invoice_pdf(pdf_url: str) -> dict:
    """Read a supplier invoice PDF with Claude and return structured line items:
    {supplier, invoice_no, invoice_date, lines:[{sku, description, qty,
    unit_price, line_total}], subtotal_ex_vat, vat, total}. Prices ex-VAT, GBP."""
    import base64
    import json as _json
    import re

    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")
    pdf = requests.get(pdf_url, timeout=60)
    pdf.raise_for_status()
    b64 = base64.standard_b64encode(pdf.content).decode()
    prompt = (
        "Read this supplier invoice carefully and extract the line items and totals. "
        "Reply with ONLY a JSON object, no other text:\n"
        '{"supplier":"...","invoice_no":"...","invoice_date":"YYYY-MM-DD",'
        '"lines":[{"sku":"the product/SKU code printed on the line","description":"...",'
        '"qty":<number>,"unit_price":<ex-VAT cost per unit>,"line_total":<ex-VAT line total>}],'
        '"subtotal_ex_vat":<number>,"vat":<number>,"total":<number>}\n'
        "All prices are GBP. unit_price and line_total MUST be EX-VAT (the cost before VAT is "
        "added). Use the product/SKU code exactly as printed on each line. If a value is genuinely "
        "absent use null. Do not invent or merge lines."
    )
    body = {
        "model": INVOICE_MODEL, "max_tokens": 2500,
        "messages": [{"role": "user", "content": [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": prompt}]}],
    }
    r = requests.post(ANTHROPIC_API,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json=body, timeout=150)
    r.raise_for_status()
    blocks = r.json().get("content", [])
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("Could not read the invoice PDF")
    return _json.loads(m.group(0))


def set_invoice_status(sub_id, label: str, token: str | None = None) -> bool:
    """Set a subitem's Payment Status (status7__1) to a label, e.g.
    'Approved (To QB)' or 'Discrepancy'. Uses change_column_value with {label} (the
    canonical method for status columns) and VERIFIES it stuck by reading the value
    back in the same response. Returns True, or raises a clear error if it didn't apply."""
    import json as _json
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    query = ("mutation ($board: ID!, $item: ID!, $val: JSON!) {"
             " change_column_value(board_id: $board, item_id: $item,"
             " column_id: \"status7__1\", value: $val, create_labels_if_missing: false)"
             " { id column_values(ids: [\"status7__1\"]) { text } } }")
    r = requests.post(
        MONDAY_API,
        json={"query": query, "variables": {"board": str(SUBITEMS_BOARD_ID),
                                            "item": str(sub_id),
                                            "val": _json.dumps({"label": label})}},
        headers={"Authorization": token, "API-Version": "2024-10"}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday rejected '{label}': {payload['errors']}")
    cv = (((payload.get("data") or {}).get("change_column_value") or {})
          .get("column_values") or [])
    actual = cv[0].get("text") if cv else None
    if actual != label:
        raise RuntimeError(f"Monday did not apply '{label}' (it shows '{actual}') — "
                           "check the label exists and the API token can edit subitems.")
    return True


def set_subitem_text(sub_id, column_id: str, text: str, token: str | None = None) -> bool:
    """Write plain text into a subitem's text column (e.g. the discrepancy note in
    text_mm3gh2za). Uses change_simple_column_value. Raises on API failure."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    query = ("mutation ($board: ID!, $item: ID!, $col: String!, $val: String!) {"
             " change_simple_column_value(board_id: $board, item_id: $item,"
             " column_id: $col, value: $val) { id } }")
    r = requests.post(
        MONDAY_API,
        json={"query": query, "variables": {"board": str(SUBITEMS_BOARD_ID),
                                            "item": str(sub_id), "col": column_id,
                                            "val": text}},
        headers={"Authorization": token, "API-Version": "2024-10"}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"Monday rejected note write: {payload['errors']}")
    return True


def get_invoice_status(sub_id, token: str | None = None) -> str | None:
    """Read a subitem's current Payment Status label (status7__1)."""
    token = token or get_token()
    if not token:
        raise RuntimeError("No MONDAY_API_TOKEN configured")
    q = ('query ($ids: [ID!]) { items(ids: $ids) { '
         'column_values(ids: ["status7__1"]) { text } } }')
    r = requests.post(MONDAY_API, json={"query": q, "variables": {"ids": [str(sub_id)]}},
                      headers={"Authorization": token, "API-Version": "2024-10"}, timeout=30)
    r.raise_for_status()
    items = (r.json().get("data") or {}).get("items") or []
    cv = items[0].get("column_values") if items else None
    return cv[0].get("text") if cv else None


def find_kind_words(emails: list) -> dict | None:
    """Find the single most positive / appreciative customer message among
    `emails`. Returns {"quote", "about"} or None if nothing genuinely kind.
    Raises if ANTHROPIC_API_KEY isn't set or the call fails."""
    import json as _json
    import re

    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured")
    if not emails:
        return None

    block = "\n".join(
        f"{i}. SUBJECT: {e['subject']}\n   PREVIEW: {e['preview']}"
        for i, e in enumerate(emails[:60], 1))
    prompt = (
        "Below are recent customer emails (subject + first line) to a UK building-supplies "
        "retailer. Find the SINGLE most positive, appreciative or kind message — a thank-you, "
        "praise, or genuinely happy comment. Reply with ONLY a JSON object, no other text:\n"
        '{"found": true|false, '
        '"quote": "a short warm lightly-tidied version of what the customer said '
        '(max ~140 chars, keep their voice, no personal names)", '
        '"about": "2-4 word summary of what they were happy about"}\n'
        'If NONE of the emails are genuinely positive, return {"found": false}. '
        "Never invent praise that isn't there.\n\n"
        f"EMAILS:\n{block}"
    )
    r = requests.post(
        ANTHROPIC_API,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": SENTIMENT_MODEL, "max_tokens": 300,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=45,
    )
    r.raise_for_status()
    txt = r.json()["content"][0]["text"].strip()
    match = re.search(r"\{.*\}", txt, re.S)
    if not match:
        return None
    data = _json.loads(match.group(0))
    if not data.get("found") or not data.get("quote"):
        return None
    return {"quote": data["quote"].strip(), "about": (data.get("about") or "").strip()}


def fetch_sales_pulse(token: str | None = None) -> dict:
    """Today's Shopify takings vs the same clock-time yesterday (Europe/London).
    Returns {today, yesterday, count_today, ahead_pct, currency}. Raises if
    Shopify isn't configured or the orders read scope isn't granted."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    store = get_secret("SHOPIFY_STORE")
    token = token or shopify_products_token()
    tz = ZoneInfo("Europe/London")
    now = datetime.now(tz)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yest0 = today0 - timedelta(days=1)
    yest_cutoff = yest0 + (now - today0)         # same time-of-day, yesterday
    since_utc = yest0.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    query ($q: String!, $cursor: String) {
      orders(first: 250, query: $q, after: $cursor, sortKey: CREATED_AT) {
        edges { cursor node { createdAt test cancelledAt
          currentTotalPriceSet { shopMoney { amount currencyCode } } } }
        pageInfo { hasNextPage }
      }
    }"""
    qfilter = f"created_at:>={since_utc}"
    today_sum = yest_sum = 0.0
    today_n = 0
    currency = "GBP"
    cursor = None
    for _ in range(20):                          # safety cap ~5000 orders
        r = requests.post(
            f"https://{store}/admin/api/2024-10/graphql.json",
            json={"query": query, "variables": {"q": qfilter, "cursor": cursor}},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=25,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise RuntimeError(f"Shopify error: {payload['errors']}")
        conn = payload["data"]["orders"]
        for e in conn["edges"]:
            n = e["node"]
            cursor = e["cursor"]
            if n.get("test") or n.get("cancelledAt"):
                continue
            money = (n.get("currentTotalPriceSet") or {}).get("shopMoney") or {}
            amt = float(money.get("amount") or 0)
            currency = money.get("currencyCode") or currency
            created = datetime.fromisoformat(
                n["createdAt"].replace("Z", "+00:00")).astimezone(tz)
            if created >= today0:
                today_sum += amt
                today_n += 1
            elif yest0 <= created <= yest_cutoff:
                yest_sum += amt
        if not conn["pageInfo"]["hasNextPage"]:
            break
    ahead = round((today_sum - yest_sum) / yest_sum * 100) if yest_sum > 0 else None
    return {"today": round(today_sum), "yesterday": round(yest_sum),
            "count_today": today_n, "ahead_pct": ahead, "currency": currency}


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
