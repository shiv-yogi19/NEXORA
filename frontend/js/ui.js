// NEXORA UI helpers: DOM builder (never uses innerHTML for data), icons, formatting, toasts, sheets, prefs.
// Created By Shiv Yogi.

/** h("div", {class:"x", onclick: fn, "aria-label":"y"}, "text", childNode) */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") for (const [p, val] of Object.entries(v)) el.style.setProperty(p.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase()), val);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k === "text") el.textContent = v;
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ---- icons (constant, trusted path data only) ----
const PATHS = {
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4",
  music: "M9 18V6l11-2v12M9 18a3 3 0 11-6 0 3 3 0 016 0zM20 16a3 3 0 11-6 0 3 3 0 016 0z",
  image: "M4 5h16v14H4zM8.5 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM4 17l5-5 4 4 3-3 4 4",
  file: "M6 3h8l5 5v13H6zM14 3v5h5M9 13h6M9 17h6",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  bookmark: "M6 3h12v18l-6-4-6 4z",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  share: "M12 3v12M8 7l4-4 4 4M5 12v8h14v-8",
  drive: "M3 14l3-9h12l3 9M3 14v5h18v-5zM7 17h.01M11 17h.01",
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  sliders: "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4",
  info: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v5M12 8h.01",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4",
  play: "M7 4l13 8-13 8z",
  pause: "M8 4v16M16 4v16",
  prev: "M19 5v14M17 12L7 5v14z",
  next: "M5 5v14M7 12l10-7v14z",
  shuffle: "M3 7h4l10 10h4M17 17l4 0M21 17l-3 3M21 17l-3-3M3 17h4l3-3M14 10l3-3h4M21 7l-3 3M21 7l-3-3",
  repeat: "M4 11V9a3 3 0 013-3h13M17 3l3 3-3 3M20 13v2a3 3 0 01-3 3H4M7 21l-3-3 3-3",
  volume: "M4 9v6h4l5 4V5L8 9zM16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11",
  mute: "M4 9v6h4l5 4V5L8 9zM17 9l5 6M22 9l-5 6",
  x: "M6 6l12 12M18 6L6 18",
  left: "M15 5l-7 7 7 7",
  right: "M9 5l7 7-7 7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  rotR: "M20 12a8 8 0 11-3-6.2M20 4v5h-5",
  rotL: "M4 12a8 8 0 103-6.2M4 4v5h5",
  zoomIn: "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4M11 8v6M8 11h6",
  zoomOut: "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4M8 11h6",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  shrink: "M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5",
  fit: "M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4M9 9h6v6H9z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  plus: "M12 5v14M5 12h14",
  copy: "M9 9h11v11H9zM5 15V4h11",
  check: "M5 12l5 5 9-10",
  alert: "M12 3l10 18H2zM12 10v5M12 18h.01",
  battery: "M3 8h16v8H3zM21 11v2M6 11v2",
  cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
  wifiOff: "M3 3l18 18M8.5 16.4a5 5 0 017 0M5 12.9a10 10 0 015-2.7M19 12.9a10 10 0 00-4-2.5M2 8.8a15 15 0 014-2.8M22 8.8a15 15 0 00-8-3.6M12 20h.01",
  refresh: "M20 11a8 8 0 00-14.5-4M4 4v4h4M4 13a8 8 0 0014.5 4M20 20v-4h-4",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  eyeOff: "M3 3l18 18M10.6 6.1A9.8 9.8 0 0112 5c6 0 10 7 10 7a17 17 0 01-3.2 3.9M6.6 6.6A17 17 0 002 12s4 7 10 7a9.6 9.6 0 004.4-1M9.9 9.9a3 3 0 004.2 4.2",
  ext: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  queue: "M3 6h12M3 12h12M3 18h8M17 15v5M17 15l4-1v4",
  logout: "M9 4H4v16h5M16 8l4 4-4 4M20 12H9",
  menu: "M4 6h16M4 12h16M4 18h16",
  lock: "M6 11h12v9H6zM8 11V8a4 4 0 018 0v3",
  folder: "M3 6h6l2 2h10v11H3z",
  slideshow: "M4 5h16v11H4zM8 20h8M12 16v4",
  pdf: "M6 3h8l5 5v13H6zM14 3v5h5M8 16h2a1.5 1.5 0 000-3H8v5",
};

export function icon(name, cls = "") {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "ico " + cls);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const p = document.createElementNS(NS, "path");
  p.setAttribute("d", PATHS[name] || PATHS.file);
  svg.append(p);
  if (name === "play") svg.classList.add("fill");
  return svg;
}

export function iconButton(name, label, onClick, extra = {}) {
  const b = h("button", { type: "button", class: "icon-btn " + (extra.class || ""), "aria-label": label, title: label, ...extra.attrs, onclick: onClick }, icon(name));
  return b;
}

// ---- formatting ----
export function fmtBytes(n) {
  if (n === null || n === undefined || isNaN(n)) return "Unknown";
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return (n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)) + " " + u[i];
}
export function fmtDuration(s) {
  if (s === null || s === undefined || !isFinite(s)) return "";
  s = Math.max(0, Math.round(s));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${mm}:${String(ss).padStart(2, "0")}`;
}
export function fmtDate(epoch) {
  if (!epoch) return "Unknown";
  return new Date(epoch * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
export function fmtDateTime(epoch) {
  if (!epoch) return "Unknown";
  return new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
export function fmtUptime(sec) {
  if (sec === null || sec === undefined) return "Unknown";
  const d = Math.floor(sec / 86400), hh = Math.floor((sec % 86400) / 3600), mm = Math.floor((sec % 3600) / 60);
  if (d) return `${d}d ${hh}h ${mm}m`;
  if (hh) return `${hh}h ${mm}m`;
  return `${mm}m ${Math.floor(sec % 60)}s`;
}
export function fmtRelative(epoch) {
  if (!epoch) return "never";
  const diff = Math.round(Date.now() / 1000 - epoch);
  if (diff < 45) return "just now";
  if (diff < 3600) return Math.round(diff / 60) + " min ago";
  if (diff < 86400) return Math.round(diff / 3600) + " h ago";
  return fmtDate(epoch);
}
export function fmtCountdown(epoch) {
  const left = Math.round(epoch - Date.now() / 1000);
  if (left <= 0) return "Expired";
  if (left < 90) return left + " s left";
  if (left < 5400) return Math.round(left / 60) + " min left";
  return (left / 3600).toFixed(1) + " h left";
}
export const kindIcon = (kind) => ({ video: "film", audio: "music", image: "image", document: "file" }[kind] || "file");

// ---- preferences (UI only; never secrets) ----
const PREF_KEY = "nexora.prefs";
const DEFAULT_PREFS = {
  light: false, motion: "auto", view: "grid", accent: "blue", resume: true, autoplayNext: true,
  slideshowSeconds: 4, volume: 0.9, pollSeconds: 30, shuffle: false, repeat: "off",
};
let prefs = { ...DEFAULT_PREFS };
try { Object.assign(prefs, JSON.parse(localStorage.getItem(PREF_KEY) || "{}")); } catch (_) { /* ignore */ }
export function getPref(k) { return prefs[k]; }
export function setPref(k, v) {
  prefs[k] = v;
  try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch (_) { /* storage may be blocked */ }
  applyPrefs();
}
export function applyPrefs() {
  const r = document.documentElement;
  r.dataset.light = prefs.light ? "1" : "0";
  r.dataset.motion = prefs.motion === "on" ? "reduced" : prefs.motion === "off" ? "full" : "auto";
  r.dataset.accent = prefs.accent;
}
export function motionReduced() {
  if (prefs.motion === "on") return true;
  if (prefs.motion === "off") return false;
  return window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
}
export const lightweight = () => !!prefs.light;

// ---- announcements, toasts ----
export function announce(msg) {
  const el = document.getElementById("sr-status");
  if (!el) return;
  el.textContent = "";
  setTimeout(() => { el.textContent = msg; }, 30);
}
export function toast(message, type = "info", opts = {}) {
  const root = document.getElementById("toasts");
  const t = h("div", { class: "toast " + type, role: type === "error" ? "alert" : "status" }, h("span", { class: "grow" }, message));
  if (opts.action) t.append(h("button", { class: "btn btn-sm", type: "button", onclick: () => { opts.action.run(); t.remove(); } }, opts.action.label));
  root.append(t);
  announce(message);
  setTimeout(() => t.remove(), opts.ms || (type === "error" ? 7000 : 4000));
  return t;
}

// ---- state blocks ----
export function stateBlock({ kind = "empty", title, message, actions = [] }) {
  const ic = { loading: "refresh", empty: "folder", error: "alert", unavailable: "lock" }[kind] || "info";
  const box = h("div", { class: "state " + (kind === "error" ? "error" : ""), role: kind === "error" ? "alert" : "status" });
  box.append(icon(ic), h("h3", null, title));
  if (message) box.append(h("p", null, message));
  if (actions.length) box.append(h("div", { class: "row" }, actions));
  return box;
}
export function loadingBlock(count = 6) {
  const g = h("div", { class: "grid", "aria-busy": "true", "aria-label": "Loading" });
  for (let i = 0; i < count; i++) g.append(h("div", { class: "skeleton" }));
  return g;
}
export function button(label, onClick, opts = {}) {
  return h("button", { type: "button", class: "btn " + (opts.class || ""), disabled: opts.disabled, onclick: onClick, ...opts.attrs }, opts.icon ? icon(opts.icon, "sm") : null, label);
}

/** Run an async action with a busy state on a button. */
export async function withBusy(btn, fn) {
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  const sp = h("span", { class: "spinner" });
  btn.prepend(sp);
  try { return await fn(); } finally { sp.remove(); btn.disabled = false; btn.removeAttribute("aria-busy"); }
}

// ---- sheets / modals with focus management ----
export function openSheet(title, content, { onClose, wide } = {}) {
  const root = document.getElementById("overlay-root");
  const prevFocus = document.activeElement;
  const scrim = h("div", { class: "scrim" });
  const titleId = "sheet-" + Math.random().toString(36).slice(2, 8);
  const closeBtn = iconButton("x", "Close", () => close());
  const sheet = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, style: wide ? { width: "min(720px, 100%)" } : null },
    h("header", null, h("h3", { id: titleId }, title), closeBtn), content);
  scrim.append(sheet);
  root.append(scrim);
  document.body.style.setProperty("overflow", "hidden");
  const focusables = () => $$("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])", sheet).filter((e) => !e.disabled && e.offsetParent !== null);
  function key(e) {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    else if (e.key === "Tab") {
      const f = focusables();
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }
  scrim.addEventListener("keydown", key);
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    scrim.remove();
    if (!$(".scrim", root)) document.body.style.removeProperty("overflow");
    if (prevFocus && prevFocus.focus) prevFocus.focus();
    if (onClose) onClose();
  }
  setTimeout(() => { const f = focusables(); (f.find((x) => x !== closeBtn) || closeBtn).focus(); }, 30);
  return { close, sheet };
}

export function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const ta = h("textarea", { readonly: true, style: { position: "fixed", opacity: "0" } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { document.execCommand("copy") ? resolve() : reject(new Error("copy failed")); } catch (e) { reject(e); } finally { ta.remove(); }
  });
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
