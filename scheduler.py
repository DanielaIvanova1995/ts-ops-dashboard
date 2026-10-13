"""Always-on triage scheduler — runs email + quote triage on a timer, independent of anyone having
the Streamlit app open. Designed to run inside the always-on API service (api/main.py) so triage no
longer depends on the Streamlit process being awake/opened.

Coordination: a Supabase "lease" (triage_scheduler_lease) ensures only ONE process runs triage at a
time. Whichever process refreshes the lease most recently owns it; others defer. The always-on API
keeps the lease fresh, so it's the de-facto owner; the Streamlit worker checks the lease and skips
triage when the API holds it (falling back automatically if the API ever goes down for >TTL).

Triage itself is idempotent (de-dups handled emails in Supabase), so even an overlap can't double-
file an email — the lease is about not wasting Claude calls, not correctness.
"""
from __future__ import annotations

import datetime as _dt
import os
import threading
import time as _time
import uuid

try:
    import supabase_db
except Exception:  # noqa: BLE001
    supabase_db = None

_OWNER = f"{os.environ.get('RENDER_SERVICE_NAME', 'svc')}:{uuid.uuid4().hex[:8]}"
_LEASE_KEY = "triage_scheduler_lease"
_LEASE_TTL = 90          # seconds a lease stays valid without a refresh
_POLL = 20               # seconds between scheduler ticks
_started = False
_lock = threading.Lock()


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def hold_lease() -> bool:
    """Claim or refresh the triage lease. Returns True if THIS process holds it (and should run
    triage), False if another process holds a still-fresh lease. With no Supabase, always True."""
    if not supabase_db or not supabase_db.configured():
        return True
    try:
        cur = supabase_db.config_get(_LEASE_KEY) or {}
        owner, ts = cur.get("owner"), cur.get("ts")
        fresh = False
        if ts:
            try:
                fresh = (_now() - _dt.datetime.fromisoformat(ts)).total_seconds() < _LEASE_TTL
            except Exception:  # noqa: BLE001
                fresh = False
        if owner and owner != _OWNER and fresh:
            return False                      # someone else is actively running
        supabase_db.config_set(_LEASE_KEY, {"owner": _OWNER, "ts": _now().isoformat()})
        return True
    except Exception:  # noqa: BLE001
        return True                           # never let coordination failure stop triage


def _run(name: str, run_callable):
    """Run one triage job and record its status in Supabase (same keys the UI + /diag read)."""
    try:
        res = run_callable()
        if supabase_db:
            supabase_db.config_set(name + "_status", {
                "at": _now().isoformat(), "moved": res.get("moved"), "failed": res.get("failed"),
                "skipped": res.get("skipped"), "capped": res.get("capped"),
                "ok": res.get("ok"), "error": res.get("error"), "reason": "auto"})
            if res.get("moved") or res.get("failed"):
                try:
                    supabase_db.audit("scheduler", name,
                                      f"moved {res.get('moved')}, failed {res.get('failed')}", "")
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        if supabase_db:
            try:
                supabase_db.config_set(name + "_status", {
                    "at": _now().isoformat(), "ok": False, "error": str(e)[:200], "reason": "auto"})
            except Exception:  # noqa: BLE001
                pass


def _cfg(name: str) -> dict:
    try:
        return (supabase_db.config_get(name) if supabase_db else None) or {}
    except Exception:  # noqa: BLE001
        return {}


def loop():
    """The scheduler tick loop (runs forever in a daemon thread)."""
    next_run = {"email_triage": 0.0, "quote_triage": 0.0}
    while True:
        try:
            if hold_lease():                  # only the lease owner does the work
                now = _time.time()
                et = _cfg("email_triage")
                if et.get("auto_enabled") and now >= next_run["email_triage"]:
                    next_run["email_triage"] = now + max(300, int(et.get("interval_min") or 10) * 60)
                    import email_triage
                    _run("email_triage", lambda: email_triage.run_triage(
                        dry_run=False, since_days=et.get("since_days"),
                        max_total=int(et.get("max_total") or 40)))
                qt = _cfg("quote_triage")
                if qt.get("auto_enabled") and now >= next_run["quote_triage"]:
                    next_run["quote_triage"] = now + max(300, int(qt.get("interval_min") or 10) * 60)
                    import quote_triage
                    _run("quote_triage", lambda: quote_triage.run_triage(
                        dry_run=False, since_days=qt.get("since_days"),
                        max_total=int(qt.get("max_total") or 40)))
        except Exception:  # noqa: BLE001 — a bad tick must never kill the loop
            pass
        _time.sleep(_POLL)


def start():
    """Start the scheduler once per process (idempotent). Gated on RUN_SCHEDULER (default on; set to
    '0' to disable, e.g. on a service that shouldn't run it)."""
    global _started
    if os.environ.get("RUN_SCHEDULER", "1") == "0":
        return False
    with _lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=loop, name="triage-scheduler", daemon=True).start()
    return True
