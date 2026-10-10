"""NEXORA backend tests. Run from the mobile-server folder:

    python -m unittest discover -s tests -v

These tests execute the real Flask app (test client) and a real server process.
They never touch real phone storage: everything lives in a temporary directory.
"""
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nexora_server as ns  # noqa: E402

ORIGIN = "https://shiv.github.io"
BASE = "https://nexora.test"
PASSWORD = "correct horse battery staple"
PW_HASH = ns.hash_password(PASSWORD)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 13 + b"IHDR" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40  # 10 KB+ fake mp4 header + data


def make_raw(tmp: Path, **over):
    raw = {
        "version": 1,
        "library_root": str(tmp / "lib" / "NEXORA"),
        "allowed_origins": [ORIGIN],
        "password_hash": PW_HASH,
        "session_secret": "a" * 64,
        "cookie_secure": True,
        "cookie_samesite": "None",
        "login_fail_delay_ms": 0,
        "min_free_space_mb": 0,
    }
    raw.update(over)
    return raw


class Base(unittest.TestCase):
    raw_over: dict = {}

    def setUp(self):
        self._saved_tempdir = tempfile.tempdir  # the server redirects tempfile into its private folder
        tempfile.tempdir = None
        self.tmp = Path(tempfile.mkdtemp(prefix="nexora-test-"))
        self.private = self.tmp / "private"
        raw = make_raw(self.tmp, **self.raw_over)
        for sub in ("Movies", "Music", "Photos", "Documents", "Uploads", "Downloads"):
            (self.tmp / "lib" / "NEXORA" / sub).mkdir(parents=True)
        self.lib = self.tmp / "lib" / "NEXORA"
        cfg, errors, _w = ns.build_config(raw, self.private)
        self.assertEqual(errors, [])
        self.cfg = cfg
        self.populate()
        self.app = ns.create_app(cfg)
        self.nx = self.app.extensions["nexora"]
        self.nx.scan_now()
        self.c = self.app.test_client()

    def tearDown(self):
        tempfile.tempdir = self._saved_tempdir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def populate(self):
        (self.lib / "Movies" / "clip.mp4").write_bytes(MP4)
        (self.lib / "Movies" / "Season 1").mkdir()
        (self.lib / "Movies" / "Season 1" / "ep1.mp4").write_bytes(MP4)
        (self.lib / "Movies" / ".hidden.mp4").write_bytes(MP4)
        (self.lib / "Music" / "song.mp3").write_bytes(b"ID3" + b"\x00" * 200)
        (self.lib / "Music" / "song2.mp3").write_bytes(b"ID3" + b"\x00" * 200)
        (self.lib / "Photos" / "pic.png").write_bytes(PNG)
        (self.lib / "Documents" / "note.txt").write_text("hello nexora")
        (self.lib / "Documents" / "page.html").write_text("<script>alert(1)</script>")
        (self.lib / "Documents" / "doc.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 100)
        (self.lib / "Documents" / "report.docx").write_bytes(b"PK\x03\x04" + b"x" * 100)

    # -- helpers ------------------------------------------------------------
    def req(self, method, path, *, origin=ORIGIN, csrf=True, client=None, **kw):
        headers = dict(kw.pop("headers", {}))
        if origin:
            headers["Origin"] = origin
        if csrf and method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
            headers["X-NEXORA-CSRF"] = "1"
        resp = (client or self.c).open(path, method=method, base_url=BASE, headers=headers, **kw)
        resp.get_data()  # consume and close the response so streaming slots are released
        return resp

    def login(self, client=None, password=PASSWORD):
        return self.req("POST", "/api/v1/auth/login", json={"password": password}, client=client)

    def authed(self):
        r = self.login()
        self.assertEqual(r.status_code, 200, r.data)

    def files(self, **params):
        q = "&".join("%s=%s" % kv for kv in params.items())
        r = self.req("GET", "/api/v1/files?" + q)
        self.assertEqual(r.status_code, 200, r.data)
        return r.get_json()["items"]

    def fid(self, name, category=None):
        for it in self.files(limit=200):
            if it["name"] == name and (category is None or it["category"] == category):
                return it["id"]
        self.fail("file %s not indexed" % name)

    def db(self):
        conn = sqlite3.connect(str(self.cfg.db_path))
        conn.row_factory = sqlite3.Row
        return conn


class TestConfigAndHashing(unittest.TestCase):
    def test_hash_roundtrip_and_format(self):
        h = ns.hash_password("pw-number-one")
        self.assertTrue(h.startswith("scrypt$") or h.startswith("pbkdf2_sha256$"))
        self.assertNotIn("pw-number-one", h)
        self.assertTrue(ns.verify_password("pw-number-one", h))
        self.assertFalse(ns.verify_password("pw-number-two", h))
        self.assertNotEqual(h, ns.hash_password("pw-number-one"))  # salted
        self.assertFalse(ns.verify_password("x", "garbage"))

    def test_pbkdf2_fallback_verifies(self):
        import base64, hashlib
        salt = b"s" * 16
        dk = hashlib.pbkdf2_hmac("sha256", b"abc", salt, 1000, 32)
        stored = "pbkdf2_sha256$1000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(dk).decode())
        self.assertTrue(ns.verify_password("abc", stored))
        self.assertFalse(ns.verify_password("abd", stored))

    def build(self, tmp, **over):
        return ns.build_config(make_raw(Path(tmp), **over), Path(tmp) / "private")

    def test_validation_errors(self):
        with tempfile.TemporaryDirectory() as t:
            _c, errs, _ = self.build(t, password_hash="")
            self.assertTrue(any("password_hash" in e for e in errs))
            _c, errs, _ = self.build(t, session_secret="CHANGE_ME" * 8)
            self.assertTrue(any("session_secret" in e for e in errs))
            _c, errs, _ = self.build(t, session_secret="short")
            self.assertTrue(any("session_secret" in e for e in errs))
            _c, errs, _ = self.build(t, allowed_origins=["*"])
            self.assertTrue(any("origin" in e.lower() for e in errs))
            _c, errs, _ = self.build(t, allowed_origins=[])
            self.assertTrue(errs)
            _c, errs, _ = self.build(t, allowed_origins=["https://x.github.io/"])
            self.assertTrue(errs)
            _c, errs, _ = self.build(t, cookie_secure=False, cookie_samesite="None")
            self.assertTrue(any("cookie" in e.lower() for e in errs))
            _c, errs, _ = self.build(t, categories={"Uploads": "/storage/emulated/0"})
            self.assertTrue(any("too broad" in e for e in errs))
            _c, errs, _ = self.build(t, categories={"Uploads": "Movies/sub"})
            self.assertTrue(any("overlap" in e for e in errs))
            _c, errs, _ = self.build(t, upload_categories=["Downloads"])
            self.assertTrue(errs)
            _c, errs, _ = self.build(t, extra_upload_extensions=["php"])
            self.assertTrue(errs)
            _c, errs, w = self.build(t, bind_host="0.0.0.0")
            self.assertEqual(errs, [])
            self.assertTrue(w)

    def test_private_dir_must_not_be_in_library(self):
        with tempfile.TemporaryDirectory() as t:
            raw = make_raw(Path(t))
            priv = Path(raw["library_root"]) / "Movies" / "secret"
            _c, errs, _ = ns.build_config(raw, priv)
            self.assertTrue(any("Private folder" in e for e in errs))

    def test_valid_config_ok(self):
        with tempfile.TemporaryDirectory() as t:
            cfg, errs, _ = self.build(t)
            self.assertEqual(errs, [])
            self.assertEqual(cfg.bind_host, "127.0.0.1")  # localhost by default


class TestHelpers(unittest.TestCase):
    def test_sanitize_filename(self):
        s = ns.sanitize_filename
        self.assertEqual(s("../../etc/passwd.txt"), "passwd.txt")
        self.assertEqual(s("..\\..\\win.PNG"), "win.png")
        self.assertEqual(s("my song (1).MP3"), "my song (1).mp3")
        self.assertEqual(s(".hidden.jpg"), "hidden.jpg")
        self.assertIsNone(s(""))
        self.assertIsNone(s("noext"))
        self.assertIsNone(s("..."))
        self.assertIsNone(s("a.verylongextension"))
        self.assertNotIn("\x00", s("a\x00b.jpg"))
        self.assertLessEqual(len(s("x" * 500 + ".jpg")), 120)
        self.assertEqual(s("we<ird>:name?.jpg"), "we_ird__name_.jpg")

    def test_parse_range(self):
        p = ns.parse_range
        self.assertEqual(p(None, 100), ("full",))
        self.assertEqual(p("bytes=0-9", 100), ("range", 0, 9))
        self.assertEqual(p("bytes=90-", 100), ("range", 90, 99))
        self.assertEqual(p("bytes=-10", 100), ("range", 90, 99))
        self.assertEqual(p("bytes=50-500", 100), ("range", 50, 99))
        self.assertEqual(p("bytes=100-", 100), ("unsatisfiable",))
        self.assertEqual(p("bytes=-0", 100), ("unsatisfiable",))
        self.assertEqual(p("bytes=0-0", 0), ("unsatisfiable",))
        self.assertEqual(p("bytes=0-1,5-6", 100), ("full",))
        self.assertEqual(p("bytes=9-3", 100), ("full",))
        self.assertEqual(p("items=0-3", 100), ("full",))
        self.assertEqual(p("bytes=abc", 100), ("full",))

    def test_content_disposition_safe(self):
        d = ns.content_disposition("attachment", 'ev"il\r\nname ü.mp4')
        self.assertNotIn("\r", d)
        self.assertNotIn("\n", d)
        self.assertEqual(d.count('"'), 2)
        self.assertIn("filename*=UTF-8''", d)

    def test_sniff(self):
        self.assertIsNone(ns.sniff_problem("png", PNG))
        self.assertIsNotNone(ns.sniff_problem("png", b"hello world"))
        self.assertIsNotNone(ns.sniff_problem("txt", b"MZ\x90\x00"))
        self.assertIsNotNone(ns.sniff_problem("txt", b"#!/bin/sh\nrm -rf /"))
        self.assertIsNotNone(ns.sniff_problem("txt", b"<script>x</script>"))
        self.assertIsNotNone(ns.sniff_problem("txt", b"a\x00b"))
        self.assertIsNotNone(ns.sniff_problem("pdf", b""))
        self.assertIsNone(ns.sniff_problem("txt", "héllo".encode()))


class TestDatabase(Base):
    def test_schema_and_idempotent_migration(self):
        conn = self.db()
        self.assertEqual(conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(ns.SCHEMA_VERSION))
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("files", "favorites", "watchlist", "playback", "recent", "sessions", "shares", "activity", "playlists", "uploads"):
            self.assertIn(t, names)
        conn.close()
        self.assertEqual(ns.migrate_db(self.cfg.db_path), ns.SCHEMA_VERSION)  # second run is a no-op

    def test_refuses_newer_schema(self):
        conn = self.db()
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        with self.assertRaises(RuntimeError):
            ns.migrate_db(self.cfg.db_path)


class TestHealthAndAuth(Base):
    def test_health_minimal_and_public(self):
        r = self.req("GET", "/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(set(body), {"status", "service", "origin_allowed"})
        self.assertTrue(body["origin_allowed"])
        r = self.req("GET", "/api/v1/health", origin="https://evil.example")
        self.assertFalse(r.get_json()["origin_allowed"])
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "*")
        self.assertNotIn("Access-Control-Allow-Credentials", r.headers)

    def test_private_routes_require_auth(self):
        fid = "0" * 24
        gets = ["/api/v1/dashboard", "/api/v1/files", "/api/v1/files/" + fid, "/api/v1/files/%s/stream" % fid, "/api/v1/files/%s/download" % fid,
                "/api/v1/files/%s/thumbnail" % fid, "/api/v1/categories", "/api/v1/storage", "/api/v1/device/status", "/api/v1/favorites",
                "/api/v1/watchlist", "/api/v1/recent", "/api/v1/shares", "/api/v1/playlists", "/api/v1/activity", "/api/v1/uploads/" + "0" * 16]
        for path in gets:
            r = self.req("GET", path)
            self.assertEqual(r.status_code, 401, path)
            self.assertEqual(r.get_json()["error"]["code"], "unauthenticated")
        posts = ["/api/v1/favorites", "/api/v1/watchlist", "/api/v1/playback/progress", "/api/v1/uploads", "/api/v1/shares", "/api/v1/playlists",
                 "/api/v1/library/rescan"]
        for path in posts:
            self.assertEqual(self.req("POST", path, json={}).status_code, 401, path)
        self.assertEqual(self.req("DELETE", "/api/v1/shares/" + "0" * 16).status_code, 401)
        self.assertEqual(self.req("DELETE", "/api/v1/favorites/" + fid).status_code, 401)

    def test_session_info_when_logged_out(self):
        self.assertEqual(self.req("GET", "/api/v1/auth/session").get_json(), {"authenticated": False})

    def test_login_success_cookie_flags_and_no_secret_leak(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        sc = r.headers["Set-Cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=None", "Path=/"):
            self.assertIn(flag, sc)
        self.assertTrue(sc.startswith("__Host-nexora_sid="))
        self.assertNotIn("Domain", sc)
        self.assertNotIn(PW_HASH, r.get_data(as_text=True))
        sid = sc.split("=", 1)[1].split(";", 1)[0]
        conn = self.db()
        stored = [row[0] for row in conn.execute("SELECT id_hash FROM sessions")]
        self.assertNotIn(sid, stored)  # only an HMAC of the session id is stored
        self.assertEqual(self.req("GET", "/api/v1/auth/session").get_json()["authenticated"], True)
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 200)

    def test_login_wrong_password(self):
        r = self.login(password="nope")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"]["code"], "invalid_credentials")
        self.assertNotIn("Set-Cookie", r.headers)
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 401)

    def test_login_malformed_bodies(self):
        for kw in ({"data": "not json", "content_type": "application/json"}, {"json": {"password": 5}}, {"json": ["x"]}, {"json": {}}):
            r = self.req("POST", "/api/v1/auth/login", **kw)
            self.assertEqual(r.status_code, 400, kw)
            self.assertEqual(r.get_json()["error"]["code"], "invalid_request")
        r = self.req("POST", "/api/v1/auth/login", json={"password": "x" * 5000})
        self.assertEqual(r.status_code, 401)

    def test_login_lockout_and_rate_limit(self):
        for i in range(self.cfg.login_max_failures - 1):
            self.assertEqual(self.login(password="bad").status_code, 401)
        r = self.login(password="bad")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"]["code"], "locked")
        self.assertIn("Retry-After", r.headers)
        r = self.login()  # correct password is also refused while locked
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 401)

    def test_login_per_minute_limit(self):
        self.cfg.rates["login_per_minute"] = 3
        codes = [self.login(password="bad").status_code for _ in range(5)]
        self.assertIn(429, codes)

    def test_csrf_and_origin_checks(self):
        self.assertEqual(self.req("POST", "/api/v1/auth/login", json={"password": PASSWORD}, origin=None).status_code, 403)
        self.assertEqual(self.req("POST", "/api/v1/auth/login", json={"password": PASSWORD}, origin="https://evil.example").status_code, 403)
        r = self.req("POST", "/api/v1/auth/login", json={"password": PASSWORD}, csrf=False)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "csrf_failed"))
        self.authed()
        self.assertEqual(self.req("POST", "/api/v1/auth/logout", origin="https://evil.example").status_code, 403)
        self.assertEqual(self.req("POST", "/api/v1/playlists", json={"name": "x"}, csrf=False).status_code, 403)
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 200)  # still logged in

    def test_cors_headers(self):
        r = self.req("OPTIONS", "/api/v1/files", headers={"Access-Control-Request-Method": "GET"})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(r.headers["Access-Control-Allow-Credentials"], "true")
        self.assertIn("X-NEXORA-CSRF", r.headers["Access-Control-Allow-Headers"])
        r = self.req("OPTIONS", "/api/v1/files", origin="https://evil.example")
        self.assertEqual(r.status_code, 403)
        r = self.req("GET", "/api/v1/auth/session", origin="https://evil.example")
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)

    def test_security_headers_and_no_store(self):
        self.authed()
        r = self.req("GET", "/api/v1/dashboard")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertIn("Strict-Transport-Security", r.headers)

    def test_session_regeneration_and_logout(self):
        r1 = self.login()
        sid1 = r1.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
        r2 = self.login()  # logging in again with the old cookie present replaces the session
        sid2 = r2.headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
        self.assertNotEqual(sid1, sid2)
        old = self.app.test_client()
        old.set_cookie("__Host-nexora_sid", sid1, domain="nexora.test")
        self.assertEqual(self.req("GET", "/api/v1/dashboard", client=old).status_code, 401)
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 200)
        out = self.req("POST", "/api/v1/auth/logout")
        self.assertEqual(out.status_code, 200)
        self.assertIn("Expires=Thu, 01 Jan 1970", out.headers["Set-Cookie"])
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 401)
        replay = self.app.test_client()
        replay.set_cookie("__Host-nexora_sid", sid2, domain="nexora.test")
        self.assertEqual(self.req("GET", "/api/v1/dashboard", client=replay).status_code, 401)  # server-side invalidation

    def test_session_expiry_and_idle(self):
        self.authed()
        conn = self.db()
        conn.execute("UPDATE sessions SET expires_at=?", (int(time.time()) - 1,))
        conn.commit()
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 401)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        self.authed()
        conn.execute("UPDATE sessions SET last_seen=?", (int(time.time()) - self.cfg.idle_seconds - 10,))
        conn.commit()
        self.assertEqual(self.req("GET", "/api/v1/dashboard").status_code, 401)
        conn.close()

    def test_error_shapes_have_no_tracebacks(self):
        r = self.req("GET", "/api/v1/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "not_found")
        r = self.req("PUT", "/api/v1/health", csrf=False)
        self.assertEqual(r.status_code, 403)  # unsafe method needs the CSRF header first
        r = self.req("PUT", "/api/v1/health")
        self.assertEqual(r.status_code, 405)
        self.assertNotIn("Traceback", r.get_data(as_text=True))

    def test_oversized_json_body_rejected(self):
        r = self.req("POST", "/api/v1/auth/login", data=b"{" + b" " * 70000 + b"}", content_type="application/json")
        self.assertEqual(r.status_code, 413)

    def test_api_rate_limit(self):
        self.cfg.rates["api_per_minute"] = 5
        codes = [self.req("GET", "/api/v1/health").status_code for _ in range(8)]
        self.assertEqual(codes[:5], [200] * 5)
        self.assertIn(429, codes)


class TestLibraryAndSecurity(Base):
    def setUp(self):
        super().setUp()
        self.authed()

    def test_listing_real_files_only_and_hidden_skipped(self):
        names = {i["name"] for i in self.files(limit=200)}
        self.assertEqual(names, {"clip.mp4", "ep1.mp4", "song.mp3", "song2.mp3", "pic.png", "note.txt", "page.html", "doc.pdf", "report.docx"})
        self.assertNotIn(".hidden.mp4", names)

    def test_no_absolute_paths_in_any_json(self):
        fid = self.fid("clip.mp4")
        bodies = []
        for p in ("/api/v1/files?limit=200", "/api/v1/files/" + fid, "/api/v1/dashboard", "/api/v1/categories", "/api/v1/storage", "/api/v1/device/status"):
            bodies.append(self.req("GET", p).get_data(as_text=True))
        joined = "\n".join(bodies)
        self.assertNotIn(str(self.tmp), joined)
        self.assertNotIn("/private", joined)
        self.assertNotIn(PW_HASH, joined)
        self.assertNotIn("a" * 64, joined)  # session secret

    def test_search_sort_pagination_filters(self):
        self.assertEqual([i["name"] for i in self.files(q="ep1")], ["ep1.mp4"])
        self.assertEqual(self.files(q="%"), [])  # LIKE wildcards are escaped
        self.assertEqual(self.files(q="_"), [])
        r = self.req("GET", "/api/v1/files?category=Movies&sort=size&order=desc&limit=1&offset=0").get_json()
        self.assertEqual((r["total"], len(r["items"])), (2, 1))
        self.assertEqual([i["name"] for i in self.files(kind="audio", sort="name")], ["song.mp3", "song2.mp3"])
        self.assertEqual(self.req("GET", "/api/v1/files?category=../etc").status_code, 400)
        self.assertEqual(self.req("GET", "/api/v1/files?sort=name;DROP").status_code, 400)
        self.assertEqual(self.req("GET", "/api/v1/files?kind=evil").status_code, 400)
        self.assertEqual(len(self.req("GET", "/api/v1/files?limit=99999").get_json()["items"]), 9)
        self.assertEqual(self.req("GET", "/api/v1/files?limit=abc&offset=-5").status_code, 200)

    def test_categories_report_availability(self):
        shutil.rmtree(self.lib / "Downloads")
        self.nx.scan_now()
        cats = {c["name"]: c for c in self.req("GET", "/api/v1/categories").get_json()["categories"]}
        self.assertTrue(cats["Movies"]["available"])
        self.assertFalse(cats["Downloads"]["available"])
        self.assertIn("not found", cats["Downloads"]["message"])
        self.assertEqual(cats["Movies"]["file_count"], 2)
        self.assertFalse(cats["Downloads"]["upload_allowed"])

    def test_path_traversal_ids_rejected(self):
        for bad in ("..%2f..%2fetc%2fpasswd", "../../etc/passwd", "%2e%2e", "0" * 23, "g" * 24, "A" * 24, "0" * 24, "a%00b"):
            for suffix in ("", "/stream", "/download", "/thumbnail"):
                r = self.req("GET", "/api/v1/files/" + bad + suffix)
                self.assertIn(r.status_code, (404, 308, 400), (bad, suffix, r.status_code))
                if r.status_code == 404:
                    self.assertEqual(r.headers["Content-Type"], "application/json")

    def test_absolute_paths_cannot_be_requested(self):
        outside = self.tmp / "secret.txt"
        outside.write_text("TOP SECRET")
        for p in (str(outside), "file://" + str(outside)):
            r = self.req("GET", "/api/v1/files/" + p.replace("/", "%2F") + "/stream")
            self.assertIn(r.status_code, (404, 400))
            self.assertNotIn(b"TOP SECRET", r.data)

    def test_symlink_escape_not_indexed_and_not_served(self):
        outside = self.tmp / "secret.txt"
        outside.write_text("TOP SECRET")
        outdir = self.tmp / "outdir"
        outdir.mkdir()
        (outdir / "leak.mp4").write_bytes(MP4)
        os.symlink(outside, self.lib / "Documents" / "link.txt")
        os.symlink(outdir, self.lib / "Movies" / "linkdir")
        self.nx.scan_now()
        names = {i["name"] for i in self.files(limit=200)}
        self.assertNotIn("link.txt", names)
        self.assertNotIn("leak.mp4", names)

    def test_symlink_swapped_in_after_indexing_is_blocked(self):
        fid = self.fid("note.txt")
        self.assertEqual(self.req("GET", "/api/v1/files/%s/stream" % fid).get_data(), b"hello nexora")
        outside = self.tmp / "secret.txt"
        outside.write_text("TOP SECRET")
        target = self.lib / "Documents" / "note.txt"
        target.unlink()
        os.symlink(outside, target)  # no rescan: the DB still lists it
        r = self.req("GET", "/api/v1/files/%s/stream" % fid)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"TOP SECRET", r.data)
        self.assertEqual(self.req("GET", "/api/v1/files/%s/download" % fid).status_code, 404)

    def test_symlink_inside_root_is_allowed(self):
        os.symlink(self.lib / "Documents" / "note.txt", self.lib / "Documents" / "alias.txt")
        self.nx.scan_now()
        fid = self.fid("alias.txt")
        self.assertEqual(self.req("GET", "/api/v1/files/%s/stream" % fid).get_data(), b"hello nexora")

    def test_deleted_file_returns_404_and_rescan_removes_it(self):
        fid = self.fid("pic.png")
        (self.lib / "Photos" / "pic.png").unlink()
        self.assertEqual(self.req("GET", "/api/v1/files/%s/stream" % fid).status_code, 404)
        self.nx.scan_now()
        self.assertNotIn("pic.png", {i["name"] for i in self.files(limit=200)})

    def test_private_files_not_indexed(self):
        names = " ".join(i["name"] for i in self.files(limit=200))
        for secret in ("config.json", "nexora.db", "nexora.log", ".part"):
            self.assertNotIn(secret, names)

    def test_original_files_cannot_be_modified_via_api(self):
        fid = self.fid("clip.mp4")
        for method in ("DELETE", "PUT", "PATCH", "POST"):
            r = self.req(method, "/api/v1/files/" + fid, json={})
            self.assertIn(r.status_code, (404, 405))
        self.assertTrue((self.lib / "Movies" / "clip.mp4").exists())

    def test_rescan_rate_limited_and_async(self):
        r = self.req("POST", "/api/v1/library/rescan")
        self.assertIn(r.status_code, (200, 202))
        self.cfg.rates["rescan_per_minute"] = 1
        codes = [self.req("POST", "/api/v1/library/rescan").status_code for _ in range(3)]
        self.assertIn(429, codes)


class TestStreaming(Base):
    def setUp(self):
        super().setUp()
        self.authed()
        self.big = MP4
        self.fid_ = self.fid("clip.mp4")
        self.url = "/api/v1/files/%s/stream" % self.fid_

    def test_full_response(self):
        r = self.req("GET", self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, MP4)
        self.assertEqual(r.headers["Content-Type"], "video/mp4")
        self.assertEqual(r.headers["Accept-Ranges"], "bytes")
        self.assertEqual(int(r.headers["Content-Length"]), len(MP4))
        self.assertTrue(r.headers["Content-Disposition"].startswith("inline"))
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn(ORIGIN, r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Access-Control-Expose-Headers"].count("Content-Range"), 1)

    def test_valid_ranges(self):
        r = self.req("GET", self.url, headers={"Range": "bytes=0-9"})
        self.assertEqual((r.status_code, r.data), (206, MP4[:10]))
        self.assertEqual(r.headers["Content-Range"], "bytes 0-9/%d" % len(MP4))
        self.assertEqual(r.headers["Content-Length"], "10")
        r = self.req("GET", self.url, headers={"Range": "bytes=100-199"})
        self.assertEqual((r.status_code, r.data), (206, MP4[100:200]))
        r = self.req("GET", self.url, headers={"Range": "bytes=%d-" % (len(MP4) - 5)})
        self.assertEqual((r.status_code, r.data), (206, MP4[-5:]))
        r = self.req("GET", self.url, headers={"Range": "bytes=-7"})
        self.assertEqual((r.status_code, r.data), (206, MP4[-7:]))
        r = self.req("GET", self.url, headers={"Range": "bytes=5-999999999"})
        self.assertEqual((r.status_code, r.data), (206, MP4[5:]))

    def test_invalid_and_unsatisfiable_ranges(self):
        r = self.req("GET", self.url, headers={"Range": "bytes=%d-" % len(MP4)})
        self.assertEqual(r.status_code, 416)
        self.assertEqual(r.headers["Content-Range"], "bytes */%d" % len(MP4))
        self.assertEqual(r.get_json()["error"]["code"], "range_not_satisfiable")
        self.assertEqual(self.req("GET", self.url, headers={"Range": "bytes=-0"}).status_code, 416)
        for h in ("bytes=abc", "bytes=9-3", "garbage", "bytes=0-1,5-6", "items=0-5"):
            r = self.req("GET", self.url, headers={"Range": h})
            self.assertEqual((r.status_code, r.data), (200, MP4), h)

    def test_if_range_mismatch_returns_full(self):
        r = self.req("GET", self.url, headers={"Range": "bytes=0-9", "If-Range": '"nope"'})
        self.assertEqual((r.status_code, len(r.data)), (200, len(MP4)))
        etag = self.req("GET", self.url).headers["ETag"]
        r = self.req("GET", self.url, headers={"Range": "bytes=0-9", "If-Range": etag})
        self.assertEqual(r.status_code, 206)

    def test_head(self):
        r = self.req("HEAD", self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(int(r.headers["Content-Length"]), len(MP4))
        self.assertEqual(r.data, b"")
        self.assertEqual(self.app.extensions["nexora"].cfg.max_streams, self.cfg.max_streams)

    def test_stream_slot_released_after_head_and_full_reads(self):
        for _ in range(self.cfg.max_streams * 3):
            self.assertEqual(self.req("HEAD", self.url).status_code, 200)
            self.assertEqual(self.req("GET", self.url, headers={"Range": "bytes=0-1"}).status_code, 206)

    def test_download_headers(self):
        r = self.req("GET", "/api/v1/files/%s/download" % self.fid_)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment; filename=\"clip.mp4\""))
        self.assertEqual(r.headers["Content-Type"], "application/octet-stream")
        self.assertEqual(r.data, MP4)
        self.assertIn("no-store", r.headers["Cache-Control"])
        events = self.req("GET", "/api/v1/activity").get_json()["events"]
        self.assertIn("download_requested", [e["event"] for e in events])

    def test_dangerous_types_never_served_inline(self):
        fid = self.fid("page.html")
        r = self.req("GET", "/api/v1/files/%s/stream" % fid)
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment"))
        self.assertEqual(r.headers["Content-Type"], "application/octet-stream")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        fid = self.fid("report.docx")
        self.assertTrue(self.req("GET", "/api/v1/files/%s/stream" % fid).headers["Content-Disposition"].startswith("attachment"))
        fid = self.fid("note.txt")
        r = self.req("GET", "/api/v1/files/%s/stream" % fid)
        self.assertTrue(r.headers["Content-Type"].startswith("text/plain"))

    def test_pdf_inline(self):
        r = self.req("GET", "/api/v1/files/%s/stream" % self.fid("doc.pdf"))
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertTrue(r.headers["Content-Disposition"].startswith("inline"))

    def test_concurrent_stream_limit_returns_503(self):
        sem = None
        # exhaust the semaphore by opening iterators without consuming them
        iters = []
        for _ in range(self.cfg.max_streams):
            r = self.c.open(self.url, base_url=BASE, headers={"Origin": ORIGIN}, buffered=False)
            self.assertEqual(r.status_code, 200)
            iters.append(r)
        r = self.req("GET", self.url)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (503, "busy"))
        self.assertIn("Retry-After", r.headers)
        for it in iters:
            it.close()
        self.assertEqual(self.req("GET", self.url).status_code, 200)

    def test_thumbnail_for_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        img = Image.new("RGB", (800, 600), (10, 120, 200))
        img.save(self.lib / "Photos" / "real.png")
        self.nx.scan_now()
        r = self.req("GET", "/api/v1/files/%s/thumbnail" % self.fid("real.png"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        with Image.open(__import__("io").BytesIO(r.data)) as t:
            self.assertLessEqual(max(t.size), 360)
        self.assertEqual(self.req("GET", "/api/v1/files/%s/thumbnail" % self.fid("clip.mp4")).status_code, 404)

    def test_album_art_thumbnail(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        Image.new("RGB", (100, 100), (200, 20, 20)).save(self.lib / "Music" / "cover.jpg")
        self.nx.scan_now()
        item = next(i for i in self.files(kind="audio") if i["name"] == "song.mp3")
        self.assertTrue(item["thumbnail"])
        self.assertEqual(self.req("GET", "/api/v1/files/%s/thumbnail" % item["id"]).status_code, 200)


class TestPreferences(Base):
    def setUp(self):
        super().setUp()
        self.authed()

    def test_favorites_roundtrip(self):
        fid = self.fid("clip.mp4")
        self.assertEqual(self.req("GET", "/api/v1/favorites").get_json()["items"], [])
        self.assertEqual(self.req("POST", "/api/v1/favorites", json={"file_id": fid}).status_code, 200)
        self.assertEqual(self.req("POST", "/api/v1/favorites", json={"file_id": fid}).status_code, 200)  # idempotent
        items = self.req("GET", "/api/v1/favorites").get_json()["items"]
        self.assertEqual([i["id"] for i in items], [fid])
        self.assertTrue(items[0]["favorite"])
        self.assertEqual(self.req("GET", "/api/v1/favorites?sort=name&order=desc").status_code, 200)
        self.assertEqual(self.req("POST", "/api/v1/favorites", json={"file_id": "f" * 24}).status_code, 404)
        self.assertEqual(self.req("POST", "/api/v1/favorites", json={"file_id": 5}).status_code, 400)
        self.assertEqual(self.req("DELETE", "/api/v1/favorites/" + fid).status_code, 200)
        self.assertEqual(self.req("GET", "/api/v1/favorites").get_json()["items"], [])
        self.assertEqual(self.req("DELETE", "/api/v1/favorites/not-an-id").status_code, 404)

    def test_watchlist_roundtrip(self):
        fid = self.fid("ep1.mp4")
        self.req("POST", "/api/v1/watchlist", json={"file_id": fid})
        self.assertEqual([i["id"] for i in self.req("GET", "/api/v1/watchlist").get_json()["items"]], [fid])
        self.assertTrue(self.files(category="Movies")[0]["watchlist"] or self.files(category="Movies")[1]["watchlist"])
        self.req("DELETE", "/api/v1/watchlist/" + fid)
        self.assertEqual(self.req("GET", "/api/v1/watchlist").get_json()["items"], [])

    def test_playback_progress_continue_and_recent(self):
        fid = self.fid("clip.mp4")
        r = self.req("POST", "/api/v1/playback/progress", json={"file_id": fid, "position": 42.5, "duration": 600})
        self.assertEqual(r.status_code, 200)
        dash = self.req("GET", "/api/v1/dashboard").get_json()
        self.assertEqual([i["id"] for i in dash["continue_watching"]], [fid])
        it = dash["continue_watching"][0]
        self.assertEqual((it["progress"]["position"], it["duration"]), (42.5, 600))
        self.assertEqual([i["id"] for i in dash["recently_played"]], [fid])
        self.assertEqual([i["id"] for i in self.req("GET", "/api/v1/recent").get_json()["items"]], [fid])
        self.req("POST", "/api/v1/playback/progress", json={"file_id": fid, "position": 590, "duration": 600})  # >95% -> completed
        dash = self.req("GET", "/api/v1/dashboard").get_json()
        self.assertEqual(dash["continue_watching"], [])
        events = [e["event"] for e in self.req("GET", "/api/v1/activity").get_json()["events"]]
        self.assertEqual(events.count("file_played"), 1)  # not logged on every progress tick

    def test_playback_validation(self):
        fid = self.fid("clip.mp4")
        for body in ({"file_id": fid}, {"file_id": fid, "position": -1}, {"file_id": fid, "position": "x"}, {"file_id": fid, "position": True},
                     {"file_id": fid, "position": 1, "duration": 0}, {"file_id": fid, "position": 1e12}, {"position": 1}):
            self.assertEqual(self.req("POST", "/api/v1/playback/progress", json=body).status_code, 400, body)
        self.assertEqual(self.req("POST", "/api/v1/playback/progress", json={"file_id": "e" * 24, "position": 1}).status_code, 404)
        img = self.fid("pic.png")
        self.assertEqual(self.req("POST", "/api/v1/playback/progress", json={"file_id": img, "position": 1}).status_code, 400)

    def test_playlists(self):
        r = self.req("POST", "/api/v1/playlists", json={"name": "Road trip"})
        self.assertEqual(r.status_code, 201)
        pid = r.get_json()["id"]
        s1, s2 = self.fid("song.mp3"), self.fid("song2.mp3")
        for f in (s1, s2, s1):
            self.assertEqual(self.req("POST", "/api/v1/playlists/%s/items" % pid, json={"file_id": f}).status_code, 200)
        self.assertEqual(self.req("POST", "/api/v1/playlists/%s/items" % pid, json={"file_id": self.fid("clip.mp4")}).status_code, 400)
        pl = self.req("GET", "/api/v1/playlists/" + pid).get_json()
        self.assertEqual([i["id"] for i in pl["items"]], [s1, s2])
        self.assertEqual(self.req("GET", "/api/v1/playlists").get_json()["playlists"][0]["track_count"], 2)
        self.assertEqual(self.req("DELETE", "/api/v1/playlists/%s/items/%s" % (pid, s1)).status_code, 200)
        self.assertEqual(len(self.req("GET", "/api/v1/playlists/" + pid).get_json()["items"]), 1)
        for bad in ({"name": ""}, {"name": "x" * 81}, {"name": 5}, {}):
            self.assertEqual(self.req("POST", "/api/v1/playlists", json=bad).status_code, 400)
        self.assertEqual(self.req("DELETE", "/api/v1/playlists/" + pid).status_code, 200)
        self.assertEqual(self.req("GET", "/api/v1/playlists/" + pid).status_code, 404)
        self.assertTrue((self.lib / "Music" / "song.mp3").exists())  # media untouched

    def test_dashboard_counts(self):
        d = self.req("GET", "/api/v1/dashboard").get_json()
        self.assertEqual(d["counts"], {"total": 9, "videos": 2, "music": 2, "photos": 1, "documents": 3})
        self.assertGreater(d["storage"]["library"]["size_bytes"], 0)

    def test_device_status_honest(self):
        d = self.req("GET", "/api/v1/device/status").get_json()
        self.assertEqual(d["server"]["version"], ns.VERSION)
        self.assertGreaterEqual(d["server"]["uptime_seconds"], 0)
        self.assertEqual(d["health"]["database"], "ok")
        self.assertIn("available", d["battery"])
        if not d["battery"]["available"]:
            self.assertEqual(d["battery"]["reason"], "Unavailable on this device")
            self.assertNotIn("percent", d["battery"])
        else:
            self.assertTrue(0 <= d["battery"]["percent"] <= 100)
        vol = next(iter(d["storage"]["volumes"].values()))
        self.assertGreater(vol["total_bytes"], 0)
        self.assertEqual(vol["used_bytes"] + vol["free_bytes"] <= vol["total_bytes"] + 4096 * 1024 * 1024, True)
        self.assertIn("system", d["memory"])
        self.assertIn("process", d["memory"])
        self.assertFalse(d["health"]["tunnel"]["known"])
        self.assertFalse(d["server"]["via_cloudflare"])
        r = self.req("GET", "/api/v1/device/status", headers={"CF-Ray": "abc"})
        self.assertTrue(r.get_json()["server"]["via_cloudflare"])

    def test_telemetry_can_be_disabled(self):
        self.cfg.telemetry_enabled = False
        d = self.req("GET", "/api/v1/device/status").get_json()
        self.assertNotIn("battery", d)

    def test_activity_log_has_no_secrets(self):
        self.login(password="wrong")
        txt = self.req("GET", "/api/v1/activity").get_data(as_text=True)
        self.assertIn("login_success", txt)
        self.assertIn("login_failed", txt)
        self.assertNotIn("wrong", txt)
        self.assertNotIn(PASSWORD, txt)


class TestUploads(Base):
    def setUp(self):
        super().setUp()
        self.authed()

    def upload(self, name, content, category="Uploads", **kw):
        import io
        return self.req("POST", "/api/v1/uploads", data={"category": category, "file": (io.BytesIO(content), name)}, content_type="multipart/form-data", **kw)

    def quarantine_files(self):
        return [p for p in self.cfg.quarantine_dir.iterdir() if p.is_file()]

    def test_successful_upload_indexed_and_private_quarantine_cleaned(self):
        r = self.upload("holiday.png", PNG, "Photos")
        self.assertEqual(r.status_code, 201, r.data)
        body = r.get_json()
        self.assertEqual((body["status"], body["name"], body["category"], body["scanned_for_malware"]), ("completed", "holiday.png", "Photos", False))
        self.assertEqual((self.lib / "Photos" / "holiday.png").read_bytes(), PNG)
        self.assertEqual(self.quarantine_files(), [])
        self.assertIn("holiday.png", {i["name"] for i in self.files(limit=200)})
        st = self.req("GET", "/api/v1/uploads/" + body["id"]).get_json()
        self.assertEqual((st["status"], st["file_id"]), ("completed", body["file_id"]))
        self.assertEqual(self.req("GET", "/api/v1/files/%s/stream" % body["file_id"]).data, PNG)

    def test_never_overwrites_existing_files(self):
        original = (self.lib / "Photos" / "pic.png").read_bytes()
        r = self.upload("pic.png", PNG + b"DIFFERENT", "Photos")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["name"], "pic (1).png")
        self.assertTrue(r.get_json()["renamed"])
        self.assertEqual((self.lib / "Photos" / "pic.png").read_bytes(), original)
        r = self.upload("pic.png", PNG + b"AGAIN", "Photos")
        self.assertEqual(r.get_json()["name"], "pic (2).png")
        self.assertEqual((self.lib / "Photos" / "pic.png").read_bytes(), original)

    def test_traversal_filenames_are_flattened(self):
        r = self.upload("../../evil.png", PNG)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["name"], "evil.png")
        self.assertTrue((self.lib / "Uploads" / "evil.png").exists())
        self.assertFalse((self.tmp / "evil.png").exists())
        self.assertFalse((self.lib / "evil.png").exists())
        r = self.upload("..\\..\\win.png", PNG)
        self.assertEqual(r.get_json()["name"], "win.png")
        r = self.upload("/etc/cron.png", PNG)
        self.assertEqual(r.get_json()["name"], "cron.png")

    def test_dangerous_types_rejected(self):
        for name in ("run.py", "x.sh", "app.apk", "index.html", "a.php", "evil.php.jpg", "x.exe", "pic.svg", "x.js", "tool.jar", "noextension", ".bashrc", "x.PY"):
            r = self.upload(name, b"print('x')")
            self.assertEqual(r.status_code, 400, name)
        self.assertEqual(list((self.lib / "Uploads").iterdir()), [])

    def test_content_must_match_extension_and_no_executables(self):
        self.assertEqual(self.upload("fake.png", b"just text here").status_code, 400)
        self.assertEqual(self.upload("fake.mp3", b"MZ\x90\x00" + b"\x00" * 100).status_code, 400)
        self.assertEqual(self.upload("script.txt", b"#!/bin/sh\necho hi").status_code, 400)
        self.assertEqual(self.upload("page.txt", b"<html><body>hi</body></html>").status_code, 400)
        self.assertEqual(self.upload("empty.png", b"").status_code, 400)
        self.assertEqual(self.upload("note.txt", b"plain notes").status_code, 201)
        self.assertEqual(self.quarantine_files(), [])

    def test_extension_must_fit_destination(self):
        r = self.upload("movie.mp4", MP4, "Photos")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "type_not_allowed"))
        self.assertEqual(self.upload("movie.mp4", MP4, "Movies").status_code, 201)

    def test_destination_allowlist(self):
        for cat in ("Downloads", "../../tmp", "/etc", "Config", "", "Thumbnails", "movies"):
            r = self.upload("a.png", PNG, cat)
            self.assertEqual(r.status_code, 400, cat)
            self.assertEqual(r.get_json()["error"]["code"], "invalid_category")
        self.assertEqual(list((self.lib / "Downloads").iterdir()), [])

    def test_size_limit_enforced(self):
        self.cfg.max_upload_bytes = 5000
        self.app.config["MAX_CONTENT_LENGTH"] = 5000 + 2 * 1024 * 1024
        big = PNG + b"\x00" * 6000
        r = self.upload("big.png", big)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (413, "file_too_large"))
        self.assertFalse((self.lib / "Uploads" / "big.png").exists())
        self.assertEqual(self.quarantine_files(), [])

    def test_request_body_cap_413(self):
        self.cfg.max_upload_bytes = 1000
        r = self.req("POST", "/api/v1/uploads", data=b"x" * (3 * 1024 * 1024 + 10), content_type="multipart/form-data; boundary=zzz")
        self.assertEqual(r.status_code, 413)

    def test_uploads_can_be_disabled(self):
        self.cfg.uploads_enabled = False
        r = self.upload("a.png", PNG)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "uploads_disabled"))
        cats = {c["name"]: c for c in self.req("GET", "/api/v1/categories").get_json()["categories"]}
        self.assertFalse(cats["Uploads"]["upload_allowed"])

    def test_missing_file_part_and_unauth(self):
        r = self.req("POST", "/api/v1/uploads", data={"category": "Uploads"}, content_type="multipart/form-data")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "no_file"))
        self.req("POST", "/api/v1/auth/logout")
        self.assertEqual(self.upload("a.png", PNG).status_code, 401)
        self.assertEqual(self.upload("a.png", PNG, csrf=False).status_code, 403)  # CSRF is checked before auth

    def test_csrf_on_upload(self):
        r = self.upload("a.png", PNG, csrf=False)
        self.assertEqual(r.status_code, 403)
        r = self.upload("a.png", PNG, origin="https://evil.example")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(list((self.lib / "Uploads").iterdir()), [])

    def test_insufficient_space(self):
        self.cfg.min_free_bytes = 10 ** 18
        r = self.upload("a.png", PNG)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (507, "insufficient_storage"))
        self.assertEqual(self.quarantine_files(), [])

    def test_rejected_upload_status_endpoint(self):
        r = self.upload("run.py", b"x")
        uid = r.get_json()["error"]["upload_id"]
        st = self.req("GET", "/api/v1/uploads/" + uid).get_json()
        self.assertEqual(st["status"], "rejected")
        self.assertEqual(self.req("GET", "/api/v1/uploads/nothex").status_code, 404)

    def test_abandoned_partials_cleaned_by_maintenance(self):
        old = self.cfg.quarantine_dir / "deadbeef.part"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        fresh = self.cfg.quarantine_dir / "fresh.part"
        fresh.write_bytes(b"x")
        spool = self.cfg.quarantine_dir / "tmp" / "tmpabc"
        spool.write_bytes(b"x")
        os.utime(spool, (time.time() - 7200, time.time() - 7200))
        self.nx.maintenance_once()
        self.assertFalse(old.exists())
        self.assertFalse(spool.exists())
        self.assertTrue(fresh.exists())

    def test_extra_extension_config(self):
        self.cfg.extra_upload_extensions = {"zip"}
        self.assertEqual(self.upload("a.zip", b"PK\x03\x04" + b"\x00" * 50).status_code, 201)
        self.assertEqual(self.upload("b.zip", b"not a zip").status_code, 400)


class TestShares(Base):
    def setUp(self):
        super().setUp()
        self.authed()
        self.fid_ = self.fid("clip.mp4")
        self.anon = self.app.test_client()

    def create(self, fid=None, duration="1h", mode="view"):
        r = self.req("POST", "/api/v1/shares", json={"file_id": fid or self.fid_, "duration": duration, "mode": mode})
        return r

    def token_of(self, r):
        return r.get_json()["url"].rsplit("/", 1)[1]

    def public(self, token, **kw):
        return self.anon.get("/api/v1/s/" + token, base_url=BASE, **kw)

    def test_create_view_and_access_without_session(self):
        r = self.create()
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        tok = self.token_of(r)
        self.assertGreaterEqual(len(tok), 43)
        self.assertTrue(body["url"].startswith("https://nexora.test/api/v1/s/"))
        self.assertAlmostEqual(body["expires_at"], time.time() + 3600, delta=5)
        self.assertIn("screenshot", body["notice"])
        pub = self.public(tok)
        self.assertEqual((pub.status_code, pub.data), (200, MP4))
        self.assertEqual(pub.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(pub.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("no-store", pub.headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", pub.headers["Content-Security-Policy"])
        self.assertEqual(self.public(tok, headers={"Range": "bytes=2-5"}).status_code, 206)

    def test_token_only_stored_hashed_and_never_listed(self):
        tok = self.token_of(self.create())
        conn = self.db()
        dump = "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM shares"))
        dump += "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM activity"))
        self.assertNotIn(tok, dump)
        self.assertNotIn(tok, self.req("GET", "/api/v1/shares").get_data(as_text=True))
        self.assertNotIn(tok, self.cfg.logs_dir.joinpath("nexora.log").read_text() if (self.cfg.logs_dir / "nexora.log").exists() else "")
        conn.close()

    def test_all_durations_and_validation(self):
        for d, mins in (("15m", 15), ("1h", 60), ("6h", 360), ("24h", 1440)):
            r = self.create(duration=d)
            self.assertAlmostEqual(r.get_json()["expires_at"], time.time() + mins * 60, delta=5)
        for bad in ("5m", "forever", "", None, 3600):
            r = self.req("POST", "/api/v1/shares", json={"file_id": self.fid_, "duration": bad, "mode": "view"})
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "invalid_duration"))
        r = self.req("POST", "/api/v1/shares", json={"file_id": self.fid_, "duration": "1h", "mode": "edit"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.create(fid="9" * 24).status_code, 404)
        self.assertEqual(self.req("POST", "/api/v1/shares", json={"duration": "1h"}).status_code, 400)

    def test_expiry_enforced_server_side(self):
        r = self.create(duration="15m")
        tok = self.token_of(r)
        self.assertEqual(self.public(tok).status_code, 200)
        conn = self.db()
        conn.execute("UPDATE shares SET expires_at=?", (int(time.time()) - 1,))
        conn.commit()
        conn.close()
        pub = self.public(tok)
        self.assertEqual((pub.status_code, pub.get_json()["error"]["code"]), (404, "share_unavailable"))
        listing = self.req("GET", "/api/v1/shares").get_json()["shares"]
        self.assertEqual(listing[0]["status"], "expired")

    def test_revocation_immediate(self):
        r = self.create()
        tok, sid = self.token_of(r), r.get_json()["id"]
        self.assertEqual(self.public(tok).status_code, 200)
        self.assertEqual(self.req("DELETE", "/api/v1/shares/" + sid).status_code, 200)
        self.assertEqual(self.public(tok).status_code, 404)
        self.assertEqual(self.req("GET", "/api/v1/shares").get_json()["shares"][0]["status"], "revoked")
        self.assertEqual(self.req("DELETE", "/api/v1/shares/" + sid).status_code, 200)  # idempotent
        self.assertEqual(self.req("DELETE", "/api/v1/shares/" + "f" * 16).status_code, 404)
        events = [e["event"] for e in self.req("GET", "/api/v1/activity").get_json()["events"]]
        self.assertEqual((events.count("share_created"), events.count("share_revoked")), (1, 1))

    def test_view_only_blocks_download_and_download_mode_allows(self):
        tok = self.token_of(self.create(mode="view"))
        r = self.public(tok + "?download=1".replace("?", "")) if False else self.anon.get("/api/v1/s/%s?download=1" % tok, base_url=BASE)
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (403, "download_not_allowed"))
        tok2 = self.token_of(self.create(mode="download"))
        r = self.anon.get("/api/v1/s/%s?download=1" % tok2, base_url=BASE)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment"))
        r = self.public(tok2)
        self.assertTrue(r.headers["Content-Disposition"].startswith("inline"))

    def test_view_mode_refused_for_non_viewable_format(self):
        docx = self.fid("report.docx")
        r = self.create(fid=docx, mode="view")
        self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (400, "view_not_supported"))
        r = self.create(fid=docx, mode="download")
        self.assertEqual(r.status_code, 201)
        pub = self.public(self.token_of(r))
        self.assertTrue(pub.headers["Content-Disposition"].startswith("attachment"))

    def test_token_scoped_to_one_file_and_not_a_session(self):
        tok = self.token_of(self.create())
        pub = self.public(tok)
        self.assertEqual(pub.data, MP4)
        for path in ("/api/v1/files", "/api/v1/dashboard", "/api/v1/shares", "/api/v1/files/%s/stream" % self.fid("note.txt")):
            self.assertEqual(self.anon.get(path + "?token=" + tok, base_url=BASE).status_code, 401)
            self.assertEqual(self.anon.get(path, base_url=BASE, headers={"Authorization": "Bearer " + tok}).status_code, 401)
        self.assertEqual(self.public(tok + "/../files").status_code, 404)

    def test_invalid_tokens_uniform_response(self):
        outcomes = set()
        for tok in ("x" * 43, "short", "%00" * 20, "A" * 100, "a-b_c" * 10):
            r = self.public(tok)
            outcomes.add((r.status_code, r.get_json()["error"]["code"]))
        self.assertEqual(outcomes, {(404, "share_unavailable")})
        for odd in ("../../etc/passwd", "a/b"):  # contains slashes: never matches the share route at all
            self.assertEqual(self.public(odd).status_code, 404)

    def test_share_access_rate_limited(self):
        self.cfg.rates["share_access_per_minute"] = 5
        codes = [self.public("x" * 43).status_code for _ in range(8)]
        self.assertIn(429, codes)

    def test_share_dies_when_file_removed(self):
        tok = self.token_of(self.create())
        (self.lib / "Movies" / "clip.mp4").unlink()
        self.assertEqual(self.public(tok).status_code, 404)

    def test_access_count(self):
        tok = self.token_of(self.create())
        self.public(tok)
        self.public(tok, headers={"Range": "bytes=100-200"})  # later ranges are not new views
        self.assertEqual(self.req("GET", "/api/v1/shares").get_json()["shares"][0]["access_count"], 1)

    def test_share_create_requires_csrf_and_auth(self):
        self.assertEqual(self.req("POST", "/api/v1/shares", json={"file_id": self.fid_, "duration": "1h"}, csrf=False).status_code, 403)
        self.req("POST", "/api/v1/auth/logout")
        self.assertEqual(self.create().status_code, 401)


class TestCLIAndRealServer(unittest.TestCase):
    """Starts the real script in a subprocess (separate private config) and talks HTTP to it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nexora-cli-"))
        self.env = dict(os.environ, NEXORA_PRIVATE_DIR=str(self.tmp / "priv"), NEXORA_LIBRARY_ROOT=str(self.tmp / "lib" / "NEXORA"), NEXORA_TEST_PW=PASSWORD)
        self.env.pop("NEXORA_CONFIG", None)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.script = str(HERE.parent / "nexora_server.py")
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args):
        return subprocess.run([sys.executable, self.script, *args], env=self.env, capture_output=True, text=True, timeout=60)

    def init(self):
        r = self.cli("init", "--origin", "http://localhost:8000", "--port", str(self.port), "--password-env", "NEXORA_TEST_PW")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def start(self):
        self.proc = subprocess.Popen([sys.executable, self.script, "run"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/v1/health" % self.port, timeout=1) as resp:
                    return json.load(resp)
            except Exception:  # noqa: BLE001
                if self.proc.poll() is not None:
                    self.fail("server exited early: " + self.proc.stdout.read())
                time.sleep(0.1)
        self.fail("server did not start")

    def http(self, method, path, *, data=None, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_init_creates_private_config_without_plaintext_password(self):
        r = self.init()
        cfg_file = self.tmp / "priv" / "Config" / "config.json"
        text = cfg_file.read_text()
        self.assertNotIn(PASSWORD, text)
        raw = json.loads(text)
        self.assertTrue(raw["password_hash"].startswith(("scrypt$", "pbkdf2_sha256$")))
        self.assertGreaterEqual(len(raw["session_secret"]), 64)
        self.assertEqual(raw["bind_host"], "127.0.0.1")
        self.assertEqual(oct(cfg_file.stat().st_mode & 0o777), "0o600")
        self.assertNotIn(PASSWORD, r.stdout)
        self.assertNotIn(raw["password_hash"], r.stdout)
        self.assertNotIn(raw["session_secret"], r.stdout)
        for sub in ("Movies", "Music", "Photos", "Documents", "Uploads", "Downloads"):
            self.assertTrue((self.tmp / "lib" / "NEXORA" / sub).is_dir())
        self.assertFalse((self.tmp / "priv").resolve() in (self.tmp / "lib").resolve().parents)
        self.assertEqual(self.init.__name__, "init")
        again = self.cli("init", "--origin", "http://localhost:8000", "--password-env", "NEXORA_TEST_PW")
        self.assertEqual(again.returncode, 1)  # will not silently replace an existing config
        self.assertEqual(self.cli("check").returncode, 0)

    def test_check_fails_without_config_and_with_bad_config(self):
        r = self.cli("check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("init", r.stdout)
        self.init()
        cfg_file = self.tmp / "priv" / "Config" / "config.json"
        raw = json.loads(cfg_file.read_text())
        raw["session_secret"] = "short"
        cfg_file.write_text(json.dumps(raw))
        r = self.cli("check")
        self.assertEqual(r.returncode, 2)
        self.assertIn("session_secret", r.stdout)
        cfg_file.write_text("{not json")
        self.assertNotEqual(self.cli("check").returncode, 0)

    def test_server_start_login_shutdown_restart(self):
        self.init()
        health = self.start()
        self.assertEqual(health["service"], "nexora")
        status, headers, body = self.http("GET", "/api/v1/files")
        self.assertEqual(status, 401)
        status, _h, _b = self.http("POST", "/api/v1/auth/login", data=json.dumps({"password": PASSWORD}).encode(),
                                   headers={"Content-Type": "application/json", "Origin": "http://localhost:8000", "X-NEXORA-CSRF": "1"})
        self.assertEqual(status, 200)
        # SIGTERM -> graceful stop, exit code 0, port released
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(timeout=15), 0)
        out = self.proc.stdout.read()
        self.assertIn("NEXORA stopped", out)
        for secret in (PASSWORD, json.loads((self.tmp / "priv" / "Config" / "config.json").read_text())["password_hash"]):
            self.assertNotIn(secret, out)
        with self.assertRaises(Exception):
            urllib.request.urlopen("http://127.0.0.1:%d/api/v1/health" % self.port, timeout=1)
        # restart: sessions persist in the DB only until expiry; server comes back healthy
        health = self.start()
        self.assertEqual(health["status"], "ok")
        self.proc.send_signal(signal.SIGINT)
        self.assertEqual(self.proc.wait(timeout=15), 0)

    def test_binds_localhost_only(self):
        self.init()
        self.start()
        rows = []
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                rows += open(table).read().splitlines()[1:]
            except OSError:
                pass
        listening = [r.split()[1] for r in rows if r.split()[3] == "0A" and int(r.split()[1].split(":")[1], 16) == self.port]
        self.assertTrue(listening, "no listening socket found for the server port")
        for addr in listening:
            self.assertIn(addr.split(":")[0], ("0100007F", "00000000000000000000000001000000"), "server is listening beyond loopback: " + addr)

    def test_large_file_seek_and_client_disconnect_releases_slots(self):
        self.init()
        cfg_file = self.tmp / "priv" / "Config" / "config.json"
        raw = json.loads(cfg_file.read_text())
        raw["max_concurrent_streams"] = 2
        cfg_file.write_text(json.dumps(raw))
        movies = self.tmp / "lib" / "NEXORA" / "Movies"
        big = movies / "big.mp4"
        with open(big, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")
            fh.seek(300 * 1024 * 1024)  # 300 MB sparse file
            fh.write(b"END-MARKER")
        self.start()
        origin = {"Origin": "http://localhost:8000", "X-NEXORA-CSRF": "1", "Content-Type": "application/json"}
        status, hdrs, _ = self.http("POST", "/api/v1/auth/login", data=json.dumps({"password": PASSWORD}).encode(), headers=origin)
        self.assertEqual(status, 200)
        cookie = hdrs["Set-Cookie"].split(";", 1)[0]
        h = {"Cookie": cookie, "Origin": "http://localhost:8000"}
        for _ in range(40):  # wait for the background scan
            status, _hh, body = self.http("GET", "/api/v1/files?q=big", headers=h)
            if json.loads(body)["total"]:
                break
            time.sleep(0.1)
        fid = json.loads(body)["items"][0]["id"]
        size = 300 * 1024 * 1024 + len(b"END-MARKER")
        # seek near the end of a 300 MB file: only the requested bytes are read
        t0 = time.time()
        status, hdrs, body = self.http("GET", "/api/v1/files/%s/stream" % fid, headers=dict(h, Range="bytes=%d-" % (size - 10)))
        self.assertEqual((status, body), (206, b"END-MARKER"))
        self.assertEqual(hdrs["Content-Range"], "bytes %d-%d/%d" % (size - 10, size - 1, size))
        self.assertLess(time.time() - t0, 3)
        # open and abandon streams more times than max_concurrent_streams
        for _ in range(6):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            s.sendall(("GET /api/v1/files/%s/stream HTTP/1.1\r\nHost: x\r\nCookie: %s\r\nRange: bytes=0-\r\n\r\n" % (fid, cookie)).encode())
            s.recv(4096)
            s.close()  # client disconnects mid-transfer
        time.sleep(1.0)
        status, _hh, body = self.http("GET", "/api/v1/files/%s/stream" % fid, headers=dict(h, Range="bytes=0-3"))
        self.assertEqual(status, 206, "slots leaked after client disconnects")
        self.assertEqual(body, b"\x00\x00\x00\x18")

    def test_set_password_invalidates_sessions(self):
        self.init()
        self.start()
        origin = {"Origin": "http://localhost:8000", "X-NEXORA-CSRF": "1", "Content-Type": "application/json"}
        status, hdrs, _ = self.http("POST", "/api/v1/auth/login", data=json.dumps({"password": PASSWORD}).encode(), headers=origin)
        cookie = hdrs["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.http("GET", "/api/v1/dashboard", headers={"Cookie": cookie})[0], 200)
        self.env["NEXORA_NEW_PW"] = "a brand new passphrase 99"
        r = self.cli("set-password", "--password-env", "NEXORA_NEW_PW", "--rotate-secret")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.http("GET", "/api/v1/dashboard", headers={"Cookie": cookie})[0], 401)
        self.proc.send_signal(signal.SIGTERM)
        self.proc.wait(timeout=15)
        self.start()
        bad = self.http("POST", "/api/v1/auth/login", data=json.dumps({"password": PASSWORD}).encode(), headers=origin)[0]
        good = self.http("POST", "/api/v1/auth/login", data=json.dumps({"password": "a brand new passphrase 99"}).encode(), headers=origin)[0]
        self.assertEqual((bad, good), (401, 200))


if __name__ == "__main__":
    unittest.main(verbosity=2)
