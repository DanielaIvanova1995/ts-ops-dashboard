"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import BrandMarkIcon from "./BrandMarkIcon";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = "th_access_key";   // holds the shared code (legacy) OR the login token (per-user mode)
const USER = "th_user";        // cached signed-in user, for nav/home filtering

const Ico = {
  home: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" /><path d="M9.5 21v-6h5v6" /></svg>),
  orders: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 7v10l9 4 9-4V7" /><path d="M12 11v10" /></svg>),
  statements: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" /><path d="M14 2v5h5" /><path d="M8 13h8M8 17h5" /></svg>),
  invoices: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1z" /><path d="M8 7h8M8 11h8M8 15h5" /></svg>),
  triage: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></svg>),
  pricing: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M20 12V7a1 1 0 0 0-1-1h-5L3 17l4 4L18 10" /><path d="M7.5 7.5h.01" /></svg>),
  quotes: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M9 13h6M9 17h6M9 9h2" /></svg>),
  payments: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M2 10h20" /><path d="M6 15h4" /></svg>),
  assistant: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>),
  users: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>),
  aftersales: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M9 14l-4 4a2 2 0 0 0 3 3l4-4" /><path d="M14.5 9.5 20 4" /><path d="M3 4l5 5" /><path d="M14 10a4 4 0 0 1 5-5l-2.5 2.5L18 9l1.5 1.5L22 8a4 4 0 0 1-5 5z" /></svg>),
  dot: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" {...p}><circle cx="12" cy="12" r="3" /></svg>),
  logout: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></svg>),
};

// `module` = the access key the signed-in user must hold (null = always visible).
const NAV = [
  { href: "/", label: "Home", icon: "home", module: null },
  { href: "/orders", label: "Orders", icon: "orders", module: "orders" },
  { href: "/recon", label: "Statements", icon: "statements", module: "recon" },
  { href: "/payments", label: "Payments", icon: "payments", module: "payments" },
  { href: "/invoices", label: "Invoices", icon: "invoices", module: "invoices" },
  { href: "/triage", label: "Triage", icon: "triage", module: "triage" },
  { href: "/pricing", label: "Pricing", icon: "pricing", module: "pricing" },
  { href: "/quotes", label: "Quotes", icon: "quotes", module: "quotes" },
  { href: "/assistant", label: "My Assistant", icon: "assistant", module: "assistant" },
  { href: "/aftersales", label: "Aftersales", icon: "aftersales", module: null },
];
const SOON = [];

export default function AppShell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [ready, setReady] = useState(false);
  const path = usePathname();

  // Auth gate. mode: loading | legacy (shared code) | login | bootstrap | app
  const [mode, setMode] = useState("loading");
  const [user, setUser] = useState(null);
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [bootName, setBootName] = useState("");
  const [bootCode, setBootCode] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try { setCollapsed(localStorage.getItem("th_nav_collapsed") === "1"); } catch {}
    setReady(true);
    (async () => {
      let st;
      try { st = await (await fetch(`${API}/auth/status`, { cache: "no-store" })).json(); }
      catch { setMode("legacy"); return; }          // API unreachable → don't brick; shared-code prompt
      if (!st || !st.enabled) { setMode("legacy"); return; }
      let tok = null;
      try { tok = localStorage.getItem(KEY); } catch {}
      if (tok) {
        try {
          const r = await fetch(`${API}/auth/me`, { cache: "no-store", headers: { Authorization: "Bearer " + tok } });
          if (r.ok) {
            const d = await r.json();
            setUser(d.user); try { localStorage.setItem(USER, JSON.stringify(d.user)); } catch {}
            setMode("app"); return;
          }
        } catch {}
      }
      setMode(st.has_users ? "login" : "bootstrap");
    })();
  }, []);

  function toggle() {
    setCollapsed((c) => {
      const n = !c;
      try { localStorage.setItem("th_nav_collapsed", n ? "1" : "0"); } catch {}
      return n;
    });
  }

  // Clear the session (or shared code) + section passcodes, then reload.
  function logout() {
    try { [KEY, USER, "th_statements_pin", "th_assistant_pin"].forEach((k) => localStorage.removeItem(k)); } catch {}
    window.location.href = "/";
  }

  async function doLogin(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const r = await fetch(`${API}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim(), password: pw }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) {
        try { localStorage.setItem(KEY, d.token); localStorage.setItem(USER, JSON.stringify(d.user)); } catch {}
        setUser(d.user); setPw(""); setMode("app");
      } else setErr(d.detail || "Wrong email or password.");
    } catch { setErr("Couldn't reach the server — try again."); }
    finally { setBusy(false); }
  }

  async function doBootstrap(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const r = await fetch(`${API}/auth/bootstrap`, { method: "POST", headers: { "Content-Type": "application/json", "X-TradeHub-Key": bootCode.trim() }, body: JSON.stringify({ email: email.trim(), name: bootName.trim(), password: pw }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) {
        try { localStorage.setItem(KEY, d.token); localStorage.setItem(USER, JSON.stringify(d.user)); } catch {}
        setUser(d.user); setPw(""); setMode("app");
      } else setErr(d.detail || "Couldn't create the admin account.");
    } catch { setErr("Couldn't reach the server — try again."); }
    finally { setBusy(false); }
  }

  if (mode === "loading") {
    return <div className="wrap" style={{ display: "flex", justifyContent: "center", paddingTop: 80 }}><span className="sub">Loading…</span></div>;
  }

  if (mode === "login" || mode === "bootstrap") {
    const boot = mode === "bootstrap";
    return (
      <div className="wrap">
        <div className="login">
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 10 }}><BrandMarkIcon size={44} /></div>
          <div className="wordmark">Trade<b>Hub</b></div>
          <p className="sub">{boot ? "Create the first admin account to switch on logins." : "Sign in to continue."}</p>
          <form onSubmit={boot ? doBootstrap : doLogin} className="loginform stack">
            {boot && <input className="input" type="password" value={bootCode} autoFocus placeholder="Current shared access code" onChange={(e) => setBootCode(e.target.value)} />}
            {boot && <input className="input" type="text" value={bootName} placeholder="Your name" onChange={(e) => setBootName(e.target.value)} />}
            <input className="input" type="email" value={email} autoFocus={!boot} placeholder="Work email" onChange={(e) => setEmail(e.target.value)} />
            <input className="input" type="password" value={pw} placeholder={boot ? "Choose a password" : "Password"} onChange={(e) => setPw(e.target.value)} />
            <button className="btn primary" type="submit" disabled={busy}>{busy ? (boot ? "Creating…" : "Signing in…") : (boot ? "Create admin & sign in" : "Sign in")}</button>
            {err && <div className="sub" style={{ color: "#c0392b" }}>{err}</div>}
          </form>
        </div>
      </div>
    );
  }

  // app (per-user) or legacy (shared code) — render the shell.
  const isApp = mode === "app" && !!user;
  const allowed = (n) => !n.module || user.role === "admin" || (user.modules || []).includes(n.module);
  const items = isApp ? NAV.filter(allowed) : NAV;

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}${ready ? "" : " preload"}`}>
      <aside className="sidebar">
        <div className="side-head">
          <Link href="/" className="side-logo" title="TradeHub home">
            <BrandMarkIcon size={28} />
            {!collapsed && <span className="side-brand">TRADE<b>HUB</b></span>}
          </Link>
          <button className="side-toggle" onClick={toggle} title={collapsed ? "Expand menu" : "Collapse menu"} aria-label="Toggle menu">
            {collapsed ? "»" : "«"}
          </button>
        </div>
        <nav className="side-nav">
          {items.map((n) => {
            const I = Ico[n.icon];
            const active = path === n.href || (n.href !== "/" && path?.startsWith(n.href));
            return (
              <Link key={n.href} href={n.href} className={`side-item${active ? " active" : ""}`} title={n.label}>
                <span className="side-ico"><I /></span>{!collapsed && <span className="side-label">{n.label}</span>}
              </Link>
            );
          })}
          {isApp && user.role === "admin" && (
            <Link href="/users" className={`side-item${path?.startsWith("/users") ? " active" : ""}`} title="Users">
              <span className="side-ico"><Ico.users /></span>{!collapsed && <span className="side-label">Users</span>}
            </Link>
          )}
          {!collapsed && SOON.length > 0 && <div className="side-sep">Coming soon</div>}
          {SOON.map((l) => (
            <span key={l} className="side-item soon" title={`${l} — coming soon`}>
              <span className="side-ico"><Ico.dot /></span>{!collapsed && <span className="side-label">{l}</span>}
            </span>
          ))}
          <div className="side-foot">
            {isApp && !collapsed && <div className="side-who" title={user.email}>{user.name || user.email}</div>}
            <button type="button" className="side-item logout" onClick={logout} title="Log out">
              <span className="side-ico"><Ico.logout /></span>{!collapsed && <span className="side-label">Log out</span>}
            </button>
          </div>
        </nav>
      </aside>
      <main className="main">
        {children}
        <footer className="app-footer">
          <span>Trade Superstore Online</span>
          <span className="dot">·</span>
          <a href="tel:03330909217">0333 090 9217</a>
          <span className="dot">·</span>
          <a href="https://www.tradesuperstoreonline.co.uk" target="_blank" rel="noreferrer">tradesuperstoreonline.co.uk</a>
        </footer>
      </main>
    </div>
  );
}
