"""Hands-off statement reconciliation.

`reconcile_bytes(...)` runs the full statement reconcile for ONE statement — resolve the QuickBooks
vendor, fetch its bills + payments, `recon_core.reconcile`, enrich each row with its Monday stage /
order / margin, annotate already-used credit notes — and optionally saves the per-vendor snapshot.
It reuses the API's Monday enrichment and the shared `recon_core`, so a background run reconciles
IDENTICALLY to a manual drop on the Statements page.

`run_auto(...)` scans an Outlook folder in accounts@ for statement PDFs, reconciles each, saves the
latest snapshot per vendor (`ds.recon_save` keeps exactly one per vendor — newest replaces), then
archives the processed email. The scheduler runs this a few times a day so every supplier's latest
statement is already reconciled and waiting in the Statements "saved" list before payments are due —
no waiting for a slow parse at the moment she needs it.
"""
from __future__ import annotations

import datetime as _dt
import importlib

import data_sources as ds
import recon_core

try:
    import supabase_db
except Exception:  # noqa: BLE001
    supabase_db = None

STATEMENTS_MAILBOX = "accounts@tradesuperstoreonline.co.uk"  # the permanent home for statements (same mailbox the invoice importer uses). Override via config 'mailbox'.
STATEMENTS_FOLDER = "Statements"              # the Outlook folder she drops statements into
ARCHIVE_FOLDER = "Statements - Reconciled"    # processed statements land here
CONFIG_KEY = "statement_recon"                # {auto_enabled, interval_min, max_total, folder, archive, mailbox}
STATUS_KEY = "statement_recon_status"


def _cfg() -> dict:
    try:
        return (supabase_db.config_get(CONFIG_KEY) if supabase_db else None) or {}
    except Exception:  # noqa: BLE001
        return {}


def _set_status(res: dict, reason: str):
    if not supabase_db:
        return
    try:
        supabase_db.config_set(STATUS_KEY, {
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "reconciled": res.get("reconciled"), "failed": res.get("failed"),
            "need_vendor": res.get("need_vendor"), "skipped": res.get("skipped"),
            "ok": res.get("ok"), "error": res.get("error"),
            "items": (res.get("items") or [])[:40], "reason": reason})
    except Exception:  # noqa: BLE001
        pass


def _parse_stmt_date(s):
    """Best-effort date parse for a statement_date — handles ISO and UK d/m/y. None if unknown."""
    import datetime as _d
    import re as _re
    t = str(s or "").strip()[:10]
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return _d.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    if m:
        try:
            return _d.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _existing_is_newer(vid, new_date) -> bool:
    """True if the vendor's already-saved snapshot has a statement date strictly NEWER than this one
    — so we don't overwrite the latest statement with an older one (both dates must be parseable)."""
    nd = _parse_stmt_date(new_date)
    if not nd:
        return False
    try:
        existing = (ds.recon_load_all() or {}).get(f"v{vid}")
    except Exception:  # noqa: BLE001
        return False
    ed = _parse_stmt_date((existing or {}).get("statement_date"))
    return bool(ed and ed > nd)


def _enrich(invoice_numbers):
    """Reuse the API's Monday enrichment (single source of truth — carries the Carron PSI- /
    digit-core matching). Imported lazily so this module has no load-time dependency on the API."""
    try:
        apimain = importlib.import_module("api.main")
        return apimain._statement_monday_enrich(invoice_numbers)
    except Exception:  # noqa: BLE001
        return {}


def reconcile_bytes(pdf_bytes=None, text=None, filename="", supplier_hint="", do_save=False) -> dict:
    """Reconcile ONE statement (PDF bytes or raw text). Returns the rec dict (same shape as the
    /recon endpoint). do_save=True persists it as this vendor's latest snapshot. On no QuickBooks
    vendor match returns {ok: False, need_vendor: True, ...}."""
    fn = (filename or "").lower()
    if pdf_bytes is not None and fn.endswith((".xlsx", ".xlsm", ".xls")):
        stmt = ds.read_statement_pdf(text=ds.statement_xlsx_to_text(pdf_bytes))
    elif pdf_bytes is not None and fn.endswith((".csv", ".txt")):
        stmt = ds.read_statement_pdf(text=pdf_bytes.decode("utf-8", "ignore"))
    elif pdf_bytes is not None:
        stmt = ds.read_statement_pdf(pdf_bytes=pdf_bytes)
    else:
        stmt = ds.read_statement_pdf(text=text or "")
    sup = (supplier_hint or "").strip() or (stmt.get("supplier") or "")
    vid = vname = None
    try:
        mp = (ds.qbo_vendor_map_load() or {}).get(recon_core.norm_code(sup))
    except Exception:  # noqa: BLE001
        mp = None
    if mp:
        vid, vname = mp.get("id"), mp.get("name")
    if not vid:
        try:
            auto = ds.qbo_find_vendor(sup)
        except Exception:  # noqa: BLE001
            auto = None
        if auto:
            vid, vname = auto.get("id"), auto.get("name")
    if not vid:
        return {"ok": False, "need_vendor": True, "supplier": sup,
                "statement_date": stmt.get("statement_date"), "balance": stmt.get("balance"),
                "filename": filename}
    if vname:
        sup = vname
    bills = ds.qbo_vendor_bills(vid)
    try:
        paymap = ds.qbo_vendor_payments(vid)
    except Exception:  # noqa: BLE001
        paymap = {}
    rec = recon_core.reconcile(stmt, bills, paymap, sup)
    try:
        enrich = _enrich([r.get("invoice") for r in (rec.get("rows") or [])])
        for r in (rec.get("rows") or []):
            e = enrich.get(str(r.get("invoice") or "").strip())
            if e:
                r.update(monday_status=e.get("monday_status"), order_no=e.get("order_no"),
                         is_split=e.get("is_split"), margin=e.get("margin"))
    except Exception:  # noqa: BLE001
        pass
    rec.update(ok=True, supplier=sup, vendor_id=vid, vendor_name=vname,
               statement_date=stmt.get("statement_date"), balance=stmt.get("balance"),
               filename=filename)
    try:
        rec["credits"] = ds.applied_credits_annotate(vid, rec.get("credits") or [])
    except Exception:  # noqa: BLE001
        pass
    # Guard: never overwrite a vendor's snapshot with an EMPTY parse (no rows, no pay lines, no
    # credits) — that's a failed/unreadable statement, and clobbering a good snapshot loses data
    # (how the Travis Perkins .xlsx wiped the Eurocell snapshot when xlsx wasn't yet supported).
    has_content = bool(rec.get("rows") or rec.get("pay_lines") or rec.get("credits"))
    rec["empty"] = not has_content
    if do_save and has_content and _existing_is_newer(vid, rec.get("statement_date")):
        rec["kept_newer_existing"] = True   # a newer statement is already saved for this vendor
        return rec
    if do_save and has_content:
        try:
            snap = dict(rec)
            snap["vid"] = vid
            snap["saved_at"] = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            ds.recon_save(f"v{vid}", snap)
        except Exception:  # noqa: BLE001
            pass
    return rec


def run_auto(folder=None, archive=None, max_total=40, dry_run=False, force=False,
             since_days=None) -> dict:
    """Scan the statements Outlook folder → reconcile each → save latest per vendor → archive. Returns
    a summary {ok, reconciled, failed, need_vendor, skipped, moved, items}. dry_run reconciles and
    reports but writes nothing (no save, no archive). force re-parses even already-seen emails."""
    cfg = _cfg()
    folder = folder or cfg.get("folder") or STATEMENTS_FOLDER
    archive = archive or cfg.get("archive") or ARCHIVE_FOLDER
    mailbox = cfg.get("mailbox") or STATEMENTS_MAILBOX
    res = {"ok": True, "reconciled": 0, "failed": 0, "need_vendor": 0, "skipped": 0,
           "items": [], "folder": folder}
    try:
        fid = ds.find_or_create_mail_folder(mailbox, folder, create=not dry_run)
    except Exception as e:  # noqa: BLE001
        res.update(ok=False, error=f"couldn't open folder {folder!r}: {str(e)[:120]}")
        _set_status(res, "preview" if dry_run else "auto")
        return res
    if not fid:
        res.update(ok=False, error=f"folder {folder!r} not found")
        _set_status(res, "preview" if dry_run else "auto")
        return res
    try:
        msgs = ds.list_folder_invoice_messages(mailbox, fid, limit=max_total, since_days=since_days)
    except Exception as e:  # noqa: BLE001
        res.update(ok=False, error=f"couldn't list {folder!r}: {str(e)[:120]}")
        _set_status(res, "preview" if dry_run else "auto")
        return res
    # Process OLDEST first so that, for a supplier with several statements, the NEWEST is reconciled
    # last and becomes the kept per-vendor snapshot (recon_save replaces by vendor).
    msgs = list(reversed(msgs))
    archive_id = None
    for m in msgs:
        mid = m.get("id")
        iid = m.get("internet_id") or mid
        seen_key = f"stmt:{iid}"
        if not force and supabase_db:
            try:
                if supabase_db.invoice_import_seen(seen_key):
                    res["skipped"] += 1
                    continue
            except Exception:  # noqa: BLE001
                pass
        try:
            pdfs = ds.fetch_message_pdf_attachments(
                mailbox, mid, exts=(".pdf", ".xlsx", ".xlsm", ".xls", ".csv"))
        except Exception as e:  # noqa: BLE001
            res["failed"] += 1
            res["items"].append({"subject": m.get("subject"), "status": "error", "detail": str(e)[:120]})
            continue
        all_ok = bool(pdfs)
        for att in pdfs:
            try:
                rec = reconcile_bytes(pdf_bytes=att.get("bytes"),
                                      filename=att.get("name") or "statement.pdf", do_save=not dry_run)
            except Exception as e:  # noqa: BLE001
                all_ok = False
                res["failed"] += 1
                res["items"].append({"subject": m.get("subject"), "file": att.get("name"),
                                     "status": "error", "detail": str(e)[:120]})
                continue
            if rec.get("ok"):
                res["reconciled"] += 1
                res["items"].append({"supplier": rec.get("vendor_name") or rec.get("supplier"),
                                     "status": "reconciled", "n_pay": rec.get("n_pay"),
                                     "to_pay": rec.get("to_pay"), "n_missing": rec.get("n_missing")})
            elif rec.get("need_vendor"):
                all_ok = False
                res["need_vendor"] += 1
                res["items"].append({"supplier": rec.get("supplier"), "status": "need_vendor",
                                     "detail": "no QuickBooks vendor match — map it, then it retries"})
            else:
                all_ok = False
                res["failed"] += 1
                res["items"].append({"subject": m.get("subject"), "status": "failed",
                                     "detail": "couldn't reconcile"})
        if not dry_run and all_ok:
            # Archive the processed email out of the folder (keeps the queue = what's left to do).
            try:
                if archive_id is None:
                    archive_id = ds.find_or_create_mail_folder(mailbox, archive, create=True)
                moved = bool(archive_id) and ds.move_message_to_folder(mailbox, mid, archive_id)
            except Exception:  # noqa: BLE001
                moved = False
            if not moved and supabase_db:
                # Couldn't archive → mark seen so we don't re-parse it every cycle.
                try:
                    supabase_db.invoice_import_log(seen_key, "reconciled")
                except Exception:  # noqa: BLE001
                    pass
    res["moved"] = res["reconciled"]     # scheduler status reads "moved"
    _set_status(res, "preview" if dry_run else "auto")
    return res
