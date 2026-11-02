"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

// Short, plain names for the Monday "leave alone" groups shown in the preview.
function sampleText(arr) {
  if (!arr || !arr.length) return "";
  const shown = arr.slice(0, 10).join(", ");
  return arr.length > 10 ? `${shown} …` : shown;
}

export default function HousekeepingPage() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [scopes, setScopes] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [err, setErr] = useState("");

  // What the user has chosen to run (defaults: fulfil yes, archive yes — but nothing runs until
  // they press Confirm & run).
  const [doFulfil, setDoFulfil] = useState(true);
  const [doArchive, setDoArchive] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

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

  // Check Shopify scopes as soon as we're authed, so we can warn before anything is attempted.
  useEffect(() => {
    if (!accessKey) return;
    (async () => {
      try {
        const res = await jsonFetch("/housekeeping/scopes");
        if (res.ok) setScopes(await res.json());
      } catch { /* non-fatal */ }
    })();
  }, [accessKey, jsonFetch]);

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  const runPreview = useCallback(async () => {
    setPreviewing(true); setErr(""); setResult(null);
    try {
      const res = await jsonFetch("/housekeeping/preview");
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `API ${res.status}`);
      setPreview(d);
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    finally { setPreviewing(false); }
  }, [jsonFetch]);

  async function confirmRun() {
    if (!preview) return;
    const fIds = doFulfil ? (preview.fulfil?.ids || []) : [];
    const aIds = doArchive ? (preview.archive?.ids || []) : [];
    if (!fIds.length && !aIds.length) return;
    const parts = [];
    if (fIds.length) parts.push(`fulfil ${fIds.length} order${fIds.length === 1 ? "" : "s"} (the customer is NOT notified)`);
    if (aIds.length) parts.push(`archive ${aIds.length} order${aIds.length === 1 ? "" : "s"}`);
    if (!window.confirm(`This will ${parts.join(" and ")}.\n\nIt acts only on the orders in this preview. Go ahead?`)) return;
    setRunning(true); setErr("");
    try {
      const res = await jsonFetch("/housekeeping/run", {
        method: "POST", body: JSON.stringify({ fulfil_ids: fIds, archive_ids: aIds }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `API ${res.status}`);
      setResult(d);
      // Re-preview so the counts reflect what's left.
      runPreview();
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    finally { setRunning(false); }
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" />
          <div className="wordmark">Trade<b>Hub</b><span className="sec">Housekeeping</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
        </div>
      </div>
    );
  }

  const missing = scopes && !scopes.ok ? (scopes.missing || []) : [];
  const leaveGroups = preview ? Object.entries(preview.leave_group_counts || {}).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Shopify Housekeeping</div>
        <div className="right">
          <button className="btn primary" onClick={runPreview} disabled={previewing || running}>
            {previewing ? "Scanning…" : preview ? "Re-scan" : "Preview"}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <p className="sub" style={{ margin: 0 }}>
          Tidies the <b>Unfulfilled</b> and <b>Open</b> order tabs. It <b>fulfils</b> orders that are
          done being worked on (the customer is <b>never</b> notified), and <b>archives</b> orders
          that need nothing more. It <b>leaves alone</b> anything still in a working Monday group, and
          anything created in the last 24 hours. Nothing happens until you press <b>Confirm &amp; run</b>.
        </p>
      </div>

      {missing.length > 0 && (
        <div className="route-msg warn" style={{ marginBottom: 12 }}>
          ⚠️ The Shopify app is missing permission{missing.length === 1 ? "" : "s"}: <b>{missing.join(", ")}</b>.
          Some orders can’t be fulfilled or archived until these are granted in Shopify (Apps → the
          private/custom app → API scopes).
        </div>
      )}

      {err && <div className="route-msg warn" style={{ marginBottom: 12 }}>{err}</div>}

      {!preview && !previewing && (
        <div className="card"><div className="state">Press <b>Preview</b> to scan the open / unfulfilled orders. Nothing is changed by a preview.</div></div>
      )}

      {preview && (
        <>
          <div className="hk-tiles">
            <div className="hk-tile green">
              <div className="hk-n">{preview.fulfil?.count ?? 0}</div>
              <div className="hk-l">To fulfil</div>
              <div className="hk-s">{sampleText(preview.fulfil?.sample)}</div>
            </div>
            <div className="hk-tile blue">
              <div className="hk-n">{preview.archive?.count ?? 0}</div>
              <div className="hk-l">To archive</div>
              <div className="hk-s">{sampleText(preview.archive?.sample)}</div>
            </div>
            <div className="hk-tile grey">
              <div className="hk-n">{preview.leave_young?.count ?? 0}</div>
              <div className="hk-l">Left — under 24h old</div>
              <div className="hk-s">{sampleText(preview.leave_young?.sample)}</div>
            </div>
            <div className="hk-tile amber">
              <div className="hk-n">{preview.review_partial_refund?.count ?? 0}</div>
              <div className="hk-l">Needs review — part-refunded &amp; unfulfilled</div>
              <div className="hk-s">{sampleText(preview.review_partial_refund?.sample)}</div>
            </div>
          </div>
          <div className="hk-scan">Scanned {preview.scanned} open / unfulfilled order{preview.scanned === 1 ? "" : "s"}.</div>

          {leaveGroups.length > 0 && (
            <div className="card" style={{ marginTop: 12 }}>
              <div className="hk-h">Left alone — in a working Monday group</div>
              <table className="hk-table">
                <tbody>
                  {leaveGroups.map(([g, n]) => (
                    <tr key={g}><td>{g}</td><td className="hk-right">{n}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card" style={{ marginTop: 12 }}>
            <div className="hk-h">Confirm &amp; run</div>
            <label className="hk-check">
              <input type="checkbox" checked={doFulfil} onChange={(e) => setDoFulfil(e.target.checked)} />
              Fulfil the {preview.fulfil?.count ?? 0} order{(preview.fulfil?.count ?? 0) === 1 ? "" : "s"} above <span className="hk-muted">— customer is not notified</span>
            </label>
            <label className="hk-check">
              <input type="checkbox" checked={doArchive} onChange={(e) => setDoArchive(e.target.checked)} />
              Archive the {preview.archive?.count ?? 0} order{(preview.archive?.count ?? 0) === 1 ? "" : "s"} above
            </label>
            <div style={{ marginTop: 12 }}>
              <button className="btn primary" onClick={confirmRun}
                disabled={running || (!doFulfil && !doArchive) || ((preview.fulfil?.count ?? 0) === 0 && (preview.archive?.count ?? 0) === 0)}>
                {running ? "Running…" : "Confirm & run"}
              </button>
              <span className="hk-muted" style={{ marginLeft: 10 }}>Acts only on the orders in this preview.</span>
            </div>
          </div>
        </>
      )}

      {result && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="hk-h">Last run</div>
          <p className="sub" style={{ marginTop: 0 }}>
            Fulfilled <b>{result.fulfilled}</b>{result.fulfil_skipped ? ` (${result.fulfil_skipped} line(s) not fulfillable)` : ""},
            archived <b>{result.archived}</b>
            {result.failed ? <>, <b className="hk-fail">{result.failed} failed</b></> : null}.
          </p>
          {(result.failures || []).length > 0 && (
            <table className="hk-table">
              <tbody>
                {result.failures.map((f, i) => (
                  <tr key={i}><td>{f.action}</td><td className="hk-fail">{f.detail}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <style jsx>{`
        .hk-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
        .hk-tile { border: 1px solid var(--line, #e5e5e5); border-radius: 12px; padding: 14px 16px; border-left-width: 4px; background: var(--card, #fff); }
        .hk-tile.green { border-left-color: #1a9d57; }
        .hk-tile.blue { border-left-color: #2563eb; }
        .hk-tile.grey { border-left-color: #9aa0a6; }
        .hk-tile.amber { border-left-color: #d98300; }
        .hk-n { font-size: 30px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
        .hk-l { font-size: 13px; font-weight: 600; margin-top: 4px; }
        .hk-s { font-size: 12px; color: var(--muted, #777); margin-top: 6px; word-break: break-word; }
        .hk-scan { font-size: 12px; color: var(--muted, #777); margin-top: 8px; }
        .hk-h { font-weight: 700; margin-bottom: 10px; }
        .hk-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .hk-table td { padding: 5px 4px; border-top: 1px solid var(--line, #eee); }
        .hk-right { text-align: right; font-variant-numeric: tabular-nums; }
        .hk-check { display: flex; align-items: center; gap: 8px; font-size: 14px; margin: 6px 0; }
        .hk-muted { color: var(--muted, #777); font-size: 12px; }
        .hk-fail { color: #c0392b; }
      `}</style>
    </div>
  );
}
