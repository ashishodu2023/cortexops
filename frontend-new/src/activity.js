/** In-dashboard activity feed — tracks what you do in this browser session. */
const STORAGE_KEY = "cxo_ui_activity";
const MAX_ENTRIES = 150;

export function loadUiActivity() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function logUiActivity(type, label, meta = {}) {
  const entry = {
    id: crypto.randomUUID(),
    type,
    label,
    meta,
    at: Date.now(),
  };
  const next = [entry, ...loadUiActivity()].slice(0, MAX_ENTRIES);
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return entry;
}

export function clearUiActivity() {
  sessionStorage.removeItem(STORAGE_KEY);
}
