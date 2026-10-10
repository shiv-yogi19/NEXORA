# NEXORA Security Notes

Created By Shiv Yogi. This describes what the code does and does not do. It is not a guarantee: no internet-facing system is unhackable.

## Threat model
**Protected against:** strangers who find the site or tunnel URL; password guessing; cross-site request forgery; path traversal and symlink escape from the library; hostile upload names and types; share-link guessing and reuse after expiry; leaking secrets through the public repository.

**Not protected against:** someone who has the password; malware on the phone or in the browser; Cloudflare itself (it terminates TLS; this is **not** end-to-end encryption); an uploaded file that is malicious *after* you open it in another app (uploads are **not malware-scanned**); a share-link recipient saving or recording the file; a rooted or compromised phone.

## Secrets
- The frontend and the repository contain no password, hash, session secret, tunnel token or API key (`config.example.json` has placeholders only; a secret scan is part of the verification report).
- `init` writes the real config to a **private folder outside the library** with mode 600. It holds a salted **scrypt** hash (PBKDF2-SHA256 fallback) and a random session secret. The plaintext password is never written anywhere.
- Passwords and tokens are never logged; the activity log stores event names and file names only.
- There is no forgot / reset / change-password flow in the web app. Changing the password is an offline command on the phone (`set-password`).

## Authentication and sessions
- Login is verified by the server with constant-time comparison.
- On success the server creates a random 256-bit session token, stores only its **HMAC**, and sets `__Host-nexora_sid` (`HttpOnly; Secure; Path=/; SameSite=None` in production). The token is regenerated at every login. Sessions expire after an idle period and an absolute lifetime and are deleted on logout.
- Login attempts are rate-limited and the failing client IP is locked out after repeated failures (default 5 failures, 15 minutes). Error messages do not say whether anything but the password was wrong.

## Cross-site request protection
- CORS allows only the exact origins in `allowed_origins` and sends credentials only to them.
- Every state-changing request (POST/PUT/PATCH/DELETE) must carry an allowed `Origin` **and** the custom header `X-NEXORA-CSRF: 1`. This is checked before authentication.
- API responses send `Cache-Control: no-store` (media responses use private caching), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

## Filesystem
- Only six configured library folders are reachable. Roots must not overlap each other or the private/thumbnail folders.
- Files are addressed by opaque HMAC ids, never by path. Every serve re-resolves the canonical path and refuses anything that leaves its root, including symlinks that escape. The server never accepts a path from the browser.
- Active content (`.html`, `.svg`, scripts, executables) is never served inline; it is forced to download with `nosniff`.

## Uploads
Size cap checked while streaming; extension allow-list per destination and a global deny list (scripts, executables, HTML/SVG, etc.); magic-byte sniffing for common types; free-space check; written to a **quarantine** folder first, then moved into the library with an exclusive-create so an existing file is **never overwritten** (a numbered name is used instead). Names are normalised (no separators, control characters, dots-only, or reserved names). **There is no antivirus.**

## Temporary share links
Random 256-bit token shown **once**; only its HMAC is stored. Expiry (15 min, 1 h, 6 h, 24 h) and revocation are enforced on the server for every request. A link exposes exactly one file, view-only or view + download, and never any listing. Share endpoints are rate-limited. Expired and revoked rows are purged.

## Network and process
- Binds to `127.0.0.1` by default; the tunnel connector on the same phone forwards to it.
- Flask debug is never enabled. Unhandled errors return a generic message; details go only to the private log.
- Concurrent streams are capped by a semaphore so a few clients cannot exhaust a 2–3 GB phone.

## Frontend
Content-Security-Policy meta tag (scripts from own origin only), no `innerHTML` for data (DOM built with `textContent`), no third-party scripts, no tracking. The only external request is the optional Google Fonts stylesheet; remove it from `index.html` for a fully self-contained site. `localStorage` holds display preferences only.

## Known limitations
Third-party-cookie blocking (see README); in-memory rate limiter resets on restart; the service worker caches only the public shell; share links are bearer secrets; telemetry values come from what Android exposes to Pydroid.
