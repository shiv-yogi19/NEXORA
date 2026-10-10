// NEXORA service worker: caches only the public site shell so the app screen and offline game can open without the phone.
// It never touches the API or media: it ignores every cross-origin request, so no private data is ever cached.
// Created By Shiv Yogi.
const CACHE = "nexora-shell-v1";
const SHELL = ["./", "index.html", "css/style.css", "css/responsive.css", "assets/logo.svg", "assets/favicon.svg",
  "js/config.js", "js/ui.js", "js/api.js", "js/app.js", "js/auth.js", "js/offline-game.js", "js/actions.js", "js/shares.js",
  "js/players.js", "js/library.js", "js/dashboard.js", "js/uploads.js", "js/server-monitor.js", "js/settings.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // API and media live on another origin: never intercepted
  e.respondWith(
    fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {}); }
      return res;
    }).catch(() => caches.match(req).then((m) => m || caches.match("index.html")))
  );
});
