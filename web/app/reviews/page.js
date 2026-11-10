"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

const EXCL_LABEL = {
  not_delivered: "Not delivered", updates_4plus: "4+ updates (had an issue)",
  customer_stage_set: "Customer stage set (return/refund)", aftersales_set: "Aftersales set",
  already_reviewed: "Already asked / unhappy", no_email: "No valid email",
  suppressed: "Unsubscribed/suppressed", out_of_window: "Outside date window",
  eta_gap_too_long: "ETA gap too long", tier_b_excluded: "Tier B excluded", duplicate_customer: "Duplicate customer",
  split_incomplete: "Split order — part not delivered yet",
};

// Delivery statuses that count as "delivered" by default (Daniela's chosen set). Everything in the
// Delivered groups that's actually with / on its way to the customer; excludes problem/early states
// (Refused, Rescheduled, Route Planned, With Courier, blank, etc.).
const DELIVERED_DEFAULT = [
  "Delivered", "Booked For Delivery", "Out For Delivery", "Delivery in 24-48hrs",
  "AM Out For Delivery", "PM Out For Delivery", "Midday Delivery", "Posted",
  "Call for ETA", "Customer Collection",
];

function csvCell(v) { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
function download(name, text) {
  const blob = new Blob(["﻿" + text], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob); const a = document.createElement("a");
  a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}

export default function Reviews() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState(null);
  const [f, setF] = useState({ window_days: 30, max_gap: 5, max_updates: 3, include_b: true });
  const [delivered, setDelivered] = useState(DELIVERED_DEFAULT);   // which Delivery-status labels count (null = all)
  const [showDelivered, setShowDelivered] = useState(false);       // picker is collapsed by default
  const [sel, setSel] = useState(() => new Set());
  const [cfg, setCfg] = useState({});
  const [savingCfg, setSavingCfg] = useState(false);
  const [showCfg, setShowCfg] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [staff, setStaff] = useState("");
  const [send, setSend] = useState(null);     // send-status
  const [emailed, setEmailed] = useState(null);   // who's been emailed, grouped by count
  const [showEmailed, setShowEmailed] = useState(false);

  useEffect(() => { let k = null; try { k = localStorage.getItem(KEY_STORE); } catch {} if (k) setAccessKey(k); else setNeedKey(true); }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, { ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) } });
    if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    return res;
  }, [accessKey]);

  const load = useCallback(async (refresh = 0) => {
    if (!accessKey) return;
    setStatus("loading"); setErr("");
    try {
      const qs = `window_days=${f.window_days}&max_gap=${f.max_gap}&max_updates=${f.max_updates}&include_b=${f.include_b}&refresh=${refresh}&delivered=${encodeURIComponent((delivered || []).join(","))}`;
      const res = await jsonFetch(`/reviews?${qs}`);
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      // NB: don't setCfg here — a list refresh must not clobber settings the user is editing
      // (that re-showed the "set review link" banner). cfg is owned by loadCfg + saveCfg only.
      setData(d); setStatus("ok");
      setSel(new Set((d.rows || []).map((r) => r.item_id)));   // default: all selected
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch, f, delivered]);
  // Deliberately NO auto-load: the Monday pull is expensive, so the list loads only when you click
  // "Load list" / "Refresh". Changing a filter doesn't re-pull until you ask.

  // Load settings ONCE on sign-in, independent of the list. Only Save changes them after this, so a
  // list refresh can never wipe the review link (which was re-triggering the "set review link" banner).
  const loadCfg = useCallback(async () => {
    if (!accessKey) return;
    try {
      const res = await jsonFetch("/reviews/config");
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.config) setCfg(d.config);
    } catch {}
  }, [accessKey, jsonFetch]);
  useEffect(() => { loadCfg(); }, [loadCfg]);

  const loadEmailed = useCallback(async () => {
    if (!accessKey) return;
    try {
      const res = await jsonFetch("/reviews/emailed");
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) setEmailed(d);
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }, [accessKey, jsonFetch]);

  // Poll send status while a send is running.
  useEffect(() => {
    if (!send?.running) return;
    const t = setInterval(async () => {
      try { const r = await jsonFetch("/reviews/send-status"); const d = await r.json(); setSend(d); if (!d.running) { clearInterval(t); load(1); } } catch {}
    }, 2000);
    return () => clearInterval(t);
  }, [send?.running, jsonFetch, load]);

  function submitKey(e) { e.preventDefault(); const k = keyInput.trim(); if (!k) return; try { localStorage.setItem(KEY_STORE, k); } catch {} setAccessKey(k); setNeedKey(false); setKeyInput(""); }

  async function saveCfg() {
    setSavingCfg(true);
    try {
      const res = await jsonFetch("/reviews/config", { method: "POST", body: JSON.stringify(cfg) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) { setCfg(d.config); setNotice({ kind: "ok", text: "Settings saved." }); }
      else setNotice({ kind: "warn", text: d.detail || `Couldn’t save (API ${res.status}).` });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setSavingCfg(false); }
  }

  async function sendTest() {
    const emails = testTo.split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean).slice(0, 3);
    if (!emails.length) { setNotice({ kind: "warn", text: "Enter up to 3 test addresses." }); return; }
    try {
      const res = await jsonFetch("/reviews/send-test", { method: "POST", body: JSON.stringify({ emails }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) setNotice({ kind: "ok", text: `Sent ${d.sent.length} test email(s) to ${d.sent.join(", ")}.` });
      else setNotice({ kind: "warn", text: (d.errors && d.errors.join("; ")) || d.detail || `API ${res.status}` });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function doSend() {
    const ids = [...sel];
    if (!ids.length) { setNotice({ kind: "warn", text: "Nobody selected." }); return; }
    if (!(cfg.review_link || "").trim()) { setNotice({ kind: "warn", text: "Set the review link in Settings first." }); return; }
    const msg = `Send the review email to ${ids.length} customer${ids.length === 1 ? "" : "s"}?\n\n`
      + `From: ${cfg.from_mailbox}\nReply-to: ${cfg.reply_to}\nSubject: ${cfg.subject}\n\n`
      + `It sends at ${cfg.throttle_per_min}/min, max ${cfg.batch_cap} per batch, and skips anyone unsubscribed. This cannot be undone.`;
    if (!window.confirm(msg)) return;
    try {
      const res = await jsonFetch("/reviews/send", { method: "POST", body: JSON.stringify({ item_ids: ids, ...f, delivered: delivered || [] }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) { setNotice({ kind: "ok", text: `Sending to ${d.total}${d.capped ? " (capped to the batch limit)" : ""}…` }); setSend({ running: true, done: 0, total: d.total, ok: 0, failed: 0 }); }
      else setNotice({ kind: "warn", text: d.detail || `API ${res.status}` });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }
  async function stopSend() { try { await jsonFetch("/reviews/send-stop", { method: "POST" }); } catch {} }

  const rows = data?.rows || [];
  const shownSel = rows.filter((r) => sel.has(r.item_id));
  function exportCsv() {
    const head = ["Tier", "Order", "Customer", "Order date", "ETA", "Gap (days)", "Manual updates", "Times emailed", "Email", "Phone"];
    const out = shownSel.map((r) => [r.tier, r.order_no, r.name, r.order_date, r.eta || "", r.gap ?? "", r.n_updates, r.times_emailed || 0, r.email, r.phone || ""]);
    download(`review_requests_${new Date().toISOString().slice(0, 10)}.csv`, [head, ...out].map((row) => row.map(csvCell).join(",")).join("\r\n"));
  }
  function exportCallList() {
    const names = staff.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
    const withPhone = shownSel.filter((r) => (r.phone || "").trim());
    const head = ["Assigned to", "Phone", "Customer", "Order"];
    const out = withPhone.map((r, i) => [names.length ? names[i % names.length] : "", r.phone, r.name, r.order_no]);
    download(`call_list_${new Date().toISOString().slice(0, 10)}.csv`, [head, ...out].map((row) => row.map(csvCell).join(",")).join("\r\n"));
  }

  if (needKey) {
    return (<div className="wrap"><div className="login"><img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" />
      <div className="wordmark">Trade<b>Hub</b><span className="sec">Reviews</span></div>
      <p className="sub">Enter the access code to continue.</p>
      <form onSubmit={submitKey} className="loginform"><input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" /><button className="btn primary" type="submit">Enter</button></form>
    </div></div>);
  }

  const t = data?.counts; const ex = data?.excluded || {};
  const allSel = rows.length > 0 && sel.size === rows.length;

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Review Requests</div>
        <div className="right">
          <button className="btn ghost" onClick={() => { setShowEmailed((v) => { const next = !v; if (next) loadEmailed(); return next; }); }}>📧 Emailed</button>
          <button className="btn ghost" onClick={() => setShowCfg((v) => !v)}>⚙ Settings</button>
          <button className="btn primary" onClick={() => load(1)} disabled={status === "loading"}>{status === "loading" ? "Loading…" : (data ? "↻ Refresh" : "Load list")}</button>
        </div>
      </div>

      {notice && <div className={`route-msg ${notice.kind}`} style={{ marginBottom: 12 }}>{notice.text}</div>}
      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}
      {!(cfg.review_link || "").trim() && <div className="route-msg warn" style={{ marginBottom: 12 }}>⚠ Set your <b>review link</b> in ⚙ Settings before sending — that's the page the button points customers to.</div>}

      {showEmailed && (
        <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <div className="tool-label" style={{ margin: 0 }}>Emailed — who's had a review request</div>
            <span className="sub" style={{ flex: 1 }}>{emailed ? `${emailed.total_people} people · ${emailed.total_sends} emails sent` : "Loading…"}</span>
            <button className="btn ghost" onClick={loadEmailed}>↻ Refresh</button>
            <button className="btn ghost" onClick={() => setShowEmailed(false)}>Close</button>
          </div>
          {emailed && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(230px,1fr))", gap: 12 }}>
              {[["Emailed once", emailed.emailed_1, "green"], ["Emailed twice", emailed.emailed_2, "amber"], ["Emailed 3+ times", emailed.emailed_3plus, "red"]].map(([title, list, cls]) => (
                <div key={title} style={{ border: "1px solid var(--line,#e5e7eb)", borderRadius: 10, overflow: "hidden" }}>
                  <div style={{ padding: "7px 10px", fontWeight: 600, fontSize: 13, display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(127,127,127,0.05)" }}>
                    <span>{title}</span><span className={`chip ${cls}`}>{(list || []).length}</span>
                  </div>
                  <div style={{ maxHeight: 320, overflowY: "auto" }}>
                    {(list || []).length === 0 && <div className="sub" style={{ padding: "8px 10px", fontSize: 12 }}>Nobody yet.</div>}
                    {(list || []).map((p) => (
                      <div key={p.email} style={{ padding: "6px 10px", borderTop: "1px solid var(--line,#eee)", fontSize: 12 }}>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.email}>{p.email}</div>
                        <div className="sub" style={{ fontSize: 11 }}>{p.count}× · last {p.last_sent ? String(p.last_sent).slice(0, 10) : "—"}{p.orders && p.orders.length ? ` · order ${p.orders.slice(0, 3).join(", ")}` : ""}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: 10 }}>
            <button className="btn ghost" disabled={!emailed} onClick={() => {
              const all = emailed ? [...emailed.emailed_1, ...emailed.emailed_2, ...emailed.emailed_3plus] : [];
              const r = [["Email", "Times emailed", "Last sent", "Orders"]].concat(all.map((p) => [p.email, p.count, p.last_sent || "", (p.orders || []).join(" ")]));
              download(`emailed_${new Date().toISOString().slice(0, 10)}.csv`, r.map((row) => row.map(csvCell).join(",")).join("\r\n"));
            }}>⬇ CSV of everyone emailed</button>
          </div>
        </div>
      )}

      {!data && status !== "loading" && !err && (
        <div className="card" style={{ padding: "18px 16px", marginBottom: 12, textAlign: "center" }}>
          <div className="sub" style={{ marginBottom: 10 }}>The list isn’t loaded automatically (it reads a lot from Monday). Set your filters, then load it when you’re ready.</div>
          <button className="btn primary" onClick={() => load(1)}>Load review list</button>
        </div>
      )}
      {status === "loading" && !data && <div className="sub" style={{ marginBottom: 12 }}>Reading delivered orders from Monday…</div>}

      {showCfg && (
        <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
          <div className="tool-label" style={{ marginBottom: 8 }}>Settings</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: 10 }}>
            <label className="sub">Review link (button URL)<input className="input" style={{ width: "100%" }} value={cfg.review_link || ""} onChange={(e) => setCfg((c) => ({ ...c, review_link: e.target.value }))} placeholder="https://g.page/r/…/review" /></label>
            <label className="sub">Send from<input className="input" style={{ width: "100%" }} value={cfg.from_mailbox || ""} onChange={(e) => setCfg((c) => ({ ...c, from_mailbox: e.target.value }))} /></label>
            <label className="sub">Reply-to<input className="input" style={{ width: "100%" }} value={cfg.reply_to || ""} onChange={(e) => setCfg((c) => ({ ...c, reply_to: e.target.value }))} /></label>
            <label className="sub">Subject<input className="input" style={{ width: "100%" }} value={cfg.subject || ""} onChange={(e) => setCfg((c) => ({ ...c, subject: e.target.value }))} /></label>
            <label className="sub">Send rate (per min)<input className="input" type="number" min="1" max="120" style={{ width: "100%" }} value={cfg.throttle_per_min || 20} onChange={(e) => setCfg((c) => ({ ...c, throttle_per_min: Number(e.target.value) }))} /></label>
            <label className="sub">Max per batch<input className="input" type="number" min="1" max="500" style={{ width: "100%" }} value={cfg.batch_cap || 100} onChange={(e) => setCfg((c) => ({ ...c, batch_cap: Number(e.target.value) }))} /></label>
          </div>
          <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn primary" onClick={saveCfg} disabled={savingCfg}>{savingCfg ? "Saving…" : "Save settings"}</button>
            <span style={{ flex: 1 }} />
            <input className="search" style={{ maxWidth: 260 }} placeholder="Test address(es), up to 3" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
            <button className="btn" onClick={sendTest}>Send test</button>
          </div>
          <div className="sub" style={{ marginTop: 6, fontSize: 12 }}>Merge fields in the email: {"{{first_name}}"}, {"{{order_no}}"}, {"{{review_link}}"}. Every email has a one-click unsubscribe + your business details.</div>
        </div>
      )}

      {/* Filters */}
      <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <label className="sub">Last <input className="input" type="number" min="0" style={{ width: 64 }} value={f.window_days} onChange={(e) => setF((x) => ({ ...x, window_days: Number(e.target.value) }))} /> days</label>
        <label className="sub">Max ETA gap <input className="input" type="number" min="0" style={{ width: 56 }} value={f.max_gap} onChange={(e) => setF((x) => ({ ...x, max_gap: Number(e.target.value) }))} /> days</label>
        <label className="sub" title="Counts MANUAL updates only — automated updates (ETA emails, order-processing notes) are ignored.">Max manual updates <input className="input" type="number" min="0" style={{ width: 56 }} value={f.max_updates} onChange={(e) => setF((x) => ({ ...x, max_updates: Number(e.target.value) }))} /></label>
        <label className="sub"><input type="checkbox" checked={f.include_b} onChange={(e) => setF((x) => ({ ...x, include_b: e.target.checked }))} /> Include Tier B (no ETA)</label>
      </div>

      {/* Which Delivery statuses count as delivered. Collapsed by default — a chosen set is baked in,
          so she only opens this if she wants to change it. */}
      {data?.delivery_dist && Object.keys(data.delivery_dist).length > 0 && (() => {
        const allLabels = Object.keys(data.delivery_dist);
        const isAll = delivered === null;
        const countOn = isAll ? allLabels.length : delivered.length;
        const isOn = (label) => isAll || delivered.some((s) => s.toLowerCase() === label.toLowerCase());
        const toggle = (label, checked) => setDelivered((prev) => {
          const cur = prev === null ? allLabels.slice() : prev.slice();
          const next = checked
            ? (cur.some((s) => s.toLowerCase() === label.toLowerCase()) ? cur : [...cur, label])
            : cur.filter((s) => s.toLowerCase() !== label.toLowerCase());
          return allLabels.every((l) => next.some((s) => s.toLowerCase() === l.toLowerCase())) ? null : next;
        });
        return (
          <div className="card" style={{ padding: "8px 14px", marginBottom: 12 }}>
            <div className="sub" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span>Counting <b>{isAll ? "all" : countOn}</b> delivery status{countOn === 1 ? "" : "es"} as delivered.</span>
              <button className="btn ghost" style={{ padding: "1px 8px" }} onClick={() => setShowDelivered((v) => !v)}>{showDelivered ? "Hide" : "Change"}</button>
            </div>
            {showDelivered && (
              <>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
                  {Object.entries(data.delivery_dist).map(([label, n]) => {
                    const on = isOn(label);
                    return (
                      <label key={label} className="sub" style={{ display: "inline-flex", alignItems: "center", gap: 5,
                        padding: "3px 8px", border: "1px solid var(--line, #d9dce1)", borderRadius: 6,
                        background: on ? "var(--accent-weak, #e8f0ff)" : "transparent" }}>
                        <input type="checkbox" checked={on} onChange={(e) => toggle(label, e.target.checked)} />
                        {label} <b>{n}</b>
                      </label>
                    );
                  })}
                </div>
                <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                  <button className="btn ghost" style={{ padding: "1px 8px" }} onClick={() => setDelivered(DELIVERED_DEFAULT)}>Reset to default</button>
                  <button className="btn ghost" style={{ padding: "1px 8px" }} onClick={() => setDelivered(null)}>Tick all</button>
                </div>
              </>
            )}
          </div>
        );
      })()}

      {t && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
          <span className="chip green"><b>{t.A}</b> Tier A (verified fast)</span>
          <span className="chip amber"><b>{t.B}</b> Tier B (clean, no ETA)</span>
          <span className="chip grey"><b>{t.total}</b> total · {sel.size} selected</span>
          <span className="sub" style={{ fontSize: 12 }}>scanned {data.total_scanned} orders{data.cached_at ? ` · as of ${String(data.cached_at).slice(11, 16)}` : ""}</span>
          <span style={{ flex: 1 }} />
          <button className="btn ghost" onClick={exportCsv} disabled={!shownSel.length}>⬇ CSV</button>
          <input className="search" style={{ maxWidth: 180 }} placeholder="Staff names (comma)" value={staff} onChange={(e) => setStaff(e.target.value)} />
          <button className="btn ghost" onClick={exportCallList} disabled={!shownSel.length}>⬇ Call list</button>
        </div>
      )}

      {/* Exclusions */}
      {Object.keys(ex).length > 0 && (
        <div className="card" style={{ padding: "8px 14px", marginBottom: 12 }}>
          <span className="sub" style={{ fontWeight: 600, marginRight: 8 }}>Excluded:</span>
          {Object.entries(ex).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
            <span key={k} className="chip grey" style={{ marginRight: 6 }}>{EXCL_LABEL[k] || k}: <b>{v}</b></span>
          ))}
        </div>
      )}

      {/* Send bar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        {send?.running
          ? <><span className="spinner" /> <b>Sending {send.done}/{send.total}</b> <span className="sub">({send.ok} ok, {send.failed} failed)</span> <button className="btn ghost" onClick={stopSend}>Stop</button></>
          : <button className="btn primary" onClick={doSend} disabled={!sel.size || !(cfg.review_link || "").trim()}>Send to selected ({sel.size})</button>}
        {(() => { const n = rows.filter((r) => r.times_emailed > 0).length; return n > 0 && !send?.running
          ? <button className="btn ghost" onClick={() => setSel(new Set(rows.filter((r) => !r.times_emailed).map((r) => r.item_id)))} title="Untick anyone who has already had a review email (even for a different order)">Deselect already-emailed ({n})</button>
          : null; })()}
        {send && !send.running && send.total ? <span className="sub">Last run: {send.ok} sent, {send.failed} failed.</span> : null}
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto" }}>
        <table className="mini">
          <thead><tr>
            <th style={{ width: 24 }}><input type="checkbox" title="Select all / none" checked={allSel} ref={(el) => { if (el) el.indeterminate = sel.size > 0 && sel.size < rows.length; }} onChange={() => setSel(allSel ? new Set() : new Set(rows.map((r) => r.item_id)))} /></th>
            <th>Tier</th><th>Order</th><th>Customer</th><th>Order date</th><th>ETA</th><th className="num">Gap</th><th className="num" title="Manual updates (automations ignored)">Upd</th><th className="num" title="Times this customer has already had a review email">Emailed</th><th>Email</th><th>Phone</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.item_id}>
                <td><input type="checkbox" checked={sel.has(r.item_id)} onChange={() => setSel((s) => { const n = new Set(s); n.has(r.item_id) ? n.delete(r.item_id) : n.add(r.item_id); return n; })} /></td>
                <td><span className={`chip ${r.tier === "A" ? "green" : "amber"}`}>{r.tier}</span></td>
                <td className="ono">{r.order_no}</td>
                <td>{r.name || "—"}</td>
                <td className="sub">{r.order_date || "—"}</td>
                <td className="sub">{r.eta || "—"}</td>
                <td className="num">{r.gap ?? "—"}</td>
                <td className="num">{r.n_updates}</td>
                <td className="num">{r.times_emailed ? <span className="chip amber">{r.times_emailed}×</span> : "—"}</td>
                <td className="sub">{r.email}</td>
                <td className="sub">{r.phone || "—"}</td>
              </tr>
            ))}
            {status === "ok" && rows.length === 0 && <tr><td colSpan={11}><div className="state">No orders qualify with these filters.</div></td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
