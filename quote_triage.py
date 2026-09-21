"""Quote-queue triage — sorts the "New Orders & Quotes" folder BY THE ACTION each enquiry needs, so
the quote builder only ever surfaces the ones that are genuinely ready to price.

Flow (per new email in the watched quote folder):
  1. skip if we've already triaged it (de-dup by internetMessageId, in Supabase)
  2. classify it with Claude → one of the action categories
  3. MOVE it to the matching sub-folder (1 - Quote To Price, 2 - Order To Place, …) — resolved by
     NAME, live; 'unsure' (or a missing folder) is LEFT in place, never mis-filed
  4. log the outcome for the history view + de-dup

Same shape as email_triage.py. `dry_run=True` classifies + reports but MOVES nothing. Read/unread
state is preserved (a move doesn't mark read). Off by default; runs in the background worker.
Based on Daniela's tso-outlook-triage-prompt spec (2026-09-21).
"""
from __future__ import annotations

import data_sources as ds

try:
    import supabase_db
except Exception:  # noqa: BLE001
    supabase_db = None

MAILBOX = "hello@tradesuperstoreonline.co.uk"
SOURCE_FOLDER = "New Orders & Quotes"      # the loose quote queue we sort (resolved by name)
DEFAULT_SINCE_DAYS = 30                     # quote queue can hold older items → wider window

# Category → destination folder NAME (resolved live against the mailbox tree). 'unsure' is absent →
# left in place. Supplier quotes are moved OUT of the quote queue to the supplier folder.
CATEGORY_FOLDER = {
    "quote_to_price":   "1 - Quote To Price",
    "order_to_place":   "2 - Order To Place",
    "q_delivery":       "3 - Q Delivery",
    "q_stock":          "4 - Q Stock & Lead Time",
    "q_product":        "5 - Q Product & Spec",
    "website_discount": "6 - Website & Discount Issues",
    "auto_archive":     "Natasha - Auto-archive",
    "supplier_quote":   "Natasha - Supplier No eta",
}


def _resolve(tree, name):
    """Folder object for `name` from the pre-walked tree — exact (normalised) match, else a unique
    'contains' match; None if not found."""
    target = ds._norm(name)
    exact = [f for f in tree if ds._norm(f["name"]) == target]
    if exact:
        return exact[0]
    contains = [f for f in tree if target and target in ds._norm(f["name"])]
    return contains[0] if len(contains) == 1 else None


def run_triage(dry_run: bool = False, since_days: int | None = None, max_total: int | None = 40,
               mailbox: str | None = None) -> dict:
    """Classify + file new emails in the quote queue.
    Returns {ok, dry_run, scanned, moved, left, no_folder, skipped, failed, capped, items, error}."""
    if since_days is None:
        since_days = DEFAULT_SINCE_DAYS
    mailbox = mailbox or MAILBOX
    summary = {"ok": True, "dry_run": dry_run, "scanned": 0, "moved": 0, "left": 0,
               "no_folder": 0, "skipped": 0, "failed": 0, "capped": False, "items": [], "error": None}
    try:
        token = ds.ms_token()
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Outlook not reachable: {str(e)[:160]}")
        return summary
    try:
        tree = ds.list_mail_folders_tree(mailbox, token=token)
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Couldn't list mail folders: {str(e)[:160]}")
        return summary

    src = _resolve(tree, SOURCE_FOLDER)
    if not src:
        summary.update(ok=False, error=f"Quote folder '{SOURCE_FOLDER}' not found.")
        return summary
    # Pre-resolve destination folder ids (by name) once.
    dest_id = {}
    for cat, fname in CATEGORY_FOLDER.items():
        f = _resolve(tree, fname)
        if f:
            dest_id[cat] = (f["id"], f["name"])

    try:
        msgs = ds.list_folder_messages_full(mailbox, src["id"], limit=max(max_total or 40, 40),
                                            token=token, since_days=since_days)
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Couldn't read the quote folder: {str(e)[:160]}")
        return summary

    handled = 0
    for m in msgs:
        if max_total and handled >= max_total:
            summary["capped"] = True
            break
        _handle_message(mailbox, m, dry_run, summary, token, dest_id)
        handled += 1
    return summary


def _handle_message(mailbox, msg, dry_run, summary, token, dest_id):
    iid = msg["internet_id"]
    if not dry_run and supabase_db and supabase_db.quote_triage_seen(iid):
        summary["skipped"] += 1
        return
    summary["scanned"] += 1
    rec = {"subject": msg.get("subject"), "sender": msg.get("from")}
    try:
        c = ds.classify_quote_email(msg.get("subject", ""), msg.get("from", ""), msg.get("body", ""))
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"couldn't classify: {str(e)[:120]}")
        _finish(iid, "failed", rec, summary, dry_run)
        return
    cat = c["category"]
    rec["category"] = cat

    # 'unsure' → leave it where it is (never mis-file). No mapped folder → also leave + note.
    if cat == "unsure" or cat not in CATEGORY_FOLDER:
        rec.update(status="left", folder="(left in queue)", detail="unsure — left in the queue")
        summary["left"] += 1
        summary["items"].append(rec)
        if not dry_run and supabase_db:
            supabase_db.quote_triage_log(iid, "left", detail=rec["detail"], **_meta(rec))
        return

    did = dest_id.get(cat)
    if not did:
        rec.update(status="no_folder", folder=CATEGORY_FOLDER[cat],
                   detail=f"folder '{CATEGORY_FOLDER[cat]}' not found — left in queue")
        summary["no_folder"] += 1
        summary["items"].append(rec)
        if not dry_run and supabase_db:
            supabase_db.quote_triage_log(iid, "no_folder", detail=rec["detail"], **_meta(rec))
        return

    fid, fname = did
    rec["folder"] = fname
    if dry_run:
        rec["status"] = "would_move"
        summary["moved"] += 1
        summary["items"].append(rec)
        return
    try:
        ds.move_message_to_folder(mailbox, msg["id"], fid, token=token)
        rec.update(status="moved", detail=f"→ {fname}")
        _finish(iid, "moved", rec, summary, dry_run)
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"move failed: {str(e)[:120]}")
        _finish(iid, "failed", rec, summary, dry_run)


def _meta(rec):
    return {"subject": rec.get("subject"), "sender": rec.get("sender"),
            "category": rec.get("category"), "folder": rec.get("folder")}


def _finish(iid, status, rec, summary, dry_run):
    summary["items"].append(rec)
    if status == "moved":
        summary["moved"] += 1
    elif status == "failed":
        summary["failed"] += 1
    if not dry_run and supabase_db:
        supabase_db.quote_triage_log(iid, status, detail=rec.get("detail"), **_meta(rec))
