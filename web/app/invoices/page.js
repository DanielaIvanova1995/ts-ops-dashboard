"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function actionLabel(a, matched) {
  if (!matched) return { cls: "red", text: "Discrepancy — needs review" };
  if (a === "push") return { cls: "green", text: "Matches — ready to approve" };
  if (a === "hold") return { cls: "amber", text: "Matches — held (margin below floor)" };
  if (a === "flag") return { cls: "amber", text: "Matches — margin high, review" };
  return { cls: "grey", text: "Matches" };
}

export default function Invoices() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [list, setList] = useState([]);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [checks, setChecks] = useState({});     // sub_id -> result
  const [checking, setChecking] = useState({}); // sub_id -> bool
  const [sel, setSel] = useState(() => new Set());
  const [approving, setApproving] = useState({}); // sub_id -> working|done|err
  const [approveMsg, setApproveMsg] = useState({}); // sub_id -> { kind, text }
  const [proc, setProc] = useState(null);
  const [notice, setNotice] = useState(null);
  const [floor, setFloor] = useState(10);
  const [ceil, setCeil] = useState(35);

  useEffect(() => {
    try {
      const f = localStorage.getItem("th_inv_floor"); const c = localStorage.getItem("th_inv_ceil");
      if (f) setFloor(Number(f)); if (c) setCeil(Number(c));
    } catch {}
  }, []);
  function setFloorP(v) { setFloor(v); try { localStorage.setItem("th_inv_floor", String(v)); } catch {} }
  function setCeilP(v) { setCeil(v); try { localStorage.setItem("th_inv_ceil", String(v)); } catch {} }

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

  const load = useCallback(async () => {
    if (!accessKey) return;
    setStatus("loading"); setErr("");
    try {
      const res = await jsonFetch("/invoices");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setList(d.invoices || []); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch]);
  useEffect(() => { if (accessKey) load(); }, [accessKey, load]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  const doCheck = useCallback(async (sub_id) => {
    setChecking((c) => ({ ...c, [sub_id]: true }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/check?lo=${floor}&hi=${ceil}`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setChecks((c) => ({ ...c, [sub_id]: d }));
      return d;
    } catch (e) {
      if (String(e.message) === "unauthorised") return null;
      const d = { ok: false, detail: String(e.message || e) };
      setChecks((c) => ({ ...c, [sub_id]: d }));
      return d;
    } finally { setChecking((c) => ({ ...c, [sub_id]: false })); }
  }, [jsonFetch, floor, ceil]);

  async function doApprove(iv) {
    const sub_id = iv.sub_id;
    if (!window.confirm(`Approve invoice ${iv.invoice_no}? This creates its bill in QuickBooks.`)) return;
    setApproving((a) => ({ ...a, [sub_id]: "working" }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
      const d = await res.json().catch(() => ({ ok: false, detail: `API ${res.status}` }));
      if (res.ok && d.ok) {
        setApproving((a) => ({ ...a, [sub_id]: "done" }));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "ok", text: d.detail || "approved" } }));
        setNotice({ kind: "ok", text: `${iv.invoice_no}: ${d.detail}` });
        setTimeout(() => setList((l) => l.filter((x) => x.sub_id !== sub_id)), 1500);
      } else {
        setApproving((a) => ({ ...a, [sub_id]: "err" }));
        const text = d.detail || "couldn’t approve";
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text } }));
        setNotice({ kind: "warn", text: `${iv.invoice_no}: ${text}` });
      }
    } catch (e) {
      setApproving((a) => ({ ...a, [sub_id]: "err" }));
      if (String(e.message) !== "unauthorised") {
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
        setNotice({ kind: "warn", text: String(e.message || e) });
      }
    }
  }

  function toggleSel(id) { setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  function toggleAll() { setSel((s) => (s.size === list.length ? new Set() : new Set(list.map((x) => x.sub_id)))); }

  async function checkApproveSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    const results = [];
    setProc({ running: true, done: 0, total: ids.length, results: [] });
    for (const sub_id of ids) {
      const iv = list.find((x) => x.sub_id === sub_id);
      let text = "—", kind = "warn";
      if (iv) {
        try {
          const d = checks[sub_id] || await doCheck(sub_id);
          if (d && d.ok) {
            if (!d.matched) text = "discrepancy — left for review";
            else if (d.suggested_action === "push") {
              const ar = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
              const ad = await ar.json();
              if (ar.ok && ad.ok) { text = `approved — ${ad.detail}`; kind = "ok"; setApproving((a) => ({ ...a, [sub_id]: "done" })); }
              else text = `couldn’t approve: ${ad.detail || ""}`;
            } else text = `matches but ${d.suggested_action} — not auto-approved (margin)`;
          } else text = (d && d.detail) || "check failed";
        } catch (e) { if (String(e.message) === "unauthorised") break; text = "error"; }
      }
      results.push({ inv: iv ? iv.invoice_no : sub_id, text, kind });
      setProc({ running: true, done: results.length, total: ids.length, results: [...results] });
    }
    setProc((p) => ({ ...(p || {}), running: false }));
    setSel(new Set());
    const approved = results.filter((r) => r.kind === "ok").map((r) => r.inv);
    if (approved.length) setList((l) => l.filter((x) => !approved.includes(x.invoice_no)));
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <div className="wordmark">Trade<b>Hub</b><span className="sec">Invoices</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Invoice Checker</div>
        <div className="right">
          <span className="count">{status === "ok" ? <><b>{list.length}</b> to review</> : status === "loading" ? "Loading…" : ""}</span>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>{status === "loading" ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>

      <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
        <div className="inv-controls">
          <span className="inv-set"><span className="sub">Approve floor %</span><input type="number" className="numin" value={floor} onChange={(e) => setFloorP(Number(e.target.value))} /></span>
          <span className="inv-set"><span className="sub">Flag above %</span><input type="number" className="numin" value={ceil} onChange={(e) => setCeilP(Number(e.target.value))} /></span>
          <span style={{ flex: 1 }} />
          {list.length > 0 && <button className="btn" onClick={toggleAll}>{sel.size === list.length ? "Clear all" : "Select all"}</button>}
          {sel.size > 0 && <button className="btn primary" onClick={checkApproveSelected} disabled={proc?.running}>{proc?.running ? `Working ${proc.done}/${proc.total}…` : `Check & approve selected (${sel.size})`}</button>}
        </div>
        <div className="sub" style={{ marginTop: 6 }}>Auto-approve pushes to QuickBooks only invoices that <b>fully match</b> and whose order margin is <b>in band</b> (floor–flag). Anything else is left for you to review.</div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 8 }}>{notice.text}</div>}
      </div>

      {proc && (
        <div className="proc-panel">
          <div className="proc-head">{proc.running ? <><span className="spinner" />Working {proc.done} of {proc.total}…</> : <>Done {proc.results.length}. <button className="linkish" onClick={() => setProc(null)}>dismiss</button></>}</div>
          {proc.total > 0 && <div className="proc-bar"><span style={{ width: `${Math.round((proc.done / proc.total) * 100)}%` }} /></div>}
          <div className="proc-results">{proc.results.map((x, i) => <div key={i} className={`proc-row ${x.kind}`}><b>{x.inv}</b> {x.text}</div>)}</div>
        </div>
      )}

      {status === "error" && <div className="card"><div className="state err">Couldn’t load invoices ({err}).</div></div>}
      {status === "ok" && list.length === 0 && <div className="card"><div className="state">No invoices in Needs Review. 🎉</div></div>}

      <div className="inv-list">
        {list.map((iv) => {
          const r = checks[iv.sub_id];
          const busy = checking[iv.sub_id];
          const al = r && r.ok ? actionLabel(r.suggested_action, r.matched) : null;
          return (
            <div className="card inv-card" key={iv.sub_id}>
              <div className="inv-head">
                <label className="inv-chk"><input type="checkbox" checked={sel.has(iv.sub_id)} onChange={() => toggleSel(iv.sub_id)} /></label>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span className="ono">{iv.invoice_no}</span>
                  <span className="sub"> · {iv.supplier || "—"} · order {iv.order_no || "—"} · {money(iv.total)}</span>
                  {iv.possible_dup ? <span className="pill red" style={{ marginLeft: 8 }}>possible duplicate of {iv.possible_dup}</span> : null}
                  {iv.margin != null ? <span className="pill grey" style={{ marginLeft: 8 }}>margin {iv.margin}%</span> : null}
                </div>
                <div className="inv-right">
                  {al && <span className={`pill ${al.cls}`}>{al.text}</span>}
                  {!iv.has_pdf ? <span className="sub">no PDF</span> :
                    <button className="btn" onClick={() => doCheck(iv.sub_id)} disabled={busy}>{busy ? "Checking…" : r ? "Re-check" : "Check"}</button>}
                  {r && r.ok && r.matched && (approving[iv.sub_id] === "done"
                    ? <span className="pill green">approved ✓</span>
                    : <button className="btn primary" onClick={() => doApprove(iv)} disabled={approving[iv.sub_id] === "working"}>{approving[iv.sub_id] === "working" ? "…" : "Approve → QB"}</button>)}
                </div>
              </div>

              {approveMsg[iv.sub_id] && <div className={`route-msg ${approveMsg[iv.sub_id].kind}`} style={{ margin: "0 14px 12px" }}>{approveMsg[iv.sub_id].text}</div>}
              {r && !r.ok && <div className="route-msg warn" style={{ margin: "0 14px 12px" }}>{r.detail || "Couldn’t check this invoice."}</div>}
              {r && r.ok && (
                <div className="inv-body">
                  {r.discrepancy_reason ? <div className="warn-note" style={{ marginBottom: 8 }}><IconWarn /> {r.discrepancy_reason}</div> : null}
                  <table className="mini">
                    <thead><tr><th>SKU</th><th>Description</th><th className="num">Qty</th><th className="num">Unit</th><th>Check</th></tr></thead>
                    <tbody>
                      {(r.lines || []).map((l, i) => {
                        const probs = (l.issues || []).filter((x) => x[0] !== "name");
                        const notes = (l.issues || []).map((x) => x[1]);
                        return (
                          <tr key={i}>
                            <td className="sub">{l.sku || "—"}</td>
                            <td>{l.desc || "—"}{notes.length ? <div className={`sub ${probs.length ? "mred" : ""}`}>{notes.join(" · ")}</div> : null}</td>
                            <td className="num">{l.qty ?? "—"}</td>
                            <td className="num">{l.unit != null ? money(l.unit) : "—"}</td>
                            <td>{probs.length ? <span className="pill red">issue</span> : <span className="pill green">ok</span>}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {r.missing?.length ? <div className="sub" style={{ marginTop: 8 }}>On the order but not invoiced: {r.missing.join(", ")}</div> : null}
                  <div className="sub" style={{ marginTop: 6 }}>{r.matched ? "All lines match the order & pricelist — use Approve → QB to push the bill to QuickBooks." : `${r.n_issues} issue(s) found — resolve on Monday, then re-check.`}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const IconWarn = (p) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>
);
