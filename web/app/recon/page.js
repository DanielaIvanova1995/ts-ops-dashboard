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
  const [credSel, setCredSel] = useState(() => new Set((r.credits || []).map((_, i) => i)));
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
    setCredSel(new Set((r.credits || []).map((_, i) => i)));   // default: all credits selected
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
  const selCredits = (r.credits || []).filter((_, i) => credSel.has(i));
  const creditTotal = round2(selCredits.reduce((s, c) => s + (Number(c.amount) || 0), 0));
  const net = round2(invTotal + creditTotal);
  function toggleCred(i) { setCredSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; }); }

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
      const res = await jsonFetch("/recon/remittance", { method: "POST", body: JSON.stringify({ supplier: r.vendor_name || r.supplier, ref, to_email: remitTo, total: net, inv_lines: selLines, credits: selCredits }) });
      const d = await res.json();
      if (res.ok && d.ok) {
        try {
          const bin = atob(d.pdf_b64); const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          const url = URL.createObjectURL(new Blob([arr], { type: "application/pdf" }));
          const a = document.createElement("a"); a.href = url; a.download = d.pdf_name; a.click(); URL.revokeObjectURL(url);
        } catch {}
        onNotice({ kind: "ok", text: d.draft_link ? `Remittance drafted in Outlook${d.to_email ? ` to ${d.to_email}` : ""} — review & send. PDF downloaded.` : `Remittance PDF downloaded.${remitTo ? " (couldn’t create the Outlook draft — send it manually)" : ""}` });
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
      {(r.credits || []).length ? (
        <div style={{ marginTop: 10 }}>
          <div className="tool-label">Credit notes — tick the ones to apply</div>
          <table className="mini">
            <thead><tr><th></th><th>Credit</th><th>Date</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {(r.credits || []).map((c, i) => (
                <tr key={i}>
                  <td><input type="checkbox" checked={credSel.has(i)} onChange={() => toggleCred(i)} /></td>
                  <td>{c.ref || "credit"}</td>
                  <td className="sub">{c.date || "—"}</td>
                  <td className="num">{money(c.amount)}</td>
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

function statusPill(s) {
  if (s === "paid") return { cls: "green", label: "Paid" };
  if (s === "ready") return { cls: "amber", label: "Ready to pay" };
  if (s === "missing") return { cls: "red", label: "Not in QuickBooks" };
  return { cls: "grey", label: s || "—" };
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
  const [supplier, setSupplier] = useState("");
  const [vendors, setVendors] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState(null);
  const [approving, setApproving] = useState({});
  const [saved, setSaved] = useState([]);
  const fileRef = useRef(null);

  useEffect(() => {
    let k = null, p = "";
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    try { p = localStorage.getItem(PIN_STORE) || ""; } catch {}
    if (p) setPin(p);
    if (k) setAccessKey(k); else setNeedKey(true);
  }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "",
        "X-TradeHub-Statements-Key": pin || "", ...(opts.headers || {}) },
    });
    if (res.status === 401) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    if (res.status === 403) { try { localStorage.removeItem(PIN_STORE); } catch {} setPin(""); setNeedPin(true); setPinErr("That passcode didn’t work — try again."); throw new Error("locked"); }
    return res;
  }, [accessKey, pin]);

  // Is the Statements section passcode-protected? If so and we have no PIN yet, prompt for it.
  useEffect(() => {
    if (!accessKey) return;
    fetch(`${API}/recon/lock-status`, { cache: "no-store" })
      .then((r) => r.ok && r.json())
      .then((d) => { if (d && d.locked && !pin) setNeedPin(true); })
      .catch(() => {});
  }, [accessKey, pin]);

  useEffect(() => {
    if (!accessKey || needPin) return;
    jsonFetch("/recon/status").then((r) => r.ok && r.json()).then((d) => d && setQb(d)).catch(() => {});
    jsonFetch("/recon/vendors").then((r) => r.ok && r.json()).then((d) => d && setVendors(d.vendors || [])).catch(() => {});
  }, [accessKey, needPin, jsonFetch]);

  const loadSaved = useCallback(() => {
    if (!accessKey) return;
    jsonFetch("/recon/saved").then((r) => r.ok && r.json()).then((d) => d && setSaved(d.saved || [])).catch(() => {});
  }, [accessKey, jsonFetch]);
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

  async function openSaved(key) {
    try {
      const res = await jsonFetch(`/recon/open?key=${encodeURIComponent(key)}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setResult(await res.json());
      try { window.scrollTo(0, 0); } catch {}
    } catch (e) {
      if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) });
    }
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
    const f = fileRef.current?.files?.[0];
    if (!f) { setNotice({ kind: "warn", text: "Choose a statement file first." }); return; }
    setBusy(true); setNotice(null); setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (supplier.trim()) fd.append("supplier", supplier.trim());
      const res = await fetch(`${API}/recon`, { method: "POST", cache: "no-store", headers: { "X-TradeHub-Key": accessKey || "", "X-TradeHub-Statements-Key": pin || "" }, body: fd });
      if (res.status === 401) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); return; }
      if (res.status === 403) { try { localStorage.removeItem(PIN_STORE); } catch {} setPin(""); setNeedPin(true); setPinErr("That passcode didn’t work — try again."); return; }
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      if (d.ok === false && d.need_vendor) { setNotice({ kind: "warn", text: d.detail || "No QuickBooks vendor match." }); }
      else { setResult(d); loadSaved(); }
    } catch (e) {
      setNotice({ kind: "warn", text: "Couldn’t reconcile — " + String(e.message || e) });
    } finally { setBusy(false); }
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

      <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
        <div className="recon-upload">
          <input ref={fileRef} type="file" accept=".pdf,.csv,.txt" className="filepick" />
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
        <div className="sub" style={{ marginTop: 8 }}>Drop a supplier statement (PDF or CSV). It’s parsed and matched against QuickBooks — read-only for now (no payments).</div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 10 }}>{notice.text}</div>}
      </div>

      {saved.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="tool-label" style={{ marginBottom: 8 }}>Saved statements</div>
          <div className="saved-list">
            {saved.map((s) => (
              <div key={s.key} className={`saved-row${s.settled ? " settled" : ""}`}>
                <div><b>{s.supplier}</b> <span className="sub">{s.statement_date ? `· ${s.statement_date} ` : ""}{s.saved_at ? `· saved ${s.saved_at}` : ""}</span></div>
                <div className="saved-right">
                  {s.settled ? <span className="chip grey">settled ✓</span> : <span className="chip amber"><b>{s.n_pay}</b> ready · {money(s.to_pay)}</span>}
                  {s.n_missing ? <span className="chip red">{s.n_missing} not in QB</span> : null}
                  <button className="btn" onClick={() => openSaved(s.key)}>Open</button>
                  <button className="btn ghost" onClick={() => dismissSaved(s)} title="Remove this saved statement from the list">Remove</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
          <PayPanel r={r} jsonFetch={jsonFetch} onNotice={setNotice}
            onPaid={(invs) => { setResult((prev) => prev ? { ...prev, rows: (prev.rows || []).map((x) => invs.includes(x.invoice) ? { ...x, status: "paid" } : x), pay_lines: (prev.pay_lines || []).filter((l) => !invs.includes(l.inv)) } : prev); loadSaved(); }} />
        </div>
      )}
    </div>
  );
}
