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


def _due(name: str, interval_min: int) -> bool:
    """True if the daily job `name` hasn't run within its interval (read from the persisted
    '<name>_status' timestamp). Survives restarts/deploys, so a once-a-day job doesn't re-run on
    every process restart."""
    st = _cfg(name + "_status")
    at = st.get("at")
    if not at:
        return True
    try:
        return (_now() - _dt.datetime.fromisoformat(at)).total_seconds() >= max(1, interval_min) * 60
    except Exception:  # noqa: BLE001
        return True


def _due_at_hour(name: str, hour: int, tzname: str = "Europe/London") -> bool:
    """True if the daily job `name` should run now because it's on/after `hour` (local time) and it
    hasn't already run today. Fires once per day at a fixed wall-clock hour (DST-aware via zoneinfo;
    falls back to UTC if the tz database isn't available)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname)
    except Exception:  # noqa: BLE001
        tz = _dt.timezone.utc
    now_local = _now().astimezone(tz)
    if now_local.hour < hour:
        return False
    st = _cfg(name + "_status")
    at = st.get("at")
    if not at:
        return True
    try:
        last_local = _dt.datetime.fromisoformat(at).astimezone(tz)
        return last_local.date() < now_local.date()   # hasn't run yet today
    except Exception:  # noqa: BLE001
        return True


def _write_status(name: str, payload: dict):
    if not supabase_db:
        return
    try:
        supabase_db.config_set(name + "_status", {**payload, "at": _now().isoformat()})
    except Exception:  # noqa: BLE001
        pass


def loop():
    """The scheduler tick loop (runs forever in a daemon thread)."""
    next_run = {"email_triage": 0.0, "quote_triage": 0.0}
    while True:
        try:
            if hold_lease():                  # only the lease owner does the work
                now = _time.time()
                # Run AT MOST ONE job per tick (ticks are _POLL seconds apart, jobs are due every
                # 15-30 min, so each still gets its turn quickly). This stops two heavy jobs' memory
                # peaks stacking in the same tick, which was tripping Render's memory limit.
                ran = False
                et = _cfg("email_triage")
                if not ran and et.get("auto_enabled") and now >= next_run["email_triage"]:
                    ran = True
                    next_run["email_triage"] = now + max(300, int(et.get("interval_min") or 10) * 60)
                    import email_triage
                    _run("email_triage", lambda: email_triage.run_triage(
                        dry_run=False, since_days=et.get("since_days"),
                        max_total=int(et.get("max_total") or 40)))
                qt = _cfg("quote_triage")
                if not ran and qt.get("auto_enabled") and now >= next_run["quote_triage"]:
                    ran = True
                    next_run["quote_triage"] = now + max(300, int(qt.get("interval_min") or 10) * 60)
                    import quote_triage
                    _run("quote_triage", lambda: quote_triage.run_triage(
                        dry_run=False, since_days=qt.get("since_days"),
                        max_total=int(qt.get("max_total") or 40)))

                # Invoice import — ALWAYS-ON here (it used to run only inside Streamlit, so when that
                # wasn't open the Suppliers folders filled up and nothing imported). Scans accounts@
                # Inbox/Suppliers, creates the Monday invoice subitems, archives handled emails.
                ii = _cfg("invoice_import")
                # CALM cadence (backlog cleared 2026-10-28): the aggressive catch-up (80/run every
                # 10 min) blew the Render memory limit — too many PDFs read + parsed per tick. Keep a
                # modest batch and a gentle interval so memory stays bounded; daily volume is small.
                _ii_int = max(int(ii.get("interval_min") or 60), 60)       # hourly (backlog cleared)
                _ii_max = min(int(ii.get("max_total") or 15), 15)          # at most 15 PDFs/run (memory)
                if not ran and ii.get("auto_enabled", True) and now >= next_run.get("invoice_import", 0.0):
                    ran = True
                    next_run["invoice_import"] = now + max(900, _ii_int * 60)
                    import invoice_import
                    def _imp():
                        r = invoice_import.run_import(dry_run=False, max_total=_ii_max)
                        # map to the status shape _run records (moved/failed)
                        return {"ok": r.get("ok"), "moved": r.get("imported"), "failed": r.get("failed"),
                                "skipped": r.get("skipped"), "error": r.get("error"),
                                "imported": r.get("imported"), "ignored": r.get("ignored"),
                                "scanned": r.get("scanned")}
                    _run("invoice_import", _imp)

                # Invoice CHECK + AUTO-APPROVE — check every Needs Review AND Matched invoice (invoice
                # vs order vs price) and push the clean, in-margin ones straight to QuickBooks + mark
                # 'Approved (To QB by TradeHub)' on Monday (Daniela 2026-10-27: push in-margin ones
                # directly). Out-of-margin / mismatched stay in Needs Review; never auto-marks
                # Discrepancy. Set invoice_check config check_only=true to revert to mark-Matched-only.
                ic = _cfg("invoice_check")
                # CALM cadence (backlog cleared): modest batch + gentle interval to keep memory down.
                _ic_int = max(int(ic.get("interval_min") or 30), 30)      # every 30 min (eased for memory)
                _ic_max = min(int(ic.get("max_total") or 20), 20)         # at most 20 checks/run
                if not ran and ic.get("auto_enabled", True) and now >= next_run.get("invoice_check", 0.0):
                    ran = True
                    next_run["invoice_check"] = now + max(1200, _ic_int * 60)
                    import run_invoice_check
                    _co = bool(ic.get("check_only", False))
                    def _chk():
                        r = run_invoice_check.main(check_only=_co, dry_run=False, max_total=_ic_max)
                        return {"ok": (r or {}).get("ok", True), "moved": (r or {}).get("matched"),
                                "failed": (r or {}).get("fail"), "checked": (r or {}).get("checked"),
                                "review": (r or {}).get("review")}
                    _run("invoice_check", _chk)

                # Daily: auto-reconcile supplier statements dropped in the Outlook folder, so each
                # supplier's latest is already reconciled in the Statements list before payments.
                sr = _cfg("statement_recon")
                # Run at a fixed wall-clock hour (default 6am UK) — set run_hour=null in config to fall
                # back to the rolling once-every-interval_min timer instead.
                _rh = sr.get("run_hour", 6)
                _sr_due = (_due_at_hour("statement_recon", int(_rh)) if _rh is not None
                           else _due("statement_recon", int(sr.get("interval_min") or 1440)))
                if not ran and sr.get("auto_enabled", True) and _sr_due:
                    ran = True
                    try:
                        import statement_recon
                        statement_recon.run_auto(max_total=int(sr.get("max_total") or 40))  # writes its own status
                    except Exception as e:  # noqa: BLE001
                        _write_status("statement_recon", {"ok": False, "error": str(e)[:200], "reason": "auto"})

                # Daily: repair ~98% margins by filling any invoice totals missing from the order's
                # INV slots across the board (duplicate-safe; only touches high-margin/unknown ones).
                fm = _cfg("fix_margins")
                if not ran and fm.get("auto_enabled", True) and _due("fix_margins", int(fm.get("interval_min") or 1440)):
                    ran = True
                    try:
                        import data_sources as _ds
                        r = _ds.fix_margins_sweep()
                        _write_status("fix_margins", {
                            "ok": r.get("ok"), "orders_checked": r.get("orders_checked"),
                            "orders_fixed": r.get("orders_fixed"), "filled": r.get("filled"),
                            "total_mismatches": (r.get("total_mismatches") or [])[:40],
                            "n_total_mismatches": r.get("n_total_mismatches"),
                            "items": (r.get("items") or [])[:40], "reason": "auto"})
                        if r.get("filled") and supabase_db:
                            try:
                                supabase_db.audit("scheduler", "fix_margins",
                                                  f"filled {r.get('filled')} slots on {r.get('orders_fixed')} orders", "")
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception as e:  # noqa: BLE001
                        _write_status("fix_margins", {"ok": False, "error": str(e)[:200], "reason": "auto"})
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
