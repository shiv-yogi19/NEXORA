# Verification report

Date of run: 2026-10-10. Environment: Linux cloud container, Python 3.13, Flask, Werkzeug threaded server, Playwright Chromium 141 (headless). **No Android device, Pydroid 3 or Cloudflare Tunnel was available.**

## A. Tests that were actually run
| Area | Result |
|---|---|
| Backend unit + integration suite (96 tests) | All pass |
| `node --check` on all 14 JavaScript files | No syntax errors |
| Manifest JSON, local asset references in `index.html`/`404.html` | Valid; all referenced files exist |
| Secret scan of the repository (excluding tests/docs) | No password, hash, session secret or token found; `config.example.json` holds placeholders only |
| Browser: intro shows "Created By Shiv Yogi", skip works, login screen | Pass |
| Browser: wrong password shows a server message and stays logged out; correct password enters the app | Pass |
| Browser: Home counts match the real files; all 15 routes render without script errors | Pass |
| Browser: WebM video loads, seeks through Range requests, progress saved and shown under Continue watching | Pass |
| Browser: audio plays from the mini player and progress advances | Pass |
| Browser: photo viewer next, rotate, zoom, slideshow toggle, close | Pass |
| Browser: text document viewer; PDF opens in an iframe | Pass (PDF rendering inside the page not visually confirmed) |
| Browser: favorite persists on the server | Pass |
| Browser: upload stored only after server confirmation; wrong extension rejected; duplicate name renamed, not replaced | Pass |
| Browser: share link opens without login; after Revoke it returns 404 | Pass |
| Browser: Mobile Server page shows real values and "Unavailable on this device" for battery | Pass |
| Browser: server stopped, "NEXORA is Offline" appears, Retry stays offline, game opens, server restarted, app recovers **without page reload** | Pass |
| Offline game logic (score, jump, landing, collision, restart, pause) | Pass |
| No horizontal scroll on 12 routes at 360, 390, 430, 768, 1024 and 1440 px wide (reduced-motion enabled) | Pass |

Console: no JavaScript errors during the runs. The only network errors were the Google Fonts request (no internet in the container, so the fallback font was used) and one expected 401 for the pre-login session check.

## B. Not tested; you must check on real hardware
- Android + Pydroid 3 behaviour (storage permission, background stopping, wake lock), and the `waitress` server path (not installed in the container).
- Battery telemetry via Termux:API or pyjnius, and memory/CPU on Android. Only the Linux sources were exercised.
- Cloudflare Tunnel, real HTTPS, and the cross-site cookie setup (`Secure; SameSite=None`) between `github.io` and your tunnel. The browser run used `localhost` with a same-site Lax cookie. Third-party-cookie blocking in Safari, Firefox and some Chrome settings is a known risk (see README).
- Firefox, Safari and iOS. Only Chromium was run.
- H.264/AAC playback (headless Chromium has no H.264; WebM and Ogg were used), very large files, slow or interrupted mobile uploads.
- The audio visualizer's behaviour with real cross-origin audio, touch gestures (pinch and swipe), the service worker, installing as an app, screen readers, and Lighthouse scores.
- Fonts from Google Fonts (blocked in the container).

## C. Known behaviours to be aware of
- Inside the PDF preview, the browser's PDF viewer captures the keyboard, so Escape may not close the sheet; use the Close button.
- After leaving a video, Continue watching may need a moment or a Refresh to show the newest position.
- Mobile browsers that cannot render PDFs in a page show a blank frame; the sheet offers Open in new tab and Download.
- Uploads are validated, quarantined and never overwrite files, but are **not** scanned for malware. NEXORA is not "unhackable" and is not end-to-end encrypted.
