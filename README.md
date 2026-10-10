# NEXORA — Your Personal Media Universe

**Created By Shiv Yogi**

NEXORA is a private media web app in two independent parts:

| Part | Where it runs | Folder |
|---|---|---|
| **Frontend** (static website, English) | GitHub Pages | `frontend/` |
| **Backend** (`nexora_server.py`, Flask + SQLite) | Your Android phone, in Pydroid 3 | `mobile-server/` |

The website holds **no media, no password and no secret**. It only talks to your phone's server through a Cloudflare Tunnel that you set up yourself. If the phone is off, the site shows **"NEXORA is Offline"** and a small offline game instead of fake data.

## What you get
Animated intro and credit, password login (checked by the server), Liquid Glass UI with separate phone / tablet / desktop layouts, Movies (Range seeking, resume), Music (queue, shuffle, repeat, playlists, mini and expanded player), Photos (zoom, rotate, fit, full screen, slideshow, thumbnail strip), Documents (PDF and text viewer, honest "cannot preview" for other formats), uploads with real progress, Favorites / Watchlist / Recent, temporary share links (15 min – 24 h, revocable), Storage explorer, Mobile Server monitor, Activity log, Lightweight Mode, reduced motion, and an offline mode with a playable game.

## Quick start (about 20 minutes)

### 1. Put the backend on the phone
Follow **[mobile-server/README-PYDROID.md](mobile-server/README-PYDROID.md)**. In short: install Flask in Pydroid 3, copy `nexora_server.py` to the phone, run `init` (it asks for your password and writes the private config), then `run`.

### 2. Expose it with a Cloudflare Tunnel
The tunnel is configured by you, separately (Cloudflare account, `cloudflared` or a Zero Trust tunnel, a hostname that points to `http://127.0.0.1:8787`). This project does not contain or need a tunnel token. See the Pydroid guide, section "Cloudflare Tunnel".

### 3. Point the frontend at your tunnel
Edit **one line** in `frontend/js/config.js`:

```js
API_BASE: "https://nexora.your-domain.example",   // your tunnel hostname, no trailing slash
```

### 4. Publish the frontend on GitHub Pages
1. Create a GitHub repository and push this project.
2. Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. The included workflow `.github/workflows/pages.yml` publishes only the `frontend/` folder on every push to `main`.
4. Your site appears at `https://<username>.github.io/<repo>/`.

### 5. Tell the server which website may talk to it
The server only accepts requests from the website origin you give it (scheme + host, **no path**): `https://<username>.github.io`. Pass it to `init --origin ...`, or edit `allowed_origins` in the private config and restart.

### 6. Open the site and log in
The intro plays, then the login screen asks for the password you chose in step 1.

## Cross-site cookies: read this
GitHub Pages (`github.io`) and your tunnel hostname are different sites, so the session cookie is a *third-party* cookie (`Secure; HttpOnly; SameSite=None`). Chrome on Android currently allows this, but **Safari, Firefox and some browser privacy settings block third-party cookies**, which would make login appear to succeed and then fail. The most robust fix is a **custom domain with a shared parent**: for example site `https://media.example.com` (GitHub Pages custom domain) and API `https://api.media.example.com` (tunnel). Both are then the same site and cookies are first-party. Set `allowed_origins` to the site origin.

## Honest limits
- Not "unhackable", and not end-to-end encrypted. HTTPS is provided by Cloudflare, which terminates it in front of your phone.
- Uploads are validated (type, size, extension allow-list, magic bytes) and quarantined, but **not malware-scanned**.
- A temporary share link can be saved, copied or recorded by whoever opens it; "view only" cannot prevent that.
- Android may stop Pydroid 3 in the background. Battery-optimisation exclusion and a wake lock are your responsibility.
- Real Android + Pydroid 3 + Cloudflare behaviour was **not** tested by the author; see [docs/VERIFICATION_REPORT.md](docs/VERIFICATION_REPORT.md).
- No licence has been chosen; add one before you make the repository public if you want others to reuse it.

## Documentation
| File | Contents |
|---|---|
| [mobile-server/README-PYDROID.md](mobile-server/README-PYDROID.md) | Phone setup, tunnel, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, controls, limits |
| [docs/API.md](docs/API.md) | Every endpoint |
| [docs/TESTING.md](docs/TESTING.md) | How to run tests; manual device checklist |
| [docs/FILES.md](docs/FILES.md) | File-by-file explanation |
| [docs/VERIFICATION_REPORT.md](docs/VERIFICATION_REPORT.md) | What was tested and what was not |
