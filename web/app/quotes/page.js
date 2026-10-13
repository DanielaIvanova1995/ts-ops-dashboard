"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

const CEDRAL_COLOURS = ["White", "Vanilla White", "Clay Brown", "Platinum Grey", "Chalk White",
  "Sky Blue", "Steel Grey", "Slate Grey", "Walnut Brown", "Black", "Silver Grey", "Pearl Grey",
  "Pewter Grey", "Sand Yellow", "Brick Red", "Ocean Blue", "Basalt Grey", "Metal Green",
  "Tea Green", "Pebble Grey", "Cocoa Brown"];

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function pct(v) { return v == null ? "—" : `${(v * 100).toFixed(1)}%`; }

export default function Quotes() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [f, setF] = useState({ system: "Lap", colour: "", gross_area_m2: "", openings_m2: "",
    wall_height_m: "", total_width_m: "", external_corners: "", internal_corners: "", num_windows: "",
    wants_trims: true, wants_battens: false, wants_screws: true });
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let k = null;
    try { k = localStorage.getItem(KEY_STORE); } catch {}
    if (k) setAccessKey(k); else setNeedKey(true);
  }, []);

  const jsonFetch = useCallback(async (path, opts = {}) => {
    const r = await fetch(`${API}${path}`, { ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-TradeHub-Key": accessKey || "", ...(opts.headers || {}) } });
    if (r.status === 401) { try { localStorage.removeItem(KEY_STORE); } catch {} setAccessKey(null); setNeedKey(true); throw new Error("unauthorised"); }
    return r;
  }, [accessKey]);

  function set(k, v) { setF((s) => ({ ...s, [k]: v })); }
  const num = (v) => (v === "" || v == null ? null : Number(v));

  async function build() {
    if (!f.gross_area_m2) { setErr("Enter the gross wall area (m²)."); return; }
    setBusy(true); setErr(""); setRes(null);
    try {
      const body = {
        system: f.system, colour: f.colour,
        gross_area_m2: Number(f.gross_area_m2), openings_m2: Number(f.openings_m2 || 0),
        wall_height_m: num(f.wall_height_m), total_width_m: num(f.total_width_m),
        external_corners: num(f.external_corners), internal_corners: Number(f.internal_corners || 0),
        num_windows: num(f.num_windows),
        wants_trims: f.wants_trims, wants_battens: f.wants_battens, wants_screws: f.wants_screws,
      };
      const r = await jsonFetch("/quotes/cedral", { method: "POST", body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `API ${r.status}`);
      if (!d.ok) { setErr(d.detail || "Couldn’t build the quote."); return; }
      setRes(d);
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  if (needKey) {
    return (
      <div className="wrap"><div className="login">
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Quotes</span></div>
        <p className="sub">Enter the shared access code to continue.</p>
        <form onSubmit={submitKey} className="loginform">
          <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
          <button className="btn primary" type="submit">Enter</button>
        </form>
      </div></div>
    );
  }

  const t = res?.totals, dsc = res?.discount;
  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Quotes · Cedral</div>
        <div className="right"><span className="count">Lap &amp; Click take-off → priced (all-AJW)</span></div>
      </div>

      <div className="card" style={{ padding: "12px 14px", marginBottom: 10 }}>
        <div className="q-grid">
          <label className="fld">System
            <select className="filter" value={f.system} onChange={(e) => set("system", e.target.value)}>
              <option value="Lap">Cedral Lap (weatherboard)</option>
              <option value="Click">Cedral Click (flush T&amp;G)</option>
            </select>
          </label>
          <label className="fld">Colour
            <input className="search" list="cedcol" value={f.colour} onChange={(e) => set("colour", e.target.value)} placeholder="e.g. Slate Grey" />
            <datalist id="cedcol">{CEDRAL_COLOURS.map((c) => <option key={c} value={c} />)}</datalist>
          </label>
          <label className="fld">Gross area (m²)<input className="search" type="number" value={f.gross_area_m2} onChange={(e) => set("gross_area_m2", e.target.value)} /></label>
          <label className="fld">Openings (m²)<input className="search" type="number" value={f.openings_m2} onChange={(e) => set("openings_m2", e.target.value)} placeholder="windows/doors" /></label>
          <label className="fld">Wall height (m)<input className="search" type="number" value={f.wall_height_m} onChange={(e) => set("wall_height_m", e.target.value)} placeholder="optional" /></label>
          <label className="fld">Total run width (m)<input className="search" type="number" value={f.total_width_m} onChange={(e) => set("total_width_m", e.target.value)} placeholder="optional" /></label>
          <label className="fld">External corners<input className="search" type="number" value={f.external_corners} onChange={(e) => set("external_corners", e.target.value)} placeholder="default 4" /></label>
          <label className="fld">Internal corners<input className="search" type="number" value={f.internal_corners} onChange={(e) => set("internal_corners", e.target.value)} placeholder="0" /></label>
          <label className="fld">Windows/doors<input className="search" type="number" value={f.num_windows} onChange={(e) => set("num_windows", e.target.value)} placeholder="optional" /></label>
        </div>
        <div className="q-opts">
          <label className="switch"><input type="checkbox" checked={f.wants_trims} onChange={(e) => set("wants_trims", e.target.checked)} /><span>Trims (corners, start profile)</span></label>
          <label className="switch"><input type="checkbox" checked={f.wants_screws} onChange={(e) => set("wants_screws", e.target.checked)} /><span>Fixings</span></label>
          <label className="switch"><input type="checkbox" checked={f.wants_battens} onChange={(e) => set("wants_battens", e.target.checked)} /><span>Battens (not AJW — flagged)</span></label>
          <span style={{ flex: 1 }} />
          <button className="btn primary" onClick={build} disabled={busy}>{busy ? "Building…" : "Build quote"}</button>
        </div>
        {err && <div className="route-msg warn" style={{ marginTop: 8 }}>{err}</div>}
      </div>

      {res && (
        <>
          <div className="card" style={{ padding: "6px 12px 12px", marginBottom: 10 }}>
            <div className="tool-label">{res.product}{res.colour ? ` · ${res.colour}` : ""} — {t.n_priced}/{t.n_total} lines priced</div>
            <table className="mini">
              <thead><tr><th>Item</th><th className="num">Qty</th><th>Matched product</th><th className="num">Unit</th><th className="num">Line</th><th className="num">Cost (AJW)</th></tr></thead>
              <tbody>
                {res.lines.map((l, i) => (
                  <tr key={i} className={l.note && !l.ajw_supplied ? "od" : ""}>
                    <td>{l.description}{l.note ? <div className="sub mamber">{l.note}</div> : null}</td>
                    <td className="num">{l.qty}</td>
                    <td className="sub">{l.matched ? `${l.matched.title || "—"}${l.matched.sku ? ` (${l.matched.sku})` : ""}` : "—"}</td>
                    <td className="num">{l.unit_sell != null ? money(l.unit_sell) : "—"}</td>
                    <td className="num">{l.line_sell != null ? money(l.line_sell) : "—"}</td>
                    <td className="num sub">{l.line_cost != null ? money(l.line_cost) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="q-cards">
            <div className="card q-tot">
              <div className="tool-label">Totals (ex VAT)</div>
              <div className="kv"><span>Sell</span><b>{money(t.sell)}</b></div>
              <div className="kv"><span>Cost (AJW)</span><b>{money(t.cost)}</b></div>
              <div className="kv big"><span>Margin (after 1.8% fee)</span><b className={t.margin_net == null ? "" : t.margin_net < 8 ? "mred" : t.margin_net < 15 ? "mamber" : "mgreen"}>{t.margin_net == null ? "—" : `${t.margin_net}%`}</b></div>
            </div>
            {dsc && (
              <div className="card q-tot">
                <div className="tool-label">Discount desk — {dsc.band}</div>
                <div className="sub" style={{ marginBottom: 4 }}>You may give up to {pct(dsc.give)} of the margin away, down to a {money(dsc.floor_price)} floor (never below 8%).</div>
                <div className="kv"><span>Lowest you may quote</span><b>{money(dsc.floor_price)}</b></div>
                <div className="kv"><span>Max discount</span><b>{dsc.no_room ? "no room" : money(dsc.max_disc)}</b></div>
                <div className="kv"><span>4% opening price</span><b>{money(dsc.four_pc_price)}</b></div>
                {dsc.four_breaches ? <div className="route-msg warn" style={{ marginTop: 6 }}>Even the standard 4% off dips below the floor — Daniela’s call.</div> : null}
              </div>
            )}
          </div>

          {res.caveats?.length ? (
            <div className="card" style={{ padding: "10px 14px", marginTop: 10 }}>
              <div className="tool-label">Notes to confirm with the customer</div>
              <ul className="disc-list">{res.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
