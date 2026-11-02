"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const PIN_STORE = "th_assistant_pin";

function fmtTime(s) {
  return s ? String(s).slice(11, 16) : "";
}

function Item({ n, it, children }) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "10px 0", borderTop: "1px solid var(--line, #eee)" }}>
      <div className="sub" style={{ width: 18, textAlign: "right" }}>{n}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>
          {it.link ? <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a> : it.title}
          {it.today ? <span className="pill red" style={{ marginLeft: 8 }}>today</span> : null}
        </div>
        <div className="sub" style={{ marginTop: 2 }}>{it.summary || null}</div>
        {children}
      </div>
    </div>
  );
}

function DraftBox({ it }) {
  const [open, setOpen] = useState(false);
  if (!it.draft_text && !it.draft_note) return null;
  return (
    <div style={{ marginTop: 6 }}>
      {it.draft_link ? <a className="btn" href={it.draft_link} target="_blank" rel="noreferrer">Open draft in Outlook</a> : null}
      {it.draft_note ? <span className="sub">{it.draft_note}</span> : null}
      {it.draft_text ? (
        <button className="btn" style={{ marginLeft: it.draft_link ? 8 : 0 }} onClick={() => setOpen(!open)}>
          {open ? "Hide draft" : "Show draft"}
        </button>
      ) : null}
      {open ? <pre className="sub" style={{ whiteSpace: "pre-wrap", marginTop: 8, fontFamily: "inherit" }}>{it.draft_text}</pre> : null}
    </div>
  );
}

export default function Assistant() {
  const [pin, setPin] = useState("");
  const [needPin, setNeedPin] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [pinErr, setPinErr] = useState("");
  const [notSetUp, setNotSetUp] = useState(false);

  const [data, setData] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let p = "";
    try { p = localStorage.getItem(PIN_STORE) || ""; } catch {}
    if (p) setPin(p); else setNeedPin(true);
  }, []);

  const apiFetch = useCallback(async (path, opts = {}) => {
    const res = await fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Assistant-Key": pin || "", ...(opts.headers || {}) },
    });
    if (res.status === 503) { setNotSetUp(true); throw new Error("not set up"); }
    if (res.status === 403) {
      try { localStorage.removeItem(PIN_STORE); } catch {}
      setPinErr(pin ? "That passcode didn’t work — try again." : ""); setPin(""); setNeedPin(true);
      throw new Error("unauthorised");
    }
    return res;
  }, [pin]);

  const load = useCallback(() => {
    if (!pin) return;
    apiFetch("/assistant/brief").then((r) => r.ok && r.json()).then((d) => d && setData(d)).catch(() => {});
  }, [pin, apiFetch]);
  useEffect(() => { load(); }, [load]);

  // While a run is going, poll every 5s until it finishes.
  useEffect(() => {
    if (!data?.running?.on) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [data?.running?.on, load]);

  async function run(dry) {
    setNotice(null);
    try {
      const res = await apiFetch("/assistant/run", { method: "POST", body: JSON.stringify({ dry_run: dry }) });
      const d = await res.json();
      setNotice({ kind: "ok", text: d.started ? (dry ? "Previewing — reading your inbox (nothing is written to Outlook)…" : "Running — reading your inbox and writing drafts. Takes a minute or two…") : (d.detail || "Already running.") });
      setData((x) => ({ ...(x || {}), running: { on: true } }));
      setTimeout(load, 3000);
    } catch (e) {
      if (!["unauthorised", "not set up"].includes(String(e.message))) setNotice({ kind: "warn", text: String(e.message || e) });
    }
  }

  async function saveCfg(patch) {
    setSaving(true);
    try {
      const res = await apiFetch("/assistant/config", { method: "POST", body: JSON.stringify(patch) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || `API ${res.status}`);
      setData((x) => ({ ...(x || {}), config: d.config }));
    } catch (e) {
      if (!["unauthorised", "not set up"].includes(String(e.message))) setNotice({ kind: "warn", text: String(e.message || e) });
    } finally { setSaving(false); }
  }

  function submitPin(e) {
    e.preventDefault();
    const p = pinInput.trim(); if (!p) return;
    try { localStorage.setItem(PIN_STORE, p); } catch {}
    setPin(p); setNeedPin(false); setPinInput(""); setPinErr("");
  }

  if (notSetUp) {
    return (
      <div className="wrap"><div className="login">
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Assistant</span></div>
        <p className="sub">🔒 The Assistant isn’t switched on yet. Add <b>TRADEHUB_ASSISTANT_KEY</b> (your private passcode) to the API service on Render, then reload.</p>
      </div></div>
    );
  }

  if (needPin) {
    return (
      <div className="wrap"><div className="login">
        <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" />
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Assistant</span></div>
        <p className="sub">🔒 Private to Daniela. Enter your Assistant passcode.</p>
        <form onSubmit={submitPin} className="loginform">
          <input className="input" type="password" value={pinInput} autoFocus onChange={(e) => setPinInput(e.target.value)} placeholder="Assistant passcode" />
          <button className="btn primary" type="submit">Enter</button>
        </form>
        {pinErr ? <div className="route-msg warn" style={{ marginTop: 10 }}>{pinErr}</div> : null}
      </div></div>
    );
  }

  const b = data?.brief || {};
  const cfg = data?.config || {};
  const running = !!data?.running?.on;
  const runErr = data?.running?.error;
  const today = new Date().toISOString().slice(0, 10);
  const evToday = (b.calendar || []).filter((e) => e.start.slice(0, 10) === today);
  const evTomorrow = (b.calendar || []).filter((e) => e.start.slice(0, 10) !== today);

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Assistant</div>
        <div className="right">
          <span className="count">daniela@ · drafts only, never sends</span>
        </div>
      </div>

      <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
        <div className="tri-ctl">
          <button className="btn" onClick={() => run(true)} disabled={running}>Preview (write nothing)</button>
          <button className="btn primary" onClick={() => run(false)} disabled={running}>{running ? "Working…" : "Run now"}</button>
          <span className="sub">
            {b.at ? `Last brief ${String(b.at).slice(0, 16).replace("T", " ")} UTC${b.dry_run ? " (preview)" : ""}` : "No brief yet — press Run now."}
          </span>
        </div>
        {notice ? <div className={`route-msg ${notice.kind}`} style={{ marginTop: 10 }}>{notice.text}</div> : null}
        {runErr ? <div className="route-msg warn" style={{ marginTop: 10 }}>Last run failed: {runErr}</div> : null}
        {b.counts ? (
          <div className="sub" style={{ marginTop: 8 }}>
            Read {b.counts.scanned} emails · {b.counts.needs} need you · {b.counts.drafts} reply drafts · {b.counts.chasers} chasers · {b.counts.tidied} tidied
          </div>
        ) : null}
      </div>

      {b.at ? (
        <>
          <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
            <div className="tool-label">📅 Today</div>
            {b.calendar_error ? <div className="sub">{b.calendar_error}</div>
              : evToday.length ? evToday.map((e, i) => (
                <div key={i} style={{ padding: "4px 0" }}>
                  <b>{e.all_day ? "All day" : `${fmtTime(e.start)}–${fmtTime(e.end)}`}</b>{" "}
                  {e.link ? <a href={e.link} target="_blank" rel="noreferrer">{e.subject}</a> : e.subject}
                  {e.location ? <span className="sub"> · {e.location}</span> : null}
                  {e.tentative ? <span className="pill amber" style={{ marginLeft: 6 }}>not answered</span> : null}
                </div>
              )) : <div className="sub">Nothing in the diary today.</div>}
            {!b.calendar_error && evTomorrow.length ? (
              <div className="sub" style={{ marginTop: 8 }}>
                Tomorrow: {evTomorrow.map((e) => `${e.all_day ? "all day" : fmtTime(e.start)} ${e.subject}`).join(" · ")}
              </div>
            ) : null}
          </div>

          <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
            <div className="tool-label">Needs you ({(b.needs || []).length})</div>
            {(b.needs || []).length ? b.needs.map((it, i) => (
              <Item key={i} n={i + 1} it={it}><div className="sub">From {it.from} · {fmtTime(it.received)}</div><DraftBox it={it} /></Item>
            )) : <div className="sub">Nothing needs you this morning.</div>}
          </div>

          {(b.chasers || []).length ? (
            <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
              <div className="tool-label">Still waiting on a reply ({b.chasers.length})</div>
              {b.chasers.map((it, i) => (
                <Item key={i} n={i + 1} it={{ ...it, summary: `You emailed ${it.to} ${it.days} days ago — no answer yet.` }}><DraftBox it={it} /></Item>
              ))}
            </div>
          ) : null}

          {(b.sorted || []).length || (b.fyi || []).length ? (
            <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
              <div className="tool-label">Already sorted / for info</div>
              {[...(b.sorted || []), ...(b.fyi || [])].map((it, i) => <Item key={i} n={i + 1} it={it} />)}
            </div>
          ) : null}

          {(b.tidied || []).length ? (
            <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
              <div className="tool-label">{b.dry_run || !cfg.tidy_enabled ? "Would tidy" : "Tidied out of your inbox"} ({b.tidied.length})</div>
              <table className="mini" style={{ marginTop: 8 }}>
                <thead><tr><th>From</th><th>About</th><th>→ Folder</th></tr></thead>
                <tbody>
                  {b.tidied.map((it, i) => (
                    <tr key={i}><td className="sub">{it.from}</td>
                      <td>{it.link ? <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a> : it.title}</td>
                      <td className="sub">{it.folder}{it.moved ? "" : " (not moved)"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {(b.errors || []).length ? (
            <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
              <div className="tool-label">⚠️ Problems</div>
              {b.errors.map((e, i) => <div key={i} className="sub">{e}</div>)}
            </div>
          ) : null}
        </>
      ) : null}

      <div className="card" style={{ padding: "14px 16px" }}>
        <div className="tool-label">Settings</div>
        <div className="tri-ctl" style={{ flexWrap: "wrap" }}>
          <label className="switch"><input type="checkbox" checked={!!cfg.auto_enabled} disabled={saving} onChange={(e) => saveCfg({ auto_enabled: e.target.checked })} /><span>Run every weekday at</span></label>
          <select className="search" value={cfg.run_hour || 7} disabled={saving} onChange={(e) => saveCfg({ run_hour: Number(e.target.value) })}>
            {[5, 6, 7, 8, 9, 10].map((h) => <option key={h} value={h}>{h}:00</option>)}
          </select>
          <label className="switch"><input type="checkbox" checked={!!cfg.drafts_enabled} disabled={saving} onChange={(e) => saveCfg({ drafts_enabled: e.target.checked })} /><span>Draft replies</span></label>
          <label className="switch"><input type="checkbox" checked={!!cfg.chasers_enabled} disabled={saving} onChange={(e) => saveCfg({ chasers_enabled: e.target.checked })} /><span>Draft chasers after {cfg.chase_days || 3} days</span></label>
          <label className="switch"><input type="checkbox" checked={!!cfg.tidy_enabled} disabled={saving} onChange={(e) => saveCfg({ tidy_enabled: e.target.checked })} /><span>Tidy newsletters / notifications / receipts</span></label>
        </div>
        <div className="sub" style={{ marginTop: 8 }}>Drafts land in your Outlook Drafts folder — nothing is ever sent or deleted. Tidied mail goes to the “Tidied - …” folders.</div>
      </div>
    </div>
  );
}
