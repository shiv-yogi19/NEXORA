// NEXORA API client and honest connection tracking. Created By Shiv Yogi.
//
// - Every request has a timeout and a visible failure path (no endless spinners).
// - A failed request triggers ONE health probe to tell "server unreachable" apart from
//   "server reachable but this website is not allowed" and from "request failed".
// - Automatic recovery attempts are capped (4 attempts, growing delay); after that the user retries by hand.
// - No credentials or tokens are kept in JavaScript or browser storage. The session lives in an HttpOnly cookie.
import { resolveApiBase, isConfigured } from "./config.js";

export const API = "/api/v1";
export const apiBase = () => resolveApiBase();
export const apiUrl = (path) => apiBase() + API + path;

export class ApiError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    Object.assign(this, extra);
  }
}
export class NetworkError extends Error {
  constructor(kind, message) { super(message); this.name = "NetworkError"; this.kind = kind; }
}

// ---- connection state ----
const LAST_KEY = "nexora.lastOnline"; // a timestamp only
export const conn = {
  status: "connecting", // online | offline | connecting | reconnecting | degraded
  reason: null,         // unreachable | origin | request | unconfigured | null
  lastSuccess: null,
  attempts: 0,
  gaveUp: false,
  listeners: new Set(),
};
try { const v = Number(localStorage.getItem(LAST_KEY)); if (v) conn.lastSuccess = v; } catch (_) { /* ignore */ }
export function onConnection(fn) { conn.listeners.add(fn); return () => conn.listeners.delete(fn); }
function emit() { for (const fn of conn.listeners) { try { fn(conn); } catch (e) { console.error(e); } } }
export function setStatus(status, reason = null) {
  if (conn.status === status && conn.reason === reason) return;
  conn.status = status; conn.reason = reason;
  emit();
}
export function markOnline() {
  conn.lastSuccess = Math.floor(Date.now() / 1000);
  try { localStorage.setItem(LAST_KEY, String(conn.lastSuccess)); } catch (_) { /* ignore */ }
  conn.attempts = 0; conn.gaveUp = false;
  clearTimeout(recoveryTimer);
  setStatus("online", null);
}

const sessionListeners = new Set();
export function onSessionExpired(fn) { sessionListeners.add(fn); return () => sessionListeners.delete(fn); }

function withTimeout(ms, outer) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(new DOMException("timeout", "TimeoutError")), ms);
  if (outer) outer.addEventListener("abort", () => ctl.abort(outer.reason), { once: true });
  return { signal: ctl.signal, done: () => clearTimeout(timer), ctl };
}

/** JSON request. Resolves with parsed JSON, or throws ApiError / NetworkError. */
export async function request(path, { method = "GET", json, body, signal, timeout = 12000, quiet = false, headers = {} } = {}) {
  if (!isConfigured()) {
    setStatus("offline", "unconfigured");
    throw new NetworkError("unconfigured", "The backend address is not configured yet.");
  }
  const t = withTimeout(timeout, signal);
  const h = { Accept: "application/json", ...headers };
  if (method !== "GET" && method !== "HEAD") h["X-NEXORA-CSRF"] = "1";
  let payload = body;
  if (json !== undefined) { h["Content-Type"] = "application/json"; payload = JSON.stringify(json); }
  let res;
  try {
    res = await fetch(apiUrl(path), { method, headers: h, body: payload, credentials: "include", signal: t.signal, cache: "no-store", referrerPolicy: "no-referrer" });
  } catch (err) {
    t.done();
    if (signal && signal.aborted) throw err; // the caller cancelled on purpose
    const timedOut = err && (err.name === "TimeoutError" || err.name === "AbortError");
    if (!quiet) reportFailure();
    throw new NetworkError(timedOut ? "timeout" : "unreachable", timedOut ? "The server took too long to answer." : "Could not reach the server.");
  }
  t.done();
  let data = null;
  const text = await res.text().catch(() => "");
  if (text) { try { data = JSON.parse(text); } catch (_) { data = null; } }
  if (!res.ok) {
    const e = (data && data.error) || {};
    const retry = Number(res.headers.get("Retry-After")) || e.retry_after || 0;
    if (res.status === 401 && e.code === "unauthenticated" && path !== "/auth/session") for (const fn of sessionListeners) fn();
    if (res.status >= 502 && !quiet) reportFailure(); // tunnel up but server down returns a gateway error
    throw new ApiError(res.status, e.code || "error", e.message || "The server returned an error (" + res.status + ").", { retryAfter: retry, data: e });
  }
  if (conn.status !== "online") markOnline();
  return data;
}
export const get = (p, o) => request(p, o);
export const post = (p, json, o) => request(p, { method: "POST", json, ...o });
export const del = (p, o) => request(p, { method: "DELETE", ...o });

// ---- health probing and recovery ----
let probing = null;
let recoveryTimer = 0;

/** Ask the public health endpoint (no credentials, no custom headers) what is going on. */
export async function probeHealth(timeout = 6000) {
  if (!isConfigured()) return { reachable: false, reason: "unconfigured" };
  const t = withTimeout(timeout);
  try {
    const res = await fetch(apiBase() + API + "/health", { cache: "no-store", credentials: "omit", signal: t.signal, referrerPolicy: "no-referrer" });
    t.done();
    const data = await res.json().catch(() => null);
    if (!data || data.service !== "nexora") return { reachable: true, healthy: false, reason: "not-nexora" };
    return { reachable: true, healthy: res.ok && data.status === "ok", originAllowed: data.origin_allowed !== false, data };
  } catch (_) {
    t.done();
    return { reachable: false, reason: "unreachable" };
  }
}

export function reportFailure() {
  if (probing) return probing;
  if (conn.status === "online") setStatus("degraded", "request");
  probing = (async () => {
    const p = await probeHealth();
    if (!p.reachable) { setStatus("offline", p.reason || "unreachable"); scheduleRecovery(); }
    else if (!p.originAllowed) setStatus("degraded", "origin");
    else if (!p.healthy) setStatus("degraded", "server");
    else setStatus("degraded", "request"); // reachable and healthy, but that one request failed or timed out
  })().finally(() => { probing = null; });
  return probing;
}

/** Manual or automatic check. Returns true when the server answered and is healthy. */
export async function checkNow({ manual = false } = {}) {
  if (manual) { conn.attempts = 0; conn.gaveUp = false; }
  if (conn.status === "offline") setStatus("reconnecting", conn.reason);
  const p = await probeHealth();
  if (p.reachable && p.healthy && p.originAllowed) { markOnline(); return true; }
  if (!p.reachable) { setStatus("offline", p.reason || "unreachable"); scheduleRecovery(); }
  else if (!p.originAllowed) setStatus("degraded", "origin");
  else setStatus("degraded", "server");
  return false;
}

const BACKOFF = [5000, 15000, 45000, 120000];
function scheduleRecovery() {
  clearTimeout(recoveryTimer);
  if (conn.attempts >= BACKOFF.length) { conn.gaveUp = true; emit(); return; } // stop: no endless retry loop
  const delay = BACKOFF[conn.attempts++];
  recoveryTimer = setTimeout(async () => {
    if (document.hidden) { conn.attempts--; return; } // resume when the tab is visible again
    await checkNow();
  }, delay);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && conn.status === "offline" && conn.attempts < BACKOFF.length) checkNow();
});
window.addEventListener("online", () => { if (conn.status !== "online") checkNow({ manual: true }); });
window.addEventListener("offline", () => setStatus("offline", "unreachable"));

// ---- file URLs (media elements send the session cookie themselves) ----
export const fileUrl = (id, what = "stream") => apiUrl("/files/" + encodeURIComponent(id) + "/" + what);

/** Upload with real progress. Returns {promise, abort}. Resolves only when the server confirms completion. */
export function uploadFile(file, category, onProgress) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("category", category);
    fd.append("file", file, file.name);
    xhr.open("POST", apiUrl("/uploads"));
    xhr.withCredentials = true;
    xhr.responseType = "text";
    xhr.timeout = 0; // large files: the user can cancel instead
    xhr.setRequestHeader("X-NEXORA-CSRF", "1");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* leave null */ }
      if (xhr.status === 201 && data && data.status === "completed") { markOnline(); resolve(data); return; }
      const e = (data && data.error) || {};
      if (xhr.status === 401) for (const fn of sessionListeners) fn();
      reject(new ApiError(xhr.status, e.code || "error", e.message || "Upload failed (" + xhr.status + ").", { data: e }));
    };
    xhr.onerror = () => { reportFailure(); reject(new NetworkError("unreachable", "The connection was lost during the upload. The file was not saved.")); };
    xhr.onabort = () => reject(new NetworkError("aborted", "Upload cancelled. Nothing was saved."));
    xhr.send(fd);
  });
  return { promise, abort: () => xhr.abort() };
}
