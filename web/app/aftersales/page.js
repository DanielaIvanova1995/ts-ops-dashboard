"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

// Editable per-supplier aftersales fields (key, label, helper/placeholder).
const SUP_FIELDS = [
  ["return_period", "Return period", "How long do we have to return? e.g. 14 days / 30 days"],
  ["restocking_fee", "Restocking fee", "e.g. 10%, 15%, or none"],
  ["returns_process", "How to raise a return", "RMA / returns request — portal, form, email, phone?"],
  ["returns_carriage", "Return carriage / collection", "Who pays? Cost? Collection vs return-to-base?"],
  ["returns_contact", "Returns / aftersales contact", "Name, email, phone for returns & claims"],
  ["condition", "Condition & non-returnables", "Unopened? Original packaging? What CAN'T be returned (cut lengths, specials, non-stock)"],
  ["damaged_process", "Damaged / short on delivery", "How long to report, photos needed, who to tell"],
  ["faulty_process", "Faulty / warranty", "Warranty length & how to claim"],
  ["lead_time", "Credit / replacement time", "How long for a credit note or replacement"],
  ["notes", "Other notes", "Anything else a new starter should know"],
];

// General training sections (key, title, starter placeholder).
const GEN_SECTIONS = [
  ["overview", "Aftersales — what the role covers", "What aftersales handles day-to-day: returns, damages, shortages, faults, credits, chasing suppliers…"],
  ["raise_return", "How to raise a return (step by step)", "1. Check the return is within the supplier's window…  2. …"],
  ["damaged", "Damaged or short on delivery", "What the customer must send us (photos, timeframe), how we claim from the supplier…"],
  ["missing", "Missing / wrong items", "How to check the order, contact the supplier, arrange a replacement…"],
  ["faulty", "Faulty / warranty claims", "How to assess, what evidence is needed, warranty periods…"],
  ["refunds", "Refunds & credits — how we process them", "When we refund the customer, how we recover the credit from the supplier, Shopify/QuickBooks steps…"],
  ["escalation", "Escalation — when & who", "When to escalate, and who to go to (manager, account manager)…"],
  ["templates", "Useful email templates", "Return request to supplier, apology to customer, chasing a credit…"],
];

function money(v) { const n = Number(v); return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB") : v; }

export default function Aftersales() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [notice, setNotice] = useState(null);
  const [gen, setGen] = useState({});
  const [savingGen, setSavingGen] = useState(false);
  const [sup, setSup] = useState({});                 // supplier name -> {field: value} (edited)
  const [savingSup, setSavingSup] = useState({});
  const [open, setOpen] = useState(() => new Set());  // expanded supplier cards
  const toggle = (name) => setOpen((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; });

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
    if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    return res;
  }, [accessKey]);

  const load = useCallback(async () => {
    if (!accessKey) return;
    setStatus("loading"); setErr("");
    try {
      const res = await jsonFetch("/aftersales");
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      setData(d);
      setGen(d.general || {});
      const s = {};
      (d.suppliers || []).forEach((x) => { s[x.supplier] = { ...(x.fields || {}) }; });
      setSup(s);
      setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch]);
  useEffect(() => { load(); }, [load]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  async function saveGen() {
    setSavingGen(true);
    try {
      const res = await jsonFetch("/aftersales/general", { method: "POST", body: JSON.stringify({ general: gen }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) setNotice({ kind: "ok", text: "Saved the general sections." });
      else setNotice({ kind: "warn", text: d.detail || `Couldn’t save (API ${res.status}).` });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setSavingGen(false); }
  }

  async function saveSup(name) {
    setSavingSup((m) => ({ ...m, [name]: true }));
    try {
      const res = await jsonFetch("/aftersales/supplier", { method: "POST", body: JSON.stringify({ supplier: name, fields: sup[name] || {} }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) setNotice({ kind: "ok", text: `Saved ${name}.` });
      else setNotice({ kind: "warn", text: d.detail || `Couldn’t save (API ${res.status}).` });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setSavingSup((m) => { const n = { ...m }; delete n[name]; return n; }); }
  }

  if (needKey) {
    return (
      <div className="wrap"><div className="login">
        <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" />
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Aftersales</span></div>
        <p className="sub">Enter the access code to continue.</p>
        <form onSubmit={submitKey} className="loginform">
          <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
          <button className="btn primary" type="submit">Enter</button>
        </form>
      </div></div>
    );
  }

  const suppliers = (data?.suppliers || []).filter((s) => {
    const t = q.trim().toLowerCase();
    if (!t) return true;
    return (s.supplier || "").toLowerCase().includes(t) || (s.contacts || []).some((c) => (c.email || "").toLowerCase().includes(t));
  });
  const filled = (name) => SUP_FIELDS.filter(([k]) => (sup[name]?.[k] || "").trim()).length;

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Aftersales</div>
        <div className="right">
          <button className="btn ghost" onClick={() => window.print()} title="Print the whole booklet">🖨 Print</button>
          <button className="btn" onClick={load} disabled={status === "loading"}>{status === "loading" ? "…" : "↻ Refresh"}</button>
        </div>
      </div>

      <div className="route-msg" style={{ marginBottom: 12, background: "rgba(255,106,0,0.08)", border: "1px solid rgba(255,106,0,0.3)" }}>
        <b>Aftersales training booklet.</b> Everything a new aftersales starter needs: how we handle returns, damages and claims, and — for every supplier — their return period, restocking fee and who to contact. <b>Fill in the blanks as you learn them</b> and hit Save; it's shared with the whole team.
      </div>

      {notice && <div className={`route-msg ${notice.kind}`} style={{ marginBottom: 12 }}>{notice.text}</div>}
      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}
      {status === "loading" && !data && <div className="sub">Loading suppliers…</div>}

      {/* General training sections */}
      <div className="card" style={{ padding: "14px 16px", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div className="tool-label" style={{ margin: 0 }}>📘 The basics — how we do aftersales</div>
          <span style={{ flex: 1 }} />
          <button className="btn primary" onClick={saveGen} disabled={savingGen}>{savingGen ? "Saving…" : "Save basics"}</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 12, marginTop: 8 }}>
          {GEN_SECTIONS.map(([k, title, ph]) => (
            <div key={k}>
              <label className="sub" style={{ fontWeight: 600, display: "block", marginBottom: 4 }}>{title}</label>
              <textarea className="input" style={{ width: "100%", minHeight: 80, resize: "vertical", fontFamily: "inherit", fontSize: 13 }}
                value={gen[k] || ""} placeholder={ph} onChange={(e) => setGen((g) => ({ ...g, [k]: e.target.value }))} />
            </div>
          ))}
        </div>
      </div>

      {/* Suppliers */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <div className="tool-label" style={{ margin: 0 }}>🏷 Suppliers ({suppliers.length})</div>
        <span style={{ flex: 1 }} />
        <input className="search" style={{ maxWidth: 240 }} placeholder="Search supplier…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {suppliers.map((s) => {
          const name = s.supplier;
          const isOpen = open.has(name);
          const nFilled = filled(name);
          return (
            <div key={name} className="card" style={{ padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", cursor: "pointer" }} onClick={() => toggle(name)}>
                <b style={{ fontSize: 15 }}>{name}</b>
                {s.account_type && <span className={`chip ${s.account_type.toLowerCase() === "credit" ? "green" : "grey"}`}>{s.account_type}</span>}
                {s.account_number && <span className="sub">A/C {s.account_number}</span>}
                {s.credit_limit && <span className="sub">· limit {money(s.credit_limit)}</span>}
                <span style={{ flex: 1 }} />
                <span className={`chip ${nFilled === SUP_FIELDS.length ? "green" : nFilled ? "amber" : "red"}`}>{nFilled}/{SUP_FIELDS.length} filled</span>
                <span className="sub">{isOpen ? "▾" : "▸"}</span>
              </div>

              {isOpen && (
                <div style={{ marginTop: 10 }}>
                  {/* Reference (read-only, from the Suppliers board) */}
                  <div style={{ background: "rgba(127,127,127,0.05)", border: "1px solid rgba(127,127,127,0.18)", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
                    <div className="sub" style={{ fontWeight: 600, marginBottom: 6 }}>Account & contacts (from the Suppliers board)</div>
                    <div className="sub" style={{ fontSize: 13, display: "flex", flexWrap: "wrap", gap: "2px 14px" }}>
                      {s.account_number && <span>A/C no: <b>{s.account_number}</b></span>}
                      {s.account_type && <span>Account: <b>{s.account_type}</b></span>}
                      {s.credit_limit && <span>Credit limit: <b>{money(s.credit_limit)}</b></span>}
                      {s.delivery && <span>Delivery: {s.delivery}</span>}
                      {s.payment_terms && <span>Terms: {s.payment_terms}</span>}
                    </div>
                    {(s.contacts || []).length > 0 && (
                      <table className="mini" style={{ marginTop: 8 }}>
                        <tbody>
                          {s.contacts.map((c, i) => (
                            <tr key={i}>
                              <td className="sub" style={{ whiteSpace: "nowrap" }}>{c.role || "—"}</td>
                              <td>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : <span className="sub">—</span>}</td>
                              <td className="sub" style={{ whiteSpace: "nowrap" }}>{c.phone || ""}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>

                  {/* Editable aftersales fields */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
                    {SUP_FIELDS.map(([k, label, ph]) => (
                      <div key={k}>
                        <label className="sub" style={{ fontWeight: 600, display: "block", marginBottom: 3 }}>{label}</label>
                        <textarea className="input" style={{ width: "100%", minHeight: 48, resize: "vertical", fontFamily: "inherit", fontSize: 13 }}
                          value={(sup[name]?.[k]) || ""} placeholder={ph}
                          onChange={(e) => setSup((m) => ({ ...m, [name]: { ...(m[name] || {}), [k]: e.target.value } }))} />
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
                    <button className="btn primary" onClick={() => saveSup(name)} disabled={savingSup[name]}>{savingSup[name] ? "Saving…" : `Save ${name}`}</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
