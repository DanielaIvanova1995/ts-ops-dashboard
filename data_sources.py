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
