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

  async function doCheck(sub_id) {
    setChecking((c) => ({ ...c, [sub_id]: true }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/check`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      setChecks((c) => ({ ...c, [sub_id]: await res.json() }));
    } catch (e) {
      if (String(e.message) !== "unauthorised") setChecks((c) => ({ ...c, [sub_id]: { ok: false, detail: String(e.message || e) } }));
    } finally { setChecking((c) => ({ ...c, [sub_id]: false })); }
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
                <div>
                  <span className="ono">{iv.invoice_no}</span>
                  <span className="sub"> · {iv.supplier || "—"} · order {iv.order_no || "—"} · {money(iv.total)}</span>
                  {iv.possible_dup ? <span className="pill red" style={{ marginLeft: 8 }}>possible duplicate of {iv.possible_dup}</span> : null}
                  {iv.margin != null ? <span className="pill grey" style={{ marginLeft: 8 }}>margin {iv.margin}%</span> : null}
                </div>
                <div className="inv-right">
                  {al && <span className={`pill ${al.cls}`}>{al.text}</span>}
                  {!iv.has_pdf ? <span className="sub">no PDF</span> :
                    <button className="btn" onClick={() => doCheck(iv.sub_id)} disabled={busy}>{busy ? "Checking…" : r ? "Re-check" : "Check"}</button>}
                </div>
              </div>

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
                  <div className="sub" style={{ marginTop: 6 }}>{r.matched ? "All lines match the order & pricelist." : `${r.n_issues} issue(s) found.`} Approving/pushing to QuickBooks comes in the next build — for now this is the check.</div>
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
