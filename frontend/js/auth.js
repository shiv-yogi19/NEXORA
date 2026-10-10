// NEXORA login flow. Created By Shiv Yogi.
// The password is sent to the backend over HTTPS and is never stored, logged, or kept after the request.
// Whether you are logged in is decided only by the server's session cookie, never by a flag in this page.
import { get, post, ApiError, NetworkError, conn, checkNow, apiBase } from "./api.js";
import { isConfigured } from "./config.js";
import { icon, announce, $ } from "./ui.js";

export async function checkSession() {
  // Returns {authenticated:boolean}. Throws NetworkError when the server cannot be reached.
  return get("/auth/session", { timeout: 8000 });
}
export async function logout() {
  try { await post("/auth/logout", {}); } catch (_) { /* the cookie may already be invalid */ }
}

export function initLogin({ onSuccess, onPlayGame }) {
  const form = $("#login-form"), input = $("#login-password"), msg = $("#login-msg"), submit = $("#login-submit");
  const toggle = $("#login-toggle"), off = $("#login-offline"), offText = $("#login-offline-text");
  toggle.append(icon("eye"));
  toggle.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(show));
    toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
    toggle.replaceChildren(icon(show ? "eyeOff" : "eye"));
    input.focus();
  });
  $("#login-game").addEventListener("click", onPlayGame);
  $("#login-retry").addEventListener("click", async (e) => {
    const b = e.currentTarget; b.disabled = true;
    const ok = await checkNow({ manual: true });
    b.disabled = false;
    setOffline(!ok);
    if (ok) { msg.textContent = ""; announce("Server reachable. You can log in."); input.focus(); }
  });

  function setOffline(isOff) {
    off.hidden = !isOff;
    if (!isOff) return;
    if (!isConfigured()) offText.textContent = "This website has not been pointed at your server yet. Set API_BASE in js/config.js to your tunnel address (see the README), then reload.";
    else if (conn.reason === "origin") offText.textContent = "The server is running but it does not allow this website address. Add " + location.origin + " to allowed_origins in the server's private config, then restart the server.";
    else offText.textContent = "The server could not be reached. It may be stopped, or the tunnel, your network, DNS or TLS may be the problem.";
  }

  let busy = false;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    msg.className = "form-msg"; msg.textContent = "";
    const pw = input.value;
    if (!pw) { msg.textContent = "Enter your password."; input.focus(); return; }
    busy = true; submit.disabled = true; submit.setAttribute("aria-busy", "true");
    $(".spinner", submit).hidden = false; $(".btn-label", submit).textContent = "Checking";
    try {
      await post("/auth/login", { password: pw }, { timeout: 20000, quiet: true });
      input.value = "";
      setOffline(false);
      onSuccess();
    } catch (err) {
      input.select();
      if (err instanceof ApiError && err.code === "invalid_credentials") {
        msg.textContent = "Incorrect password." + (err.data && err.data.attempts_remaining !== undefined ? " " + err.data.attempts_remaining + " attempt(s) left before a temporary lock." : "");
      } else if (err instanceof ApiError && (err.code === "locked" || err.code === "rate_limited")) {
        const mins = Math.max(1, Math.ceil((err.retryAfter || 60) / 60));
        msg.className = "form-msg warn";
        msg.textContent = err.code === "locked" ? `Too many wrong passwords. Login is locked for about ${mins} minute(s). Try again later.` : "Too many attempts. Wait a moment and try again.";
      } else if (err instanceof ApiError && err.code === "csrf_failed") {
        msg.textContent = "The server rejected this website's address. Add " + location.origin + " to allowed_origins in the server config.";
        setOffline(true);
      } else if (err instanceof NetworkError || (err instanceof ApiError && err.status >= 500)) {
        msg.textContent = "Could not reach the server, so no login was attempted.";
        await checkNow({ manual: true });
        setOffline(true);
      } else {
        msg.textContent = err.message || "Login failed.";
      }
      announce(msg.textContent);
    } finally {
      busy = false; submit.disabled = false; submit.removeAttribute("aria-busy");
      $(".spinner", submit).hidden = true; $(".btn-label", submit).textContent = "Log in";
    }
  });
  return { setOffline, focus: () => input.focus(), apiBase };
}
