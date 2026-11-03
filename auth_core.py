"""Per-user logins + per-module access control — Platform Phase 2.

FEATURE-FLAGGED and inert by default. Auth only activates when ALL of these are true:
  - TRADEHUB_AUTH is truthy on the host,
  - TRADEHUB_AUTH_SECRET is set (used to sign session tokens),
  - Supabase is configured (supabase_db.configured()).
Until then `enabled()` is False and the API keeps using the existing shared access-code gate, so
nothing changes for the running app. See docs/SUPABASE_PHASE2.md for the table + setup.

Storage: a `tradehub_users` table in Supabase. Passwords are bcrypt-hashed (admin sets/resets them).
Sessions are stateless HS256 JWTs carrying only the user id + expiry (signed with TRADEHUB_AUTH_SECRET,
stdlib only — no extra dependency). The guard reads the user row (active + modules) on each request,
cached ~60s, so deactivating someone or changing their access takes effect within a minute.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import bcrypt  # already a repo dependency (was used by the Streamlit config.yaml logins)

import supabase_db
from data_sources import get_secret

USERS_TABLE = "tradehub_users"
TOKEN_TTL = 12 * 3600          # 12 hours, then re-login
_USER_CACHE_TTL = 60           # seconds — how long a loaded user row is trusted before re-reading

# The modules access can be granted to — keys match the hub's routes/nav.
MODULES = {
    "orders": "Order Processing",
    "quotes": "Quotes",
    "invoices": "Invoice Checker",
    "recon": "Statements",
    "pricing": "Pricing",
    "triage": "Triage",
    "payments": "Payments",
    "assistant": "My Assistant",
}


def _secret() -> str | None:
    v = (get_secret("TRADEHUB_AUTH_SECRET") or "").strip()
    return v or None


def _flag_on() -> bool:
    return (get_secret("TRADEHUB_AUTH") or "").strip().lower() in ("1", "true", "yes", "on")


def enabled() -> bool:
    """True only when per-user auth is switched on AND fully configured. Callers fall back to the
    shared access-code gate when this is False."""
    try:
        return bool(_flag_on() and _secret() and supabase_db.configured())
    except Exception:  # noqa: BLE001
        return False


# ---- passwords -----------------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    return bcrypt.hashpw((pw or "").encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw((pw or "").encode(), (stored or "").encode())
    except Exception:  # noqa: BLE001
        return False


# ---- session tokens (stdlib HS256 JWT) -----------------------------------------------------------
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid: str, ttl: int = TOKEN_TTL) -> str:
    secret = (_secret() or "").encode()
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"uid": str(uid), "exp": int(time.time()) + int(ttl)}
    seg = (_b64e(json.dumps(header, separators=(",", ":")).encode()) + "."
           + _b64e(json.dumps(payload, separators=(",", ":")).encode()))
    sig = _b64e(hmac.new(secret, seg.encode(), hashlib.sha256).digest())
    return seg + "." + sig


def read_token(tok: str) -> dict | None:
    """Return the token payload if the signature is valid and it hasn't expired, else None."""
    secret = (_secret() or "").encode()
    if not tok or not secret:
        return None
    try:
        h, p, s = tok.split(".")
        expect = _b64e(hmac.new(secret, (h + "." + p).encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expect):
            return None
        payload = json.loads(_b64d(p))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


# ---- user store (Supabase) -----------------------------------------------------------------------
def _tbl():
    return supabase_db._client().table(USERS_TABLE)


def _clean(row: dict | None) -> dict | None:
    """Public-safe user dict — never leaks the password hash."""
    if not row:
        return None
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "name": row.get("name"),
        "role": row.get("role") or "staff",
        "modules": list(row.get("modules") or []),
        "active": bool(row.get("active", True)),
        "last_login": row.get("last_login"),
        "created_at": row.get("created_at"),
    }


def count_users() -> int:
    try:
        r = _tbl().select("id", count="exact").execute()
        return int(getattr(r, "count", None) or len(r.data or []))
    except Exception:  # noqa: BLE001
        return 0


def get_user_by_email(email: str) -> dict | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    try:
        r = _tbl().select("*").eq("email", em).limit(1).execute()
        return (r.data or [None])[0]
    except Exception:  # noqa: BLE001
        return None


def get_user(uid: str) -> dict | None:
    try:
        r = _tbl().select("*").eq("id", str(uid)).limit(1).execute()
        return (r.data or [None])[0]
    except Exception:  # noqa: BLE001
        return None


def list_users() -> list[dict]:
    try:
        r = _tbl().select("*").order("email").execute()
        return [_clean(x) for x in (r.data or [])]
    except Exception:  # noqa: BLE001
        return []


def create_user(email: str, name: str, password: str, role: str = "staff",
                modules: list | None = None, active: bool = True) -> dict:
    em = (email or "").strip().lower()
    if not em or "@" not in em:
        raise ValueError("a valid email is required")
    if get_user_by_email(em):
        raise ValueError("a user with that email already exists")
    if not password or len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    role = "admin" if role == "admin" else "staff"
    mods = [m for m in (modules or []) if m in MODULES]
    row = {"email": em, "name": (name or em).strip(), "password_hash": hash_password(password),
           "role": role, "modules": mods, "active": bool(active)}
    r = _tbl().insert(row).execute()
    return _clean((r.data or [row])[0])


def update_user(uid: str, *, name: str | None = None, role: str | None = None,
                modules: list | None = None, active: bool | None = None) -> dict | None:
    patch: dict = {}
    if name is not None:
        patch["name"] = name.strip()
    if role is not None:
        patch["role"] = "admin" if role == "admin" else "staff"
    if modules is not None:
        patch["modules"] = [m for m in modules if m in MODULES]
    if active is not None:
        patch["active"] = bool(active)
    if not patch:
        return get_user(uid)
    _tbl().update(patch).eq("id", str(uid)).execute()
    _CACHE.pop(str(uid), None)
    return _clean(get_user(uid))


def set_password(uid: str, password: str) -> None:
    if not password or len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    _tbl().update({"password_hash": hash_password(password)}).eq("id", str(uid)).execute()
    _CACHE.pop(str(uid), None)


def delete_user(uid: str) -> None:
    _tbl().delete().eq("id", str(uid)).execute()
    _CACHE.pop(str(uid), None)


def touch_login(uid: str) -> None:
    try:
        import datetime as _dt
        _tbl().update({"last_login": _dt.datetime.utcnow().isoformat()}).eq("id", str(uid)).execute()
    except Exception:  # noqa: BLE001
        pass


def authenticate(email: str, password: str) -> dict | None:
    """Return a public user dict (+ a fresh token) on valid credentials, else None."""
    row = get_user_by_email(email)
    if not row or not row.get("active", True):
        return None
    if not verify_password(password, row.get("password_hash") or ""):
        return None
    touch_login(row["id"])
    user = _clean(row)
    return {"token": make_token(row["id"]), "user": user}


# ---- request-time resolution (cached) ------------------------------------------------------------
_CACHE: dict[str, tuple[float, dict]] = {}   # uid -> (loaded_at, clean_user)


def load_user_cached(uid: str) -> dict | None:
    now = time.time()
    hit = _CACHE.get(str(uid))
    if hit and now - hit[0] < _USER_CACHE_TTL:
        return hit[1]
    row = get_user(uid)
    user = _clean(row) if row else None
    if user:
        _CACHE[str(uid)] = (now, user)
    return user


def user_from_token(tok: str) -> dict | None:
    """Validate a bearer token and return the live (cached) user, or None. Admins implicitly have
    every module; staff have exactly their granted list."""
    payload = read_token(tok or "")
    if not payload:
        return None
    user = load_user_cached(payload.get("uid"))
    if not user or not user.get("active", True):
        return None
    if user.get("role") == "admin":
        user = dict(user, modules=list(MODULES.keys()))
    return user


def user_can(user: dict | None, module: str | None) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    if module is None:
        return True                       # shared/meta endpoint — any logged-in user
    return module in (user.get("modules") or [])


def module_for_path(path: str) -> str | None:
    """Map an API request path to the module it belongs to. Returns None for shared/meta endpoints
    (any logged-in user may call them)."""
    p = (path or "").rstrip("/")
    if p.startswith("/recon/payments"):
        return "payments"
    if p.startswith("/recon"):
        return "recon"
    if p.startswith("/orders"):
        return "orders"
    if p.startswith("/invoices"):
        return "invoices"
    if p.startswith("/quotes"):
        return "quotes"
    if p.startswith("/pricing"):
        return "pricing"
    if p.startswith("/triage"):
        return "triage"
    if p.startswith("/assistant"):
        return "assistant"
    return None                            # /meta, /updates-counts, /auth/*, etc.
