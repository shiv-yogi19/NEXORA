// Settings, Activity log and About. Settings here are display preferences stored in this browser only.
// Created By Shiv Yogi.
import { get } from "./api.js";
import { APP_VERSION, CREATOR, resolveApiBase } from "./config.js";
import { h, icon, clear, stateBlock, loadingBlock, getPref, setPref, fmtDateTime, announce } from "./ui.js";
import { errText } from "./actions.js";
import { shell } from "./app.js";

function toggle(label, desc, key, onChange) {
  const input = h("input", { type: "checkbox", role: "switch", id: "set-" + key, checked: !!getPref(key), "aria-describedby": "d-" + key });
  input.addEventListener("change", () => { setPref(key, input.checked); announce(label + (input.checked ? " on" : " off")); if (onChange) onChange(); });
  return h("div", { class: "setting" }, h("div", null, h("label", { for: "set-" + key, style: { fontWeight: "600", color: "var(--ink)" } }, label), h("div", { class: "desc", id: "d-" + key }, desc)), h("span", { class: "switch" }, input, h("span")));
}
function choice(label, desc, key, options, onChange, asNumber) {
  const sel = h("select", { id: "set-" + key, "aria-describedby": "d-" + key }, ...options.map(([v, t]) => h("option", { value: v, selected: String(getPref(key)) === String(v) }, t)));
  sel.addEventListener("change", () => { setPref(key, asNumber ? Number(sel.value) : sel.value); announce(label + " set to " + sel.selectedOptions[0].textContent); if (onChange) onChange(); });
  return h("div", { class: "setting" }, h("div", null, h("label", { for: "set-" + key, style: { fontWeight: "600", color: "var(--ink)" } }, label), h("div", { class: "desc", id: "d-" + key }, desc)), sel);
}

export async function renderSettings(ctx) {
  const { main } = ctx;
  main.append(h("div", { class: "page-head" }, h("h2", null, "Settings")),
    h("div", { class: "monitor" },
      h("section", { class: "panel glass", "aria-label": "Display" }, h("h3", null, "Display"),
        toggle("Lightweight Mode", "Turns off blur and glass effects and looping animation. Recommended for older phones.", "light"),
        choice("Reduce motion", "Automatic follows your device setting.", "motion", [["auto", "Automatic"], ["on", "Always reduce"], ["off", "Allow all motion"]]),
        choice("Accent colour", "Highlights in buttons and active items.", "accent", [["blue", "Electric blue"], ["violet", "Violet"], ["cyan", "Cyan"]]),
        choice("Library layout", "How files are shown in lists.", "view", [["grid", "Grid"], ["list", "List"]])),
      h("section", { class: "panel glass", "aria-label": "Playback" }, h("h3", null, "Playback"),
        toggle("Resume videos", "Continue a video from where you stopped, using the position saved on the server.", "resume"),
        toggle("Play next track automatically", "When a track ends, start the next one in the queue.", "autoplayNext"),
        choice("Slideshow speed", "Seconds each photo stays on screen.", "slideshowSeconds", [[3, "3 seconds"], [4, "4 seconds"], [6, "6 seconds"], [10, "10 seconds"]], null, true)),
      h("section", { class: "panel glass", "aria-label": "Connection" }, h("h3", null, "Connection"),
        choice("Refresh interval", "How often the dashboard and server monitor update while this tab is visible. Updates pause when the tab is hidden.", "pollSeconds", [[15, "Every 15 seconds"], [30, "Every 30 seconds"], [60, "Every minute"], [120, "Every 2 minutes"]], () => shell.restartPolling(), true),
        h("div", { class: "setting" }, h("div", null, h("b", null, "Server address"), h("div", { class: "desc" }, resolveApiBase())))),
      h("section", { class: "panel glass", "aria-label": "Privacy" }, h("h3", null, "Privacy"),
        h("p", { class: "muted" }, "These settings are saved only in this browser. Your password is never stored here. Favorites, Watchlist, playlists and history are kept in the database on your phone."))));
}

const EVENT_LABELS = {
  login_success: ["Signed in", "badge-ok"], login_failed: ["Failed sign-in", "badge-bad"], logout: ["Signed out", "badge-muted"],
  file_played: ["Played", "badge-info"], download_requested: ["Download requested", "badge-info"], upload_completed: ["Upload completed", "badge-ok"],
  share_created: ["Share link created", "badge-info"], share_revoked: ["Share link revoked", "badge-warn"],
};

export async function renderActivity(ctx) {
  const { main } = ctx;
  const body = h("div");
  main.append(h("div", { class: "page-head" }, h("h2", null, "Activity"), h("span", { class: "grow" }), h("button", { class: "btn", type: "button", onclick: () => load() }, icon("refresh", "sm"), "Refresh")), body);
  async function load() {
    clear(body).append(loadingBlock(2));
    try {
      const d = await get("/activity?limit=150", { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      clear(body);
      body.append(h("p", { class: "muted", style: { marginBottom: "14px" } }, "Failed sign-ins recorded: " + d.failed_login_count + ". The log never contains passwords, session tokens or share links."));
      if (!d.events.length) { body.append(stateBlock({ title: "No activity yet", message: "Sign-ins, plays, uploads and shares will be listed here." })); return; }
      body.append(h("div", { class: "timeline", role: "list" }, d.events.map((ev) => {
        const [label, cls] = EVENT_LABELS[ev.event] || [ev.event.replace(/_/g, " "), "badge-muted"];
        return h("div", { class: "event", role: "listitem" }, h("time", { datetime: new Date(ev.ts * 1000).toISOString() }, fmtDateTime(ev.ts)), h("span", { class: "badge " + cls }, label), h("span", { class: "grow", style: { overflowWrap: "anywhere" } }, ev.detail || ""));
      })));
    } catch (e) {
      if (!ctx.isCurrent() || (e && e.name === "AbortError")) return;
      clear(body).append(stateBlock({ kind: "error", title: "Could not load activity", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: load }, "Try again")] }));
    }
  }
  await load();
}

export async function renderAbout(ctx) {
  const { main } = ctx;
  main.append(h("div", { class: "page-head" }, h("h2", null, "About NEXORA")),
    h("section", { class: "panel glass", style: { maxWidth: "720px" } },
      h("img", { src: "assets/logo.svg", alt: "NEXORA", width: "72", height: "72", style: { marginBottom: "10px" } }),
      h("h3", { style: { fontSize: "22px" } }, "NEXORA"), h("p", null, "Your Personal Media Universe"), h("p", { class: "muted", style: { marginTop: "6px" } }, CREATOR),
      h("dl", { class: "kv", style: { marginTop: "16px" } }, h("dt", null, "Web app version"), h("dd", null, APP_VERSION), h("dt", null, "Server"), h("dd", { id: "about-server" }, "Checking")),
      h("p", { class: "muted", style: { marginTop: "16px" } }, "NEXORA shows files from allowed folders on your own phone through a server that you run. Nothing is uploaded to a media cloud. Temporary share links open one file and expire. Uploads are checked for type and size but are not malware-scanned.")));
  try {
    const d = await get("/device/status", { signal: ctx.signal, quiet: true });
    if (ctx.isCurrent()) document.getElementById("about-server").textContent = "Version " + d.server.version;
  } catch (_) { if (ctx.isCurrent()) document.getElementById("about-server").textContent = "Not reachable right now"; }
}
