import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from azan import audio, paths
from azan.scheduler import Scheduler
from azan.web import App, make_server
from tests.helpers import temp_store


class FakePlayer:
    def __init__(self):
        self.started = []
        self.busy = False

    def status(self):
        return {"playing": None, "last": None}

    def play_async(self, label, fajr=False, file=None, volume=None):
        if self.busy:
            return False
        self.started.append((label, fajr, file, volume))
        return True

    def stop(self):
        return False


class WebTests(unittest.TestCase):
    def setUp(self):
        self.store, self.dir = temp_store(self)
        self.audio_dir = os.path.join(self.dir, "audio")
        os.makedirs(self.audio_dir)
        for name in ("azan.mp3", "fajr_azan.mp3", "spare.mp3"):
            with open(os.path.join(self.audio_dir, name), "wb") as f:
                f.write(b"0123456789")
        log_file = os.path.join(self.dir, "azan.log")
        with open(log_file, "w") as f:
            f.write("one\ntwo\nthree\n")
        for patch in (mock.patch.object(paths, "AUDIO_DIR", self.audio_dir),
                      mock.patch.object(paths, "LOG_FILE", log_file),
                      mock.patch.object(audio, "duration", return_value=12.0)):
            patch.start()
            self.addCleanup(patch.stop)
        self.player = FakePlayer()
        scheduler = Scheduler(self.store, self.player,
                              fetch=lambda *a: {"times": {}, "timezone": None},
                              times_file=os.path.join(self.dir, "t.json"),
                              state_file=os.path.join(self.dir, "s.json"))
        self.server = make_server(App(self.store, scheduler, self.player), "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def call(self, method, path, body=None, content_type="application/json", headers=None):
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            hdrs["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                raw, status, rh = resp.read(), resp.status, resp.headers
        except urllib.error.HTTPError as exc:
            raw, status, rh = exc.read(), exc.code, exc.headers
        if rh.get_content_type() == "application/json":
            return status, json.loads(raw)
        return status, raw

    def test_page_and_status(self):
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Azan</title>", page)
        status, data = self.call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["prayers"]), 5)
        self.assertIn("version", data)

    def test_home_screen_files_are_served(self):
        status, page = self.call("GET", "/")
        self.assertIn(b'rel="manifest" href="/manifest.webmanifest"', page)
        self.assertIn(b'rel="apple-touch-icon" href="/apple-touch-icon.png"', page)
        status, raw = self.call("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200)
        manifest = json.loads(raw)
        self.assertEqual(manifest["display"], "standalone")
        for icon in manifest["icons"] + [{"src": "/apple-touch-icon.png"},
                                         {"src": "/apple-touch-icon-precomposed.png"}]:
            status, png = self.call("GET", icon["src"])
            self.assertEqual(status, 200, icon["src"])
            self.assertTrue(png.startswith(b"\x89PNG"), icon["src"])

    def test_settings_round_trip_hides_the_token(self):
        status, data = self.call("POST", "/api/settings",
                                 {"device_name": "Den", "volume": 44, "ha_token": "s3cret"})
        self.assertEqual(status, 200)
        self.assertNotIn("ha_token", data)
        self.assertTrue(data["ha_token_set"])
        self.assertEqual(self.store.get()["ha_token"], "s3cret")
        # Saving again without a token keeps it.
        self.call("POST", "/api/settings", {"volume": 45, "ha_token": None})
        self.assertEqual(self.store.get()["ha_token"], "s3cret")
        self.assertEqual(self.call("GET", "/api/settings")[1]["volume"], 45)

    def test_setup_completion_is_reported_and_saved(self):
        self.assertFalse(self.store.get()["setup_complete"])
        self.assertFalse(self.call("GET", "/api/status")[1]["setup_complete"])
        self.assertEqual(self.call("POST", "/api/setup", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/setup", {"complete": "yes"})[0], 400)
        self.assertFalse(self.store.get()["setup_complete"])
        status, data = self.call("POST", "/api/setup", {"complete": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["setup_complete"])
        self.assertTrue(self.store.get()["setup_complete"])
        self.assertTrue(self.call("GET", "/api/status")[1]["setup_complete"])

    def test_invalid_settings_report_fields(self):
        status, data = self.call("POST", "/api/settings", {"volume": 400})
        self.assertEqual(status, 400)
        self.assertIn("volume", data["fields"])

    def test_changes_must_be_json(self):
        status, _ = self.call("POST", "/api/settings", b"volume=1",
                              content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 415)
        self.assertEqual(self.call("POST", "/api/settings", b"{oops")[0], 400)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)

    def test_play_needs_a_speaker_and_a_real_file(self):
        self.assertEqual(self.call("POST", "/api/play", {})[0], 400)
        self.store.update({"device_name": "Den"})
        self.assertEqual(self.call("POST", "/api/play", {"file": "../x.mp3"})[0], 400)
        self.assertEqual(self.call("POST", "/api/play", {"volume": 300})[0], 400)
        self.assertEqual(self.call("POST", "/api/play", {"fajr": True, "volume": 10})[0], 200)
        self.assertEqual(self.player.started, [("Test", True, "fajr_azan.mp3", 10)])
        self.player.busy = True
        self.assertEqual(self.call("POST", "/api/play", {})[0], 409)

    def test_audio_list_upload_delete(self):
        status, data = self.call("GET", "/api/audio")
        self.assertEqual([f["name"] for f in data["files"]],
                         ["azan.mp3", "fajr_azan.mp3", "spare.mp3"])
        status, data = self.call("POST", "/api/audio?name=..%2Fnew%20one.mp3", b"abc",
                                 content_type="application/octet-stream")
        self.assertEqual(status, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.audio_dir, "new one.mp3")))
        self.assertEqual(self.call("POST", "/api/audio?name=evil.sh", b"abc",
                                   content_type="application/octet-stream")[0], 400)
        self.assertEqual(self.call("DELETE", "/api/audio?name=azan.mp3")[0], 400)  # in use
        self.assertEqual(self.call("DELETE", "/api/audio?name=..%2Fsettings.json")[0], 400)
        self.assertEqual(self.call("DELETE", "/api/audio?name=spare.mp3")[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.audio_dir, "spare.mp3")))

    def test_audio_preview_supports_ranges_and_blocks_traversal(self):
        self.assertEqual(self.call("GET", "/audio/azan.mp3"), (200, b"0123456789"))
        self.assertEqual(self.call("GET", "/audio/azan.mp3", headers={"Range": "bytes=2-4"}),
                         (206, b"234"))
        self.assertEqual(self.call("GET", "/audio/azan.mp3", headers={"Range": "bytes=-3"}),
                         (206, b"789"))
        self.assertEqual(self.call("GET", "/audio/..%2Fsettings.json")[0], 404)

    def test_log_tail(self):
        self.assertEqual(self.call("GET", "/api/log?lines=2")[1]["lines"], ["two", "three"])


if __name__ == "__main__":
    unittest.main()
