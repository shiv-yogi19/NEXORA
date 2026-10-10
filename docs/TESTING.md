# Testing NEXORA

## 1. Backend automated tests (no phone needed)
```
cd mobile-server
python3 -W ignore -m unittest discover -s tests
```
96 tests. They build a temporary library and private folder, run the Flask app in-process (and one real subprocess server) and cover: config validation, password hashing, DB migration and backup, login/logout, session expiry, lockout, CSRF/origin checks, CORS, path traversal, symlink escape, Range requests (206/416/If-Range/HEAD), uploads (size, extension, magic bytes, no overwrite, quarantine cleanup), shares (expiry, revoke, hashed tokens, view-only), favorites/watchlist/recent/progress, playlists, telemetry fallbacks, the CLI, and loopback-only binding.

## 2. Browser end-to-end scripts (developer tools)
`mobile-server/tests/e2e/` holds Playwright scripts that drive Chromium against a throwaway server. See the README in that folder. They cover login, library pages, video seek, music, photo viewer, documents, favorites, upload, share create/revoke, the server monitor, the offline screen and automatic recovery, the offline game logic, and horizontal overflow at six screen widths.

## 3. Manual checklist for a real Android phone (you must do this)
Nothing below was tested by the author.

**Server on the phone**
- [ ] `init` and `check` succeed in Pydroid 3; `run` shows the "listening on 127.0.0.1" line.
- [ ] Storage permission is granted; Movies/Music/Photos/Documents folders appear in the Storage page with real counts.
- [ ] Battery card shows a real value or "Unavailable on this device" (never a made-up number). Try with and without Termux:API / pyjnius.
- [ ] Server keeps running with the screen off for 10+ minutes (battery-optimisation exclusion, wake lock).
- [ ] If `waitress` is installed, the server starts with it and still serves Range video.

**Tunnel and cross-site cookies**
- [ ] `https://<tunnel>/api/v1/health` returns JSON from another network (mobile data).
- [ ] From the GitHub Pages site, login succeeds and a page refresh stays logged in (Chrome Android).
- [ ] Repeat in Firefox and Safari; if login "succeeds" and then returns to the login screen, third-party cookies are blocked: use a custom domain with a shared parent (see README).
- [ ] A wrong origin is rejected (the site shows a clear "origin not allowed" message, not "offline").

**Media**
- [ ] A large MP4 (1 GB+) seeks instantly and resumes after closing the tab. Check an H.264 file and a file your browser cannot play: the player must show an honest error.
- [ ] MP3/M4A/FLAC playback with the screen locked; queue, shuffle, repeat, playlists.
- [ ] Photos: pinch zoom, swipe, rotate, slideshow, fullscreen on a phone.
- [ ] PDF: some mobile browsers cannot show PDFs inside a page; confirm "Open in new tab" and "Download" work.
- [ ] Upload a 100 MB+ file over mobile data; cancel one mid-way and check nothing is left in the library; upload the same name twice and confirm it is renamed, not replaced.
- [ ] Share link: open on another device while logged out; confirm it stops working after expiry and after Revoke.

**Offline mode**
- [ ] Stop the server: "NEXORA is Offline" appears, the game plays, Retry Connection works, and starting the server brings the app back without reloading the page.
- [ ] Turn off the phone's network: same behaviour, and no endless spinner.

**Accessibility**
- [ ] TalkBack: login, navigation, player controls, upload list.
- [ ] Keyboard only on desktop: every control reachable; Escape closes sheets and the photo viewer.
- [ ] Reduced-motion setting on the OS shortens the intro and stills animations; Lightweight Mode removes blur.
