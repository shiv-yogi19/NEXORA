// NEXORA application shell: intro, login, router, navigation, offline handling. Created By Shiv Yogi.
import { APP_VERSION, isConfigured } from "./config.js";
import { conn, onConnection, onSessionExpired, checkNow, get, probeHealth, setStatus } from "./api.js";
import { checkSession, initLogin, logout } from "./auth.js";
import { $, $$, h, icon, iconButton, applyPrefs, getPref, motionReduced, openSheet, announce, toast, fmtDateTime, stateBlock, clear } from "./ui.js";
import { createGame } from "./offline-game.js";
import { renderHome } from "./dashboard.js";
import * as lib from "./library.js";
import { renderWatch, renderPlaylists, renderPlaylist, initMiniPlayer, stopAudio } from "./players.js";
import { renderUploads } from "./uploads.js";
import { renderShares } from "./shares.js";
import { renderServer, renderStorage } from "./server-monitor.js";
import { renderSettings, renderActivity, renderAbout } from "./settings.js";

applyPrefs();

const NAV = [
  { id: "home", label: "Home", icon: "home", mobile: true },
  { id: "movies", label: "Movies", icon: "film", mobile: true },
  { id: "music", label: "Music", icon: "music", mobile: true },
  { id: "photos", label: "Photos", icon: "image", mobile: true },
  { id: "documents", label: "Documents", icon: "file" },
  { id: "uploads", label: "Uploads", icon: "upload" },
  { id: "downloads", label: "Downloads", icon: "download" },
  { sep: true },
  { id: "favorites", label: "Favorites", icon: "star" },
  { id: "watchlist", label: "Watchlist", icon: "bookmark" },
  { id: "recent", label: "Recent", icon: "clock" },
  { id: "shares", label: "Temporary Share", icon: "share" },
  { sep: true },
  { id: "storage", label: "Storage", icon: "drive" },
  { id: "server", label: "Mobile Server", icon: "server" },
  { id: "activity", label: "Activity", icon: "activity" },
  { sep: true },
  { id: "settings", label: "Settings", icon: "sliders" },
  { id: "about", label: "About NEXORA", icon: "info" },
];
const TITLES = Object.fromEntries(NAV.filter((n) => n.id).map((n) => [n.id, n.label]));
Object.assign(TITLES, { watch: "Now playing", search: "Search", playlists: "Playlists" });

const VIEWS = {
  home: renderHome,
  movies: (c) => lib.renderCategory(c, "movies"),
  music: (c) => (c.args[0] === "playlists" ? renderPlaylists(c) : c.args[0] === "playlist" ? renderPlaylist(c) : lib.renderCategory(c, "music")),
  photos: (c) => lib.renderCategory(c, "photos"),
  documents: (c) => lib.renderCategory(c, "documents"),
  downloads: (c) => lib.renderCategory(c, "downloads"),
  favorites: (c) => lib.renderCollection(c, "favorites"),
  watchlist: (c) => lib.renderCollection(c, "watchlist"),
  recent: (c) => lib.renderCollection(c, "recent"),
  search: lib.renderSearch,
  watch: renderWatch,
  uploads: renderUploads,
  shares: renderShares,
  storage: renderStorage,
  server: renderServer,
  activity: renderActivity,
  settings: renderSettings,
  about: renderAbout,
};

const state = { screen: "intro", cleanup: null, renderId: 0, ctl: null, pollTimer: 0, poll: null, game: null, wasApp: false, loginUi: null };
export const shell = { navigate, rerender: () => renderRoute(), setPoll: (fn) => { state.poll = fn; }, restartPolling: () => startPolling(), sessionLost };

function show(screen) {
  state.screen = screen;
  $("#login-screen").hidden = screen !== "login";
  $("#app").hidden = screen !== "app";
  if (screen !== "app") $("#miniplayer").hidden = true;
}

// ---------------- intro ----------------
function runIntro() {
  return new Promise((resolve) => {
    const intro = $("#intro");
    intro.hidden = false;
    const reduced = motionReduced();
    const timers = [];
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      timers.forEach(clearTimeout);
      intro.classList.add("done");
      document.removeEventListener("keydown", onKey);
      setTimeout(() => { intro.hidden = true; }, 650);
      resolve();
    };
    const onKey = (e) => { if (e.key === "Escape") finish(); };
    document.addEventListener("keydown", onKey);
    $("#intro-skip").addEventListener("click", finish);
    $("#intro-skip").focus({ preventScroll: true });
    const t = reduced ? [30, 1100, 2000] : [60, 2500, 4200];
    timers.push(setTimeout(() => intro.classList.add("p1"), t[0]));
    timers.push(setTimeout(() => { intro.classList.remove("p1"); intro.classList.add("p2"); }, t[1]));
    timers.push(setTimeout(finish, t[2]));
  });
}

// ---------------- navigation ----------------
function buildNav() {
  const side = clear($("#side-nav"));
  for (const n of NAV) {
    if (n.sep) { side.append(h("div", { class: "nav-sep", role: "separator" })); continue; }
    side.append(h("a", { class: "nav-link", href: "#/" + n.id, dataset: { nav: n.id }, title: n.label }, icon(n.icon), h("span", { class: "nav-label" }, n.label)));
  }
  const bottom = clear($("#bottomnav"));
  for (const n of NAV.filter((x) => x.mobile)) {
    bottom.append(h("a", { href: "#/" + n.id, dataset: { nav: n.id } }, icon(n.icon), h("span", null, n.label)));
  }
  bottom.append(h("button", { type: "button", id: "more-btn", "aria-haspopup": "dialog", onclick: openMore }, icon("menu"), h("span", null, "More")));
}
function openMore() {
  const menu = h("nav", { class: "menu", "aria-label": "More" });
  let group = [];
  const flush = () => { if (group.length) { menu.append(...group); group = []; } };
  const sheet = openSheet("More", menu);
  for (const n of NAV.filter((x) => !x.mobile)) {
    if (n.sep) { flush(); menu.append(h("div", { class: "nav-sep", role: "separator" })); continue; }
    group.push(h("a", { href: "#/" + n.id, onclick: () => sheet.close() }, icon(n.icon), n.label));
  }
  flush();
  menu.append(h("div", { class: "nav-sep", role: "separator" }), h("button", { type: "button", onclick: () => { sheet.close(); doLogout(); } }, icon("logout"), "Log out"));
}
function parseHash() {
  const raw = (location.hash || "#/home").replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch (_) { return p; } });
  return { name: parts[0] || "home", args: parts.slice(1) };
}
export function navigate(hash) { if (location.hash === hash) renderRoute(); else location.hash = hash; }

async function renderRoute() {
  if (state.screen !== "app") return;
  const { name, args } = parseHash();
  const view = VIEWS[name] || VIEWS.home;
  state.renderId++;
  const id = state.renderId;
  if (state.ctl) state.ctl.abort();
  if (state.cleanup) { try { state.cleanup(); } catch (e) { console.error(e); } state.cleanup = null; }
  state.poll = null;
  state.ctl = new AbortController();
  const main = clear($("#main"));
  const navId = name === "watch" ? "movies" : name === "playlists" ? "music" : name;
  for (const a of $$("[data-nav]")) { if (a.dataset.nav === navId) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }
  const title = TITLES[name] || "NEXORA";
  $("#toolbar-title").textContent = title; $("#mobile-title").textContent = title;
  document.title = title + " - NEXORA";
  const ctx = { main, args, signal: state.ctl.signal, isCurrent: () => id === state.renderId, navigate, shell, setTitle: (t) => { $("#toolbar-title").textContent = t; $("#mobile-title").textContent = t; document.title = t + " - NEXORA"; } };
  try {
    const cleanup = await view(ctx);
    if (typeof cleanup === "function") { if (ctx.isCurrent()) state.cleanup = cleanup; else cleanup(); }
  } catch (err) {
    if (!ctx.isCurrent() || (err && err.name === "AbortError")) return;
    console.error(err);
    clear(main).append(stateBlock({ kind: "error", title: "This page could not load", message: err.message || "Something went wrong.", actions: [h("button", { class: "btn", type: "button", onclick: () => renderRoute() }, "Try again")] }));
  }
  if (ctx.isCurrent()) { window.scrollTo(0, 0); if (!$("#overlay-root").firstChild) main.focus({ preventScroll: true }); announce(title); }
}
window.addEventListener("hashchange", () => { if (state.screen === "app") renderRoute(); });

// ---------------- connection status ----------------
const LABELS = { online: "Online", offline: "Offline", connecting: "Connecting", reconnecting: "Reconnecting", degraded: "Degraded" };
function renderConnection() {
  for (const el of ["#side-status", "#tool-status"]) { const p = $(el); p.dataset.state = conn.status; p.textContent = LABELS[conn.status]; }
  $("#mobile-status").dataset.state = conn.status;
  $("#mobile-status").setAttribute("aria-label", "Server " + LABELS[conn.status].toLowerCase());
  const banner = $("#banner");
  if (state.screen === "app" && conn.status === "degraded") {
    banner.hidden = false; banner.className = "banner";
    const why = { origin: "The server is reachable but does not allow this website address.", server: "The server answered but reports a problem.", request: "A request failed or timed out, but the server answers health checks." }[conn.reason] || "The connection is unstable.";
    clear(banner).append(h("span", { class: "grow" }, why), h("button", { class: "btn btn-sm", type: "button", onclick: () => checkNow({ manual: true }) }, "Check again"));
  } else banner.hidden = true;
}

function offlineCause() {
  if (!isConfigured()) return "This website has not been pointed at a server yet. Set API_BASE in js/config.js (see the README).";
  if (conn.reason === "origin") return "The server is running but does not allow this website address. Check allowed_origins in the server's private config.";
  return "The browser could not reach the server. Besides a stopped server, the tunnel, your network connection, DNS or TLS could be the cause.";
}
function showOffline() {
  const el = $("#offline-screen");
  el.hidden = false;
  $("#offline-badge").textContent = conn.status === "reconnecting" ? "Reconnecting" : "Offline";
  $("#offline-cause").textContent = offlineCause();
  $("#offline-last").textContent = conn.lastSuccess ? "Last successful connection: " + fmtDateTime(conn.lastSuccess) : "No successful connection has been recorded on this device.";
  if (conn.gaveUp) $("#offline-last").textContent += ". Automatic retries have stopped; tap Retry Connection when you are ready.";
  if (!state.game) { $("#offline-panel").hidden = false; $("#game-panel").hidden = true; }
}
function hideOffline() { endGame(); $("#offline-screen").hidden = true; }
function endGame() { if (state.game) { state.game.destroy(); state.game = null; } $("#game-panel").hidden = true; $("#offline-panel").hidden = false; }
function startGame() {
  $("#offline-screen").hidden = false;
  $("#offline-panel").hidden = true; $("#game-panel").hidden = false;
  if (state.game) state.game.destroy();
  state.game = createGame($("#game-mount"), { reducedMotion: motionReduced() || getPref("light") });
  const sound = $("#game-sound");
  sound.textContent = "Sound off"; sound.setAttribute("aria-pressed", "false");
  state.game.focusStart();
}
async function retryConnection(btn) {
  btn.disabled = true; $(".spinner", btn).hidden = false; $(".btn-label", btn).textContent = "Checking";
  const ok = await checkNow({ manual: true });
  btn.disabled = false; $(".spinner", btn).hidden = true; $(".btn-label", btn).textContent = "Retry Connection";
  if (!ok) { showOffline(); announce("Still offline."); }
}
$("#offline-retry").addEventListener("click", (e) => retryConnection(e.currentTarget));
$("#offline-play").addEventListener("click", startGame);
$("#game-back").addEventListener("click", () => {
  endGame();
  if (conn.status === "online") hideOffline();
  else if (state.screen === "login") { $("#offline-screen").hidden = true; }
});
$("#game-sound").addEventListener("click", (e) => {
  const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
  e.currentTarget.setAttribute("aria-pressed", String(on)); e.currentTarget.textContent = on ? "Sound on" : "Sound off";
  if (state.game) state.game.setSound(on);
});

let recovering = false;
onConnection(async () => {
  renderConnection();
  if (conn.status === "offline" || (conn.status === "reconnecting" && !$("#offline-screen").hidden)) {
    if (state.screen === "app") { stopPolling(); showOffline(); state.wasApp = true; }
    else if (state.screen === "login" && state.loginUi) state.loginUi.setOffline(true);
  } else if (conn.status === "online" && !$("#offline-screen").hidden && !recovering) {
    // The server is back: return to the library without reloading the page.
    recovering = true;
    try {
      const sess = await checkSession().catch(() => null);
      hideOffline();
      if (sess && sess.authenticated) { if (state.screen !== "app") enterApp(); else { startPolling(); renderRoute(); } toast("Reconnected to your server.", "ok"); }
      else { showLogin("Reconnected. Please log in again."); }
    } finally { recovering = false; }
  }
});

// ---------------- polling (paused while the tab is hidden) ----------------
function startPolling() {
  stopPolling();
  const every = Math.max(15, Number(getPref("pollSeconds")) || 30) * 1000;
  state.pollTimer = setInterval(async () => {
    if (document.hidden || state.screen !== "app" || conn.status === "offline") return;
    try {
      if (state.poll) await state.poll();
      else { const s = await get("/auth/session", { quiet: false, timeout: 8000 }); if (!s.authenticated) sessionLost(); }
    } catch (_) { /* failures are reported through the connection state */ }
  }, every);
}
function stopPolling() { clearInterval(state.pollTimer); }
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.screen === "app" && conn.status === "online") get("/auth/session", { timeout: 8000 }).then((s) => { if (!s.authenticated) sessionLost(); }).catch(() => {});
});

// ---------------- login / logout ----------------
function showLogin(message) {
  stopPolling();
  if (state.cleanup) { try { state.cleanup(); } catch (_) { /* ignore */ } state.cleanup = null; }
  stopAudio();
  show("login");
  $("#offline-screen").hidden = true;
  const msg = $("#login-msg");
  msg.className = "form-msg warn"; msg.textContent = message || "";
  if (message) announce(message);
  state.loginUi && state.loginUi.focus();
}
function sessionLost() {
  if (state.screen === "app") showLogin("Your session ended. Please log in again.");
}
async function doLogout() {
  await logout();
  showLogin("You have been logged out.");
}
onSessionExpired(sessionLost);

function enterApp() {
  show("app");
  $("#app-version").textContent = "v" + APP_VERSION;
  renderConnection();
  startPolling();
  if (!location.hash || location.hash === "#") location.hash = "#/home";
  renderRoute();
}

// ---------------- boot ----------------
async function boot() {
  buildNav();
  $("#more-btn");
  $("#side-toggle").append(icon("menu"));
  $("#mobile-search").append(icon("search"));
  $("#tool-upload").prepend(icon("upload", "sm"));
  $("#side-toggle").addEventListener("click", () => {
    const app = $("#app"); const open = app.classList.toggle("side-open");
    $("#side-toggle").setAttribute("aria-expanded", String(open));
  });
  $("#side-nav").addEventListener("click", () => { $("#app").classList.remove("side-open"); $("#side-toggle").setAttribute("aria-expanded", "false"); });
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#search-input").value.trim();
    if (q) navigate("#/search/" + encodeURIComponent(q));
  });
  $("#mobile-search").addEventListener("click", () => {
    const input = h("input", { type: "search", placeholder: "Search your library", maxlength: "100", "aria-label": "Search your library" });
    const form = h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); const q = input.value.trim(); if (q) { sheet.close(); navigate("#/search/" + encodeURIComponent(q)); } } }, h("div", { class: "grow" }, input), h("button", { class: "btn btn-primary", type: "submit" }, "Search"));
    const sheet = openSheet("Search", form);
  });
  state.loginUi = initLogin({ onSuccess: () => { markLoggedIn(); }, onPlayGame: () => startGame() });
  initMiniPlayer();
  loadOptionalFonts();
  registerServiceWorker();

  // Start checking the session while the intro plays, then continue when both are done.
  let sessionResult = { authenticated: false, offline: false };
  const sessionP = (async () => {
    if (!isConfigured()) { setStatus("offline", "unconfigured"); sessionResult = { authenticated: false, offline: true }; return; }
    try { sessionResult = await checkSession(); } catch (e) {
      const p = await probeHealth();
      setStatus(p.reachable ? "degraded" : "offline", p.reachable ? (p.originAllowed ? "server" : "origin") : p.reason);
      sessionResult = { authenticated: false, offline: true };
    }
  })();
  await Promise.all([runIntro(), sessionP]);
  if (sessionResult.authenticated) enterApp();
  else { show("login"); state.loginUi.focus(); if (sessionResult.offline) state.loginUi.setOffline(true); }
}
function markLoggedIn() { enterApp(); }

function loadOptionalFonts() {
  // Optional visual enhancement only. The interface works without it.
  const link = document.createElement("link");
  link.rel = "stylesheet"; link.href = "https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&display=swap";
  link.referrerPolicy = "no-referrer";
  document.head.append(link);
}
function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (location.protocol !== "https:" && location.hostname !== "localhost") return;
  navigator.serviceWorker.register("service-worker.js").catch(() => { /* optional */ });
}

boot().catch((e) => { console.error(e); document.body.prepend(h("p", { class: "noscript" }, "NEXORA could not start: " + e.message)); show("login"); });
