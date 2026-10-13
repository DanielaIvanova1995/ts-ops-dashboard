"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

/* ---- professional inline icons (Lucide-style strokes, no emoji) ---- */
const IconPaperclip = (p) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);
const IconFile = (p) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" /><path d="M14 2v5h5" />
  </svg>
);
const IconChat = (p) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);
const IconX = (p) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M18 6 6 18M6 6l12 12" /></svg>
);
const IconWarn = (p) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
    <path d="M12 9v4" /><path d="M12 17h.01" /></svg>
);
const IconExternal = (p) => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M15 3h6v6" /><path d="M10 14 21 3" />
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
);

/* "£ to us" is the GROSS (inc-VAT) order value, so compare it directly to the Shopify gross total
   (totalPriceSet, inc VAT + delivery). Warn when they differ beyond a penny tolerance — i.e. the
   order was edited after it came in, or the Monday value is stale. Returns the Shopify total. */
function totalWarn(sell, t) {
  const s = num(sell);
  const c = t ? num(t.total) : null;
  if (s === null || c === null) return null;
  // Exact to the penny — no tolerance. (Round only to avoid float noise like 202.1299…)
  return Math.round(s * 100) === Math.round(c * 100) ? null : c;
}

function stageClass(stage) {
  if (!stage) return "grey";
  const s = stage.toLowerCase();
  if (s.includes("send po") || s.includes("po sent")) return "green";
  if (s.includes("place order")) return "blue";
  if (s.includes("quote") || s.includes("portal")) return "amber";
  return "grey";
}
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
/* A split part (31824-1, 31824-2…) is only PART of the order, so its "£ to us" will never equal the
   whole Shopify total — never warn on those. */
function isSplit(ono) { return /-\d+$/.test(String(ono || "").trim()); }
function money(v, cur = "£") {
  const n = num(v);
  return n === null ? "—" : cur + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
function stripHtml(h) { return (h || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/[ \t]+/g, " ").trim(); }

export default function Board() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [orders, setOrders] = useState([]);
  const [meta, setMeta] = useState({ suppliers: [], stages: [] });
  const [counts, setCounts] = useState({});
  const [totals, setTotals] = useState({}); // {item_id: {total, subtotal}} live Shopify totals
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const [toast, setToast] = useState(null);

  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState("All");
  const [supplierFilter, setSupplierFilter] = useState("All");
  const [sort, setSort] = useState({ field: null, dir: 1 });

  const [drawer, setDrawer] = useState(null); // the order whose detail is open
  const [detail, setDetail] = useState(null);
  const [detailErr, setDetailErr] = useState("");

  const [selected, setSelected] = useState(() => new Set());
  const [proc, setProc] = useState(null); // {running, done, total, results:[{order,text,kind}]}

  useEffect(() => {
    let k = null;
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    if (k) setAccessKey(k); else setNeedKey(true);
  }, []);

  const flash = useCallback((msg, kind = "ok") => {
    setToast({ msg, kind }); setTimeout(() => setToast(null), 2400);
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
      // update-count bubbles + live Shopify totals (extra calls, non-fatal, keep board fast)
      apiFetch("/updates-counts").then((r) => r.ok && r.json()).then((d) => d && setCounts(d.counts || {})).catch(() => {});
      apiFetch("/order-totals").then((r) => r.ok && r.json()).then((d) => d && setTotals(d.totals || {})).catch(() => {});
    } catch (e) {
      if (String(e.message) !== "unauthorised") { setError(String(e.message || e)); setStatus("error"); }
    }
  }, [accessKey, apiFetch]);

  useEffect(() => { if (accessKey) load(); }, [accessKey, load]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
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

  // "Process" one order: if it already has a supplier, just (re)generate the PO for that supplier
  // (keeps your manual choice); if it's unrouted, route it first then generate. Updates the row.
  const processOne = useCallback(async (o) => {
    const path = o.supplier ? `/orders/${o.item_id}/po` : `/orders/${o.item_id}/process`;
    const res = await apiFetch(path, { method: "POST" });
    if (!res.ok) throw new Error(`process ${res.status}`);
    const d = await res.json();
    setOrders((os) => os.map((x) => (x.item_id === o.item_id
      ? { ...x, supplier: d.supplier ?? x.supplier, stage: d.stage ?? x.stage, has_po: d.attached ? true : x.has_po }
      : x)));
    return d;
  }, [apiFetch]);

  const processSelected = useCallback(async () => {
    const ids = orders.filter((o) => selected.has(o.item_id));
    if (!ids.length) return;
    const results = [];
    setProc({ running: true, done: 0, total: ids.length, results: [] });
    for (const o of ids) {
      let text = "—", kind = "warn";
      try {
        const d = await processOne(o);
        text = d.result || (d.blocked ? "blocked" : d.ok ? "done" : "—");
        kind = d.ok ? "ok" : "warn";
      } catch (e) {
        if (String(e.message) === "unauthorised") break;
        text = "error: " + String(e.message || e);
      }
      results.push({ order: o.order_no, text, kind });
      setProc({ running: true, done: results.length, total: ids.length, results: [...results] });
    }
    setProc((p) => ({ ...(p || {}), running: false }));
    setSelected(new Set());
    flash(`Processed ${results.length}`);
    load();
  }, [orders, selected, processOne, flash, load]);

  const openDetail = useCallback(async (o) => {
    setDrawer(o); setDetail(null); setDetailErr("");
    try {
      const qs = o.shopify_id ? `?shopify_id=${encodeURIComponent(o.shopify_id)}` : "";
      const res = await apiFetch(`/orders/${o.item_id}/detail${qs}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setDetail(await res.json());
    } catch (e) { if (String(e.message) !== "unauthorised") setDetailErr(String(e.message || e)); }
  }, [apiFetch]);

  const stagesPresent = useMemo(() => Array.from(new Set(orders.map((o) => o.stage).filter(Boolean))).sort(), [orders]);
  const suppliersPresent = useMemo(() => Array.from(new Set(orders.map((o) => o.supplier).filter(Boolean))).sort(), [orders]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = orders.filter((o) => {
      if (stageFilter !== "All" && (o.stage || "") !== stageFilter) return false;
      if (supplierFilter !== "All" && (o.supplier || "") !== supplierFilter) return false;
      if (q && !`${o.order_no || ""} ${o.customer || ""}`.toLowerCase().includes(q)) return false;
      return true;
    });
    if (sort.field) {
      const f = sort.field, dir = sort.dir;
      rows = [...rows].sort((a, b) => {
        if (f === "sell" || f === "cost_supplier") return ((num(a[f]) ?? -Infinity) - (num(b[f]) ?? -Infinity)) * dir;
        return String(a[f] || "").localeCompare(String(b[f] || "")) * dir;
      });
    }
    return rows;
  }, [orders, query, stageFilter, supplierFilter, sort]);

  const totalSell = useMemo(() => filtered.reduce((s, o) => s + (num(o.sell) || 0), 0), [filtered]);
  function toggleSort(field) { setSort((s) => (s.field === field ? { field, dir: s.dir * -1 } : { field, dir: 1 })); }
  function toggleSel(id) { setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  function toggleAll() {
    setSelected((s) => {
      const ids = filtered.map((o) => o.item_id);
      const allOn = ids.length && ids.every((i) => s.has(i));
      const n = new Set(s);
      ids.forEach((i) => (allOn ? n.delete(i) : n.add(i)));
      return n;
    });
  }
  const allSelected = filtered.length > 0 && filtered.every((o) => selected.has(o.item_id));
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
        <nav className="nav">
          <Link className="navlink active" href="/">Orders</Link>
          <Link className="navlink" href="/recon">Statements</Link>
        </nav>
        <div className="right">
          <span className="count">
            {status === "ok" ? <><b>{orders.length}</b> orders</> : status === "loading" ? "Loading…" : ""}
            {updatedAt && status === "ok" ? ` · ${updatedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
          <button className="btn" onClick={signOut}>Sign out</button>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>{status === "loading" ? "Refreshing…" : "Refresh"}</button>
        </div>
      </div>

      <div className="toolbar">
        <input className="search" placeholder="Search order no. or customer…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="filter" value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}>
          <option value="All">All stages</option>
          {stagesPresent.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="filter" value={supplierFilter} onChange={(e) => setSupplierFilter(e.target.value)}>
          <option value="All">All suppliers</option>
          {suppliersPresent.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {selected.size > 0 && (
          <button className="btn primary" onClick={processSelected} disabled={proc?.running}>
            {proc?.running ? `Processing ${proc.done}/${proc.total}…` : `Process selected (${selected.size})`}
          </button>
        )}
      </div>

      {proc && (
        <div className="proc-panel">
          <div className="proc-head">
            {proc.running ? <><span className="spinner" />Processing {proc.done} of {proc.total}…</>
              : <>Processed {proc.results.length}. <button className="linkish" onClick={() => setProc(null)}>dismiss</button></>}
          </div>
          {proc.total > 0 && <div className="proc-bar"><span style={{ width: `${Math.round((proc.done / proc.total) * 100)}%` }} /></div>}
          {proc.results.length > 0 && (
            <div className="proc-results">
              {proc.results.map((r, i) => (
                <div key={i} className={`proc-row ${r.kind}`}><b>{r.order}</b> {r.text}</div>
              ))}
            </div>
          )}
        </div>
      )}

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
                  <th className="chk"><input type="checkbox" checked={allSelected} onChange={toggleAll} title="Select all shown" /></th>
                  <th className="sortable" onClick={() => toggleSort("order_no")}>Order{arrow("order_no")}</th>
                  <th className="sortable" onClick={() => toggleSort("customer")}>Customer{arrow("customer")}</th>
                  <th className="sortable" onClick={() => toggleSort("supplier")}>Supplier{arrow("supplier")}</th>
                  <th className="sortable" onClick={() => toggleSort("stage")}>Stage{arrow("stage")}</th>
                  <th className="num sortable" onClick={() => toggleSort("sell")}>£ to us{arrow("sell")}</th>
                  <th className="num sortable" onClick={() => toggleSort("cost_supplier")}>£ supplier{arrow("cost_supplier")}</th>
                  <th className="mid">PO</th>
                  <th className="mid">Updates</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => {
                  const supList = o.supplier && !supplierOpts.includes(o.supplier) ? [o.supplier, ...supplierOpts] : supplierOpts;
                  const stgList = o.stage && !stageOpts.includes(o.stage) ? [o.stage, ...stageOpts] : stageOpts;
                  const n = counts[o.item_id] || 0;
                  return (
                    <tr key={o.item_id} className={selected.has(o.item_id) ? "sel" : ""}>
                      <td className="chk"><input type="checkbox" checked={selected.has(o.item_id)} onChange={() => toggleSel(o.item_id)} /></td>
                      <td className="ono">
                        <span className="ono-wrap">
                          <button className="linkish" onClick={() => openDetail(o)}>{o.order_no}</button>
                          {o.shopify_url && <a className="ext" href={o.shopify_url} target="_blank" rel="noopener noreferrer" title="Open in Shopify"><IconExternal /></a>}
                        </span>
                      </td>
                      <td className="cust">{o.customer || "—"}</td>
                      <td>
                        <select className="cell-select" value={o.supplier || ""} onChange={(e) => saveField(o.item_id, "supplier", e.target.value)}>
                          <option value="">— unrouted —</option>
                          {supList.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td>
                        <select className={`cell-select ${stageClass(o.stage)}`} value={o.stage || ""} onChange={(e) => saveField(o.item_id, "stage", e.target.value)}>
                          <option value="">—</option>
                          {stgList.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td className="num">
                        {(() => {
                          const w = isSplit(o.order_no) ? null : totalWarn(o.sell, totals[o.item_id]);
                          return (
                            <span className="sell-cell">
                              {money(o.sell)}
                              {w !== null && (
                                <span className="warn-ico" title={`Monday £ to us ${money(o.sell)} ≠ Shopify total ${money(w)}`}>
                                  <IconWarn />
                                </span>
                              )}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="num">{money(o.cost_supplier)}</td>
                      <td className="mid">
                        {o.po_url
                          ? <a className="icon-btn" href={o.po_url} target="_blank" rel="noopener noreferrer" title={o.po_name || "Open PO"}><IconPaperclip /></a>
                          : <span className="icon-btn muted" title="No PO yet"><IconFile /></span>}
                      </td>
                      <td className="mid">
                        <button className={`bubble${n ? " has" : ""}`} onClick={() => openDetail(o)} title="Open order & updates">
                          <IconChat />{n ? <span className="badge">{n}</span> : null}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {status === "ok" && filtered.length === 0 && (
                  <tr><td colSpan={9}><div className="state">No orders match.</div></td></tr>
                )}
              </tbody>
            </table>
            <div className="totals">
              Showing <b>{filtered.length}</b> of {orders.length}
              <span className="spacer" />£ to us (shown): <b>{money(totalSell)}</b>
            </div>
          </>
        )}
      </div>

      {drawer && (
        <OrderDrawer
          order={drawer} detail={detail} err={detailErr} onClose={() => setDrawer(null)}
          onProcess={processOne} apiFetch={apiFetch} flash={flash} reload={load} suppliers={meta.suppliers || []}
        />
      )}
      {toast && <div className={`toast ${toast.kind === "err" ? "err" : ""}`}>{toast.msg}</div>}
    </div>
  );
}

function OrderDrawer({ order, detail, err, onClose, onProcess, apiFetch, flash, reload, suppliers }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const [editorOpen, setEditorOpen] = useState(false);  // the big PO editor modal
  const [splitOpen, setSplitOpen] = useState(false);    // the manual split picker modal
  // Merge
  const [siblings, setSiblings] = useState([]);
  const [mergeSel, setMergeSel] = useState(() => new Set());
  const [mergeTarget, setMergeTarget] = useState("");
  const [mergeBusy, setMergeBusy] = useState(false);
  const [mergeMsg, setMergeMsg] = useState(null);

  // Load split-part siblings (for Merge) when the drawer opens.
  useEffect(() => {
    let live = true;
    apiFetch(`/orders/${order.item_id}/siblings`).then((r) => r.ok && r.json())
      .then((d) => { if (live && d) setSiblings(d.siblings || []); }).catch(() => {});
    return () => { live = false; };
  }, [order.item_id, apiFetch]);

  async function doProcess() {
    setBusy(true); setMsg(null);
    try {
      const d = await onProcess(order);
      if (d.blocked) { setMsg({ kind: "warn", text: "Can’t complete — " + (d.errors || []).join("; ") }); flash("Blocked", "err"); }
      else if (d.ok) { setMsg({ kind: "ok", text: d.result || "Done." }); flash("Processed"); reload && reload(); }
      else { setMsg({ kind: "warn", text: d.result || d.detail || "Couldn’t process." }); flash(d.result || "Not processed", "err"); }
    } catch (e) {
      if (String(e.message) !== "unauthorised") setMsg({ kind: "warn", text: String(e.message || e) });
    } finally { setBusy(false); }
  }


  async function doMerge() {
    const ids = [...mergeSel];
    if (ids.length < 2) { setMergeMsg({ kind: "warn", text: "Tick at least two parts to merge." }); return; }
    if (!mergeTarget) { setMergeMsg({ kind: "warn", text: "Choose which supplier fulfils the merged part." }); return; }
    setMergeBusy(true); setMergeMsg(null);
    try {
      const res = await apiFetch(`/orders/merge`, { method: "POST", body: JSON.stringify({ part_item_ids: ids, target_supplier: mergeTarget }) });
      if (!res.ok) throw new Error(`merge ${res.status}`);
      const d = await res.json();
      setMergeMsg({ kind: d.ok ? "ok" : "warn", text: d.result || "—" });
      if (d.ok) { flash("Merged"); reload && reload(); setTimeout(onClose, 900); }
    } catch (e) {
      if (String(e.message) !== "unauthorised") setMergeMsg({ kind: "warn", text: String(e.message || e) });
    } finally { setMergeBusy(false); }
  }
  function toggleMerge(id) { setMergeSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  const mergeSuppliers = Array.from(new Set(siblings.map((s) => s.supplier).filter(Boolean)));

  const sx = detail?.shopify;
  const cur = sx?.totals?.currency === "GBP" ? "£" : "£";
  const ship = sx?.shipping?.lines || [];
  const bill = sx?.billing?.lines || [];
  const addrDiffer = ship.length && bill.length && ship.join("|") !== bill.join("|");
  const sellWarn = (sx?.totals && !isSplit(order.order_no)) ? totalWarn(order.sell, { total: sx.totals.total, subtotal: sx.totals.subtotal }) : null;
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          <div><span className="dh-ono">#{order.order_no}</span>{sx?.financial_status ? <span className="pill grey" style={{ marginLeft: 8 }}>{sx.financial_status}</span> : null}</div>
          <div className="dh-actions">
            {order.shopify_url && <a className="icon-btn" href={order.shopify_url} target="_blank" rel="noopener noreferrer" title="Open in Shopify"><IconExternal /></a>}
            <button className="icon-btn" onClick={onClose} title="Close"><IconX /></button>
          </div>
        </div>

        <div className="drawer-actions3">
          <button className="btn primary" onClick={doProcess} disabled={busy}>{busy ? "Working…" : "Generate PO"}</button>
          <button className="btn" onClick={() => setEditorOpen(true)}>Edit PO</button>
          <button className="btn" onClick={() => setSplitOpen(true)}>Split order</button>
        </div>
        {msg && <div className={`route-msg ${msg.kind}`}>{msg.text}</div>}

        {/* Merge — only when this order has split parts */}
        {siblings.length > 1 && (
          <div className="tool">
            <div className="tool-label">Merge split parts into one delivery</div>
            <div className="merge-list">
              {siblings.map((s) => (
                <label key={s.item_id} className="merge-row">
                  <input type="checkbox" checked={mergeSel.has(s.item_id)} onChange={() => toggleMerge(s.item_id)} />
                  <span><b>{s.name}</b> <span className="sub">{s.supplier || "—"}{s.items ? ` · ${s.items}` : ""}</span></span>
                </label>
              ))}
            </div>
            <div className="merge-ctl">
              <select className="filter" value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)}>
                <option value="">— fulfil merged part with —</option>
                {mergeSuppliers.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="btn primary" onClick={doMerge} disabled={mergeBusy}>{mergeBusy ? "Merging…" : "Merge"}</button>
            </div>
            {mergeMsg && <div className={`route-msg ${mergeMsg.kind}`}>{mergeMsg.text}</div>}
          </div>
        )}

        {!detail && !err && <div className="state"><span className="spinner" />Loading order…</div>}
        {err && <div className="state err">Couldn’t load detail ({err}).</div>}

        {detail && (
          <div className="drawer-body">
            {/* Customer */}
            <section>
              <h4>Customer</h4>
              <div className="kv"><span>Name</span><b>{sx?.customer?.name || order.customer || "—"}</b></div>
              {sx?.customer?.email && <div className="kv"><span>Email</span><b>{sx.customer.email}</b></div>}
              {sx?.customer?.phone && <div className="kv"><span>Phone</span><b>{sx.customer.phone}</b></div>}
            </section>

            {/* Addresses */}
            <section>
              <h4>Addresses{addrDiffer ? <span className="warn-tag">billing differs from delivery</span> : null}</h4>
              <div className="addrs">
                <div className="addr">
                  <div className="addr-label">Delivery (ship to)</div>
                  {ship.length ? ship.map((l, i) => <div key={i}>{l}</div>) : <div className="sub">—</div>}
                  {sx?.shipping?.phone && <div className="sub">{sx.shipping.phone}</div>}
                </div>
                <div className="addr">
                  <div className="addr-label">Billing</div>
                  {bill.length ? bill.map((l, i) => <div key={i}>{l}</div>) : <div className="sub">—</div>}
                  {sx?.billing?.phone && <div className="sub">{sx.billing.phone}</div>}
                </div>
              </div>
            </section>

            {/* Items */}
            <section>
              <h4>Ordered</h4>
              {sx?.items?.length ? (
                <table className="mini">
                  <thead><tr><th>Qty</th><th>Item</th><th className="num">Unit</th><th className="num">Total</th></tr></thead>
                  <tbody>
                    {sx.items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.qty}</td>
                        <td>{it.title}{it.variant ? <span className="sub"> · {it.variant}</span> : null}{it.sku ? <div className="sub">{it.sku}</div> : null}</td>
                        <td className="num">{money(it.unit, cur)}</td>
                        <td className="num">{money(it.line_total, cur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="sub">{detail.shopify_error ? `Couldn’t read Shopify (${detail.shopify_error})` : "No line items."}</div>}
              {sx?.totals && (
                <div className="ordtotals">
                  <div className="kv"><span>Subtotal</span><b>{money(sx.totals.subtotal, cur)}</b></div>
                  <div className="kv"><span>Delivery</span><b>{money(sx.totals.shipping, cur)}</b></div>
                  <div className="kv"><span>VAT</span><b>{money(sx.totals.tax, cur)}</b></div>
                  <div className="kv big"><span>Total</span><b>{money(sx.totals.total, cur)}</b></div>
                  <div className={`kv${sellWarn !== null ? " warnrow" : ""}`}>
                    <span>£ to us (Monday)</span><b>{money(order.sell, cur)}</b>
                  </div>
                </div>
              )}
              {sellWarn !== null && (
                <div className="warn-note"><IconWarn /> Monday’s “£ to us” doesn’t match the Shopify total — the order may have been edited, or the Monday value is stale. Worth checking before processing.</div>
              )}
            </section>

            {/* Changed when */}
            <section>
              <h4>Activity</h4>
              <div className="kv"><span>Placed</span><b>{fmtDate(sx?.created_at)}</b></div>
              <div className="kv"><span>Order last changed</span><b>{fmtDate(sx?.updated_at)}</b></div>
              <div className="kv"><span>Monday last changed</span><b>{fmtDate(detail.monday_updated_at)}</b></div>
            </section>

            {/* Updates thread */}
            <section>
              <h4>Monday Updates {detail.updates?.length ? <span className="pill grey">{detail.updates.length}</span> : null}</h4>
              {detail.updates?.length ? (
                <div className="thread">
                  {detail.updates.map((u) => (
                    <div className="upd" key={u.id}>
                      <div className="upd-head"><b>{u.creator || "—"}</b><span className="sub">{fmtDate(u.created_at)}</span></div>
                      <div className="upd-body">{stripHtml(u.body) || "—"}</div>
                    </div>
                  ))}
                </div>
              ) : <div className="sub">{detail.updates_error ? `Couldn’t read updates (${detail.updates_error})` : "No updates yet."}</div>}
            </section>
          </div>
        )}
      </aside>
      {editorOpen && (
        <PoEditor order={order} apiFetch={apiFetch} flash={flash} reload={reload}
          onClose={() => setEditorOpen(false)} />
      )}
      {splitOpen && (
        <SplitEditor order={order} apiFetch={apiFetch} flash={flash} reload={reload}
          suppliers={suppliers} onClose={() => setSplitOpen(false)} onDone={onClose} />
      )}
    </>
  );
}

function SplitEditor({ order, apiFetch, flash, reload, suppliers, onClose, onDone }) {
  const [lines, setLines] = useState([]);
  const [sel, setSel] = useState(() => new Set());
  const [bulk, setBulk] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    let live = true;
    (async () => {
      setLoading(true);
      try {
        const res = await apiFetch(`/orders/${order.item_id}/split-lines`);
        if (!res.ok) throw new Error(`lines ${res.status}`);
        const d = await res.json();
        if (live) setLines((d.lines || []).map((l) => ({ ...l, supplier: l.supplier || "" })));
      } catch (e) {
        if (String(e.message) !== "unauthorised") setMsg({ kind: "warn", text: String(e.message || e) });
      } finally { if (live) setLoading(false); }
    })();
    return () => { live = false; };
  }, [apiFetch, order.item_id]);

  // supplier options = live labels + any already-suggested supplier not in that list
  const opts = Array.from(new Set([...(suppliers || []), ...lines.map((l) => l.supplier).filter(Boolean)])).sort();
  const groups = Array.from(new Set(lines.map((l) => l.supplier).filter(Boolean)));

  function toggle(i) { setSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; }); }
  function toggleAll() { setSel((s) => (s.size === lines.length ? new Set() : new Set(lines.map((_, i) => i)))); }
  function setLineSup(i, v) { setLines((ls) => ls.map((l, j) => (j === i ? { ...l, supplier: v } : l))); }
  function assignBulk() {
    if (!bulk) { setMsg({ kind: "warn", text: "Pick a supplier to assign." }); return; }
    setLines((ls) => ls.map((l, i) => (sel.has(i) ? { ...l, supplier: bulk } : l)));
    setSel(new Set());
  }

  async function doSplit() {
    if (groups.length < 2) { setMsg({ kind: "warn", text: "Assign lines to at least two different suppliers to split." }); return; }
    if (lines.some((l) => !l.supplier)) { setMsg({ kind: "warn", text: "Every line needs a supplier." }); return; }
    setBusy(true); setMsg(null);
    try {
      const res = await apiFetch(`/orders/${order.item_id}/split-manual`, { method: "POST", body: JSON.stringify({ lines }) });
      if (!res.ok) throw new Error(`split ${res.status}`);
      const d = await res.json();
      if (d.ok) { flash("Split created"); reload && reload(); setMsg({ kind: "ok", text: d.result || "Split created." }); setTimeout(() => { onClose(); onDone && onDone(); }, 1100); }
      else setMsg({ kind: "warn", text: d.result || "Couldn’t split." });
    } catch (e) {
      if (String(e.message) !== "unauthorised") setMsg({ kind: "warn", text: String(e.message || e) });
    } finally { setBusy(false); }
  }

  const allSel = lines.length > 0 && sel.size === lines.length;
  return (
    <>
      <div className="overlay" onClick={onClose} style={{ zIndex: 60 }} />
      <div className="po-modal">
        <div className="po-head">
          <div className="dh-ono">Split order · #{order.order_no}</div>
          <button className="icon-btn" onClick={onClose} title="Close"><IconX /></button>
        </div>
        {loading ? <div className="state"><span className="spinner" />Reading the lines…</div> : (
          <div style={{ padding: "12px 18px", overflowY: "auto" }}>
            <div className="split-bulk">
              <span className="sub">Tick lines, choose a supplier, assign them all at once:</span>
              <select className="filter" value={bulk} onChange={(e) => setBulk(e.target.value)}>
                <option value="">— supplier —</option>
                {opts.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button className="btn" onClick={assignBulk} disabled={!sel.size}>Assign to selected ({sel.size})</button>
            </div>
            <table className="editgrid">
              <thead><tr>
                <th className="chk"><input type="checkbox" checked={allSel} onChange={toggleAll} /></th>
                <th>Item</th><th className="qty">Qty</th><th style={{ width: 200 }}>Supplier</th>
              </tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i} className={sel.has(i) ? "sel" : ""}>
                    <td className="chk"><input type="checkbox" checked={sel.has(i)} onChange={() => toggle(i)} /></td>
                    <td>{l.title}{l.sku ? <div className="sub">{l.sku}</div> : null}</td>
                    <td className="qty">{l.qty}</td>
                    <td>
                      <select className="filter" style={{ width: "100%" }} value={l.supplier} onChange={(e) => setLineSup(i, e.target.value)}>
                        <option value="">— choose —</option>
                        {opts.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="sub" style={{ marginTop: 8 }}>
              {groups.length >= 2 ? `Will create ${groups.length} parts: ${groups.join(", ")}` : "Assign 2+ suppliers to split."}
            </div>
            {msg && <div className={`route-msg ${msg.kind}`} style={{ marginTop: 8 }}>{msg.text}</div>}
          </div>
        )}
        <div className="po-foot">
          <button className="btn primary" onClick={doSplit} disabled={busy || loading}>{busy ? "Splitting…" : "Create split"}</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </>
  );
}

function PoEditor({ order, apiFetch, flash, reload, onClose }) {
  const [address, setAddress] = useState("");
  const [delivery, setDelivery] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState([]);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const body = useCallback(() => ({
    address: address || null,
    delivery: delivery === "" ? null : Number(delivery),
    notes: note || null,
    items: lines.map((l) => ({ sku: l.sku, item: l.item, qty: l.qty, cost: l.cost })),
  }), [address, delivery, note, lines]);

  const runPreview = useCallback(async (seed) => {
    const b = seed ? {} : body();           // seed=true → ask the server for the current lines
    try {
      const res = await apiFetch(`/orders/${order.item_id}/po-preview`, { method: "POST", body: JSON.stringify(b) });
      if (!res.ok) throw new Error(`preview ${res.status}`);
      const d = await res.json();
      setPreview(d);
      if (seed) {
        setLines((d.editable || []).map((e) => ({ sku: e.sku || "", item: e.item || "", qty: e.qty || "1", cost: e.cost ?? "" })));
        setAddress((d.dl || []).join("\n"));
        setDelivery(d.delivery != null ? String(d.delivery) : "");
      }
      return d;
    } catch (e) {
      if (String(e.message) !== "unauthorised") setMsg({ kind: "warn", text: String(e.message || e) });
      return null;
    }
  }, [apiFetch, order.item_id, body]);

  useEffect(() => { (async () => { setLoading(true); await runPreview(true); setLoading(false); })(); }, []); // eslint-disable-line

  function setLine(i, k, v) { setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l))); }
  function addLine() { setLines((ls) => [...ls, { sku: "", item: "", qty: "1", cost: "" }]); }
  function removeLine(i) { setLines((ls) => ls.filter((_, j) => j !== i)); }

  async function doPreview() { setBusy(true); setMsg(null); await runPreview(false); setBusy(false); }

  async function doGenerate() {
    setBusy(true); setMsg(null);
    try {
      const res = await apiFetch(`/orders/${order.item_id}/po`, { method: "POST", body: JSON.stringify(body()) });
      if (!res.ok) throw new Error(`po ${res.status}`);
      const d = await res.json();
      if (d.blocked) setMsg({ kind: "warn", text: "Can’t generate — " + (d.errors || []).join("; ") });
      else if (d.ok) {
        setMsg({ kind: "ok", text: `${d.kind === "po" ? "PO" : "Packing slip"} attached${d.total ? ` · £${Number(d.total).toFixed(2)}` : ""}` });
        flash("PO attached"); reload && reload();
      } else setMsg({ kind: "warn", text: d.detail || "Didn’t attach." });
    } catch (e) {
      if (String(e.message) !== "unauthorised") setMsg({ kind: "warn", text: String(e.message || e) });
    } finally { setBusy(false); }
  }

  const errs = preview?.errors || [];
  return (
    <>
      <div className="overlay" onClick={onClose} style={{ zIndex: 60 }} />
      <div className="po-modal">
        <div className="po-head">
          <div className="dh-ono">Edit PO · #{order.order_no}</div>
          <button className="icon-btn" onClick={onClose} title="Close"><IconX /></button>
        </div>
        {loading ? <div className="state"><span className="spinner" />Loading the order…</div> : (
          <div className="po-body">
            <div className="po-lines">
              <table className="editgrid">
                <thead><tr><th>SKU</th><th>Description</th><th className="qty">Qty</th><th className="cost">Cost £ (ex VAT)</th><th></th></tr></thead>
                <tbody>
                  {lines.map((l, i) => (
                    <tr key={i}>
                      <td><input value={l.sku} onChange={(e) => setLine(i, "sku", e.target.value)} /></td>
                      <td><input value={l.item} onChange={(e) => setLine(i, "item", e.target.value)} /></td>
                      <td className="qty"><input value={l.qty} onChange={(e) => setLine(i, "qty", e.target.value)} /></td>
                      <td className="cost"><input type="number" step="0.01" value={l.cost} placeholder="unpriced" onChange={(e) => setLine(i, "cost", e.target.value)} /></td>
                      <td><button className="icon-btn muted" onClick={() => removeLine(i)} title="Remove line"><IconX /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn" onClick={addLine}>+ Add line</button>
            </div>

            <div className="po-fields">
              <label className="fld"><span>Delivery address</span>
                <textarea rows={5} value={address} onChange={(e) => setAddress(e.target.value)} /></label>
              <div className="po-row2">
                <label className="fld"><span>Delivery £ (ex VAT) — blank = auto</span>
                  <input type="number" step="0.01" value={delivery} placeholder="auto" onChange={(e) => setDelivery(e.target.value)} /></label>
                <label className="fld"><span>Note on the PO (optional)</span>
                  <input value={note} onChange={(e) => setNote(e.target.value)} /></label>
              </div>

              {preview && (
                <div className="po-summary">
                  <div className="kv"><span>Document</span><b>{preview.kind === "po" ? "Purchase Order (priced)" : "Packing slip (no prices)"}</b></div>
                  {preview.goods != null && <div className="kv"><span>Goods (ex VAT)</span><b>£{Number(preview.goods).toFixed(2)}</b></div>}
                  {preview.delivery != null && <div className="kv"><span>Delivery (ex VAT)</span><b>£{Number(preview.delivery).toFixed(2)}</b></div>}
                  {preview.total != null && <div className="kv big"><span>Total (inc VAT)</span><b>£{Number(preview.total).toFixed(2)}</b></div>}
                  {preview.unpriced?.length ? <div className="warn-note"><IconWarn /> Unpriced (will be a packing slip until priced): {preview.unpriced.join(", ")}</div> : null}
                  {errs.length ? <div className="warn-note"><IconWarn /> {errs.join("; ")}</div> : null}
                </div>
              )}
              {msg && <div className={`route-msg ${msg.kind}`}>{msg.text}</div>}
            </div>
          </div>
        )}
        <div className="po-foot">
          <button className="btn" onClick={doPreview} disabled={busy || loading}>{busy ? "…" : "Preview"}</button>
          <button className="btn primary" onClick={doGenerate} disabled={busy || loading}>{busy ? "Working…" : "Generate & attach PO"}</button>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </>
  );
}
