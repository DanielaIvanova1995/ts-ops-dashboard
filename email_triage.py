"""Native email triage — a verbatim copy of the Make "Outlook Triage NEW" scenario, run inside
TradeHub instead.

Flow (per new email in the watched Inbox):
  1. skip if we've already triaged it (de-dup by internetMessageId, in Supabase)
  2. classify it with Claude -> {category, is_reply_to_our_thread, thread_owner}
  3. pick the destination folder EXACTLY as Make did (category, with per-owner folders for supplier
     replies) — using the same Outlook folder IDs the Make scenario moved to
  4. MOVE the email there (Outlook)
  5. log the outcome (moved / skipped / failed) for the history view + de-dup

The folder IDs are copied straight from the Make blueprint. Outlook folder IDs are stable across
renames (that's why Make kept working after the folders were renamed), so this files mail into the
same folders Make does. `dry_run=True` classifies + reports but MOVES nothing and marks nothing
handled — so it can be shadow-run against Make before cutover. Every email is handled independently;
one bad email never stops the batch.
"""
from __future__ import annotations

import data_sources as ds

try:
    import supabase_db
except Exception:  # noqa: BLE001 — triage still runs without Supabase (the move itself is the backstop)
    supabase_db = None

# The shared inbox that gets triaged, and the exact Inbox folder Make watched (its id).
MAILBOX = "hello@tradesuperstoreonline.co.uk"
INBOX_ID = ("AAMkAGUzYjQwOWIyLWE2NDktNDhhMS04OGRmLWY2NDM3YTRkNzc0MgAuAAAAAADNPrxz3I1jRrPdjo9v"
            "FUNzAQA9StLmUbsCToOil6HnGLWNAAAAAAEMAAA=")

# Destination Outlook folder IDs, copied verbatim from the Make scenario. Category -> folder id.
_F = "AAMkAGUzYjQwOWIyLWE2NDktNDhhMS04OGRmLWY2NDM3YTRkNzc0MgAuAAAAAADNPrxz3I1jRrPdjo9vFUNzAQA9StLmUbsCToOil6HnGLWN"
CATEGORY_FOLDER = {
    "supplier_with_eta":              _F + "AAPQP8E_AAA=",
    "supplier_no_eta":                _F + "AAPQP8E-AAA=",   # owner none/natasha/unknown (Make default)
    "customer_after_sales":           _F + "AAPQP8FAAAA=",
    "customer_new_order_or_quote":    _F + "AAPQP8FGAAA=",
    "customer_pre_delivery_question": _F + "AAPQP8FIAAA=",
    "customer_delivery_chase":        _F + "AAPQP8FFAAA=",
    "customer_returns":               _F + "AAPQP8FEAAA=",
    "customer_refund_chase":          _F + "AAPQP8FHAAA=",   # Make: same folder as cancellation
    "customer_cancellation":          _F + "AAPQP8FHAAA=",
    "automated_system":               _F + "AAPQP8FDAAA=",
    "unsure":                         _F + "AAPQP8FCAAA=",
}
# Per-owner supplier-reply folders (Make routed supplier_no_eta by the thread owner's sign-off).
# Melissa has left, so there's no Melissa folder — the classifier returns "unknown" for her old
# threads and they fall back to the default supplier_no_eta folder.
OWNER_FOLDER = {
    "megan":   _F + "AAPQP8FLAAA=",
    "malyeka": _F + "AAPQP8FMAAA=",
}


def _dest_id(category: str, owner: str) -> str | None:
    """The destination folder id for a classified email — exactly as Make decided: a per-owner
    folder for a supplier reply that has one, otherwise the category's folder."""
    if category == "supplier_no_eta" and owner in OWNER_FOLDER:
        return OWNER_FOLDER[owner]
    return CATEGORY_FOLDER.get(category)


def run_triage(dry_run: bool = False, since_days: int | None = None, max_total: int | None = 40,
               mailbox: str | None = None) -> dict:
    """Classify + file new emails in the watched Inbox, exactly as the Make scenario did.

    dry_run: classify + report, but MOVE nothing and mark nothing handled.
    since_days: only look at emails received within the last N days.
    max_total: stop after this many emails handled (keeps each run bounded).
    Returns {ok, dry_run, scanned, moved, skipped, failed, capped, items:[{...}], error}.
    """
    mailbox = mailbox or MAILBOX
    summary = {"ok": True, "dry_run": dry_run, "scanned": 0, "moved": 0, "skipped": 0,
               "failed": 0, "capped": False, "items": [], "error": None}
    try:
        token = ds.ms_token()
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Outlook not reachable: {str(e)[:160]}")
        return summary

    try:
        msgs = ds.list_folder_messages_full(mailbox, INBOX_ID, limit=max(max_total or 40, 40),
                                            token=token, since_days=since_days)
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Couldn't read the inbox: {str(e)[:160]}")
        return summary

    handled = 0
    for m in msgs:
        if max_total and handled >= max_total:
            summary["capped"] = True
            break
        _handle_message(mailbox, m, dry_run, summary, token)
        handled += 1
    return summary


def _handle_message(mailbox, msg, dry_run, summary, token):
    """Classify + file one email. Never raises — records the outcome and moves on."""
    iid = msg["internet_id"]
    # De-dup: already triaged (and moved)?
    if not dry_run and supabase_db and supabase_db.email_triage_seen(iid):
        summary["skipped"] += 1
        return
    summary["scanned"] += 1
    rec = {"subject": msg.get("subject"), "sender": msg.get("from")}
    try:
        c = ds.classify_email(msg.get("subject", ""), msg.get("from", ""), msg.get("body", ""))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"couldn't classify: {str(e)[:120]}")
        _finish(iid, "failed", rec, summary, dry_run)
        return
    cat, owner = c["category"], c["thread_owner"]
    rec.update(category=cat, owner=owner)
    rec["folder"] = ("supplier reply → " + owner) if _dest_id(cat, owner) in OWNER_FOLDER.values() \
        else cat

    dest_id = _dest_id(cat, owner)
    if not dest_id:
        # No mapped folder (shouldn't happen — every category is mapped) — leave it, log it.
        rec.update(status="failed", detail=f"no folder mapped for {cat}")
        _finish(iid, "failed", rec, summary, dry_run)
        return

    if dry_run:
        rec["status"] = "would_move"
        summary["moved"] += 1
        summary["items"].append(rec)
        return

    try:
        ds.move_message_to_folder(mailbox, msg["id"], dest_id, token=token)
        rec.update(status="moved", detail=f"filed as {cat}"
                   + (f" ({owner})" if owner in OWNER_FOLDER else ""))
        _finish(iid, "moved", rec, summary, dry_run)
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"move failed: {str(e)[:120]}")
        _finish(iid, "failed", rec, summary, dry_run)


def _meta(rec):
    return {"subject": rec.get("subject"), "sender": rec.get("sender"),
            "category": rec.get("category"), "owner": rec.get("owner"),
            "folder": rec.get("folder")}


def _finish(iid, status, rec, summary, dry_run):
    summary["items"].append(rec)
    if status == "moved":
        summary["moved"] += 1
    elif status == "failed":
        summary["failed"] += 1
    if not dry_run and supabase_db:
        supabase_db.email_triage_log(iid, status, detail=rec.get("detail"), **_meta(rec))
