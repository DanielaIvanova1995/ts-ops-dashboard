"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

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

/* Warn only if Monday's "£ to us" matches NEITHER the Shopify gross total NOR the ex-VAT subtotal
   (so a gross-vs-ex-VAT basis difference never false-alarms). Returns the Shopify total to show. */
function totalWarn(sell, t) {
  const s = num(sell);
  if (s === null || !t) return null;
  const cand = [t.total, t.subtotal].filter((x) => x !== null && x !== undefined);
  if (!cand.length) return null;
  const ok = cand.some((c) => Math.abs(s - c) <= Math.max(0.5, Math.abs(c) * 0.005));
  return ok ? null : (t.total ?? t.subtotal);
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
                    <tr key={o.item_id}>
                      <td className="ono"><button className="linkish" onClick={() => openDetail(o)}>{o.order_no}</button></td>
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
                          const w = totalWarn(o.sell, totals[o.item_id]);
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
                  <tr><td colSpan={8}><div className="state">No orders match.</div></td></tr>
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

      {drawer && <OrderDrawer order={drawer} detail={detail} err={detailErr} onClose={() => setDrawer(null)} />}
      {toast && <div className={`toast ${toast.kind === "err" ? "err" : ""}`}>{toast.msg}</div>}
    </div>
  );
}

function OrderDrawer({ order, detail, err, onClose }) {
  const sx = detail?.shopify;
  const cur = sx?.totals?.currency === "GBP" ? "£" : "£";
  const ship = sx?.shipping?.lines || [];
  const bill = sx?.billing?.lines || [];
  const addrDiffer = ship.length && bill.length && ship.join("|") !== bill.join("|");
  const sellWarn = sx?.totals ? totalWarn(order.sell, { total: sx.totals.total, subtotal: sx.totals.subtotal }) : null;
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-head">
          <div><span className="dh-ono">#{order.order_no}</span>{sx?.financial_status ? <span className="pill grey" style={{ marginLeft: 8 }}>{sx.financial_status}</span> : null}</div>
          <button className="icon-btn" onClick={onClose} title="Close"><IconX /></button>
        </div>

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
              <h4>Updates {detail.updates?.length ? <span className="pill grey">{detail.updates.length}</span> : null}</h4>
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
    </>
  );
}
