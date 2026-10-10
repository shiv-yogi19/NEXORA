# NEXORA Mobile Server — Pydroid 3 setup

Created By Shiv Yogi. Requirements: Android phone with 2–3 GB RAM, Pydroid 3, Python 3.9+ (Pydroid ships 3.11+). No root, Docker or Node.

## 1. Install
1. In Pydroid 3 open **☰ → Pip**, install **flask**. Optional extras: `waitress` (recommended), `psutil`, `Pillow` (thumbnails). If one fails to build, skip it; the server reports the feature as unavailable instead of failing.
2. Copy `nexora_server.py` to the phone (for example into Pydroid's own folder). Open it in Pydroid 3.
3. Allow Pydroid 3 to access storage (Android Settings → Apps → Pydroid 3 → Permissions → Files / "All files access" if you keep media in shared storage).

## 2. Create the private configuration (once)
Run the script with the argument `init`. In Pydroid 3 use **☰ → Run with arguments**, or from a Pydroid terminal:

```
python nexora_server.py init --origin https://YOUR-USERNAME.github.io
```

`init` will:
- ask for a password (at least 10 characters; a passphrase is best; typing is hidden) — the password is **never stored**, only a salted scrypt hash;
- create the private folder (`~/NEXORA_PRIVATE`, not visible to other apps) containing `Config/config.json` (hash + random session secret, mode 600), `Database`, `Logs`, `Quarantine`;
- create the library folder, by default `/storage/emulated/0/NEXORA/` with `Movies  Music  Photos  Documents  Uploads  Downloads`.

Then check it: `python nexora_server.py check`.

**The private folder must never be copied into GitHub.** The included `.gitignore` already excludes it.

## 3. Add your media
Copy files into the library folders with any file manager. Only these folders are visible to NEXORA. After copying, open **Storage → Rescan library** in the web app (or restart the server).

## 4. Run
`python nexora_server.py run` (also the default command). It binds to `127.0.0.1:8787` — reachable only from the phone itself — and uses `waitress` when installed. Keep the Pydroid screen on or exempt Pydroid 3 from battery optimisation; Android may kill background apps. Stop with Ctrl+C or Pydroid's stop button; shutdown is clean.

The server never runs Flask debug mode.

## 5. Cloudflare Tunnel (configured by you, separately)
1. A Cloudflare account and a domain managed there.
2. Create a tunnel (Zero Trust dashboard → Networks → Tunnels, or `cloudflared tunnel create`).
3. Add a public hostname, for example `nexora.example.com`, with service **`http://127.0.0.1:8787`**.
4. Run the connector on the phone (for example `cloudflared` in Termux). Keep the tunnel token **private**; it never goes into this project.
5. Put the hostname in `frontend/js/config.js` (`API_BASE`) and in the private config as `public_base_url` (used to build share links).
6. Optional hardening: protect the hostname with Cloudflare Access in addition to the NEXORA password. Be aware that Access also affects the cross-origin requests from your site, so test it.

The server reads the visitor IP from `CF-Connecting-IP` only when a request arrives from the phone's loopback address (that is, through the local tunnel connector), so lockouts and logs see real client addresses and the header cannot be spoofed from outside.

## 6. Change the password
`python nexora_server.py set-password` (offline, on the phone). Add `--rotate-secret` to also sign out every session. There is intentionally no "forgot password" or in-app password change.

## 7. Troubleshooting
| Symptom | Likely cause |
|---|---|
| Site shows "NEXORA is Offline" | Server not running, tunnel down, phone asleep, or wrong `API_BASE`. Open `https://<tunnel>/api/v1/health` in a browser. |
| Health says `origin_allowed: false` | `allowed_origins` is missing your exact site origin (no path, no trailing slash). |
| Login works then immediately logs out | Browser blocks third-party cookies; use a custom domain with shared parent (see main README). |
| Folder "not available / permission" | Grant Pydroid 3 storage access; check the folder exists. |
| No thumbnails | Install Pillow, or accept icon placeholders. |
| Battery / memory shows "Unavailable on this device" | The phone does not expose it to Pydroid. This is reported honestly, never faked. |
| Server stops after a while | Android battery optimisation; exclude Pydroid 3 and keep it foreground. |
