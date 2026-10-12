"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function stageClass(stage) {
  if (!stage) return "grey";
  const s = stage.toLowerCase();
  if (s.includes("send po") || s.includes("po sent")) return "green";
  if (s.includes("place order")) return "blue";
  if (s.includes("quote") || s.includes("portal")) return "amber";
  return "grey";
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function money(v) {
  const n = num(v);
  return n === null ? "—" : "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function Board() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [orders, setOrders] = useState([]);
  const [meta, setMeta] = useState({ suppliers: [], stages: [] });
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const [toast, setToast] = useState(null);

  // tools
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState("All");
  const [supplierFilter, setSupplierFilter] = useState("All");
  const [sort, setSort] = useState({ field: null, dir: 1 });

  useEffect(() => {
    let k = null;
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    if (k) setAccessKey(k); else setNeedKey(true);
  }, []);

  const flash = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2400);
  }, []);

  const apiFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) },
    });
    if (res.status === 401) {
      try { localStorage.removeItem(KEY_STORE); } catch {}
      setAccessKey(null); setNeedKey(true); setError("Wrong access code — try again.");
      throw new Error("unauthorised");
    }
    return res;
  }, [accessKey]);

  const load = useCallback(async () => {
    if (!accessKey) return;
    setStatus("loading"); setError("");
    try {
      const [oRes, mRes] = await Promise.all([apiFetch("/orders"), apiFetch("/meta")]);
      if (!oRes.ok) throw new Error(`API ${oRes.status}`);
      const data = await oRes.json();
      setOrders(data.orders || []);
      if (mRes.ok) setMeta(await mRes.json());
      setUpdatedAt(new Date()); setStatus("ok");
    } catch (e) {
      if (String(e.message) !== "unauthorised") { setError(String(e.message || e)); setStatus("error"); }
    }
  }, [accessKey, apiFetch]);

  useEffect(() => { if (accessKey) load(); }, [accessKey, load]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim();
    if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput(""); setError("");
  }
  function signOut() {
    try { localStorage.removeItem(KEY_STORE); } catch {}
    setAccessKey(null); setOrders([]); setNeedKey(true); setStatus("idle");
  }

  const saveField = useCallback(async (item_id, field, value) => {
    const prev = orders.find((o) => o.item_id === item_id)?.[field] ?? null;
    setOrders((os) => os.map((o) => (o.item_id === item_id ? { ...o, [field]: value || null } : o)));
    try {
      const res = await apiFetch(`/orders/${item_id}/${field}`, { method: "POST", body: JSON.stringify({ [field]: value }) });
      if (!res.ok) throw new Error(`save ${res.status}`);
      flash(`${field === "supplier" ? "Supplier" : "Stage"} saved`);
    } catch (e) {
      setOrders((os) => os.map((o) => (o.item_id === item_id ? { ...o, [field]: prev } : o)));
      if (String(e.message) !== "unauthorised") flash(`Couldn't save — ${String(e.message || e)}`, "err");
    }
  }, [orders, apiFetch, flash]);

  const stagesPresent = useMemo(
    () => Array.from(new Set(orders.map((o) => o.stage).filter(Boolean))).sort(), [orders]);
  const suppliersPresent = useMemo(
    () => Array.from(new Set(orders.map((o) => o.supplier).filter(Boolean))).sort(), [orders]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = orders.filter((o) => {
      if (stageFilter !== "All" && (o.stage || "") !== stageFilter) return false;
      if (supplierFilter !== "All" && (o.supplier || "") !== supplierFilter) return false;
      if (q) {
        const hay = `${o.order_no || ""} ${o.customer || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    if (sort.field) {
      const f = sort.field, dir = sort.dir;
      rows = [...rows].sort((a, b) => {
        let av = a[f], bv = b[f];
        if (f === "sell" || f === "cost_supplier") { av = num(av) ?? -Infinity; bv = num(bv) ?? -Infinity; return (av - bv) * dir; }
        return String(av || "").localeCompare(String(bv || "")) * dir;
      });
    }
    return rows;
  }, [orders, query, stageFilter, supplierFilter, sort]);

  const totalSell = useMemo(
    () => filtered.reduce((s, o) => s + (num(o.sell) || 0), 0), [filtered]);

  function toggleSort(field) {
    setSort((s) => (s.field === field ? { field, dir: s.dir * -1 } : { field, dir: 1 }));
  }
  function arrow(field) { return sort.field === field ? <span className="arrow">{sort.dir > 0 ? "▲" : "▼"}</span> : null; }
  const supplierOpts = meta.suppliers || [];
  const stageOpts = meta.stages || [];

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <div className="wordmark">Trade<b>Hub</b><span className="sec">Order Processing</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus
              onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
          {error && <p className="state err">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Order Processing</span></div>
        <div className="right">
          <span className="count">
            {status === "ok" ? <><b>{orders.length}</b> orders</> : status === "loading" ? "Loading…" : ""}
            {updatedAt && status === "ok" ? ` · ${updatedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
          <button className="btn" onClick={signOut}>Sign out</button>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>
            {status === "loading" ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="toolbar">
        <input className="search" placeholder="Search order no. or customer…" value={query}
          onChange={(e) => setQuery(e.target.value)} />
        <select className="filter" value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}>
          <option value="All">All stages</option>
          {stagesPresent.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="filter" value={supplierFilter} onChange={(e) => setSupplierFilter(e.target.value)}>
          <option value="All">All suppliers</option>
          {suppliersPresent.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div className="card">
        {status === "loading" && orders.length === 0 && (
          <div className="state"><span className="spinner" />Reading the NEW ORDERS board from Monday…</div>
        )}
        {status === "error" && (
          <div className="state err">Couldn’t reach the API ({error}).<br />
            <span className="sub">Check the API is running and the access code is correct.</span></div>
        )}
        {(status === "ok" || orders.length > 0) && (
          <>
            <table>
              <thead>
                <tr>
                  <th className="sortable" onClick={() => toggleSort("order_no")}>Order{arrow("order_no")}</th>
                  <th className="sortable" onClick={() => toggleSort("customer")}>Customer{arrow("customer")}</th>
                  <th className="sortable" onClick={() => toggleSort("supplier")}>Supplier{arrow("supplier")}</th>
                  <th className="sortable" onClick={() => toggleSort("stage")}>Stage{arrow("stage")}</th>
                  <th className="num sortable" onClick={() => toggleSort("sell")}>£ to us{arrow("sell")}</th>
                  <th className="num sortable" onClick={() => toggleSort("cost_supplier")}>£ supplier{arrow("cost_supplier")}</th>
                  <th>PO</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => {
                  const supList = o.supplier && !supplierOpts.includes(o.supplier) ? [o.supplier, ...supplierOpts] : supplierOpts;
                  const stgList = o.stage && !stageOpts.includes(o.stage) ? [o.stage, ...stageOpts] : stageOpts;
                  return (
                    <tr key={o.item_id}>
                      <td className="ono">{o.order_no}</td>
                      <td className="cust">{o.customer || "—"}</td>
                      <td>
                        <select className="cell-select" value={o.supplier || ""}
                          onChange={(e) => saveField(o.item_id, "supplier", e.target.value)}>
                          <option value="">— unrouted —</option>
                          {supList.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td>
                        <select className={`cell-select ${stageClass(o.stage)}`} value={o.stage || ""}
                          onChange={(e) => saveField(o.item_id, "stage", e.target.value)}>
                          <option value="">—</option>
                          {stgList.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td className="num">{money(o.sell)}</td>
                      <td className="num">{money(o.cost_supplier)}</td>
                      <td>{o.has_po ? <span className="pill green">attached</span> : <span className="pill dash">none</span>}</td>
                    </tr>
                  );
                })}
                {status === "ok" && filtered.length === 0 && (
                  <tr><td colSpan={7}><div className="state">No orders match.</div></td></tr>
                )}
              </tbody>
            </table>
            <div className="totals">
              Showing <b>{filtered.length}</b> of {orders.length}
              <span className="spacer" />
              £ to us (shown): <b>{money(totalSell)}</b>
            </div>
          </>
        )}
      </div>

      {toast && <div className={`toast ${toast.kind === "err" ? "err" : ""}`}>{toast.msg}</div>}
    </div>
  );
}
