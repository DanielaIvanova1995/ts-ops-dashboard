"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = "th_access_key";

export default function Users() {
  const [token, setToken] = useState(null);
  const [modules, setModules] = useState({});   // key -> label
  const [users, setUsers] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | ok | denied | disabled | error
  const [err, setErr] = useState("");
  // new-user form
  const [nName, setNName] = useState("");
  const [nEmail, setNEmail] = useState("");
  const [nPw, setNPw] = useState("");
  const [nRole, setNRole] = useState("staff");
  const [nMods, setNMods] = useState(new Set());
  const [adding, setAdding] = useState(false);

  useEffect(() => { try { setToken(localStorage.getItem(KEY)); } catch { setToken(""); } }, []);

  const authFetch = useCallback(async (path, opts = {}) => {
    return fetch(`${API}${path}`, {
      ...opts, cache: "no-store",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + (token || ""), ...(opts.headers || {}) },
    });
  }, [token]);

  const load = useCallback(async () => {
    if (token === null) return;
    setStatus("loading"); setErr("");
    try {
      const mr = await authFetch("/auth/modules");
      const ur = await authFetch("/auth/users");
      if (ur.status === 503) { setStatus("disabled"); return; }
      if (ur.status === 401) { setStatus("denied"); setErr("Please sign in again."); return; }
      if (ur.status === 403) { setStatus("denied"); setErr("Only an admin can manage users."); return; }
      if (!ur.ok) { setStatus("error"); setErr(`API ${ur.status}`); return; }
      const md = await mr.json().catch(() => ({}));
      const ud = await ur.json();
      setModules(md.modules || {});
      setUsers(ud.users || []);
      setStatus("ok");
    } catch (e) { setStatus("error"); setErr(String(e.message || e)); }
  }, [token, authFetch]);
  useEffect(() => { if (token !== null) load(); }, [token, load]);

  const MODS = Object.entries(modules); // [key,label]

  function toggleN(k) { setNMods((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; }); }

  async function addUser(e) {
    e.preventDefault();
    if (!nEmail.trim() || !nPw || nPw.length < 6) { setErr("Email and a 6+ character password are required."); return; }
    setAdding(true); setErr("");
    try {
      const r = await authFetch("/auth/users", { method: "POST", body: JSON.stringify({ email: nEmail.trim(), name: nName.trim(), password: nPw, role: nRole, modules: nRole === "admin" ? [] : [...nMods], active: true }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) { setNName(""); setNEmail(""); setNPw(""); setNRole("staff"); setNMods(new Set()); load(); }
      else setErr(d.detail || "Couldn't add the user.");
    } catch (e) { setErr(String(e.message || e)); }
    finally { setAdding(false); }
  }

  async function patch(u, body) {
    try {
      const r = await authFetch(`/auth/users/${u.id}`, { method: "PATCH", body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) setUsers((xs) => xs.map((x) => x.id === u.id ? d.user : x));
      else setErr(d.detail || "Couldn't update.");
    } catch (e) { setErr(String(e.message || e)); }
  }

  function toggleMod(u, k) {
    const has = (u.modules || []).includes(k);
    patch(u, { modules: has ? u.modules.filter((m) => m !== k) : [...(u.modules || []), k] });
  }

  async function resetPw(u) {
    const p = window.prompt(`Set a new password for ${u.name || u.email} (6+ characters):`);
    if (!p) return;
    if (p.length < 6) { setErr("Password must be at least 6 characters."); return; }
    try {
      const r = await authFetch(`/auth/users/${u.id}/password`, { method: "POST", body: JSON.stringify({ password: p }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) setErr(""); else setErr(d.detail || "Couldn't reset the password.");
      if (r.ok && d.ok) window.alert(`Password updated for ${u.email}.`);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function del(u) {
    if (!window.confirm(`Remove ${u.name || u.email}? They won't be able to sign in.`)) return;
    try {
      const r = await authFetch(`/auth/users/${u.id}`, { method: "DELETE" });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) setUsers((xs) => xs.filter((x) => x.id !== u.id)); else setErr(d.detail || "Couldn't remove the user.");
    } catch (e) { setErr(String(e.message || e)); }
  }

  if (status === "disabled") return (
    <div className="wrap"><div className="topbar"><div className="pagetitle">Users</div></div>
      <div className="card"><div className="state">Per-user logins aren't switched on yet. Follow <code>docs/SUPABASE_PHASE2.md</code> to enable them (set <code>TRADEHUB_AUTH=1</code>).</div></div></div>
  );
  if (status === "denied") return (
    <div className="wrap"><div className="topbar"><div className="pagetitle">Users</div></div>
      <div className="card"><div className="state err">{err || "Admins only."}</div></div></div>
  );

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="pagetitle">Users</div>
        <div className="right">
          <span className="count">{status === "ok" ? `${users.length} user${users.length === 1 ? "" : "s"}` : status === "loading" ? "Loading…" : ""}</span>
          <button className="btn" onClick={load} disabled={status === "loading"}>Refresh</button>
        </div>
      </div>

      {err && status === "ok" && <div className="card"><div className="state err">{err}</div></div>}

      <div className="card" style={{ padding: "12px 14px", marginBottom: 12 }}>
        <div className="tool-label">Add a person</div>
        <form onSubmit={addUser} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 8 }}>
          <input className="input" style={{ maxWidth: 180 }} placeholder="Name" value={nName} onChange={(e) => setNName(e.target.value)} />
          <input className="input" style={{ maxWidth: 220 }} type="email" placeholder="Work email" value={nEmail} onChange={(e) => setNEmail(e.target.value)} />
          <input className="input" style={{ maxWidth: 160 }} type="password" placeholder="Password (6+)" value={nPw} onChange={(e) => setNPw(e.target.value)} />
          <select className="input" style={{ maxWidth: 130 }} value={nRole} onChange={(e) => setNRole(e.target.value)}>
            <option value="staff">Staff</option>
            <option value="admin">Admin (all access)</option>
          </select>
          <button className="btn primary" type="submit" disabled={adding}>{adding ? "Adding…" : "Add"}</button>
        </form>
        {nRole === "staff" && (
          <div style={{ marginTop: 10 }}>
            <div className="sub" style={{ marginBottom: 4 }}>Can open:</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {MODS.map(([k, label]) => (
                <label key={k} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 13 }}>
                  <input type="checkbox" checked={nMods.has(k)} onChange={() => toggleN(k)} /> {label}
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="sub" style={{ marginTop: 8 }}>You set the password here; the person can't change it themselves — use “Reset” below to change it later.</div>
      </div>

      {status === "ok" && (
        <div className="card" style={{ padding: "6px 10px" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="mini">
              <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Can open</th><th>Active</th><th>Last sign-in</th><th></th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><b>{u.name || "—"}</b></td>
                    <td className="sub">{u.email}</td>
                    <td>
                      <select className="input" style={{ padding: "2px 6px", height: 28 }} value={u.role} onChange={(e) => patch(u, { role: e.target.value })}>
                        <option value="staff">Staff</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td>
                      {u.role === "admin" ? <span className="pill grey">all modules</span> : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 7, maxWidth: 420 }}>
                          {MODS.map(([k, label]) => (
                            <label key={k} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
                              <input type="checkbox" checked={(u.modules || []).includes(k)} onChange={() => toggleMod(u, k)} /> {label}
                            </label>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <label style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <input type="checkbox" checked={!!u.active} onChange={(e) => patch(u, { active: e.target.checked })} />
                        <span className={`pill ${u.active ? "green" : "red"}`}>{u.active ? "Active" : "Off"}</span>
                      </label>
                    </td>
                    <td className="sub" style={{ whiteSpace: "nowrap" }}>{u.last_login ? String(u.last_login).slice(0, 16).replace("T", " ") : "—"}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn ghost" onClick={() => resetPw(u)}>Reset password</button>
                      <button className="btn ghost" onClick={() => del(u)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {status === "error" && <div className="card"><div className="state err">Couldn’t load users ({err}).</div></div>}
    </div>
  );
}
