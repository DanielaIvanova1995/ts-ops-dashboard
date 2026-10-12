"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Stage → pill colour. Mirrors how the current board reads at a glance.
function stagePill(stage) {
  if (!stage) return { cls: "dash", label: "—" };
  const s = stage.toLowerCase();
  if (s.includes("send po") || s.includes("po sent")) return { cls: "green", label: stage };
  if (s.includes("place order")) return { cls: "blue", label: stage };
  if (s.includes("quote")) return { cls: "amber", label: stage };
  if (s.includes("portal")) return { cls: "amber", label: stage };
  return { cls: "grey", label: stage };
}

function money(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? "£" + n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(v);
}

export default function Board() {
  const [orders, setOrders] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | ok | error
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const res = await fetch(`${API}/orders`, { cache: "no-store" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setOrders(data.orders || []);
      setUpdatedAt(new Date());
      setStatus("ok");
    } catch (e) {
      setError(String(e.message || e));
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="wordmark">Trade<b>Hub</b><span className="sec">Order Processing</span></div>
        <div className="right">
          <span className="count">
            {status === "ok" ? <><b>{orders.length}</b> orders</> : status === "loading" ? "Loading…" : ""}
            {updatedAt && status === "ok" ? ` · ${updatedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
          <button className="btn primary" onClick={load} disabled={status === "loading"}>
            {status === "loading" ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="card">
        {status === "loading" && orders.length === 0 && (
          <div className="state"><span className="spinner" />Reading the NEW ORDERS board from Monday…</div>
        )}
        {status === "error" && (
          <div className="state err">
            Couldn’t reach the API ({error}).<br />
            <span className="sub">Check the API service is running and NEXT_PUBLIC_API_URL points to it.</span>
          </div>
        )}
        {(status === "ok" || orders.length > 0) && (
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Supplier</th>
                <th>Stage</th>
                <th className="num">£ to us</th>
                <th className="num">£ supplier</th>
                <th>PO</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => {
                const sp = stagePill(o.stage);
                return (
                  <tr key={o.item_id}>
                    <td className="ono">{o.order_no}</td>
                    <td className="cust">{o.customer || "—"}</td>
                    <td>{o.supplier || <span className="sub">— unrouted —</span>}</td>
                    <td><span className={`pill ${sp.cls}`}>{sp.label}</span></td>
                    <td className="num">{money(o.sell)}</td>
                    <td className="num">{money(o.cost_supplier)}</td>
                    <td>{o.has_po ? <span className="pill green">attached</span> : <span className="pill dash">none</span>}</td>
                  </tr>
                );
              })}
              {status === "ok" && orders.length === 0 && (
                <tr><td colSpan={7}><div className="state">No orders in the NEW ORDERS group right now. 🎉</div></td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
