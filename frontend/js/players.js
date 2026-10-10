// NEXORA players: audio engine, mini-player, expanded player, playlists, and the video watch page.
// Created By Shiv Yogi.
import { get, post, del, fileUrl, ApiError } from "./api.js";
import { h, $, icon, iconButton, clear, stateBlock, loadingBlock, toast, announce, fmtDuration, fmtBytes, fmtDate, getPref, setPref, motionReduced, lightweight, openSheet, withBusy, kindIcon } from "./ui.js";
import { toggleFavorite, toggleWatchlist, downloadFile, errText } from "./actions.js";
import { openShareSheet } from "./shares.js";

// =====================================================================
// Audio engine (one shared <audio> element, queue, shuffle, repeat)
// =====================================================================
const eng = {
  audio: null, original: [], queue: [], index: -1, shuffle: !!getPref("shuffle"), repeat: getPref("repeat") || "off",
  listeners: new Set(), ctx: null, analyser: null, source: null, cors: true, lastReport: 0, errorsInRow: 0, seekOnLoad: 0,
};
const emit = (what) => { for (const fn of eng.listeners) { try { fn(what, eng); } catch (e) { console.error(e); } } };
export function onEngine(fn) { eng.listeners.add(fn); return () => eng.listeners.delete(fn); }
export const current = () => (eng.index >= 0 ? eng.queue[eng.index] : null);
export const engineState = () => ({ item: current(), playing: !!eng.audio && !eng.audio.paused, queue: eng.queue, index: eng.index, shuffle: eng.shuffle, repeat: eng.repeat, time: eng.audio ? eng.audio.currentTime : 0, duration: eng.audio && isFinite(eng.audio.duration) ? eng.audio.duration : 0 });

function ensureAudio() {
  if (eng.audio) return eng.audio;
  const a = new Audio();
  a.preload = "metadata";
  a.volume = Number(getPref("volume"));
  if (isNaN(a.volume)) a.volume = 0.9;
  a.addEventListener("timeupdate", () => { emit("time"); const t = Date.now(); if (!a.paused && t - eng.lastReport > 15000) { eng.lastReport = t; report(false); } });
  a.addEventListener("play", () => { emit("state"); setSession(); });
  a.addEventListener("pause", () => { emit("state"); report(false); });
  a.addEventListener("loadedmetadata", () => {
    if (eng.seekOnLoad > 0 && eng.seekOnLoad < (a.duration || 0) - 5) { a.currentTime = eng.seekOnLoad; }
    eng.seekOnLoad = 0; emit("time");
  });
  a.addEventListener("playing", () => { eng.errorsInRow = 0; hookAnalyser(); });
  a.addEventListener("ended", () => { report(true); step(1, true); });
  a.addEventListener("error", onAudioError);
  eng.audio = a;
  return a;
}

function onAudioError() {
  const it = current();
  if (!it) return;
  if (eng.cors && !eng.source && eng.audio.crossOrigin) { // retry once without CORS (no visualizer, same sound)
    eng.cors = false; eng.audio.removeAttribute("crossorigin"); eng.audio.src = fileUrl(it.id); eng.audio.play().catch(() => {}); return;
  }
  eng.errorsInRow++;
  const code = eng.audio.error ? eng.audio.error.code : 0;
  toast(code === 4 ? `This browser cannot play "${it.name}" (.${it.ext}). Download it to use another app.` : `Could not play "${it.name}". Check your connection to the server.`, "error");
  emit("state");
  if (eng.errorsInRow < Math.min(3, eng.queue.length) && eng.index < eng.queue.length - 1) step(1, true);
}

function load(item, resume = true) {
  const a = ensureAudio();
  eng.cors = true;
  a.crossOrigin = "use-credentials";
  eng.seekOnLoad = 0;
  if (resume && getPref("resume") && item.progress && !item.progress.completed && (item.duration || 0) > 1200 && item.progress.position > 10) eng.seekOnLoad = item.progress.position;
  a.src = fileUrl(item.id);
  emit("track"); emit("queue");
  return a.play().catch((e) => { if (e && e.name === "NotAllowedError") toast("Press play to start the audio.", "info"); });
}
function report(done) {
  const it = current(), a = eng.audio;
  if (!it || !a || !a.currentTime) return;
  const body = { file_id: it.id, position: Math.min(a.currentTime, 1e7) };
  if (isFinite(a.duration) && a.duration > 0) body.duration = a.duration;
  if (done) body.completed = true;
  post("/playback/progress", body, { quiet: true, timeout: 8000 }).then(() => { it.progress = { position: done ? 0 : body.position, duration: body.duration, completed: !!done }; if (body.duration) it.duration = body.duration; }).catch(() => {});
}
function step(dir, auto) {
  if (!eng.queue.length) return;
  if (auto && eng.repeat === "one") { eng.audio.currentTime = 0; eng.audio.play().catch(() => {}); return; }
  let i = eng.index + dir;
  if (i >= eng.queue.length) { if (eng.repeat === "all") i = 0; else { eng.audio.pause(); emit("state"); return; } }
  if (i < 0) i = eng.repeat === "all" ? eng.queue.length - 1 : 0;
  eng.index = i;
  load(eng.queue[i], false);
}
function shuffled(arr) { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }

export function playQueue(items, start = 0) {
  const tracks = items.filter((i) => i.kind === "audio");
  if (!tracks.length) return;
  const first = items[start] && items[start].kind === "audio" ? items[start] : tracks[0];
  eng.original = tracks.slice();
  eng.queue = eng.shuffle ? [first, ...shuffled(tracks.filter((t) => t !== first))] : tracks.slice();
  eng.index = eng.queue.indexOf(first);
  stopVideo();
  load(first);
}
export function enqueue(item, playNext = false) {
  if (item.kind !== "audio") return;
  if (eng.index < 0) { playQueue([item], 0); return; }
  if (eng.queue.some((q) => q.id === item.id)) { toast("Already in the queue.", "info"); return; }
  if (playNext) eng.queue.splice(eng.index + 1, 0, item); else eng.queue.push(item);
  eng.original.push(item);
  emit("queue");
  toast(playNext ? "Will play next." : "Added to the queue.", "ok");
}
export function removeFromQueue(i) {
  if (i === eng.index) return;
  const [gone] = eng.queue.splice(i, 1);
  eng.original = eng.original.filter((o) => o.id !== gone.id);
  if (i < eng.index) eng.index--;
  emit("queue");
}
export function playIndex(i) { if (i >= 0 && i < eng.queue.length) { eng.index = i; load(eng.queue[i], false); } }
export const next = () => step(1, false);
export function prev() { if (eng.audio && eng.audio.currentTime > 3) eng.audio.currentTime = 0; else step(-1, false); }
export function togglePlay() { const a = eng.audio; if (!a || !current()) return; if (a.paused) a.play().catch(() => {}); else a.pause(); }
export function seekTo(sec) { if (eng.audio && isFinite(eng.audio.duration)) eng.audio.currentTime = Math.max(0, Math.min(sec, eng.audio.duration)); }
export function setVolume(v) { ensureAudio().volume = v; setPref("volume", v); emit("volume"); }
export function toggleShuffle() {
  eng.shuffle = !eng.shuffle; setPref("shuffle", eng.shuffle);
  const cur = current();
  if (cur) {
    if (eng.shuffle) eng.queue = [cur, ...shuffled(eng.queue.filter((t) => t !== cur))]; else eng.queue = eng.original.slice();
    eng.index = Math.max(0, eng.queue.indexOf(cur));
  }
  emit("queue"); emit("state");
}
export function cycleRepeat() { eng.repeat = { off: "all", all: "one", one: "off" }[eng.repeat]; setPref("repeat", eng.repeat); emit("state"); }
export function stopAudio() {
  if (eng.audio) { report(false); eng.audio.pause(); eng.audio.removeAttribute("src"); eng.audio.load(); }
  eng.queue = []; eng.original = []; eng.index = -1; emit("track"); emit("queue"); emit("state");
}
export function pauseAudio() { if (eng.audio && !eng.audio.paused) eng.audio.pause(); }

function hookAnalyser() {
  // Only when the audio element passed a CORS check; otherwise routing it through Web Audio would silence it.
  if (eng.source || !eng.cors || !eng.audio || !eng.audio.crossOrigin) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    eng.ctx = eng.ctx || new AC();
    eng.source = eng.ctx.createMediaElementSource(eng.audio);
    eng.analyser = eng.ctx.createAnalyser();
    eng.analyser.fftSize = 128; eng.analyser.smoothingTimeConstant = 0.8;
    eng.source.connect(eng.analyser); eng.analyser.connect(eng.ctx.destination);
  } catch (_) { eng.source = null; eng.analyser = null; }
  if (eng.ctx && eng.ctx.state === "suspended") eng.ctx.resume().catch(() => {});
}

function setSession() {
  if (!("mediaSession" in navigator)) return;
  const it = current();
  if (!it) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({ title: it.name.replace(/\.[^.]+$/, ""), artist: "NEXORA", album: it.category });
    const set = (a, f) => { try { navigator.mediaSession.setActionHandler(a, f); } catch (_) { /* unsupported */ } };
    set("play", togglePlay); set("pause", togglePlay); set("previoustrack", prev); set("nexttrack", next);
    set("seekto", (d) => seekTo(d.seekTime));
  } catch (_) { /* optional */ }
}

// =====================================================================
// Mini-player and expanded player
// =====================================================================
const title = (it) => it.name.replace(/\.[^.]+$/, "");
function art(it, cls = "thumb") {
  const box = h("span", { class: cls }, icon("music"));
  if (it && it.thumbnail) box.append(h("img", { src: fileUrl(it.id, "thumbnail"), alt: "", loading: "lazy", onerror: (e) => e.currentTarget.remove() }));
  return box;
}

export function initMiniPlayer() {
  const root = $("#miniplayer");
  const seek = h("input", { type: "range", min: "0", max: "1000", value: "0", "aria-label": "Seek", step: "1" });
  const tCur = h("span", null, "0:00"), tDur = h("span", null, "0:00");
  const info = h("button", { type: "button", class: "mini-info", "aria-label": "Open full player", onclick: () => openExpanded() });
  const play = h("button", { type: "button", class: "icon-btn playbtn", "aria-label": "Play", onclick: togglePlay });
  const vol = h("input", { type: "range", min: "0", max: "1", step: "0.02", "aria-label": "Volume", value: String(getPref("volume")) });
  vol.addEventListener("input", () => setVolume(Number(vol.value)));
  let dragging = false;
  seek.addEventListener("input", () => { dragging = true; const s = engineState(); if (s.duration) tCur.textContent = fmtDuration((seek.value / 1000) * s.duration); });
  seek.addEventListener("change", () => { const s = engineState(); seekTo((seek.value / 1000) * s.duration); dragging = false; });
  const ctl = h("div", { class: "mini-ctl" }, iconButton("prev", "Previous track", prev), play, iconButton("next", "Next track", next));
  const right = h("div", { class: "mini-right" }, h("span", { class: "sr-only" }, "Volume"), vol, iconButton("queue", "Open queue", () => openExpanded(true)), iconButton("expand", "Open full player", () => openExpanded()));
  root.append(info, ctl, right, h("div", { class: "mini-prog" }, tCur, seek, tDur));
  function paint(what) {
    const it = current();
    root.hidden = !it || $("#app").hidden;
    if (!it) return;
    if (what === "track" || !info.firstChild) {
      clear(info).append(art(it), h("span", { class: "rowtext" }, h("b", null, title(it)), h("span", null, it.category + (it.folder ? ", " + it.folder : ""))));
    }
    const s = engineState();
    if (what === "state" || what === "track" || what === "init") { play.replaceChildren(icon(s.playing ? "pause" : "play")); play.setAttribute("aria-label", s.playing ? "Pause" : "Play"); }
    if (!dragging) { seek.value = s.duration ? String(Math.round((s.time / s.duration) * 1000)) : "0"; tCur.textContent = fmtDuration(s.time); }
    tDur.textContent = fmtDuration(s.duration);
  }
  onEngine(paint);
  window.addEventListener("hashchange", () => paint("state"));
  new MutationObserver(() => paint("state")).observe($("#app"), { attributes: true, attributeFilter: ["hidden"] });
}

let expandedEl = null;
export function openExpanded(showQueue = false) {
  if (expandedEl) return;
  const it0 = current();
  if (!it0) return;
  const prevFocus = document.activeElement;
  const root = document.getElementById("overlay-root");
  const artBox = h("div", { class: "exp-art" }, icon("music"));
  const nameEl = h("h2", { class: "exp-title" });
  const subEl = h("p", { class: "muted" });
  const canvas = h("canvas", { class: "exp-viz", width: "420", height: "64", "aria-hidden": "true" });
  const vizNote = h("p", { class: "muted", style: { fontSize: "12.5px" } });
  const seek = h("input", { type: "range", min: "0", max: "1000", value: "0", "aria-label": "Seek" });
  const tCur = h("span", null, "0:00"), tDur = h("span", { style: { textAlign: "right" } }, "0:00");
  const play = h("button", { type: "button", class: "icon-btn playbtn", style: { width: "64px", height: "64px" }, onclick: togglePlay });
  const shuffleB = h("button", { type: "button", class: "icon-btn", "aria-label": "Shuffle", "aria-pressed": "false", onclick: toggleShuffle }, icon("shuffle"));
  const repeatB = h("button", { type: "button", class: "icon-btn", "aria-label": "Repeat", onclick: cycleRepeat }, icon("repeat"));
  const repeatTxt = h("span", { class: "muted", style: { fontSize: "12px", minWidth: "42px" } });
  const vol = h("input", { type: "range", min: "0", max: "1", step: "0.02", value: String(getPref("volume")), "aria-label": "Volume", style: { maxWidth: "160px" } });
  vol.addEventListener("input", () => setVolume(Number(vol.value)));
  const queueEl = h("div", { class: "queue", role: "list", "aria-label": "Queue" });
  const favB = h("button", { type: "button", class: "btn btn-sm" });
  const side = h("div", { class: "exp-side" });
  const closeBtn = iconButton("x", "Close player", () => close());
  const wrap = h("div", { class: "expanded", role: "dialog", "aria-modal": "true", "aria-label": "Music player" },
    h("div", { class: "exp-top" }, h("span", { class: "muted" }, "Now playing"), closeBtn),
    h("div", { class: "exp-main" }, artBox, h("div", null, nameEl, subEl), canvas, vizNote,
      h("div", { class: "exp-seek" }, tCur, seek, tDur),
      h("div", { class: "exp-ctl" }, shuffleB, iconButton("prev", "Previous track", prev), play, iconButton("next", "Next track", next), repeatB, repeatTxt),
      h("div", { class: "row", style: { justifyContent: "center" } }, icon("volume", "sm"), vol)),
    side);
  side.append(h("div", { class: "row" }, favB,
    h("button", { class: "btn btn-sm", type: "button", onclick: () => { const it = current(); if (it) addToPlaylistSheet(it); } }, icon("plus", "sm"), "Add to playlist"),
    h("button", { class: "btn btn-sm", type: "button", onclick: () => { const it = current(); if (it) downloadFile(it); } }, icon("download", "sm"), "Download"),
    h("button", { class: "btn btn-sm", type: "button", onclick: () => { const it = current(); if (it) openShareSheet(it); } }, icon("share", "sm"), "Share")),
    h("h3", { id: "queue-h" }, "Queue"), queueEl);
  root.append(wrap);
  document.body.style.setProperty("overflow", "hidden");
  let dragging = false, raf = 0;
  seek.addEventListener("input", () => { dragging = true; });
  seek.addEventListener("change", () => { const s = engineState(); seekTo((seek.value / 1000) * s.duration); dragging = false; });

  function paint(what) {
    const s = engineState(), it = s.item;
    if (!it) { close(); return; }
    if (what === "track" || what === "init") {
      clear(artBox).append(icon("music")); if (it.thumbnail) artBox.append(h("img", { src: fileUrl(it.id, "thumbnail"), alt: "", onerror: (e) => e.currentTarget.remove() }));
      nameEl.textContent = title(it); subEl.textContent = it.category + (it.folder ? ", " + it.folder : "") + ", " + fmtBytes(it.size);
      favB.replaceChildren(icon("star", "sm"), it.favorite ? "Unfavorite" : "Favorite");
      favB.onclick = async () => { await toggleFavorite(it); favB.replaceChildren(icon("star", "sm"), it.favorite ? "Unfavorite" : "Favorite"); };
    }
    if (["state", "track", "init"].includes(what)) {
      play.replaceChildren(icon(s.playing ? "pause" : "play")); play.setAttribute("aria-label", s.playing ? "Pause" : "Play");
      shuffleB.setAttribute("aria-pressed", String(s.shuffle)); shuffleB.style.setProperty("color", s.shuffle ? "var(--cyan)" : "");
      repeatB.style.setProperty("color", s.repeat !== "off" ? "var(--cyan)" : ""); repeatB.setAttribute("aria-label", "Repeat: " + s.repeat);
      repeatTxt.textContent = s.repeat === "one" ? "Repeat one" : s.repeat === "all" ? "Repeat all" : "";
      startViz();
    }
    if (what === "queue" || what === "init" || what === "track") {
      clear(queueEl);
      s.queue.forEach((q, i) => queueEl.append(h("div", { class: "rowitem" + (i === s.index ? " playing" : ""), role: "listitem" },
        h("button", { type: "button", class: "rowmain", onclick: () => playIndex(i), "aria-current": i === s.index ? "true" : null }, art(q), h("span", { class: "rowtext" }, h("b", null, title(q)), h("span", null, q.category))),
        i === s.index ? null : iconButton("x", "Remove from queue", () => removeFromQueue(i), { class: "sm" }))));
    }
    if (!dragging) { seek.value = s.duration ? String(Math.round((s.time / s.duration) * 1000)) : "0"; tCur.textContent = fmtDuration(s.time); }
    tDur.textContent = fmtDuration(s.duration);
  }
  function startViz() {
    cancelAnimationFrame(raf);
    const s = engineState();
    const off = motionReduced() || lightweight();
    canvas.hidden = off;
    if (off) { vizNote.textContent = "Visualizer is off in Lightweight Mode or reduced motion."; return; }
    if (!eng.analyser) { vizNote.textContent = s.playing ? "Visualizer unavailable for this stream." : ""; canvas.hidden = !eng.analyser; return; }
    vizNote.textContent = "";
    if (!s.playing) return;
    const data = new Uint8Array(eng.analyser.frequencyBinCount), ctx = canvas.getContext("2d");
    let lastDraw = 0;
    const loop = (t) => {
      raf = requestAnimationFrame(loop);
      if (t - lastDraw < 40 || document.hidden) return; // about 25 fps keeps battery use low
      lastDraw = t;
      eng.analyser.getByteFrequencyData(data);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const bars = 32, w = canvas.width / bars;
      for (let i = 0; i < bars; i++) { // real spectrum values from the audio being played
        const v = data[Math.floor((i / bars) * data.length * 0.8)] / 255, hgt = Math.max(2, v * canvas.height);
        ctx.fillStyle = i % 2 ? "#6b9bff" : "#a074ff"; ctx.fillRect(i * w + 2, canvas.height - hgt, w - 4, hgt);
      }
    };
    raf = requestAnimationFrame(loop);
  }
  const off = onEngine(paint);
  function close() {
    cancelAnimationFrame(raf); off(); wrap.remove(); expandedEl = null;
    document.body.style.removeProperty("overflow"); document.removeEventListener("keydown", onKey);
    if (prevFocus && prevFocus.focus) prevFocus.focus();
  }
  const onKey = (e) => { if (e.key === "Escape" && !$(".scrim", root)) close(); };
  document.addEventListener("keydown", onKey);
  expandedEl = wrap;
  paint("init");
  (showQueue ? queueEl : closeBtn).scrollIntoView?.({ block: "nearest" });
  closeBtn.focus();
}

// =====================================================================
// Playlists
// =====================================================================
export async function addToPlaylistSheet(item) {
  const list = h("div", { class: "menu" });
  const name = h("input", { type: "text", maxlength: "80", placeholder: "New playlist name", "aria-label": "New playlist name" });
  const msg = h("p", { class: "form-msg", role: "alert" });
  const sheet = openSheet("Add to playlist", h("div", { style: { display: "grid", gap: "12px" } }, list, h("div", { class: "row" }, h("div", { class: "grow" }, name),
    h("button", { class: "btn", type: "button", onclick: async (e) => withBusy(e.currentTarget, async () => {
      try { const p = await post("/playlists", { name: name.value.trim() }); await post("/playlists/" + p.id + "/items", { file_id: item.id }); toast(`Added to "${p.name}".`, "ok"); sheet.close(); } catch (err) { msg.textContent = errText(err, "Could not create the playlist."); }
    }) }, "Create and add")), msg));
  try {
    const d = await get("/playlists");
    if (!d.playlists.length) list.append(h("p", { class: "muted" }, "No playlists yet. Name one below."));
    for (const p of d.playlists) list.append(h("button", { type: "button", onclick: async () => {
      try { await post("/playlists/" + p.id + "/items", { file_id: item.id }); toast(`Added to "${p.name}".`, "ok"); sheet.close(); } catch (err) { toast(errText(err, "Could not add the track."), "error"); }
    } }, icon("music"), p.name + " (" + p.track_count + ")"));
  } catch (e) { list.append(h("p", { class: "muted", role: "alert" }, errText(e, "Could not load playlists."))); }
}

export async function renderPlaylists(ctx) {
  const { main } = ctx;
  const name = h("input", { type: "text", maxlength: "80", placeholder: "Playlist name", "aria-label": "Playlist name" });
  const msg = h("p", { class: "form-msg", role: "alert" });
  const body = h("div");
  main.append(h("div", { class: "page-head" }, h("h2", null, "Playlists"), h("a", { class: "btn btn-ghost", href: "#/music" }, "Back to music")),
    h("form", { class: "toolrow", onsubmit: async (e) => {
      e.preventDefault(); msg.textContent = "";
      try { await post("/playlists", { name: name.value.trim() }); name.value = ""; load(); } catch (err) { msg.textContent = errText(err, "Could not create the playlist."); }
    } }, h("div", { class: "grow" }, name), h("button", { class: "btn btn-primary", type: "submit" }, icon("plus", "sm"), "Create playlist")), msg, body);
  async function load() {
    clear(body).append(loadingBlock(3));
    try {
      const d = await get("/playlists", { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      clear(body);
      if (!d.playlists.length) { body.append(stateBlock({ title: "No playlists yet", message: "Name a playlist above, then add tracks from the Music page with the track menu." })); return; }
      body.append(h("div", { class: "list" }, d.playlists.map((p) => h("a", { class: "rowitem", href: "#/music/playlist/" + p.id, style: { color: "inherit" } }, h("span", { class: "thumb" }, icon("queue")), h("span", { class: "rowtext grow" }, h("b", null, p.name), h("span", null, p.track_count + " track" + (p.track_count === 1 ? "" : "s"))), icon("right", "sm")))));
    } catch (e) { if (ctx.isCurrent()) clear(body).append(stateBlock({ kind: "error", title: "Could not load playlists", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: load }, "Try again")] })); }
  }
  await load();
}

export async function renderPlaylist(ctx) {
  const { main } = ctx, id = ctx.args[1];
  const body = h("div");
  main.append(body);
  async function load() {
    clear(body).append(loadingBlock(3));
    try {
      const p = await get("/playlists/" + encodeURIComponent(id), { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      ctx.setTitle(p.name);
      clear(body).append(h("div", { class: "page-head" }, h("a", { class: "btn btn-ghost", href: "#/music/playlists" }, "All playlists"), h("h2", { class: "grow" }, p.name), h("span", { class: "count" }, p.items.length + " track" + (p.items.length === 1 ? "" : "s")),
        h("button", { class: "btn btn-primary", type: "button", disabled: !p.items.length, onclick: () => playQueue(p.items, 0) }, icon("play", "sm"), "Play"),
        h("button", { class: "btn btn-danger", type: "button", onclick: async () => { if (!confirm(`Delete the playlist "${p.name}"? Your music files are not touched.`)) return; try { await del("/playlists/" + id); toast("Playlist deleted.", "ok"); location.hash = "#/music/playlists"; } catch (e) { toast(errText(e, "Could not delete."), "error"); } } }, "Delete playlist")));
      if (!p.items.length) { body.append(stateBlock({ title: "This playlist is empty", message: "Open the Music page and use a track's menu to add tracks.", actions: [h("a", { class: "btn", href: "#/music" }, "Go to Music")] })); return; }
      body.append(h("div", { class: "list" }, p.items.map((it, i) => h("div", { class: "rowitem" },
        h("button", { type: "button", class: "rowmain", onclick: () => playQueue(p.items, i) }, art(it), h("span", { class: "rowtext" }, h("b", null, title(it)), h("span", null, it.folder || it.category))),
        h("span", { class: "rowsize" }, fmtBytes(it.size)),
        iconButton("x", "Remove from playlist", async () => { try { await del("/playlists/" + id + "/items/" + it.id); load(); } catch (e) { toast(errText(e, "Could not remove."), "error"); } }, { class: "sm" })))));
    } catch (e) {
      if (!ctx.isCurrent()) return;
      clear(body).append(stateBlock({ kind: "error", title: e instanceof ApiError && e.status === 404 ? "Playlist not found" : "Could not load the playlist", message: errText(e, ""), actions: [h("a", { class: "btn", href: "#/music/playlists" }, "All playlists")] }));
    }
  }
  await load();
}

// =====================================================================
// Video watch page
// =====================================================================
let activeVideo = null;
function stopVideo() { if (activeVideo) { activeVideo(); activeVideo = null; } }

export async function renderWatch(ctx) {
  const { main } = ctx, id = ctx.args[0];
  pauseAudio();
  main.append(loadingBlock(1));
  let item;
  try { item = await get("/files/" + encodeURIComponent(id), { signal: ctx.signal }); } catch (e) {
    if (!ctx.isCurrent()) return;
    clear(main).append(stateBlock({ kind: "error", title: e instanceof ApiError && e.status === 404 ? "This file is no longer available" : "Could not open this video", message: e instanceof ApiError && e.status === 404 ? "It may have been moved or deleted on the phone. Rescan the library from Storage." : errText(e, ""), actions: [h("a", { class: "btn", href: "#/movies" }, "Back to Movies")] }));
    return;
  }
  if (!ctx.isCurrent()) return;
  if (item.kind !== "video") { location.replace("#/movies"); return; }
  ctx.setTitle(item.name);
  clear(main);

  const video = h("video", { controls: true, playsinline: true, preload: "metadata", "aria-label": item.name });
  const errBox = h("div", { class: "media-error", role: "alert", hidden: true });
  const resumeNote = h("div");
  let lastSent = 0, started = false;
  const send = (done) => {
    if (!video.currentTime) return;
    const body = { file_id: item.id, position: video.currentTime };
    if (isFinite(video.duration) && video.duration > 0) body.duration = video.duration;
    if (done) body.completed = true;
    fetchKeepalive(body);
  };
  video.addEventListener("loadedmetadata", () => {
    const p = item.progress;
    if (getPref("resume") && p && !p.completed && p.position > 10 && p.position < video.duration - 10) {
      video.currentTime = p.position;
      resumeNote.append(h("div", { class: "panel tight glass row", role: "status" }, h("span", { class: "grow" }, "Resumed at " + fmtDuration(p.position) + "."), h("button", { class: "btn btn-sm", type: "button", onclick: () => { video.currentTime = 0; resumeNote.replaceChildren(); } }, "Start over")));
    }
  });
  video.addEventListener("timeupdate", () => { const t = Date.now(); if (!video.paused && t - lastSent > 10000) { lastSent = t; send(false); } });
  video.addEventListener("pause", () => { if (started) send(false); });
  video.addEventListener("playing", () => { started = true; });
  video.addEventListener("ended", () => { send(true); if (getPref("autoplayNext")) playNext(); });
  video.addEventListener("error", () => {
    const code = video.error ? video.error.code : 0;
    errBox.hidden = false;
    errBox.textContent = code === 4 ? `Your browser cannot play .${item.ext} files here (${item.name}). Download the file and open it in a player app such as VLC.` :
      code === 2 ? "The connection to the server was interrupted. Check that the server and tunnel are running, then press play to try again." :
        code === 3 ? "This video could not be decoded. The file may be damaged or use a codec this browser does not support." : "This video could not be loaded.";
  });
  video.addEventListener("playing", () => { errBox.hidden = true; });
  video.crossOrigin = null;
  video.src = fileUrl(item.id);

  const favBtn = h("button", { class: "btn", type: "button" });
  const watchBtn = h("button", { class: "btn", type: "button" });
  const paintBtns = () => {
    favBtn.replaceChildren(icon("star", "sm"), item.favorite ? "Remove favorite" : "Favorite");
    watchBtn.replaceChildren(icon("bookmark", "sm"), item.watchlist ? "Remove from Watchlist" : "Add to Watchlist");
  };
  favBtn.onclick = async () => { await toggleFavorite(item); paintBtns(); };
  watchBtn.onclick = async () => { await toggleWatchlist(item); paintBtns(); };
  paintBtns();
  const more = h("div", { class: "list" });
  const info = h("div", { class: "watch-info" }, h("h2", null, item.name),
    h("div", { class: "card-meta" }, h("span", null, fmtBytes(item.size)), h("span", null, "Modified " + fmtDate(item.mtime)), h("span", null, "Duration " + (item.duration ? fmtDuration(item.duration) : "unknown until played")), h("span", null, item.category + (item.folder ? " / " + item.folder : ""))),
    resumeNote, errBox,
    h("div", { class: "row" }, favBtn, watchBtn,
      h("button", { class: "btn", type: "button", onclick: () => downloadFile(item) }, icon("download", "sm"), "Download"),
      h("button", { class: "btn", type: "button", onclick: () => openShareSheet(item) }, icon("share", "sm"), "Share")));
  main.append(h("div", { class: "watch" }, h("div", null, h("div", { class: "videobox" }, video), info), h("aside", { "aria-label": "More videos" }, h("h3", { style: { marginBottom: "10px" } }, "More videos"), more)));

  let siblings = [];
  async function playNext() {
    const i = siblings.findIndex((s) => s.id === item.id);
    const nxt = i >= 0 ? siblings[i + 1] : null;
    if (!nxt) return;
    const t = toast(`Next up: ${nxt.name}`, "info", { ms: 5000, action: { label: "Cancel", run: () => { cancelled = true; } } });
    let cancelled = false;
    setTimeout(() => { if (!cancelled && ctx.isCurrent()) location.hash = "#/watch/" + nxt.id; }, 4000);
    void t;
  }
  get("/files?kind=video&category=" + encodeURIComponent(item.category) + "&sort=name&limit=60", { signal: ctx.signal, quiet: true }).then((d) => {
    if (!ctx.isCurrent()) return;
    siblings = d.items;
    for (const s of siblings.filter((x) => x.id !== item.id).slice(0, 14)) more.append(h("a", { class: "rowitem", href: "#/watch/" + s.id, style: { color: "inherit" } }, h("span", { class: "thumb" }, icon("film")), h("span", { class: "rowtext" }, h("b", null, s.name), h("span", null, fmtBytes(s.size)))));
    if (!more.firstChild) more.append(h("p", { class: "muted" }, "No other videos in this folder."));
  }).catch(() => more.append(h("p", { class: "muted" }, "Could not load other videos.")));

  const key = (e) => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === " " && e.target !== video && e.target.tagName !== "BUTTON") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    else if (e.key === "k") video.paused ? video.play() : video.pause();
    else if (e.key === "ArrowRight" && e.target !== video) video.currentTime += 10;
    else if (e.key === "ArrowLeft" && e.target !== video) video.currentTime -= 10;
    else if (e.key === "f") { document.fullscreenElement ? document.exitFullscreen() : video.requestFullscreen && video.requestFullscreen(); }
    else if (e.key === "m") video.muted = !video.muted;
  };
  document.addEventListener("keydown", key);
  const cleanup = () => {
    document.removeEventListener("keydown", key);
    if (started) send(false);
    video.pause(); video.removeAttribute("src"); video.load(); // frees the server's streaming slot
  };
  activeVideo = cleanup;
  return () => { if (activeVideo === cleanup) activeVideo = null; cleanup(); };
}

function fetchKeepalive(body) {
  // Progress is a convenience; failures are ignored so a stopped server never causes retry loops.
  post("/playback/progress", body, { quiet: true, timeout: 8000 }).catch(() => {});
}
