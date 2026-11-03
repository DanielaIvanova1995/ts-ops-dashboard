"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const PIN_STORE = "th_assistant_pin";

const CSS = `
.as { max-width: 820px; margin: 0 auto; padding: 18px 16px 56px; font-size: 14px; }
.as-hero { background: linear-gradient(135deg, #FFF4EC 0%, #FFFDFB 60%, #F3F8F4 100%); border: 1px solid #F6E3D6;
  border-radius: 18px; padding: 26px 26px 22px; margin-bottom: 18px; }
.as-date { color: var(--muted); font-size: 12.5px; font-weight: 600; letter-spacing: .02em; }
.as-hello { font-size: 27px; font-weight: 800; letter-spacing: -.4px; margin: 4px 0 6px; color: var(--ink); }
.as-line { color: #4B5160; font-size: 15px; line-height: 1.5; }
.as-prog { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.as-bar { flex: 1; height: 8px; background: rgba(28,31,38,.07); border-radius: 99px; overflow: hidden; }
.as-bar > span { display: block; height: 100%; background: linear-gradient(90deg, #F5934F, #4CAF6E); border-radius: 99px; transition: width .4s ease; }
.as-prog-t { font-size: 12.5px; color: var(--muted); font-weight: 600; white-space: nowrap; }
.as-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 16px; }
.as-btn { appearance: none; border: 1px solid #EADFD6; background: #fff; color: var(--ink); border-radius: 99px;
  padding: 8px 15px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }
.as-btn:hover { border-color: var(--brand); }
.as-btn.main { background: var(--brand); border-color: var(--brand); color: #fff; }
.as-btn.main:hover { background: var(--brand-dark); }
.as-btn:disabled { opacity: .55; cursor: default; }
.as-btn.sm { padding: 5px 11px; font-size: 12px; }
.as-meta { color: var(--muted); font-size: 12px; }
.as-note { margin-top: 12px; padding: 10px 14px; border-radius: 12px; font-size: 13px; }
.as-note.ok { background: #EEF7F1; color: #1E6B3A; }
.as-note.warn { background: #FDF3E7; color: #8A4B0F; }
.as-sec { background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 6px 20px 8px; margin-bottom: 14px; }
.as-sec h2 { font-size: 15px; font-weight: 800; margin: 14px 0 6px; display: flex; align-items: center; gap: 8px; }
.as-sec h2 .n { font-size: 12px; font-weight: 700; color: var(--muted); background: var(--muted-bg); border-radius: 99px; padding: 2px 8px; }
.as-sec .hint { color: var(--muted); font-size: 12.5px; margin: -2px 0 6px; }
.as-item { display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid #F0F1F3; transition: opacity .25s ease; }
.as-item:first-of-type { border-top: 0; }
.as-item.done { opacity: .5; }
.as-item.done .as-t { text-decoration: line-through; }
.as-tick { flex: 0 0 24px; width: 24px; height: 24px; margin-top: 1px; border-radius: 50%; border: 2px solid #D5D9DF; background: #fff;
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center; color: #fff; padding: 0; transition: all .15s ease; }
.as-tick:hover { border-color: #4CAF6E; }
.as-tick.on { background: #4CAF6E; border-color: #4CAF6E; }
.as-body { flex: 1; min-width: 0; }
.as-t { font-weight: 700; color: var(--ink); }
.as-t a { color: inherit; text-decoration: none; }
.as-t a:hover { text-decoration: underline; }
.as-s { color: #4B5160; margin-top: 3px; line-height: 1.45; }
.as-tag { display: inline-block; margin-left: 8px; font-size: 11px; font-weight: 700; color: #B4471B; background: #FFE9DC; border-radius: 99px; padding: 2px 8px; vertical-align: 1px; }
.as-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; }
.as-draft { white-space: pre-wrap; font: inherit; font-size: 13px; color: #3A3F4B; background: #FAFAF8; border: 1px solid #EFEDE8;
  border-radius: 12px; padding: 12px 14px; margin: 8px 0 0; }
.as-empty { color: var(--muted); padding: 10px 0 14px; }
.as-cal { display: flex; gap: 12px; padding: 8px 0; border-top: 1px solid #F0F1F3; }
.as-cal:first-of-type { border-top: 0; }
.as-cal .tm { flex: 0 0 92px; font-weight: 700; color: var(--brand-dark); font-size: 13px; }
.as-done-t { cursor: pointer; color: var(--muted); font-weight: 700; font-size: 13px; padding: 10px 0; list-style: none; }
.as-tidy { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-top: 1px solid #F0F1F3; font-size: 13px; }
.as-tidy:first-of-type { border-top: 0; }
.as-set { display: flex; flex-direction: column; gap: 10px; padding: 6px 0 12px; }
.as-set label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.as-lock { max-width: 380px; margin: 70px auto; text-align: center; background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 30px 26px; }
.as-lock input { width: 100%; margin: 14px 0 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; font: inherit; }
@media (max-width: 640px) { .as-hello { font-size: 22px; } .as-hero { padding: 20px 18px; } .as-sec { padding: 4px 14px 6px; } .as-cal .tm { flex-basis: 70px; } }
`;

function Check() {
  return (<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>);
}

function hhmm(s) { return s ? String(s).slice(11, 16) : ""; }
function keyOf(it) { return it.key || it.link || it.title; }

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function Draft({ it }) {
  const [open, setOpen] = useState(false);
  if (!it.draft_text && !it.draft_note && !it.draft_link) return null;
  return (
    <>
      <div className="as-row">
        {it.draft_link ? <a className="as-btn sm" href={it.draft_link} target="_blank" rel="noreferrer">✉️ Open draft in Outlook</a> : null}
        {it.draft_text ? <button className="as-btn sm" onClick={() => setOpen(!open)}>{open ? "Hide draft" : "Read draft"}</button> : null}
        {it.draft_note ? <span className="as-meta">{it.draft_note}</span> : null}
      </div>
      {open ? <pre className="as-draft">{it.draft_text}</pre> : null}
    </>
  );
}

function Item({ it, done, onTick, meta, children }) {
  return (
    <div className={`as-item${done ? " done" : ""}`}>
      <button className={`as-tick${done ? " on" : ""}`} onClick={onTick} title={done ? "Untick" : "Tick off — it's sorted"} aria-label={done ? "Untick" : "Tick off"}>
        {done ? <Check /> : null}
      </button>
      <div className="as-body">
        <div className="as-t">
          {it.link ? <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a> : it.title}
          {it.today && !done ? <span className="as-tag">today</span> : null}
        </div>
        {it.summary ? <div className="as-s">{it.summary}</div> : null}
        {meta ? <div className="as-meta" style={{ marginTop: 4 }}>{meta}</div> : null}
        {!done ? children : null}
      </div>
    </div>
  );
}

// A section of tickable items: open ones first, ticked ones folded into "Done" underneath.
function TickList({ title, emoji, hint, items, ticked, onTick, empty, meta, render }) {
  const open = items.filter((it) => !ticked.has(keyOf(it)));
  const done = items.filter((it) => ticked.has(keyOf(it)));
  if (!items.length && !empty) return null;
  return (
    <section className="as-sec">
      <h2><span>{emoji}</span>{title}{open.length ? <span className="n">{open.length}</span> : null}</h2>
      {hint ? <div className="hint">{hint}</div> : null}
      {open.length ? open.map((it) => (
        <Item key={keyOf(it)} it={it} done={false} onTick={() => onTick(it, true)} meta={meta && meta(it)}>{render && render(it)}</Item>
      )) : <div className="as-empty">{items.length ? "All ticked off — nice." : empty}</div>}
      {done.length ? (
        <details>
          <summary className="as-done-t">✓ Done ({done.length})</summary>
          {done.map((it) => <Item key={keyOf(it)} it={it} done onTick={() => onTick(it, false)} />)}
        </details>
      ) : null}
    </section>
  );
}

export default function Assistant() {
  const [pin, setPin] = useState("");
  const [needPin, setNeedPin] = useState(false);
  const [pinInput, setPinInput] = useState("");
  const [pinErr, setPinErr] = useState("");
  const [notSetUp, setNotSetUp] = useState(false);

  const [data, setData] = useState(null);
  const [ticked, setTicked] = useState(new Set());
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
    apiFetch("/assistant/brief").then((r) => r.ok && r.json()).then((d) => {
      if (d) { setData(d); setTicked(new Set(d.ticked || [])); }
    }).catch(() => {});
  }, [pin, apiFetch]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!data?.running?.on) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [data?.running?.on, load]);

  async function tick(it, done) {
    const k = keyOf(it);
    setTicked((s) => { const n = new Set(s); if (done) n.add(k); else n.delete(k); return n; });   // instant
    try {
      const res = await apiFetch("/assistant/tick", { method: "POST", body: JSON.stringify({ key: k, done }) });
      if (!res.ok) throw new Error("Couldn’t save that tick — try again.");
    } catch (e) {
      setTicked((s) => { const n = new Set(s); if (done) n.delete(k); else n.add(k); return n; });   // undo
      if (!["unauthorised", "not set up"].includes(String(e.message))) setNotice({ kind: "warn", text: String(e.message || e) });
    }
  }

  async function run(dry) {
    setNotice(null);
    try {
      const res = await apiFetch("/assistant/run", { method: "POST", body: JSON.stringify({ dry_run: dry }) });
      const d = await res.json();
      setNotice({ kind: "ok", text: d.started ? (dry ? "Having a look through your inbox — nothing will be written to Outlook…" : "Reading your inbox and writing drafts — give it a minute or two…") : (d.detail || "Already running.") });
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

  if (notSetUp || needPin) {
    return (
      <div className="as"><style>{CSS}</style>
        <div className="as-lock">
          <div style={{ fontSize: 30 }}>🔒</div>
          <div className="as-hello" style={{ fontSize: 22 }}>Your assistant</div>
          {notSetUp ? (
            <p className="as-meta">Not switched on yet — add <b>TRADEHUB_ASSISTANT_KEY</b> to the API service on Render, then reload.</p>
          ) : (
            <form onSubmit={submitPin}>
              <p className="as-meta">Private to Daniela. Enter your passcode.</p>
              <input type="password" value={pinInput} autoFocus onChange={(e) => setPinInput(e.target.value)} placeholder="Passcode" />
              <button className="as-btn main" type="submit" style={{ width: "100%", justifyContent: "center" }}>Open</button>
              {pinErr ? <div className="as-note warn">{pinErr}</div> : null}
            </form>
          )}
        </div>
      </div>
    );
  }

  const b = data?.brief || {};
  const cfg = data?.config || {};
  const running = !!data?.running?.on;
  const needs = b.needs || [];
  const chasers = b.chasers || [];
  const tickables = [...needs, ...chasers];
  const doneN = tickables.filter((it) => ticked.has(keyOf(it))).length;
  const openNeeds = needs.filter((it) => !ticked.has(keyOf(it)));
  const drafts = openNeeds.filter((it) => it.draft_link).length + chasers.filter((it) => it.draft_link && !ticked.has(keyOf(it))).length;
  const urgent = openNeeds.filter((it) => it.today).length;
  const todayStr = new Date().toISOString().slice(0, 10);
  const evToday = (b.calendar || []).filter((e) => e.start.slice(0, 10) === todayStr);
  const evTomorrow = (b.calendar || []).filter((e) => e.start.slice(0, 10) !== todayStr);
  const dateLine = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

  let line;
  if (!b.at) line = "I haven’t looked at your inbox yet — press Run now and I’ll put your morning together.";
  else if (!openNeeds.length) line = "Nothing in your inbox needs you right now. Enjoy the quiet. ☀️";
  else line = `${openNeeds.length} email${openNeeds.length > 1 ? "s" : ""} waiting on you`
    + (urgent ? `, ${urgent} worth doing today` : "")
    + (drafts ? ` — ${drafts} draft${drafts > 1 ? "s are" : " is"} already written in Outlook for you to check and send.` : ".");
  // (drafts is only non-zero for briefs made before drafting was switched off)

  return (
    <div className="as"><style>{CSS}</style>
      <div className="as-hero">
        <div className="as-date">{dateLine}</div>
        <div className="as-hello">{greeting()}, Daniela</div>
        <div className="as-line">{line}</div>
        {tickables.length ? (
          <div className="as-prog">
            <div className="as-bar"><span style={{ width: `${Math.round((doneN / tickables.length) * 100)}%` }} /></div>
            <div className="as-prog-t">{doneN} of {tickables.length} done</div>
          </div>
        ) : null}
        <div className="as-actions">
          <button className="as-btn main" onClick={() => run(false)} disabled={running}>{running ? "Working on it…" : "↻ Run now"}</button>
          <button className="as-btn" onClick={() => run(true)} disabled={running}>Preview (write nothing)</button>
          {b.at ? <span className="as-meta">Updated {new Date(b.at).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" })}{b.dry_run ? " · preview" : ""}</span> : null}
        </div>
        {notice ? <div className={`as-note ${notice.kind}`}>{notice.text}</div> : null}
        {data?.running?.error ? <div className="as-note warn">The last run hit a problem: {data.running.error}</div> : null}
      </div>

      {b.at ? (
        <>
          <section className="as-sec">
            <h2><span>📅</span>Your day</h2>
            {b.calendar_error ? <div className="as-empty">{b.calendar_error}</div>
              : evToday.length ? evToday.map((e, i) => (
                <div className="as-cal" key={i}>
                  <div className="tm">{e.all_day ? "All day" : `${hhmm(e.start)}–${hhmm(e.end)}`}</div>
                  <div>
                    <div className="as-t">{e.link ? <a href={e.link} target="_blank" rel="noreferrer">{e.subject}</a> : e.subject}</div>
                    <div className="as-meta">{[e.location, e.tentative ? "you haven’t replied" : ""].filter(Boolean).join(" · ")}</div>
                  </div>
                </div>
              )) : <div className="as-empty">A clear diary today.</div>}
            {!b.calendar_error && evTomorrow.length ? (
              <div className="as-meta" style={{ paddingBottom: 12 }}>Tomorrow: {evTomorrow.map((e) => `${e.all_day ? "all day" : hhmm(e.start)} ${e.subject}`).join(" · ")}</div>
            ) : null}
          </section>

          <TickList title="Needs you" emoji="✉️" items={needs} ticked={ticked} onTick={tick}
            hint="Tick each one off once it’s handled."
            empty="Nothing needs you this morning."
            meta={(it) => `${it.from}${it.received ? " · " + hhmm(it.received) : ""}`}
            render={(it) => <Draft it={it} />} />

          <TickList title="Waiting to hear back" emoji="⏳" items={chasers} ticked={ticked} onTick={tick}
            hint="Emails you sent that haven’t had an answer yet."
            meta={(it) => `To ${it.to} · ${it.days} days ago`}
            render={(it) => <Draft it={it} />} />

          {(b.sorted || []).length || (b.fyi || []).length ? (
            <section className="as-sec">
              <h2><span>🌿</span>Already sorted &amp; for info</h2>
              {[...(b.sorted || []), ...(b.fyi || [])].map((it, i) => (
                <div className="as-item" key={i}>
                  <div className="as-body">
                    <div className="as-t">{it.link ? <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a> : it.title}</div>
                    {it.summary ? <div className="as-s">{it.summary}</div> : null}
                  </div>
                </div>
              ))}
            </section>
          ) : null}

          {(b.tidied || []).length ? (
            <section className="as-sec">
              <details>
                <summary className="as-done-t" style={{ color: "var(--ink)", fontSize: 15 }}>
                  🧹 {(() => {
                    const moved = b.tidied.filter((it) => it.moved).length;
                    if (!moved) return `${b.tidied.length} newsletters & notifications to tidy — none moved yet${b.dry_run ? " (preview)" : ""}`;
                    return `Tidied away ${moved} newsletters & notifications${moved < b.tidied.length ? ` (${b.tidied.length - moved} not moved)` : ""}`;
                  })()}
                </summary>
                {b.tidied.map((it, i) => (
                  <div className="as-tidy" key={i}>
                    <span>{it.link ? <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a> : it.title} <span className="as-meta">· {it.from}</span></span>
                    <span className="as-meta" style={{ whiteSpace: "nowrap" }}>{it.moved ? `✓ moved to ${it.folder}` : `not moved · would go to ${it.folder}`}</span>
                  </div>
                ))}
              </details>
            </section>
          ) : null}

          {(b.errors || []).length ? (
            <section className="as-sec">
              <h2><span>⚠️</span>A few things I couldn’t do</h2>
              {b.errors.map((e, i) => <div key={i} className="as-meta" style={{ padding: "4px 0" }}>{e}</div>)}
              <div style={{ height: 8 }} />
            </section>
          ) : null}
        </>
      ) : null}

      <section className="as-sec">
        <details>
          <summary className="as-done-t">⚙️ Settings</summary>
          <div className="as-set">
            <label>
              <input type="checkbox" checked={!!cfg.auto_enabled} disabled={saving} onChange={(e) => saveCfg({ auto_enabled: e.target.checked })} />
              Run by itself every weekday at
              <select value={cfg.run_hour || 7} disabled={saving} onChange={(e) => saveCfg({ run_hour: Number(e.target.value) })}>
                {[5, 6, 7, 8, 9, 10].map((h) => <option key={h} value={h}>{h}:00</option>)}
              </select>
            </label>
            <label><input type="checkbox" checked={!!cfg.tidy_enabled} disabled={saving} onChange={(e) => saveCfg({ tidy_enabled: e.target.checked })} />Tidy newsletters, notifications &amp; receipts into folders</label>
            <div className="as-meta">Your assistant only sorts, lists and tidies — it doesn’t write, send or delete any emails.</div>
          </div>
        </details>
      </section>
    </div>
  );
}
