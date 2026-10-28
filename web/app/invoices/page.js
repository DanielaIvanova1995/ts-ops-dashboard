"use client";

import { Fragment, useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY_STORE = "th_access_key";

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
}
function actionLabel(a, matched) {
  if (!matched) return { cls: "red", text: "Discrepancy — needs review" };
  if (a === "push") return { cls: "green", text: "Matches — ready to approve" };
  if (a === "hold") return { cls: "amber", text: "Matches — held (margin below floor)" };
  if (a === "flag") return { cls: "amber", text: "Matches — margin high, review" };
  return { cls: "grey", text: "Matches" };
}

// Pull the specific discrepancies out of a check result, and best-effort the overcharge total.
// Overcharge comes from (invoiced − agreed) × qty on priced lines where we have the figures, else
// from the two £ amounts in the issue message ("£X vs agreed/expected £Y").
function discrepancyDetail(r) {
  const lines = [];
  let oc = 0, ocOk = false, approx = false;
  (r?.lines || []).forEach((l) => {
    (l.issues || []).filter((x) => x[0] !== "name").forEach((x) => {
      lines.push(`${l.sku || l.desc || "line"}: ${x[1]}`);
      if (x[0] === "price" && typeof l.unit === "number" && typeof l.cost === "number" && typeof l.qty === "number" && l.unit > l.cost) {
        oc += (l.unit - l.cost) * l.qty; ocOk = true;
      } else {
        const m = /£\s*([\d,]+(?:\.\d+)?)[^£]*£\s*([\d,]+(?:\.\d+)?)/.exec(x[1] || "");
        if (m) { oc += parseFloat(m[1].replace(/,/g, "")) - parseFloat(m[2].replace(/,/g, "")); ocOk = true; approx = true; }
        else approx = true;
      }
    });
  });
  (r?.missing || []).forEach((m) => lines.push(`on the order but not invoiced: ${m}`));
  const overcharge = ocOk && oc > 0.005 ? Math.round(oc * 100) / 100 : null;
  return { lines, overcharge, approx };
}

// The discrepancy SPECIFICS — what's wrong, as bullet points — written to Monday AND dropped into
// the supplier query email. Just the facts; the email template supplies the friendly ask + closing,
// so no internal tool name and no resolution boilerplate here (that would double up in the email).
function discrepancyReason(iv, r) {
  const d = discrepancyDetail(r);
  const L = [];
  (d.lines.length ? d.lines : ["see invoice"]).forEach((s) => L.push("• " + s));
  const f = (n) => `£${n.toFixed(2)}`;
  if (d.overcharge != null) L.push(`Overcharged by ${d.approx ? "~" : ""}${f(d.overcharge)}.`);
  return L.join("\n");
}

function ImportPanel({ jsonFetch, onNotice }) {
  const [open, setOpen] = useState(false);
  const [folder, setFolder] = useState("Travis Perkins");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState(null);

  async function run(dry) {
    if (!dry && !window.confirm(`Import for real from "${folder}"? This creates invoice subitems on Monday.`)) return;
    setRunning(true); setStatus(null);
    try {
      const res = await jsonFetch("/invoices/import-run", { method: "POST", body: JSON.stringify({ folders: folder.trim() ? [folder.trim()] : null, dry_run: dry, limit: 15 }) });
      const d = await res.json();
      if (!(res.ok && d.started)) { onNotice({ kind: "warn", text: d.detail || "Couldn’t start the import." }); setRunning(false); return; }
      let tries = 0;
      const poll = async () => {
        tries++;
        try {
          const sr = await jsonFetch("/invoices/import-run-status");
          const sd = await sr.json();
          const st = sd.status || {};
          setStatus(st);
          if (st.running && tries < 80) setTimeout(poll, 3000);
          else setRunning(false);
        } catch { setRunning(false); }
      };
      setTimeout(poll, 2500);
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); setRunning(false); }
  }

  const items = status?.items || [];
  const would = items.filter((x) => x.status === "would_import" || x.status === "imported");
  const failed = items.filter((x) => x.status === "failed");
  const byAddr = would.filter((x) => /customer/i.test(x.detail || ""));
  return (
    <div className="card" style={{ padding: "10px 14px", marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button className="btn ghost" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} Import from email</button>
        <span className="sub">Preview how invoices in an Outlook folder match to orders — including by delivery address.</span>
      </div>
      {open && (
        <div style={{ marginTop: 10 }}>
          <div className="inv-controls">
            <input className="search" style={{ maxWidth: 240, flex: "none" }} value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Supplier folder (e.g. Travis Perkins)" />
            <button className="btn primary" onClick={() => run(true)} disabled={running}>{running ? "Working…" : "Preview (dry run)"}</button>
          </div>
          {running && <div className="sub" style={{ marginTop: 8 }}>Reading &amp; matching invoices… each PDF is parsed, so give it a moment.</div>}
          {status && !status.running && (
            status.error
              ? <div className="route-msg warn" style={{ marginTop: 10 }}>{status.error}</div>
              : (
                <div style={{ marginTop: 10 }}>
                  <div className="sub">Scanned {status.scanned ?? 0} · <b>{status.dry_run ? "would match" : "imported"} {status.imported ?? 0}</b>{byAddr.length ? <> · <b>{byAddr.length}</b> by address</> : null} · failed {status.failed ?? 0} · skipped {status.skipped ?? 0}{status.capped ? " · (capped — run again for more)" : ""}</div>
                  {would.length > 0 && (
                    <table className="mini" style={{ marginTop: 8 }}>
                      <thead><tr><th>Invoice</th><th>Supplier</th><th>Order</th><th>How it matched</th></tr></thead>
                      <tbody>{would.map((x, i) => <tr key={i}><td>{x.invoice_no || "—"}</td><td className="sub">{x.supplier || "—"}</td><td>{x.order_no || "—"}</td><td className="sub">{x.detail || ""}</td></tr>)}</tbody>
                    </table>
                  )}
                  {failed.length > 0 && (
                    <div style={{ marginTop: 10 }}>
                      <div className="sub"><b>{failed.length}</b> didn’t match an order:</div>
                      <table className="mini"><tbody>{failed.map((x, i) => <tr key={i}><td>{x.invoice_no || "—"}</td><td className="sub">{x.detail || ""}</td></tr>)}</tbody></table>
                    </div>
                  )}
                  {status.dry_run && would.length > 0 && <button className="btn primary" style={{ marginTop: 10 }} onClick={() => run(false)} disabled={running}>Import these for real</button>}
                </div>
              )
          )}
        </div>
      )}
    </div>
  );
}

export default function Invoices() {
  const [accessKey, setAccessKey] = useState(null);
  const [needKey, setNeedKey] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [list, setList] = useState([]);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [checks, setChecks] = useState({});     // sub_id -> result
  const [checking, setChecking] = useState({}); // sub_id -> bool
  const [sel, setSel] = useState(() => new Set());
  const [approving, setApproving] = useState({}); // sub_id -> working|done|err
  const [approveMsg, setApproveMsg] = useState({}); // sub_id -> { kind, text }
  const [findingPdf, setFindingPdf] = useState({}); // sub_id -> bool
  const [proc, setProc] = useState(null);
  const [notice, setNotice] = useState(null);
  const [floor, setFloor] = useState(10);
  const [ceil, setCeil] = useState(35);
  const [supFilter, setSupFilter] = useState("");
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]); // server-side matches across ALL statuses
  const [sortBy, setSortBy] = useState("");
  const [onlyDup, setOnlyDup] = useState(false);
  const [tab, setTab] = useState("review");       // "review" | "disc"
  const [disc, setDisc] = useState([]);
  const [discStatus, setDiscStatus] = useState("idle");
  const [unflagging, setUnflagging] = useState({}); // sub_id -> bool
  const [discCopied, setDiscCopied] = useState({}); // sub_id -> bool
  const [discSel, setDiscSel] = useState(() => new Set()); // sub_ids selected for bulk chase
  const [chasing, setChasing] = useState(false);
  const [chaseResult, setChaseResult] = useState(null); // {drafted, suppliers:[...]}
  const [discSupFilter, setDiscSupFilter] = useState(""); // "" = all suppliers on the Discrepancies tab
  function toggleDiscSel(id) { setDiscSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  const [orderOpen, setOrderOpen] = useState(() => new Set()); // sub_ids with the Monday order panel open
  function toggleOrder(id) { setOrderOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  const [accepted, setAccepted] = useState({}); // sub_id -> Set(line keys the user has accepted as OK)
  function toggleAccept(sub_id, key) {
    setAccepted((a) => { const n = { ...a }; const s = new Set(n[sub_id] || []); s.has(key) ? s.delete(key) : s.add(key); n[sub_id] = s; return n; });
  }

  useEffect(() => {
    try {
      const f = localStorage.getItem("th_inv_floor"); const c = localStorage.getItem("th_inv_ceil");
      if (f) setFloor(Number(f)); if (c) setCeil(Number(c));
    } catch {}
  }, []);
  function setFloorP(v) { setFloor(v); try { localStorage.setItem("th_inv_floor", String(v)); } catch {} }
  function setCeilP(v) { setCeil(v); try { localStorage.setItem("th_inv_ceil", String(v)); } catch {} }

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

  const load = useCallback(async () => {
    if (!accessKey || tab === "disc") return;
    setStatus("loading"); setErr("");
    try {
      const res = await jsonFetch(tab === "matched" ? "/invoices/matched" : "/invoices");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setList(d.invoices || []); setStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") { setErr(String(e.message || e)); setStatus("error"); } }
  }, [accessKey, jsonFetch, tab]);
  useEffect(() => { if (accessKey && tab !== "disc") load(); }, [accessKey, tab, load]);

  const loadDisc = useCallback(async () => {
    if (!accessKey) return;
    setDiscStatus("loading");
    try {
      const res = await jsonFetch("/invoices/discrepancies");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setDisc(d.invoices || []); setDiscStatus("ok");
    } catch (e) { if (String(e.message) !== "unauthorised") setDiscStatus("error"); }
  }, [accessKey, jsonFetch]);
  useEffect(() => { if (accessKey && tab === "disc") loadDisc(); }, [accessKey, tab, loadDisc]);

  // Search ALL invoices (any status) server-side so the box finds a matched/approved/discrepancy one
  // that isn't in the open tab. Debounced; cleared when the query is short or on the Discrepancies tab.
  useEffect(() => {
    const qq = query.trim();
    if (!accessKey || tab === "disc" || qq.length < 2) { setSearchResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await jsonFetch(`/invoices/search?q=${encodeURIComponent(qq)}`);
        if (!res.ok) return;
        const d = await res.json();
        setSearchResults(d.invoices || []);
      } catch (e) { if (String(e.message) !== "unauthorised") setSearchResults([]); }
    }, 350);
    return () => clearTimeout(t);
  }, [query, accessKey, tab, jsonFetch]);

  function discEmailText(iv) {
    // Friendly supplier query: opener, the specifics (the saved reason), the standard ask, our
    // closing. No internal tool name, no supplier name (it's going to them).
    const L = [];
    L.push("Hi,", "");
    L.push(`Hope you're well. We've been going through invoice ${iv.invoice_no}${iv.order_no ? ` (order ${iv.order_no})` : ""} and there's a discrepancy we wanted to flag:`, "");
    L.push(iv.reason ? iv.reason : "(see invoice)", "");
    L.push("Would you be able to put this right — either credit the invoice in full and reinvoice at the corrected amount, or send a credit note for the difference, whichever's easiest for you? We'll then get the invoice cleared together with its credit note.", "");
    L.push("Thanks so much,", "Trade Superstore Online", "Accounts");
    return L.join("\n");
  }
  async function copyDiscEmail(iv) {
    try {
      await navigator.clipboard.writeText(discEmailText(iv));
      setDiscCopied((s) => ({ ...s, [iv.sub_id]: true }));
      setTimeout(() => setDiscCopied((s) => ({ ...s, [iv.sub_id]: false })), 2000);
    } catch { window.prompt("Copy the query email:", discEmailText(iv)); }
  }

  // Draft supplier query emails for the given discrepancies — ONE Outlook draft per supplier
  // (grouped), in the Accounts mailbox, for review. Never auto-sent.
  async function chaseDiscrepancies(subIds) {
    const ids = [...subIds];
    if (!ids.length) return;
    const n = ids.length;
    if (!window.confirm(`Draft supplier query email${n === 1 ? "" : "s"} for ${n} discrepanc${n === 1 ? "y" : "ies"}? One draft per supplier is created in the Accounts mailbox for you to review and send — nothing is sent automatically.`)) return;
    setChasing(true); setChaseResult(null);
    try {
      const res = await jsonFetch("/invoices/chase-discrepancies", { method: "POST", body: JSON.stringify({ sub_ids: ids }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setChaseResult(d);
        const noEmail = (d.suppliers || []).filter((s) => s.no_email);
        setNotice({ kind: noEmail.length ? "warn" : "ok", text: `Drafted ${d.drafted} supplier email${d.drafted === 1 ? "" : "s"} in Accounts for review${noEmail.length ? ` — ${noEmail.length} supplier(s) had no email on file` : ""}.` });
        setDiscSel(new Set());
      } else setNotice({ kind: "warn", text: d.detail || "Couldn’t draft the chasers." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setChasing(false); }
  }

  // Approve a flagged invoice straight to QuickBooks from the Discrepancies tab (when the query turns
  // out fine). Creates the bill and clears it from the discrepancy queue. Credit notes are skipped
  // server-side (left for a vendor credit).
  async function doApproveDisc(iv) {
    const sub_id = iv.sub_id;
    if (!window.confirm(`Invoice ${iv.invoice_no} is flagged as a discrepancy. Approve it to QuickBooks anyway? This creates its bill and clears it from the discrepancy queue.`)) return;
    setApproving((a) => ({ ...a, [sub_id]: "working" }));
    try {
      const res = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
      const d = await res.json().catch(() => ({ ok: false, detail: `API ${res.status}` }));
      if (res.ok && d.ok) {
        setApproving((a) => ({ ...a, [sub_id]: "done" }));
        setNotice({ kind: "ok", text: `${iv.invoice_no}: ${d.detail || "approved to QuickBooks"}` });
        setTimeout(() => setDisc((l) => l.filter((x) => x.sub_id !== sub_id)), 1200);
      } else {
        setApproving((a) => ({ ...a, [sub_id]: "err" }));
        setNotice({ kind: "warn", text: `${iv.invoice_no}: ${d.detail || "couldn’t approve"}` });
      }
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
  }

  async function doUnflag(iv) {
    if (!window.confirm(`Move invoice ${iv.invoice_no} back to Needs Review? The discrepancy is treated as resolved.`)) return;
    setUnflagging((u) => ({ ...u, [iv.sub_id]: true }));
    try {
      const res = await jsonFetch(`/invoices/${iv.sub_id}/unflag`, { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setDisc((l) => l.filter((x) => x.sub_id !== iv.sub_id));
        setNotice({ kind: "ok", text: `${iv.invoice_no} moved back to Needs Review.` });
      } else setNotice({ kind: "warn", text: d.detail || "Couldn’t move it back." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setUnflagging((u) => ({ ...u, [iv.sub_id]: false })); }
  }

  const [issues, setIssues] = useState([]);
  const [showIssues, setShowIssues] = useState(false);
  const [suggest, setSuggest] = useState({});   // row index -> { loading, rows }
  async function doSuggest(i, r) {
    setSuggest((s) => ({ ...s, [i]: { loading: true } }));
    try {
      const res = await jsonFetch(`/invoices/suggest-order?total=${encodeURIComponent(r.total)}&supplier=${encodeURIComponent(r.supplier || "")}`);
      const d = await res.json().catch(() => ({ rows: [] }));
      setSuggest((s) => ({ ...s, [i]: { loading: false, rows: d.rows || [] } }));
    } catch (e) {
      if (String(e.message) !== "unauthorised") setSuggest((s) => ({ ...s, [i]: { loading: false, rows: [] } }));
    }
  }
  const [issueSel, setIssueSel] = useState(new Set());
  const [clearing, setClearing] = useState(false);
  const loadIssues = useCallback(() => {
    if (!accessKey) return;
    jsonFetch("/invoices/import-issues?limit=200").then((r) => r.ok && r.json())
      .then((d) => d && setIssues(d.rows || [])).catch(() => {});
  }, [accessKey, jsonFetch]);
  useEffect(() => { loadIssues(); }, [loadIssues]);
  function toggleIssue(id) { setIssueSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  function toggleAllIssues() { setIssueSel((s) => (s.size >= issues.length ? new Set() : new Set(issues.map((r) => r.id).filter(Boolean)))); }
  async function clearOnMonday() {
    if (!window.confirm("Check all of these against Monday and clear any whose invoice is already a subitem there?")) return;
    setClearing(true);
    try {
      const res = await jsonFetch(`/invoices/import-issues/clear-on-monday`, { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) { setNotice({ kind: "ok", text: `Checked ${d.checked}, cleared ${d.cleared} already on Monday.` }); loadIssues(); }
      else setNotice({ kind: "warn", text: d.detail || "Couldn’t sweep." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setClearing(false); }
  }
  async function clearIds(ids) {
    const list = (ids || []).filter(Boolean);
    if (!list.length) return;
    if (!window.confirm(`Clear ${list.length} failed import(s) off this list? They won't be retried.`)) return;
    setClearing(true);
    try {
      const res = await jsonFetch(`/invoices/import-issues/clear`, { method: "POST", body: JSON.stringify({ ids: list }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setNotice({ kind: "ok", text: `Cleared ${d.cleared}.` });
        setIssues((rows) => rows.filter((r) => !list.includes(r.id)));
        setIssueSel((s) => { const n = new Set(s); list.forEach((x) => n.delete(x)); return n; });
      } else setNotice({ kind: "warn", text: d.detail || "Couldn’t clear." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setClearing(false); }
  }

  function submitKey(e) {
    e.preventDefault();
    const k = keyInput.trim(); if (!k) return;
    try { localStorage.setItem(KEY_STORE, k); } catch {}
    setAccessKey(k); setNeedKey(false); setKeyInput("");
  }

  const doCheck = useCallback(async (sub_id) => {
    setChecking((c) => ({ ...c, [sub_id]: true }));
    setAccepted((a) => { const n = { ...a }; delete n[sub_id]; return n; });   // fresh check → clear accepts
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/check?lo=${floor}&hi=${ceil}`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const d = await res.json();
      setChecks((c) => ({ ...c, [sub_id]: d }));
      return d;
    } catch (e) {
      if (String(e.message) === "unauthorised") return null;
      const d = { ok: false, detail: String(e.message || e) };
      setChecks((c) => ({ ...c, [sub_id]: d }));
      return d;
    } finally { setChecking((c) => ({ ...c, [sub_id]: false })); }
  }, [jsonFetch, floor, ceil]);

  async function doApprove(iv, force = false) {
    const sub_id = iv.sub_id;
    const msg = force
      ? `⚠️ Invoice ${iv.invoice_no} is NOT fully matched (it has discrepancies). Push it to QuickBooks anyway? This creates its bill.`
      : `Approve invoice ${iv.invoice_no}? This creates its bill in QuickBooks.`;
    if (!window.confirm(msg)) return;
    setApproving((a) => ({ ...a, [sub_id]: "working" }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
      const d = await res.json().catch(() => ({ ok: false, detail: `API ${res.status}` }));
      if (res.ok && d.ok) {
        setApproving((a) => ({ ...a, [sub_id]: "done" }));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "ok", text: d.detail || "approved" } }));
        setNotice({ kind: "ok", text: `${iv.invoice_no}: ${d.detail}` });
        setTimeout(() => setList((l) => l.filter((x) => x.sub_id !== sub_id)), 1500);
      } else {
        setApproving((a) => ({ ...a, [sub_id]: "err" }));
        const text = d.detail || "couldn’t approve";
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text } }));
        setNotice({ kind: "warn", text: `${iv.invoice_no}: ${text}` });
      }
    } catch (e) {
      setApproving((a) => ({ ...a, [sub_id]: "err" }));
      if (String(e.message) !== "unauthorised") {
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
        setNotice({ kind: "warn", text: String(e.message || e) });
      }
    }
  }

  async function doFlag(iv) {
    const sub_id = iv.sub_id;
    const r = checks[sub_id];
    // Rich reason: the specific discrepancies + the resolution ask (credit & reinvoice, or credit
    // the difference). Falls back to the one-line reason if we don't have a full check result.
    const reason = (r && r.ok) ? discrepancyReason(iv, r) : ((r && r.discrepancy_reason) || "Discrepancy — see invoice");
    if (!window.confirm(`Flag invoice ${iv.invoice_no} as a Discrepancy on Monday? It moves out of Needs Review into the discrepancy queue, with the resolution ask (credit & reinvoice / credit the difference) saved as the note.`)) return;
    setApproving((a) => ({ ...a, [sub_id]: "working" }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/flag`, { method: "POST", body: JSON.stringify({ reason }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setApproving((a) => ({ ...a, [sub_id]: "flagged" }));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: "Flagged as Discrepancy on Monday." } }));
        setTimeout(() => setList((l) => l.filter((x) => x.sub_id !== sub_id)), 1200);
      } else {
        setApproving((a) => ({ ...a, [sub_id]: "err" }));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: d.detail || "Couldn’t flag." } }));
      }
    } catch (e) {
      setApproving((a) => ({ ...a, [sub_id]: "err" }));
      if (String(e.message) !== "unauthorised") setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
    }
  }

  // Email the supplier's accounts the discrepancy query AND mark it Discrepancy in one go — the
  // "email accounts" action Daniela wanted straight from the check screen. Sends from the Accounts
  // mailbox (falls back to a draft if direct send is blocked).
  async function doFlagEmail(iv) {
    const sub_id = iv.sub_id;
    const r = checks[sub_id];
    const reason = (r && r.ok) ? discrepancyReason(iv, r) : ((r && r.discrepancy_reason) || "Discrepancy — see invoice");
    if (!window.confirm(`Email ${iv.supplier || "the supplier"}'s accounts team the query for invoice ${iv.invoice_no} and mark it Discrepancy on Monday? The email is sent from the Accounts mailbox.`)) return;
    setApproving((a) => ({ ...a, [sub_id]: "working" }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/flag`, { method: "POST", body: JSON.stringify({ reason, email_accounts: true, supplier: iv.supplier, invoice_no: iv.invoice_no, order_no: iv.order_no }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setApproving((a) => ({ ...a, [sub_id]: "flagged" }));
        const txt = d.emailed ? `Emailed ${d.email} and flagged as Discrepancy.` : d.drafted ? `Couldn’t send directly — left a draft in Accounts for ${d.email}. Flagged as Discrepancy.` : (d.detail || "Flagged as Discrepancy.");
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: d.emailed ? "ok" : "warn", text: txt } }));
        setNotice({ kind: d.emailed ? "ok" : "warn", text: `${iv.invoice_no}: ${txt}` });
        setTimeout(() => setList((l) => l.filter((x) => x.sub_id !== sub_id)), 1500);
      } else {
        setApproving((a) => ({ ...a, [sub_id]: "err" }));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: d.detail || "Couldn’t email / flag." } }));
      }
    } catch (e) {
      setApproving((a) => ({ ...a, [sub_id]: "err" }));
      if (String(e.message) !== "unauthorised") setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
    }
  }

  async function doFindPdf(iv) {
    const sub_id = iv.sub_id;
    setFindingPdf((f) => ({ ...f, [sub_id]: true }));
    setApproveMsg((m) => ({ ...m, [sub_id]: null }));
    try {
      const res = await jsonFetch(`/invoices/${sub_id}/find-pdf`, { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no, supplier: iv.supplier || "" }) });
      const d = await res.json().catch(() => ({ ok: false, detail: `API ${res.status}` }));
      if (res.ok && d.ok && d.attached) {
        setList((l) => l.map((x) => x.sub_id === sub_id ? { ...x, has_pdf: true } : x));
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "ok", text: `PDF attached — ${d.detail}. You can Check it now.` } }));
        doCheck(sub_id);
      } else {
        setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: d.detail || "No PDF found in Outlook." } }));
      }
    } catch (e) {
      if (String(e.message) !== "unauthorised") setApproveMsg((m) => ({ ...m, [sub_id]: { kind: "warn", text: String(e.message || e) } }));
    } finally { setFindingPdf((f) => ({ ...f, [sub_id]: false })); }
  }

  function toggleSel(id) { setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; }); }
  function toggleAll() { setSel((s) => (s.size === list.length ? new Set() : new Set(list.map((x) => x.sub_id)))); }

  const [fixingMargins, setFixingMargins] = useState(false);
  async function fixMargins() {
    const ids = [...sel];
    if (!ids.length) return;
    if (!window.confirm(`Fix the order margin for ${ids.length} selected invoice(s)? This adds any invoice totals missing from the order on Monday (fixes a wrong 98%-type margin). It won't double-count.`)) return;
    setFixingMargins(true);
    try {
      const res = await jsonFetch("/invoices/fix-margins", { method: "POST", body: JSON.stringify({ sub_ids: ids }) });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        setNotice({ kind: "ok", text: d.filled ? `Fixed margins on ${d.orders} order(s) — added ${d.filled} missing total(s). Refreshing…` : `Checked ${d.orders} order(s) — margins already up to date.` });
        setSel(new Set());
        load();
      } else setNotice({ kind: "warn", text: d.detail || "Couldn’t fix margins." });
    } catch (e) { if (String(e.message) !== "unauthorised") setNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setFixingMargins(false); }
  }

  async function checkApproveSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    const results = [];
    setProc({ running: true, done: 0, total: ids.length, results: [] });
    for (const sub_id of ids) {
      const iv = list.find((x) => x.sub_id === sub_id);
      let text = "—", kind = "warn";
      if (iv) {
        try {
          const d = checks[sub_id] || await doCheck(sub_id);
          if (d && d.ok) {
            if (!d.matched) text = "discrepancy — left for review";
            else if (d.suggested_action === "push") {
              const ar = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
              const ad = await ar.json();
              if (ar.ok && ad.ok) { text = `approved — ${ad.detail}`; kind = "ok"; setApproving((a) => ({ ...a, [sub_id]: "done" })); }
              else text = `couldn’t approve: ${ad.detail || ""}`;
            } else text = `matches but ${d.suggested_action} — not auto-approved (margin)`;
          } else text = (d && d.detail) || "check failed";
        } catch (e) { if (String(e.message) === "unauthorised") break; text = "error"; }
      }
      results.push({ inv: iv ? iv.invoice_no : sub_id, text, kind });
      setProc({ running: true, done: results.length, total: ids.length, results: [...results] });
    }
    setProc((p) => ({ ...(p || {}), running: false }));
    setSel(new Set());
    const approved = results.filter((r) => r.kind === "ok").map((r) => r.inv);
    if (approved.length) setList((l) => l.filter((x) => !approved.includes(x.invoice_no)));
  }

  // Push the selected invoices straight to QuickBooks WITHOUT running the check — for ones she's
  // already happy with. Creates a QB bill for each via /recon/approve (never double-creates).
  async function pushSelected() {
    const ids = [...sel];
    if (!ids.length) return;
    if (!window.confirm(`Push ${ids.length} invoice(s) straight to QuickBooks without checking? This creates a bill in QuickBooks for each.`)) return;
    const results = [];
    setProc({ running: true, done: 0, total: ids.length, results: [] });
    for (const sub_id of ids) {
      const iv = list.find((x) => x.sub_id === sub_id);
      let text = "—", kind = "warn";
      if (iv) {
        setApproving((a) => ({ ...a, [sub_id]: "working" }));
        try {
          const ar = await jsonFetch("/recon/approve", { method: "POST", body: JSON.stringify({ invoice_no: iv.invoice_no }) });
          const ad = await ar.json();
          if (ar.ok && ad.ok) { text = `pushed — ${ad.detail}`; kind = "ok"; setApproving((a) => ({ ...a, [sub_id]: "done" })); }
          else { text = `couldn’t push: ${ad.detail || ""}`; setApproving((a) => ({ ...a, [sub_id]: "err" })); }
        } catch (e) { if (String(e.message) === "unauthorised") break; text = "error"; setApproving((a) => ({ ...a, [sub_id]: "err" })); }
      }
      results.push({ inv: iv ? iv.invoice_no : sub_id, text, kind });
      setProc({ running: true, done: results.length, total: ids.length, results: [...results] });
    }
    setProc((p) => ({ ...(p || {}), running: false }));
    setSel(new Set());
    const pushed = results.filter((r) => r.kind === "ok").map((r) => r.inv);
    if (pushed.length) setList((l) => l.filter((x) => !pushed.includes(x.invoice_no)));
  }

  if (needKey) {
    return (
      <div className="wrap">
        <div className="login">
          <img src="/tradehub-logo.png" alt="TradeHub" className="login-logo" /><div className="wordmark">Trade<b>Hub</b><span className="sec">Invoices</span></div>
          <p className="sub">Enter the shared access code to continue.</p>
          <form onSubmit={submitKey} className="loginform">
            <input className="input" type="password" value={keyInput} autoFocus onChange={(e) => setKeyInput(e.target.value)} placeholder="Access code" />
            <button className="btn primary" type="submit">Enter</button>
          </form>
        </div>
      </div>
    );
  }

  const suppliers = Array.from(new Set(list.map((i) => i.supplier).filter(Boolean))).sort((a, b) => a.localeCompare(b));
  // Discrepancies tab: narrow to one supplier when a filter is set (pills are clickable too).
  const discShown = discSupFilter ? disc.filter((d) => (d.supplier || "—") === discSupFilter) : disc;
  const shown = list.filter((iv) => {
    if (supFilter && (iv.supplier || "") !== supFilter) return false;
    if (onlyDup && !iv.possible_dup) return false;
    if (query) {
      const q = query.toLowerCase();
      if (!`${iv.invoice_no || ""} ${iv.supplier || ""} ${iv.order_no || ""}`.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  if (sortBy === "supplier") shown.sort((a, b) => (a.supplier || "").localeCompare(b.supplier || "") || (a.invoice_no || "").localeCompare(b.invoice_no || ""));
  else if (sortBy === "margin") shown.sort((a, b) => (a.margin == null ? 1e9 : a.margin) - (b.margin == null ? 1e9 : b.margin));
  else if (sortBy === "total") shown.sort((a, b) => (b.total || 0) - (a.total || 0));
  const allShownSelected = shown.length > 0 && shown.every((x) => sel.has(x.sub_id));
  function toggleAllShown() { setSel(allShownSelected ? new Set() : new Set(shown.map((x) => x.sub_id))); }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Invoice Checker</div>
        <div className="right">
          <div className="seg">
            <button className={`seg-btn ${tab === "review" ? "on" : ""}`} onClick={() => setTab("review")}>To review{tab === "review" && status === "ok" ? ` (${list.length})` : ""}</button>
            <button className={`seg-btn ${tab === "matched" ? "on" : ""}`} onClick={() => setTab("matched")}>Matched{tab === "matched" && status === "ok" ? ` (${list.length})` : ""}</button>
            <button className={`seg-btn ${tab === "disc" ? "on" : ""}`} onClick={() => setTab("disc")}>Discrepancies{discStatus === "ok" ? ` (${disc.length})` : ""}</button>
          </div>
          {tab !== "disc"
            ? <>
                <span className="count">{status === "ok" ? <><b>{shown.length}</b>{shown.length !== list.length ? ` / ${list.length}` : ""} {tab === "matched" ? "matched" : "to review"}</> : status === "loading" ? "Loading…" : ""}</span>
                <button className="btn primary" onClick={load} disabled={status === "loading"}>{status === "loading" ? "Refreshing…" : "Refresh"}</button>
              </>
            : <button className="btn primary" onClick={loadDisc} disabled={discStatus === "loading"}>{discStatus === "loading" ? "Refreshing…" : "Refresh"}</button>}
        </div>
      </div>

      {notice && tab === "disc" && <div className={`route-msg ${notice.kind}`} style={{ marginBottom: 8 }}>{notice.text}</div>}

      {tab === "disc" && (
        <>
          {discStatus === "error" && <div className="card"><div className="state err">Couldn’t load discrepancies.</div></div>}
          {discStatus === "ok" && disc.length === 0 && <div className="card"><div className="state">No invoices flagged as discrepancies. 🎉</div></div>}
          {discStatus === "ok" && disc.length > 0 && (() => {
            // Summary: total, by-supplier tally (click a supplier to filter), how many already
            // chased — plus bulk chase controls. Select all / Chase all act on the FILTERED set.
            const bySup = {};
            disc.forEach((iv) => { const s = iv.supplier || "—"; bySup[s] = (bySup[s] || 0) + 1; });
            const supList = Object.entries(bySup).sort((a, b) => b[1] - a[1]);
            const chased = discShown.filter((iv) => iv.sent).length;
            const allSel = discShown.length > 0 && discShown.every((iv) => discSel.has(iv.sub_id));
            const chaseAllLabel = discSupFilter ? `Chase all ${discSupFilter}` : "Chase all";
            return (
              <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
                <div className="inv-controls" style={{ flexWrap: "wrap" }}>
                  <span className="pill red">{discShown.length}{discSupFilter ? ` / ${disc.length}` : ""} discrepanc{discShown.length === 1 ? "y" : "ies"}</span>
                  {!discSupFilter && <span className="pill grey">{supList.length} supplier{supList.length === 1 ? "" : "s"}</span>}
                  {discSupFilter && <button className="btn ghost" onClick={() => { setDiscSupFilter(""); setDiscSel(new Set()); }}>✕ {discSupFilter}</button>}
                  {chased > 0 && <span className="pill amber">{chased} already chased</span>}
                  <select className="filter" value={discSupFilter} onChange={(e) => { setDiscSupFilter(e.target.value); setDiscSel(new Set()); }} title="Filter by supplier">
                    <option value="">All suppliers ({supList.length})</option>
                    {supList.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
                  </select>
                  <span style={{ flex: 1 }} />
                  <button className="btn" onClick={() => setDiscSel(allSel ? new Set() : new Set(discShown.map((x) => x.sub_id)))}>{allSel ? "Clear" : "Select all"}</button>
                  {discSel.size > 0 && <button className="btn primary" onClick={() => chaseDiscrepancies(discSel)} disabled={chasing}>{chasing ? "Drafting…" : `Chase selected (${discSel.size})`}</button>}
                  <button className="btn" onClick={() => chaseDiscrepancies(new Set(discShown.map((x) => x.sub_id)))} disabled={chasing} title="Draft one Outlook email per supplier for the discrepancies shown">{chasing ? "…" : chaseAllLabel}</button>
                </div>
                <div className="sub" style={{ marginTop: 8 }}>
                  {supList.map(([s, n]) => <span key={s} className={`pill ${discSupFilter === s ? "amber" : "grey"}`} onClick={() => { setDiscSupFilter(discSupFilter === s ? "" : s); setDiscSel(new Set()); }} style={{ marginRight: 6, marginBottom: 4, display: "inline-block", cursor: "pointer" }} title="Click to filter by this supplier">{s} · {n}</span>)}
                </div>
                {chaseResult && (
                  <div className="route-msg ok" style={{ marginTop: 10 }}>
                    <b>Drafted {chaseResult.drafted} email{chaseResult.drafted === 1 ? "" : "s"} in the Accounts mailbox</b> — open Outlook to review and send.
                    <div style={{ marginTop: 6 }}>
                      {(chaseResult.suppliers || []).map((r, i) => (
                        <div key={i} className="sub">{r.drafted ? "✓" : "⚠️"} {r.supplier} · {r.count} invoice{r.count === 1 ? "" : "s"} {r.no_email ? "— no email on file, draft not created" : `→ ${r.email}`}</div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
          {discStatus === "ok" && disc.length > 0 && discShown.length === 0 && <div className="card"><div className="state">No discrepancies for {discSupFilter}. <button className="btn ghost" onClick={() => setDiscSupFilter("")}>Show all</button></div></div>}
          <div className="inv-list">
            {discShown.map((iv) => (
              <div className={`card inv-card${discSel.has(iv.sub_id) ? " sel" : ""}`} key={iv.sub_id}>
                <div className="inv-head">
                  <label style={{ display: "flex", alignItems: "center", marginRight: 8 }} title="Select for bulk chase">
                    <input type="checkbox" checked={discSel.has(iv.sub_id)} onChange={() => toggleDiscSel(iv.sub_id)} />
                  </label>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span className="ono">{iv.invoice_no}</span>
                    <span className="sub"> · {iv.supplier || "—"} · order {iv.order_no || "—"} · {money(iv.total)}</span>
                    {iv.margin != null ? <span className={`pill ${iv.margin < 0 ? "red" : iv.margin < floor ? "amber" : "green"}`} style={{ marginLeft: 8 }} title={iv.margin < 0 ? "Losing money" : iv.margin < floor ? `Under the ${floor}% threshold` : "Healthy margin"}>margin {iv.margin}%</span> : null}
                    {iv.flagged_on ? <span className="sub" style={{ marginLeft: 8 }}>flagged {iv.flagged_on}</span> : null}
                  </div>
                  <div className="inv-right">
                    {iv.order_url && <a className="btn ghost" href={iv.order_url} target="_blank" rel="noreferrer">Order ↗</a>}
                    <button className="btn primary" onClick={() => doApproveDisc(iv)} disabled={approving[iv.sub_id] === "working"} title="Approve this invoice to QuickBooks (overrides the discrepancy)">{approving[iv.sub_id] === "working" ? "…" : "Approve → QB"}</button>
                    <button className="btn" onClick={() => chaseDiscrepancies(new Set([iv.sub_id]))} disabled={chasing} title="Draft an Outlook query email to this supplier for review">Chase</button>
                    <button className="btn" onClick={() => copyDiscEmail(iv)} title="Copy a query email to the supplier">{discCopied[iv.sub_id] ? "Copied ✓" : "Copy query email"}</button>
                    <button className="btn" onClick={() => doUnflag(iv)} disabled={unflagging[iv.sub_id]} title="Move back to Needs Review">{unflagging[iv.sub_id] ? "…" : "Move back to review"}</button>
                  </div>
                </div>
                {(iv.reason || iv.sent) ? (
                  <div className="inv-body">
                    {iv.reason ? (
                      <div className="warn-note col">
                        <div className="warn-head"><IconWarn /> Why it was queried</div>
                        <div className="sub" style={{ whiteSpace: "pre-wrap" }}>{iv.reason}</div>
                      </div>
                    ) : null}
                    {iv.sent ? <div className="sub" style={{ marginTop: iv.reason ? 6 : 0 }}>Chaser sent: {iv.sent}</div> : null}
                  </div>
                ) : (
                  <div className="inv-body">
                    <div className="sub">Flagged as a discrepancy on Monday, but no reason was saved against it (flagged by hand or before reasons were recorded). Open the order to review, or move it back to the checker.</div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {(tab === "review" || tab === "matched") && (<>

      {tab === "review" && <ImportPanel jsonFetch={jsonFetch} onNotice={setNotice} />}

      {tab === "matched" && (
        <div className="route-msg ok" style={{ marginBottom: 8 }}>
          These invoices were auto-matched by TradeHub (invoice ✓ order ✓ price). Review and <b>Approve → QB</b> to post them to QuickBooks, or flag any that don’t look right.
        </div>
      )}

      <div className="card" style={{ padding: "8px 12px", marginBottom: 8 }}>
        <div className="inv-controls">
          <input className="search" style={{ maxWidth: 240, flex: "none" }} placeholder="Search invoice / order / supplier" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select className="filter" value={supFilter} onChange={(e) => setSupFilter(e.target.value)}>
            <option value="">All suppliers ({suppliers.length})</option>
            {suppliers.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="filter" value={sortBy} onChange={(e) => setSortBy(e.target.value)} title="Sort">
            <option value="">Sort: default</option>
            <option value="margin">Lowest margin first</option>
            <option value="supplier">Supplier</option>
            <option value="total">Highest total first</option>
          </select>
          <label className="inv-set" style={{ cursor: "pointer" }} title="Only possible duplicates"><input type="checkbox" checked={onlyDup} onChange={(e) => setOnlyDup(e.target.checked)} /><span className="sub">dups</span></label>
          {(supFilter || query || sortBy || onlyDup) && <button className="btn ghost" onClick={() => { setSupFilter(""); setQuery(""); setSortBy(""); setOnlyDup(false); }}>Clear</button>}
          <span style={{ flex: 1 }} />
          <span className="inv-set"><span className="sub">Approve</span><input type="number" className="numin" value={floor} onChange={(e) => setFloorP(Number(e.target.value))} title="Auto-approve floor margin %" /><span className="sub">–</span><input type="number" className="numin" value={ceil} onChange={(e) => setCeilP(Number(e.target.value))} title="Flag-above margin %" /><span className="sub">%</span></span>
          {shown.length > 0 && <button className="btn" onClick={toggleAllShown}>{allShownSelected ? "Clear" : "Select all"}</button>}
          {sel.size > 0 && <button className="btn" onClick={fixMargins} disabled={fixingMargins} title="Add any invoice totals missing from the order on Monday so the margin is right">{fixingMargins ? "Fixing…" : `Fix margins (${sel.size})`}</button>}
          {sel.size > 0 && <button className="btn primary" onClick={checkApproveSelected} disabled={proc?.running}>{proc?.running ? `Working ${proc.done}/${proc.total}…` : `Check & approve (${sel.size})`}</button>}
          {sel.size > 0 && <button className="btn" onClick={pushSelected} disabled={proc?.running} title="Create the QB bill for each selected invoice without running the check">{proc?.running ? "…" : `Push to QB (${sel.size})`}</button>}
        </div>
        {notice && <div className={`route-msg ${notice.kind}`} style={{ marginTop: 8 }}>{notice.text}</div>}
      </div>

      {query.trim().length >= 2 && (() => {
        // Invoices matching the search that AREN'T in the current tab — found across all statuses.
        const haveIds = new Set(shown.map((x) => String(x.sub_id)));
        const extra = (searchResults || []).filter((r) => !haveIds.has(String(r.sub_id)));
        if (!extra.length) return null;
        return (
          <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
            <div className="sub" style={{ marginBottom: 8 }}>Also found matching <b>“{query.trim()}”</b> (any status, not in this tab):</div>
            <table className="mini">
              <thead><tr><th>Invoice</th><th>Supplier</th><th>Order</th><th className="num">Total</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {extra.map((r) => (
                  <tr key={r.sub_id}>
                    <td className="ono">{r.invoice_no}</td>
                    <td className="sub">{r.supplier || "—"}</td>
                    <td className="sub">{r.order_no || "—"}</td>
                    <td className="num">{r.total != null ? money(r.total) : "—"}</td>
                    <td><span className="pill grey">{r.status || "—"}</span></td>
                    <td style={{ whiteSpace: "nowrap" }}>{r.order_url && <a className="btn ghost" href={r.order_url} target="_blank" rel="noreferrer">Order ↗</a>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}

      {issues.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <div className="inv-controls">
            <span className="pill red">{issues.length} didn’t import</span>
            <span className="sub">invoices in Outlook that never became a Monday subitem (mostly no matching order)</span>
            <span style={{ flex: 1 }} />
            <button className="btn ghost" onClick={clearOnMonday} disabled={clearing}>{clearing ? "…" : "Clear ones already on Monday"}</button>
            {showIssues && issues.length > 0 && <button className="btn" onClick={toggleAllIssues}>{issueSel.size >= issues.length ? "Clear all" : "Select all"}</button>}
            {issueSel.size > 0 && <button className="btn" onClick={() => clearIds([...issueSel])} disabled={clearing}>{clearing ? "…" : `Clear selected (${issueSel.size})`}</button>}
            <button className="btn" onClick={() => setShowIssues((s) => !s)}>{showIssues ? "Hide" : "Show"}</button>
          </div>
          {showIssues && (
            <table className="mini" style={{ marginTop: 8 }}>
              <thead><tr><th></th><th>Invoice</th><th>Supplier</th><th>Order/PO</th><th className="num">Total</th><th>Invoice date</th><th>Why it didn’t import</th><th></th></tr></thead>
              <tbody>
                {issues.map((r, i) => {
                  const sg = suggest[i];
                  return (
                  <Fragment key={i}>
                  <tr className={issueSel.has(r.id) ? "od" : ""}>
                    <td><input type="checkbox" checked={issueSel.has(r.id)} onChange={() => toggleIssue(r.id)} /></td>
                    <td className="ono">{r.invoice_no || "—"}</td>
                    <td className="sub">{r.supplier || "—"}</td>
                    <td className="sub">{r.order_no || "—"}</td>
                    <td className="num">{r.total != null ? money(r.total) : "—"}</td>
                    <td className="sub">{r.inv_date || "—"}</td>
                    <td className="sub">{r.detail || "—"}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.total != null && <button className="btn ghost" onClick={() => doSuggest(i, r)} disabled={sg?.loading}>{sg?.loading ? "…" : "Suggest"}</button>}
                      {" "}<button className="btn ghost" onClick={() => clearIds([r.id])} disabled={clearing}>Clear</button>
                    </td>
                  </tr>
                  {sg && !sg.loading && (
                    <tr><td colSpan={8} className="sub" style={{ paddingLeft: 18 }}>
                      {sg.rows?.length
                        ? <>Possible match{sg.rows.length > 1 ? "es" : ""}: {sg.rows.map((o, j) => (
                            <span key={j} className="pill grey" style={{ marginRight: 6 }}>
                              order {o.order_no} · {o.matched_on === "cost" ? "cost" : "value"} {money(o.matched_on === "cost" ? o.cost : o.value)}{o.supplier_match ? " · supplier ✓" : (o.supplier ? ` · ${o.supplier}` : "")}
                            </span>))} — assign on Monday, then it imports on the next run.</>
                        : "No live order matched this amount — the order may not be on the board yet."}
                    </td></tr>
                  )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {proc && (
        <div className="proc-panel">
          <div className="proc-head">{proc.running ? <><span className="spinner" />Working {proc.done} of {proc.total}…</> : <>Done {proc.results.length}. <button className="linkish" onClick={() => setProc(null)}>dismiss</button></>}</div>
          {proc.total > 0 && <div className="proc-bar"><span style={{ width: `${Math.round((proc.done / proc.total) * 100)}%` }} /></div>}
          <div className="proc-results">{proc.results.map((x, i) => <div key={i} className={`proc-row ${x.kind}`}><b>{x.inv}</b> {x.text}</div>)}</div>
        </div>
      )}

      {status === "error" && <div className="card"><div className="state err">Couldn’t load invoices ({err}).</div></div>}
      {status === "ok" && list.length === 0 && <div className="card"><div className="state">{tab === "matched" ? "No auto-matched invoices waiting. 🎉" : "No invoices in Needs Review. 🎉"}</div></div>}
      {status === "ok" && list.length > 0 && shown.length === 0 && <div className="card"><div className="state">No invoices match this filter.</div></div>}

      <div className="inv-list">
        {shown.map((iv) => {
          const r = checks[iv.sub_id];
          const busy = checking[iv.sub_id];
          const al = r && r.ok ? actionLabel(r.suggested_action, r.matched) : null;
          // Per-line accept: group each problem LINE (and each missing item) so one "accept" clears it.
          const probLines = [];
          if (r && r.ok) {
            (r.lines || []).forEach((l, i) => {
              const iss = (l.issues || []).filter((x) => x[0] !== "name");
              if (iss.length) probLines.push({ key: `L${i}`, idx: i, sku: l.sku || l.desc || "line", msgs: iss.map((x) => x[1]) });
            });
            (r.missing || []).forEach((m) => probLines.push({ key: `M${m}`, sku: null, msgs: [`On the order but not invoiced: ${m}`] }));
          }
          const accSet = accepted[iv.sub_id];
          const isAcc = (k) => !!(accSet && accSet.has(k));
          const blocking = probLines.filter((p) => !isAcc(p.key));
          const effMatched = !!(r && r.ok && (r.matched || (probLines.length > 0 && blocking.length === 0)));
          return (
            <div className="card inv-card" key={iv.sub_id}>
              <div className="inv-head">
                <label className="inv-chk"><input type="checkbox" checked={sel.has(iv.sub_id)} onChange={() => toggleSel(iv.sub_id)} /></label>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span className="ono">{iv.invoice_no}</span>
                  <span className="sub"> · {iv.supplier || "—"} · order {iv.order_no || "—"} · {money(iv.total)}</span>
                  {iv.possible_dup ? <span className="pill red" style={{ marginLeft: 8 }}>possible duplicate of {iv.possible_dup}</span> : null}
                  {iv.margin != null ? <span className={`pill ${iv.margin < 0 ? "red" : iv.margin < floor ? "amber" : "green"}`} style={{ marginLeft: 8 }} title={iv.margin < 0 ? "Losing money" : iv.margin < floor ? `Under the ${floor}% threshold` : "Healthy margin"}>margin {iv.margin}%</span> : null}
                </div>
                <div className="inv-right">
                  {al && <span className={`pill ${al.cls}`}>{al.text}</span>}
                  <button className={`btn ghost ${orderOpen.has(iv.sub_id) ? "on" : ""}`} onClick={() => toggleOrder(iv.sub_id)} title="See & edit this order on Monday">Monday {orderOpen.has(iv.sub_id) ? "▾" : "▸"}</button>
                  {iv.order_url && <a className="btn ghost" href={iv.order_url} target="_blank" rel="noreferrer" title="Open this order in Shopify">Shopify ↗</a>}
                  {!iv.has_pdf && <button className="btn" onClick={() => doFindPdf(iv)} disabled={findingPdf[iv.sub_id]}>{findingPdf[iv.sub_id] ? "Searching…" : "Find PDF in Outlook"}</button>}
                  <button className="btn" onClick={() => doCheck(iv.sub_id)} disabled={busy} title={!iv.has_pdf ? "No PDF — for no-pricelist suppliers this checks on the order margin alone" : "Check this invoice"}>{busy ? "Checking…" : r ? "Re-check" : "Check"}</button>
                  {!r && approving[iv.sub_id] === "done" && <span className="pill green">pushed ✓</span>}
                  {!r && approving[iv.sub_id] !== "done" && <button className="btn primary" onClick={() => doApprove(iv)} disabled={approving[iv.sub_id] === "working"} title="Create the QB bill now without running the check">{approving[iv.sub_id] === "working" ? "…" : "Push to QB"}</button>}
                  {r && r.ok && approving[iv.sub_id] === "done" && <span className="pill green">approved ✓</span>}
                  {r && r.ok && approving[iv.sub_id] === "flagged" && <span className="pill red">flagged</span>}
                  {r && r.ok && approving[iv.sub_id] !== "done" && approving[iv.sub_id] !== "flagged" && (
                    <>
                      {(r.matched || effMatched)
                        ? <button className="btn primary" onClick={() => doApprove(iv)} disabled={approving[iv.sub_id] === "working"} title={effMatched && !r.matched ? "All remaining issues accepted — approve to QuickBooks" : "Approve to QuickBooks"}>{approving[iv.sub_id] === "working" ? "…" : (effMatched && !r.matched ? "Approve → QB (accepted)" : "Approve → QB")}</button>
                        : <button className="btn" onClick={() => doApprove(iv, true)} disabled={approving[iv.sub_id] === "working"} title="Push to QuickBooks even though it isn't fully matched">{approving[iv.sub_id] === "working" ? "…" : "Push to QB anyway"}</button>}
                      <button className="btn" onClick={() => doFlag(iv)} disabled={approving[iv.sub_id] === "working"} title="Flag as a discrepancy on Monday (no email)">Flag</button>
                      <button className="btn primary" onClick={() => doFlagEmail(iv)} disabled={approving[iv.sub_id] === "working"} title="Email the supplier's accounts the query and mark it Discrepancy">Email accounts &amp; flag</button>
                    </>
                  )}
                </div>
              </div>

              {orderOpen.has(iv.sub_id) && <OrderPanel sub_id={iv.sub_id} orderItemId={iv.order_item_id} jsonFetch={jsonFetch} onNotice={setNotice} />}
              {approveMsg[iv.sub_id] && <div className={`route-msg ${approveMsg[iv.sub_id].kind}`} style={{ margin: "0 14px 12px" }}>{approveMsg[iv.sub_id].text}</div>}
              {r && !r.ok && <div className="route-msg warn" style={{ margin: "0 14px 12px" }}>{r.detail || "Couldn’t check this invoice."}</div>}
              {r && r.ok && (
                <div className="inv-body">
                  {probLines.length ? (
                    <div className="warn-note col" style={{ marginBottom: 8 }}>
                      <div className="warn-head"><IconWarn /> What doesn’t match ({blocking.length}{blocking.length !== probLines.length ? ` of ${probLines.length}` : ""})</div>
                      <ul className="disc-list">
                        {probLines.map((p) => (
                          <li key={p.key} className={isAcc(p.key) ? "accepted-line" : ""}>
                            {p.sku ? <><b>{p.sku}</b> — </> : null}{p.msgs.join(" · ")}
                            <button className="linkish accept-btn" onClick={() => toggleAccept(iv.sub_id, p.key)}>{isAcc(p.key) ? "undo" : "accept"}</button>
                          </li>
                        ))}
                      </ul>
                      {blocking.length === 0 ? <div className="sub accepted-ok">All issues accepted — you can Approve → QB.</div> : <div className="sub">Accept a line to say the charge is fine (margin’s healthy) — once all are accepted you can approve it cleanly.</div>}
                    </div>
                  ) : null}
                  {r.no_pdf ? (
                    <div className="sub" style={{ marginTop: 2 }}>No PDF attached — checked on the <b>order margin only</b> (no pricelist held for {r.supplier}). {r.margin != null ? <>Margin <b>{r.margin}%</b> — </> : null}{r.suggested_action === "push" ? "clear to Approve → QB." : r.suggested_action === "hold" ? "below the 10% threshold, so held for review." : "review before approving."}</div>
                  ) : (
                    <>
                      <table className="mini">
                        <thead><tr><th>SKU</th><th>Description</th><th className="num">Qty</th><th className="num">Unit</th><th>Check</th></tr></thead>
                        <tbody>
                          {(r.lines || []).map((l, i) => {
                            const probs = (l.issues || []).filter((x) => x[0] !== "name");
                            const notes = (l.issues || []).map((x) => x[1]);
                            return (
                              <tr key={i}>
                                <td className="sub">{l.sku || "—"}</td>
                                <td>{l.desc || "—"}{notes.length ? <div className={`sub ${probs.length ? "mred" : ""}`}>{notes.join(" · ")}</div> : null}</td>
                                <td className="num">{l.qty ?? "—"}</td>
                                <td className="num">{l.unit != null ? money(l.unit) : "—"}</td>
                                <td>{probs.length ? (isAcc(`L${i}`) ? <span className="pill grey">accepted</span> : <span className="pill red">issue</span>) : <span className="pill green">ok</span>}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      <div className="sub" style={{ marginTop: 6 }}>{r.matched ? "All lines match the order & pricelist — use Approve → QB to push the bill to QuickBooks." : `${r.n_issues} issue(s) found — resolve & re-check, or “Push to QB anyway” if you’re happy to approve it.`}</div>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      </>)}
    </div>
  );
}

function OrderPanel({ sub_id, orderItemId, jsonFetch, onNotice }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [inv, setInv] = useState([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await jsonFetch(`/invoices/${sub_id}/order${orderItemId ? `?order_item_id=${encodeURIComponent(orderItemId)}` : ""}`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      const d = await r.json();
      setData(d);
      setInv(d.order.inv.map((x) => ({ ...x, edit: x.value == null ? "" : String(x.value) })));
      const cur = (d.invoices || []).find((s) => s.is_current);
      setNote(cur ? cur.note : "");
    } catch (e) { if (String(e.message) !== "unauthorised") setErr(String(e.message || e)); }
    finally { setLoading(false); }
  }, [sub_id, orderItemId, jsonFetch]);
  useEffect(() => { load(); }, [load]);

  const orig = (row) => (row.value == null ? "" : String(row.value));
  const dirty = inv.some((row) => row.edit !== orig(row));
  async function saveSlots() {
    const changed = inv.filter((row) => row.edit !== orig(row));
    if (!changed.length) return;
    setSaving("slots");
    try {
      for (const row of changed) {
        const val = row.edit === "" ? null : Number(row.edit);
        const r = await jsonFetch("/invoices/order-set", { method: "POST", body: JSON.stringify({ order_item_id: data.order.order_item_id, col: row.col, value: val }) });
        const dd = await r.json().catch(() => ({}));
        if (!r.ok || !dd.ok) { onNotice({ kind: "warn", text: `${row.label}: ${dd.detail || "couldn’t save"}` }); return; }
      }
      onNotice({ kind: "ok", text: `Saved ${changed.length} slot${changed.length > 1 ? "s" : ""} on Monday.` });
      load();
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setSaving(""); }
  }
  async function saveNote() {
    setSaving("note");
    try {
      const r = await jsonFetch(`/invoices/${sub_id}/note`, { method: "POST", body: JSON.stringify({ note }) });
      const dd = await r.json().catch(() => ({}));
      if (r.ok && dd.ok) onNotice({ kind: "ok", text: "Note saved on Monday." });
      else onNotice({ kind: "warn", text: dd.detail || "Couldn’t save the note." });
    } catch (e) { if (String(e.message) !== "unauthorised") onNotice({ kind: "warn", text: String(e.message || e) }); }
    finally { setSaving(""); }
  }

  if (loading) return <div className="inv-body"><div className="state"><span className="spinner" />Reading the order from Monday…</div></div>;
  if (err) return <div className="inv-body"><div className="route-msg warn" style={{ margin: "0 14px 12px" }}>{err}</div></div>;
  if (!data) return null;
  const o = data.order;
  const sibs = data.invoices || [];
  const isCN = (s) => (typeof s.total === "number" && s.total < 0) || /credit|^\s*c?n\b|scn/i.test(s.status || "") || /^(cn|scn|crn)/i.test(s.name || "");
  const net = sibs.reduce((a, x) => a + (typeof x.total === "number" ? x.total : 0), 0);
  const anyCredit = sibs.some(isCN);

  // Alarm: each invoice total should fill exactly ONE INV slot. Compare the multiset of filled slot
  // values against the multiset of invoice totals — a value in more slots than invoices is a
  // double-count; a value on more invoices than slots is a missing total (margin reads too high).
  const round2 = (n) => Math.round(n * 100) / 100;
  const slotVals = inv.map((x) => x.value).filter((v) => typeof v === "number").map(round2);
  const invVals = sibs.map((s) => s.total).filter((v) => typeof v === "number").map(round2);
  const ms = {}, mi = {};
  slotVals.forEach((v) => { const k = v.toFixed(2); ms[k] = (ms[k] || 0) + 1; });
  invVals.forEach((v) => { const k = v.toFixed(2); mi[k] = (mi[k] || 0) + 1; });
  const alarms = [];
  Object.keys(ms).forEach((k) => { if (ms[k] > (mi[k] || 0)) alarms.push(`£${k} is in ${ms[k]} invoice slots but only ${mi[k] || 0} invoice${(mi[k] || 0) === 1 ? "" : "s"} has that total — it's likely been entered more than once, which double-counts the order.`); });
  Object.keys(mi).forEach((k) => { if (mi[k] > (ms[k] || 0)) alarms.push(`£${k} is on ${mi[k]} invoice${mi[k] === 1 ? "" : "s"} but only ${ms[k] || 0} slot${(ms[k] || 0) === 1 ? "" : "s"} — a total is missing from the order, so the margin will read too high.`); });
  if (!alarms.length && slotVals.length !== invVals.length) alarms.push(`${slotVals.length} invoice slot(s) filled but ${invVals.length} invoice(s) on the order — each invoice total should fill exactly one slot.`);

  return (
    <div className="inv-body order-panel">
      {alarms.length ? (
        <div className="op-alarm">
          <div className="op-alarm-head">⚠ Invoice slots don’t match the invoices</div>
          <ul>{alarms.map((a, i) => <li key={i}>{a}</li>)}</ul>
          <div className="sub">Fix the INV slots below so each invoice total sits in one slot, then the order margin is right.</div>
        </div>
      ) : null}
      <div className="op-card">
        <div className="op-head">
          <b>Order {o.order_no || o.name}</b>
          {o.stage ? <span className="pill grey">{o.stage}</span> : null}
        </div>
        <div className="sub op-sub">{o.customer || "—"} · {o.supplier || "—"}{o.payment_status ? ` · ${o.payment_status}` : ""}</div>
        <div className="op-stats">
          <div className="op-stat"><span>£ to us</span><b>{money(o.sell_n)}</b></div>
          <div className="op-stat"><span>£ to supplier</span><b>{money(o.cost_n)}</b></div>
          <div className="op-stat"><span>Margin</span><b>{o.margin || "—"}</b></div>
          <div className="op-stat"><span>Invoiced so far</span><b>{o.invoiced_total != null ? money(o.invoiced_total) : "—"}</b></div>
        </div>
      </div>

      <div className="op-card">
        <div className="op-card-head"><span>Invoice slots</span>{dirty ? <button className="btn primary sm" onClick={saveSlots} disabled={saving === "slots"}>{saving === "slots" ? "Saving…" : "Save changes"}</button> : null}</div>
        <div className="op-inv-grid">
          {inv.map((row, i) => (
            <label className={`op-inv-cell${row.value != null ? " filled" : ""}${row.edit !== orig(row) ? " dirty" : ""}`} key={row.col}>
              <span>{row.label}</span>
              <input className="op-inv-in" type="number" inputMode="decimal" value={row.edit} placeholder="—" onChange={(e) => setInv((xs) => xs.map((x, j) => (j === i ? { ...x, edit: e.target.value } : x)))} />
            </label>
          ))}
        </div>
        <div className="sub op-hint">Type a figure in a slot and hit <b>Save changes</b> — it writes straight to Monday.</div>
      </div>

      <div className="op-card">
        <div className="op-card-head"><span>Invoices &amp; credits on this order ({sibs.length})</span></div>
        <table className="mini op-sibs">
          <thead><tr><th>Invoice</th><th className="num">Total</th><th>Status</th><th>Date</th></tr></thead>
          <tbody>
            {sibs.map((s, i) => (
              <tr key={i} className={`${s.is_current ? "od " : ""}${isCN(s) ? "cn" : ""}`}>
                <td className="ono">{s.name}{isCN(s) ? <span className="pill red" style={{ marginLeft: 6 }}>credit</span> : null}{s.is_current ? <span className="sub"> · this one</span> : null}</td>
                <td className="num">{s.total != null ? money(s.total) : "—"}</td>
                <td className="sub">{s.status || "—"}</td>
                <td className="sub">{s.date || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="sub op-net">
          Net of all invoices &amp; credits: <b>{money(net)}</b>
          {o.cost_n != null ? <> · order cost <b>{money(o.cost_n)}</b></> : null}
          {o.cost_n != null && Math.abs(net - o.cost_n) > 0.01 ? <span className="mamber"> · differs by {money(Math.abs(net - o.cost_n))}</span> : null}
          {anyCredit ? <div style={{ marginTop: 2 }}>Looks like a credit / reinvoice — check the net above matches the corrected order cost before approving.</div> : null}
        </div>
        {o.order_items ? <details className="op-items"><summary className="sub">Order items</summary><div className="sub" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{o.order_items}</div></details> : null}
      </div>

      <div className="op-card">
        <div className="op-card-head"><span>Note</span><button className="btn sm" onClick={saveNote} disabled={saving === "note"}>{saving === "note" ? "Saving…" : "Save note"}</button></div>
        <textarea className="op-note-ta" value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Why this invoice is stuck, what you've checked, what's needed…" />
      </div>
    </div>
  );
}

const IconWarn = (p) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>
);
