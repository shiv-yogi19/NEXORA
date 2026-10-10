#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXORA Mobile Server  -  Created By Shiv Yogi
=============================================

Private media backend for NEXORA, designed to run in Pydroid 3 on Android.

Quick start (details in README-PYDROID.md):

    python nexora_server.py init          # one-time: create folders + private config + password hash
    python nexora_server.py check         # validate the private configuration
    python nexora_server.py run           # start the server (default command)
    python nexora_server.py set-password  # change the password (private, offline procedure)

Security model in one paragraph: the server binds to localhost by default,
every private route needs a server-side session (random token in an HttpOnly
cookie; only an HMAC of it is stored), state-changing requests must come from
an allow-listed website origin, files are only served from explicitly
configured library folders (canonical-path checks, no symlink escapes), uploads
go through a private quarantine folder, and temporary shares use separate
random tokens (only HMACs stored). HTTPS is provided by the Cloudflare Tunnel,
not by this script.

This file is intentionally a single module so it can be copied to a phone.
"""
from __future__ import annotations

import argparse
import base64
import collections
import getpass
import hashlib
import hmac
import ipaddress
import json
import logging
import logging.handlers
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

try:
    from flask import Flask, Response, g, jsonify, request
    from werkzeug.exceptions import HTTPException
except ImportError:  # pragma: no cover - startup guidance
    sys.stderr.write(
        "NEXORA needs Flask. In Pydroid 3 open the 'Pip' menu and install: flask\n"
        "(or run: pip install flask)\n"
    )
    raise SystemExit(2)

try:  # optional: richer telemetry
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None

try:  # optional: thumbnails
    from PIL import Image  # type: ignore

    Image.MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard
except Exception:  # noqa: BLE001
    Image = None

VERSION = "1.0.0"
SERVICE = "nexora"
START_TIME = time.time()
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------
# Constants: file types
# --------------------------------------------------------------------------
CATEGORY_NAMES = ["Movies", "Music", "Photos", "Documents", "Uploads", "Downloads"]

VIDEO_EXTS = {"mp4", "m4v", "webm", "mkv", "mov", "avi", "3gp"}
AUDIO_EXTS = {"mp3", "m4a", "aac", "flac", "wav", "ogg", "oga", "opus"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "avif"}
DOC_EXTS = {"pdf", "txt", "md", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "epub"}
TEXT_EXTS = {"txt", "md", "csv"}

# Never accepted as uploads, regardless of configuration.
DENY_EXTS = {
    "py", "pyc", "pyw", "sh", "bash", "zsh", "bat", "cmd", "com", "exe", "dll", "so", "apk", "xapk",
    "aab", "jar", "js", "mjs", "cjs", "html", "htm", "xhtml", "php", "phtml", "pl", "rb", "ps1", "vbs",
    "msi", "scr", "lnk", "desktop", "svg", "swf", "jsp", "asp", "aspx", "cgi", "war", "dex", "elf",
    "bin", "ipa", "dmg", "appimage",
}

MIME_BY_EXT = {
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mkv": "video/x-matroska",
    "mov": "video/quicktime", "avi": "video/x-msvideo", "3gp": "video/3gpp",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac",
    "wav": "audio/wav", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "avif": "image/avif",
    "pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8", "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text", "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation", "epub": "application/epub+zip",
}
# Types the browser may render inline. Everything else is always an attachment.
INLINE_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | {"pdf", "txt", "md"}

ART_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "albumart.jpg")

DEFAULT_RATES = {
    "api_per_minute": 1200,
    "login_per_minute": 10,
    "upload_per_hour": 60,
    "share_create_per_minute": 30,
    "share_access_per_minute": 60,
    "rescan_per_minute": 6,
}

SHARE_DURATIONS = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440}


def kind_for_ext(ext: str) -> str:
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOC_EXTS:
        return "document"
    return "other"


def mime_for_ext(ext: str) -> str:
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def now_s() -> int:
    return int(time.time())


# --------------------------------------------------------------------------
# Password hashing (stdlib only): scrypt, with a PBKDF2 fallback
# --------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """Return a salted password hash string. Never store the password itself."""
    salt = os.urandom(16)
    if hasattr(hashlib, "scrypt"):
        try:
            n, r, p = 2 ** 14, 8, 1
            dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)
            return "scrypt$%d$%d$%d$%s$%s" % (n, r, p, _b64e(salt), _b64e(dk))
        except (ValueError, MemoryError):
            pass
    iters = 600_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, 32)
    return "pbkdf2_sha256$%d$%s$%s" % (iters, _b64e(salt), _b64e(dk))


def verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if parts[0] == "scrypt" and len(parts) == 6:
            n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            salt, expected = _b64d(parts[4]), _b64d(parts[5])
            dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=len(expected))
            return hmac.compare_digest(dk, expected)
        if parts[0] == "pbkdf2_sha256" and len(parts) == 4:
            iters = int(parts[1])
            salt, expected = _b64d(parts[2]), _b64d(parts[3])
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, len(expected))
            return hmac.compare_digest(dk, expected)
    except (ValueError, AttributeError, TypeError, MemoryError):
        return False
    return False


def password_hash_is_valid(stored: object) -> bool:
    if not isinstance(stored, str):
        return False
    parts = stored.split("$")
    return (parts[0] == "scrypt" and len(parts) == 6) or (parts[0] == "pbkdf2_sha256" and len(parts) == 4)


# --------------------------------------------------------------------------
# Paths and configuration
# --------------------------------------------------------------------------
def default_paths() -> tuple[Path, Path]:
    """Return (private_dir, library_root) defaults.

    The private folder defaults to the app-private home directory (in Pydroid 3
    this is not visible to other apps). The library defaults to shared storage
    so that you can copy media into it with a file manager.
    """
    home = Path(os.path.expanduser("~"))
    private = Path(os.environ.get("NEXORA_PRIVATE_DIR") or (home / "NEXORA_PRIVATE"))
    shared = Path("/storage/emulated/0")
    lib_env = os.environ.get("NEXORA_LIBRARY_ROOT")
    library = Path(lib_env) if lib_env else ((shared / "NEXORA") if shared.is_dir() else (home / "NEXORA"))
    return private, library


def config_path_for(private_dir: Path) -> Path:
    env = os.environ.get("NEXORA_CONFIG")
    return Path(env) if env else private_dir / "Config" / "config.json"


def _is_within(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


FORBIDDEN_ROOTS = {"/", "/storage", "/storage/emulated", "/storage/emulated/0", "/sdcard", "/data", "/system"}


def build_config(raw: dict, private_dir: Path) -> tuple[SimpleNamespace | None, list[str], list[str]]:
    """Validate raw JSON config and build a runtime config. Returns (cfg, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, ["Configuration file must contain a JSON object."], warnings

    def num(key, default, lo, hi):
        val = raw.get(key, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not (lo <= val <= hi):
            errors.append("'%s' must be a number between %s and %s." % (key, lo, hi))
            return default
        return val

    # --- secrets ---------------------------------------------------------
    if not password_hash_is_valid(raw.get("password_hash")):
        errors.append("'password_hash' is missing or invalid. Run: python nexora_server.py init (or set-password).")
    secret = raw.get("session_secret")
    if not isinstance(secret, str) or len(secret) < 48 or "CHANGE" in secret.upper():
        errors.append("'session_secret' is missing, too short (need 48+ characters) or a placeholder. Run: python nexora_server.py init.")

    # --- origins & cookies ----------------------------------------------
    origins = raw.get("allowed_origins")
    clean_origins: list[str] = []
    if not isinstance(origins, list) or not origins:
        errors.append("'allowed_origins' must list your website origin, e.g. [\"https://yourname.github.io\"].")
    else:
        for o in origins:
            if not isinstance(o, str) or not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?", o):
                errors.append("Invalid allowed origin %r (use scheme://host[:port], no path, no trailing slash, no wildcard)." % (o,))
                continue
            host = urllib.parse.urlsplit(o).hostname or ""
            if o.startswith("http://") and host not in ("localhost", "127.0.0.1"):
                warnings.append("Origin %s is plain HTTP; use HTTPS in production." % o)
            clean_origins.append(o)

    cookie_secure = bool(raw.get("cookie_secure", True))
    samesite = raw.get("cookie_samesite", "None" if cookie_secure else "Lax")
    if samesite not in ("None", "Lax", "Strict"):
        errors.append("'cookie_samesite' must be None, Lax or Strict.")
        samesite = "Lax"
    if samesite == "None" and not cookie_secure:
        errors.append("cookie_samesite 'None' requires cookie_secure true (browsers reject it otherwise).")

    # --- network -----------------------------------------------------------
    bind_host = str(raw.get("bind_host", "127.0.0.1"))
    port = int(num("port", 8787, 1024, 65535))
    if bind_host not in ("127.0.0.1", "::1", "localhost"):
        warnings.append("bind_host %s exposes the server beyond this phone without TLS. Prefer 127.0.0.1 plus a Cloudflare Tunnel." % bind_host)

    # --- library roots -----------------------------------------------------
    lib_root = raw.get("library_root")
    if not isinstance(lib_root, str) or not lib_root.strip():
        errors.append("'library_root' is required (the NEXORA media folder).")
        lib_root = ""
    overrides = raw.get("categories", {}) or {}
    roots: dict[str, str] = {}
    if lib_root:
        for name in CATEGORY_NAMES:
            sub = overrides.get(name, name) if isinstance(overrides, dict) else name
            if not isinstance(sub, str) or not sub.strip():
                errors.append("categories.%s must be a folder name or absolute path." % name)
                continue
            path = sub if os.path.isabs(sub) else os.path.join(lib_root, sub)
            real = os.path.realpath(path)
            if real in FORBIDDEN_ROOTS or real == os.path.realpath(os.path.expanduser("~")):
                errors.append("Library folder for %s is too broad (%s). Use a dedicated NEXORA folder." % (name, name))
                continue
            roots[name] = real
    names = list(roots)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if _is_within(roots[a], roots[b]) or _is_within(roots[b], roots[a]):
                errors.append("Library folders %s and %s overlap; each category needs its own separate folder." % (a, b))
    priv_real = os.path.realpath(str(private_dir))
    thumbs = os.path.realpath(raw.get("thumbnails_dir") or os.path.join(lib_root or str(private_dir), "Thumbnails"))
    for name, real in roots.items():
        if _is_within(priv_real, real) or _is_within(real, priv_real):
            errors.append("Private folder must not be inside (or contain) the %s library folder." % name)
        if _is_within(thumbs, real) or _is_within(real, thumbs):
            errors.append("Thumbnails folder must not overlap the %s library folder." % name)

    upload_cats = raw.get("upload_categories", ["Uploads", "Movies", "Music", "Photos", "Documents"])
    if not isinstance(upload_cats, list) or any(c not in CATEGORY_NAMES or c == "Downloads" for c in upload_cats):
        errors.append("'upload_categories' may only contain: Movies, Music, Photos, Documents, Uploads.")
        upload_cats = ["Uploads"]
    extra_exts = raw.get("extra_upload_extensions", [])
    if not isinstance(extra_exts, list) or any(not isinstance(e, str) or not re.fullmatch(r"[a-z0-9]{1,8}", e) or e in DENY_EXTS for e in extra_exts):
        errors.append("'extra_upload_extensions' must be lowercase extensions that are not on the built-in deny list.")
        extra_exts = []

    rates = dict(DEFAULT_RATES)
    if isinstance(raw.get("rate_limits"), dict):
        for k, v in raw["rate_limits"].items():
            if k in rates and isinstance(v, int) and v > 0:
                rates[k] = v

    cfg = SimpleNamespace(
        raw_version=raw.get("version", 1),
        private_dir=Path(priv_real),
        db_path=Path(priv_real) / "Database" / "nexora.db",
        quarantine_dir=Path(priv_real) / "Quarantine",
        logs_dir=Path(priv_real) / "Logs",
        thumbs_dir=Path(thumbs),
        library_root=os.path.realpath(lib_root) if lib_root else "",
        roots=roots,
        password_hash=raw.get("password_hash", ""),
        secret=(secret if isinstance(secret, str) else "").encode("utf-8"),
        allowed_origins=clean_origins,
        cookie_secure=cookie_secure,
        cookie_samesite=samesite,
        session_seconds=int(num("session_hours", 12, 1, 24 * 30) * 3600),
        idle_seconds=int(num("idle_minutes", 240, 5, 24 * 60 * 30) * 60),
        bind_host=bind_host,
        port=port,
        public_base_url=str(raw.get("public_base_url", "") or "").rstrip("/"),
        trust_proxy_headers=bool(raw.get("trust_proxy_headers", True)),
        uploads_enabled=bool(raw.get("uploads_enabled", True)),
        upload_categories=upload_cats,
        extra_upload_extensions=set(extra_exts),
        max_upload_bytes=int(num("max_upload_mb", 500, 1, 20480) * 1024 * 1024),
        min_free_bytes=int(num("min_free_space_mb", 200, 0, 1024 * 1024) * 1024 * 1024),
        max_streams=int(num("max_concurrent_streams", 8, 1, 64)),
        max_uploads=int(num("max_concurrent_uploads", 2, 1, 8)),
        login_max_failures=int(num("login_max_failures", 5, 1, 50)),
        login_lock_seconds=int(num("login_lock_minutes", 15, 1, 24 * 60) * 60),
        login_fail_delay=float(num("login_fail_delay_ms", 400, 0, 5000)) / 1000.0,
        telemetry_enabled=bool(raw.get("telemetry_enabled", True)),
        scan_on_start=bool(raw.get("scan_on_start", True)),
        max_scan_files=int(num("max_scan_files_per_category", 50000, 100, 1_000_000)),
        rates=rates,
    )
    return cfg, errors, warnings


def load_config_file(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
class RateLimiter:
    """Small in-memory sliding-window limiter (resets when the server restarts)."""

    def __init__(self) -> None:
        self._hits: dict[str, tuple[float, collections.deque]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            entry = self._hits.get(key)
            if entry is None:
                if len(self._hits) > 20000:
                    self._prune(now)
                entry = (window, collections.deque())
                self._hits[key] = entry
            dq = entry[1]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= limit:
                return False, int(window - (now - dq[0])) + 1
            dq.append(now)
            return True, 0

    def _prune(self, now: float) -> None:
        for k in [k for k, (w, dq) in self._hits.items() if not dq or now - dq[-1] > w]:
            self._hits.pop(k, None)


class LoginGuard:
    """Per-client failed-login tracking with temporary lockout."""

    def __init__(self, max_failures: int, window: int, lock_seconds: int) -> None:
        self.max_failures, self.window, self.lock_seconds = max_failures, window, lock_seconds
        self._state: dict[str, list] = {}
        self._lock = threading.Lock()

    def locked_for(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            st = self._state.get(key)
            if st and st[1] > now:
                return int(st[1] - now) + 1
        return 0

    def failure(self, key: str) -> int:
        """Record a failure; returns remaining attempts before lockout (0 when locked now)."""
        now = time.monotonic()
        with self._lock:
            if len(self._state) > 5000:
                for k in [k for k, v in self._state.items() if v[1] < now and (not v[0] or now - v[0][-1] > self.window)]:
                    self._state.pop(k, None)
            st = self._state.setdefault(key, [[], 0.0])
            st[0] = [t for t in st[0] if now - t < self.window] + [now]
            if len(st[0]) >= self.max_failures:
                st[1] = now + self.lock_seconds
                st[0] = []
                return 0
            return self.max_failures - len(st[0])

    def success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE files(
            id TEXT PRIMARY KEY, category TEXT NOT NULL, relpath TEXT NOT NULL, name TEXT NOT NULL,
            ext TEXT NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
            mtime INTEGER NOT NULL, art TEXT, seen INTEGER NOT NULL DEFAULT 0,
            UNIQUE(category, relpath)
        );
        CREATE INDEX idx_files_cat_kind ON files(category, kind);
        CREATE INDEX idx_files_name ON files(name COLLATE NOCASE);
        CREATE INDEX idx_files_mtime ON files(mtime);
        CREATE TABLE favorites(file_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL);
        CREATE TABLE watchlist(file_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL);
        CREATE TABLE playback(
            file_id TEXT PRIMARY KEY, position REAL NOT NULL DEFAULT 0, duration REAL,
            completed INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL
        );
        CREATE TABLE recent(
            file_id TEXT PRIMARY KEY, last_played_at INTEGER NOT NULL, play_count INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX idx_recent_time ON recent(last_played_at);
        CREATE TABLE sessions(
            id_hash TEXT PRIMARY KEY, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, last_seen INTEGER NOT NULL
        );
        CREATE TABLE shares(
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, file_id TEXT NOT NULL, mode TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
            access_count INTEGER NOT NULL DEFAULT 0, last_access INTEGER
        );
        CREATE TABLE activity(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, event TEXT NOT NULL, detail TEXT);
        CREATE TABLE playlists(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE playlist_items(
            playlist_id TEXT NOT NULL, file_id TEXT NOT NULL, position INTEGER NOT NULL, added_at INTEGER NOT NULL,
            PRIMARY KEY(playlist_id, file_id)
        );
        CREATE TABLE uploads(
            id TEXT PRIMARY KEY, original_name TEXT, category TEXT, status TEXT NOT NULL, size INTEGER,
            created_at INTEGER NOT NULL, completed_at INTEGER, final_name TEXT, file_id TEXT, error TEXT
        );
        """,
    ),
]


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def migrate_db(path: Path) -> int:
    """Create or upgrade the database. Backs up the old file before upgrading. Returns schema version."""
    existed = path.exists() and path.stat().st_size > 0
    conn = open_db(path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        latest = MIGRATIONS[-1][0]
        if current > latest:
            raise RuntimeError("Database was created by a newer NEXORA version (schema %d > %d)." % (current, latest))
        pending = [m for m in MIGRATIONS if m[0] > current]
        if pending and existed and current > 0:
            shutil.copy2(str(path), str(path) + ".bak-v%d" % current)
        for version, sql in pending:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    conn.execute(stmt)
                conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(version),))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return latest
    finally:
        conn.close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------
def safe_real_path(root_real: str, candidate: str) -> str | None:
    """Canonicalise `candidate` and return it only if it stays inside `root_real`."""
    real = os.path.realpath(candidate)
    if real == root_real or not _is_within(real, root_real):
        return None
    return real


def relpath_is_clean(rel: str) -> bool:
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return False
    return all(p not in ("", ".", "..") for p in rel.split("/"))


_SAFE_CHARS = re.compile(r"[^\w\s.\-()+,&'@#!\[\]]", re.UNICODE)


def sanitize_filename(raw: str | None, max_len: int = 120) -> str | None:
    """Return a safe single-component filename with a lowercase extension, or None."""
    if not raw:
        return None
    name = unicodedata.normalize("NFKC", raw).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = _SAFE_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .").lstrip(".")
    if not name:
        return None
    stem, dot, ext = name.rpartition(".")
    if not dot or not ext or not re.fullmatch(r"[A-Za-z0-9]{1,8}", ext):
        return None
    stem = stem.strip(" .") or "file"
    stem = stem[: max(1, max_len - len(ext) - 1)]
    return "%s.%s" % (stem, ext.lower())


def allowed_upload_exts(cfg: SimpleNamespace, category: str) -> set[str]:
    base = {
        "Movies": VIDEO_EXTS, "Music": AUDIO_EXTS, "Photos": IMAGE_EXTS, "Documents": DOC_EXTS,
        "Uploads": VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | DOC_EXTS,
    }.get(category, set())
    extra = cfg.extra_upload_extensions if category in ("Uploads", "Documents") else set()
    return (set(base) | set(extra)) - DENY_EXTS


EXEC_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe")


def sniff_problem(ext: str, head: bytes) -> str | None:
    """Check the first bytes of an upload. Returns a reason string if it should be rejected.

    This is NOT a malware scan. It only checks that the content plausibly matches
    the extension and rejects obvious executables / script / markup content.
    """
    if not head:
        return "The file is empty."
    for magic in EXEC_MAGIC:
        if head.startswith(magic):
            return "Executable or script content is not allowed."
    ok = True
    if ext in ("jpg", "jpeg"):
        ok = head[:3] == b"\xff\xd8\xff"
    elif ext == "png":
        ok = head[:8] == b"\x89PNG\r\n\x1a\n"
    elif ext == "gif":
        ok = head[:4] == b"GIF8"
    elif ext == "webp":
        ok = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    elif ext == "bmp":
        ok = head[:2] == b"BM"
    elif ext == "avif":
        ok = head[4:8] == b"ftyp"
    elif ext == "pdf":
        ok = b"%PDF-" in head[:1024]
    elif ext in ("mp4", "m4v", "mov", "3gp", "m4a"):
        ok = head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip")
    elif ext in ("webm", "mkv"):
        ok = head[:4] == b"\x1a\x45\xdf\xa3"
    elif ext == "mp3":
        ok = head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    elif ext == "aac":
        ok = head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xF0) == 0xF0)
    elif ext == "flac":
        ok = head[:4] == b"fLaC"
    elif ext in ("ogg", "oga", "opus"):
        ok = head[:4] == b"OggS"
    elif ext == "wav":
        ok = head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    elif ext == "avi":
        ok = head[:4] == b"RIFF" and head[8:12] == b"AVI "
    elif ext in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "zip"):
        ok = head[:4] in (b"PK\x03\x04", b"PK\x05\x06")
    elif ext in ("doc", "xls", "ppt"):
        ok = head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    elif ext in TEXT_EXTS:
        if b"\x00" in head:
            return "Text files must not contain binary data."
        try:
            text = head[:-3].decode("utf-8") if len(head) > 3 else head.decode("utf-8")
        except UnicodeDecodeError:
            return "Text files must be UTF-8 encoded."
        lowered = text.lstrip("\ufeff \t\r\n").lower()
        if lowered.startswith(("<!doctype html", "<html", "<script", "<?php", "<svg", "<?xml")):
            return "Markup or script content is not allowed in text files."
    return None if ok else "File content does not match its extension."


def content_disposition(disposition: str, filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")) or "download"
    return "%s; filename=\"%s\"; filename*=UTF-8''%s" % (disposition, ascii_name, urllib.parse.quote(filename, safe=""))


class FileIter:
    """Streams a byte range of a file in small chunks; releases its slot exactly once."""

    def __init__(self, fh, start: int, length: int, release=None, chunk: int = 131072) -> None:
        self.fh, self.remaining, self.chunk, self.release, self.closed = fh, length, chunk, release, False
        fh.seek(start)

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        if self.closed or self.remaining <= 0:
            self.close()
            raise StopIteration
        try:
            data = self.fh.read(min(self.chunk, self.remaining))
        except OSError:
            self.close()
            raise StopIteration from None
        if not data:
            self.close()
            raise StopIteration
        self.remaining -= len(data)
        return data

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.fh.close()
        finally:
            if self.release:
                self.release()


def parse_range(header: str | None, size: int):
    """Return ('full',), ('range', start, end) or ('unsatisfiable',) for a single-range header."""
    if not header:
        return ("full",)
    header = header.strip()
    if not header.lower().startswith("bytes=") or "," in header:
        return ("full",)  # unsupported/multi-range: serve the whole file (allowed by RFC 9110)
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.replace(" ", "").lower())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return ("full",)
    first, last = m.group(1), m.group(2)
    if first == "":
        n = int(last)
        if n == 0 or size == 0:
            return ("unsatisfiable",)
        return ("range", max(size - n, 0), size - 1)
    start = int(first)
    if start >= size:
        return ("unsatisfiable",)
    end = int(last) if last else size - 1
    if end < start:
        return ("full",)
    return ("range", start, min(end, size - 1))


# --------------------------------------------------------------------------
# Telemetry (honest: returns "unavailable" instead of inventing numbers)
# --------------------------------------------------------------------------
_battery_cache: dict = {"t": 0.0, "v": None}


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _battery_sysfs():
    base = "/sys/class/power_supply"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for name in names:
        d = os.path.join(base, name)
        if _read_text(d + "/type") != "Battery":
            continue
        cap = _read_text(d + "/capacity")
        if cap is None or not cap.isdigit():
            continue
        status = (_read_text(d + "/status") or "").lower()
        state = {"charging": "charging", "discharging": "discharging", "full": "full", "not charging": "not_charging"}.get(status, "unknown")
        temp = _read_text(d + "/temp")
        temp_c = int(temp) / 10.0 if temp and temp.lstrip("-").isdigit() else None
        return {"percent": int(cap), "state": state, "plugged": None if state == "unknown" else state in ("charging", "full", "not_charging"),
                "temperature_c": temp_c, "source": "sysfs"}
    return None


def _battery_termux():
    exe = shutil.which("termux-battery-status")
    if not exe:
        return None
    try:
        out = subprocess.run([exe], capture_output=True, text=True, timeout=4, check=False).stdout
        data = json.loads(out)
        pct = data.get("percentage")
        if not isinstance(pct, (int, float)):
            return None
        status = str(data.get("status", "")).lower()
        state = {"charging": "charging", "discharging": "discharging", "full": "full", "not_charging": "not_charging"}.get(status, "unknown")
        plugged = str(data.get("plugged", "UNPLUGGED")).upper() != "UNPLUGGED"
        temp = data.get("temperature")
        return {"percent": int(pct), "state": state, "plugged": plugged,
                "temperature_c": float(temp) if isinstance(temp, (int, float)) else None, "source": "termux-api"}
    except Exception:  # noqa: BLE001
        return None


def _battery_jnius():
    """Best-effort Android BatteryManager access through pyjnius (only if installed and a context is reachable)."""
    try:
        from jnius import autoclass  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    ctx = None
    for cls in ("org.kivy.android.PythonActivity", "org.renpy.android.PythonActivity"):
        try:
            ctx = autoclass(cls).mActivity
            if ctx is not None:
                break
        except Exception:  # noqa: BLE001
            continue
    if ctx is None:
        return None
    try:
        IntentFilter = autoclass("android.content.IntentFilter")
        Intent = autoclass("android.content.Intent")
        st = ctx.registerReceiver(None, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        level, scale = st.getIntExtra("level", -1), st.getIntExtra("scale", -1)
        if level < 0 or scale <= 0:
            return None
        status = st.getIntExtra("status", -1)
        state = {2: "charging", 3: "discharging", 4: "not_charging", 5: "full"}.get(status, "unknown")
        plugged = st.getIntExtra("plugged", 0) > 0
        temp = st.getIntExtra("temperature", -1)
        return {"percent": int(round(level * 100 / scale)), "state": state, "plugged": plugged,
                "temperature_c": temp / 10.0 if temp > 0 else None, "source": "android-jnius"}
    except Exception:  # noqa: BLE001
        return None


def _battery_psutil():
    if psutil is None:
        return None
    try:
        b = psutil.sensors_battery()
    except Exception:  # noqa: BLE001
        return None
    if b is None:
        return None
    return {"percent": int(round(b.percent)), "state": "charging" if b.power_plugged else "discharging",
            "plugged": bool(b.power_plugged), "temperature_c": None, "source": "psutil"}


def battery_info() -> dict:
    if time.time() - _battery_cache["t"] < 15 and _battery_cache["v"] is not None:
        return _battery_cache["v"]
    result = None
    for fn in (_battery_sysfs, _battery_termux, _battery_jnius, _battery_psutil):
        try:
            result = fn()
        except Exception:  # noqa: BLE001
            result = None
        if result:
            break
    value = dict(result, available=True) if result else {"available": False, "reason": "Unavailable on this device"}
    _battery_cache.update(t=time.time(), v=value)
    return value


def memory_info() -> dict:
    system: dict = {"available": False, "reason": "Unavailable on this device"}
    try:
        if psutil is not None:
            vm = psutil.virtual_memory()
            system = {"available": True, "total_bytes": vm.total, "available_bytes": vm.available,
                      "used_percent": round(vm.percent, 1), "scope": "system"}
    except Exception:  # noqa: BLE001
        pass
    if not system.get("available"):
        txt = _read_text("/proc/meminfo")
        if txt:
            vals = {}
            for line in txt.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    vals[parts[0].rstrip(":")] = int(parts[1]) * 1024
            if "MemTotal" in vals and "MemAvailable" in vals:
                total, avail = vals["MemTotal"], vals["MemAvailable"]
                system = {"available": True, "total_bytes": total, "available_bytes": avail,
                          "used_percent": round((total - avail) * 100.0 / total, 1), "scope": "system"}
    process: dict = {"available": False, "reason": "Unavailable on this device"}
    try:
        if psutil is not None:
            process = {"available": True, "rss_bytes": psutil.Process().memory_info().rss, "scope": "process", "kind": "current"}
    except Exception:  # noqa: BLE001
        pass
    if not process.get("available"):
        txt = _read_text("/proc/self/status")
        if txt:
            for line in txt.splitlines():
                if line.startswith("VmRSS:"):
                    process = {"available": True, "rss_bytes": int(line.split()[1]) * 1024, "scope": "process", "kind": "current"}
        if not process.get("available"):
            try:
                import resource  # noqa: WPS433

                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                process = {"available": True, "rss_bytes": int(rss) * (1 if sys.platform == "darwin" else 1024), "scope": "process", "kind": "peak"}
            except Exception:  # noqa: BLE001
                pass
    return {"system": system, "process": process}


def cpu_info() -> dict:
    out: dict = {"system": {"available": False, "reason": "Unavailable on this device"},
                 "process": {"available": False, "reason": "Unavailable on this device"}}
    try:
        if psutil is not None:
            out["system"] = {"available": True, "percent": psutil.cpu_percent(interval=None), "scope": "system", "cores": psutil.cpu_count()}
    except Exception:  # noqa: BLE001
        pass
    try:
        if psutil is not None:
            out["process"] = {"available": True, "percent": psutil.Process().cpu_percent(interval=None), "scope": "process"}
    except Exception:  # noqa: BLE001
        pass
    try:
        out["load_average"] = [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        pass
    return out


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------
def create_app(cfg: SimpleNamespace, start_background: bool = False) -> Flask:
    cfg.private_dir.mkdir(parents=True, exist_ok=True)
    for d in (cfg.db_path.parent, cfg.quarantine_dir / "tmp", cfg.logs_dir, cfg.thumbs_dir):
        d.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(cfg.quarantine_dir / "tmp")  # request spool files stay in the private area
    schema = migrate_db(cfg.db_path)

    log = logging.getLogger("nexora")
    log.setLevel(logging.INFO)
    if not log.handlers:
        fh = logging.handlers.RotatingFileHandler(str(cfg.logs_dir / "nexora.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # access logs would contain share tokens in URLs

    app = Flask("nexora")
    app.json.sort_keys = False  # type: ignore[attr-defined]
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes + 2 * 1024 * 1024

    limiter = RateLimiter()
    guard = LoginGuard(cfg.login_max_failures, 15 * 60, cfg.login_lock_seconds)
    stream_sem = threading.BoundedSemaphore(cfg.max_streams)
    upload_sem = threading.BoundedSemaphore(cfg.max_uploads)
    thumb_lock = threading.Lock()
    scan_lock = threading.Lock()
    scan_state: dict = {"state": "idle", "started_at": None, "finished_at": None, "categories": {}}
    recent_errors: collections.deque = collections.deque(maxlen=20)
    stop_event = threading.Event()
    cookie_name = "__Host-nexora_sid" if cfg.cookie_secure else "nexora_sid"
    activity_counter = {"n": 0}
    if psutil is not None:  # prime counters so later percentages are meaningful
        try:
            psutil.cpu_percent(interval=None)
            psutil.Process().cpu_percent(interval=None)
        except Exception:  # noqa: BLE001
            pass

    # ---- helpers ---------------------------------------------------------
    def hm(value: str) -> str:
        return hmac.new(cfg.secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def file_id_for(category: str, relpath: str) -> str:
        return hm("file:%s/%s" % (category, relpath))[:24]

    def db() -> sqlite3.Connection:
        conn = g.get("_db")
        if conn is None:
            conn = g._db = open_db(cfg.db_path)
        return conn

    @app.teardown_appcontext
    def _close_db(_exc):
        conn = g.pop("_db", None)
        if conn is not None:
            conn.close()

    def err(code: str, message: str, status: int, headers: dict | None = None, **extra):
        body = {"error": {"code": code, "message": message}}
        body["error"].update(extra)
        resp = jsonify(body)
        resp.status_code = status
        for k, v in (headers or {}).items():
            resp.headers[k] = v
        return resp

    def log_activity(event: str, detail: str = "") -> None:
        conn = db()
        conn.execute("INSERT INTO activity(ts,event,detail) VALUES(?,?,?)", (now_s(), event, detail[:200]))
        activity_counter["n"] += 1
        if activity_counter["n"] % 100 == 0:
            conn.execute("DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - 1000")

    def client_ip() -> str:
        remote = request.remote_addr or "unknown"
        if cfg.trust_proxy_headers and remote in ("127.0.0.1", "::1"):
            cf = request.headers.get("CF-Connecting-IP", "").strip()
            if cf:
                try:
                    return str(ipaddress.ip_address(cf))
                except ValueError:
                    pass
        return remote

    def public_base() -> str:
        if cfg.public_base_url:
            return cfg.public_base_url
        proto = request.headers.get("X-Forwarded-Proto", request.scheme) if cfg.trust_proxy_headers else request.scheme
        proto = proto if proto in ("http", "https") else "https"
        return "%s://%s" % (proto, request.host)

    def origin_allowed() -> bool:
        return request.headers.get("Origin", "") in cfg.allowed_origins

    # ---- request pipeline --------------------------------------------------
    UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

    @app.before_request
    def _pipeline():
        g.ip = client_ip()
        if request.method == "OPTIONS":
            if origin_allowed():
                resp = app.response_class(status=204)
                return resp
            return err("origin_not_allowed", "This website origin is not allowed to use this server.", 403)
        ok, retry = limiter.check("api:" + g.ip, cfg.rates["api_per_minute"], 60)
        if not ok:
            return err("rate_limited", "Too many requests. Please slow down.", 429, {"Retry-After": str(retry)})
        cap = cfg.max_upload_bytes + 2 * 1024 * 1024 if request.path == "/api/v1/uploads" else 64 * 1024
        if request.content_length is not None and request.content_length > cap:
            return err("payload_too_large", "The request is larger than this server allows.", 413)
        if request.method in UNSAFE:
            if not origin_allowed() or request.headers.get("X-NEXORA-CSRF") != "1":
                return err("csrf_failed", "Request blocked: it did not come from the NEXORA website.", 403)
        return None

    @app.after_request
    def _headers(resp: Response):
        origin = request.headers.get("Origin", "")
        if origin in cfg.allowed_origins:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Expose-Headers"] = "Content-Range, Accept-Ranges, Content-Length, Retry-After"
            if request.method == "OPTIONS":
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-NEXORA-CSRF, Range"
                resp.headers["Access-Control-Max-Age"] = "600"
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "private, no-store")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
        if "Content-Security-Policy" not in resp.headers:
            resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if cfg.cookie_secure:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
        return resp

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        code = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                408: "timeout", 413: "payload_too_large", 416: "range_not_satisfiable", 429: "rate_limited"}.get(e.code or 500, "error")
        msgs = {404: "Resource not found.", 405: "Method not allowed.", 413: "The request is larger than this server allows.",
                400: "The request could not be understood."}
        return err(code, msgs.get(e.code or 0, "Request failed."), e.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        log.exception("Unhandled error")
        recent_errors.append({"ts": now_s(), "code": "internal_error", "type": type(e).__name__})
        return err("internal_error", "Something went wrong on the server. Check the server log on the phone.", 500)

    # ---- auth --------------------------------------------------------------
    def current_session():
        sid = request.cookies.get(cookie_name)
        if not sid or len(sid) > 128:
            return None
        h = hm("sid:" + sid)
        conn = db()
        row = conn.execute("SELECT * FROM sessions WHERE id_hash=?", (h,)).fetchone()
        t = now_s()
        if row is None:
            return None
        if row["expires_at"] <= t or t - row["last_seen"] > cfg.idle_seconds:
            conn.execute("DELETE FROM sessions WHERE id_hash=?", (h,))
            return None
        if t - row["last_seen"] >= 60:
            conn.execute("UPDATE sessions SET last_seen=? WHERE id_hash=?", (t, h))
        return row

    def login_required(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*a, **kw):
            if current_session() is None:
                return err("unauthenticated", "Please log in to continue.", 401)
            return fn(*a, **kw)

        return wrapper

    @app.get("/api/v1/health")
    def health():
        healthy = True
        try:
            db().execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001
            healthy = False
        resp = jsonify({"status": "ok" if healthy else "degraded", "service": SERVICE, "origin_allowed": origin_allowed()})
        resp.status_code = 200 if healthy else 503
        resp.headers["Access-Control-Allow-Origin"] = "*"  # health only: lets the site tell 'offline' from 'origin not allowed'
        return resp

    @app.post("/api/v1/auth/login")
    def login():
        ip = g.ip
        remaining = guard.locked_for(ip)
        if remaining:
            return err("locked", "Too many failed attempts. Try again in %d minute(s)." % ((remaining + 59) // 60), 429,
                       {"Retry-After": str(remaining)}, retry_after=remaining)
        ok, retry = limiter.check("login:" + ip, cfg.rates["login_per_minute"], 60)
        if not ok:
            return err("rate_limited", "Too many login attempts. Wait a moment and try again.", 429, {"Retry-After": str(retry)}, retry_after=retry)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("password"), str):
            return err("invalid_request", "Send a JSON body with a 'password' field.", 400)
        password = data["password"]
        good = len(password) <= 256 and verify_password(password, cfg.password_hash)
        if not good:
            left = guard.failure(ip)
            if cfg.login_fail_delay:
                time.sleep(cfg.login_fail_delay)
            log_activity("login_failed")
            if left == 0:
                return err("locked", "Too many failed attempts. Login is locked for %d minute(s)." % (cfg.login_lock_seconds // 60), 429,
                           {"Retry-After": str(cfg.login_lock_seconds)}, retry_after=cfg.login_lock_seconds)
            return err("invalid_credentials", "Incorrect password.", 401, attempts_remaining=left)
        guard.success(ip)
        conn = db()
        old = request.cookies.get(cookie_name)
        if old:  # session regeneration: the previous id is invalidated
            conn.execute("DELETE FROM sessions WHERE id_hash=?", (hm("sid:" + old),))
        sid = secrets.token_urlsafe(32)
        t = now_s()
        conn.execute("INSERT INTO sessions(id_hash,created_at,expires_at,last_seen) VALUES(?,?,?,?)", (hm("sid:" + sid), t, t + cfg.session_seconds, t))
        log_activity("login_success")
        resp = jsonify({"ok": True, "expires_at": t + cfg.session_seconds, "idle_timeout_seconds": cfg.idle_seconds})
        resp.set_cookie(cookie_name, sid, max_age=cfg.session_seconds, httponly=True, secure=cfg.cookie_secure, samesite=cfg.cookie_samesite, path="/")
        return resp

    @app.post("/api/v1/auth/logout")
    def logout():
        sid = request.cookies.get(cookie_name)
        if sid:
            db().execute("DELETE FROM sessions WHERE id_hash=?", (hm("sid:" + sid),))
            log_activity("logout")
        resp = jsonify({"ok": True})
        resp.delete_cookie(cookie_name, path="/", secure=cfg.cookie_secure, httponly=True, samesite=cfg.cookie_samesite)
        return resp

    @app.get("/api/v1/auth/session")
    def session_info():
        row = current_session()
        if row is None:
            return jsonify({"authenticated": False})
        return jsonify({"authenticated": True, "expires_at": row["expires_at"], "idle_timeout_seconds": cfg.idle_seconds})

    # ---- library indexing ---------------------------------------------------
    def scan_category(conn: sqlite3.Connection, cat: str, root: str, scan_no: int) -> dict:
        info = {"available": False, "error": None, "count": 0, "truncated": False}
        if not os.path.isdir(root):
            info["error"] = "missing"
            return info
        if not os.access(root, os.R_OK | os.X_OK):
            info["error"] = "permission"
            return info
        info["available"] = True
        stack = [(root, "", 0)]
        batch = 0
        conn.execute("BEGIN")
        try:
            while stack:
                dirpath, rel, depth = stack.pop()
                try:
                    entries = list(os.scandir(dirpath))
                except PermissionError:
                    info["error"] = "permission"
                    continue
                except OSError:
                    continue
                names_lower = {e.name.lower(): e.name for e in entries if e.is_file(follow_symlinks=False)}
                art_name = next((names_lower[a] for a in ART_NAMES if a in names_lower), None)
                for e in entries:
                    if e.name.startswith(".") or "\\" in e.name or "\x00" in e.name:
                        continue
                    child_rel = e.name if not rel else rel + "/" + e.name
                    try:
                        if e.is_symlink():
                            real = os.path.realpath(e.path)
                            if not _is_within(real, root) or real == root:
                                continue  # symlink escapes the library: ignore
                            if e.is_dir():
                                continue  # never recurse into symlinked directories
                        if e.is_dir(follow_symlinks=False):
                            if depth < 10:
                                stack.append((e.path, child_rel, depth + 1))
                            continue
                        if not e.is_file():
                            continue
                        st = e.stat()
                    except OSError:
                        continue
                    ext = e.name.rpartition(".")[2].lower() if "." in e.name else ""
                    kind = kind_for_ext(ext)
                    art = None
                    if kind == "audio" and art_name:
                        art = art_name if not rel else rel + "/" + art_name
                    if info["count"] >= cfg.max_scan_files:
                        info["truncated"] = True
                        stack.clear()
                        break
                    conn.execute(
                        "INSERT INTO files(id,category,relpath,name,ext,kind,mime,size,mtime,art,seen) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(category,relpath) DO UPDATE SET name=excluded.name, ext=excluded.ext, kind=excluded.kind, mime=excluded.mime, "
                        "size=excluded.size, mtime=excluded.mtime, art=excluded.art, seen=excluded.seen",
                        (file_id_for(cat, child_rel), cat, child_rel, e.name, ext, kind, mime_for_ext(ext), st.st_size, int(st.st_mtime), art, scan_no),
                    )
                    info["count"] += 1
                    batch += 1
                    if batch >= 500:
                        conn.execute("COMMIT")
                        conn.execute("BEGIN")
                        batch = 0
            if not info["truncated"]:
                conn.execute("DELETE FROM files WHERE category=? AND seen<>?", (cat, scan_no))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return info

    def scan_now() -> bool:
        """Synchronous scan of configured roots only. Returns False if a scan is already running."""
        if not scan_lock.acquire(blocking=False):
            return False
        conn = open_db(cfg.db_path)
        try:
            scan_state.update(state="scanning", started_at=now_s())
            scan_no = int(time.time() * 1000)
            cats = {}
            for cat, root in cfg.roots.items():
                try:
                    cats[cat] = scan_category(conn, cat, root, scan_no)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Scan failed for %s", cat)
                    recent_errors.append({"ts": now_s(), "code": "scan_failed", "type": type(exc).__name__})
                    cats[cat] = {"available": False, "error": "failed", "count": 0, "truncated": False}
            scan_state.update(categories=cats, finished_at=now_s(), state="idle")
            return True
        finally:
            conn.close()
            scan_lock.release()

    def start_scan_thread() -> bool:
        if scan_lock.locked():
            return False
        threading.Thread(target=scan_now, name="nexora-scan", daemon=True).start()
        return True

    def index_single_file(conn: sqlite3.Connection, cat: str, relpath: str, real: str) -> str:
        st = os.stat(real)
        name = relpath.rsplit("/", 1)[-1]
        ext = name.rpartition(".")[2].lower()
        fid = file_id_for(cat, relpath)
        conn.execute(
            "INSERT INTO files(id,category,relpath,name,ext,kind,mime,size,mtime,art,seen) VALUES(?,?,?,?,?,?,?,?,?,NULL,?) "
            "ON CONFLICT(category,relpath) DO UPDATE SET size=excluded.size, mtime=excluded.mtime",
            (fid, cat, relpath, name, ext, kind_for_ext(ext), mime_for_ext(ext), st.st_size, int(st.st_mtime), now_s()),
        )
        return fid

    # ---- file lookup & serving ----------------------------------------------
    def lookup_file(file_id: str):
        """Return (row, real_path) for an indexed file that is still inside its allow-listed root, else (None, None)."""
        if not re.fullmatch(r"[0-9a-f]{24}", file_id or ""):
            return None, None
        row = db().execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None or not relpath_is_clean(row["relpath"]):
            return None, None
        root = cfg.roots.get(row["category"])
        if not root:
            return None, None
        real = safe_real_path(root, os.path.join(root, *row["relpath"].split("/")))
        if real is None or not os.path.isfile(real):
            return None, None
        return row, real

    def serve_file(real: str, name: str, ext: str, *, force_download: bool, shared: bool = False, allow_frame: bool = False):
        mime = mime_for_ext(ext)
        inline = ext in INLINE_EXTS and not force_download
        if not stream_sem.acquire(blocking=False):
            return err("busy", "The server is busy streaming other files. Try again in a moment.", 503, {"Retry-After": "2"})
        try:
            fh = open(real, "rb")
        except OSError:
            stream_sem.release()
            return err("not_found", "File not found.", 404)
        try:
            st = os.fstat(fh.fileno())
            size = st.st_size
            etag = '"%x-%x"' % (st.st_size, int(st.st_mtime))
            rng = parse_range(request.headers.get("Range"), size)
            if_range = request.headers.get("If-Range")
            if rng[0] == "range" and if_range and if_range != etag:
                rng = ("full",)
            headers = {
                "Content-Type": mime if inline else "application/octet-stream",
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Content-Disposition": content_disposition("inline" if inline else "attachment", name),
                "X-Content-Type-Options": "nosniff",
            }
            if shared:
                headers["X-Robots-Tag"] = "noindex, nofollow"
            if allow_frame and inline:
                headers["Content-Security-Policy"] = "frame-ancestors " + " ".join(cfg.allowed_origins)
            if rng[0] == "unsatisfiable":
                fh.close()
                stream_sem.release()
                resp = err("range_not_satisfiable", "Requested range not satisfiable.", 416, {"Content-Range": "bytes */%d" % size})
                return resp
            if rng[0] == "range":
                start, end = rng[1], rng[2]
                status = 206
                headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
            else:
                start, end, status = 0, size - 1, 200
            length = max(0, end - start + 1) if size else 0
            headers["Content-Length"] = str(length)
            if request.method == "HEAD":  # headers only: no body, no streaming slot held
                fh.close()
                stream_sem.release()
                head_resp = Response(b"", status=status)
                for key, value in headers.items():
                    head_resp.headers[key] = value  # set after construction so Content-Length stays the real size
                return head_resp
            body = FileIter(fh, start, length, release=stream_sem.release)
            return Response(body, status=status, headers=headers, direct_passthrough=True)
        except Exception:
            fh.close()
            stream_sem.release()
            raise

    # ---- file listing helpers ------------------------------------------------
    FILE_SELECT = (
        "SELECT f.id,f.category,f.relpath,f.name,f.ext,f.kind,f.mime,f.size,f.mtime,f.art,"
        "(fav.file_id IS NOT NULL) AS favorite,(w.file_id IS NOT NULL) AS watch,"
        "pb.position AS pb_pos,pb.duration AS pb_dur,pb.completed AS pb_done,pb.updated_at AS pb_updated "
        "FROM files f LEFT JOIN favorites fav ON fav.file_id=f.id LEFT JOIN watchlist w ON w.file_id=f.id "
        "LEFT JOIN playback pb ON pb.file_id=f.id "
    )

    def row_to_item(r) -> dict:
        thumb = (r["kind"] == "image" and (Image is not None or r["size"] <= 1_500_000)) or (r["kind"] == "audio" and r["art"] is not None)
        folder = r["relpath"].rpartition("/")[0]
        progress = None
        if r["pb_updated"] is not None:
            progress = {"position": r["pb_pos"], "duration": r["pb_dur"], "completed": bool(r["pb_done"]), "updated_at": r["pb_updated"]}
        return {
            "id": r["id"], "name": r["name"], "category": r["category"], "folder": folder, "kind": r["kind"], "ext": r["ext"],
            "mime": r["mime"], "size": r["size"], "mtime": r["mtime"], "favorite": bool(r["favorite"]), "watchlist": bool(r["watch"]),
            "progress": progress, "duration": r["pb_dur"], "thumbnail": bool(thumb),
            "inline": r["ext"] in INLINE_EXTS,
        }

    def int_arg(name: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    def escape_like(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def list_files(extra_join: str = "", extra_where: str = "", extra_params: tuple = (), default_sort: str = "name", default_order: str = "asc",
                   sort_override: str | None = None):
        where, params = ["1=1"], list(extra_params)
        cat = request.args.get("category")
        if cat:
            if cat not in cfg.roots:
                return err("invalid_category", "Unknown category.", 400)
            where.append("f.category=?")
            params.append(cat)
        kind = request.args.get("kind")
        if kind:
            if kind not in ("video", "audio", "image", "document", "other"):
                return err("invalid_kind", "Unknown kind.", 400)
            where.append("f.kind=?")
            params.append(kind)
        q = (request.args.get("q") or "").strip()[:100]
        if q:
            where.append("(f.name LIKE ? ESCAPE '\\' OR f.relpath LIKE ? ESCAPE '\\')")
            params += ["%" + escape_like(q) + "%"] * 2
        if extra_where:
            where.append(extra_where)
        sorts = {"name": "f.name COLLATE NOCASE", "date": "f.mtime", "size": "f.size", "type": "f.ext"}
        user_sort = request.args.get("sort")
        if user_sort is not None and user_sort not in sorts:
            return err("invalid_sort", "Unknown sort field.", 400)
        order = "DESC" if request.args.get("order", default_order).lower() == "desc" else "ASC"
        if user_sort is None and sort_override:
            order_sql = sort_override
        else:
            order_sql = "%s %s, f.id" % (sorts[user_sort or default_sort], order)
        limit, offset = int_arg("limit", 50, 1, 200), int_arg("offset", 0, 0, 10_000_000)
        conn = db()
        total = conn.execute("SELECT COUNT(*) FROM files f %s WHERE %s" % (extra_join, " AND ".join(where)), params).fetchone()[0]
        select = FILE_SELECT.replace("FROM files f ", "FROM files f " + extra_join + " ", 1)
        rows = conn.execute("%s WHERE %s ORDER BY %s LIMIT ? OFFSET ?" % (select, " AND ".join(where), order_sql), params + [limit, offset]).fetchall()
        return jsonify({"items": [row_to_item(r) for r in rows], "total": total, "limit": limit, "offset": offset,
                        "scan": {"state": scan_state["state"], "finished_at": scan_state["finished_at"]}})

    @app.get("/api/v1/files")
    @login_required
    def files_list():
        return list_files()

    @app.get("/api/v1/files/<file_id>")
    @login_required
    def file_detail(file_id):
        row, real = lookup_file(file_id)
        if row is None:
            return err("not_found", "File not found.", 404)
        r = db().execute(FILE_SELECT + "WHERE f.id=?", (file_id,)).fetchone()
        item = row_to_item(r)
        item["stream_url"] = "/api/v1/files/%s/stream" % file_id
        item["download_url"] = "/api/v1/files/%s/download" % file_id
        item["thumbnail_url"] = "/api/v1/files/%s/thumbnail" % file_id if item["thumbnail"] else None
        return jsonify(item)

    @app.get("/api/v1/files/<file_id>/stream")
    @login_required
    def file_stream(file_id):
        row, real = lookup_file(file_id)
        if row is None:
            return err("not_found", "File not found.", 404)
        return serve_file(real, row["name"], row["ext"], force_download=False, allow_frame=True)

    @app.get("/api/v1/files/<file_id>/download")
    @login_required
    def file_download(file_id):
        row, real = lookup_file(file_id)
        if row is None:
            return err("not_found", "File not found.", 404)
        rng = request.headers.get("Range")
        if not rng or rng.strip().lower().startswith("bytes=0-"):
            log_activity("download_requested", row["name"])
        return serve_file(real, row["name"], row["ext"], force_download=True)

    @app.get("/api/v1/files/<file_id>/thumbnail")
    @login_required
    def file_thumbnail(file_id):
        row, real = lookup_file(file_id)
        if row is None:
            return err("not_found", "File not found.", 404)
        src = real
        if row["kind"] == "audio":
            if not row["art"] or not relpath_is_clean(row["art"]):
                return err("thumbnail_unavailable", "No cover art for this track.", 404)
            root = cfg.roots[row["category"]]
            src = safe_real_path(root, os.path.join(root, *row["art"].split("/")))
            if src is None or not os.path.isfile(src):
                return err("thumbnail_unavailable", "No cover art for this track.", 404)
        elif row["kind"] != "image":
            return err("thumbnail_unavailable", "No thumbnail for this file type.", 404)
        if Image is None:
            if os.path.getsize(src) <= 1_500_000 and src.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = src.lower().rsplit(".", 1)[-1]
                resp = serve_file(src, "thumb." + ext, ext, force_download=False)
                resp.headers["Cache-Control"] = "private, max-age=300"
                return resp
            return err("thumbnail_unavailable", "Thumbnails need the optional Pillow package.", 404)
        thumb = cfg.thumbs_dir / (file_id + ".jpg")
        try:
            if not (thumb.exists() and thumb.stat().st_mtime >= os.stat(src).st_mtime):
                if os.path.getsize(src) > 40 * 1024 * 1024:
                    return err("thumbnail_unavailable", "Image too large for a thumbnail.", 404)
                with thumb_lock:
                    with Image.open(src) as im:
                        if im.format == "JPEG":
                            im.draft("RGB", (720, 720))
                        im.thumbnail((360, 360))
                        if im.mode not in ("RGB", "L"):
                            im = im.convert("RGB")
                        tmp = str(thumb) + ".tmp"
                        im.save(tmp, "JPEG", quality=78)
                    os.replace(tmp, thumb)
            resp = serve_file(str(thumb), "thumb.jpg", "jpg", force_download=False)
            if resp.status_code < 400:
                resp.headers["Cache-Control"] = "private, max-age=300"
            return resp
        except Exception:  # noqa: BLE001
            log.exception("Thumbnail generation failed")
            return err("thumbnail_unavailable", "Could not create a thumbnail for this file.", 404)

    @app.get("/api/v1/categories")
    @login_required
    def categories():
        conn = db()
        out = []
        for cat in CATEGORY_NAMES:
            info = scan_state["categories"].get(cat)
            row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS s FROM files WHERE category=?", (cat,)).fetchone()
            root = cfg.roots.get(cat)
            if info is None:
                available, error = (bool(root) and os.path.isdir(root)), None
            else:
                available, error = info["available"], info["error"]
            msg = None
            if not available:
                msg = ("Permission denied. Grant Pydroid 3 access to storage and check the folder." if error == "permission"
                       else "Folder not found. Create it on the phone or check library_root in the private config.")
            out.append({"name": cat, "available": available, "status": "ok" if available else (error or "missing"), "message": msg,
                        "file_count": row["n"], "size_bytes": row["s"], "upload_allowed": cfg.uploads_enabled and cat in cfg.upload_categories,
                        "truncated": bool(info and info.get("truncated"))})
        return jsonify({"categories": out, "scan": {"state": scan_state["state"], "started_at": scan_state["started_at"],
                                                    "finished_at": scan_state["finished_at"]}})

    @app.post("/api/v1/library/rescan")
    @login_required
    def rescan():
        ok, retry = limiter.check("rescan:" + g.ip, cfg.rates["rescan_per_minute"], 60)
        if not ok:
            return err("rate_limited", "Rescan requested too often.", 429, {"Retry-After": str(retry)})
        started = start_scan_thread()
        resp = jsonify({"started": started, "state": "scanning" if started else scan_state["state"]})
        resp.status_code = 202 if started else 200
        return resp

    # ---- storage & device ------------------------------------------------------
    def storage_info() -> dict:
        volumes: dict = {}
        dev_to_vid: dict = {}
        cats = []
        conn = db()
        for cat, root in cfg.roots.items():
            row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS s FROM files WHERE category=?", (cat,)).fetchone()
            entry = {"name": cat, "file_count": row["n"], "size_bytes": row["s"], "available": os.path.isdir(root), "volume": None}
            if entry["available"]:
                try:
                    du = shutil.disk_usage(root)
                    dev = os.stat(root).st_dev
                    if dev not in dev_to_vid:
                        vid = "v%d" % len(volumes)
                        dev_to_vid[dev] = vid
                        volumes[vid] = {"total_bytes": du.total, "used_bytes": du.used, "free_bytes": du.free,
                                        "used_percent": round(du.used * 100.0 / du.total, 1) if du.total else None}
                    entry["volume"] = dev_to_vid[dev]
                except OSError:
                    entry["available"] = False
            cats.append(entry)
        totals = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS s FROM files").fetchone()
        return {
            "library": {"file_count": totals["n"], "size_bytes": totals["s"]},
            "categories": cats,
            "volumes": volumes,
            "note": "Capacity figures describe the storage volume that holds your NEXORA folders as seen by this app. "
                    "Android may hide other storage from Pydroid 3, so this is not necessarily the whole phone.",
        }

    @app.get("/api/v1/storage")
    @login_required
    def storage():
        return jsonify(storage_info())

    @app.get("/api/v1/device/status")
    @login_required
    def device_status():
        db_ok = True
        try:
            db().execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001
            db_ok = False
        proc_started = START_TIME
        try:
            if psutil is not None:
                proc_started = psutil.Process().create_time()
        except Exception:  # noqa: BLE001
            pass
        out = {
            "server": {
                "version": VERSION, "schema_version": schema, "started_at": int(START_TIME), "uptime_seconds": int(time.time() - START_TIME),
                "process_uptime_seconds": int(time.time() - proc_started),
                "python": "%d.%d.%d" % sys.version_info[:3],
                "platform": "android" if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ else sys.platform,
                "via_cloudflare": bool(request.headers.get("CF-Ray") or request.headers.get("CF-Connecting-IP")),
                "uploads_enabled": cfg.uploads_enabled,
                "max_upload_bytes": cfg.max_upload_bytes,
            },
            "health": {"api": "ok", "database": "ok" if db_ok else "error", "checked_at": now_s(),
                       "library_scan": {"state": scan_state["state"], "finished_at": scan_state["finished_at"]},
                       "tunnel": {"known": False,
                                  "note": "The server cannot reliably detect the tunnel. 'via_cloudflare' only says whether this request arrived through Cloudflare."}},
            "recent_errors": list(recent_errors)[-10:],
            "telemetry_enabled": cfg.telemetry_enabled,
        }
        if cfg.telemetry_enabled:
            out["battery"] = battery_info()
            out["memory"] = memory_info()
            out["cpu"] = cpu_info()
            out["storage"] = storage_info()
        return jsonify(out)

    # ---- dashboard -------------------------------------------------------------
    @app.get("/api/v1/dashboard")
    @login_required
    def dashboard():
        conn = db()
        kinds = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) AS n FROM files GROUP BY kind")}
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

        def items(sql, params=()):
            return [row_to_item(r) for r in conn.execute(sql, params).fetchall()]

        recent_files = items(FILE_SELECT + "ORDER BY f.mtime DESC LIMIT 12")
        favorites_ = items(FILE_SELECT + "JOIN favorites x ON x.file_id=f.id ORDER BY x.created_at DESC LIMIT 12")
        cont = items(FILE_SELECT + "WHERE f.kind='video' AND pb.completed=0 AND pb.position>=10 ORDER BY pb.updated_at DESC LIMIT 12")
        played = items(FILE_SELECT + "JOIN recent x ON x.file_id=f.id ORDER BY x.last_played_at DESC LIMIT 12")
        st = storage_info()
        return jsonify({
            "counts": {"total": total, "videos": kinds.get("video", 0), "music": kinds.get("audio", 0), "photos": kinds.get("image", 0),
                       "documents": kinds.get("document", 0)},
            "recent_files": recent_files, "favorites": favorites_, "continue_watching": cont, "recently_played": played,
            "storage": {"library": st["library"], "volumes": st["volumes"]},
            "server": {"version": VERSION, "uptime_seconds": int(time.time() - START_TIME), "uploads_enabled": cfg.uploads_enabled},
            "scan": {"state": scan_state["state"], "finished_at": scan_state["finished_at"]},
        })

    # ---- favorites / watchlist ----------------------------------------------------
    def body_file_id():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("file_id"), str):
            return None, err("invalid_request", "Send JSON with a 'file_id' field.", 400)
        row = db().execute("SELECT id FROM files WHERE id=?", (data["file_id"],)).fetchone()
        if row is None:
            return None, err("not_found", "File not found.", 404)
        return data["file_id"], None

    for table, path in (("favorites", "favorites"), ("watchlist", "watchlist")):
        def make(table=table, path=path):
            def listing():
                return list_files("JOIN %s x ON x.file_id=f.id" % table, "", (), sort_override="x.created_at DESC")

            def add():
                fid, bad = body_file_id()
                if bad:
                    return bad
                db().execute("INSERT OR IGNORE INTO %s(file_id,created_at) VALUES(?,?)" % table, (fid, now_s()))
                return jsonify({"ok": True, "file_id": fid})

            def remove(file_id):
                if not re.fullmatch(r"[0-9a-f]{24}", file_id):
                    return err("not_found", "File not found.", 404)
                db().execute("DELETE FROM %s WHERE file_id=?" % table, (file_id,))
                return jsonify({"ok": True})

            listing.__name__, add.__name__, remove.__name__ = "list_" + table, "add_" + table, "remove_" + table
            app.add_url_rule("/api/v1/%s" % path, view_func=login_required(listing), methods=["GET"])
            app.add_url_rule("/api/v1/%s" % path, view_func=login_required(add), methods=["POST"])
            app.add_url_rule("/api/v1/%s/<file_id>" % path, view_func=login_required(remove), methods=["DELETE"])
        make()

    @app.get("/api/v1/recent")
    @login_required
    def recent_list():
        return list_files("JOIN recent x ON x.file_id=f.id", "", (), sort_override="x.last_played_at DESC")

    @app.post("/api/v1/playback/progress")
    @login_required
    def playback_progress():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("file_id"), str):
            return err("invalid_request", "Send JSON with 'file_id' and 'position'.", 400)
        pos, dur = data.get("position"), data.get("duration")
        if isinstance(pos, bool) or not isinstance(pos, (int, float)) or not (0 <= pos <= 10_000_000):
            return err("invalid_request", "'position' must be a number of seconds.", 400)
        if dur is not None and (isinstance(dur, bool) or not isinstance(dur, (int, float)) or not (0 < dur <= 10_000_000)):
            return err("invalid_request", "'duration' must be a positive number of seconds.", 400)
        conn = db()
        row = conn.execute("SELECT id,name,kind FROM files WHERE id=?", (data["file_id"],)).fetchone()
        if row is None:
            return err("not_found", "File not found.", 404)
        if row["kind"] not in ("video", "audio"):
            return err("not_playable", "Only audio and video files record playback progress.", 400)
        completed = bool(data.get("completed")) or bool(dur and pos >= dur * 0.95)
        t = now_s()
        prev = conn.execute("SELECT last_played_at FROM recent WHERE file_id=?", (row["id"],)).fetchone()
        old_dur = conn.execute("SELECT duration FROM playback WHERE file_id=?", (row["id"],)).fetchone()
        conn.execute(
            "INSERT INTO playback(file_id,position,duration,completed,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(file_id) DO UPDATE SET position=excluded.position, duration=COALESCE(excluded.duration, playback.duration), "
            "completed=excluded.completed, updated_at=excluded.updated_at",
            (row["id"], float(pos), float(dur) if dur else (old_dur["duration"] if old_dur else None), int(completed), t),
        )
        conn.execute(
            "INSERT INTO recent(file_id,last_played_at,play_count) VALUES(?,?,1) ON CONFLICT(file_id) DO UPDATE SET "
            "play_count=recent.play_count+CASE WHEN ?-recent.last_played_at>1800 THEN 1 ELSE 0 END, last_played_at=?",
            (row["id"], t, t, t),
        )
        if prev is None or t - prev["last_played_at"] > 1800:
            log_activity("file_played", row["name"])
        return jsonify({"ok": True, "completed": completed})

    # ---- playlists ------------------------------------------------------------------
    def playlist_row(pid: str):
        if not re.fullmatch(r"[0-9a-f]{16}", pid or ""):
            return None
        return db().execute("SELECT * FROM playlists WHERE id=?", (pid,)).fetchone()

    @app.get("/api/v1/playlists")
    @login_required
    def playlists_list():
        rows = db().execute(
            "SELECT p.id,p.name,p.created_at,COUNT(i.file_id) AS n FROM playlists p LEFT JOIN playlist_items i ON i.playlist_id=p.id "
            "GROUP BY p.id ORDER BY p.created_at DESC").fetchall()
        return jsonify({"playlists": [{"id": r["id"], "name": r["name"], "created_at": r["created_at"], "track_count": r["n"]} for r in rows]})

    @app.post("/api/v1/playlists")
    @login_required
    def playlists_create():
        data = request.get_json(silent=True)
        name = data.get("name") if isinstance(data, dict) else None
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80) or any(ord(c) < 32 for c in name):
            return err("invalid_request", "Playlist name must be 1-80 characters.", 400)
        conn = db()
        if conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0] >= 100:
            return err("limit_reached", "Playlist limit reached (100).", 400)
        pid = secrets.token_hex(8)
        conn.execute("INSERT INTO playlists(id,name,created_at) VALUES(?,?,?)", (pid, name.strip(), now_s()))
        resp = jsonify({"id": pid, "name": name.strip(), "track_count": 0})
        resp.status_code = 201
        return resp

    @app.get("/api/v1/playlists/<pid>")
    @login_required
    def playlists_get(pid):
        p = playlist_row(pid)
        if p is None:
            return err("not_found", "Playlist not found.", 404)
        rows = db().execute(FILE_SELECT.replace("FROM files f ", "FROM files f JOIN playlist_items pi ON pi.file_id=f.id ", 1) +
                            "WHERE pi.playlist_id=? ORDER BY pi.position", (pid,)).fetchall()
        return jsonify({"id": p["id"], "name": p["name"], "items": [row_to_item(r) for r in rows]})

    @app.delete("/api/v1/playlists/<pid>")
    @login_required
    def playlists_delete(pid):
        if playlist_row(pid) is None:
            return err("not_found", "Playlist not found.", 404)
        conn = db()
        conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
        conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
        return jsonify({"ok": True})

    @app.post("/api/v1/playlists/<pid>/items")
    @login_required
    def playlists_add(pid):
        if playlist_row(pid) is None:
            return err("not_found", "Playlist not found.", 404)
        data = request.get_json(silent=True)
        fid = data.get("file_id") if isinstance(data, dict) else None
        conn = db()
        row = conn.execute("SELECT id,kind FROM files WHERE id=?", (fid,)).fetchone() if isinstance(fid, str) else None
        if row is None:
            return err("not_found", "File not found.", 404)
        if row["kind"] != "audio":
            return err("not_playable", "Playlists can only contain audio files.", 400)
        n = conn.execute("SELECT COUNT(*), COALESCE(MAX(position),-1) FROM playlist_items WHERE playlist_id=?", (pid,)).fetchone()
        if n[0] >= 2000:
            return err("limit_reached", "Playlist is full (2000 tracks).", 400)
        conn.execute("INSERT OR IGNORE INTO playlist_items(playlist_id,file_id,position,added_at) VALUES(?,?,?,?)", (pid, fid, n[1] + 1, now_s()))
        return jsonify({"ok": True})

    @app.delete("/api/v1/playlists/<pid>/items/<file_id>")
    @login_required
    def playlists_remove(pid, file_id):
        if playlist_row(pid) is None:
            return err("not_found", "Playlist not found.", 404)
        db().execute("DELETE FROM playlist_items WHERE playlist_id=? AND file_id=?", (pid, file_id))
        return jsonify({"ok": True})

    # ---- uploads ------------------------------------------------------------------------
    def reject_upload(upload_id, original, category, status, message, http=400, code="upload_rejected"):
        db().execute("INSERT INTO uploads(id,original_name,category,status,size,created_at,error) VALUES(?,?,?,?,?,?,?)",
                     (upload_id, (original or "")[:120], category, status, 0, now_s(), message[:200]))
        return err(code, message, http, upload_id=upload_id)

    @app.post("/api/v1/uploads")
    @login_required
    def uploads_create():
        if not cfg.uploads_enabled:
            return err("uploads_disabled", "Uploads are disabled in the server's private configuration.", 403)
        ok, retry = limiter.check("upload:" + g.ip, cfg.rates["upload_per_hour"], 3600)
        if not ok:
            return err("rate_limited", "Too many uploads. Try again later.", 429, {"Retry-After": str(retry)})
        if not upload_sem.acquire(blocking=False):
            return err("busy", "Another upload is in progress. Try again shortly.", 503, {"Retry-After": "5"})
        upload_id = secrets.token_hex(8)
        part = None
        try:
            category = request.form.get("category", "Uploads")
            f = request.files.get("file")
            if f is None or not f.filename:
                return reject_upload(upload_id, "", category, "rejected", "No file was provided.", code="no_file")
            if category not in cfg.upload_categories or category not in cfg.roots:
                return reject_upload(upload_id, f.filename, category, "rejected", "That destination is not available for uploads.", 400, "invalid_category")
            name = sanitize_filename(f.filename)
            if name is None:
                return reject_upload(upload_id, f.filename, category, "rejected", "The file name is not valid. Use a simple name with an extension.", code="invalid_filename")
            parts = name.lower().split(".")
            ext = parts[-1]
            if any(p in DENY_EXTS for p in parts[1:]):
                return reject_upload(upload_id, f.filename, category, "rejected", "This file type is not allowed.", code="type_not_allowed")
            if ext not in allowed_upload_exts(cfg, category):
                return reject_upload(upload_id, f.filename, category, "rejected", "'.%s' files are not accepted in %s." % (ext, category), code="type_not_allowed")
            root = cfg.roots[category]
            if not os.path.isdir(root):
                return reject_upload(upload_id, f.filename, category, "failed", "The destination folder is not available on the phone.", 507, "folder_unavailable")
            # copy into quarantine, enforcing the size limit while copying
            cfg.quarantine_dir.mkdir(parents=True, exist_ok=True)
            part = cfg.quarantine_dir / ("%s.part" % upload_id)
            total = 0
            with open(part, "xb") as out:
                while True:
                    chunk = f.stream.read(262144)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > cfg.max_upload_bytes:
                        raise ValueError("too_large")
                    out.write(chunk)
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                free = 0
            if free - total < cfg.min_free_bytes:
                return reject_upload(upload_id, f.filename, category, "failed", "Not enough free storage on the phone.", 507, "insufficient_storage")
            with open(part, "rb") as chk:
                head = chk.read(8192)
            problem = sniff_problem(ext, head)
            if problem:
                return reject_upload(upload_id, f.filename, category, "rejected", problem, 400, "content_rejected")
            # finalize: exclusive create so an existing file is never overwritten
            stem, _, _ext = name.rpartition(".")
            final_name, final_path = None, None
            for i in range(0, 1000):
                candidate = name if i == 0 else "%s (%d).%s" % (stem[:110], i, ext)
                target = os.path.join(root, candidate)
                real_parent = os.path.realpath(os.path.dirname(target))
                if real_parent != root:
                    raise RuntimeError("destination escaped root")
                try:
                    with open(target, "xb") as dst, open(part, "rb") as src:
                        shutil.copyfileobj(src, dst, 262144)
                    final_name, final_path = candidate, target
                    break
                except FileExistsError:
                    continue
            if final_name is None:
                return reject_upload(upload_id, f.filename, category, "failed", "Could not find a free file name.", 409, "name_conflict")
            conn = db()
            fid = index_single_file(conn, category, final_name, final_path)
            conn.execute("INSERT INTO uploads(id,original_name,category,status,size,created_at,completed_at,final_name,file_id) VALUES(?,?,?,?,?,?,?,?,?)",
                         (upload_id, f.filename[:120], category, "completed", total, now_s(), now_s(), final_name, fid))
            log_activity("upload_completed", "%s -> %s" % (category, final_name))
            resp = jsonify({"id": upload_id, "status": "completed", "category": category, "file_id": fid, "name": final_name,
                            "renamed": final_name != name, "size": total, "scanned_for_malware": False})
            resp.status_code = 201
            return resp
        except ValueError as exc:
            if str(exc) == "too_large":
                return reject_upload(upload_id, "", "", "rejected", "File exceeds the maximum upload size of %d MB." % (cfg.max_upload_bytes // 1048576), 413, "file_too_large")
            raise
        finally:
            upload_sem.release()
            if part is not None:
                try:
                    os.unlink(part)
                except OSError:
                    pass

    @app.get("/api/v1/uploads/<upload_id>")
    @login_required
    def uploads_get(upload_id):
        if not re.fullmatch(r"[0-9a-f]{16}", upload_id):
            return err("not_found", "Upload not found.", 404)
        r = db().execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if r is None:
            return err("not_found", "Upload not found.", 404)
        return jsonify({"id": r["id"], "status": r["status"], "category": r["category"], "size": r["size"], "name": r["final_name"],
                        "file_id": r["file_id"], "error": r["error"], "created_at": r["created_at"], "completed_at": r["completed_at"]})

    # ---- temporary shares -------------------------------------------------------------------
    def share_status(r) -> str:
        if r["revoked_at"]:
            return "revoked"
        return "expired" if r["expires_at"] <= now_s() else "active"

    @app.get("/api/v1/shares")
    @login_required
    def shares_list():
        rows = db().execute(
            "SELECT s.*, f.name AS fname, f.category AS fcat FROM shares s LEFT JOIN files f ON f.id=s.file_id ORDER BY s.created_at DESC LIMIT 100").fetchall()
        return jsonify({"shares": [{
            "id": r["id"], "file_id": r["file_id"], "file_name": r["fname"], "category": r["fcat"], "mode": r["mode"], "created_at": r["created_at"],
            "expires_at": r["expires_at"], "revoked_at": r["revoked_at"], "status": share_status(r), "access_count": r["access_count"],
            "last_access": r["last_access"]} for r in rows]})

    @app.post("/api/v1/shares")
    @login_required
    def shares_create():
        ok, retry = limiter.check("share-create:" + g.ip, cfg.rates["share_create_per_minute"], 60)
        if not ok:
            return err("rate_limited", "Too many share requests.", 429, {"Retry-After": str(retry)})
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("file_id"), str):
            return err("invalid_request", "Send JSON with 'file_id', 'duration' and 'mode'.", 400)
        minutes = SHARE_DURATIONS.get(str(data.get("duration", "")))
        if minutes is None:
            return err("invalid_duration", "Duration must be one of: 15m, 1h, 6h, 24h.", 400)
        mode = data.get("mode", "view")
        if mode not in ("view", "download"):
            return err("invalid_mode", "Mode must be 'view' or 'download'.", 400)
        row, real = lookup_file(data["file_id"])
        if row is None:
            return err("not_found", "File not found.", 404)
        if mode == "view" and row["ext"] not in INLINE_EXTS:
            return err("view_not_supported", "This format cannot be viewed in a browser. Choose view-and-download instead.", 400)
        conn = db()
        t = now_s()
        if conn.execute("SELECT COUNT(*) FROM shares WHERE revoked_at IS NULL AND expires_at>?", (t,)).fetchone()[0] >= 50:
            return err("limit_reached", "Too many active shares. Revoke some first.", 400)
        token = secrets.token_urlsafe(32)
        sid = secrets.token_hex(8)
        conn.execute("INSERT INTO shares(id,token_hash,file_id,mode,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                     (sid, hm("share:" + token), row["id"], mode, t, t + minutes * 60))
        log_activity("share_created", "%s (%s, %dm)" % (row["name"], mode, minutes))
        resp = jsonify({"id": sid, "url": "%s/api/v1/s/%s" % (public_base(), token), "expires_at": t + minutes * 60, "mode": mode,
                        "file": {"id": row["id"], "name": row["name"]},
                        "notice": "This link is shown only now. Anyone with it can view the file until it expires or is revoked, "
                                  "and could save, copy, screenshot or record it."})
        resp.status_code = 201
        return resp

    @app.delete("/api/v1/shares/<share_id>")
    @login_required
    def shares_revoke(share_id):
        if not re.fullmatch(r"[0-9a-f]{16}", share_id):
            return err("not_found", "Share not found.", 404)
        conn = db()
        r = conn.execute("SELECT s.*, f.name AS fname FROM shares s LEFT JOIN files f ON f.id=s.file_id WHERE s.id=?", (share_id,)).fetchone()
        if r is None:
            return err("not_found", "Share not found.", 404)
        if r["revoked_at"] is None:
            conn.execute("UPDATE shares SET revoked_at=? WHERE id=?", (now_s(), share_id))
            log_activity("share_revoked", r["fname"] or "")
        return jsonify({"ok": True, "status": "revoked"})

    @app.get("/api/v1/s/<token>")
    def share_access(token):
        """Public, token-scoped access to exactly one file. Not a user session."""
        ok, retry = limiter.check("share:" + g.ip, cfg.rates["share_access_per_minute"], 60)
        if not ok:
            return err("rate_limited", "Too many requests.", 429, {"Retry-After": str(retry)})
        gone = err("share_unavailable", "This share link is invalid, expired or has been revoked.", 404)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{30,64}", token):
            return gone
        conn = db()
        r = conn.execute("SELECT * FROM shares WHERE token_hash=?", (hm("share:" + token),)).fetchone()
        if r is None or r["revoked_at"] is not None or r["expires_at"] <= now_s():
            return gone
        row, real = lookup_file(r["file_id"])
        if row is None:
            return gone
        want_download = request.args.get("download") == "1"
        if want_download and r["mode"] != "download":
            return err("download_not_allowed", "This share is view-only.", 403)
        rng = request.headers.get("Range")
        if not rng or rng.strip().lower().startswith("bytes=0-"):
            conn.execute("UPDATE shares SET access_count=access_count+1, last_access=? WHERE id=?", (now_s(), r["id"]))
        force = want_download or row["ext"] not in INLINE_EXTS
        resp = serve_file(real, row["name"], row["ext"], force_download=force, shared=True)
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return resp

    @app.get("/api/v1/activity")
    @login_required
    def activity():
        rows = db().execute("SELECT ts,event,detail FROM activity ORDER BY id DESC LIMIT ?", (int_arg("limit", 100, 1, 500),)).fetchall()
        failed = db().execute("SELECT COUNT(*) FROM activity WHERE event='login_failed'").fetchone()[0]
        return jsonify({"events": [{"ts": r["ts"], "event": r["event"], "detail": r["detail"]} for r in rows], "failed_login_count": failed})

    # ---- maintenance ----------------------------------------------------------------------------
    def maintenance_once() -> None:
        conn = open_db(cfg.db_path)
        try:
            t = now_s()
            conn.execute("DELETE FROM sessions WHERE expires_at<=? OR last_seen<?", (t, t - cfg.idle_seconds))
            conn.execute("DELETE FROM shares WHERE expires_at<? OR revoked_at<?", (t - 86400, t - 86400))
            conn.execute("DELETE FROM uploads WHERE created_at<?", (t - 30 * 86400,))
        finally:
            conn.close()
        cutoff = time.time() - 3600
        for folder in (cfg.quarantine_dir, cfg.quarantine_dir / "tmp"):
            try:
                for p in folder.iterdir():
                    if p.is_file() and (p.suffix == ".part" or folder.name == "tmp") and p.stat().st_mtime < cutoff:
                        p.unlink()
            except OSError:
                pass

    def maintenance_loop() -> None:
        while not stop_event.wait(300):
            try:
                maintenance_once()
            except Exception:  # noqa: BLE001
                log.exception("Maintenance failed")

    app.extensions["nexora"] = SimpleNamespace(cfg=cfg, scan_now=scan_now, maintenance_once=maintenance_once, stop_event=stop_event,
                                               scan_state=scan_state, limiter=limiter, guard=guard, hm=hm, file_id_for=file_id_for)
    try:
        maintenance_once()
    except Exception:  # noqa: BLE001
        log.exception("Initial maintenance failed")
    if start_background:
        threading.Thread(target=maintenance_loop, name="nexora-maint", daemon=True).start()
        if cfg.scan_on_start:
            start_scan_thread()
    return app


# --------------------------------------------------------------------------
# Command line: init / check / set-password / run
# --------------------------------------------------------------------------
def read_secret(prompt: str) -> str:
    try:
        return getpass.getpass(prompt)
    except Exception:  # noqa: BLE001
        print("(Your terminal cannot hide typing, so the password will be visible while you type it.)")
        return input(prompt)


def prompt_new_password(env_name: str | None) -> str:
    if env_name:
        pw = os.environ.get(env_name, "")
        if len(pw) < 10:
            raise SystemExit("Password from %s must be at least 10 characters." % env_name)
        return pw
    while True:
        a = read_secret("Choose a NEXORA password (10+ characters): ")
        if len(a) < 10:
            print("Too short. Use at least 10 characters (a long passphrase is best).")
            continue
        if a != read_secret("Repeat the password: "):
            print("Passwords did not match. Try again.")
            continue
        return a


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(str(tmp), str(path))
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


def cmd_init(args) -> int:
    private, library = default_paths()
    if args.private_dir:
        private = Path(args.private_dir)
    if args.library_root:
        library = Path(args.library_root)
    cfg_file = Path(args.config) if args.config else config_path_for(private)
    if cfg_file.exists() and not args.force:
        print("A configuration already exists at the private config path. Use --force to replace it (this resets the password and sessions).")
        return 1
    origins = args.origin or []
    if not origins:
        entered = input("Your website origin (e.g. https://yourname.github.io) [comma-separate several]: ").strip()
        origins = [o.strip().rstrip("/") for o in entered.split(",") if o.strip()]
    password = prompt_new_password(args.password_env)
    local = all(urllib.parse.urlsplit(o).hostname in ("localhost", "127.0.0.1") for o in origins) if origins else False
    raw = {
        "version": 1,
        "library_root": str(library),
        "allowed_origins": origins,
        "password_hash": hash_password(password),
        "session_secret": secrets.token_hex(32),
        "bind_host": "127.0.0.1",
        "port": args.port,
        "public_base_url": "",
        "cookie_secure": not local,
        "cookie_samesite": "Lax" if local else "None",
        "session_hours": 12,
        "idle_minutes": 240,
        "uploads_enabled": True,
        "upload_categories": ["Uploads", "Movies", "Music", "Photos", "Documents"],
        "max_upload_mb": 500,
        "min_free_space_mb": 200,
        "login_max_failures": 5,
        "login_lock_minutes": 15,
        "telemetry_enabled": True,
    }
    cfg, errors, warnings = build_config(raw, private)
    if errors:
        print("Cannot create configuration:")
        for e in errors:
            print("  -", e)
        return 2
    for sub in ("Config", "Database", "Quarantine", "Logs"):
        (private / sub).mkdir(parents=True, exist_ok=True)
    try:
        for root in cfg.roots.values():
            os.makedirs(root, exist_ok=True)
        cfg.thumbs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print("Could not create the library folders (%s)." % exc.__class__.__name__)
        print("On Android: allow Pydroid 3 to access storage (Settings > Apps > Pydroid 3 > Permissions), or create the folders yourself.")
    write_private_json(cfg_file, raw)
    print("NEXORA is initialised.")
    print("  Private config : %s" % cfg_file)
    print("  Library folder : %s" % library)
    for w in warnings:
        print("  warning:", w)
    print("Next: python nexora_server.py check   then   python nexora_server.py run")
    return 0


def load_runtime(config_arg: str | None):
    private, _ = default_paths()
    cfg_file = Path(config_arg) if config_arg else config_path_for(private)
    if not cfg_file.exists():
        print("No configuration found. Run first:  python nexora_server.py init")
        return None, None
    try:
        raw = load_config_file(cfg_file)
    except (OSError, json.JSONDecodeError) as exc:
        print("Could not read the configuration file (%s). Fix the JSON or run init --force." % exc.__class__.__name__)
        return None, None
    private_dir = cfg_file.parent.parent if cfg_file.parent.name == "Config" else private
    cfg, errors, warnings = build_config(raw, private_dir)
    for w in warnings:
        print("warning:", w)
    if errors or cfg is None:
        print("Configuration problems:")
        for e in errors:
            print("  -", e)
        return None, cfg_file
    return cfg, cfg_file


def cmd_check(args) -> int:
    cfg, _ = load_runtime(args.config)
    if cfg is None:
        return 2
    print("Configuration is valid.")
    for cat, root in cfg.roots.items():
        state = "ok" if os.path.isdir(root) and os.access(root, os.R_OK) else "MISSING or no permission"
        print("  %-10s %s" % (cat, state))
    print("  uploads    %s" % ("enabled" if cfg.uploads_enabled else "disabled"))
    print("  cookies    secure=%s samesite=%s" % (cfg.cookie_secure, cfg.cookie_samesite))
    print("  origins    %s" % ", ".join(cfg.allowed_origins))
    return 0


def cmd_set_password(args) -> int:
    private, _ = default_paths()
    cfg_file = Path(args.config) if args.config else config_path_for(private)
    if not cfg_file.exists():
        print("No configuration found. Run init first.")
        return 1
    raw = load_config_file(cfg_file)
    raw["password_hash"] = hash_password(prompt_new_password(args.password_env))
    if args.rotate_secret:
        raw["session_secret"] = secrets.token_hex(32)
    write_private_json(cfg_file, raw)
    db_file = (cfg_file.parent.parent / "Database" / "nexora.db")
    if db_file.exists():
        conn = open_db(db_file)
        try:
            conn.execute("DELETE FROM sessions")
        except sqlite3.DatabaseError:
            pass
        finally:
            conn.close()
    print("Password updated and all existing sessions were signed out. Restart the server if it is running.")
    return 0


def cmd_run(args) -> int:
    cfg, _ = load_runtime(args.config)
    if cfg is None:
        return 2
    if args.port:
        cfg.port = args.port
    app = create_app(cfg, start_background=True)
    log = logging.getLogger("nexora")
    host = "127.0.0.1" if cfg.bind_host == "localhost" else cfg.bind_host
    server, kind = None, "werkzeug"
    try:
        import waitress  # type: ignore
        from waitress.server import create_server  # type: ignore

        server = create_server(app, host=host, port=cfg.port, threads=8, max_request_body_size=cfg.max_upload_bytes + 4 * 1024 * 1024,
                               ident="nexora", clear_untrusted_proxy_headers=True)
        kind = "waitress"
    except ImportError:
        from werkzeug.serving import make_server

        server = make_server(host, cfg.port, app, threaded=True)
    except Exception as exc:  # noqa: BLE001
        print("Could not start the server: %s. Is port %d already in use?" % (exc.__class__.__name__, cfg.port))
        return 1

    def stop(*_a):
        print("\nShutting down NEXORA...")
        app.extensions["nexora"].stop_event.set()
        threading.Thread(target=(server.close if kind == "waitress" else server.shutdown), daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, stop)
        except (ValueError, OSError):
            pass
    print("=" * 60)
    print(" NEXORA Mobile Server %s  -  Created By Shiv Yogi" % VERSION)
    print("=" * 60)
    print(" Listening on   : http://%s:%d  (local only; tunnel it for remote access)" % (host, cfg.port))
    print(" WSGI server    : %s%s" % (kind, "" if kind == "waitress" else " (development server; install 'waitress' for a production server)"))
    print(" Health check   : http://%s:%d/api/v1/health" % (host, cfg.port))
    print(" Allowed origins: %s" % ", ".join(cfg.allowed_origins))
    print(" Cookies        : secure=%s samesite=%s" % (cfg.cookie_secure, cfg.cookie_samesite))
    print(" Library        : %s" % ", ".join("%s=%s" % (c, "ok" if os.path.isdir(r) else "MISSING") for c, r in cfg.roots.items()))
    print(" Uploads        : %s (max %d MB, no malware scanning)" % ("enabled" if cfg.uploads_enabled else "disabled", cfg.max_upload_bytes // 1048576))
    print(" Optional libs  : psutil=%s Pillow=%s" % (psutil is not None, Image is not None))
    print(" Press Ctrl+C (or the stop button) to stop. Android may stop this process in the background.")
    log.info("Server started on %s:%d (%s)", host, cfg.port, kind)
    try:
        server.run() if kind == "waitress" else server.serve_forever()
    except KeyboardInterrupt:
        stop()
    finally:
        try:
            server.server_close() if kind == "werkzeug" else None
        except Exception:  # noqa: BLE001
            pass
        log.info("Server stopped")
    print("NEXORA stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexora_server.py", description="NEXORA Mobile Server")
    parser.add_argument("--config", help="path to config.json (default: <private dir>/Config/config.json)")
    sub = parser.add_subparsers(dest="cmd")
    p_init = sub.add_parser("init", help="create folders and a private configuration")
    p_init.add_argument("--origin", action="append", help="allowed website origin (repeatable)")
    p_init.add_argument("--library-root")
    p_init.add_argument("--private-dir")
    p_init.add_argument("--port", type=int, default=8787)
    p_init.add_argument("--password-env", help="read the password from this environment variable instead of prompting")
    p_init.add_argument("--force", action="store_true")
    sub.add_parser("check", help="validate configuration")
    p_pw = sub.add_parser("set-password", help="change the password (offline, private)")
    p_pw.add_argument("--password-env")
    p_pw.add_argument("--rotate-secret", action="store_true")
    p_run = sub.add_parser("run", help="start the server")
    p_run.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "port"):
        args.port = None
    return {"init": cmd_init, "check": cmd_check, "set-password": cmd_set_password, "run": cmd_run}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
