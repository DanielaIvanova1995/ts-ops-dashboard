"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

const STATUS_PILL = {
  fulfil: ["green", "Fulfil + tracking"],
  eta: ["blue", "Set ETA"],
  done: ["grey", "Already done"],
  no_match: ["red", "No Monday match"],
  skip: ["amber", "Skip"],
};

export default function Stream() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState(null);

  useEffect(() => { let k = null; try { k = localStorage.getItem(KEY_STORE); } catch {} if (k) setAccessKey(k); else setNeedKey(true); }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, { ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) } });
    if (res.status === 401 || res.status === 403) {
      if (res.status === 403 && path.endsWith("/run")) return res;
      try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised");
    }
    return res;
  }, [accessKey]);

  const preview = useCallback(async () => {
    if (!accessKey) return;
    setStatus("loading"); setErr(""); setRunResult(null); setReviewed(false);
    try {
      const res = await jsonFetch("/stream/dry-run");
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      setData(d); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch]);

  async function run() {
    if (!data || !reviewed) return;
    setRunning(true); setRunResult(null);
    try {
      const res = await jsonFetch("/stream/run", { method: "POST", body: JSON.stringify({ job_nos: [] }) });
      const d = await res.json().catch(() => ({}));
      if (res.status === 403 || d.ok === false) { setRunResult({ blocked: true, detail: d.detail || "Live processing is off." }); return; }
      setRunResult(d);
      await preview();   // refresh — fulfilled orders drop off / flip to done
    } catch (e) { if (String(e.message) !== "unauthorised") setRunResult({ blocked: true, detail: String(e.message || e) }); }
    finally { setRunning(false); }
  }

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="topbar"><div className="pagetitle">National Skirting · Stream</div></div>
        <form className="card" onSubmit={submitKey} style={{ padding: 16, maxWidth: 420 }}>
          <div className="sub" style={{ marginBottom: 8 }}>Enter your TradeHub access key.</div>
          <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access key" />
          <button className="btn primary" style={{ marginTop: 10 }}>Unlock</button>
        </form>
      </div>
    );
  }

  const plans = (data?.plans || []);
  const live = data?.live_enabled;

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">National Skirting · Stream tracking</div>
        <div className="right">
          <button className="btn" onClick={preview} disabled={status === "loading"}>{status === "loading" ? "Checking…" : "↻ Preview"}</button>
        </div>
      </div>

      <div className="sub" style={{ marginBottom: 12 }}>
        Reads the Stream (go2stream) tracking emails in hello@ / orders@, matches each to its Shopify order by
        the <b>Job no.</b> on Monday, and — on processing — fulfils with courier <b>Other</b> + the tracking link,
        <b> notifies the customer</b>, posts the link to Monday, and sets the Customer ETA when the email carries a
        delivery date. Already-fulfilled orders are never fulfilled or emailed twice.
      </div>

      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}

      {data && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="inv-controls" style={{ flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            <span className="pill red">{data.count} order{data.count === 1 ? "" : "s"}</span>
            {data.n_fulfil > 0 && <span className="pill green">{data.n_fulfil} to fulfil</span>}
            {data.n_eta > 0 && <span className="pill blue">{data.n_eta} ETA to set</span>}
            {data.n_no_match > 0 && <span className="pill amber">{data.n_no_match} no Monday match</span>}
            <span style={{ flex: 1 }} />
            {!live && <span className="pill amber" title="Set STREAM_LIVE=1 on the API to enable live processing">Live is OFF</span>}
            <label style={{ display: "flex", alignItems: "center", gap: 6, opacity: live ? 1 : 0.5 }}>
              <input type="checkbox" checked={reviewed} disabled={!live || !data.count} onChange={(e) => setReviewed(e.target.checked)} />
              I’ve reviewed these
            </label>
            <button className="btn primary" onClick={run} disabled={!live || !reviewed || running || !data.count}
              title={live ? "Fulfil + notify customers + update Monday for every order above" : "Live processing is off"}>
              {running ? "Processing…" : "⚡ Process (fulfils + emails customers)"}
            </button>
          </div>
        </div>
      )}

      {runResult && (
        <div className={`route-msg ${runResult.blocked ? "warn" : "ok"}`} style={{ marginBottom: 12 }}>
          {runResult.blocked ? runResult.detail : <b>Processed {runResult.processed} order(s).</b>}
          {!runResult.blocked && (runResult.results || []).map((r, i) => (
            <div key={i} className="sub" style={{ marginTop: 4 }}>
              {r.status === "ok" ? "✓" : r.status === "error" ? "⚠️" : "—"} {r.order_no || r.job_no}
              {r.customer ? ` · ${r.customer}` : ""} — {(r.steps || []).join("; ")}
            </div>
          ))}
        </div>
      )}

      <div className="inv-list">
        {plans.map((p) => {
          const [cls, label] = STATUS_PILL[p.status] || ["grey", p.status];
          return (
            <div className="card inv-card" key={p.job_no}>
              <div className="inv-head">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span className="ono">{p.order_no ? `#${p.order_no}` : `Job ${p.job_no}`}</span>
                    <span className={`pill ${cls}`}>{label}</span>
                    {p.emails_for_order > 1 && <span className="pill grey">{p.emails_for_order} emails</span>}
                  </div>
                  <div className="sub" style={{ marginTop: 3 }}>
                    {p.customer || "—"} · Job no. {p.job_no}{p.do?.set_eta ? ` · ETA → ${p.do.set_eta}` : ""}
                  </div>
                  <div className="sub" style={{ marginTop: 3 }}>{p.note}</div>
                </div>
                <div className="inv-right">
                  {p.tracking_url && <a className="btn ghost" href={p.tracking_url} target="_blank" rel="noreferrer">Tracking ↗</a>}
                </div>
              </div>
            </div>
          );
        })}
        {data && plans.length === 0 && <div className="card"><div className="state">No Stream tracking emails to process.</div></div>}
        {!data && status !== "loading" && <div className="card"><div className="state">Hit <b>Preview</b> to check for new Stream tracking emails.</div></div>}
      </div>
    </div>
  );
}
