# NEXORA API (v1)

Base: `https://<tunnel-host>/api/v1`. JSON everywhere except file streams. Errors: `{"error":{"code":"...","message":"..."}}`.
Browser calls use `credentials: "include"`. Unsafe methods need `Origin` (allow-listed) and `X-NEXORA-CSRF: 1`. All routes except `health`, `auth/login`, `auth/session` and `s/<token>` need a session.

| Method & path | Purpose |
|---|---|
| `GET /health` | `{status, service, origin_allowed}`. No auth; used to tell "server down" from "origin not allowed". |
| `POST /auth/login` | `{password}` → sets session cookie. 401 wrong password (with attempts left), 429 locked. |
| `POST /auth/logout` | Ends the session. |
| `GET /auth/session` | `{authenticated, ...}`. |
| `GET /dashboard` | Counts, continue watching, recently played, favorites, recently added, storage and server summary. |
| `GET /files` | Query: `category, kind, q, sort(name\|date\|size\|type), order, limit(≤200), offset`. → `{items,total,limit,offset,scan}`. |
| `GET /files/<id>` | One item plus `stream_url, download_url, thumbnail_url`. |
| `GET /files/<id>/stream` | Inline media with `Range`, `If-Range`, `ETag`; `HEAD` supported; 416 on bad ranges. |
| `GET /files/<id>/download` | Same bytes as an attachment. |
| `GET /files/<id>/thumbnail` | JPEG thumbnail / cover art, or 404 `thumbnail_unavailable`. |
| `GET /categories` | Folders: availability, counts, upload permission, last scan. |
| `POST /library/rescan` | Starts a background scan (202) or reports one already running. Rate-limited. |
| `GET /storage` | Library totals, per-folder sizes, volume capacity (as seen by the app). |
| `GET /device/status` | Server info, health, recent errors, and battery / memory / CPU / storage when available, otherwise `{available:false, reason}`. |
| `GET/POST /favorites`, `DELETE /favorites/<id>` | Favorites (`POST {file_id}`). |
| `GET/POST /watchlist`, `DELETE /watchlist/<id>` | Watchlist. |
| `GET /recent` | Recently played, newest first. |
| `POST /playback/progress` | `{file_id, position, duration?, completed?}` for audio/video resume and history. |
| `GET/POST /playlists`, `GET/DELETE /playlists/<id>`, `POST /playlists/<id>/items`, `DELETE /playlists/<id>/items/<file_id>` | Playlists. |
| `POST /uploads` | `multipart/form-data` `category`, `file`. 201 `{id,status:"completed",category,file_id,name,renamed,size,scanned_for_malware:false}`. Errors: 400/403/409/413/415/507. |
| `GET /uploads/<id>` | Status of an upload. |
| `GET/POST /shares`, `DELETE /shares/<id>` | List, create (`{file_id,duration:"15m\|1h\|6h\|24h",mode:"view\|download"}`; the URL is returned once), revoke. |
| `GET /s/<token>` | **Public.** Serves the one shared file while active; `?download=1` only for download-mode shares. 404 once expired or revoked. |
| `GET /activity` | Recent events (no secrets) and failed-login count. |

Status codes used: 200, 201, 202, 206, 304, 400, 401, 403, 404, 405, 409, 413, 415, 416, 429 (with `Retry-After`), 500, 503 (stream slots busy), 507.
