"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import BrandMark from "./BrandMark";

const Ico = {
  home: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" /><path d="M9.5 21v-6h5v6" /></svg>),
  orders: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 7v10l9 4 9-4V7" /><path d="M12 11v10" /></svg>),
  statements: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" /><path d="M14 2v5h5" /><path d="M8 13h8M8 17h5" /></svg>),
  invoices: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1z" /><path d="M8 7h8M8 11h8M8 15h5" /></svg>),
  dot: (p) => (<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" {...p}><circle cx="12" cy="12" r="3" /></svg>),
};

const NAV = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/orders", label: "Orders", icon: "orders" },
  { href: "/recon", label: "Statements", icon: "statements" },
  { href: "/invoices", label: "Invoices", icon: "invoices" },
];
const SOON = ["Quotes", "Triage"];

export default function AppShell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [ready, setReady] = useState(false);
  const path = usePathname();

  useEffect(() => {
    try { setCollapsed(localStorage.getItem("th_nav_collapsed") === "1"); } catch {}
    setReady(true);
  }, []);

  function toggle() {
    setCollapsed((c) => {
      const n = !c;
      try { localStorage.setItem("th_nav_collapsed", n ? "1" : "0"); } catch {}
      return n;
    });
  }

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}${ready ? "" : " preload"}`}>
      <aside className="sidebar">
        <div className="side-head">
          <Link href="/" className="side-logo" title="TradeHub home">
            <BrandMark size={28} />
            {!collapsed && <span className="side-brand">Trade<b>Hub</b></span>}
          </Link>
          <button className="side-toggle" onClick={toggle} title={collapsed ? "Expand menu" : "Collapse menu"} aria-label="Toggle menu">
            {collapsed ? "»" : "«"}
          </button>
        </div>
        <nav className="side-nav">
          {NAV.map((n) => {
            const I = Ico[n.icon];
            const active = path === n.href || (n.href !== "/" && path?.startsWith(n.href));
            return (
              <Link key={n.href} href={n.href} className={`side-item${active ? " active" : ""}`} title={n.label}>
                <span className="side-ico"><I /></span>{!collapsed && <span className="side-label">{n.label}</span>}
              </Link>
            );
          })}
          {!collapsed && <div className="side-sep">Coming soon</div>}
          {SOON.map((l) => (
            <span key={l} className="side-item soon" title={`${l} — coming soon`}>
              <span className="side-ico"><Ico.dot /></span>{!collapsed && <span className="side-label">{l}</span>}
            </span>
          ))}
        </nav>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
