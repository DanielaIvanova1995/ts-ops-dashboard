"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
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

  const [qb, setQb] = useState(null);
  const [supplier, setSupplier] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState(null);
  const [approving, setApproving] = useState({});
  const [saved, setSaved] = useState([]);
  const fileRef = useRef(null);

  useEffect(() => {
    let k = null;
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    if (k) setAccessKey(k); else setNeedKey(true);
  }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) },
    });
    if (res.status === 401) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    return res;
  }, [accessKey]);

  useEffect(() => {
    if (!accessKey) return;
    jsonFetch("/recon/status").then((r) => r.ok && r.json()).then((d) => d && setQb(d)).catch(() => {});
  }, [accessKey, jsonFetch]);

  const loadSaved = useCallback(() => {
    if (!accessKey) return;
    jsonFetch("/recon/saved").then((r) => r.ok && r.json()).then((d) => d && setSaved(d.saved || [])).catch(() => {});
  }, [accessKey, jsonFetch]);
  useEffect(() => { loadSaved(); }, [loadSaved]);

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

  async function reconcile() {
    const f = fileRef.current?.files?.[0];
    if (!f) { setNotice({ kind: "warn", text: "Choose a statement file first." }); return; }
    setBusy(true); setNotice(null); setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (supplier.trim()) fd.append("supplier", supplier.trim());
      const res = await fetch(`${API}/recon`, { method: "POST", cache: "no-store", headers: { "X-TradeHub-Key": accessKey || "" }, body: fd });
      if (res.status === 401) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); return; }
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
        setResult((prev) => prev ? { ...prev, rows: prev.rows.map((x) => x.invoice === inv ? { ...x, status: "ready" } : x) } : prev);
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
          <div className="wordmark">Trade<b>Hub</b><span className="sec">Statements</span></div>
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
          <input className="search" style={{ maxWidth: 240, flex: "none" }} placeholder="Supplier (optional override)" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          <button className="btn primary" onClick={reconcile} disabled={busy}>{busy ? "Reconciling…" : "Reconcile"}</button>
        </div>
        <div className="sub" style={{ marginTop: 8 }}>Drop a supplier statement (PDF or CSV). It’s parsed and matched against QuickBooks — read-only for now (no payments).</div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 10 }}>{notice.text}</div>}
      </div>

      {saved.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="tool-label" style={{ marginBottom: 8 }}>Saved statements — still to pay</div>
          <div className="saved-list">
            {saved.map((s) => (
              <div key={s.key} className="saved-row">
                <div><b>{s.supplier}</b> <span className="sub">{s.statement_date ? `· ${s.statement_date} ` : ""}{s.saved_at ? `· saved ${s.saved_at}` : ""}</span></div>
                <div className="saved-right">
                  <span className="chip amber"><b>{s.n_pay}</b> ready · {money(s.to_pay)}</span>
                  {s.n_missing ? <span className="chip red">{s.n_missing} not in QB</span> : null}
                  <button className="btn" onClick={() => openSaved(s.key)}>Open</button>
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
              {(r.rows || []).map((row, i) => {
                const p = statusPill(row.status);
                const st = approving[row.invoice];
                const canApprove = row.status === "missing" && !!row.monday_status && st !== "done";
                const mClass = row.margin == null ? "" : row.margin < 8 ? "mred" : row.margin < 15 ? "mamber" : "mgreen";
                return (
                  <tr key={i}>
                    <td className="ono">{row.invoice}{row.overdue ? <span className="pill red" style={{ marginLeft: 6 }}>overdue</span> : null}</td>
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
        </div>
      )}
    </div>
  );
}
