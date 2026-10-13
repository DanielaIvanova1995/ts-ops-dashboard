"use client";

import { Fragment, useCallback, useEffect, useState } from "react";

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
  const [findingPdf, setFindingPdf] = useState({}); // sub_id -> bool
  const [proc, setProc] = useState(null);
  const [notice, setNotice] = useState(null);
  const [floor, setFloor] = useState(10);
  const [ceil, setCeil] = useState(35);
  const [supFilter, setSupFilter] = useState("");
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState("");
  const [onlyDup, setOnlyDup] = useState(false);

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

  const [issues, setIssues] = useState([]);
  const [showIssues, setShowIssues] = useState(false);
  const [suggest, setSuggest] = useState({});   // row index -> { loading, rows }
  async function doSuggest(i, r) {
    setSuggest((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await jsonFetch(`/invoices/suggest-order?total=${encodeURIComponent(r.total)}&supplier=${encodeURIComponent(r.supplier || "")}`);
      const d = await res.json().catch(() => ({ rows: [] }));
      setSuggest((s) => ({ ...s, [i]: { loading: false, rows: d.rows || [] } }));
    } catch (e) {
      if (String(e.message) !== "unauthorised") setSuggest((s) => ({ ...s, [i]: { loading: false, rows: [] } }));
    }
  }
  useEffect(() => {
    if (!accessKey) return;
    jsonFetch("/invoices/import-issues?limit=200").then((r) => r.ok && r.json())
      .then((d) => d && setIssues(d.rows || [])).catch(() => {});
  }, [accessKey, jsonFetch]);

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

  async function doFindPdf(iv) {
    const sub_id = iv.sub_id;
    setFindingPdf((f) => ({ ...f, [sub_id]: true }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/find-pdf`, { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no, supplier: iv.supplier || "" }) });
      const d = await res.json().catch(() => ({ ok: false, detail: `API ${res.status}` }));
      if (res.ok && d.ok && d.attached) {
        setList((l) => l.map((x) => x.sub_id === sub_id ? { ...x, has_pdf: true } : x));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "ok", text: `PDF attached — ${d.detail}. You can Check it now.` } }));
        doCheck(sub_id);
      } else {
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: d.detail || "No PDF found in Outlook." } }));
      }
    } catch (e) {
      if (String(e.message) !== "unauthorised") setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
    } finally { setFindingPdf((f) => ({ ...f, [sub_id]: false })); }
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

  const suppliers = Array.from(new Set(list.map((i) => i.supplier).filter(Boolean))).sort((a, b) => a.localeCompare(b));
  const shown = list.filter((iv) => {
    if (supFilter && (iv.supplier || "") !== supFilter) return false;
    if (onlyDup && !iv.possible_dup) return false;
    if (query) {
      const q = query.toLowerCase();
      if (!`${iv.invoice_no || ""} ${iv.supplier || ""} ${iv.order_no || ""}`.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  if (sortBy === "supplier") shown.sort((a, b) => (a.supplier || "").localeCompare(b.supplier || "") || (a.invoice_no || "").localeCompare(b.invoice_no || ""));
  else if (sortBy === "margin") shown.sort((a, b) => (a.margin == null ? 1e9 : a.margin) - (b.margin == null ? 1e9 : b.margin));
  else if (sortBy === "total") shown.sort((a, b) => (b.total || 0) - (a.total || 0));
  const allShownSelected = shown.length > 0 && shown.every((x) => sel.has(x.sub_id));
  function toggleAllShown() { setSel(allShownSelected ? new Set() : new Set(shown.map((x) => x.sub_id))); }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Invoice Checker</div>
        <div className="right">
          <span className="count">{status === "ok" ? <><b>{shown.length}</b>{shown.length !== list.length ? ` / ${list.length}` : ""} to review</> : status === "loading" ? "Loading…" : ""}</span>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>{status === "loading" ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>

      <div className="card" style={{ padding: "8px 12px", marginBottom: 8 }}>
        <div className="inv-controls">
          <input className="search" style={{ maxWidth: 240, flex: "none" }} placeholder="Search invoice / order / supplier" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="filter" value={supFilter} onChange={(e) => setSupFilter(e.target.value)}>
            <option value="">All suppliers ({suppliers.length})</option>
            {suppliers.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="filter" value={sortBy} onChange={(e) => setSortBy(e.target.value)} title="Sort">
            <option value="">Sort: default</option>
            <option value="margin">Lowest margin first</option>
            <option value="supplier">Supplier</option>
            <option value="total">Highest total first</option>
          </select>
          <label className="inv-set" style={{ cursor: "pointer" }} title="Only possible duplicates"><input type="checkbox" checked={onlyDup} onChange={(e) => setOnlyDup(e.target.checked)} /><span className="sub">dups</span></label>
          {(supFilter || query || sortBy || onlyDup) && <button className="btn ghost" onClick={() => { setSupFilter(""); setQuery(""); setSortBy(""); setOnlyDup(false); }}>Clear</button>}
          <span style={{ flex: 1 }} />
          <span className="inv-set"><span className="sub">Approve</span><input type="number" className="numin" value={floor} onChange={(e) => setFloorP(Number(e.target.value))} title="Auto-approve floor margin %" /><span className="sub">–</span><input type="number" className="numin" value={ceil} onChange={(e) => setCeilP(Number(e.target.value))} title="Flag-above margin %" /><span className="sub">%</span></span>
          {shown.length > 0 && <button className="btn" onClick={toggleAllShown}>{allShownSelected ? "Clear" : "Select all"}</button>}
          {sel.size > 0 && <button className="btn primary" onClick={checkApproveSelected} disabled={proc?.running}>{proc?.running ? `Working ${proc.done}/${proc.total}…` : `Check & approve (${sel.size})`}</button>}
        </div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 8 }}>{notice.text}</div>}
      </div>

      {issues.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="inv-controls">
            <span className="pill red">{issues.length} didn’t import</span>
            <span className="sub">invoices in Outlook that never became a Monday subitem (mostly no matching order)</span>
            <span style={{ flex: 1 }} />
            <button className="btn" onClick={() => setShowIssues((s) => !s)}>{showIssues ? "Hide" : "Show"}</button>
          </div>
          {showIssues && (
            <table className="mini" style={{ marginTop: 8 }}>
              <thead><tr><th>Invoice</th><th>Supplier</th><th>Order/PO</th><th className="num">Total</th><th>Why it didn’t import</th><th></th></tr></thead>
              <tbody>
                {issues.map((r, i) => {
                  const sg = suggest[i];
                  return (
                  <Fragment key={i}>
                  <tr>
                    <td className="ono">{r.invoice_no || "—"}</td>
                    <td className="sub">{r.supplier || "—"}</td>
                    <td className="sub">{r.order_no || "—"}</td>
                    <td className="num">{r.total != null ? money(r.total) : "—"}</td>
                    <td className="sub">{r.detail || "—"}</td>
                    <td>{r.total != null && <button className="btn ghost" onClick={() => doSuggest(i, r)} disabled={sg?.loading}>{sg?.loading ? "…" : "Suggest order"}</button>}</td>
                  </tr>
                  {sg && !sg.loading && (
                    <tr><td colSpan={6} className="sub" style={{ paddingLeft: 18 }}>
                      {sg.rows?.length
                        ? <>Possible match{sg.rows.length > 1 ? "es" : ""}: {sg.rows.map((o, j) => (
                            <span key={j} className="pill grey" style={{ marginRight: 6 }}>
                              order {o.order_no} · {o.matched_on === "cost" ? "cost" : "value"} {money(o.matched_on === "cost" ? o.cost : o.value)}{o.supplier_match ? " · supplier ✓" : (o.supplier ? ` · ${o.supplier}` : "")}
                            </span>))} — assign on Monday, then it imports on the next run.</>
                        : "No live order matched this amount — the order may not be on the board yet."}
                    </td></tr>
                  )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {proc && (
        <div className="proc-panel">
          <div className="proc-head">{proc.running ? <><span className="spinner" />Working {proc.done} of {proc.total}…</> : <>Done {proc.results.length}. <button className="linkish" onClick={() => setProc(null)}>dismiss</button></>}</div>
          {proc.total > 0 && <div className="proc-bar"><span style={{ width: `${Math.round((proc.done / proc.total) * 100)}%` }} /></div>}
          <div className="proc-results">{proc.results.map((x, i) => <div key={i} className={`proc-row ${x.kind}`}><b>{x.inv}</b> {x.text}</div>)}</div>
        </div>
      )}

      {status === "error" && <div className="card"><div className="state err">Couldn’t load invoices ({err}).</div></div>}
      {status === "ok" && list.length === 0 && <div className="card"><div className="state">No invoices in Needs Review. 🎉</div></div>}
      {status === "ok" && list.length > 0 && shown.length === 0 && <div className="card"><div className="state">No invoices match this filter.</div></div>}

      <div className="inv-list">
        {shown.map((iv) => {
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
                  {!iv.has_pdf
                    ? <button className="btn" onClick={() => doFindPdf(iv)} disabled={findingPdf[iv.sub_id]}>{findingPdf[iv.sub_id] ? "Searching…" : "Find PDF in Outlook"}</button>
                    : <button className="btn" onClick={() => doCheck(iv.sub_id)} disabled={busy}>{busy ? "Checking…" : r ? "Re-check" : "Check"}</button>}
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
