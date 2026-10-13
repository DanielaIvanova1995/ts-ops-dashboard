"use client";

import { Fragment, useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}

export default function Pricing() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [tab, setTab] = useState("prices");

  const [suppliers, setSuppliers] = useState([]);
  const [sup, setSup] = useState("");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const [meta, setMeta] = useState({ total: 0, capped: false });
  const [loadingPrices, setLoadingPrices] = useState(false);

  const [deliv, setDeliv] = useState(null);
  const [expanded, setExpanded] = useState(null);

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
    jsonFetch("/pricing/suppliers").then((r) => r.ok && r.json()).then((d) => d && setSuppliers(d.suppliers || [])).catch(() => {});
  }, [accessKey, jsonFetch]);

  const loadPrices = useCallback(async (supplier, query) => {
    if (!supplier) { setRows(null); return; }
    setLoadingPrices(true);
    try {
      const res = await jsonFetch(`/pricing/prices?supplier=${encodeURIComponent(supplier)}&q=${encodeURIComponent(query || "")}`);
      const d = await res.json();
      setRows(d.rows || []); setMeta({ total: d.total || 0, capped: !!d.capped, updated: d.updated, fee: d.fee_pct });
    } catch (e) { if (String(e.message) !== "unauthorised") { setRows([]); setMeta({ total: 0, capped: false }); } }
    finally { setLoadingPrices(false); }
  }, [jsonFetch]);

  useEffect(() => {
    if (!accessKey || tab !== "delivery" || deliv) return;
    jsonFetch("/pricing/delivery").then((r) => r.ok && r.json()).then((d) => d && setDeliv(d.rows || [])).catch(() => {});
  }, [accessKey, tab, deliv, jsonFetch]);

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
          <div className="wordmark">Trade<b>Hub</b><span className="sec">Pricing</span></div>
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
        <div className="pagetitle">Pricing</div>
        <div className="right">
          <div className="seg">
            <button className={`seg-btn${tab === "prices" ? " on" : ""}`} onClick={() => setTab("prices")}>Pricelists</button>
            <button className={`seg-btn${tab === "delivery" ? " on" : ""}`} onClick={() => setTab("delivery")}>Delivery charges</button>
          </div>
        </div>
      </div>

      {tab === "prices" && (
        <>
          <div className="card" style={{ padding: "8px 12px", marginBottom: 8 }}>
            <div className="inv-controls">
              <select className="filter" value={sup} onChange={(e) => { setSup(e.target.value); loadPrices(e.target.value, q); }}>
                <option value="">Choose a supplier…</option>
                {suppliers.map((s) => <option key={s.supplier} value={s.supplier}>{s.supplier} ({s.count})</option>)}
              </select>
              <input className="search" style={{ maxWidth: 240 }} placeholder="Search SKU or name" value={q}
                onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") loadPrices(sup, q); }} disabled={!sup} />
              <button className="btn" onClick={() => loadPrices(sup, q)} disabled={!sup || loadingPrices}>{loadingPrices ? "…" : "Search"}</button>
              <span style={{ flex: 1 }} />
              {rows && <span className="sub">{meta.total.toLocaleString()} priced SKU{meta.total === 1 ? "" : "s"}{meta.capped ? ` · showing first ${rows.length}` : ""}{meta.updated ? ` · prices updated ${meta.updated}` : ""}</span>}
            </div>
          </div>
          {!sup && <div className="card"><div className="state">Pick a supplier to see their cost prices.</div></div>}
          {sup && rows && rows.length === 0 && <div className="card"><div className="state">No priced SKUs{q ? " match this search" : ""}.</div></div>}
          {sup && rows && rows.length > 0 && (
            <div className="card" style={{ padding: "6px 12px 12px" }}>
              <table className="mini">
                <thead><tr><th>SKU</th><th>Product</th><th className="num">Cost</th><th className="num">Sell</th><th className="num">Margin{meta.fee ? ` (−${meta.fee}%)` : ""}</th><th></th></tr></thead>
                <tbody>
                  {rows.map((r, i) => {
                    const mClass = r.margin == null ? "" : r.margin < 8 ? "mred" : r.margin < 15 ? "mamber" : "mgreen";
                    return (
                    <tr key={i}>
                      <td className="ono">{r.sku || "—"}</td>
                      <td>{r.on_shopify ? r.name : <span className="pill amber">not on Shopify</span>}</td>
                      <td className="num">{money(r.cost)}</td>
                      <td className="num">{r.sell != null ? money(r.sell) : "—"}</td>
                      <td className={`num ${mClass}`}>{r.margin == null ? "—" : `${r.margin}%`}</td>
                      <td>{r.source === "override" ? <span className="pill grey">override</span> : null}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "delivery" && (
        <div className="card" style={{ padding: "6px 12px 12px" }}>
          <div className="sub" style={{ margin: "8px 2px" }}>Ex‑VAT. “We pay” is what the supplier charges us; “Customer” is what we charge the customer — set in Shopify shipping except AJW, which is managed here.</div>
          {!deliv && <div className="state">Loading…</div>}
          {deliv && (
            <table className="mini">
              <thead><tr><th>Supplier</th><th>Basis</th><th>We pay</th><th>Free over</th><th>Customer</th><th></th></tr></thead>
              <tbody>
                {deliv.map((r, i) => (
                  <Fragment key={i}>
                    <tr>
                      <td><b>{r.supplier}</b>{r.notes ? <div className="sub">{r.notes}</div> : null}</td>
                      <td className="sub">{r.basis}</td>
                      <td>{r.we_pay}</td>
                      <td className="sub">{r.free_over}</td>
                      <td>{r.customer}</td>
                      <td>{r.zones ? <button className="btn ghost" onClick={() => setExpanded(expanded === i ? null : i)}>{expanded === i ? "Hide zones" : "Zones"}</button> : null}</td>
                    </tr>
                    {r.zones && expanded === i && (
                      <tr><td colSpan={6} style={{ paddingLeft: 18 }}>
                        <table className="mini">
                          <thead><tr><th>Zone</th><th>We pay</th><th>Free over (our cost)</th><th>Customer</th><th>Customer free over</th></tr></thead>
                          <tbody>
                            {r.zones.map((z, j) => (
                              <tr key={j}>
                                <td>{z.zone}</td><td>{z.we_pay}</td><td className="sub">{z.free_over}</td>
                                <td>{z.customer}</td><td className="sub">{z.customer_free}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
