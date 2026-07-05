export const API = import.meta.env?.VITE_API_URL || "https://api.getcortexops.com";

const SESSION_KEY = "cxo_session";

export function loadSession() {
  try {
    let raw = localStorage.getItem(SESSION_KEY);
    if (!raw) {
      const legacy = sessionStorage.getItem(SESSION_KEY);
      if (legacy) {
        localStorage.setItem(SESSION_KEY, legacy);
        sessionStorage.removeItem(SESSION_KEY);
        raw = legacy;
      }
    }
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(SESSION_KEY);
}

export function sessionExpired(session) {
  if (!session?.expires_at) return true;
  return Date.now() >= session.expires_at - 60_000;
}

export function isAuthError(err) {
  const msg = err?.message || String(err);
  return /invalid|revoked|expired|401|unauthorized|sign in again/i.test(msg);
}

export async function issueToken(apiKey) {
  const r = await fetch(`${API}/v1/auth/token/issue`, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    const detail = typeof err.detail === "string"
      ? err.detail
      : err.detail?.error || JSON.stringify(err.detail || err);
    throw new Error(detail || `Login failed (${r.status})`);
  }
  const data = await r.json();
  return {
    access_token: data.access_token,
    project: data.project,
    tier: data.tier,
    scope: data.scope,
    key_id: data.key_id || "",
    expires_at: Date.now() + (data.expires_in || 3600) * 1000,
    api_key: apiKey,
  };
}

export async function refreshSession(session) {
  if (!session?.api_key) throw new Error("Session missing API key — sign in again");
  const next = await issueToken(session.api_key);
  saveSession(next);
  return next;
}

export async function ensureSession(session) {
  if (!session) throw new Error("Not logged in");
  if (!sessionExpired(session)) return session;
  return refreshSession(session);
}

export function keyIdFromToken(token) {
  if (!token) return "";
  try {
    const part = token.split(".")[1];
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
    return json.key_id || "";
  } catch {
    return "";
  }
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

export async function apiFetch(token, path, options = {}) {
  const headers = {
    ...authHeaders(token),
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...options.headers,
  };
  const r = await fetch(`${API}${path}`, { ...options, headers });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    const detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail || err);
    throw new Error(detail || `Request failed (${r.status})`);
  }
  if (r.status === 204) return null;
  return r.json();
}
