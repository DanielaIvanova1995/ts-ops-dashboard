"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function StatusPill({ s }) {
  const map = { moved: "green", filed: "green", skipped: "grey", failed: "red", preview: "amber" };
  return <span className={`pill ${map[s] || "grey"}`}>{s || "—"}</span>;
}

export default function Triage() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [days, setDays] = useState(7);
  const [cap, setCap] = useState(40);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [notice, setNotice] = useState(null);

  const [cfg, setCfg] = useState(null);       // { auto_enabled, interval_min, ... }
  const [lastRun, setLastRun] = useState(null);
  const [savingCfg, setSavingCfg] = useState(false);
  const [problems, setProblems] = useState([]);

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

  const loadStatus = useCallback(() => {
    if (!accessKey) return;
    jsonFetch("/triage/status").then((r) => r.ok && r.json()).then((d) => {
      if (d) { setCfg(d.config || {}); setLastRun(d.status || null); }
    }).catch(() => {});
    jsonFetch("/triage/history?only_failed=true&limit=100").then((r) => r.ok && r.json())
      .then((d) => d && setProblems(d.rows || [])).catch(() => {});
  }, [accessKey, jsonFetch]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  async function run(dry) {
    setBusy(true); setNotice(null); if (!dry) setResult(null);
    try {
      const res = await jsonFetch("/triage/run", { method: "POST", body: JSON.stringify({ dry_run: dry, since_days: Number(days), max_total: Number(cap) }) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `API ${res.status}`);
      setResult(d);
      if (!d.ok) setNotice({ kind: "warn", text: d.error || "Triage couldn’t run." });
      loadStatus();
    } catch (e) {
      if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) });
    } finally { setBusy(false); }
  }

  async function saveCfg(next) {
    setSavingCfg(true);
    try {
      const body = { auto_enabled: next.auto_enabled, interval_min: Number(next.interval_min || 10), max_total: Number(cap) };
      const res = await jsonFetch("/triage/config", { method: "POST", body: JSON.stringify(body) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `API ${res.status}`);
      setCfg(d.config || next);
      setNotice({ kind: "ok", text: next.auto_enabled ? `Automatic triage is ON — every ${body.interval_min} min.` : "Automatic triage is OFF." });
    } catch (e) {
      if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) });
    } finally { setSavingCfg(false); }
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
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" /><div className="wordmark">Trade<b>Hub</b><span className="sec">Triage</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
        </div>
      </div>
    );
  }

  const items = result?.items || [];
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Triage</div>
        <div className="right">
          <span className="count">hello@ inbox · files into Outlook folders</span>
        </div>
      </div>

      <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
        <div className="tri-ctl">
          <label className="fld">How far back
            <input type="number" min={0} max={180} className="search" style={{ width: 80 }} value={days} onChange={(e) => setDays(e.target.value)} /> days
          </label>
          <label className="fld">Max this run
            <input type="number" min={10} max={500} step={10} className="search" style={{ width: 90 }} value={cap} onChange={(e) => setCap(e.target.value)} />
          </label>
          <button className="btn" onClick={() => run(true)} disabled={busy}>{busy ? "…" : "Preview (move nothing)"}</button>
          <button className="btn primary" onClick={() => run(false)} disabled={busy}>{busy ? "Triaging…" : "Triage now"}</button>
        </div>
        <div className="sub" style={{ marginTop: 8 }}>Reads only inbox mail from the last {days} day(s). Preview classifies without moving anything; Triage now files them into the Outlook folders.</div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 10 }}>{notice.text}</div>}
      </div>

      {result && result.ok ? (
        <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
          <div className="tool-label">
            {result.dry_run ? "Would file" : "Filed"} {result.moved || 0}
            {" · "}left in inbox {result.no_folder || 0}
            {" · "}skipped {result.skipped || 0}
            {" · "}failed {result.failed || 0}
            {result.capped ? " · capped (run again for more)" : ""}
          </div>
          {items.length ? (
            <table className="mini" style={{ marginTop: 8 }}>
              <thead><tr><th>From</th><th>Subject</th><th>Category</th><th>Owner</th><th>→ Folder</th><th>Status</th></tr></thead>
              <tbody>
                {items.map((r, i) => (
                  <tr key={i} className={r.status === "failed" ? "od" : ""}>
                    <td className="sub">{r.sender || "—"}</td>
                    <td>{(r.subject || "").slice(0, 70)}</td>
                    <td className="sub">{r.category || "—"}</td>
                    <td className="sub">{r.owner || "—"}</td>
                    <td className="sub">{r.folder || "—"}</td>
                    <td><StatusPill s={r.status} />{r.detail ? <span className="sub"> {r.detail}</span> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="sub" style={{ marginTop: 8 }}>No new emails to file.</div>}
        </div>
      ) : null}

      <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
        <div className="tool-label">🤖 Automatic triage (hands-off)</div>
        <div className="sub" style={{ marginBottom: 10 }}>When on, TradeHub classifies &amp; files new inbox mail on a schedule — no clicks. Runs on the always-on host.</div>
        <div className="tri-ctl">
          <label className="switch">
            <input type="checkbox" checked={!!cfg?.auto_enabled} disabled={savingCfg || !cfg}
              onChange={(e) => saveCfg({ auto_enabled: e.target.checked, interval_min: cfg?.interval_min || 10 })} />
            <span>Run automatically</span>
          </label>
          <label className="fld">Every
            <input type="number" min={5} max={120} step={5} className="search" style={{ width: 80 }}
              value={cfg?.interval_min || 10}
              onChange={(e) => setCfg((c) => ({ ...(c || {}), interval_min: e.target.value }))} /> min
          </label>
          <button className="btn" onClick={() => saveCfg({ auto_enabled: !!cfg?.auto_enabled, interval_min: cfg?.interval_min || 10 })} disabled={savingCfg || !cfg}>
            {savingCfg ? "…" : "Save interval"}
          </button>
        </div>
        {lastRun?.at ? (
          <div className="sub" style={{ marginTop: 10 }}>
            🤖 Last run {String(lastRun.at).slice(0, 16).replace("T", " ")} UTC — moved {lastRun.moved || 0}, failed {lastRun.failed || 0}
            {lastRun.reason ? ` (${lastRun.reason})` : ""}
            {lastRun.ok === false ? <span className="pill red" style={{ marginLeft: 6 }}>error</span> : null}
          </div>
        ) : <div className="sub" style={{ marginTop: 10 }}>No scheduled run recorded yet.</div>}
      </div>

      {problems.length ? (
        <div className="card" style={{ padding: "14px 16px" }}>
          <div className="tool-label">⚠️ Didn’t get filed ({problems.length})</div>
          <table className="mini" style={{ marginTop: 8 }}>
            <thead><tr><th>When</th><th>From</th><th>Subject</th><th>Category</th><th>Why</th></tr></thead>
            <tbody>
              {problems.map((r, i) => (
                <tr key={i}>
                  <td className="sub">{String(r.at || "").slice(0, 16).replace("T", " ")}</td>
                  <td className="sub">{r.sender || "—"}</td>
                  <td>{(r.subject || "").slice(0, 50)}</td>
                  <td className="sub">{r.category || "—"}</td>
                  <td className="sub">{r.detail || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
