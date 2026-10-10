// Mobile Server monitor and Storage explorer. Anything the phone cannot report is shown as "Unavailable on this device".
// Created By Shiv Yogi.
import { get, post, conn, ApiError } from "./api.js";
import { h, icon, clear, stateBlock, loadingBlock, fmtBytes, fmtUptime, fmtDateTime, fmtRelative, withBusy, toast, getPref } from "./ui.js";
import { errText } from "./actions.js";
import { shell } from "./app.js";

const UNAVAIL = "Unavailable on this device";

function meter(label, pct, right, label2, invert = false) {
  const cls = invert ? (pct < 15 ? "bad" : pct < 30 ? "warn" : "ok") : (pct > 90 ? "bad" : pct > 75 ? "warn" : "ok");
  return h("div", null, h("div", { class: "meter-label" }, h("span", null, label), h("span", null, right)),
    h("div", { class: "meter " + cls, role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)), "aria-label": label2 || label }, h("i", { style: { width: Math.max(0, Math.min(100, pct)) + "%" } })));
}
const unavailable = (why) => h("p", { class: "muted" }, why || UNAVAIL);
const pill = (cls, text) => h("span", { class: "badge " + cls }, text);

export async function renderServer(ctx) {
  const { main } = ctx;
  const body = h("div");
  const stamp = h("span", { class: "count", role: "status" });
  main.append(h("div", { class: "page-head" }, h("h2", null, "Mobile Server"), stamp, h("span", { class: "grow" }),
    h("button", { class: "btn", type: "button", onclick: (e) => withBusy(e.currentTarget, () => load()) }, icon("refresh", "sm"), "Refresh")), body);
  let first = true;

  async function load() {
    if (first) clear(body).append(loadingBlock(3));
    try {
      const d = await get("/device/status", { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      first = false;
      paint(d);
      stamp.textContent = "Updated " + fmtDateTime(Math.floor(Date.now() / 1000));
    } catch (e) {
      if (!ctx.isCurrent() || (e && e.name === "AbortError")) return;
      if (!first) { stamp.textContent = "Could not refresh. Showing the last reading."; return; }
      clear(body).append(stateBlock({ kind: "error", title: "Could not read the server status", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: () => load() }, "Try again")] }));
    }
  }

  function card(title, ...children) { return h("section", { class: "panel glass", "aria-label": title }, h("h3", null, title), ...children); }

  function paint(d) {
    clear(body);
    const s = d.server, hl = d.health;
    const grid = h("div", { class: "monitor" });

    grid.append(card("Connection",
      h("dl", { class: "kv" },
        h("dt", null, "Browser to server"), h("dd", null, pill(conn.status === "online" ? "badge-ok" : "badge-warn", conn.status === "online" ? "Reachable" : conn.status)),
        h("dt", null, "Server API"), h("dd", null, pill(hl.api === "ok" ? "badge-ok" : "badge-bad", hl.api === "ok" ? "Running" : "Problem")),
        h("dt", null, "Database"), h("dd", null, pill(hl.database === "ok" ? "badge-ok" : "badge-bad", hl.database === "ok" ? "OK" : "Error")),
        h("dt", null, "Via Cloudflare"), h("dd", null, s.via_cloudflare ? "Yes, this request came through Cloudflare" : "No Cloudflare headers seen on this request"),
        h("dt", null, "Tunnel health"), h("dd", null, "Not measurable from the phone. If you can read this page, the tunnel is carrying traffic right now.")),
    ));

    grid.append(card("Server",
      h("dl", { class: "kv" },
        h("dt", null, "Version"), h("dd", null, s.version), h("dt", null, "Uptime"), h("dd", null, fmtUptime(s.uptime_seconds)),
        h("dt", null, "Started"), h("dd", null, fmtDateTime(s.started_at)), h("dt", null, "Python"), h("dd", null, s.python),
        h("dt", null, "Platform"), h("dd", null, s.platform), h("dt", null, "Uploads"), h("dd", null, s.uploads_enabled ? "Enabled, up to " + fmtBytes(s.max_upload_bytes) + " per file" : "Disabled"),
        h("dt", null, "Library scan"), h("dd", null, hl.library_scan.state + (hl.library_scan.finished_at ? ", last finished " + fmtRelative(hl.library_scan.finished_at) : "")))));

    if (!d.telemetry_enabled) {
      grid.append(card("Phone telemetry", h("p", { class: "muted" }, "Telemetry is turned off in the server configuration, so battery, memory and CPU are not reported.")));
    } else {
      const b = d.battery;
      grid.append(card("Battery", b && b.available
        ? h("div", { style: { display: "grid", gap: "10px" } }, meter("Charge", b.percent, b.percent + "%", "Battery charge", true),
            h("dl", { class: "kv" }, h("dt", null, "State"), h("dd", null, b.state || "Unknown"), b.temperature_c != null ? [h("dt", null, "Temperature"), h("dd", null, b.temperature_c + " C")] : null, h("dt", null, "Source"), h("dd", null, b.source)))
        : unavailable(b && b.reason)));
      const m = d.memory;
      grid.append(card("Memory", m && m.system && m.system.available
        ? h("div", { style: { display: "grid", gap: "10px" } }, meter("System memory in use", m.system.used_percent, m.system.used_percent + "%  of " + fmtBytes(m.system.total_bytes)),
            h("p", { class: "muted" }, fmtBytes(m.system.available_bytes) + " available"),
            m.process && m.process.available ? h("p", null, "NEXORA server process: " + fmtBytes(m.process.rss_bytes)) : h("p", { class: "muted" }, "Server process memory: " + UNAVAIL))
        : unavailable(m && m.system && m.system.reason)));
      const c = d.cpu;
      grid.append(card("CPU", c && c.system && c.system.available
        ? h("div", { style: { display: "grid", gap: "10px" } }, meter("CPU load", c.system.percent, c.system.percent + "%"), c.process && c.process.available ? h("p", null, "Server process: " + c.process.percent + "%") : null,
            h("p", { class: "muted" }, "A snapshot at the moment of the request, not an average."))
        : unavailable("CPU usage is not readable on this device. Install psutil in Pydroid 3 if it is available for your build.")));
      const st = d.storage;
      const vols = Object.values(st.volumes || {});
      grid.append(card("Storage", vols.length ? h("div", { style: { display: "grid", gap: "12px" } },
        vols.map((v) => v.total_bytes ? meter("Volume in use", v.used_percent, fmtBytes(v.used_bytes) + " of " + fmtBytes(v.total_bytes)) : null), h("p", { class: "muted" }, st.note), h("a", { class: "btn", href: "#/storage" }, "Open Storage explorer")) : unavailable()));
    }

    const errs = d.recent_errors || [];
    grid.append(h("section", { class: "panel glass wide", "aria-label": "Recent server errors" }, h("h3", null, "Recent server errors"),
      errs.length ? h("div", { class: "timeline" }, errs.slice().reverse().map((e) => h("div", { class: "event" }, h("time", null, typeof e.ts === "number" ? fmtDateTime(e.ts) : ""), h("span", null, (e.code || "error") + (e.type ? " (" + e.type + ")" : "") + ". Details are in the server log on the phone.")))) : h("p", { class: "muted" }, "No server errors since the server started.")));
    body.append(grid);
  }

  shell.setPoll(() => load());
  await load();
  return () => shell.setPoll(null);
}

export async function renderStorage(ctx) {
  const { main } = ctx;
  const body = h("div");
  const rescanBtn = h("button", { class: "btn btn-primary", type: "button", onclick: (e) => withBusy(e.currentTarget, rescan) }, icon("refresh", "sm"), "Rescan library");
  main.append(h("div", { class: "page-head" }, h("h2", null, "Storage"), h("span", { class: "grow" }), rescanBtn), body);
  let pollTimer = 0;

  async function rescan() {
    try {
      const r = await post("/library/rescan");
      toast(r.started ? "Scan started." : "A scan is already running.", "info");
      watchScan();
    } catch (e) { toast(errText(e, "Could not start a scan."), "error"); }
  }
  function watchScan() {
    clearInterval(pollTimer);
    let n = 0;
    pollTimer = setInterval(async () => {
      if (!ctx.isCurrent() || ++n > 90) { clearInterval(pollTimer); return; }
      try { const c = await get("/categories", { quiet: true }); if (c.scan.state !== "scanning") { clearInterval(pollTimer); toast("Scan finished.", "ok"); load(); } } catch (_) { /* connection banner covers this */ }
    }, 2000);
  }

  async function load() {
    clear(body).append(loadingBlock(3));
    try {
      const [st, cats] = await Promise.all([get("/storage", { signal: ctx.signal }), get("/categories", { signal: ctx.signal })]);
      if (!ctx.isCurrent()) return;
      paint(st, cats);
      if (cats.scan.state === "scanning") watchScan();
    } catch (e) {
      if (!ctx.isCurrent() || (e && e.name === "AbortError")) return;
      clear(body).append(stateBlock({ kind: "error", title: "Could not read storage", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: load }, "Try again")] }));
    }
  }

  function paint(st, cats) {
    clear(body);
    const catMap = Object.fromEntries(cats.categories.map((c) => [c.name, c]));
    const grid = h("div", { class: "monitor" });
    const vols = Object.entries(st.volumes || {});
    grid.append(h("section", { class: "panel glass" }, h("h3", null, "Library"),
      h("dl", { class: "kv" }, h("dt", null, "Files indexed"), h("dd", null, String(st.library.file_count)), h("dt", null, "Total size"), h("dd", null, fmtBytes(st.library.size_bytes)),
        h("dt", null, "Last scan"), h("dd", null, cats.scan.state === "scanning" ? "Scanning now" : cats.scan.finished_at ? fmtDateTime(cats.scan.finished_at) : "Not scanned yet"))));
    for (const [id, v] of vols) {
      grid.append(h("section", { class: "panel glass" }, h("h3", null, vols.length > 1 ? "Storage volume " + id.slice(1) : "Storage volume"),
        v.total_bytes ? h("div", { style: { display: "grid", gap: "10px" } }, meter("In use", v.used_percent, fmtBytes(v.used_bytes) + " of " + fmtBytes(v.total_bytes)), h("p", { class: "muted" }, fmtBytes(v.free_bytes) + " free")) : unavailable()));
    }
    const cl = h("section", { class: "panel glass wide" }, h("h3", null, "Allowed folders"),
      h("p", { class: "muted", style: { marginBottom: "10px" } }, "NEXORA can only see these folders. Nothing else on the phone is reachable through it."));
    const rows = st.categories.map((c) => {
      const info = catMap[c.name] || {};
      return h("div", { class: "rowitem" }, h("span", { class: "thumb" }, icon("folder")),
        h("span", { class: "rowtext grow" }, h("b", null, c.name), h("span", null, c.available ? c.file_count + " files, " + fmtBytes(c.size_bytes) + (info.truncated ? ". Listing was capped; some files are not shown." : "") : (info.message || "Folder is not available."))),
        pill(c.available ? "badge-ok" : "badge-warn", c.available ? "Available" : (info.status === "permission" ? "No permission" : "Missing")));
    });
    cl.append(h("div", { class: "list" }, rows), h("p", { class: "muted", style: { marginTop: "12px" } }, st.note));
    grid.append(cl);
    body.append(grid);
  }
  await load();
  return () => clearInterval(pollTimer);
}
