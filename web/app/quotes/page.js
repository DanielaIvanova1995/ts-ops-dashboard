"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

const CEDRAL_COLOURS = ["White", "Vanilla White", "Clay Brown", "Platinum Grey", "Chalk White",
  "Sky Blue", "Steel Grey", "Slate Grey", "Walnut Brown", "Black", "Silver Grey", "Pearl Grey",
  "Pewter Grey", "Sand Yellow", "Brick Red", "Ocean Blue", "Basalt Grey", "Metal Green",
  "Tea Green", "Pebble Grey", "Cocoa Brown"];
const HARDIE_COLOURS = ["Anthracite Grey", "Arctic White", "Boothbay Blue", "Chestnut Brown",
  "Cobble Stone", "Evening Blue", "Grey Slate", "Heathered Moss", "Iron Grey", "Khaki Brown",
  "Light Mist", "Midnight Black", "Monterey Taupe", "Mountain Sage", "Pearl Grey", "Rich Espresso",
  "Sail Cloth", "Soft Green", "Timber Bark", "Traditional Red", "Woodland Cream"];

// Per-range config: label, endpoint, supplier (whose cost we use), colour palette, system options,
// and the "how to quote" guide bullets for a new starter.
const RANGES = {
  cedral: {
    label: "Cedral",
    endpoint: "/quotes/cedral",
    supplier: "AJW",
    colours: CEDRAL_COLOURS,
    defaultSystem: "Lap",
    systems: [
      { value: "Lap", label: "Cedral Lap (weatherboard)" },
      { value: "Click", label: "Cedral Click (flush T&G)" },
    ],
    colourHint: "e.g. Slate Grey",
    guide: [
      ["Area to clad.", "Get the total wall area across all elevations (m²), and the area of windows & doors to deduct (openings). Net = gross − openings."],
      ["Lap or Click?", "Cedral Lap is the overlapped weatherboard look; Click is flush tongue-&-groove. Different coverage and trims — always confirm."],
      ["Colour.", "Confirm the exact Cedral colour (21 options). We never default it — if it's not stated or isn't a real Cedral colour, ask."],
      ["Height & width.", "Give the cladding height and total run width so trims size correctly. Without them we assume 2.4 m and work width out from the area (flagged to confirm)."],
      ["Corners.", "Count external and internal corners (we assume 4 external if not given). Corners drive the corner-profile quantity (corner × height)."],
      ["Openings.", "Note how many windows/doors. Cedral has no single window surround — send the opening sizes and we add the right reveal/sill trims."],
      ["Delivery & access.", "AJW carriage is by postcode zone (free over the zone threshold — see the Pricing → Delivery tab). It's a rigid vehicle needing a forklift; flag mechanical offload (+£75)."],
      ["Margin.", "Check the margin after fees and the discount band below — never quote below an 8% margin."],
    ],
  },
  hardie: {
    label: "James Hardie",
    endpoint: "/quotes/hardie",
    supplier: "UPB",
    colours: HARDIE_COLOURS,
    defaultSystem: "Lap",
    systems: [
      { value: "Lap", label: "HardiePlank (lap weatherboard)" },
      { value: "VL", label: "VL Plank (interlocking 'Click')" },
    ],
    colourHint: "e.g. Anthracite Grey",
    guide: [
      ["Area to clad.", "Get the total wall area across all elevations (m²), and the area of windows & doors to deduct (openings). Net = gross − openings."],
      ["HardiePlank or VL?", "HardiePlank is the overlapped weatherboard (0.54 m²/board). VL Plank is the interlocking board some call 'Click' (0.72 m²/board) with its OWN trim set — 2-part corner, J profile, starter. Always confirm which."],
      ["Colour.", "Confirm the exact James Hardie colour (21 options). We never default it — if it's not stated or isn't a real Hardie colour, ask (never assume a grey)."],
      ["Height & width.", "Give the cladding height and total run width so trims size correctly. Without them we assume 2.4 m and work width out from the area (flagged to confirm)."],
      ["Corners.", "Count external and internal corners (we assume 4 external if not given). Corners × height sizes the corner trims (3 m lengths, rounded up)."],
      ["Openings.", "Note how many windows/doors — each gets a HardieTrim NT3 (lap) or reveal/head trims (VL). Send sizes to tighten it."],
      ["Extras.", "Battens (not a Hardie item — flagged), EPDM joint tape over battens, and touch-up paint + edge sealer for cut edges. Tick what the job needs."],
      ["Margin.", "Hardie cost comes from UPB only. Check the margin after fees and the discount band below — never quote below an 8% margin."],
    ],
  },
};

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function pct(v) { return v == null ? "—" : `${(v * 100).toFixed(1)}%`; }

export default function Quotes() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");

  const [range, setRange] = useState("cedral");
  const [f, setF] = useState({ system: "Lap", colour: "", gross_area_m2: "", openings_m2: "",
    wall_height_m: "", total_width_m: "", external_corners: "", internal_corners: "", num_windows: "",
    wants_trims: true, wants_battens: false, wants_screws: true, wants_epdm: false, wants_paint: false });
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [showGuide, setShowGuide] = useState(true);

  const cfg = RANGES[range];

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

  function pickRange(r) {
    setRange(r);
    setRes(null); setErr("");
    setF((s) => ({ ...s, system: RANGES[r].defaultSystem }));
  }

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
        ...(range === "hardie" ? { wants_epdm: f.wants_epdm, wants_paint: f.wants_paint } : {}),
      };
      const r = await jsonFetch(cfg.endpoint, { method: "POST", body: JSON.stringify(body) });
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
        <div className="pagetitle">Quotes · {cfg.label}</div>
        <div className="right">
          <div className="seg">
            {Object.entries(RANGES).map(([k, v]) => (
              <button key={k} className={`seg-btn ${range === k ? "on" : ""}`} onClick={() => pickRange(k)}>{v.label}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="card q-guide">
        <button className="q-guide-head" onClick={() => setShowGuide((s) => !s)}>
          <span>📋 How to quote {cfg.label} — what to ask &amp; check</span><span>{showGuide ? "▾" : "▸"}</span>
        </button>
        {showGuide && (
          <ol className="q-guide-list">
            {cfg.guide.map(([h, b], i) => <li key={i}><b>{h}</b> {b}</li>)}
          </ol>
        )}
      </div>

      <div className="card q-form">
        <div className="q-section">The wall</div>
        <div className="q-grid">
          <label className="fld"><span>System</span>
            <select className="filter" value={f.system} onChange={(e) => set("system", e.target.value)}>
              {cfg.systems.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          <label className="fld"><span>Colour</span>
            <input className="search" list="qcol" value={f.colour} onChange={(e) => set("colour", e.target.value)} placeholder={cfg.colourHint} />
            <datalist id="qcol">{cfg.colours.map((c) => <option key={c} value={c} />)}</datalist>
          </label>
          <label className="fld"><span>Gross wall area (m²) *</span><input className="search" type="number" inputMode="decimal" value={f.gross_area_m2} onChange={(e) => set("gross_area_m2", e.target.value)} placeholder="all elevations" /></label>
          <label className="fld"><span>Openings (m²)</span><input className="search" type="number" inputMode="decimal" value={f.openings_m2} onChange={(e) => set("openings_m2", e.target.value)} placeholder="windows + doors to deduct" /></label>
          <label className="fld"><span>Wall height (m)</span><input className="search" type="number" inputMode="decimal" value={f.wall_height_m} onChange={(e) => set("wall_height_m", e.target.value)} placeholder="optional — assumes 2.4" /></label>
          <label className="fld"><span>Total run width (m)</span><input className="search" type="number" inputMode="decimal" value={f.total_width_m} onChange={(e) => set("total_width_m", e.target.value)} placeholder="optional" /></label>
        </div>

        <div className="q-section">Corners &amp; openings</div>
        <div className="q-grid">
          <label className="fld"><span>External corners</span><input className="search" type="number" inputMode="numeric" value={f.external_corners} onChange={(e) => set("external_corners", e.target.value)} placeholder="assumes 4" /></label>
          <label className="fld"><span>Internal corners</span><input className="search" type="number" inputMode="numeric" value={f.internal_corners} onChange={(e) => set("internal_corners", e.target.value)} placeholder="0" /></label>
          <label className="fld"><span>Windows / doors</span><input className="search" type="number" inputMode="numeric" value={f.num_windows} onChange={(e) => set("num_windows", e.target.value)} placeholder="count (optional)" /></label>
        </div>

        <div className="q-section">Include in the quote</div>
        <div className="q-opts">
          <label className="switch"><input type="checkbox" checked={f.wants_trims} onChange={(e) => set("wants_trims", e.target.checked)} /><span>Trims (corners &amp; start profile)</span></label>
          <label className="switch"><input type="checkbox" checked={f.wants_screws} onChange={(e) => set("wants_screws", e.target.checked)} /><span>Fixings</span></label>
          <label className="switch"><input type="checkbox" checked={f.wants_battens} onChange={(e) => set("wants_battens", e.target.checked)} /><span>Battens <span className="sub">(not {cfg.supplier} — flagged)</span></span></label>
          {range === "hardie" && <>
            <label className="switch"><input type="checkbox" checked={f.wants_epdm} onChange={(e) => set("wants_epdm", e.target.checked)} /><span>EPDM joint tape</span></label>
            <label className="switch"><input type="checkbox" checked={f.wants_paint} onChange={(e) => set("wants_paint", e.target.checked)} /><span>Touch-up paint + edge sealer</span></label>
          </>}
          <span style={{ flex: 1 }} />
          <button className="btn primary" onClick={build} disabled={busy}>{busy ? "Building…" : "Build quote"}</button>
        </div>
        {err && <div className="route-msg warn" style={{ marginTop: 10 }}>{err}</div>}
      </div>

      {res && (
        <>
          <div className="card" style={{ padding: "6px 12px 12px", marginBottom: 10 }}>
            <div className="tool-label">{res.product}{res.colour ? ` · ${res.colour}` : ""} — {t.n_priced}/{t.n_total} lines priced</div>
            <table className="mini">
              <thead><tr><th>Item</th><th className="num">Qty</th><th>Matched product</th><th className="num">Unit</th><th className="num">Line</th><th className="num">Cost ({cfg.supplier})</th></tr></thead>
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
              <div className="kv"><span>Cost ({cfg.supplier})</span><b>{money(t.cost)}</b></div>
              <div className="kv big"><span>Margin (after 1.8% fee)</span><b className={t.margin_net == null ? "" : t.margin_net < 8 ? "mred" : t.margin_net < 15 ? "mamber" : "mgreen"}>{t.margin_net == null ? "—" : `${t.margin_net}%`}</b></div>
            </div>
            {dsc && (
              <div className="card q-tot">
                <div className="tool-label">Discount desk — {dsc.band}</div>
                <div className="sub" style={{ marginBottom: 4 }}>You may give up to {pct(dsc.give)} of the margin away, down to a {money(dsc.floor_price)} floor (never below 8%).</div>
                <div className="kv"><span>Lowest you may quote</span><b>{money(dsc.floor_price)}</b></div>
                <div className="kv"><span>Max discount</span><b>{dsc.no_room ? "no room" : money(dsc.max_disc)}</b></div>
                <div className="kv"><span>Opening price (less 4%)</span><b>{money(dsc.four_pc_price)}</b></div>
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
