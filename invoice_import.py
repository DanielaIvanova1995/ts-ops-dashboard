"""Native invoice importer — replaces the ~24 Make "Process Invoices & Credit notes - <supplier>"
scenarios with ONE supplier-agnostic job that runs inside TradeHub.

Flow (per new email with a PDF, in the accounts@ mailbox's invoice folders):
  1. skip if we've already handled it (de-dup by internetMessageId, in Supabase)
  2. read the PDF with Claude -> total, invoice number, due date, order (PO) number, doc type
  3. find the order on Monday by number (text_mkv6z0nt)
  4. create the invoice subitem (total -> numbers4, Payment Status -> Needs Review,
     due date -> date0) and attach the PDF (file_mm38gx3j)
  5. log the outcome (imported / failed / skipped) for the on-screen list + de-dup

Safe by design: `dry_run=True` does everything EXCEPT writing to Monday (and doesn't mark the
email handled) — so we can shadow-run alongside Make and eyeball that it matches before cutover.
Every email is handled independently; one bad PDF never stops the batch. De-dup means a re-run
never double-creates. Reuses the same Claude parser + Monday/Outlook plumbing the app already has.
"""
from __future__ import annotations

import base64
import re

import data_sources as ds

try:
    import supabase_db
except Exception:  # noqa: BLE001 — importer still runs without Supabase (Monday dedup is the backstop)
    supabase_db = None

# Where invoices live: every subfolder under Inbox's "Suppliers" folder (Daniela 2026-09-06). When
# no explicit folder list is given, the importer scans ALL of these automatically.
INVOICE_PARENT_FOLDER = "Suppliers"
# Processed emails are always moved here (created if missing) — one fixed archive, no per-run choice.
DEFAULT_ARCHIVE_FOLDER = "Fully Processed - Claude"
# Optional explicit override (folder NAMES). Normally left empty so all Suppliers subfolders scan.
INVOICE_SCAN_FOLDERS: list[str] = []


def _order_no_candidates(po_number: str | None) -> list[str]:
    """Order-number forms to try against Monday, mirroring Make (base = first 5 chars of the PO
    ref). Tries the 5-char base first, then the full reference."""
    raw = (po_number or "").strip()
    if not raw:
        return []
    compact = re.sub(r"\s", "", raw)
    base = compact[:5]
    out = []
    for c in (base, compact, raw):
        if c and c not in out:
            out.append(c)
    return out


def _resolve_folder_ids(folder_names: list[str], mailbox: str, token) -> list[dict]:
    """Map folder NAMES to {id, name} using the mailbox's folder tree (case/space-insensitive)."""
    tree = ds.list_mail_folders_tree(mailbox, token=token)
    by_norm = {}
    for f in tree:
        by_norm.setdefault(ds._norm(f["name"]), f)
    out = []
    for nm in folder_names:
        f = by_norm.get(ds._norm(nm))
        if f:
            out.append({"id": f["id"], "name": f["name"]})
    return out


def _norm_no(s: str) -> str:
    """Normalise an invoice number for duplicate comparison — drop non-alphanumerics, lowercase,
    and strip a leading 'i' before a digit (PJH's 'I11703035' == Monday's '11703035')."""
    n = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    if n[:1] == "i" and n[1:2].isdigit():
        n = n[1:]
    return n


def run_import(folders: list[str] | None = None, dry_run: bool = False,
               limit_per_folder: int = 40, mailbox: str | None = None,
               archive_folder_id: str | None = None, since_days: int | None = None,
               max_total: int | None = None) -> dict:
    """Scan the invoice folders and import each new invoice as a Monday subitem.

    folders: folder NAMES to scan (defaults to all Inbox/Suppliers subfolders).
    dry_run: parse + match + report, but write NOTHING and don't mark anything handled.
    archive_folder_id: if set (and not a dry run), a fully-handled email is MOVED here so the
        invoice folders empty out and it can't be re-read.
    since_days: only look at emails received within the last N days (recent invoices only).
    max_total: stop after this many emails have been handled this run (keeps each run bounded so a
        big backlog is chewed through over several runs instead of one giant, session-freezing pass).
    Returns a summary: {ok, scanned, imported, skipped, failed, archived, capped, items:[{...}]}.
    """
    mailbox = mailbox or ds.INVOICE_IMPORT_MAILBOX
    names = folders if folders is not None else (INVOICE_SCAN_FOLDERS or None)
    summary = {"ok": True, "dry_run": dry_run, "scanned": 0, "imported": 0,
               "skipped": 0, "failed": 0, "ignored": 0, "archived": 0, "capped": False,
               "items": [], "error": None}
    try:
        token = ds.ms_token()
    except Exception as e:  # noqa: BLE001
        summary.update(ok=False, error=f"Outlook not reachable: {str(e)[:160]}")
        return summary

    if names:                                          # explicit folder names given
        folders_resolved = _resolve_folder_ids(names, mailbox, token)
    else:                                              # default: all Inbox/Suppliers subfolders
        try:
            folders_resolved = [{"id": f["id"], "name": f["name"]}
                                for f in ds.list_child_folders(mailbox, INVOICE_PARENT_FOLDER, token)]
        except Exception as e:  # noqa: BLE001
            summary.update(ok=False, error=f"Couldn't list Suppliers folders: {str(e)[:160]}")
            return summary
    if not folders_resolved:
        summary.update(ok=False,
                       error=f"No invoice folders found (looked under '{INVOICE_PARENT_FOLDER}').")
        return summary

    # Resolve the fixed archive folder for live runs (create it if it doesn't exist).
    if not dry_run and not archive_folder_id:
        try:
            archive_folder_id = ds.find_or_create_mail_folder(mailbox, DEFAULT_ARCHIVE_FOLDER, token)
        except Exception:  # noqa: BLE001
            archive_folder_id = None

    handled = 0
    for fol in folders_resolved:
        if max_total and handled >= max_total:
            summary["capped"] = True
            break
        try:
            msgs = ds.list_folder_invoice_messages(mailbox, fol["id"], limit=limit_per_folder,
                                                   token=token, since_days=since_days)
        except Exception as e:  # noqa: BLE001
            summary["items"].append({"folder": fol["name"], "status": "folder_error",
                                     "detail": str(e)[:160]})
            continue
        for m in msgs:
            if max_total and handled >= max_total:
                summary["capped"] = True
                break
            _handle_message(mailbox, m, fol["name"], dry_run, summary, token, archive_folder_id)
            handled += 1
    return summary


def _handle_message(mailbox, msg, folder_name, dry_run, summary, token, archive_folder_id=None):
    """Process one email: may hold more than one invoice PDF (each handled separately)."""
    try:
        pdfs = ds.fetch_message_pdf_attachments(mailbox, msg["id"], token=token, max_items=6)
    except Exception as e:  # noqa: BLE001
        summary["failed"] += 1
        summary["items"].append({"folder": folder_name, "subject": msg.get("subject"),
                                 "status": "failed", "detail": f"couldn't read attachments: {e}"})
        return
    if not pdfs:
        return  # nothing to import (email without a PDF)

    all_clear = True   # every PDF imported or safely skipped → the email can be archived
    for i, a in enumerate(pdfs):
        outcome = _handle_pdf(mailbox, msg, folder_name, a, i, len(pdfs), dry_run, summary, token)
        if outcome not in ("imported", "skipped"):
            all_clear = False

    # Archive the email once everything on it is handled (live runs only).
    if archive_folder_id and not dry_run and all_clear:
        try:
            ds.move_message_to_folder(mailbox, msg["id"], archive_folder_id, token=token)
            summary["archived"] += 1
        except Exception:  # noqa: BLE001 — archiving is a convenience; dedup already protects us
            pass


def _handle_pdf(mailbox, msg, folder_name, a, i, n_pdfs, dry_run, summary, token):
    """Handle one invoice PDF. Returns the outcome string (imported/skipped/failed/would_import)."""
    key = f"{msg['internet_id']}#{i}" if n_pdfs > 1 else msg["internet_id"]
    # De-dup #1: this exact email already handled?
    if not dry_run and supabase_db and supabase_db.invoice_import_seen(key):
        summary["skipped"] += 1
        return "skipped"
    summary["scanned"] += 1
    rec = {"folder": folder_name, "subject": msg.get("subject"), "from": msg.get("from"),
           "file": a.get("name")}
    try:
        parsed = ds.parse_invoice_header(base64.b64encode(a["bytes"]).decode())
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"couldn't read the PDF: {str(e)[:120]}")
        _finish(key, "failed", rec, summary, dry_run)
        return "failed"

    inv_no = (parsed.get("invoice_number") or "").strip() or (a.get("name") or "invoice")
    total = parsed.get("total")
    due = parsed.get("due_date")
    inv_date = parsed.get("invoice_date")
    po = parsed.get("po_number")
    doc_type = (parsed.get("document_type") or "").strip().lower()
    rec.update(invoice_no=inv_no, supplier=parsed.get("supplier_name"), total=total,
               doc_type=doc_type)

    # Only invoices and credit notes become subitems. Statements (and anything else — order
    # confirmations, delivery notes) are IGNORED, not failed: logged so they aren't re-read, and
    # left in the folder (not archived) in case they're needed elsewhere.
    if doc_type not in ("invoice", "credit_note"):
        rec.update(status="ignored", detail=f"ignored ({doc_type or 'not an invoice'})")
        summary["ignored"] = summary.get("ignored", 0) + 1
        summary["items"].append(rec)
        if not dry_run and supabase_db:
            supabase_db.invoice_import_log(key, "ignored", invoice_no=inv_no,
                                           supplier=parsed.get("supplier_name"), detail=rec["detail"])
        return "ignored"

    order = None
    for c in _order_no_candidates(po):
        try:
            order = ds.find_order_item_by_number(c, token=None)
        except Exception:  # noqa: BLE001
            order = None
        if order:
            rec["order_no"] = c
            break
    if not order:
        rec.update(status="failed", detail=f"no order on Monday for PO {po!r}")
        _finish(key, "failed", rec, summary, dry_run)
        return "failed"
    rec["order"] = order.get("name")

    # De-dup #2: is this invoice number ALREADY a subitem on the order? (re-sent email / Make copy)
    try:
        existing = {_norm_no(x) for x in ds.order_subitem_invoice_numbers(order["id"])}
    except Exception:  # noqa: BLE001
        existing = set()
    if _norm_no(inv_no) and _norm_no(inv_no) in existing:
        rec.update(status="skipped", detail=f"invoice {inv_no} already on order {rec['order_no']}")
        summary["skipped"] += 1
        summary["items"].append(rec)
        if not dry_run and supabase_db:
            supabase_db.invoice_import_log(key, "skipped", invoice_no=inv_no,
                                           order_no=rec.get("order_no"), detail=rec["detail"])
        return "skipped"

    if dry_run:
        rec["status"] = "would_import"
        summary["items"].append(rec)
        summary["imported"] += 1
        return "would_import"

    # Live: create subitem + attach PDF.
    try:
        sub = ds.create_invoice_subitem(order["id"], inv_no, total, due_date=due,
                                        invoice_date=inv_date)
        sub_id = sub.get("id")
        try:
            attached = ds.add_pdf_to_subitem_file(
                sub_id, a["bytes"], a.get("name") or f"{inv_no}.pdf")
            rec["detail"] = "PDF attached" if attached else "subitem made (PDF unverified)"
        except Exception as e:  # noqa: BLE001
            rec["detail"] = f"subitem made but PDF attach failed: {str(e)[:100]}"
        rec.update(status="imported", subitem_id=sub_id)
        _finish(key, "imported", rec, summary, dry_run)
        return "imported"
    except Exception as e:  # noqa: BLE001
        rec.update(status="failed", detail=f"couldn't create subitem: {str(e)[:120]}")
        _finish(key, "failed", rec, summary, dry_run)
        return "failed"


def _finish(key, status, rec, summary, dry_run):
    summary["items"].append(rec)
    if status == "imported":
        summary["imported"] += 1
    elif status == "failed":
        summary["failed"] += 1
    if not dry_run and supabase_db:
        supabase_db.invoice_import_log(
            key, status, supplier=rec.get("supplier"), order_no=rec.get("order_no"),
            invoice_no=rec.get("invoice_no"), subitem_id=rec.get("subitem_id"),
            total=rec.get("total"), detail=rec.get("detail"))
