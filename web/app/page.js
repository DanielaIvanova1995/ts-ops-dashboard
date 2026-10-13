"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import BrandMark from "./BrandMark";

/* Light, instant landing page. Nothing here fetches — each screen loads only when opened,
   so visiting the hub no longer forces the heavy Order Processing load every time. */

const Ico = {
  orders: (p) => (<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M3 7l9-4 9 4-9 4-9-4z" /><path d="M3 7v10l9 4 9-4V7" /><path d="M12 11v10" /></svg>),
  statements: (p) => (<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" /><path d="M14 2v5h5" /><path d="M8 13h8M8 17h5" /></svg>),
  invoices: (p) => (<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1z" /><path d="M8 7h8M8 11h8M8 15h5" /></svg>),
  quotes: (p) => (<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none" /></svg>),
  triage: (p) => (<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></svg>),
};

const LIVE = [
  { href: "/orders", icon: "orders", title: "Order Processing", sub: "Route orders, raise & send POs, split & merge" },
  { href: "/recon", icon: "statements", title: "Statements", sub: "Reconcile supplier statements, pay & remit" },
  { href: "/invoices", icon: "invoices", title: "Invoice Checker", sub: "3-way check invoices, approve to QuickBooks" },
];
const SOON = [
  { icon: "quotes", title: "Quotes", sub: "Build & price customer quotes" },
  { icon: "triage", title: "Triage", sub: "Sort the inbox into action folders" },
];

export default function Home() {
  const [greeting, setGreeting] = useState("Welcome back");
  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening");
  }, []);

  return (
    <div className="wrap home">
      <div className="home-brand">
        <BrandMark size={48} />
        <span className="bn">Trade<b>Hub</b><span className="bs">Trade Superstore Online · operations</span></span>
      </div>
      <div className="home-head">
        <h1>{greeting}</h1>
        <p>Pick where to start — screens load only when you open them.</p>
      </div>

      <div className="home-grid">
        {LIVE.map((t) => {
          const I = Ico[t.icon];
          return (
            <Link key={t.href} href={t.href} className="home-tile">
              <span className="home-ico"><I /></span>
              <span className="home-tt">{t.title}</span>
              <span className="home-sub">{t.sub}</span>
              <span className="home-go">Open →</span>
            </Link>
          );
        })}
        {SOON.map((t) => {
          const I = Ico[t.icon];
          return (
            <span key={t.title} className="home-tile soon">
              <span className="home-ico"><I /></span>
              <span className="home-tt">{t.title}</span>
              <span className="home-sub">{t.sub}</span>
              <span className="home-badge">Coming soon</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
