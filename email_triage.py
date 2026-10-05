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

# Only ever look at RECENT mail — never reach back into old emails sitting in the Inbox. A run that
# hasn't happened for a while still won't touch anything older than this many days.
DEFAULT_SINCE_DAYS = 7

# The shared inbox that gets triaged, and the exact Inbox folder Make watched (its id).
MAILBOX = "hello@tradesuperstoreonline.co.uk"
INBOX_ID = ("AAMkAGUzYjQwOWIyLWE2NDktNDhhMS04OGRmLWY2NDM3YTRkNzc0MgAuAAAAAADNPrxz3I1jRrPdjo9v"
            "FUNzAQA9StLmUbsCToOil6HnGLWNAAAAAAEMAAA=")

# Destination Outlook folder IDs, copied verbatim from the Make scenario. Category -> folder id.
_F = "AAMkAGUzYjQwOWIyLWE2NDktNDhhMS04OGRmLWY2NDM3YTRkNzc0MgAuAAAAAADNPrxz3I1jRrPdjo9vFUNzAQA9StLmUbsCToOil6HnGLWN"
CATEGORY_FOLDER = {
    "supplier_with_eta":              _F + "AAPQP8E_AAA=",   # Robyn - Supplier ETAs
    "supplier_no_eta":                _F + "AAPQP8E-AAA=",   # Natasha - Supplier - No ETA (default)
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
# Per-owner supplier-reply folders (supplier replies are filed by the thread owner's sign-off).
# Daniela 2026-09-30: each owner now has their OWN "initials - Supplier replies" folder —
# Megan Steer -> MS, Megan Clark -> MC, Robyn Jackson -> RJ. The folders are resolved by NAME at
# run time (and created if missing) rather than hard-coded ids, so TradeHub provisions them itself.
# Melissa and Malyeka have left — the classifier returns "unknown" for their old threads, which
# fall back to the default supplier_no_eta folder (Natasha - Supplier - No ETA).
OWNER_FOLDER_NAMES = {
    "megan_steer": "MS - Supplier replies",
    "megan_clark": "MC - Supplier replies",
    "robyn":       "RJ - Supplier replies",
}


def _resolve_owner_folders(mailbox: str, token, create: bool = True) -> dict:
    """Map each owner -> their supplier-reply folder id, resolving by name (creating missing folders
    on a live run; find-only when create=False, i.e. dry-runs). Lists the folder tree once, then only
    reaches out again for any folder that still needs creating. An owner whose folder can't be
    resolved is simply omitted, so routing safely falls back to the default supplier folder."""
    found: dict[str, str] = {}
    by_name: dict[str, str] = {}
    try:
        for f in ds.list_mail_folders_tree(mailbox, token=token):
            by_name[ds._norm(f["name"])] = f["id"]
    except Exception:  # noqa: BLE001
        by_name = {}
    for owner, name in OWNER_FOLDER_NAMES.items():
        fid = by_name.get(ds._norm(name))
        if not fid and create:
            fid = ds.find_or_create_mail_folder(mailbox, name, token=token, create=True)
        if fid:
            found[owner] = fid
    return found


# "Robyn - Supplier ETAs" folder (= the supplier_with_eta folder). Daniela 2026-09-29: genuine
# supplier DELIVERY NOTES / PODs go here, whatever else the classifier calls them — Robyn handles
# supplier ETAs/deliveries. Everything else in supplier_no_eta still files to Natasha's folder.
ROBYN_ETA_FOLDER = _F + "AAPQP8E_AAA="

# A delivery note / proof-of-delivery, spotted from the subject or sender (the classifier has no
# separate category for these). Kept tight so PO acknowledgements, order confirmations, ETA-chase
# replies and quotes are NOT swept up — only real delivery/POD notifications.
import re as _re  # noqa: E402
_DELIVERY_NOTE_SUBJECT = _re.compile(
    r"\b(deliver(?:y|ed)\s+note|delivery\s+notification|proof\s+of\s+delivery|despatch\s+note|"
    r"dispatch\s+note|goods\s+received\s+note|\bP\.?O\.?D\b)\b", _re.I)
_DELIVERY_NOTE_SENDERS = ("track-pod.com",)


def _is_delivery_note(subject: str, sender: str) -> bool:
    """True if this looks like a genuine supplier delivery note / POD (→ Robyn's folder)."""
    if any(s in (sender or "").lower() for s in _DELIVERY_NOTE_SENDERS):
        return True
    return bool(_DELIVERY_NOTE_SUBJECT.search(subject or ""))


# Auto-archive noise (→ Natasha - Auto-archive = the automated_system folder). Daniela 2026-09-29:
# Rexel ORDER CONFIRMATIONS, and supplier auto-acknowledgements like GAP's "your email has been
# passed to one of the team … within 3 business hours". Rexel confirmations are matched by
# sender+subject; the body phrases must be a true "we got your email, someone will respond"
# auto-responder with NO order content.
# NARROWED 2026-10-05 (Daniela): the old generic footer phrases ("this is an automated message",
# "please do not reply to this email", "do not reply to this message") were archiving GENUINE
# supplier replies — order confirmations, PO replies, ETA/order updates (C TIE SO-confirmations,
# "Re: Purchase Order …", "National Skirting Order … Update", "Re: Order …") — because those carry
# the same auto-footer. Dropped them; only the GAP-style "received your email" acknowledgements
# (which have no order number and need no action) now auto-archive via the body.
_AUTO_ACK_BODY = _re.compile(
    r"(passed to (one of|a member of|our|the)[^.\n]{0,25}team|"
    r"be in contact with you within)", _re.I)


def _is_auto_archive(subject: str, sender: str, body: str = "") -> bool:
    """True if this is automated noise to file straight into Natasha - Auto-archive."""
    s = (sender or "").lower()
    if "rexel" in s and _re.search(r"\border (confirmation|acknowledg\w*)\b", subject or "", _re.I):
        return True
    return bool(_AUTO_ACK_BODY.search(body or ""))


NATASHA_NOETA_FOLDER = _F + "AAPQP8E-AAA="   # Natasha - Supplier - No ETA


# National Skirting order/status NOTIFICATION emails → Robyn's Supplier ETAs folder (Daniela
# 2026-10-05: "all stream-notification-like emails from national skirting should go into Supplier
# ETAs"). They're automated order updates (e.g. "National Skirting Order 122008 Update"), so Robyn
# — who handles supplier ETAs/deliveries — should get them, not Natasha's No-ETA folder.
def _is_national_skirting(subject: str, sender: str) -> bool:
    s = (sender or "").lower()
    return "nationalskirting" in s or "national skirting" in s


def move_delivery_notes(mailbox: str | None = None, src_folder_id: str | None = None,
                        dest_folder_id: str | None = None, dry_run: bool = False,
                        limit: int = 400, token=None) -> dict:
    """One-off backlog cleanup: move genuine delivery-note / POD emails OUT of the Natasha
    Supplier-No-ETA folder INTO Robyn's Supplier ETAs folder. ONLY messages `_is_delivery_note`
    flags are touched — PO acknowledgements, order confirmations, ETA replies, quotes, proformas
    and credits are left exactly where they are. dry_run reports what it WOULD move.
    Returns {ok, scanned, delivery_notes, moved, would_move, failed, items, error}."""
    mailbox = mailbox or MAILBOX
    src = src_folder_id or NATASHA_NOETA_FOLDER
    dest = dest_folder_id or ROBYN_ETA_FOLDER
    out = {"ok": True, "scanned": 0, "delivery_notes": 0, "moved": 0, "would_move": 0,
           "failed": 0, "items": [], "error": None}
    try:
        token = token or ds.ms_token()
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, error=f"Outlook not reachable: {str(e)[:160]}")
        return out
    try:
        msgs = ds.list_folder_messages_full(mailbox, src, limit=limit, token=token)
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, error=f"Couldn't list folder: {str(e)[:160]}")
        return out
    out["scanned"] = len(msgs)
    for m in msgs:
        if not _is_delivery_note(m.get("subject", ""), m.get("from", "")):
            continue
        out["delivery_notes"] += 1
        item = {"subject": m.get("subject"), "sender": m.get("from")}
        if dry_run:
            out["would_move"] += 1
            item["status"] = "would move"
            out["items"].append(item)
            continue
        try:
            ds.move_message_to_folder(mailbox, m["id"], dest, token=token)
            out["moved"] += 1
            item["status"] = "moved"
        except Exception as e:  # noqa: BLE001
            out["failed"] += 1
            item["status"] = f"failed: {str(e)[:80]}"
        out["items"].append(item)
    return out


def _dest_id(category: str, owner: str, subject: str = "", sender: str = "",
             body: str = "", owner_ids: dict | None = None) -> str | None:
    """The destination folder id for a classified email. A genuine delivery note / POD always goes
    to Robyn's Supplier ETAs folder; automated noise (Rexel order confirmations, supplier auto-acks)
    goes to Natasha - Auto-archive. Otherwise: a per-owner folder (MS/MC/RJ) for a supplier reply
    whose owner has one, else the category's folder (exactly as Make decided). `owner_ids` maps
    owner -> resolved folder id (from _resolve_owner_folders)."""
    owner_ids = owner_ids or {}
    if _is_delivery_note(subject, sender) or _is_national_skirting(subject, sender):
        return ROBYN_ETA_FOLDER                          # delivery notes + National Skirting notices
    if _is_auto_archive(subject, sender, body):
        return CATEGORY_FOLDER["automated_system"]      # = Natasha - Auto-archive
    if category == "supplier_no_eta" and owner in owner_ids:
        return owner_ids[owner]
    return CATEGORY_FOLDER.get(category)


def run_triage(dry_run: bool = False, since_days: int | None = None, max_total: int | None = 40,
               mailbox: str | None = None) -> dict:
    """Classify + file new emails in the watched Inbox, exactly as the Make scenario did.

    dry_run: classify + report, but MOVE nothing and mark nothing handled.
    since_days: only look at emails received within the last N days. Defaults to DEFAULT_SINCE_DAYS
        so triage NEVER reaches back into old mail; pass an explicit number to override (0 = today
        only). None means "not specified" → the default is used.
    max_total: stop after this many emails handled (keeps each run bounded).
    Returns {ok, dry_run, scanned, moved, skipped, failed, capped, items:[{...}], error}.
    """
    if since_days is None:
        since_days = DEFAULT_SINCE_DAYS
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

    # Resolve the per-person supplier-reply folders once per run (create them on a live run; just
    # look them up on a dry-run). Missing ones simply fall back to the default supplier folder.
    owner_ids = _resolve_owner_folders(mailbox, token, create=not dry_run)

    handled = 0
    for m in msgs:
        if max_total and handled >= max_total:
            summary["capped"] = True
            break
        _handle_message(mailbox, m, dry_run, summary, token, owner_ids)
        handled += 1
    return summary


def _handle_message(mailbox, msg, dry_run, summary, token, owner_ids=None):
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
    owner_ids = owner_ids or {}
    cat, owner = c["category"], c["thread_owner"]
    rec.update(category=cat, owner=owner)
    subj, sndr, body = msg.get("subject", ""), msg.get("from", ""), msg.get("body", "")
    dest_id = _dest_id(cat, owner, subj, sndr, body, owner_ids)
    if _is_national_skirting(subj, sndr):
        rec["folder"] = "National Skirting notice → Robyn - Supplier ETAs"
    elif _is_delivery_note(subj, sndr):
        rec["folder"] = "delivery note → Robyn - Supplier ETAs"
    elif _is_auto_archive(subj, sndr, body):
        rec["folder"] = "auto-archive → Natasha - Auto-archive"
    elif dest_id in owner_ids.values():
        rec["folder"] = "supplier reply → " + OWNER_FOLDER_NAMES.get(owner, owner)
    else:
        rec["folder"] = cat
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
                   + (f" ({OWNER_FOLDER_NAMES[owner]})" if owner in owner_ids else ""))
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
