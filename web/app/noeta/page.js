"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

// The two suppliers wired in so far. Each has a preview (dry-run) and a live run endpoint.
const SUPPLIERS = {
  carron: {
    label: "Carron",
    preview: "/noeta/carron/dry-run",
    run: "/noeta/carron/run",
    folder: "“Natasha - Supplier - No ETA”",
    blurb: "Classifies each Carron email. Booked-in → set the Customer ETA + archive to NV Resolved. Order confirmation → validate vs Shopify + margin, attach to the Job column + move to Supplier-ETAs (with a note to ring the customer). Problems → left for a human.",
    tiles: (t) => [["Set ETA + archive", t.archive, "green"], ["→ Supplier-ETAs", t.to_etas, "blue"], ["Flag — review", t.flag, "red"], ["Leave", t.leave, "grey"], ["Superseded", t.superseded, "grey"]],
  },
  lpd: {
    label: "LPD",
    preview: "/noeta/lpd/dry-run",
    run: "/noeta/lpd/run",
    folder: "“Sales Orders”",
    blurb: "Pulls our order ref + lines from each LPD PDF and validates vs Shopify + full money-check. Validated → attach to the Job column + archive to NV Resolved. Backorder / amended / unmatched → flagged for a human.",
    tiles: (t) => [["Archive to NV Resolved", t.archive, "green"], ["Flag — review", t.flag, "red"]],
  },
};

// Colour + label for each planned action.
function planStyle(p) {
  const s = p.plan || "";
  if (p.superseded) return { cls: "grey", tag: "Superseded" };
  if (s.startsWith("FLAG")) return { cls: "red", tag: "Flag — review" };
  if (s.includes("ARCHIVE") && p.action === "booked_in") return { cls: "green", tag: "Set ETA + archive" };
  if (s.includes("ARCHIVE")) return { cls: "green", tag: "Archive" };
  if (s.startsWith("MOVE")) return { cls: "blue", tag: "→ Supplier-ETAs" };
  if (s.startsWith("LEAVE")) return { cls: "grey", tag: "Leave" };
  return { cls: "amber", tag: p.action };
}

export default function NoEta() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [supplier, setSupplier] = useState("carron");
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [runResult, setRunResult] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => { let k = null; try { k = localStorage.getItem(KEY_STORE); } catch {} if (k) setAccessKey(k); else setNeedKey(true); }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, { ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) } });
    if (res.status === 401 || res.status === 403) {
      // 403 can also be the kill-switch on /run — only treat an AUTH 403 as a sign-out.
      if (res.status === 403 && path.endsWith("/run")) return res;
      try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised");
    }
    return res;
  }, [accessKey]);

  const preview = useCallback(async (sup) => {
    const s = sup || supplier;
    if (!accessKey) return;
    setStatus("loading"); setErr(""); setRunResult(null);
    try {
      const res = await jsonFetch(SUPPLIERS[s].preview);
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      setData(d); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch, supplier]);

  const runLive = useCallback(async () => {
    if (!accessKey || !data) return;
    const t = data.counts || {};
    const willAct = (t.archive || 0) + (t.to_etas || 0) + (t.superseded || 0);
    if (!window.confirm(`Process ${SUPPLIERS[supplier].label} LIVE now?\n\nThis will move ${willAct} email${willAct === 1 ? "" : "s"} out of the folder and write to Monday (ETAs, notes, Job-column files) for the validated/booked-in orders. Flagged ones are left untouched.\n\nThis can't be auto-undone.`)) return;
    setRunning(true); setErr("");
    try {
      const res = await jsonFetch(SUPPLIERS[supplier].run, { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (res.status === 403) { setErr(d.detail || "Live processing is switched off."); setRunning(false); return; }
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      setRunResult(d);
      await preview();   // refresh the plan — processed emails have left the folder
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    setRunning(false);
  }, [accessKey, data, jsonFetch, supplier, preview]);

  function pickSupplier(s) { if (s === supplier) return; setSupplier(s); setData(null); setStatus("idle"); setErr(""); setRunResult(null); }
  function submitKey(e) { e.preventDefault(); const k = keyInput.trim(); if (!k) return; try { localStorage.setItem(KEY_STORE, k); } catch {} setAccessKey(k); setNeedKey(false); setKeyInput(""); }

  if (needKey) {
    return (
      <div className="wrap"><div className="topbar"><div className="pagetitle">Supplier Confirms</div></div>
        <form onSubmit={submitKey} className="card" style={{ padding: 16, maxWidth: 420 }}>
          <div className="sub" style={{ marginBottom: 8 }}>Enter your TradeHub access key.</div>
          <input className="input" type="password" value={keyInput} onChange={(e) => setKeyInput(e.target.value)} style={{ width: "100%" }} />
          <button className="btn primary" style={{ marginTop: 10 }}>Unlock</button>
        </form>
      </div>
    );
  }

  const cfg = SUPPLIERS[supplier];
  const t = data?.counts;
  const noun = cfg.label;
  const liveOff = data && data.live_enabled === false;
  const actionable = data ? (data.counts?.archive || 0) + (data.counts?.to_etas || 0) + (data.counts?.superseded || 0) : 0;
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Supplier Confirms — {cfg.label}</div>
        <div className="right" style={{ display: "flex", gap: 6 }}>
          <button className="btn" onClick={() => preview()} disabled={status === "loading" || running}>{status === "loading" ? "Reading…" : (data ? "↻ Re-check" : "Run preview")}</button>
          <button className="btn primary" onClick={runLive} disabled={!data || running || liveOff || actionable === 0}
            title={liveOff ? "Live processing is switched off (NOETA_LIVE)" : "Execute the plan: move emails + write to Monday"}>
            {running ? "Processing…" : `⚡ Process live${actionable ? ` (${actionable})` : ""}`}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {Object.entries(SUPPLIERS).map(([k, v]) => (
          <button key={k} onClick={() => pickSupplier(k)} className={`btn ${k === supplier ? "primary" : ""}`} style={{ fontSize: 13 }}>{v.label}</button>
        ))}
      </div>

      <div className="route-msg" style={{ marginBottom: 12, background: "rgba(0,126,181,0.08)", border: "1px solid rgba(0,126,181,0.25)" }}>
        <b>Preview first, then process.</b> “Run preview” shows what <i>would</i> happen to each {noun} email in the {cfg.folder} folder — nothing moves.
        {" "}“⚡ Process live” then carries it out: writes ETAs/notes, attaches confirmations to the <b>Job</b> column, and moves emails to their folders. Flagged ones are always left in place.
        {liveOff && <div className="th-red" style={{ marginTop: 6 }}><b>Live processing is currently switched off</b> (NOETA_LIVE). Previews still work.</div>}
      </div>

      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}

      {runResult && (
        <div className="card" style={{ padding: "4px 0", marginBottom: 12, border: "1px solid rgba(40,167,69,0.35)" }}>
          <div className="sub" style={{ padding: "8px 14px" }}>
            <b>Live run done</b> · {runResult.n_done} processed{runResult.n_partial ? ` · ${runResult.n_partial} partial` : ""}{runResult.n_skipped ? ` · ${runResult.n_skipped} already done` : ""}
          </div>
          {(runResult.results || []).map((r, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--line,#eee)", padding: "7px 14px", fontSize: 12.5 }}>
              <span className={`chip ${r.status === "done" ? "green" : r.status === "partial" ? "red" : "grey"}`} style={{ marginRight: 8 }}>{r.status}</span>
              <b>{r.order_no ? `Order ${r.order_no}` : "(order?)"}</b>
              {r.steps && <span className="sub"> — {r.steps.join(" · ")}</span>}
              {r.note && <span className="sub"> — {r.note}</span>}
            </div>
          ))}
        </div>
      )}

      {!data && status !== "loading" && !err && (
        <div className="card" style={{ padding: "18px 16px", textAlign: "center" }}>
          <div className="sub" style={{ marginBottom: 10 }}>{cfg.blurb}</div>
          <button className="btn primary" onClick={() => preview()}>Run preview</button>
        </div>
      )}

      {t && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 8, marginBottom: 12 }}>
          {cfg.tiles(t).map(([lab, n, cls]) => (
            <div key={lab} style={{ border: "1px solid rgba(127,127,127,0.16)", borderRadius: 9, padding: "8px 12px", background: "rgba(127,127,127,0.04)" }}>
              <div className="sub" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.3 }}>{lab}</div>
              <div style={{ fontSize: 18, fontWeight: 700 }} className={n > 0 && cls === "red" ? "th-red" : ""}>{n}</div>
            </div>
          ))}
        </div>
      )}

      {data && (
        <div className="card" style={{ padding: "4px 0", marginBottom: 12 }}>
          <div className="sub" style={{ padding: "8px 14px" }}>{data.n_emails} {noun} email{data.n_emails === 1 ? "" : "s"} in the folder</div>
          {(data.plan || []).map((p, i) => {
            const st = planStyle(p);
            const v = p.validation;
            return (
              <div key={i} style={{ borderTop: "1px solid var(--line,#eee)", padding: "10px 14px", display: "flex", gap: 10, alignItems: "flex-start" }}>
                <span className={`chip ${st.cls}`} style={{ whiteSpace: "nowrap" }}>{st.tag}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{p.order_no ? `Order ${p.order_no}` : "(no order no)"}{p.eta ? ` · ETA ${p.eta}` : ""}</div>
                  <div className="sub" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.subject}>{p.subject || ""}</div>
                  <div style={{ fontSize: 12, marginTop: 3 }}>{p.plan}</div>
                  {v && v.issues && v.issues.length > 0 && (
                    <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12 }}>
                      {v.issues.map((iss, j) => <li key={j} className="th-red">{iss}</li>)}
                    </ul>
                  )}
                  {v && v.verdict === "validated" && typeof v.margin_pct === "number" && (
                    <div className="sub" style={{ fontSize: 11, marginTop: 2 }}>margin {v.margin_pct}% after fee</div>
                  )}
                </div>
              </div>
            );
          })}
          {(data.plan || []).length === 0 && <div className="sub" style={{ padding: "10px 14px" }}>No {noun} emails in the folder right now.</div>}
        </div>
      )}
    </div>
  );
}
