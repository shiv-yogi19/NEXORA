// NEXORA frontend configuration. Created By Shiv Yogi.
//
// This file is PUBLIC (it is served by GitHub Pages). It must never contain a password,
// a password hash, a session secret, a tunnel token or any other credential.
//
// >>> CHANGE THIS ONE VALUE <<<
// Set API_BASE to the HTTPS address of your Cloudflare Tunnel, with no trailing slash,
// for example "https://nexora.example.com". It is the public address that forwards to the
// Python server on your phone.
export const CONFIG = {
  API_BASE: "https://YOUR-TUNNEL-HOSTNAME.example.com",
};

export const APP_NAME = "NEXORA";
export const APP_VERSION = "1.0.0";
export const CREATOR = "Created By Shiv Yogi";

// Extensions the server accepts per destination. This only drives early, friendly checks in the
// browser; the server repeats every check and is the authority.
export const UPLOAD_EXTS = {
  Movies: ["mp4", "m4v", "webm", "mkv", "mov", "avi", "3gp"],
  Music: ["mp3", "m4a", "aac", "flac", "wav", "ogg", "oga", "opus"],
  Photos: ["jpg", "jpeg", "png", "gif", "webp", "bmp", "avif"],
  Documents: ["pdf", "txt", "md", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "epub"],
};
UPLOAD_EXTS.Uploads = [...UPLOAD_EXTS.Movies, ...UPLOAD_EXTS.Music, ...UPLOAD_EXTS.Photos, ...UPLOAD_EXTS.Documents];

const PLACEHOLDER = /YOUR-TUNNEL/i;

/** Resolve the backend origin. A `?api=` override is honoured ONLY when this page itself is served from localhost,
 *  so a crafted link on the public site can never point the login form at someone else's server. */
export function resolveApiBase() {
  let base = CONFIG.API_BASE;
  try {
    const host = location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      const override = new URLSearchParams(location.search).get("api");
      if (override && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?$/.test(override)) base = override;
    }
  } catch (_) { /* ignore */ }
  return base.replace(/\/+$/, "");
}

export function isConfigured() {
  return !PLACEHOLDER.test(resolveApiBase());
}
