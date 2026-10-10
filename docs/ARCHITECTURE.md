# NEXORA Architecture

```
 Browser ── https://<user>.github.io (static frontend, GitHub Pages)
    │
    │  fetch / <video> / <audio> / <img> with cookie (HTTPS, CORS allow-list)
    ▼
 Cloudflare edge ── Tunnel ──► cloudflared on the phone ──► http://127.0.0.1:8787
                                                             │
                                                  nexora_server.py (Flask)
                                                  ├─ SQLite (WAL) : sessions, favorites, playlists, history, shares, activity
                                                  ├─ Library folders (allow-list): Movies Music Photos Documents Uploads Downloads
                                                  └─ Private folder: config, database, logs, quarantine
```

## Backend (single file, `mobile-server/nexora_server.py`)
Sections: configuration + validation → SQLite with versioned migrations (backup before upgrade) → security helpers (scrypt, HMAC, rate limiter, lockout, path guard) → library scanner (background thread, generation ids, per-folder status) → request hooks (origin/CSRF, CORS, session, headers) → routes → CLI (`init`, `check`, `set-password`, `run`). It uses waitress when installed, otherwise Werkzeug's threaded server.

## Frontend (`frontend/`)
Vanilla ES modules, no build step.
- `app.js` — boot, intro, hash router, shell, connection banner, offline screen, polling, recovery.
- `api.js` — requests with timeouts, error classes, **connection state machine** (online / offline / connecting / reconnecting / degraded) with reasons; capped backoff (5 s, 15 s, 45 s, 120 s, then stop and wait for Retry); pauses when the tab is hidden.
- `ui.js` — DOM builder, icons, formatting, toasts, sheets, preferences.
- `auth.js`, `library.js`, `players.js`, `uploads.js`, `shares.js`, `server-monitor.js`, `settings.js`, `dashboard.js`, `actions.js`, `offline-game.js` — screens and features.
- `service-worker.js` — caches the public shell only; ignores every cross-origin request.

## Data flow rules
1. The frontend never invents data: every list, number and status is a server response or an explicit "Unavailable" state.
2. Success is shown only after the server confirms (uploads, share creation, favorites).
3. A failed request moves the connection state machine; a failed `/health` probe plus a reachable server means "degraded" (for example origin not allowed), never "offline".
4. Media elements load `/files/<id>/stream` directly with the session cookie, so seeking is handled by HTTP Range, not by JavaScript.

## Responsive design
Three layouts: desktop (≥1100 px sidebar + toolbar), tablet (700–1099 px icon rail), mobile (<700 px top bar + bottom navigation + mini-player above it).
