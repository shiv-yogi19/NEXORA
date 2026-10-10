# File-by-file guide

## Root
- `README.md` – overview, GitHub Pages and phone setup, limits.
- `.gitignore` – keeps private config, databases, logs and caches out of Git.
- `.github/workflows/pages.yml` – publishes only `frontend/` to GitHub Pages.

## `frontend/` (public, static)
- `index.html` – page skeleton: intro, login, offline screen, app shell, overlays, CSP meta tag.
- `404.html` – friendly page for unknown paths on GitHub Pages.
- `manifest.webmanifest`, `service-worker.js` – installable shell. The service worker caches only this site's own files and never intercepts API or media requests.
- `assets/` – logo, favicon and app icons.
- `css/style.css` – Liquid Glass design system, components, light/lightweight/reduced-motion modes.
- `css/responsive.css` – separate desktop (sidebar), tablet (icon rail) and mobile (bottom bar) layouts.
- `js/config.js` – **the one file you edit**: `API_BASE` (your tunnel URL) and upload type lists. Contains no secrets.
- `js/ui.js` – DOM builder (no `innerHTML` for data), icons, formatting, toasts, sheets, preferences.
- `js/api.js` – every request to the server: timeouts, connection state machine, recovery, upload with progress.
- `js/auth.js` – login form and session check. The password is only sent to the server.
- `js/app.js` – intro, router, navigation, connection banner, offline screen, polling.
- `js/offline-game.js` – "Nova Run", the original offline game.
- `js/dashboard.js` – Home. `js/library.js` – category/collection/search pages, photo viewer, document viewer.
- `js/players.js` – audio engine, mini and expanded player, playlists, video watch page.
- `js/actions.js` – favorites, watchlist, download. `js/shares.js` – temporary share sheet and center.
- `js/uploads.js` – upload page. `js/server-monitor.js` – Mobile Server and Storage pages. `js/settings.js` – Settings, Activity, About.

## `mobile-server/` (runs on the phone, never published)
- `nexora_server.py` – the whole backend: config, password hashing, sessions, CSRF/origin checks, rate limits, library scan, streaming, uploads, shares, telemetry, CLI.
- `README-PYDROID.md` – phone setup and tunnel guide. `requirements.txt` – Python packages. `config.example.json` – shape of the private config; contains **no** usable credentials.
- `tests/test_backend.py` – 96 backend tests. `tests/e2e/` – browser scripts.

## `docs/`
`ARCHITECTURE.md`, `SECURITY.md`, `API.md`, `TESTING.md`, this file, and `VERIFICATION_REPORT.md`.
