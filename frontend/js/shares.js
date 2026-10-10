// Temporary Share Center. Created By Shiv Yogi.
// Links are created and revoked on the server; expiry is enforced by the server on every request.
import { get, post, del } from "./api.js";
import { h, icon, clear, stateBlock, openSheet, toast, copyText, fmtDateTime, fmtCountdown, fmtBytes, kindIcon, loadingBlock, debounce, withBusy } from "./ui.js";
import { errText } from "./actions.js";

const DURATIONS = [["15m", "15 minutes"], ["1h", "1 hour"], ["6h", "6 hours"], ["24h", "24 hours"]];
const LIMITS = "Anyone with the link can open this one file until it expires or you revoke it. They may be able to save it, copy it, screenshot it or record it; view-only cannot prevent that.";

/** Sheet that lets the owner search the library and pick one file. */
export function pickFile({ title, hint, onPick, kind }) {
  const input = h("input", { type: "search", placeholder: "Search by file name", maxlength: "100", "aria-label": "Search by file name" });
  const list = h("div", { class: "list", "aria-live": "polite" });
  const sheet = openSheet(title, h("div", { style: { display: "grid", gap: "12px" } }, hint ? h("p", { class: "muted" }, hint) : null, input, list));
  async function load() {
    clear(list).append(h("p", { class: "muted" }, "Loading"));
    try {
      const d = await get("/files?limit=30&sort=date&order=desc&q=" + encodeURIComponent(input.value.trim()) + (kind ? "&kind=" + kind : ""));
      clear(list);
      if (!d.items.length) { list.append(h("p", { class: "muted" }, input.value ? "No files match that search." : "No files are indexed yet.")); return; }
      for (const it of d.items) list.append(h("button", { type: "button", class: "rowitem", style: { cursor: "pointer", color: "inherit", font: "inherit", textAlign: "left", width: "100%" }, onclick: () => { sheet.close(); onPick(it); } },
        h("span", { class: "thumb" }, icon(kindIcon(it.kind))), h("span", { class: "rowtext grow" }, h("b", null, it.name), h("span", null, it.category + ", " + fmtBytes(it.size)))));
    } catch (e) { clear(list).append(h("p", { class: "muted", role: "alert" }, errText(e, "Could not load files."))); }
  }
  input.addEventListener("input", debounce(load, 300));
  load();
  return sheet;
}

export function openShareSheet(item, onCreated) {
  let duration = "1h", mode = item.inline ? "view" : "download";
  const body = h("div", { style: { display: "grid", gap: "16px" } });
  const sheet = openSheet("Temporary share", body);
  function chips(label, opts, get_, set, disabledFn) {
    const group = h("div", { role: "radiogroup", "aria-label": label, class: "chips" });
    const paint = () => { for (const b of group.children) b.setAttribute("aria-checked", String(b.dataset.v === get_())); };
    for (const [v, text] of opts) {
      const dis = disabledFn && disabledFn(v);
      group.append(h("button", { type: "button", role: "radio", class: "chip", dataset: { v }, disabled: dis, onclick: () => { set(v); paint(); } }, text));
    }
    paint();
    return h("div", null, h("label", null, label), group);
  }
  const msg = h("p", { class: "form-msg", role: "alert" });
  const create = h("button", { type: "button", class: "btn btn-primary", onclick: () => withBusy(create, async () => {
    msg.textContent = "";
    try {
      const r = await post("/shares", { file_id: item.id, duration, mode });
      showLink(r);
      if (onCreated) onCreated(r);
    } catch (e) { msg.textContent = errText(e, "Could not create the link."); }
  }) }, icon("share", "sm"), "Create link");
  body.append(
    h("p", null, h("b", null, item.name), h("span", { class: "muted" }, "  " + fmtBytes(item.size))),
    chips("Link expires after", DURATIONS, () => duration, (v) => { duration = v; }),
    chips("What the link allows", [["view", "View only"], ["download", "View and download"]], () => mode, (v) => { mode = v; }, (v) => v === "view" && !item.inline),
    item.inline ? null : h("p", { class: "muted" }, "Browsers cannot display this file type, so the link will download it."),
    h("p", { class: "muted" }, LIMITS), msg, create);

  function showLink(r) {
    clear(body);
    const field = h("input", { type: "text", readonly: true, value: r.url, "aria-label": "Share link" });
    const copyBtn = h("button", { type: "button", class: "btn btn-primary", onclick: async () => {
      try { await copyText(r.url); toast("Link copied.", "ok"); } catch (_) { field.select(); toast("Select the link and copy it manually.", "info"); }
    } }, icon("copy", "sm"), "Copy link");
    body.append(
      h("p", { role: "status" }, h("b", null, "Link created.")),
      h("div", { class: "linkbox" }, field, copyBtn),
      h("p", null, "Expires " + fmtDateTime(r.expires_at) + ". " + (r.mode === "view" ? "View only." : "View and download.")),
      h("p", { class: "muted" }, "This link is shown only once because the server keeps just a fingerprint of it. To share again, create a new link. " + LIMITS),
      h("div", { class: "row" }, h("a", { class: "btn", href: "#/shares", onclick: () => sheet.close() }, "Open Temporary Share"), h("button", { class: "btn btn-ghost", type: "button", onclick: () => sheet.close() }, "Done")));
    field.focus(); field.select();
  }
  return sheet;
}

export async function renderShares(ctx) {
  const { main } = ctx;
  let timer = 0;
  const head = h("div", { class: "page-head" }, h("h2", null, "Temporary Share"), h("span", { class: "grow" }),
    h("button", { class: "btn", type: "button", onclick: () => load() }, icon("refresh", "sm"), "Refresh"),
    h("button", { class: "btn btn-primary", type: "button", onclick: () => pickFile({ title: "Choose a file to share", hint: "Each link opens exactly one file.", onPick: (it) => openShareSheet(it, () => load()) }) }, icon("plus", "sm"), "New share"));
  const note = h("div", { class: "panel tight glass", style: { marginBottom: "18px" } }, h("p", { class: "muted" }, LIMITS));
  const body = h("div");
  main.append(head, note, body);

  async function load() {
    clear(body).append(loadingBlock(2));
    try {
      const d = await get("/shares", { signal: ctx.signal });
      if (!ctx.isCurrent()) return;
      paint(d.shares);
    } catch (e) {
      if (!ctx.isCurrent()) return;
      clear(body).append(stateBlock({ kind: "error", title: "Could not load shares", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: load }, "Try again")] }));
    }
  }
  function badge(s) { return h("span", { class: "badge " + ({ active: "badge-ok", expired: "badge-muted", revoked: "badge-bad" }[s.status]) }, { active: "Active", expired: "Expired", revoked: "Revoked" }[s.status]); }
  function expires(s) { return s.status === "active" ? fmtCountdown(s.expires_at) + " (" + fmtDateTime(s.expires_at) + ")" : fmtDateTime(s.expires_at); }
  async function revoke(s, btn) {
    if (!confirm("Revoke this link now? Anyone using it will lose access immediately.")) return;
    await withBusy(btn, async () => {
      try { await del("/shares/" + s.id); toast("Link revoked.", "ok"); load(); } catch (e) { toast(errText(e, "Could not revoke the link."), "error"); }
    });
  }
  function paint(shares) {
    clear(body);
    if (!shares.length) { body.append(stateBlock({ title: "No shares yet", message: "Create a time-limited link for one file. You can revoke it at any time.", actions: [h("button", { class: "btn btn-primary", type: "button", onclick: () => head.querySelector(".btn-primary").click() }, "New share")] })); return; }
    const rows = shares.map((s) => ({ s, rev: () => h("button", { class: "btn btn-sm btn-danger", type: "button", disabled: s.status !== "active", onclick: (e) => revoke(s, e.currentTarget) }, "Revoke") }));
    const table = h("table", { class: "table" }, h("thead", null, h("tr", null, ["File", "Allows", "Status", "Expires", "Opened", ""].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", null, rows.map(({ s, rev }) => h("tr", null, h("td", null, s.file_name || "File removed"), h("td", null, s.mode === "view" ? "View only" : "View and download"), h("td", null, badge(s)), h("td", { dataset: { exp: s.id } }, expires(s)), h("td", null, String(s.access_count)), h("td", null, rev())))));
    body.append(h("div", { class: "tablewrap glass panel tight" }, table));
    body.append(h("div", { class: "cards-m" }, rows.map(({ s, rev }) => h("div", { class: "panel tight glass" }, h("div", { class: "row" }, h("b", { class: "grow" }, s.file_name || "File removed"), badge(s)),
      h("p", { class: "muted" }, (s.mode === "view" ? "View only" : "View and download") + ", opened " + s.access_count + " time(s)"), h("p", { dataset: { exp: s.id } }, expires(s)), h("div", { style: { marginTop: "10px" } }, rev())))));
    clearInterval(timer);
    timer = setInterval(() => { for (const s of shares) { if (s.status === "active" && s.expires_at * 1000 <= Date.now()) s.status = "expired"; } for (const el of body.querySelectorAll("[data-exp]")) { const s = shares.find((x) => x.id === el.dataset.exp); if (s) el.textContent = expires(s); } }, 20000);
  }
  await load();
  return () => clearInterval(timer);
}
