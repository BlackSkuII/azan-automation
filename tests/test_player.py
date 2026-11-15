import os
import unittest
from unittest import mock

from azan import audio, paths
from azan.player import Player
from tests.helpers import FakeCast, FakeClock, FakeProc, FakeTV, temp_store

RUNNING = None


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.store, self.dir = temp_store(self, device_name="Den", volume=50,
                                          fajr_volume=35, end_buffer_seconds=5)
        for name in ("azan.mp3", "fajr_azan.mp3"):
            open(os.path.join(self.dir, name), "w").close()
        patches = [mock.patch.object(paths, "AUDIO_DIR", self.dir),
                   mock.patch.object(audio, "duration", return_value=100.0)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.clock = FakeClock()
        self.tv = FakeTV()

    def player(self, cast):
        return Player(self.store, cast=cast, tv=self.tv, clock=self.clock,
                      sleep=self.clock.sleep)

    def test_plays_then_restores_previous_volume_and_tv(self):
        cast = FakeCast([FakeProc([RUNNING] * 200 + [0])], volume=22)
        player = self.player(cast)
        self.assertTrue(player.play("Dhuhr azan"))
        self.assertEqual(cast.calls, [("volume", 50), ("cast", "azan.mp3"), ("volume", 22)])
        self.assertEqual(self.tv.calls, ["pause", "resume"])
        self.assertTrue(player.last_result["ok"])
        self.assertIsNone(player.status()["playing"])

    def test_fajr_uses_its_own_file_and_volume(self):
        cast = FakeCast([FakeProc([RUNNING] * 10 + [0])])
        self.player(cast).play("Fajr azan", fajr=True)
        self.assertEqual(cast.calls[:2], [("volume", 35), ("cast", "fajr_azan.mp3")])

    def test_fixed_volume_after(self):
        self.store.update({"volume_after": 60})
        cast = FakeCast([FakeProc([RUNNING] * 10 + [0])], volume=22)
        self.player(cast).play("Asr azan")
        self.assertEqual(cast.calls[-1], ("volume", 60))

    def test_retries_when_the_speaker_is_asleep(self):
        cast = FakeCast([FakeProc([1], "Error: Device not found"),
                         FakeProc([RUNNING] * 10 + [0])])
        cast.volume_failures = 1
        self.assertTrue(self.player(cast).play("Isha azan"))
        self.assertEqual([c[0] for c in cast.calls].count("cast"), 2)

    def test_gives_up_after_three_attempts_and_still_restores(self):
        cast = FakeCast([FakeProc([1], "Error: boom") for _ in range(3)], volume=22)
        player = self.player(cast)
        self.assertFalse(player.play("Asr azan"))
        self.assertEqual(player.last_result["message"], "boom")
        self.assertEqual(cast.calls[-1], ("volume", 22))
        self.assertEqual(self.tv.calls, ["pause", "resume"])

    def test_late_failure_is_not_replayed(self):
        cast = FakeCast([FakeProc([RUNNING] * 120 + [1]), FakeProc([0])])
        self.assertFalse(self.player(cast).play("Asr azan"))
        self.assertEqual(len(cast.procs), 1)  # second process never started

    def test_catt_that_never_exits_is_ended_after_the_track(self):
        proc = FakeProc([RUNNING] * 100000)
        cast = FakeCast([proc])
        self.assertTrue(self.player(cast).play("Asr azan"))
        self.assertTrue(proc.terminated)
        self.assertAlmostEqual(self.clock.t, 130, delta=2)  # 100 s + 5 s buffer + start-up

    def test_stop_ends_playback_early(self):
        proc = FakeProc([RUNNING] * 100000)
        cast = FakeCast([proc], volume=22)
        player = self.player(cast)
        polls = {"n": 0}
        real_sleep = self.clock.sleep

        def sleep(seconds):
            polls["n"] += 1
            if polls["n"] == 5:
                self.assertTrue(player.stop())
            real_sleep(seconds)
        player.sleep = sleep
        self.assertFalse(player.play("Asr azan"))
        self.assertTrue(proc.terminated)
        self.assertIn(("stop",), cast.calls)
        self.assertEqual(cast.calls[-1], ("volume", 22))
        self.assertEqual(player.last_result["message"], "Stopped")

    def test_no_speaker_or_missing_file_fails_cleanly(self):
        cast = FakeCast([])
        player = self.player(cast)
        self.assertFalse(player.play("Test", file="gone.mp3"))
        self.store.update({"device_name": ""})
        self.assertFalse(player.play("Test"))
        self.assertEqual(cast.calls, [])

    def test_unreadable_volume_is_left_alone(self):
        cast = FakeCast([FakeProc([RUNNING] * 10 + [0])], volume=None)
        self.player(cast).play("Asr azan")
        self.assertEqual(cast.calls, [("volume", 50), ("cast", "azan.mp3")])


if __name__ == "__main__":
    unittest.main()
