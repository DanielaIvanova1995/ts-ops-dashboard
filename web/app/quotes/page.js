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

const POLY_SHEETS = ["10mm Twinwall", "16mm Multiwall", "25mm Multiwall", "32mm Multiwall", "35mm Multiwall"];
const POLY_COLOURS = ["Clear", "Opal", "Bronze", "Heatguard Opal", "Bronze on Opal"];
const POLY_WIDTHS = [{ v: 700, l: "700 mm" }, { v: 1050, l: "1050 mm" }, { v: 1200, l: "1200 mm" }, { v: 2100, l: "2100 mm" }];
const POLY_SYSTEMS = ["Self-Supported (16/35mm)", "Artisan"];
const POLY_BAR_COLOURS = ["White", "Brown", "Anthracite Grey"];
const EZGLAZE_COLOURS = ["Clear", "Breeze Blue", "Solar Ice", "Beehive Clear"];
const STORM_SHEETS = ["10mm Twinwall", "16mm Triplewall", "25mm Multiwall", "35mm Multiwall"];
const STORM_COLOURS = ["Clear", "Bronze", "Opal"];
const STORM_WIDTHS = [{ v: 700, l: "700 mm" }, { v: 1050, l: "1050 mm" }, { v: 1400, l: "1400 mm" }, { v: 2100, l: "2100 mm" }];
const STORM_BAR_COLOURS = ["White", "Brown"];

// Per-range config: label, endpoint, supplier (whose cost we use), and the "how to quote" guide.
const RANGES = {
  cedral: {
    label: "Cedral", endpoint: "/quotes/cedral", supplier: "AJW", kind: "clad",
    installGuide: { url: "https://www.cedral.world/siteassets/documents/uk/cedral-fixing-guide-UK", label: "Cedral UK fixing guide" },
    colours: CEDRAL_COLOURS, defaultSystem: "Lap", colourHint: "e.g. Slate Grey",
    systems: [{ value: "Lap", label: "Cedral Lap (weatherboard)" }, { value: "Click", label: "Cedral Click (flush T&G)" }],
    guide: [
      ["Area to clad.", "Get the total wall area across all elevations (m²), and the area of windows & doors to deduct (openings). Net = gross − openings."],
      ["Lap or Click?", "Cedral Lap is the overlapped weatherboard look; Click is flush tongue-&-groove. Different coverage and trims — always confirm."],
      ["Colour.", "Confirm the exact Cedral colour (21 options). We never default it — if it's not stated or isn't a real Cedral colour, ask."],
      ["Height & width.", "Give the cladding height and total run width so trims size correctly. Without them we assume 2.4 m and work width out from the area (flagged)."],
      ["Corners.", "Count external and internal corners (we assume 4 external if not given). Corners drive the corner-profile quantity (corner × height)."],
      ["Openings.", "Note how many windows/doors. Cedral has no single window surround — send the opening sizes and we add the right reveal/sill trims."],
      ["Delivery & access.", "AJW carriage is by postcode zone (free over the zone threshold — see Pricing → Delivery). Rigid vehicle needing a forklift; flag mechanical offload (+£75)."],
      ["Margin.", "Check the margin after fees and the discount band below — never quote below an 8% margin."],
    ],
  },
  hardie: {
    label: "James Hardie", endpoint: "/quotes/hardie", supplier: "UPB", kind: "clad",
    installGuide: { url: "https://www.jameshardie.eu/GB-en/products/fixings", label: "James Hardie fitting & fixings (official)" },
    colours: HARDIE_COLOURS, defaultSystem: "Lap", colourHint: "e.g. Anthracite Grey",
    systems: [{ value: "Lap", label: "HardiePlank (lap weatherboard)" }, { value: "VL", label: "VL Plank (interlocking 'Click')" }],
    guide: [
      ["Area to clad.", "Get the total wall area across all elevations (m²), and the area of windows & doors to deduct (openings). Net = gross − openings."],
      ["HardiePlank or VL?", "HardiePlank is the overlapped weatherboard (0.54 m²/board). VL Plank is the interlocking board some call 'Click' (0.72 m²/board) with its OWN trim set. Always confirm which."],
      ["Colour.", "Confirm the exact James Hardie colour (21 options). We never default it — if it's not stated or isn't a real Hardie colour, ask (never assume a grey)."],
      ["Height & width.", "Give the cladding height and total run width so trims size correctly. Without them we assume 2.4 m and work width out from the area (flagged)."],
      ["Corners.", "Count external and internal corners (we assume 4 external if not given). Corners × height sizes the corner trims (3 m lengths, rounded up)."],
      ["Openings.", "Note how many windows/doors — each gets a HardieTrim NT3 (lap) or reveal/head trims (VL). Send sizes to tighten it."],
      ["Extras.", "Battens (not a Hardie item — flagged), EPDM joint tape over battens, and touch-up paint + edge sealer for cut edges. Tick what the job needs."],
      ["Margin.", "Hardie cost comes from UPB only. Check the margin after fees and the discount band below — never quote below an 8% margin."],
    ],
  },
  molan: {
    label: "Molan (poly roof)", endpoint: "/quotes/molan", supplier: "Molan", kind: "roof",
    guide: [
      ["Roof size.", "Get the front span (width, m) along the house and the slope/rafter length (rake, m) from wall to eaves. Sheets run down the slope."],
      ["Sheet.", "Pick the thickness/wall (10mm Twinwall up to 35mm Multiwall) and the tint (Clear, Opal, Bronze, Heatguard). Thicker = warmer/stronger."],
      ["Sheet width.", "700/1050/1200/2100 mm. We work out how many sheets cover the span, and how many intermediate + end bars sit between them."],
      ["Bar system.", "Self-Supported (16/35mm) or Artisan (adds an eaves beam). Bars come in 2/3/4/6 m — we pick the shortest that covers the slope."],
      ["Over 6 m slopes.", "A slope longer than 6 m needs the sheets/bars joined (extra H-section) — flagged so you add it."],
      ["Accessories.", "Anti-dust tape seals the sheet tops and vented foil tape the bottoms — leave ticked unless the customer has them."],
      ["Brand lock.", "All polycarbonate is quoted as Molan only. Margin after fees + discount band below — never below 8%."],
    ],
  },
  storm: {
    label: "Storm (poly roof)", endpoint: "/quotes/storm", supplier: "Storm", kind: "stormroof",
    guide: [
      ["What it is.", "Storm's self-support polycarbonate roof — multiwall sheets on Storm's own Rafter Bar glazing-bar system. Costed from Storm's prices."],
      ["Roof size.", "Get the span (width, m) along the house and the slope length (m) from wall to eaves. Sheets run down the slope between the bars."],
      ["Sheet.", "Thickness/wall (10mm Twinwall / 16mm Triplewall / 25mm or 35mm Multiwall) and tint (Clear, Bronze, Opal)."],
      ["Sheet width.", "700/1050/1400/2100 mm — this sets how many sheets (and bars) cover the span. We match the nearest Storm stock length for the slope."],
      ["Bars.", "Storm Rafter Bars come in 3 m and 4 m — we pick the shortest that covers the slope, one either side of each sheet, with end caps and edge trim."],
      ["Finish.", "Lean-to flashing trim at the top wall, sheet closures at the ends, plus tape and fixing buttons. Counts are estimates to confirm."],
      ["Over 7 m slope.", "Longer than Storm's longest stock sheet — sheets/bars will need joining (flagged)."],
      ["Margin.", "Margin after fees + discount band below — never below 8%."],
    ],
  },
  ezglaze: {
    label: "EZ Glaze", endpoint: "/quotes/ezglaze", supplier: "Molan", kind: "ezglaze",
    guide: [
      ["What it is.", "EZ Glaze is Molan's corrugated polycarbonate roofing — lightweight sheets for lean-tos, carports and canopies. Brand-locked to Molan."],
      ["Roof size.", "Get the roof width (m) across the front and the slope length (m) from eaves to ridge. Sheets run down the slope."],
      ["Sheet cover.", "The usable cover width per sheet (default 1.0 m) — confirm for the exact profile. We work out how many sheets cover the width."],
      ["Length.", "We match each sheet to the nearest EZ Glaze stock length (2.5/3/3.5/4/6/7 m) that covers the slope."],
      ["Colour.", "Clear, Breeze Blue, Solar Ice or Beehive Clear."],
      ["Accessories.", "Foam sealing strip, screws & washers and the wall connector are sized from the roof — estimates to confirm."],
      ["Margin.", "Margin after fees + discount band below — never below 8%."],
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
  const [f, setF] = useState({
    // cladding
    system: "Lap", colour: "", gross_area_m2: "", openings_m2: "", wall_height_m: "", total_width_m: "",
    external_corners: "", internal_corners: "", num_windows: "",
    wants_trims: true, wants_battens: false, wants_screws: true, wants_epdm: false, wants_paint: false,
    // roof (molan)
    width: "", rake: "", sheet_width_mm: 1050, sheet_type: "25mm Multiwall", molan_colour: "Clear",
    poly_system: "Self-Supported (16/35mm)", bar_colour: "White", include_acc: true,
    // ez glaze
    ez_cover: 1.0, ez_colour: "Clear",
    // storm roof
    st_width_mm: 1050, st_sheet_type: "25mm Multiwall", st_colour: "Clear", st_bar_colour: "White",
  });
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [showGuide, setShowGuide] = useState(true);

  // customer details + draft/email state
  const [cust, setCust] = useState({ name: "", email: "", postcode: "" });
  const [draft, setDraft] = useState(null);      // { name, admin_url, total, tax } | { error }
  const [drafting, setDrafting] = useState(false);
  const [copied, setCopied] = useState(false);

  // extra products added by hand
  const [extras, setExtras] = useState([]);      // [{variant_id,title,sku,qty,unit_sell}]
  const [psearch, setPsearch] = useState("");
  const [presults, setPresults] = useState(null); // null | [results]
  const [psearching, setPsearching] = useState(false);

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
    setRange(r); setRes(null); setErr(""); setDraft(null); setCopied(false);
    setExtras([]); setPresults(null); setPsearch("");
    if (RANGES[r].kind === "clad") setF((s) => ({ ...s, system: RANGES[r].defaultSystem }));
  }

  async function searchProducts() {
    if (psearch.trim().length < 2) { setPresults([]); return; }
    setPsearching(true);
    try {
      const r = await jsonFetch(`/quotes/search?q=${encodeURIComponent(psearch.trim())}`);
      const d = await r.json();
      setPresults(d.results || []);
    } catch (e) { if (String(e.message) !== "unauthorised") setPresults([]); }
    finally { setPsearching(false); }
  }
  function addExtra(p) {
    if (!p.variant_id) return;
    setExtras((x) => [...x, { variant_id: p.variant_id, title: p.title, sku: p.sku, qty: 1, unit_sell: p.price }]);
    setPresults(null); setPsearch("");
  }
  function setExtraQty(i, q) { setExtras((x) => x.map((e, j) => (j === i ? { ...e, qty: Math.max(1, Number(q) || 1) } : e))); }
  function removeExtra(i) { setExtras((x) => x.filter((_, j) => j !== i)); }

  async function build() {
    setErr(""); setRes(null); setDraft(null); setCopied(false); setExtras([]); setPresults(null);
    let body;
    if (cfg.kind === "roof") {
      if (!f.width || !f.rake) { setErr("Enter the roof span (width) and slope length."); return; }
      body = { width: Number(f.width), rake: Number(f.rake), sheet_width_mm: Number(f.sheet_width_mm),
        sheet_type: f.sheet_type, colour: f.molan_colour, system: f.poly_system,
        bar_colour: f.bar_colour, include_acc: f.include_acc };
    } else if (cfg.kind === "ezglaze") {
      if (!f.width || !f.rake) { setErr("Enter the roof width and slope length."); return; }
      body = { width: Number(f.width), slope: Number(f.rake), cover: Number(f.ez_cover || 1.0), colour: f.ez_colour };
    } else if (cfg.kind === "stormroof") {
      if (!f.width || !f.rake) { setErr("Enter the roof span (width) and slope length."); return; }
      body = { width: Number(f.width), slope: Number(f.rake), sheet_width_mm: Number(f.st_width_mm),
        sheet_type: f.st_sheet_type, colour: f.st_colour, bar_colour: f.st_bar_colour, include_acc: f.include_acc };
    } else {
      if (!f.gross_area_m2) { setErr("Enter the gross wall area (m²)."); return; }
      body = { system: f.system, colour: f.colour,
        gross_area_m2: Number(f.gross_area_m2), openings_m2: Number(f.openings_m2 || 0),
        wall_height_m: num(f.wall_height_m), total_width_m: num(f.total_width_m),
        external_corners: num(f.external_corners), internal_corners: Number(f.internal_corners || 0),
        num_windows: num(f.num_windows),
        wants_trims: f.wants_trims, wants_battens: f.wants_battens, wants_screws: f.wants_screws,
        ...(range === "hardie" ? { wants_epdm: f.wants_epdm, wants_paint: f.wants_paint } : {}) };
    }
    setBusy(true);
    try {
      const r = await jsonFetch(cfg.endpoint, { method: "POST", body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `API ${r.status}`);
      if (!d.ok) { setErr(d.detail || "Couldn’t build the quote."); return; }
      setRes(d);
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  // Lines that matched a product with a variant id — the only ones a draft order can carry.
  // Take-off lines plus any hand-added extras (normalised to the same {matched, qty} shape).
  const extrasSell = extras.reduce((s, e) => s + (Number(e.unit_sell) || 0) * e.qty, 0);
  const draftableLines = [
    ...(res?.lines || []).filter((l) => l.matched && l.matched.variant_id && l.unit_sell != null),
    ...extras.filter((e) => e.variant_id && e.unit_sell != null).map((e) => ({ matched: { variant_id: e.variant_id }, qty: e.qty })),
  ];

  async function buildDraft() {
    if (!draftableLines.length) { setDraft({ error: "No matched, priced lines to put on a draft." }); return; }
    if (!window.confirm(`Create a Shopify DRAFT order with ${draftableLines.length} line(s)? It takes no payment — you can edit it in Shopify before sending.`)) return;
    setDrafting(true); setDraft(null);
    try {
      const items = draftableLines.map((l) => ({ variant_id: l.matched.variant_id, qty: l.qty }));
      const r = await jsonFetch("/quotes/draft", { method: "POST", body: JSON.stringify({
        items, customer_email: cust.email || null, customer_name: cust.name || null,
        postcode: cust.postcode || null, note: `TradeHub quote — ${res.product}` }) });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.detail || `API ${r.status}`);
      setDraft(d);
    } catch (e) { if (String(e.message) !== "unauthorised") setDraft({ error: String(e.message || e) }); }
    finally { setDrafting(false); }
  }

  function emailText() {
    const t = res.totals;
    const hi = cust.name ? `Hi ${cust.name.split(" ")[0]},` : "Hi there,";
    const priced = (res.lines || []).filter((l) => l.unit_sell != null);
    const unpriced = (res.lines || []).filter((l) => l.unit_sell == null);
    const L = [];
    L.push(hi, "");
    L.push(`Thank you for your enquiry — please find your quote for ${res.product} below.`, "");
    priced.forEach((l) => L.push(`• ${l.qty} × ${l.description} — ${money(l.line_sell)}`));
    extras.forEach((e) => L.push(`• ${e.qty} × ${e.title}${e.sku ? ` (${e.sku})` : ""} — ${money((Number(e.unit_sell) || 0) * e.qty)}`));
    const grand = (t.sell || 0) + extrasSell;
    if (grand) {
      const vat = grand * 0.2;
      L.push("", `Subtotal (ex VAT): ${money(grand)}`, `VAT (20%): ${money(vat)}`, `Total (inc VAT): ${money(grand + vat)}`);
    }
    if (unpriced.length) {
      L.push("", "Also required (not included above — we can source or advise):");
      unpriced.forEach((l) => L.push(`• ${l.qty} × ${l.description}`));
    }
    L.push("", "Prices are ex VAT unless stated. Delivery is quoted by postcode — send me yours and I'll confirm the carriage.",
      "This quote is valid for 30 days. Any questions, just reply and I'll be happy to help.",
      "", "Kind regards,", "Trade Superstore Online");
    return L.join("\n");
  }

  async function copyEmail() {
    try {
      await navigator.clipboard.writeText(emailText());
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    } catch { setCopied(false); window.prompt("Copy the quote email:", emailText()); }
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
          <>
            <ol className="q-guide-list">
              {cfg.guide.map(([h, b], i) => <li key={i}><b>{h}</b> {b}</li>)}
            </ol>
            {cfg.installGuide && (
              <div className="sub" style={{ padding: "0 16px 12px" }}>
                📄 <a href={cfg.installGuide.url} target="_blank" rel="noreferrer">Official install guide — {cfg.installGuide.label} ↗</a>
              </div>
            )}
          </>
        )}
      </div>

      {cfg.kind === "stormroof" ? (
        <div className="card q-form">
          <div className="q-section">The roof</div>
          <div className="q-grid">
            <label className="fld"><span>Span / width (m) *</span><input className="search" type="number" inputMode="decimal" value={f.width} onChange={(e) => set("width", e.target.value)} placeholder="along the house" /></label>
            <label className="fld"><span>Slope length (m) *</span><input className="search" type="number" inputMode="decimal" value={f.rake} onChange={(e) => set("rake", e.target.value)} placeholder="wall to eaves" /></label>
            <label className="fld"><span>Sheet type</span>
              <select className="filter" value={f.st_sheet_type} onChange={(e) => set("st_sheet_type", e.target.value)}>{STORM_SHEETS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
            <label className="fld"><span>Tint / colour</span>
              <select className="filter" value={f.st_colour} onChange={(e) => set("st_colour", e.target.value)}>{STORM_COLOURS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
            <label className="fld"><span>Sheet width</span>
              <select className="filter" value={f.st_width_mm} onChange={(e) => set("st_width_mm", Number(e.target.value))}>{STORM_WIDTHS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}</select>
            </label>
            <label className="fld"><span>Bar colour</span>
              <select className="filter" value={f.st_bar_colour} onChange={(e) => set("st_bar_colour", e.target.value)}>{STORM_BAR_COLOURS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
          </div>
          <div className="q-opts">
            <label className="switch"><input type="checkbox" checked={f.include_acc} onChange={(e) => set("include_acc", e.target.checked)} /><span>Tape &amp; fixing buttons</span></label>
            <span style={{ flex: 1 }} />
            <button className="btn primary" onClick={build} disabled={busy}>{busy ? "Building…" : "Build quote"}</button>
          </div>
          {err && <div className="route-msg warn" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      ) : cfg.kind === "ezglaze" ? (
        <div className="card q-form">
          <div className="q-section">The roof</div>
          <div className="q-grid">
            <label className="fld"><span>Roof width (m) *</span><input className="search" type="number" inputMode="decimal" value={f.width} onChange={(e) => set("width", e.target.value)} placeholder="across the front" /></label>
            <label className="fld"><span>Slope length (m) *</span><input className="search" type="number" inputMode="decimal" value={f.rake} onChange={(e) => set("rake", e.target.value)} placeholder="eaves → ridge" /></label>
            <label className="fld"><span>Sheet cover width (m)</span><input className="search" type="number" inputMode="decimal" value={f.ez_cover} onChange={(e) => set("ez_cover", e.target.value)} placeholder="default 1.0" /></label>
            <label className="fld"><span>Colour</span>
              <select className="filter" value={f.ez_colour} onChange={(e) => set("ez_colour", e.target.value)}>{EZGLAZE_COLOURS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
          </div>
          <div className="q-opts">
            <span style={{ flex: 1 }} />
            <button className="btn primary" onClick={build} disabled={busy}>{busy ? "Building…" : "Build quote"}</button>
          </div>
          {err && <div className="route-msg warn" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      ) : cfg.kind === "roof" ? (
        <div className="card q-form">
          <div className="q-section">The roof</div>
          <div className="q-grid">
            <label className="fld"><span>Span / width (m) *</span><input className="search" type="number" inputMode="decimal" value={f.width} onChange={(e) => set("width", e.target.value)} placeholder="front edge" /></label>
            <label className="fld"><span>Slope length (m) *</span><input className="search" type="number" inputMode="decimal" value={f.rake} onChange={(e) => set("rake", e.target.value)} placeholder="wall to eaves" /></label>
            <label className="fld"><span>Sheet type</span>
              <select className="filter" value={f.sheet_type} onChange={(e) => set("sheet_type", e.target.value)}>{POLY_SHEETS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
            <label className="fld"><span>Tint / colour</span>
              <select className="filter" value={f.molan_colour} onChange={(e) => set("molan_colour", e.target.value)}>{POLY_COLOURS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
            <label className="fld"><span>Sheet width</span>
              <select className="filter" value={f.sheet_width_mm} onChange={(e) => set("sheet_width_mm", Number(e.target.value))}>{POLY_WIDTHS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}</select>
            </label>
            <label className="fld"><span>Bar system</span>
              <select className="filter" value={f.poly_system} onChange={(e) => set("poly_system", e.target.value)}>{POLY_SYSTEMS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
            <label className="fld"><span>Bar colour</span>
              <select className="filter" value={f.bar_colour} onChange={(e) => set("bar_colour", e.target.value)}>{POLY_BAR_COLOURS.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            </label>
          </div>
          <div className="q-opts">
            <label className="switch"><input type="checkbox" checked={f.include_acc} onChange={(e) => set("include_acc", e.target.checked)} /><span>Anti-dust &amp; vented foil tape</span></label>
            <span style={{ flex: 1 }} />
            <button className="btn primary" onClick={build} disabled={busy}>{busy ? "Building…" : "Build quote"}</button>
          </div>
          {err && <div className="route-msg warn" style={{ marginTop: 10 }}>{err}</div>}
        </div>
      ) : (
        <div className="card q-form">
          <div className="q-section">The wall</div>
          <div className="q-grid">
            <label className="fld"><span>System</span>
              <select className="filter" value={f.system} onChange={(e) => set("system", e.target.value)}>
                {cfg.systems.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </label>
            <label className="fld"><span>Colour</span>
              <select className="filter" value={f.colour} onChange={(e) => set("colour", e.target.value)}>
                <option value="">— choose a colour —</option>
                {cfg.colours.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
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
      )}

      {res && (
        <>
          <div className="card" style={{ padding: "6px 12px 12px", marginBottom: 10 }}>
            <div className="tool-label">{res.product}{res.colour && cfg.kind === "clad" ? ` · ${res.colour}` : ""} — {t.n_priced}/{t.n_total} lines priced</div>
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

          <div className="card" style={{ padding: "10px 14px", marginBottom: 10 }}>
            <div className="tool-label">Add another product</div>
            {extras.length > 0 && (
              <table className="mini" style={{ marginBottom: 8 }}>
                <thead><tr><th>Added product</th><th className="num">Qty</th><th className="num">Unit</th><th className="num">Line</th><th></th></tr></thead>
                <tbody>
                  {extras.map((e, i) => (
                    <tr key={i}>
                      <td>{e.title}{e.sku ? <span className="sub"> ({e.sku})</span> : null}</td>
                      <td className="num"><input className="numin" type="number" min="1" value={e.qty} onChange={(ev) => setExtraQty(i, ev.target.value)} style={{ width: 56 }} /></td>
                      <td className="num">{e.unit_sell != null ? money(e.unit_sell) : "—"}</td>
                      <td className="num">{e.unit_sell != null ? money(e.unit_sell * e.qty) : "—"}</td>
                      <td className="num"><button className="btn ghost" onClick={() => removeExtra(i)}>✕</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="q-opts" style={{ marginTop: 0 }}>
              <input className="search" style={{ maxWidth: 320 }} value={psearch} placeholder="Search a product to add (e.g. breather membrane)"
                onChange={(e) => setPsearch(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") searchProducts(); }} />
              <button className="btn" onClick={searchProducts} disabled={psearching || psearch.trim().length < 2}>{psearching ? "Searching…" : "Search"}</button>
            </div>
            {presults && presults.length === 0 && <div className="sub" style={{ marginTop: 8 }}>No products matched “{psearch}”.</div>}
            {presults && presults.length > 0 && (
              <table className="mini" style={{ marginTop: 8 }}>
                <thead><tr><th>Product</th><th>SKU</th><th className="num">Price</th><th></th></tr></thead>
                <tbody>
                  {presults.map((p, i) => (
                    <tr key={i}>
                      <td>{p.title}{p.vendor ? <span className="sub"> · {p.vendor}</span> : null}</td>
                      <td className="sub">{p.sku || "—"}</td>
                      <td className="num">{p.price != null ? money(p.price) : "—"}</td>
                      <td className="num"><button className="btn ghost" onClick={() => addExtra(p)} disabled={!p.variant_id}>Add</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="q-cards">
            <div className="card q-tot">
              <div className="tool-label">Totals (ex VAT)</div>
              <div className="kv"><span>Sell{extras.length ? " (take-off)" : ""}</span><b>{money(t.sell)}</b></div>
              {extras.length ? <div className="kv"><span>Extras</span><b>{money(extrasSell)}</b></div> : null}
              {extras.length ? <div className="kv"><span>Sell incl. extras</span><b>{money((t.sell || 0) + extrasSell)}</b></div> : null}
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

          <div className="card q-actions" style={{ padding: "12px 14px", marginTop: 10 }}>
            <div className="tool-label">Turn this into a quote</div>
            <div className="q-grid" style={{ marginBottom: 10 }}>
              <label className="fld"><span>Customer name</span><input className="search" value={cust.name} onChange={(e) => setCust((s) => ({ ...s, name: e.target.value }))} placeholder="for the draft & email" /></label>
              <label className="fld"><span>Customer email</span><input className="search" value={cust.email} onChange={(e) => setCust((s) => ({ ...s, email: e.target.value }))} placeholder="optional" /></label>
              <label className="fld"><span>Delivery postcode</span><input className="search" value={cust.postcode} onChange={(e) => setCust((s) => ({ ...s, postcode: e.target.value }))} placeholder="for VAT region" /></label>
            </div>
            <div className="q-opts">
              <button className="btn primary" onClick={buildDraft} disabled={drafting || !draftableLines.length}>{drafting ? "Creating…" : `Build Shopify draft (${draftableLines.length})`}</button>
              <button className="btn" onClick={copyEmail}>{copied ? "Copied ✓" : "Copy email for Outlook"}</button>
              <span className="sub">Draft adds 20% VAT and takes no payment — edit it in Shopify before sending.</span>
            </div>
            {draft && !draft.error && (
              <div className="route-msg ok" style={{ marginTop: 10 }}>
                Draft {draft.name} created — total {money(draft.total)} inc VAT.{" "}
                {draft.admin_url && <a href={draft.admin_url} target="_blank" rel="noreferrer">Open in Shopify ↗</a>}
              </div>
            )}
            {draft && draft.error && <div className="route-msg warn" style={{ marginTop: 10 }}>{draft.error}</div>}
          </div>
        </>
      )}
    </div>
  );
}
