// Library views: category pages, collections (Favorites/Watchlist/Recent), search, photo viewer, document viewer.
// Created By Shiv Yogi.
import { get, fileUrl, ApiError } from "./api.js";
import { h, icon, iconButton, clear, stateBlock, loadingBlock, fmtBytes, fmtDate, fmtDuration, kindIcon, getPref, setPref, debounce, toast, openSheet, motionReduced, announce } from "./ui.js";
import { toggleFavorite, toggleWatchlist, downloadFile, errText } from "./actions.js";
import { playQueue, enqueue, addToPlaylistSheet, current as currentTrack } from "./players.js";
import { openShareSheet } from "./shares.js";

const PAGE = 48;
const CAT_TITLES = { movies: "Movies", music: "Music", photos: "Photos", documents: "Documents", downloads: "Downloads", uploads: "Uploads" };
const TEXT_EXTS = new Set(["txt", "md", "csv", "json", "log", "xml", "yml", "yaml", "ini"]);

// ---------------------------------------------------------------- opening items
export function openItem(item, list = [], ctx = null) {
  if (item.kind === "video") { location.hash = "#/watch/" + item.id; return; }
  if (item.kind === "audio") {
    const tracks = list.filter((x) => x.kind === "audio");
    const i = tracks.findIndex((x) => x.id === item.id);
    playQueue(tracks.length ? tracks : [item], Math.max(0, i));
    return;
  }
  if (item.kind === "image") {
    const imgs = list.filter((x) => x.kind === "image");
    openPhotoViewer(imgs.length ? imgs : [item], Math.max(0, imgs.findIndex((x) => x.id === item.id)));
    return;
  }
  if (item.kind === "document") { openDocViewer(item); return; }
  openUnsupported(item);
}

function openUnsupported(item) {
  const body = h("div", { style: { display: "grid", gap: "12px" } },
    h("p", null, "NEXORA cannot preview this file type (" + (item.ext ? "." + item.ext : "no extension") + ")."),
    h("p", { class: "muted" }, "You can still download it and open it with another app on your device."),
    h("div", { class: "row" }, h("button", { class: "btn btn-primary", type: "button", onclick: () => downloadFile(item) }, icon("download", "sm"), "Download"),
      h("button", { class: "btn", type: "button", onclick: () => openShareSheet(item) }, icon("share", "sm"), "Share")));
  openSheet(item.name, body);
}

// ---------------------------------------------------------------- cards and rows
function thumbBox(item, square) {
  const box = h("span", { class: "thumb" + (square ? " square" : "") }, icon(kindIcon(item.kind)));
  if (item.thumbnail || (item.kind === "image")) {
    box.append(h("img", { src: fileUrl(item.id, "thumbnail"), alt: "", loading: "lazy", decoding: "async", onerror: (e) => e.currentTarget.remove() }));
  }
  if (item.kind === "video" && item.progress && item.duration) {
    const pct = Math.min(100, Math.round((item.progress / item.duration) * 100));
    if (pct > 1 && pct < 99) box.append(h("span", { class: "bar", "aria-hidden": "true" }, h("i", { style: { width: pct + "%" } })));
  }
  return box;
}

function meta(item) {
  const bits = [fmtBytes(item.size)];
  if (item.duration) bits.unshift(fmtDuration(item.duration));
  if (item.kind === "video" && item.progress > 10 && item.duration && item.progress < item.duration - 10) bits.push("resume " + fmtDuration(item.progress));
  return bits;
}

function itemMenu(item, onChange) {
  const body = h("div", { class: "list" });
  const sheet = openSheet(item.name, body);
  const act = (label, ic, fn) => body.append(h("button", { type: "button", class: "btn btn-block", style: { justifyContent: "flex-start" }, onclick: async () => { sheet.close(); await fn(); } }, icon(ic, "sm"), label));
  act("Open", kindIcon(item.kind), () => openItem(item, [item]));
  act(item.favorite ? "Remove from Favorites" : "Add to Favorites", "star", async () => { await toggleFavorite(item); if (onChange) onChange(); });
  act(item.watchlist ? "Remove from Watchlist" : "Add to Watchlist", "bookmark", async () => { await toggleWatchlist(item); if (onChange) onChange(); });
  if (item.kind === "audio") {
    act("Play next", "queue", () => { enqueue(item, true); toast("Will play next.", "ok"); });
    act("Add to queue", "queue", () => { enqueue(item); toast("Added to the queue.", "ok"); });
    act("Add to playlist", "plus", () => addToPlaylistSheet(item));
  }
  act("Download", "download", () => downloadFile(item));
  act("Create temporary share link", "share", () => openShareSheet(item));
  body.append(h("dl", { class: "kv", style: { marginTop: "10px" } },
    h("dt", null, "Category"), h("dd", null, item.category), h("dt", null, "Folder"), h("dd", null, item.folder || "Top level"),
    h("dt", null, "Type"), h("dd", null, (item.mime || item.kind) + (item.ext ? " (." + item.ext + ")" : "")),
    h("dt", null, "Size"), h("dd", null, fmtBytes(item.size)), h("dt", null, "Modified"), h("dd", null, fmtDate(item.mtime))));
}

export function card(item, list, onChange) {
  const star = iconButton("star", item.favorite ? "Remove from Favorites" : "Add to Favorites", async (e) => {
    e.stopPropagation();
    await toggleFavorite(item);
    star.setAttribute("aria-label", item.favorite ? "Remove from Favorites" : "Add to Favorites");
    star.setAttribute("aria-pressed", String(!!item.favorite)); star.title = star.getAttribute("aria-label");
    star.classList.toggle("on", !!item.favorite);
    if (onChange) onChange(item);
  }, { class: item.favorite ? "on" : "", attrs: { "aria-pressed": String(!!item.favorite) } });
  const more = iconButton("more", "More actions for " + item.name, (e) => { e.stopPropagation(); itemMenu(item, onChange); });
  return h("article", { class: "card", dataset: { id: item.id } },
    h("button", { type: "button", class: "card-main", "aria-label": "Open " + item.name, onclick: () => openItem(item, list) },
      thumbBox(item, item.kind === "image" || item.kind === "audio"),
      h("span", { class: "card-body" }, h("span", { class: "card-title" }, item.name), h("span", { class: "card-meta" }, meta(item).map((m) => h("span", null, m))))),
    h("div", { class: "card-actions" }, star, more));
}

export function row(item, list, onChange) {
  const playing = item.kind === "audio" && currentTrack() && currentTrack().id === item.id;
  return h("div", { class: "rowitem" + (playing ? " playing" : ""), dataset: { id: item.id } },
    h("button", { type: "button", class: "rowmain", "aria-label": "Open " + item.name, onclick: () => openItem(item, list) },
      thumbBox(item, true), h("span", { class: "rowtext" }, h("b", null, item.name), h("span", null, (item.folder ? item.folder + ", " : "") + meta(item).join(", ") + ", " + fmtDate(item.mtime)))),
    h("span", { class: "rowsize" }, fmtBytes(item.size)),
    iconButton("more", "More actions for " + item.name, () => itemMenu(item, onChange)));
}

// ---------------------------------------------------------------- generic paged listing
function pagedList({ ctx, path, params = {}, emptyTitle, emptyMessage, toolbar = true, defaultSort = "name", defaultOrder = "asc", showCategory = false, onTotal }) {
  const root = h("div");
  const st = { items: [], total: 0, sort: defaultSort, order: defaultOrder, q: "", kind: "", loading: false };
  const view = () => getPref("view") === "list" ? "list" : "grid";
  const out = h("div", { "aria-live": "polite" });
  const more = h("div", { class: "row", style: { justifyContent: "center", margin: "18px 0" } });
  const count = h("span", { class: "muted", role: "status" });

  function qs(offset) {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    for (const [k, v] of Object.entries(params)) if (!k.startsWith("__")) p.set(k, v);
    if (st.sort) p.set("sort", st.sort);
    if (st.order) p.set("order", st.order);
    if (st.q) p.set("q", st.q);
    if (st.kind) p.set("kind", st.kind);
    return p.toString();
  }
  async function load(reset) {
    if (st.loading) return;
    st.loading = true;
    if (reset) { st.items = []; clear(out).append(loadingBlock(8)); clear(more); }
    else clear(more).append(h("span", { class: "muted" }, "Loading more"));
    try {
      const d = await get(path + "?" + qs(reset ? 0 : st.items.length), { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      st.total = d.total;
      st.items = reset ? d.items : st.items.concat(d.items);
      if (onTotal) onTotal(d);
      paint(d.scan);
    } catch (e) {
      if (!ctx.isCurrent() || (e && e.name === "AbortError")) return;
      clear(more);
      clear(out).append(stateBlock({ kind: "error", title: "Could not load this list", message: errText(e, "Something went wrong."), actions: [h("button", { class: "btn", type: "button", onclick: () => load(true) }, "Try again")] }));
    } finally { st.loading = false; }
  }
  function paint(scan) {
    clear(out);
    count.textContent = st.total + (st.total === 1 ? " item" : " items");
    if (!st.items.length) {
      const filtered = st.q || st.kind;
      out.append(stateBlock({
        title: filtered ? "Nothing matches" : emptyTitle, message: filtered ? "Try a different search or clear the filter." : emptyMessage,
        actions: filtered ? [h("button", { class: "btn", type: "button", onclick: () => { st.q = ""; st.kind = ""; if (qInput) qInput.value = ""; if (kindSel) kindSel.value = ""; load(true); } }, "Clear filters")] : [],
      }));
      clear(more);
      return;
    }
    const isPhotos = st.items.every((i) => i.kind === "image");
    const onChange = () => { if (params.__reload) load(true); };
    if (view() === "list") out.append(h("div", { class: "list" }, st.items.map((it) => row(it, st.items, onChange))));
    else out.append(h("div", { class: "grid" + (isPhotos ? " photos" : "") }, st.items.map((it) => card(it, st.items, onChange))));
    clear(more);
    if (st.items.length < st.total) more.append(h("button", { class: "btn", type: "button", onclick: () => load(false) }, "Load more (" + (st.total - st.items.length) + " left)"));
    if (scan && scan.state === "scanning") out.append(h("p", { class: "muted", role: "status" }, "The library is being scanned, so this list may still grow."));
  }

  let qInput = null, kindSel = null;
  if (toolbar) {
    qInput = h("input", { type: "search", placeholder: "Filter by name", maxlength: "100", "aria-label": "Filter by name" });
    qInput.addEventListener("input", debounce(() => { st.q = qInput.value.trim(); load(true); }, 300));
    const sortSel = h("select", { "aria-label": "Sort by", onchange: () => { st.sort = sortSel.value; load(true); } },
      [["name", "Name"], ["date", "Date modified"], ["size", "Size"], ["type", "Type"]].map(([v, t]) => h("option", { value: v, selected: v === st.sort }, t)));
    const orderBtn = h("button", { class: "btn", type: "button", "aria-label": "Sort order", onclick: () => { st.order = st.order === "asc" ? "desc" : "asc"; orderBtn.textContent = st.order === "asc" ? "Ascending" : "Descending"; load(true); } }, st.order === "asc" ? "Ascending" : "Descending");
    const seg = h("div", { class: "seg", role: "group", "aria-label": "View" });
    const gridB = h("button", { type: "button", "aria-label": "Grid view", "aria-pressed": String(view() === "grid"), onclick: () => setView("grid") }, icon("grid"));
    const listB = h("button", { type: "button", "aria-label": "List view", "aria-pressed": String(view() === "list"), onclick: () => setView("list") }, icon("list"));
    seg.append(gridB, listB);
    function setView(v) { setPref("view", v); gridB.setAttribute("aria-pressed", String(v === "grid")); listB.setAttribute("aria-pressed", String(v === "list")); if (st.items.length || !st.loading) paint(); }
    const kinds = params.category === undefined && !params.__noKind ? [["", "All types"], ["video", "Videos"], ["audio", "Music"], ["image", "Photos"], ["document", "Documents"], ["other", "Other"]] : null;
    if (kinds) kindSel = h("select", { "aria-label": "File type", onchange: () => { st.kind = kindSel.value; load(true); } }, kinds.map(([v, t]) => h("option", { value: v }, t)));
    root.append(h("div", { class: "toolrow" }, h("div", { class: "grow" }, qInput), kindSel, sortSel, orderBtn, seg, count));
  } else root.append(h("div", { class: "toolrow" }, count));
  root.append(out, more);
  return { root, load, state: st };
}

// ---------------------------------------------------------------- category page
export async function renderCategory(ctx, cat) {
  const { main } = ctx;
  const title = CAT_TITLES[cat];
  ctx.setTitle(title);
  const banner = h("div");
  const head = h("div", { class: "page-head" }, h("h2", null, title), h("span", { class: "grow" }));
  const list = pagedList({
    ctx, path: "/files", params: { category: title }, defaultSort: cat === "downloads" ? "date" : "name", defaultOrder: cat === "downloads" ? "desc" : "asc",
    emptyTitle: "No " + title.toLowerCase() + " found",
    emptyMessage: "NEXORA only shows files that are really in this phone folder. Add files to the folder, then use Rescan on the Storage page.",
  });
  main.append(head, banner, list.root);
  list.load(true);
  try {
    const c = await get("/categories", { signal: ctx.signal });
    if (!ctx.isCurrent()) return;
    const info = c.categories.find((x) => x.name === title);
    if (info && !info.available) {
      list.root.hidden = true;
      main.append(stateBlock({ kind: "unavailable", title: title + " folder unavailable", message: info.message || "The folder cannot be read.", actions: [h("a", { class: "btn", href: "#/storage" }, "Open Storage"), h("button", { class: "btn", type: "button", onclick: () => shellReload() }, "Check again")] }));
      return;
    }
    if (info && info.truncated) banner.append(h("p", { class: "muted" }, "This folder has more files than NEXORA indexes, so the list is incomplete."));
    if (info && info.upload_allowed) head.append(h("a", { class: "btn btn-primary", href: "#/uploads" }, icon("upload", "sm"), "Upload"));
  } catch (_) { /* the list itself reports connection problems */ }
}
function shellReload() { location.reload(); }

// ---------------------------------------------------------------- collections and search
const COLLECTIONS = {
  favorites: { title: "Favorites", path: "/favorites", empty: "Nothing in Favorites yet", msg: "Use the star on any file to keep it here.", sort: null },
  watchlist: { title: "Watchlist", path: "/watchlist", empty: "Your Watchlist is empty", msg: "Add a movie or video from its menu to save it for later.", sort: null },
  recent: { title: "Recent", path: "/recent", empty: "Nothing played recently", msg: "Videos and music you play appear here.", sort: null },
};
export async function renderCollection(ctx, name) {
  const c = COLLECTIONS[name];
  ctx.setTitle(c.title);
  const list = pagedList({ ctx, path: c.path, params: { __reload: name !== "recent", __noKind: false }, defaultSort: "", defaultOrder: "", emptyTitle: c.empty, emptyMessage: c.msg });
  // the server orders collections by when they were added or played; sort controls would be misleading
  list.state.sort = ""; list.state.order = "";
  ctx.main.append(h("div", { class: "page-head" }, h("h2", null, c.title)), list.root);
  const sortControls = list.root.querySelectorAll("select[aria-label='Sort by'], button[aria-label='Sort order']");
  sortControls.forEach((el) => { el.hidden = true; });
  list.load(true);
}

export async function renderSearch(ctx) {
  const q = decodeURIComponent(ctx.args.join("/") || "").slice(0, 100);
  ctx.setTitle("Search");
  const input = document.getElementById("search-input");
  if (input && !input.value) input.value = q;
  const list = pagedList({ ctx, path: "/files", params: { __noKind: false }, defaultSort: "name", emptyTitle: "No results", emptyMessage: "Search covers file names and folders inside your NEXORA library." });
  list.state.q = q;
  ctx.main.append(h("div", { class: "page-head" }, h("h2", null, "Results for "), h("span", { class: "grow" }, h("b", null, "“" + q + "”"))), list.root);
  const own = list.root.querySelector("input[type=search]");
  if (own) own.value = q;
  list.load(true);
}

// ---------------------------------------------------------------- NEXORA Vision (photo viewer)
export function openPhotoViewer(items, startIndex = 0) {
  let i = startIndex, scale = 1, fit = true, rot = 0, tx = 0, ty = 0, slide = 0, infoOpen = false;
  const prevFocus = document.activeElement;
  const img = h("img", { alt: "", draggable: "false" });
  const stage = h("div", { class: "stage", tabindex: "0", role: "img", "aria-label": "Photo" }, img);
  const err = h("div", { class: "state", hidden: true, style: { position: "absolute" }, role: "alert" });
  const title = h("span", { class: "title" });
  const pos = h("span", { class: "muted", style: { fontSize: "13px", padding: "0 6px" } });
  const info = h("div", { class: "viewer-info panel glass", hidden: true });
  const strip = h("div", { class: "strip", role: "list", "aria-label": "Photos" });
  const thumbs = items.map((it, k) => {
    const b = h("button", { type: "button", role: "listitem", "aria-label": "Photo " + (k + 1) + ": " + it.name, onclick: () => go(k) },
      h("img", { src: fileUrl(it.id, "thumbnail"), alt: "", loading: "lazy", onerror: (e) => { e.currentTarget.replaceWith(h("span", { class: "muted", style: { fontSize: "11px", padding: "4px" } }, k + 1)); } }));
    strip.append(b); return b;
  });
  const prevB = iconButton("left", "Previous photo", () => go(i - 1), { class: "navbtn prev" });
  const nextB = iconButton("right", "Next photo", () => go(i + 1), { class: "navbtn next" });
  stage.append(prevB, nextB, err);

  const playBtn = iconButton("slideshow", "Start slideshow", () => toggleSlide());
  const fitBtn = iconButton("fit", "Fit to screen", () => { fit = true; scale = 1; tx = ty = 0; apply(); });
  const bar = h("div", { class: "viewer-bar" },
    iconButton("left", "Close viewer", () => close()), title, pos,
    iconButton("plus", "Zoom in", () => zoom(1.25)), iconButton("x", "Zoom out", () => zoom(0.8)), fitBtn,
    iconButton("refresh", "Rotate", () => { rot = (rot + 90) % 360; fit = true; scale = 1; tx = ty = 0; apply(); }),
    playBtn, iconButton("expand", "Toggle fullscreen", () => toggleFs()),
    iconButton("info", "Photo details", () => { infoOpen = !infoOpen; info.hidden = !infoOpen; }),
    iconButton("download", "Download", () => downloadFile(items[i])),
    iconButton("share", "Temporary share", () => openShareSheet(items[i])));
  const viewer = h("div", { class: "viewer", role: "dialog", "aria-modal": "true", "aria-label": "NEXORA Vision photo viewer" }, bar, stage, strip, info);
  document.getElementById("overlay-root").append(viewer);
  document.body.style.setProperty("overflow", "hidden");

  function apply() {
    const nat = img.naturalWidth ? img : null;
    if (fit && nat) {
      const rect = stage.getBoundingClientRect();
      const swap = rot % 180 !== 0;
      const w = swap ? img.naturalHeight : img.naturalWidth, hgt = swap ? img.naturalWidth : img.naturalHeight;
      const f = Math.min(rect.width / w, rect.height / hgt, 1);
      img.style.width = img.naturalWidth * f + "px"; img.style.height = img.naturalHeight * f + "px";
      scale = 1;
    }
    img.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ") rotate(" + rot + "deg)";
    img.style.transition = motionReduced() ? "none" : "transform .15s ease";
  }
  function zoom(f) {
    if (fit) { fit = false; }
    scale = Math.max(0.2, Math.min(8, scale * f));
    apply();
    announce("Zoom " + Math.round(scale * 100) + " percent");
  }
  function load() {
    const it = items[i];
    title.textContent = it.name; pos.textContent = (i + 1) + " / " + items.length;
    err.hidden = true; img.style.opacity = "0.4";
    fit = true; scale = 1; rot = 0; tx = ty = 0;
    img.style.width = ""; img.style.height = "";
    img.onload = () => { img.style.opacity = "1"; apply(); };
    img.onerror = () => { img.style.opacity = "0"; clear(err).append(icon("alert"), h("h3", null, "This photo cannot be shown"), h("p", null, "The file may have been removed, or your browser cannot display this image format."), h("button", { class: "btn", type: "button", onclick: () => downloadFile(it) }, "Download instead")); err.hidden = false; };
    img.src = fileUrl(it.id, "stream");
    img.alt = it.name;
    thumbs.forEach((b, k) => { if (k === i) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current"); });
    thumbs[i].scrollIntoView({ block: "nearest", inline: "center" });
    prevB.hidden = items.length < 2; nextB.hidden = items.length < 2;
    clear(info).append(h("h3", null, "Details"), h("dl", { class: "kv" }, h("dt", null, "Name"), h("dd", null, it.name), h("dt", null, "Size"), h("dd", null, fmtBytes(it.size)),
      h("dt", null, "Modified"), h("dd", null, fmtDate(it.mtime)), h("dt", null, "Folder"), h("dd", null, it.folder || "Top level"), h("dt", null, "Pixels"), h("dd", { id: "pv-px" }, "Loading")));
    img.addEventListener("load", () => { const el = info.querySelector("#pv-px"); if (el) el.textContent = img.naturalWidth + " x " + img.naturalHeight; }, { once: true });
  }
  function go(k) {
    if (!items.length) return;
    i = (k + items.length) % items.length;
    load();
  }
  function toggleSlide() {
    if (slide) { clearInterval(slide); slide = 0; playBtn.setAttribute("aria-label", "Start slideshow"); playBtn.title = "Start slideshow"; announce("Slideshow stopped"); return; }
    if (items.length < 2) { toast("A slideshow needs at least two photos.", "info"); return; }
    slide = setInterval(() => go(i + 1), Math.max(2, Number(getPref("slideshowSeconds")) || 4) * 1000);
    playBtn.setAttribute("aria-label", "Stop slideshow"); playBtn.title = "Stop slideshow"; announce("Slideshow started");
  }
  function toggleFs() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (viewer.requestFullscreen) viewer.requestFullscreen().catch(() => toast("Fullscreen is not available in this browser.", "info"));
    else toast("Fullscreen is not available in this browser.", "info");
  }
  function close() {
    if (slide) clearInterval(slide);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", apply);
    viewer.remove();
    if (!document.querySelector("#overlay-root .scrim")) document.body.style.removeProperty("overflow");
    if (prevFocus && prevFocus.focus) prevFocus.focus();
  }
  function onKey(e) {
    if (!viewer.isConnected) return;
    if (document.querySelector("#overlay-root .scrim")) return; // a sheet is on top
    const k = e.key;
    if (k === "Escape") { e.preventDefault(); close(); }
    else if (k === "ArrowLeft") { e.preventDefault(); go(i - 1); }
    else if (k === "ArrowRight") { e.preventDefault(); go(i + 1); }
    else if (k === "+" || k === "=") zoom(1.25);
    else if (k === "-") zoom(0.8);
    else if (k === "0") fitBtn.click();
    else if (k === "r" || k === "R") bar.querySelector("[aria-label='Rotate']").click();
    else if (k === "f" || k === "F") toggleFs();
    else if (k === " " && document.activeElement === stage) { e.preventDefault(); toggleSlide(); }
  }
  document.addEventListener("keydown", onKey, true);
  window.addEventListener("resize", apply);

  // drag to pan, wheel and pinch to zoom
  const pts = new Map();
  let lastDist = 0, drag = null;
  stage.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".navbtn")) return;
    stage.setPointerCapture(e.pointerId); pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) drag = { x: e.clientX - tx, y: e.clientY - ty, sx: e.clientX, moved: false };
    stage.classList.add("dragging");
  });
  stage.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (lastDist) { fit = false; scale = Math.max(0.2, Math.min(8, scale * (d / lastDist))); apply(); }
      lastDist = d;
    } else if (drag && !fit) { tx = e.clientX - drag.x; ty = e.clientY - drag.y; drag.moved = true; apply(); }
  });
  const endPtr = (e) => {
    const wasDrag = drag, endX = e.clientX;
    pts.delete(e.pointerId); lastDist = 0; if (!pts.size) { stage.classList.remove("dragging"); drag = null; }
    // swipe to change photo when not zoomed
    if (wasDrag && fit && e.type === "pointerup" && Math.abs(endX - wasDrag.sx) > 70) go(i + (endX < wasDrag.sx ? 1 : -1));
  };
  stage.addEventListener("pointerup", endPtr); stage.addEventListener("pointercancel", endPtr);
  stage.addEventListener("wheel", (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.15 : 0.87); }, { passive: false });
  stage.addEventListener("dblclick", () => { if (fit) zoom(2); else fitBtn.click(); });

  load();
  stage.focus();
  return { close };
}

// ---------------------------------------------------------------- document / PDF viewer
export function openDocViewer(item) {
  const ext = (item.ext || "").toLowerCase();
  const body = h("div", { class: "docview" });
  const sheet = openSheet(item.name, body, { wide: true });
  const actions = h("div", { class: "row" },
    h("button", { class: "btn", type: "button", onclick: () => downloadFile(item) }, icon("download", "sm"), "Download"),
    h("a", { class: "btn", href: fileUrl(item.id, "stream"), target: "_blank", rel: "noopener" }, icon("ext", "sm"), "Open in new tab"),
    h("button", { class: "btn", type: "button", onclick: () => { sheet.close(); openShareSheet(item); } }, icon("share", "sm"), "Share"));
  if (ext === "pdf") {
    body.append(h("p", { class: "muted" }, "PDF preview uses your browser's own PDF viewer. Some mobile browsers cannot show PDFs inside a page; if you see a blank area, use Open in new tab or Download."),
      h("iframe", { class: "docframe", src: fileUrl(item.id, "stream"), title: item.name }), actions);
    return sheet;
  }
  if (TEXT_EXTS.has(ext)) {
    const box = h("pre", { class: "doctext", tabindex: "0", "aria-label": "File contents" }, "Loading");
    body.append(box, actions);
    const MAX = 512 * 1024;
    fetch(fileUrl(item.id, "stream"), { credentials: "include", headers: { Range: "bytes=0-" + (MAX - 1) } }).then(async (r) => {
      if (!r.ok && r.status !== 206) throw new ApiError(r.status, "error", "The server returned " + r.status + ".");
      const txt = await r.text();
      box.textContent = txt.slice(0, MAX);
      if (item.size > MAX) body.insertBefore(h("p", { class: "muted", role: "status" }, "Showing the first " + fmtBytes(MAX) + " of " + fmtBytes(item.size) + ". Download the file to read all of it."), box);
    }).catch((e) => { box.textContent = ""; body.insertBefore(h("p", { role: "alert" }, "Could not load this file. " + (e.message || "")), box); });
    return sheet;
  }
  body.append(h("p", null, "NEXORA cannot preview ." + (ext || "this") + " files. Supported previews are PDF and plain text formats (" + [...TEXT_EXTS].join(", ") + ")."),
    h("p", { class: "muted" }, "Download the file to open it in another app."), actions);
  return sheet;
}
