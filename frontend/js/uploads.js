// Uploads. Success is shown only after the server confirms the file is stored. Created By Shiv Yogi.
import { get, uploadFile, NetworkError } from "./api.js";
import { UPLOAD_EXTS } from "./config.js";
import { h, icon, clear, fmtBytes, stateBlock, toast, announce } from "./ui.js";
import { errText } from "./actions.js";

export async function renderUploads(ctx) {
  const { main } = ctx;
  ctx.setTitle("Uploads");
  let cats = [], maxBytes = 0, enabled = true;
  const jobs = [];
  const queue = h("div", { class: "list", "aria-live": "polite" });
  const body = h("div");
  main.append(h("div", { class: "page-head" }, h("h2", null, "Upload to your phone")), body);

  try {
    const [c, dev] = await Promise.all([get("/categories", { signal: ctx.signal }), get("/device/status", { signal: ctx.signal })]);
    if (!ctx.isCurrent()) return;
    cats = c.categories.filter((x) => x.upload_allowed);
    enabled = dev.server.uploads_enabled; maxBytes = dev.server.max_upload_bytes;
  } catch (e) {
    if (!ctx.isCurrent()) return;
    body.append(stateBlock({ kind: "error", title: "Could not check upload settings", message: errText(e, ""), actions: [h("button", { class: "btn", type: "button", onclick: () => ctx.shell.rerender() }, "Try again")] }));
    return;
  }
  if (!enabled || !cats.length) {
    body.append(stateBlock({ kind: "unavailable", title: "Uploads are turned off", message: "The server owner has disabled uploads in the private server config." }));
    return;
  }

  const sel = h("select", { "aria-label": "Destination folder" }, cats.map((c) => h("option", { value: c.name }, c.name + (c.available ? "" : " (folder unavailable)"))));
  const pick = h("input", { type: "file", multiple: true, hidden: true });
  const drop = h("div", { class: "drop", tabindex: "0", role: "button", "aria-label": "Choose files to upload" },
    icon("upload"), h("b", null, "Drop files here or choose them"),
    h("span", { class: "muted" }, "Maximum " + fmtBytes(maxBytes) + " per file. Files are checked by extension and content type before they are stored. They are not scanned for malware."),
    h("button", { class: "btn btn-primary", type: "button", onclick: () => pick.click() }, "Choose files"));
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick.click(); } });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); add([...e.dataTransfer.files]); });
  pick.addEventListener("change", () => { add([...pick.files]); pick.value = ""; });
  body.append(h("div", { class: "toolrow" }, h("label", { for: "up-dest" }, "Save to"), sel), drop, pick, h("h3", { style: { margin: "22px 0 10px" } }, "This session"), queue);
  sel.id = "up-dest";
  queue.append(h("p", { class: "muted", id: "up-empty" }, "No uploads yet."));

  function validate(file, cat) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!file.name.includes(".")) return "Files need an extension.";
    if (file.size === 0) return "The file is empty.";
    if (maxBytes && file.size > maxBytes) return "Larger than the " + fmtBytes(maxBytes) + " limit.";
    const allowed = UPLOAD_EXTS[cat];
    if (allowed && !allowed.includes(ext)) return "." + ext + " files are not allowed in " + cat + ".";
    return null;
  }

  function add(files) {
    if (!files.length) return;
    const cat = sel.value;
    document.getElementById("up-empty")?.remove();
    for (const f of files) {
      const job = { file: f, cat, state: "queued" };
      const bar = h("div", { class: "meter" }, h("i", { style: { width: "0%" } }));
      const status = h("span", { class: "muted", role: "status" });
      const cancel = h("button", { class: "btn btn-sm", type: "button" }, "Cancel");
      const el = h("div", { class: "upitem" }, h("header", null, icon("file"), h("b", { class: "grow" }, f.name), h("span", { class: "muted" }, fmtBytes(f.size)), cancel), bar, status);
      job.el = el; job.bar = bar.firstChild; job.status = status; job.cancel = cancel;
      queue.prepend(el);
      jobs.push(job);
      const bad = validate(f, cat);
      if (bad) { fail(job, bad); continue; }
      job.state = "queued"; status.textContent = "Waiting";
      cancel.onclick = () => { if (job.state === "queued") { job.state = "cancelled"; status.textContent = "Cancelled. Nothing was saved."; cancel.remove(); } else if (job.run) job.run.abort(); };
    }
    pump();
  }
  function fail(job, msg) { job.state = "failed"; job.status.textContent = "Not uploaded: " + msg; job.status.setAttribute("role", "alert"); job.el.style.setProperty("border-color", "rgba(248,113,113,.5)"); job.cancel.remove(); announce("Upload failed: " + job.file.name); }
  let running = false;
  async function pump() {
    if (running) return;
    running = true;
    try {
      for (;;) {
        const job = jobs.find((j) => j.state === "queued");
        if (!job || !ctx.isCurrent()) break;
        job.state = "uploading"; job.status.textContent = "Uploading";
        job.run = uploadFile(job.file, job.cat, (l, t) => { const p = Math.round((l / t) * 100); job.bar.style.width = p + "%"; job.status.textContent = "Uploading " + p + "% (" + fmtBytes(l) + " of " + fmtBytes(t) + ")"; });
        try {
          const r = await job.run.promise;
          job.state = "done"; job.bar.style.width = "100%"; job.cancel.remove();
          job.status.textContent = "Stored" + (r.renamed ? " as " + r.name + " (a file with that name already existed, so nothing was replaced)" : "") + ". Not scanned for malware.";
          toast("Uploaded " + r.name, "ok");
        } catch (e) {
          if (e instanceof NetworkError && e.kind === "aborted") { job.state = "cancelled"; job.status.textContent = e.message; job.cancel.remove(); }
          else fail(job, errText(e, "The upload failed."));
        }
      }
    } finally { running = false; }
  }
  return () => { for (const j of jobs) if (j.state === "uploading" && j.run) j.run.abort(); };
}
