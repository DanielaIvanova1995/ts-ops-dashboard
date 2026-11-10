"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

// The two suppliers wired into the dry-run so far. Each has its own endpoint, folder and count tiles.
const SUPPLIERS = {
  carron: {
    label: "Carron",
    endpoint: "/noeta/carron/dry-run",
    folder: "“Natasha - Supplier - No ETA”",
    blurb: "Reads the folder, classifies each Carron email, and (for order confirmations) validates it against Shopify + margin.",
    tiles: (t) => [["Set ETA + archive", t.archive, "green"], ["→ Supplier-ETAs", t.to_etas, "blue"], ["Flag — review", t.flag, "red"], ["Leave", t.leave, "grey"], ["Superseded", t.superseded, "grey"]],
  },
  lpd: {
    label: "LPD",
    endpoint: "/noeta/lpd/dry-run",
    folder: "“Sales Orders”",
    blurb: "Reads the Sales Orders subfolder, pulls our order ref + lines from each LPD PDF, and validates against Shopify + full money-check. Validated ones have their PDF attached to the order's Job column live; backorder / amended confirmations are flagged for a human.",
    tiles: (t) => [["Archive to NV Resolved", t.archive, "green"], ["Attached to Job", t.attached, "blue"], ["Flag — review", t.flag, "red"]],
    attachNote: true,
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

  useEffect(() => { let k = null; try { k = localStorage.getItem(KEY_STORE); } catch {} if (k) setAccessKey(k); else setNeedKey(true); }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, { ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) } });
    if (res.status === 401 || res.status === 403) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    return res;
  }, [accessKey]);

  const run = useCallback(async (sup) => {
    const s = sup || supplier;
    if (!accessKey) return;
    setStatus("loading"); setErr("");
    try {
      const res = await jsonFetch(SUPPLIERS[s].endpoint);
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.ok) throw new Error(d.detail || `API ${res.status}`);
      setData(d); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch, supplier]);

  function pickSupplier(s) { if (s === supplier) return; setSupplier(s); setData(null); setStatus("idle"); setErr(""); }

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
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Supplier Confirms — {cfg.label}</div>
        <div className="right">
          <button className="btn primary" onClick={() => run()} disabled={status === "loading"}>{status === "loading" ? "Reading folder…" : (data ? "↻ Re-run" : "Run dry-run")}</button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
        {Object.entries(SUPPLIERS).map(([k, v]) => (
          <button key={k} onClick={() => pickSupplier(k)}
            className={`btn ${k === supplier ? "primary" : ""}`}
            style={{ fontSize: 13 }}>{v.label}</button>
        ))}
      </div>

      <div className="route-msg" style={{ marginBottom: 12, background: "rgba(0,126,181,0.08)", border: "1px solid rgba(0,126,181,0.25)" }}>
        {cfg.attachNote ? (
          <>
            <b>Validated confirmations are attached to Monday live.</b> When an {noun} confirmation passes the
            money-check, its PDF is attached to the order&rsquo;s <b>Job</b> column straight away. The <i>email
            archiving</i> stays a dry run — nothing is moved out of the {cfg.folder} folder until switched on.
          </>
        ) : (
          <>
            <b>Dry run — nothing moves.</b> This shows what the automation <i>would</i> do to each {noun} email in the
            {" "}{cfg.folder} folder. Review it; the live moves stay off until switched on.
          </>
        )}
      </div>

      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}
      {!data && status !== "loading" && !err && (
        <div className="card" style={{ padding: "18px 16px", textAlign: "center" }}>
          <div className="sub" style={{ marginBottom: 10 }}>{cfg.blurb}</div>
          <button className="btn primary" onClick={() => run()}>Run dry-run</button>
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
                  {p.attached && (
                    <div style={{ fontSize: 11.5, marginTop: 2 }}
                      className={/fail|error|no pdf/i.test(p.attached) ? "th-red" : "sub"}>📎 {p.attached}</div>
                  )}
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
