# End-to-end browser scripts (developer tools)

These Playwright (Python) scripts drive a real Chromium against a real running `nexora_server.py` and a locally served `frontend/`. They are **not** needed to use NEXORA and must be pointed at a **throwaway test server**, never your real library or password.

Setup used for the verification report:

1. `NEXORA_PRIVATE_DIR=<tmp>/priv NEXORA_LIBRARY_ROOT=<tmp>/lib python3 nexora_server.py init --origin http://localhost:8080 --password-env NEXORA_TEST_PASSWORD --force` (sample media in `<tmp>/lib/{Movies,Music,Photos,Documents}`: a small `.webm` video, `.ogg`/`.mp3` audio, `.jpg` photos, `note.txt`, `doc.pdf`).
2. `python3 nexora_server.py run` (port 8787) and `python3 -m http.server 8080 --directory frontend`.
3. `NEXORA_TEST_PASSWORD=... python3 e2e_features.py <scratch-dir>`.

`e2e_offline_recovery.py` expects `<scratch-dir>/server.pid` and `priv`/`lib` folders as above because it stops and restarts the server. Headless Chromium from Playwright has no H.264, so use WebM for the video check.
