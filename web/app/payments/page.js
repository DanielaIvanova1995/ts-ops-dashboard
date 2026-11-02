"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}

// Pull the £ amount out of a payment's detail text ("N invoice(s) · £X · inv1, inv2…") for the total,
// and the invoice list (the bit after the amount) for display.
function parseDetail(detail) {
  const d = String(detail || "");
  let amount = null;
  const m = /£\s*([\d,]+(?:\.\d+)?)/.exec(d);
  if (m) { const n = parseFloat(m[1].replace(/,/g, "")); if (Number.isFinite(n)) amount = n; }
  const parts = d.split("·").map((s) => s.trim()).filter(Boolean);
  const count = parts[0] || "";                    // "N invoice(s)"
  const invoices = parts.slice(2).join(" · ");      // the invoice numbers, if recorded
  return { amount, count, invoices };
}

export default function Payments() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");

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
      const res = await jsonFetch("/recon/payments");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setRows(d.payments || []); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch]);
  useEffect(() => { if (accessKey) load(); }, [accessKey, load]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" /><div className="wordmark">Trade<b>Hub</b><span className="sec">Payments</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
        </div>
      </div>
    );
  }

  const enriched = rows.map((p) => ({ ...p, ...parseDetail(p.detail) }));
  const shown = q
    ? enriched.filter((p) => `${p.supplier || ""} ${p.detail || ""} ${p.ref || ""}`.toLowerCase().includes(q.toLowerCase()))
    : enriched;
  const total = shown.reduce((a, p) => a + (typeof p.amount === "number" ? p.amount : 0), 0);

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Payments</div>
        <div className="right">
          <span className="count">{status === "ok" ? <><b>{shown.length}</b>{shown.length !== rows.length ? ` / ${rows.length}` : ""} payment{shown.length === 1 ? "" : "s"}</> : status === "loading" ? "Loading…" : ""}</span>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>{status === "loading" ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>

      <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
        <div className="inv-controls" style={{ flexWrap: "wrap", alignItems: "center" }}>
          <input className="search" style={{ maxWidth: 260, flex: "none" }} placeholder="Search supplier / invoice / reference" value={q} onChange={(e) => setQ(e.target.value)} />
          {q && <button className="btn ghost" onClick={() => setQ("")}>Clear</button>}
          <span style={{ flex: 1 }} />
          <span className="pill grey"><b>{shown.length}</b> payment{shown.length === 1 ? "" : "s"}</span>
          <span className="pill green">Total {money(total)}</span>
        </div>
        <div className="sub" style={{ marginTop: 6 }}>Every payment recorded through TradeHub (marked paid in QuickBooks on the Statements page), newest first. Payments made directly in QuickBooks aren’t shown.</div>
      </div>

      {status === "error" && <div className="card"><div className="state err">Couldn’t load payments ({err}).</div></div>}
      {status === "ok" && rows.length === 0 && <div className="card"><div className="state">No payments recorded yet.</div></div>}
      {status === "ok" && rows.length > 0 && shown.length === 0 && <div className="card"><div className="state">No payments match “{q}”.</div></div>}

      {shown.length > 0 && (
        <div className="card" style={{ padding: "6px 10px" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="mini">
              <thead><tr><th>Date</th><th>Supplier</th><th className="num">Amount</th><th>Invoices</th><th>Reference</th></tr></thead>
              <tbody>
                {shown.map((p, i) => (
                  <tr key={i}>
                    <td className="sub" style={{ whiteSpace: "nowrap" }}>{(p.at || "").slice(0, 16).replace("T", " ") || "—"}</td>
                    <td><b>{p.supplier || "—"}</b></td>
                    <td className="num">{p.amount != null ? money(p.amount) : "—"}</td>
                    <td className="sub">{p.count ? <>{p.count}{p.invoices ? <> · {p.invoices}</> : null}</> : (p.detail || "—")}</td>
                    <td className="sub">{p.ref || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
