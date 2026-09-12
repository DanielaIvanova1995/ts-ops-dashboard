"""Supabase backend — Platform Phase 1 (durable state in Postgres instead of Monday-item hacks
and the host's wiped disk).

FEATURE-FLAGGED: everything here is inert unless SUPABASE_URL + SUPABASE_SERVICE_KEY are set, so
the app behaves EXACTLY as before until the project is connected. `configured()` gates every caller,
and each write is best-effort (a Supabase hiccup never breaks the app — it falls back to the current
Monday storage). Nothing here changes live behaviour on its own.

First slices (see docs/SUPABASE_PHASE1.md for the schema + setup):
  - reconciliations  : saved statement reconciliations (real history, not one snapshot per supplier)
  - qbo_tokens       : the QuickBooks refresh/access token (off the Monday-item hack)
  - vendor_map       : learned statement-supplier -> QuickBooks vendor mappings
  - audit_log        : who did what, when (append-only)
"""
from __future__ import annotations

import datetime as _dt

from data_sources import get_secret          # reuse the quote/whitespace-tolerant secret reader

_CLIENT = None


def configured() -> bool:
    """True only when a Supabase project is wired up. Callers use this to decide whether to use
    Supabase or fall back to the existing Monday/disk storage."""
    return bool(get_secret("SUPABASE_URL") and get_secret("SUPABASE_SERVICE_KEY"))


def _client():
    global _CLIENT
    if _CLIENT is None:
        from supabase import create_client        # imported lazily so the app runs without the lib
        _CLIENT = create_client(get_secret("SUPABASE_URL"), get_secret("SUPABASE_SERVICE_KEY"))
    return _CLIENT


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _json_safe(o):
    """Make a value valid JSON for a jsonb column: NaN/Infinity → null (they aren't valid JSON and
    make PostgREST 400), and anything non-primitive (datetime, Decimal, numpy, sets…) → str."""
    import math
    if isinstance(o, bool) or o is None or isinstance(o, (str, int)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return str(o)


# ---- Saved reconciliations (first slice) ----------------------------------------------------
def recon_save(vid: str, snapshot: dict) -> bool:
    """Append a reconciliation snapshot for a QuickBooks vendor id. Keeps history (one row per
    save) rather than overwriting. Best-effort; returns True on success."""
    if not configured():
        return False
    try:
        _client().table("reconciliations").insert({
            "vendor_id": str(vid),
            "supplier": snapshot.get("supplier"),
            "saved_at": _now(),
            "snapshot": _json_safe(snapshot),
        }).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def recon_save_strict(vid: str, snapshot: dict):
    """Like recon_save but RAISES on failure — used by the on-screen diagnostic so a write problem
    (RLS, key perms, a non-JSON snapshot) is surfaced instead of silently swallowed."""
    _client().table("reconciliations").insert({
        "vendor_id": str(vid), "supplier": snapshot.get("supplier"),
        "saved_at": _now(), "snapshot": _json_safe(snapshot),
    }).execute()


def recon_latest(vid: str) -> dict | None:
    """The most recent saved reconciliation snapshot for a vendor, or None."""
    if not configured():
        return None
    try:
        r = (_client().table("reconciliations").select("snapshot")
             .eq("vendor_id", str(vid)).order("saved_at", desc=True).limit(1).execute())
        rows = r.data or []
        return rows[0]["snapshot"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def recon_load_all() -> dict:
    """{f"v{vendor_id}": latest snapshot} — the most recent saved reconciliation per vendor, read
    from the database. Mirrors data_sources.recon_load_all()'s shape so the saved-list UI is
    unchanged, just backed by durable storage."""
    if not configured():
        return {}
    try:
        r = (_client().table("reconciliations").select("vendor_id,snapshot")
             .order("saved_at", desc=True).limit(1000).execute())
        out = {}
        for row in (r.data or []):
            key = f"v{row['vendor_id']}"
            if key not in out:            # rows come newest-first, so the first seen is the latest
                out[key] = row["snapshot"]
        return out
    except Exception:  # noqa: BLE001
        return {}


def recon_history(vid: str, limit: int = 50) -> list:
    """Recent saved reconciliations for a vendor (newest first) — the real history."""
    if not configured():
        return []
    try:
        r = (_client().table("reconciliations").select("saved_at,supplier,snapshot")
             .eq("vendor_id", str(vid)).order("saved_at", desc=True).limit(limit).execute())
        return r.data or []
    except Exception:  # noqa: BLE001
        return []


# ---- QuickBooks token (off the Monday-item hack) --------------------------------------------
def qbo_tokens_get() -> dict | None:
    if not configured():
        return None
    try:
        r = _client().table("qbo_tokens").select("tokens").eq("id", 1).limit(1).execute()
        rows = r.data or []
        return rows[0]["tokens"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def qbo_tokens_set(tokens: dict) -> bool:
    if not configured():
        return False
    try:
        _client().table("qbo_tokens").upsert({"id": 1, "tokens": _json_safe(tokens),
                                              "updated_at": _now()}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Learned statement-supplier -> QuickBooks vendor map -----------------------------------
def vendor_map_load() -> dict:
    if not configured():
        return {}
    try:
        r = _client().table("vendor_map").select("supplier_key,vendor_id,vendor_name").execute()
        return {row["supplier_key"]: {"id": row["vendor_id"], "name": row["vendor_name"]}
                for row in (r.data or [])}
    except Exception:  # noqa: BLE001
        return {}


def vendor_map_save(supplier_key: str, vendor_id: str, vendor_name: str) -> bool:
    if not configured():
        return False
    try:
        _client().table("vendor_map").upsert({
            "supplier_key": supplier_key, "vendor_id": str(vendor_id),
            "vendor_name": vendor_name, "updated_at": _now()}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Audit log (append-only) ---------------------------------------------------------------
def audit_recent(limit: int = 50) -> list:
    """Recent audit-log entries (newest first) — [{at, actor, action, detail, ref}]."""
    if not configured():
        return []
    try:
        r = (_client().table("audit_log").select("at,actor,action,detail,ref")
             .order("at", desc=True).limit(limit).execute())
        return r.data or []
    except Exception:  # noqa: BLE001
        return []


# ---- Durable invoice-parse cache (so a checked invoice is never re-read by Claude = no re-pay) --
def invoice_parse_get(key: str) -> dict | None:
    """A previously stored PDF parse for this key (asset id + parser version), or None. Lets a
    checked invoice survive restarts/redeploys without paying Claude to re-read it."""
    if not configured() or not key:
        return None
    try:
        r = _client().table("invoice_parses").select("parsed").eq("key", key).limit(1).execute()
        rows = r.data or []
        return rows[0]["parsed"] if rows else None
    except Exception:  # noqa: BLE001
        return None


def invoice_parse_set(key: str, parsed: dict) -> bool:
    """Store a successful PDF parse durably (upsert). Callers must NOT store error results."""
    if not configured() or not key or not isinstance(parsed, dict):
        return False
    try:
        _client().table("invoice_parses").upsert({"key": key, "parsed": _json_safe(parsed),
                                                  "at": _now()}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Small key/value config store (so the scheduled job reads the UI's settings) -----------
def config_get(key: str, default=None):
    """Read a JSON config value by key (e.g. the invoice-import folder selection). default if unset."""
    if not configured():
        return default
    try:
        r = _client().table("app_config").select("value").eq("key", key).limit(1).execute()
        rows = r.data or []
        return rows[0]["value"] if rows else default
    except Exception:  # noqa: BLE001
        return default


def config_set(key: str, value) -> bool:
    """Store a JSON config value by key (upsert)."""
    if not configured():
        return False
    try:
        _client().table("app_config").upsert({"key": key, "value": _json_safe(value),
                                              "updated_at": _now()}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Invoice import (de-dup + failure log for the native invoice importer) -----------------
def invoice_import_seen(internet_id: str) -> bool:
    """True if this email (by internetMessageId) has already been successfully handled
    (imported or skipped) — the de-dup guard so an invoice is never imported twice. A previous
    FAILED row does NOT count as seen, so failures auto-retry on the next run (a transient glitch
    self-heals; a genuine problem stays in the failed list for review). When Supabase isn't
    configured, returns False (the importer relies on Monday's own duplicate detection as a
    backstop)."""
    if not configured() or not internet_id:
        return False
    try:
        r = (_client().table("invoice_imports").select("status")
             .eq("internet_id", internet_id).in_("status", ["imported", "skipped", "ignored"])
             .limit(1).execute())
        return bool(r.data)
    except Exception:  # noqa: BLE001
        return False


def invoice_import_log(internet_id: str, status: str, **fields) -> bool:
    """Record the outcome of handling one invoice email: status = 'imported' | 'failed' |
    'skipped'. Extra fields (supplier, order_no, invoice_no, subitem_id, total, detail) are stored
    for the on-screen recent/failed lists. Upsert on internet_id so a retry overwrites."""
    if not configured() or not internet_id:
        return False
    try:
        row = {"internet_id": internet_id, "status": status, "at": _now()}
        for k in ("supplier", "order_no", "invoice_no", "subitem_id", "detail"):
            if k in fields and fields[k] is not None:
                row[k] = str(fields[k])[:500]
        if isinstance(fields.get("total"), (int, float)):
            row["total"] = fields["total"]
        _client().table("invoice_imports").upsert(row).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def invoice_import_recent(limit: int = 50, status: str | None = None) -> list:
    """Recent invoice-import outcomes (newest first). Pass status='failed' for the retry list."""
    if not configured():
        return []
    try:
        q = (_client().table("invoice_imports")
             .select("internet_id,status,supplier,order_no,invoice_no,subitem_id,total,detail,at")
             .order("at", desc=True).limit(limit))
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception:  # noqa: BLE001
        return []


def invoice_import_delete(internet_id: str) -> bool:
    """Forget one email (so the next run re-tries it) — used by the 'retry' button on a failure."""
    if not configured() or not internet_id:
        return False
    try:
        _client().table("invoice_imports").delete().eq("internet_id", internet_id).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Email triage (de-dup + history for the native Outlook-triage job) ----------------------
def email_triage_seen(internet_id: str) -> bool:
    """True if this email (by internetMessageId) has already been triaged and MOVED (moved/skipped),
    so it's never re-classified — the de-dup + cost guard. A 'failed' or 'no_folder' row does NOT
    count as seen, so those auto-retry next run once fixed. False when Supabase isn't configured (the
    move itself is the backstop: a moved email leaves the watched folder)."""
    if not configured() or not internet_id:
        return False
    try:
        r = (_client().table("email_triage").select("status")
             .eq("internet_id", internet_id).in_("status", ["moved", "skipped"])
             .limit(1).execute())
        return bool(r.data)
    except Exception:  # noqa: BLE001
        return False


def email_triage_log(internet_id: str, status: str, **fields) -> bool:
    """Record a triage outcome (upsert by internet_id): status = 'moved' | 'skipped' | 'no_folder' |
    'failed'. Extra fields (subject, sender, category, owner, folder, detail) feed the history view."""
    if not configured() or not internet_id:
        return False
    try:
        row = {"internet_id": internet_id, "status": status, "at": _now()}
        for k in ("subject", "sender", "category", "owner", "folder", "detail"):
            if fields.get(k) is not None:
                row[k] = str(fields[k])[:500]
        _client().table("email_triage").upsert(row).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def email_triage_recent(limit: int = 100, status: str | None = None) -> list:
    """Recent triage outcomes (newest first). Pass status='no_folder'/'failed' for the problem list."""
    if not configured():
        return []
    try:
        q = (_client().table("email_triage")
             .select("internet_id,status,subject,sender,category,owner,folder,detail,at")
             .order("at", desc=True).limit(limit))
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception:  # noqa: BLE001
        return []


def email_triage_delete(internet_id: str) -> bool:
    """Forget one triaged email so the next run re-tries it (used after fixing a folder mapping)."""
    if not configured() or not internet_id:
        return False
    try:
        _client().table("email_triage").delete().eq("internet_id", internet_id).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- Claude API usage/cost log (so TradeHub can show its own daily Claude spend) ------------
def llm_usage_log(model: str, feature: str, input_tokens: int, output_tokens: int,
                  cost_usd: float) -> bool:
    """Append one Claude call's token usage + computed cost. `feature` groups spend by area
    (triage / invoice_import / invoice_read / …). Best-effort; one row per call, aggregated on read."""
    if not configured():
        return False
    try:
        import datetime as _d
        now = _dt.datetime.now(_dt.timezone.utc)
        _client().table("llm_usage").insert({
            "at": now.isoformat(), "day": now.date().isoformat(),
            "model": str(model)[:60], "feature": str(feature)[:40],
            "input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
            "cost_usd": float(cost_usd or 0.0)}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def llm_usage_recent(days: int = 14) -> list:
    """Rows from the last N days (for the cost display). [{at, day, model, feature, input_tokens,
    output_tokens, cost_usd}]. Aggregated into per-day / per-feature totals by the caller."""
    if not configured():
        return []
    try:
        import datetime as _d
        cutoff = (_dt.datetime.now(_dt.timezone.utc).date()
                  - _d.timedelta(days=days)).isoformat()
        r = (_client().table("llm_usage")
             .select("at,day,model,feature,input_tokens,output_tokens,cost_usd")
             .gte("day", cutoff).order("at", desc=True).limit(20000).execute())
        return r.data or []
    except Exception:  # noqa: BLE001
        return []


# ---- Scheduled invoice-check log (skip already-handled, keep a reasons history) -------------
def invoice_check_seen(sub_id: str) -> bool:
    """True if the scheduler has already checked this invoice AND set it aside (left/failed), so it
    isn't re-checked every cycle. A pushed/held one leaves Needs Review so it won't be re-fetched
    anyway; this guards the ones that stay in the queue."""
    if not configured() or not sub_id:
        return False
    try:
        r = (_client().table("invoice_check_log").select("outcome")
             .eq("sub_id", str(sub_id)).in_("outcome", ["left", "failed"]).limit(1).execute())
        return bool(r.data)
    except Exception:  # noqa: BLE001
        return False


def invoice_check_log(sub_id: str, outcome: str, **fields) -> bool:
    """Record a scheduled-check outcome for an invoice (upsert by sub_id): outcome =
    'pushed'|'held'|'left'|'failed', plus invoice_no/order_no/supplier/reason for the history view."""
    if not configured() or not sub_id:
        return False
    try:
        row = {"sub_id": str(sub_id), "outcome": outcome, "at": _now()}
        for k in ("invoice_no", "order_no", "supplier", "reason"):
            if fields.get(k) is not None:
                row[k] = str(fields[k])[:400]
        _client().table("invoice_check_log").upsert(row).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def invoice_check_recent(limit: int = 100, outcomes: list | None = None) -> list:
    """Recent scheduled-check outcomes (newest first). Pass outcomes=['left','failed'] for the
    'didn't go through' history."""
    if not configured():
        return []
    try:
        q = (_client().table("invoice_check_log")
             .select("sub_id,outcome,invoice_no,order_no,supplier,reason,at")
             .order("at", desc=True).limit(limit))
        if outcomes:
            q = q.in_("outcome", outcomes)
        return q.execute().data or []
    except Exception:  # noqa: BLE001
        return []


def invoice_check_clear(sub_id: str) -> bool:
    """Forget a left/failed invoice so the scheduler re-checks it next cycle (after you've fixed it)."""
    if not configured() or not sub_id:
        return False
    try:
        _client().table("invoice_check_log").delete().eq("sub_id", str(sub_id)).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def audit(actor: str, action: str, detail: str = "", ref: str = "") -> bool:
    if not configured():
        return False
    try:
        _client().table("audit_log").insert({
            "at": _now(), "actor": actor or "", "action": action or "",
            "detail": detail or "", "ref": ref or ""}).execute()
        return True
    except Exception:  # noqa: BLE001
        return False
