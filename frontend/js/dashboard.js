// Home dashboard. Every number comes from the server; empty states are shown honestly. Created By Shiv Yogi.
import { get } from "./api.js";
import { h, icon, clear, stateBlock, loadingBlock, fmtBytes, fmtUptime } from "./ui.js";
import { card } from "./library.js";
import { errText } from "./actions.js";

export async function renderHome(ctx) {
  const { main } = ctx;
  ctx.setTitle("Home");
  const body = h("div");
  main.append(h("div", { class: "page-head" }, h("h2", null, "Your Personal Media Universe"), h("span", { class: "grow" }),
    h("button", { class: "btn", type: "button", onclick: () => load() }, icon("refresh", "sm"), "Refresh")), body);

  async function load(silent) {
    if (!silent) clear(body).append(loadingBlock(4));
    try {
      const d = await get("/dashboard", { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      paint(d);
    } catch (e) {
      if (!ctx.isCurrent() || silent) return;
      clear(body).append(stateBlock({ kind: "error", title: "Could not load your dashboard", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: () => load() }, "Try again")] }));
    }
  }

  function strip(title, items, link) {
    if (!items.length) return null;
    return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h3", null, title), link ? h("a", { href: link }, "See all") : null),
      h("div", { class: "hscroll" }, items.map((it) => card(it, items, () => load(true)))));
  }

  function paint(d) {
    clear(body);
    const c = d.counts;
    const tile = (n, label, href) => h("a", { class: "stat", href }, h("b", null, String(n)), h("span", null, label));
    body.append(h("div", { class: "stats" }, tile(c.videos, "Videos", "#/movies"), tile(c.music, "Songs", "#/music"), tile(c.photos, "Photos", "#/photos"), tile(c.documents, "Documents", "#/documents")));
    if (d.scan.state === "scanning") body.append(h("p", { class: "muted", role: "status" }, "Scanning your library. Counts may still change."));
    if (c.total === 0 && d.scan.state !== "scanning") {
      body.append(stateBlock({ title: "Your library is empty", message: "NEXORA shows only files that exist in its phone folders. Put media in the Movies, Music or Photos folder, or upload from the Uploads page, then rescan from Storage.",
        actions: [h("a", { class: "btn btn-primary", href: "#/uploads" }, "Upload files"), h("a", { class: "btn", href: "#/storage" }, "Open Storage")] }));
    }
    for (const s of [strip("Continue watching", d.continue_watching, "#/movies"), strip("Recently played", d.recently_played, "#/recent"), strip("Favorites", d.favorites, "#/favorites"), strip("Recently added", d.recent_files, null)]) if (s) body.append(s);
    const vols = Object.values(d.storage.volumes || {});
    const v = vols[0];
    body.append(h("div", { class: "monitor" },
      h("section", { class: "panel glass" }, h("h3", null, "Storage"),
        v && v.total_bytes ? h("div", null, h("div", { class: "meter " + (v.used_percent > 90 ? "bad" : v.used_percent > 75 ? "warn" : "") }, h("i", { style: { width: (v.used_percent || 0) + "%" } })),
          h("div", { class: "meter-label" }, h("span", null, fmtBytes(v.used_bytes) + " used"), h("span", null, fmtBytes(v.free_bytes) + " free"))) : h("p", { class: "unavailable" }, "Capacity unavailable on this device"),
        h("p", { class: "muted" }, c.total + " indexed files, " + fmtBytes(d.storage.library.size_bytes))),
      h("section", { class: "panel glass" }, h("h3", null, "Server"), h("dl", { class: "kv" }, h("dt", null, "Version"), h("dd", null, d.server.version), h("dt", null, "Up for"), h("dd", null, fmtUptime(d.server.uptime_seconds)),
        h("dt", null, "Uploads"), h("dd", null, d.server.uploads_enabled ? "Enabled" : "Disabled")), h("a", { href: "#/server" }, "Open Mobile Server"))));
  }
  ctx.shell.setPoll(() => load(true));
  await load();
}
