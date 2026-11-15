"""The web interface: a small JSON API plus one static page.

There is no login — it is meant for a trusted home network only. Changes are
only accepted as JSON requests, which other websites cannot send from a
visitor's browser without permission this server never grants.
"""

import json
import logging
import os
import re
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from azan import __version__, audio, cast, paths, system, tv_control
from azan.settings import SettingsError

log = logging.getLogger("azan")

MAX_JSON_BYTES = 64 * 1024


class ApiError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields


class App:
    """Everything the request handlers need."""

    def __init__(self, store, scheduler, player):
        self.store = store
        self.scheduler = scheduler
        self.player = player

    # Each handler returns a JSON-serialisable object.

    def status(self, _body, _query):
        s = self.store.get()
        data = self.scheduler.snapshot()
        data.update({
            "version": __version__,
            "masjid_name": s["masjid_name"],
            "device_name": s["device_name"],
            "player": self.player.status(),
            "tv_control": tv_control.configured(s),
        })
        return data

    def get_settings(self, _body, _query):
        s = self.store.get()
        s["ha_token_set"] = bool(s.pop("ha_token"))
        return s

    def save_settings(self, body, _query):
        body = dict(body)
        body.pop("ha_token_set", None)
        if body.get("ha_token") is None:
            body.pop("ha_token", None)  # omitted/null = keep the saved token
        try:
            self.store.update(body)
        except SettingsError as exc:
            raise ApiError("Some settings are not valid", fields=exc.errors)
        return self.get_settings(None, None)

    def devices(self, _body, _query):
        try:
            return {"devices": cast.scan()}
        except cast.CastError as exc:
            raise ApiError(str(exc), status=502)

    def check(self, _body, _query):
        if not self.store.get()["device_name"]:
            raise ApiError("Choose a speaker in Settings first")
        self.scheduler.check_speaker(allow_reboot=False)
        return {"device": self.scheduler.device_status}

    def play(self, body, _query):
        s = self.store.get()
        if not s["device_name"]:
            raise ApiError("Choose a speaker in Settings first")
        fajr = bool(body.get("fajr"))
        name = body.get("file") or (s["fajr_azan_file"] if fajr else s["azan_file"])
        try:
            if not os.path.isfile(audio.path_for(name)):
                raise audio.AudioError("Audio file not found")
        except audio.AudioError as exc:
            raise ApiError(str(exc))
        volume = body.get("volume")
        if volume is not None:
            if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
                raise ApiError("Volume must be a whole number from 0 to 100")
        if not self.player.play_async("Test", fajr=fajr, file=name, volume=volume):
            raise ApiError("Something is already playing", status=409)
        return {"started": True}

    def stop(self, _body, _query):
        return {"stopped": self.player.stop()}

    def refresh(self, _body, _query):
        ok = self.scheduler.refresh(force=True)
        if self.scheduler.fetch_error:
            raise ApiError(self.scheduler.fetch_error, status=502)
        return {"ok": ok}

    def audio_list(self, _body, _query):
        s = self.store.get()
        return {"files": audio.list_files(),
                "azan_file": s["azan_file"], "fajr_azan_file": s["fajr_azan_file"]}

    def audio_delete(self, _body, query):
        s = self.store.get()
        try:
            audio.delete(query.get("name", ""), in_use=(s["azan_file"], s["fajr_azan_file"]))
        except audio.AudioError as exc:
            raise ApiError(str(exc))
        log.info("Audio file deleted: %s", query.get("name"))
        return self.audio_list(None, None)

    def ha_players(self, body, _query):
        s = self.store.get()
        url = str(body.get("ha_url") or s["ha_url"]).strip()
        token = str(body.get("ha_token") or s["ha_token"]).strip()
        if not url.startswith(("http://", "https://")) or not token:
            raise ApiError("Enter the Home Assistant address and token first")
        try:
            return {"players": tv_control.media_players(url, token)}
        except RuntimeError as exc:
            raise ApiError(str(exc), status=502)

    def log_tail(self, _body, query):
        try:
            wanted = max(1, min(int(query.get("lines", 200)), 1000))
        except ValueError:
            wanted = 200
        try:
            with open(paths.LOG_FILE, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 200_000))
                lines = f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            lines = []
        return {"lines": lines[-wanted:]}

    def reboot(self, _body, _query):
        if not system.is_pi():
            raise ApiError("Restart is only available on the Raspberry Pi")
        log.warning("Restart requested from the web page.")
        import subprocess
        subprocess.Popen(["sudo", "-n", "reboot"])
        return {"rebooting": True}


ROUTES = {
    ("GET", "/api/status"): "status",
    ("GET", "/api/settings"): "get_settings",
    ("POST", "/api/settings"): "save_settings",
    ("GET", "/api/devices"): "devices",
    ("POST", "/api/check"): "check",
    ("POST", "/api/play"): "play",
    ("POST", "/api/stop"): "stop",
    ("POST", "/api/refresh"): "refresh",
    ("GET", "/api/audio"): "audio_list",
    ("DELETE", "/api/audio"): "audio_delete",
    ("POST", "/api/ha/players"): "ha_players",
    ("GET", "/api/log"): "log_tail",
    ("POST", "/api/reboot"): "reboot",
}


# Home-screen ("add to home screen") files served next to the page.
STATIC_FILES = {
    "/manifest.webmanifest": "application/manifest+json",
    "/apple-touch-icon.png": "image/png",
    "/apple-touch-icon-precomposed.png": "image/png",
    "/icon-192.png": "image/png",
    "/icon-512.png": "image/png",
}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Azan/" + __version__
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the log for azan events
            pass

        # ── plumbing ────────────────────────────────────────────────────

        def _send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, data, status=200):
            self._send(status, json.dumps(data).encode(), "application/json")

        def _error(self, message, status=400, fields=None):
            payload = {"error": message}
            if fields:
                payload["fields"] = fields
            self._json(payload, status)

        def _content_length(self):
            try:
                return max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                return 0

        def _read_json(self):
            if self.headers.get_content_type() != "application/json":
                raise ApiError("Expected application/json", status=415)
            length = self._content_length()
            if length > MAX_JSON_BYTES:
                raise ApiError("Request is too large", status=413)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise ApiError("Request is not valid JSON")
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object")
            return body

        def _dispatch(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            try:
                if self.command == "POST" and parsed.path == "/api/audio":
                    return self._upload(query)
                name = ROUTES.get((self.command, parsed.path))
                if name:
                    body = self._read_json() if self.command == "POST" else None
                    return self._json(getattr(app, name)(body, query))
                if self.command in ("GET", "HEAD"):
                    if parsed.path in ("/", "/index.html"):
                        return self._static("index.html", "text/html; charset=utf-8")
                    if parsed.path in STATIC_FILES:
                        return self._static(parsed.path[1:], STATIC_FILES[parsed.path])
                    if parsed.path.startswith("/audio/"):
                        return self._audio(urllib.parse.unquote(parsed.path[7:]))
                self.close_connection = True
                self._error("Not found", 404)
            except ApiError as exc:
                self.close_connection = True  # the request body may be unread
                self._error(str(exc), exc.status, exc.fields)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                log.exception("Web request failed: %s %s", self.command, parsed.path)
                self.close_connection = True
                self._error("Something went wrong — see the log", 500)

        do_GET = do_HEAD = do_POST = do_DELETE = _dispatch

        # ── files ───────────────────────────────────────────────────────

        def _static(self, name, content_type):
            name = name.replace("-precomposed", "")
            with open(os.path.join(paths.STATIC_DIR, name), "rb") as f:
                self._send(200, f.read(), content_type)

        def _upload(self, query):
            if self.headers.get_content_type() != "application/octet-stream":
                raise ApiError("Expected application/octet-stream", status=415)
            try:
                name = audio.save_upload(query.get("name", ""), self.rfile,
                                         self._content_length())
            except audio.AudioError as exc:
                raise ApiError(str(exc))
            log.info("Audio file uploaded: %s", name)
            self._json(app.audio_list(None, None))

        def _audio(self, name):
            """Let the browser preview a file (supports seeking)."""
            try:
                path = audio.path_for(name)
                size = os.path.getsize(path)
            except (audio.AudioError, OSError):
                return self._error("Not found", 404)
            start, end, status = 0, size - 1, HTTPStatus.OK
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if match and (match.group(1) or match.group(2)):
                if match.group(1):
                    start = int(match.group(1))
                    end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
                else:
                    start = max(0, size - int(match.group(2)))
                if start > end or start >= size:
                    return self._send(416, b"", "audio/mpeg",
                                      {"Content-Range": f"bytes */{size}"})
                status = HTTPStatus.PARTIAL_CONTENT
            self.send_response(status)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(app, host="0.0.0.0", port=9090):
    return Server((host, port), make_handler(app))
