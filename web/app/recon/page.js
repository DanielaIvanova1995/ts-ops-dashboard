"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";
const PIN_STORE = "th_statements_pin";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function round2(n) { return Math.round((Number(n) || 0) * 100) / 100; }

// Overdue = invoice date is 2+ calendar months before this month (Daniela's pay-by-end-of-next-month
// rule). Computed live from the date so it's right even for older saved statements without the flag.
function isOverdue(dateStr) {
  const d = new Date(String(dateStr || "").slice(0, 10));
  if (isNaN(d.getTime())) return false;
  const now = new Date();
  return (now.getFullYear() - d.getFullYear()) * 12 + (now.getMonth() - d.getMonth()) >= 2;
}

function PayPanel({ r, jsonFetch, onNotice, onPaid }) {
  const lines = (r.pay_lines || [])
    .map((l) => ({ ...l, _od: l.overdue || isOverdue(l.inv_date) }))
    .sort((a, b) => {
      if (a._od !== b._od) return a._od ? -1 : 1;                 // overdue first
      return String(a.inv_date || "").localeCompare(String(b.inv_date || ""));  // then oldest
    });
  const overdueCount = lines.filter((l) => l._od).length;
  const [sel, setSel] = useState(() => new Set(lines.map((l) => l.bill_id)));
  const [credits, setCredits] = useState(() => r.credits || []);
  const [credSel, setCredSel] = useState(() => new Set((r.credits || []).map((_, i) => i).filter((i) => !(r.credits[i] || {}).applied)));
  const [ref, setRef] = useState("");
  const [banks, setBanks] = useState([]);
  const [bank, setBank] = useState("");
  const [bankErr, setBankErr] = useState("");
  const [bankLoading, setBankLoading] = useState(false);
  const [remitTo, setRemitTo] = useState("");
  const [paying, setPaying] = useState(false);
  const [remitting, setRemitting] = useState(false);

  useEffect(() => {
    setSel(new Set((r.pay_lines || []).map((l) => l.bill_id)));
    setCredits(r.credits || []);
    // default: select only credits NOT already used on a previous remittance
    setCredSel(new Set((r.credits || []).map((_, i) => i).filter((i) => !(r.credits[i] || {}).applied)));
  }, [r]);
  useEffect(() => {
    const sup = (r.vendor_name || r.supplier || "").split(" ")[0] || "REM";
    const d = new Date();
    const dd = String(d.getDate()).padStart(2, "0") + String(d.getMonth() + 1).padStart(2, "0") + String(d.getFullYear()).slice(-2);
    setRef(`${sup} B${dd}`);
  }, [r]);
  const loadBanks = useCallback(async () => {
    setBankLoading(true); setBankErr("");
    try {
      const res = await jsonFetch("/recon/bank-accounts");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      const accts = d.accounts || [];
      setBanks(accts);
      setBank((b) => b || accts[0]?.id || "");
      if (!accts.length) setBankErr("QuickBooks returned no bank accounts.");
    } catch (e) {
      if (String(e.message) !== "unauthorised") setBankErr("Couldn’t load bank accounts — " + String(e.message || e));
    } finally { setBankLoading(false); }
  }, [jsonFetch]);
  useEffect(() => { loadBanks(); }, [loadBanks]);

  if (!lines.length) return null;
  function toggle(id) { setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  const selLines = lines.filter((l) => sel.has(l.bill_id));
  const invTotal = round2(selLines.reduce((s, l) => s + (Number(l.amt) || 0), 0));
  const selCredits = credits.filter((_, i) => credSel.has(i));
  const creditTotal = round2(selCredits.reduce((s, c) => s + (Number(c.amount) || 0), 0));
  const net = round2(invTotal + creditTotal);
  function toggleCred(i) {
    if ((credits[i] || {}).applied) return;   // already used — must Undo first
    setCredSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  }

  async function markCreditUsed(i) {
    const c = credits[i]; if (!c) return;
    try {
      const res = await jsonFetch("/recon/credit-apply", { method: "POST", body: JSON.stringify({ vendor_id: r.vendor_id, credits: [{ ref: c.ref, amount: c.amount, date: c.date }], remit_ref: "manual" }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        setCredits((cs) => cs.map((x, j) => j === i ? { ...x, applied: true, remit_ref: "manual" } : x));
        setCredSel((s) => { const n = new Set(s); n.delete(i); return n; });
        onNotice({ kind: "ok", text: `Credit ${c.ref || ""} marked used — it won’t be offered again.` });
      } else onNotice({ kind: "warn", text: d.detail || "Couldn’t mark it used." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function undoCredit(i) {
    const c = credits[i]; if (!c) return;
    try {
      const res = await jsonFetch("/recon/credit-unapply", { method: "POST", body: JSON.stringify({ vendor_id: r.vendor_id, credits: [{ ref: c.ref, amount: c.amount, date: c.date }] }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        setCredits((cs) => cs.map((x, j) => j === i ? { ...x, applied: false, applied_at: undefined, remit_ref: undefined } : x));
        setCredSel((s) => { const n = new Set(s); n.add(i); return n; });
        onNotice({ kind: "ok", text: `Credit ${c.ref || ""} put back in play.` });
      } else onNotice({ kind: "warn", text: d.detail || "Couldn’t undo it." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function markPaid() {
    if (!bank) { onNotice({ kind: "warn", text: "Choose a bank account to pay from." }); return; }
    if (!selLines.length) { onNotice({ kind: "warn", text: "Tick at least one invoice." }); return; }
    if (!window.confirm(`Record a £${invTotal.toFixed(2)} bill payment in QuickBooks, settling ${selLines.length} invoice(s), ref ${ref}? This marks them PAID in QuickBooks. You still move the money via the bank separately.`)) return;
    setPaying(true);
    try {
      const res = await jsonFetch("/recon/pay", { method: "POST", body: JSON.stringify({ vendor_id: r.vendor_id, bank_id: bank, ref, lines: selLines.map((l) => ({ bill_id: l.bill_id, amount: l.amt })) }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        const skips = [];
        if (d.skipped_paid) skips.push(`${d.skipped_paid} already paid in QuickBooks`);
        if (d.missing) skips.push(`${d.missing} no longer in QuickBooks`);
        const skipMsg = skips.length ? ` Skipped ${skips.join(" and ")}.` : "";
        const payAmt = round2((Number(d.total != null ? d.total : invTotal) || 0) + creditTotal);
        onNotice({ kind: skips.length ? "warn" : "ok", text: `Marked ${d.paid} paid in QuickBooks (ref ${d.ref}).${skipMsg} Pay £${payAmt.toFixed(2)} by bank.` });
        onPaid(selLines.map((l) => l.inv));
      }
      else onNotice({ kind: "warn", text: d.detail || "Couldn’t mark paid." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setPaying(false); }
  }

  async function draftRemit() {
    if (!selLines.length && !selCredits.length) { onNotice({ kind: "warn", text: "Nothing selected for the remittance." }); return; }
    setRemitting(true);
    try {
      const res = await jsonFetch("/recon/remittance", { method: "POST", body: JSON.stringify({ supplier: r.vendor_name || r.supplier, vendor_id: r.vendor_id || "", ref, to_email: remitTo, total: net, inv_lines: selLines, credits: selCredits }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        try {
          const bin = atob(d.pdf_b64); const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          const url = URL.createObjectURL(new Blob([arr], { type: "application/pdf" }));
          const a = document.createElement("a"); a.href = url; a.download = d.pdf_name; a.click(); URL.revokeObjectURL(url);
        } catch {}
        // Mark the credits just used as applied so they're not offered again, and untick them.
        if (d.credits_applied) {
          const usedKeys = new Set(selCredits.map((c) => `${(c.ref || "").toLowerCase()}|${Math.abs(Number(c.amount) || 0).toFixed(2)}`));
          setCredits((cs) => cs.map((c) => usedKeys.has(`${(c.ref || "").toLowerCase()}|${Math.abs(Number(c.amount) || 0).toFixed(2)}`) ? { ...c, applied: true, remit_ref: ref } : c));
          setCredSel((s) => { const n = new Set(s); credits.forEach((c, i) => { if (usedKeys.has(`${(c.ref || "").toLowerCase()}|${Math.abs(Number(c.amount) || 0).toFixed(2)}`)) n.delete(i); }); return n; });
        }
        const credMsg = d.credits_applied ? ` ${d.credits_applied} credit(s) marked used.` : "";
        onNotice({ kind: "ok", text: (d.draft_link ? `Remittance drafted in Outlook${d.to_email ? ` to ${d.to_email}` : ""} — review & send. PDF downloaded.` : `Remittance PDF downloaded.${remitTo ? " (couldn’t create the Outlook draft — send it manually)" : ""}`) + credMsg });
      } else onNotice({ kind: "warn", text: d.detail || "Couldn’t build the remittance." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setRemitting(false); }
  }

  return (
    <div className="paypanel">
      <div className="tool-label">Pay these — tick invoices, mark paid in QuickBooks, draft the remittance{overdueCount ? <span className="pill red" style={{ marginLeft: 8 }}>{overdueCount} overdue</span> : null}</div>
      <div className="sel-ctl">
        <button type="button" className="btn ghost" onClick={() => setSel(new Set(lines.map((l) => l.bill_id)))}>Select all ({lines.length})</button>
        <button type="button" className="btn ghost" onClick={() => setSel(new Set(lines.filter((l) => l._od).map((l) => l.bill_id)))} disabled={!overdueCount}>Select overdue{overdueCount ? ` (${overdueCount})` : ""}</button>
        <button type="button" className="btn ghost" onClick={() => setSel(new Set())} disabled={!sel.size}>Clear</button>
        <span className="sub" style={{ marginLeft: "auto" }}>{selLines.length} of {lines.length} selected</span>
      </div>
      <table className="mini">
        <thead><tr><th></th><th>Invoice</th><th>Inv date</th><th>Due</th><th className="num">Amount</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.bill_id} className={l._od ? "od" : ""}>
              <td><input type="checkbox" checked={sel.has(l.bill_id)} onChange={() => toggle(l.bill_id)} /></td>
              <td>{l.inv}{l._od ? <span className="pill red" style={{ marginLeft: 6 }}>overdue</span> : null}</td>
              <td className="sub">{l.inv_date || "—"}</td>
              <td className="sub">{l.due_date || "—"}</td>
              <td className="num">{money(l.amt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {credits.length ? (
        <div style={{ marginTop: 10 }}>
          <div className="tool-label">Credit notes — tick the ones to apply</div>
          <table className="mini">
            <thead><tr><th></th><th>Credit</th><th>Date</th><th className="num">Amount</th><th></th></tr></thead>
            <tbody>
              {credits.map((c, i) => (
                <tr key={i} style={c.applied ? { opacity: 0.6 } : undefined}>
                  <td><input type="checkbox" checked={credSel.has(i)} disabled={!!c.applied} onChange={() => toggleCred(i)} /></td>
                  <td>{c.ref || "credit"}</td>
                  <td className="sub">{c.date || "—"}</td>
                  <td className="num">{money(c.amount)}</td>
                  <td>{c.applied
                    ? <span className="sub">already used{c.remit_ref ? ` · ${c.remit_ref}` : ""}{c.applied_at ? ` · ${c.applied_at}` : ""} <button className="linkish" onClick={() => undoCredit(i)} title="Put this credit back in play">undo</button></span>
                    : <button className="linkish" onClick={() => markCreditUsed(i)} title="Mark this credit as already used so it won’t be offered again">mark used</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {creditTotal ? <div className="sub" style={{ marginTop: 4 }}>Selected credits net off: {money(creditTotal)}</div> : null}
        </div>
      ) : null}
      <div className="kv big" style={{ maxWidth: 280 }}><span>Net to pay</span><b>{money(net)}</b></div>
      <div className="pay-ctl">
        <input className="search" style={{ maxWidth: 220, flex: "none" }} value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Reference" />
        <select className="filter" value={bank} onChange={(e) => setBank(e.target.value)}>
          {banks.length ? banks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)
            : <option value="">{bankLoading ? "loading banks…" : "(no bank accounts)"}</option>}
        </select>
        {!banks.length && <button className="btn ghost" onClick={loadBanks} disabled={bankLoading}>{bankLoading ? "…" : "Reload banks"}</button>}
        <button className="btn primary" onClick={markPaid} disabled={paying}>{paying ? "…" : `Mark ${selLines.length} paid in QuickBooks`}</button>
      </div>
      {bankErr ? <div className="route-msg warn" style={{ marginTop: 6 }}>{bankErr} <button className="linkish" onClick={loadBanks}>retry</button></div> : null}
      <div className="pay-ctl">
        <input className="search" style={{ maxWidth: 300, flex: "none" }} value={remitTo} onChange={(e) => setRemitTo(e.target.value)} placeholder="Supplier accounts email (for the remittance)" />
        <button className="btn" onClick={draftRemit} disabled={remitting}>{remitting ? "…" : "Draft remittance"}</button>
      </div>
      <div className="sub" style={{ marginTop: 6 }}>Credit notes aren’t written to QuickBooks (no API) — apply them against the bill in QuickBooks by hand. The remittance is drafted in Outlook for you to review & send.</div>
    </div>
  );
}

function MissingPanel({ r, jsonFetch, onNotice }) {
  // Invoices on the statement that we hold NO record of anywhere — not in QuickBooks AND not on
  // Monday. These are the only ones to ask the supplier to send copies of. An invoice that IS on
  // Monday (has a Monday stage) but not yet in QB just needs approving, so it's excluded here.
  const missing = (r.rows || [])
    .map((raw) => ({
      invoice: raw.invoice || raw.inv || "",
      order: raw.order_no || raw.order || raw.order_ref || "",
      inv_date: raw.inv_date || raw.date || "",
      amount: raw.amount != null ? raw.amount : raw.amt,
      status: raw.status || "",
      monday_status: raw.monday_status || "",
    }))
    .filter((x) => x.status === "missing" && x.invoice && !x.monday_status);
  const [sel, setSel] = useState(() => new Set(missing.map((_, i) => i)));
  const [email, setEmail] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [preview, setPreview] = useState(null);
  useEffect(() => { setSel(new Set(missing.map((_, i) => i))); setPreview(null); }, [r]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!missing.length) return null;
  function toggle(i) { setSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; }); }
  const chosen = missing.filter((_, i) => sel.has(i));
  const total = round2(chosen.reduce((s, x) => s + (Number(x.amount) || 0), 0));

  async function draft() {
    if (!chosen.length) { onNotice({ kind: "warn", text: "Tick at least one invoice to request." }); return; }
    setDrafting(true);
    try {
      const res = await jsonFetch("/recon/query-missing", { method: "POST", body: JSON.stringify({
        supplier: r.vendor_name || r.supplier, to_email: email.trim(), statement_date: r.statement_date || "",
        lines: chosen.map((x) => ({ invoice: x.invoice, inv_date: x.inv_date, amount: x.amount, order: x.order })),
      }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        setPreview(d.body);
        if (d.draft_link) onNotice({ kind: "ok", text: `Drafted in Outlook${d.to_email ? ` to ${d.to_email}` : ""} — review & send it there.` });
        else {
          try { await navigator.clipboard.writeText(`Subject: ${d.subject}\n\n${d.body}`); onNotice({ kind: "ok", text: "Email copied to clipboard — paste into Outlook. (Add a recipient email and re-draft to create it in Outlook automatically.)" }); }
          catch { onNotice({ kind: "ok", text: "Email ready below to copy. (Add a recipient email to draft it in Outlook automatically.)" }); }
        }
      } else onNotice({ kind: "warn", text: d.detail || "Couldn’t draft the email." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setDrafting(false); }
  }

  return (
    <div className="paypanel" style={{ marginTop: 14 }}>
      <div className="tool-label">Not in our records — request copies from {r.vendor_name || r.supplier}’s accounts team <span className="pill red" style={{ marginLeft: 8 }}>{missing.length}</span></div>
      <div className="sel-ctl">
        <button type="button" className="btn ghost" onClick={() => setSel(new Set(missing.map((_, i) => i)))}>Select all ({missing.length})</button>
        <button type="button" className="btn ghost" onClick={() => setSel(new Set())} disabled={!sel.size}>Clear</button>
        <span className="sub" style={{ marginLeft: "auto" }}>{chosen.length} selected · {money(total)}</span>
      </div>
      <table className="mini">
        <thead><tr><th></th><th>Invoice</th><th>Order</th><th>Date</th><th className="num">Amount</th></tr></thead>
        <tbody>
          {missing.map((x, i) => (
            <tr key={i}>
              <td><input type="checkbox" checked={sel.has(i)} onChange={() => toggle(i)} /></td>
              <td>{x.invoice}</td>
              <td className="sub">{x.order || "—"}</td>
              <td className="sub">{x.inv_date || "—"}</td>
              <td className="num">{money(x.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="pay-ctl" style={{ marginTop: 8 }}>
        <input className="search" style={{ maxWidth: 320, flex: "none" }} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Supplier accounts email (to draft the request)" />
        <button className="btn primary" onClick={draft} disabled={drafting}>{drafting ? "…" : `Draft request for ${chosen.length} invoice${chosen.length === 1 ? "" : "s"}`}</button>
      </div>
      <div className="sub" style={{ marginTop: 6 }}>Drafts an email in Outlook (Accounts) asking them to send copies — nothing is sent until you review it. No email to hand? Leave it blank and the request is copied to your clipboard to paste in.</div>
      {preview ? <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12.5, background: "rgba(127,127,127,0.06)", border: "1px solid rgba(127,127,127,0.2)", borderRadius: 8, padding: "10px 12px", fontFamily: "inherit" }}>{preview}</pre> : null}
    </div>
  );
}

function statusPill(s) {
  if (s === "paid") return { cls: "green", label: "Paid" };
  if (s === "ready") return { cls: "amber", label: "Ready to pay" };
  if (s === "missing") return { cls: "red", label: "Not in QuickBooks" };
  return { cls: "grey", label: s || "—" };
}

function AutoReconcilePanel({ jsonFetch, onNotice }) {
  const [status, setStatus] = useState(null);     // { status:{...}, auto_enabled, interval_min, folder }
  const [cov, setCov] = useState(null);           // { saved:[...], suppliers:[...] }
  const [running, setRunning] = useState(false);
  const [showMissing, setShowMissing] = useState(false);

  const loadStatus = useCallback(async () => {
    try { const r = await jsonFetch("/recon/auto-status"); if (r.ok) setStatus(await r.json()); } catch {}
  }, [jsonFetch]);
  const loadCov = useCallback(async () => {
    try { const r = await jsonFetch("/recon/coverage"); if (r.ok) setCov(await r.json()); } catch {}
  }, [jsonFetch]);
  useEffect(() => { loadStatus(); loadCov(); }, [loadStatus, loadCov]);

  // While a run is in progress (this tab, the daily job, or another session), keep refreshing the
  // status every few seconds so the list of reconciled suppliers grows live. A "running" status
  // whose timestamp is >12 min old is treated as a crashed/stale run, not active — stop polling it.
  useEffect(() => {
    const s = status?.status || {};
    const ageMin = s.at ? (Date.now() - new Date(s.at).getTime()) / 60000 : 999;
    if (!(s.running && ageMin < 12)) return;
    const t = setInterval(() => { loadStatus(); }, 3000);
    return () => clearInterval(t);
  }, [status?.status?.running, status?.status?.at, loadStatus]);

  // When a run finishes (running flips off), refresh the saved/coverage list so the new ones show.
  useEffect(() => {
    if (status && status.status && status.status.running === false) loadCov();
  }, [status?.status?.running, loadCov]);

  async function runNow() {
    setRunning(true);
    try {
      const r = await jsonFetch("/recon/auto-run", { method: "POST" });
      const d = await r.json();
      if (!(r.ok && d.started)) { onNotice({ kind: "warn", text: "Couldn’t start the run." }); setRunning(false); return; }
      onNotice({ kind: "ok", text: "Reconciling the whole folder in the background — this can take a few minutes." });
      let tries = 0;
      const poll = async () => {
        tries++;
        try {
          const sr = await jsonFetch("/recon/auto-status"); const sd = await sr.json();
          setStatus(sd);
          if (sd.status?.running && tries < 150) { setTimeout(poll, 4000); return; }
          setRunning(false); loadCov();
          const s = sd.status || {};
          onNotice(s.error
            ? { kind: "warn", text: `Reconcile finished with an error: ${s.error}` }
            : { kind: "ok", text: `Reconcile finished — ${s.reconciled ?? 0} reconciled${s.failed ? `, ${s.failed} failed` : ""}${s.need_vendor ? `, ${s.need_vendor} need a QuickBooks vendor` : ""}${s.skipped ? `, ${s.skipped} already done` : ""}.` });
        } catch { setRunning(false); }
      };
      setTimeout(poll, 3500);
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); setRunning(false); }
  }

  const st = status?.status || {};
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const savedNames = (cov?.saved || []).map((x) => norm(x.supplier)).filter(Boolean);
  const covered = (sup) => {
    const n = norm(sup); if (!n) return false;
    const w = n.slice(0, Math.min(5, n.length));
    return savedNames.some((sn) => sn && (sn.includes(w) || n.includes(sn.slice(0, 5))));
  };
  const missing = (cov?.suppliers || []).filter((s) => !covered(s)).sort((a, b) => String(a).localeCompare(String(b)));
  const stale = (cov?.saved || []).filter((x) => x.stale);

  async function chase(supplier, reason, lastDate) {
    const email = (cov?.emails || {})[norm(supplier)] || "";
    const msg = email
      ? `Draft a statement request to ${supplier} at ${email}?`
      : `Draft a statement request for ${supplier}? No email is on file, so it'll be drafted without a recipient for you to add in Outlook.`;
    if (!window.confirm(msg)) return;
    try {
      const res = await jsonFetch("/recon/chase-statement", { method: "POST", body: JSON.stringify({ supplier, email, reason, last_date: lastDate || "" }) });
      const d = await res.json();
      if (res.ok && d.ok) onNotice({ kind: "ok", text: d.draft_link ? `Statement request drafted to ${d.email || supplier} — review & send in Outlook.` : `Draft prepared${d.email ? "" : " — no email on file, add a recipient in Outlook"}.` });
      else onNotice({ kind: "warn", text: d.detail || "Couldn’t draft it." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  return (
    <div className="card" style={{ padding: "12px 16px", marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 700 }}>Auto-reconcile</div>
        <span className="sub" style={{ flex: 1, minWidth: 180 }}>
          Scans the <b>Statements</b> folder in accounts@, reconciles each, keeps the latest per supplier.
          {status ? <> Runs automatically {status.interval_min >= 1440 ? "once a day" : `every ${Math.round((status.interval_min || 1440) / 60)}h`}{status.auto_enabled === false ? " (off)" : ""}.</> : null}
        </span>
        <button className="btn primary" onClick={runNow} disabled={running}>{running ? "Reconciling…" : "Reconcile all now"}</button>
      </div>
      {(st.at || st.running || running) && (() => {
        const ageMin = st.at ? (Date.now() - new Date(st.at).getTime()) / 60000 : 999;
        const activeRun = running || (st.running && ageMin < 12);
        const stuckRun = st.running && ageMin >= 12 && !running;
        return (
        <div style={{ marginTop: 8 }}>
          <div className="sub">
            {activeRun
              ? <>⏳ Reconciling… <b>{st.done ?? 0}{st.total ? ` of ${st.total}` : ""}</b> done · {st.reconciled ?? 0} reconciled{st.need_vendor ? `, ${st.need_vendor} need a vendor` : ""}{st.failed ? `, ${st.failed} failed` : ""}</>
              : stuckRun
                ? <>⚠ A previous run didn’t finish (it got {st.reconciled ?? 0}). Hit <b>Reconcile all now</b> to restart — the done ones are saved.</>
                : <>Last run {String(st.at || "").slice(0, 16).replace("T", " ")}: <b>{st.reconciled ?? 0}</b> reconciled{st.need_vendor ? `, ${st.need_vendor} need a vendor` : ""}{st.failed ? `, ${st.failed} failed` : ""}{st.skipped ? `, ${st.skipped} already done` : ""}.</>}
          </div>
          {st.error ? <div className="route-msg warn" style={{ marginTop: 6 }}>{st.error}</div> : null}
          {(st.items || []).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {(st.items || []).map((it, i) => (
                <span key={i} className={`pill ${it.status === "reconciled" ? "green" : it.status === "need_vendor" ? "amber" : "red"}`} title={it.detail || ""}>
                  {it.supplier || it.subject || "statement"}
                  {it.status === "reconciled" && it.to_pay ? ` · ${money(it.to_pay)}` : ""}
                  {it.status === "need_vendor" ? " · needs vendor" : it.status !== "reconciled" ? ` · ${it.status || "failed"}` : ""}
                </span>
              ))}
            </div>
          )}
        </div>
        );
      })()}
      {cov && typeof cov.folder_waiting === "number" && cov.folder_waiting > 0 && (
        <div className="route-msg ok" style={{ marginTop: 8 }}>
          📥 <b>{cov.folder_waiting}</b> statement{cov.folder_waiting === 1 ? "" : "s"} waiting in the folder — hit <b>Reconcile all now</b> to process {cov.folder_waiting === 1 ? "it" : "them"}.
        </div>
      )}
      {cov && (
        <div style={{ marginTop: 10 }}>
          <div className="sub">
            <b>{(cov.saved || []).length}</b> supplier{(cov.saved || []).length === 1 ? "" : "s"} reconciled
            {stale.length ? <> · <span className="pill amber">{stale.length} stale (&gt;35 days)</span></> : null}
            {missing.length ? <> · <button className="linkish" onClick={() => setShowMissing(!showMissing)}>{missing.length} with no statement yet {showMissing ? "▾" : "▸"}</button></> : null}
          </div>
          {(cov.saved || []).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {[...(cov.saved || [])].sort((a, b) => String(a.supplier || "").localeCompare(String(b.supplier || ""))).map((s, i) => (
                <span key={i} className={`pill ${s.stale ? "amber" : "green"}`} title={`saved ${s.saved_at || "?"}${s.to_pay ? ` · ${money(s.to_pay)} ready` : ""}`}>{s.supplier}{s.stale ? " ⏱" : ""}</span>
              ))}
            </div>
          )}
          {stale.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div className="sub" style={{ marginBottom: 4 }}>Last statement over 35 days old — chase a fresh one:</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {[...stale].sort((a, b) => String(a.supplier || "").localeCompare(String(b.supplier || ""))).map((s, i) => (
                  <span key={i} className="pill amber">{s.supplier} ⏱<button className="linkish" style={{ marginLeft: 6 }} onClick={() => chase(s.supplier, "stale", s.statement_date || s.saved_at)} title="Draft an email asking for their latest statement">✉ chase</button></span>
                ))}
              </div>
            </div>
          )}
          {showMissing && missing.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="sub" style={{ marginBottom: 4 }}>No statement reconciled yet — chase, or drop one in the folder:</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {missing.map((s, i) => (
                  <span key={i} className="pill grey">{s}<button className="linkish" style={{ marginLeft: 6 }} onClick={() => chase(s, "missing")} title="Draft an email asking for their latest statement">✉ chase</button></span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Recon() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [err, setErr] = useState("");

  const [pin, setPin] = useState("");            // Statements passcode (separate from access code)
  const [needPin, setNeedPin] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [pinErr, setPinErr] = useState("");

  const [qb, setQb] = useState(null);
  const [qbUrl, setQbUrl] = useState("");
  const [supplier, setSupplier] = useState("");
  const [vendors, setVendors] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [openKey, setOpenKey] = useState(null);  // key of the currently-open saved reconciliation
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState(null);
  const [approving, setApproving] = useState({});
  const [saved, setSaved] = useState([]);
  const [excluded, setExcluded] = useState([]);   // never-reconcile skip-list [{vid, name}]
  const [exclPick, setExclPick] = useState("");
  const [exclOpen, setExclOpen] = useState(false); // collapsed by default
  const fileRef = useRef(null);
  const [picked, setPicked] = useState(null);   // the chosen statement file (click or drag-drop)
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    let k = null, p = "";
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    try { p = localStorage.getItem(PIN_STORE) || ""; } catch {}
    if (p) setPin(p);
    if (k) setAccessKey(k);   // optional — kept if present; Statements is gated by the 6-digit passcode only
  }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "",
        "X-TradeHub-Statements-Key": pin || "", ...(opts.headers || {}) },
    });
    // Statements is gated by the 6-digit passcode only, so ANY auth failure (401/403) re-prompts for
    // the passcode — there's no separate access-code screen here. Only show the "didn't work" message
    // when a passcode was actually entered (avoids a scary error on the very first load).
    if (res.status === 401 || res.status === 403) {
      try { localStorage.removeItem(PIN_STORE); } catch {}
      setNeedPin(true); setPinErr(pin ? "That passcode didn’t work — try again." : ""); setPin("");
      throw new Error("locked");
    }
    return res;
  }, [accessKey, pin]);

  // Is the Statements section passcode-protected? If so and we have no PIN yet, prompt for it.
  useEffect(() => {
    fetch(`${API}/recon/lock-status`, { cache: "no-store" })
      .then((r) => r.ok && r.json())
      .then((d) => { if (d && d.locked && !pin) setNeedPin(true); })
      .catch(() => {});
  }, [pin]);

  useEffect(() => {
    if (needPin) return;
    jsonFetch("/recon/status").then((r) => r.ok && r.json()).then((d) => d && setQb(d)).catch(() => {});
    jsonFetch("/recon/vendors").then((r) => r.ok && r.json()).then((d) => d && setVendors(d.vendors || [])).catch(() => {});
  }, [needPin, jsonFetch]);

  // When QuickBooks is disconnected, fetch the connect link so we can show a "Connect" button here.
  useEffect(() => {
    if (qb && qb.qbo_connected === false && !qbUrl && !needPin) {
      jsonFetch("/recon/qbo-connect-url").then((r) => r.ok && r.json()).then((d) => d && d.url && setQbUrl(d.url)).catch(() => {});
    }
  }, [qb, qbUrl, needPin, jsonFetch]);

  const recheckQb = useCallback(() => {
    jsonFetch("/recon/status").then((r) => r.ok && r.json()).then((d) => { if (d) { setQb(d); if (d.qbo_connected) { setNotice({ kind: "ok", text: "QuickBooks connected ✓" }); jsonFetch("/recon/vendors").then((r2) => r2.ok && r2.json()).then((v) => v && setVendors(v.vendors || [])).catch(() => {}); } } }).catch(() => {});
  }, [jsonFetch]);

  const loadSaved = useCallback(() => {
    if (needPin) return;
    jsonFetch("/recon/saved").then((r) => r.ok && r.json()).then((d) => d && setSaved(d.saved || [])).catch(() => {});
  }, [needPin, jsonFetch]);

  const loadExcluded = useCallback(() => {
    if (needPin) return;
    jsonFetch("/recon/coverage").then((r) => r.ok && r.json()).then((d) => d && setExcluded(d.excluded || [])).catch(() => {});
  }, [needPin, jsonFetch]);
  useEffect(() => { loadExcluded(); }, [loadExcluded]);

  async function addExcludePick() {
    const v = vendors.find((x) => String(x.id) === String(exclPick));
    if (!v) return;
    try {
      const res = await jsonFetch("/recon/exclude", { method: "POST", body: JSON.stringify({ vid: String(v.id), supplier: v.name || "" }) });
      const d = await res.json();
      if (res.ok && d.ok) { setExcluded(d.excluded || []); setSaved((xs) => xs.filter((x) => String(x.vid) !== String(v.id))); setExclPick(""); setNotice({ kind: "ok", text: `${v.name} added to the never-reconcile list.` }); }
      else setNotice({ kind: "warn", text: d.detail || "Couldn’t add it." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function removeExclude(vid) {
    try {
      const res = await jsonFetch("/recon/unexclude", { method: "POST", body: JSON.stringify({ vid: String(vid) }) });
      const d = await res.json();
      if (res.ok && d.ok) { setExcluded(d.excluded || []); setNotice({ kind: "ok", text: "Allowed again — it'll reconcile on the next run." }); }
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }
  useEffect(() => { loadSaved(); }, [loadSaved]);

  async function dismissSaved(s) {
    if (!window.confirm(`Remove the saved ${s.supplier} statement from the list? (It won't touch QuickBooks or any payments.)`)) return;
    try {
      const res = await jsonFetch("/recon/dismiss", { method: "POST", body: JSON.stringify({ key: s.key, vid: s.vid }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) { setSaved((xs) => xs.filter((x) => x.key !== s.key)); setNotice({ kind: "ok", text: `Removed ${s.supplier}.` }); }
      else setNotice({ kind: "warn", text: d.detail || "Couldn’t remove it." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function excludeSupplier(vid, supplier) {
    if (!vid) { setNotice({ kind: "warn", text: "No QuickBooks vendor id for this supplier." }); return; }
    if (!window.confirm(`Never auto-reconcile ${supplier || "this supplier"} again? It'll be removed from the list and skipped on future runs. (You can allow it again any time.)`)) return;
    try {
      const res = await jsonFetch("/recon/exclude", { method: "POST", body: JSON.stringify({ vid: String(vid), supplier: supplier || "" }) });
      const d = await res.json();
      if (res.ok && d.ok) { setSaved((xs) => xs.filter((x) => String(x.vid) !== String(vid))); setExcluded(d.excluded || []); setNotice({ kind: "ok", text: `${supplier || "Supplier"} added to the never-reconcile list.` }); }
      else setNotice({ kind: "warn", text: d.detail || "Couldn’t add it." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function openSaved(key, { scroll = true, quiet = false, live = false } = {}) {
    try {
      setOpenKey(key);
      const res = await jsonFetch(`/recon/open?key=${encodeURIComponent(key)}${live ? "&refresh=1" : ""}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setResult(await res.json());
      if (scroll) { try { window.scrollTo(0, 0); } catch {} }
      if (!quiet) setNotice(null);
    } catch (e) {
      if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) });
    }
  }

  // Re-run the live check on the open reconciliation — re-reads QuickBooks so a just-approved invoice
  // flips from "Not in QuickBooks" to ready, and refreshes Monday stage/margin.
  async function refreshResult() {
    const key = openKey || (result && (result.vid || result.vendor_id) ? `v${result.vid || result.vendor_id}` : null);
    if (!key) return;
    setRefreshing(true);
    try { await openSaved(key, { scroll: false, quiet: true, live: true }); loadSaved(); setNotice({ kind: "ok", text: "Refreshed against QuickBooks." }); }
    finally { setRefreshing(false); }
  }

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput(""); setErr("");
  }

  function submitPin(e) {
    e.preventDefault();
    const p = pinInput.trim(); if (!p) return;
    try { localStorage.setItem(PIN_STORE, p); } catch {}
    setPin(p); setNeedPin(false); setPinInput(""); setPinErr("");
  }

  async function reconcile() {
    const f = picked || fileRef.current?.files?.[0];
    if (!f) { setNotice({ kind: "warn", text: "Choose a statement file first." }); return; }
    setBusy(true); setResult(null);
    setNotice({ kind: "ok", text: "Reconciling… big statements (e.g. Travis Perkins) can take a minute — it runs in the background so it won't time out." });
    const authHdr = { "X-TradeHub-Key": accessKey || "", "X-TradeHub-Statements-Key": pin || "" };
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (supplier.trim()) fd.append("supplier", supplier.trim());
      const res = await fetch(`${API}/recon`, { method: "POST", cache: "no-store", headers: authHdr, body: fd });
      if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(PIN_STORE); } catch {} setPin(""); setNeedPin(true); setPinErr("That passcode didn’t work — try again."); return; }
      if (!res.ok) { const ed = await res.json().catch(() => ({})); throw new Error(ed.detail || `API ${res.status}`); }
      const start = await res.json();
      // Older API returned the full result inline — handle that too.
      if (!start.job) {
        if (start.ok === false && start.need_vendor) setNotice({ kind: "warn", text: start.detail || "No QuickBooks vendor match." });
        else { setResult(start); setNotice(null); loadSaved(); }
        return;
      }
      // Poll the background job until it finishes (it also SAVES the result, so even a slow one shows
      // up in the Statements list afterwards).
      const deadline = Date.now() + 5 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2500));
        let sd;
        try {
          const sr = await fetch(`${API}/recon/upload-status?job=${encodeURIComponent(start.job)}`, { cache: "no-store", headers: authHdr });
          if (!sr.ok) continue;
          sd = await sr.json();
        } catch { continue; }
        if (sd && sd.pending === false) {
          const r = sd.result;
          if (r && r.need_vendor) setNotice({ kind: "warn", text: r.detail || "No QuickBooks vendor match." });
          else if (sd.ok === false || sd.error) setNotice({ kind: "warn", text: "Couldn’t reconcile — " + (sd.error || (r && r.detail) || "failed") });
          else if (r) { setResult(r); setNotice(null); loadSaved(); }
          return;
        }
      }
      setNotice({ kind: "warn", text: "Still reconciling — it's taking a while. It saves when done, so check the Statements list in a moment." });
      loadSaved();
    } catch (e) {
      setNotice({ kind: "warn", text: "Couldn’t reconcile — " + String(e.message || e) });
    } finally { setBusy(false); }
  }

  function downloadCsv() {
    if (!result) return;
    const esc = (v) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const header = ["Invoice", "Order", "Inv date", "Amount", "Unpaid", "Due", "Margin %", "Monday stage", "vs QuickBooks"];
    const rows = (result.rows || []).map((raw) => [
      raw.invoice || raw.inv || "",
      raw.order_no || raw.order || raw.order_ref || "",
      raw.inv_date || raw.date || "",
      raw.amount != null ? raw.amount : raw.amt,
      raw.unpaid != null ? raw.unpaid : (raw.balance != null ? raw.balance : raw.amt),
      raw.due_date || raw.stmt_due || "",
      raw.margin == null ? "" : raw.margin,
      raw.monday_status || "",
      statusPill(raw.status).label,
    ]);
    const credits = (result.credits || []).map((c) => ["CN " + (c.ref || ""), "", c.date || "", c.amount, "", "", "", "", "Credit note"]);
    const csv = [header, ...rows, ...credits].map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const sup = (result.vendor_name || result.supplier || "statement").replace(/[^A-Za-z0-9]+/g, "_");
    const stamp = (result.statement_date || "").replace(/[^0-9]/g, "") || "export";
    const a = document.createElement("a");
    a.href = url; a.download = `Reconciliation_${sup}_${stamp}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  async function doApprove(row) {
    const inv = row.invoice;
    if (!window.confirm(`Create a QuickBooks bill for invoice ${inv}? This posts it to QuickBooks.`)) return;
    setApproving((a) => ({ ...a, [inv]: "working" }));
    try {
      const res = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: inv, inv_date: row.inv_date || null }) });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      if (d.ok) {
        setApproving((a) => ({ ...a, [inv]: "done" }));
        setResult((prev) => prev ? { ...prev, rows: (prev.rows || []).map((x) => x.invoice === inv ? { ...x, status: "ready" } : x) } : prev);
        setNotice({ kind: "ok", text: `${inv}: ${d.detail}` });
        loadSaved();
      } else {
        setApproving((a) => ({ ...a, [inv]: "err" }));
        setNotice({ kind: "warn", text: `${inv}: ${d.detail || "couldn’t approve"}` });
      }
    } catch (e) {
      setApproving((a) => ({ ...a, [inv]: "err" }));
      if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) });
    }
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" /><div className="wordmark">Trade<b>Hub</b><span className="sec">Statements</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
          {err && <p className="state err">{err}</p>}
        </div>
      </div>
    );
  }

  if (needPin) {
    return (
      <div className="wrap">
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" /><div className="wordmark">Trade<b>Hub</b><span className="sec">Statements</span></div>
          <p className="sub">🔒 This section is passcode-protected. Enter the Statements passcode.</p>
          <form onSubmit={submitPin} className="loginform">
            <input className="input" type="password" value={pinInput} autoFocus onChange={(e) => setPinInput(e.target.value)} placeholder="Statements passcode" />
            <button className="btn primary" type="submit">Unlock</button>
          </form>
          {pinErr && <p className="state err">{pinErr}</p>}
        </div>
      </div>
    );
  }

  const r = result;
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Statements</div>
        <div className="right">
          <span className="count">{qb ? (qb.qbo_connected ? <>QuickBooks: <b>{qb.company || "connected"}</b></> : "QuickBooks not connected") : ""}</span>
        </div>
      </div>

      {qb && qb.qbo_connected === false && (
        <div className="route-msg warn" style={{ marginBottom: 12 }}>
          <div>⚠ <b>QuickBooks is disconnected</b> — reconciling, the supplier list and approvals all read from it, so they won’t work until it’s reconnected.</div>
          <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {qbUrl
              ? <a className="btn primary" href={qbUrl} target="_blank" rel="noreferrer">Connect QuickBooks</a>
              : <span className="sub">Loading the connect link…</span>}
            <button className="btn" onClick={recheckQb}>I’ve connected — re-check</button>
            <span className="sub">Opens QuickBooks to sign in &amp; approve (read-only). Then come back and hit “re-check”.</span>
          </div>
        </div>
      )}
      {qb && qb.qbo_connected && qb.company && (
        <div className="route-msg ok" style={{ marginBottom: 12 }}>QuickBooks connected — <b>{qb.company}</b>.</div>
      )}

      <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
        <input ref={fileRef} type="file" accept=".pdf,.csv,.txt,.xlsx,.xlsm,.xls" style={{ display: "none" }}
          onChange={(e) => setPicked(e.target.files?.[0] || null)} />
        <div
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); if (!drag) setDrag(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDrag(false); }}
          onDrop={(e) => {
            e.preventDefault(); setDrag(false);
            const f = e.dataTransfer.files?.[0];
            if (f) { setPicked(f); try { fileRef.current.files = e.dataTransfer.files; } catch {} }
          }}
          role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}
          style={{
            border: `2px dashed ${drag ? "#e05a00" : "rgba(127,127,127,0.4)"}`,
            background: drag ? "rgba(224,90,0,0.07)" : "rgba(127,127,127,0.05)",
            borderRadius: 12, padding: "34px 20px", textAlign: "center", cursor: "pointer",
            transition: "border-color .15s ease, background .15s ease",
          }}
        >
          <div style={{ fontSize: 22, lineHeight: 1 }}>{picked ? "📄" : "⬆"}</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginTop: 8 }}>
            {picked ? picked.name : (drag ? "Drop to upload" : "Drop a supplier statement here")}
          </div>
          <div className="sub" style={{ marginTop: 4 }}>
            {picked ? "Click to choose a different file" : "or click to browse — PDF, Excel or CSV"}
          </div>
        </div>
        <div className="recon-upload" style={{ marginTop: 12 }}>
          {vendors.length ? (
            <select className="filter" style={{ maxWidth: 280, flex: "none" }} value={supplier} onChange={(e) => setSupplier(e.target.value)} title="Pick the QuickBooks supplier (or leave on auto-detect)">
              <option value="">Auto-detect supplier from statement</option>
              {vendors.map((v) => <option key={v.id} value={v.name}>{v.name}</option>)}
            </select>
          ) : (
            <input className="search" style={{ maxWidth: 240, flex: "none" }} placeholder="Supplier (optional override)" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          )}
          <button className="btn primary" onClick={reconcile} disabled={busy}>{busy ? "Reconciling…" : "Reconcile"}</button>
        </div>
        <div className="sub" style={{ marginTop: 8 }}>It’s parsed and matched against QuickBooks — read-only for now (no payments).</div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 10 }}>{notice.text}</div>}
      </div>

      {!needPin && <AutoReconcilePanel jsonFetch={jsonFetch} onNotice={setNotice} />}

      {saved.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="tool-label" style={{ marginBottom: 8 }}>Saved statements</div>
          <div className="saved-list">
            {[...saved].sort((a, b) => String(a.supplier || "").localeCompare(String(b.supplier || ""))).map((s) => (
              <div key={s.key} className={`saved-row${s.settled ? " settled" : ""}`}>
                <div><b>{s.supplier}</b> <span className="sub">{s.statement_date ? `· ${s.statement_date} ` : ""}{s.saved_at ? `· saved ${s.saved_at}` : ""}</span></div>
                <div className="saved-right">
                  {s.settled ? <span className="chip grey">settled ✓</span> : <span className="chip amber"><b>{s.n_pay}</b> ready · {money(s.to_pay)}</span>}
                  {s.n_missing ? <span className="chip red">{s.n_missing} not in QB</span> : null}
                  <button className="btn" onClick={() => openSaved(s.key)}>Open</button>
                  <button className="btn ghost" onClick={() => dismissSaved(s)} title="Remove this saved statement from the list">Remove</button>
                  <button className="btn ghost" onClick={() => excludeSupplier(s.vid, s.supplier)} title="Never auto-reconcile this supplier again (removes it and skips it on future runs)">Don’t reconcile</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
        <button className="linkish" onClick={() => setExclOpen(!exclOpen)} style={{ fontWeight: 600 }}>
          {exclOpen ? "▾" : "▸"} Never reconcile these suppliers{excluded.length ? ` (${excluded.length})` : ""}
        </button>
        {exclOpen && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
              {excluded.length === 0 && <span className="sub">None — the sweep reconciles every supplier in the folder.</span>}
              {[...excluded].sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""))).map((e) => (
                <span key={e.vid} className="pill grey">{e.name || `vendor ${e.vid}`}
                  <button className="linkish" style={{ marginLeft: 6 }} onClick={() => removeExclude(e.vid)} title="Allow this supplier to reconcile again">allow</button>
                </span>
              ))}
            </div>
            <div className="recon-upload" style={{ marginTop: 10 }}>
              <select className="filter" style={{ maxWidth: 280, flex: "none" }} value={exclPick} onChange={(e) => setExclPick(e.target.value)} title="Pick a QuickBooks supplier to never auto-reconcile">
                <option value="">Add a supplier to skip…</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
              <button className="btn" onClick={addExcludePick} disabled={!exclPick}>Add to skip-list</button>
            </div>
            <div className="sub" style={{ marginTop: 6 }}>Skipped suppliers aren’t reconciled by the daily run or “Reconcile all now”, and their statements are archived out of the folder.</div>
          </div>
        )}
      </div>

      {r && (
        <div className="card">
          <div className="recon-head">
            <div>
              <div className="dh-ono">{r.vendor_name || r.supplier}</div>
              <div className="sub">{r.statement_date ? `Statement ${r.statement_date}` : ""}{r.filename ? ` · ${r.filename}` : ""}</div>
            </div>
            <div className="recon-chips">
              <span className="chip amber"><b>{r.n_pay}</b> ready · {money(r.to_pay)}</span>
              {r.n_missing ? <span className="chip red"><b>{r.n_missing}</b> not in QB</span> : null}
              {r.n_paid ? <span className="chip green"><b>{r.n_paid}</b> paid</span> : null}
              <span className="chip grey">Statement {money(r.stmt_total)}</span>
              <button className="btn ghost" onClick={refreshResult} disabled={refreshing} title="Re-check against QuickBooks — picks up invoices you've just approved">{refreshing ? "Refreshing…" : "↻ Refresh"}</button>
              <button className="btn ghost" onClick={downloadCsv} title="Download the whole reconciliation as a CSV">⬇ CSV</button>
              <button className="btn ghost" onClick={() => { setResult(null); setOpenKey(null); }} title="Close this reconciliation">✕ Close</button>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr>
              <th>Invoice</th><th>Order</th><th>Inv date</th><th className="num">Amount</th>
              <th className="num">Unpaid</th><th>Due</th><th className="num">Margin</th>
              <th>Monday stage</th><th>vs QuickBooks</th><th></th>
            </tr></thead>
            <tbody>
              {(r.rows || []).map((raw, i) => {
                // Tolerate older saved snapshots whose rows used legacy keys (inv/amt/date).
                const row = raw.invoice ? raw : {
                  ...raw,
                  invoice: raw.invoice || raw.inv || "",
                  order: raw.order || raw.order_ref || "",
                  inv_date: raw.inv_date || raw.date || "",
                  amount: raw.amount != null ? raw.amount : raw.amt,
                  unpaid: raw.unpaid != null ? raw.unpaid : (raw.balance != null ? raw.balance : raw.amt),
                  due_date: raw.due_date || raw.stmt_due || "",
                };
                const p = statusPill(row.status);
                const st = approving[row.invoice];
                const canApprove = row.status === "missing" && !!row.monday_status && st !== "done";
                const mClass = row.margin == null ? "" : row.margin < 8 ? "mred" : row.margin < 15 ? "mamber" : "mgreen";
                const overdue = row.overdue || isOverdue(row.inv_date);
                return (
                  <tr key={i} className={overdue ? "od" : ""}>
                    <td className="ono">{row.invoice}{overdue ? <span className="pill red" style={{ marginLeft: 6 }}>overdue</span> : null}</td>
                    <td>{row.order_no || row.order || "—"}{row.is_split ? <span className="pill grey" style={{ marginLeft: 6 }}>split</span> : null}</td>
                    <td className="sub">{row.inv_date || "—"}</td>
                    <td className="num">{money(row.amount)}</td>
                    <td className="num">{money(row.unpaid)}</td>
                    <td className="sub">{row.due_date || "—"}</td>
                    <td className={`num ${mClass}`}>{row.margin == null ? "—" : `${row.margin}%`}</td>
                    <td className="sub">{row.monday_status || "—"}</td>
                    <td><span className={`pill ${p.cls}`}>{p.label}</span>{row.paid_ref ? <span className="sub"> {row.paid_ref}</span> : null}</td>
                    <td>
                      {st === "done" ? <span className="pill green">approved ✓</span>
                        : canApprove ? <button className="btn" onClick={() => doApprove(row)} disabled={st === "working"}>{st === "working" ? "…" : "Approve → QB"}</button>
                          : null}
                    </td>
                  </tr>
                );
              })}
              {(!r.rows || !r.rows.length) && <tr><td colSpan={10}><div className="state">No invoice lines found on the statement.</div></td></tr>}
            </tbody>
          </table>
          </div>
          {r.credits?.length ? (
            <div className="totals" style={{ display: "block" }}>
              <b>Credit notes:</b> {r.credits.map((c, i) => <span key={i} className="sub"> {c.ref || "credit"} {money(c.amount)}{i < r.credits.length - 1 ? " ·" : ""}</span>)}
            </div>
          ) : null}
          <MissingPanel r={r} jsonFetch={jsonFetch} onNotice={setNotice} />
          <PayPanel r={r} jsonFetch={jsonFetch} onNotice={setNotice}
            onPaid={(invs) => { setResult((prev) => prev ? { ...prev, rows: (prev.rows || []).map((x) => invs.includes(x.invoice) ? { ...x, status: "paid" } : x), pay_lines: (prev.pay_lines || []).filter((l) => !invs.includes(l.inv)) } : prev); loadSaved(); }} />
        </div>
      )}
    </div>
  );
}
