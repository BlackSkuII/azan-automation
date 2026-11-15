import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from azan import prayer_times
from azan.scheduler import Scheduler
from tests.helpers import FakeCast, temp_store

NY = ZoneInfo("America/New_York")
TIMES = {"Fajr": "05:12", "Dhuhr": "11:29", "Asr": "14:42", "Maghrib": "16:24", "Isha": "17:45"}


def at(hh, mm, ss=0, day=13):
    return datetime(2026, 11, day, hh, mm, ss, tzinfo=NY)


class FakePlayer:
    def __init__(self):
        self.played = []

    def play_async(self, label, fajr=False, file=None, volume=None):
        self.played.append((label, fajr))
        return True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.store, self.dir = temp_store(self, device_name="Den", precheck_minutes=0)
        self.player = FakePlayer()
        self.fetches = []
        self.offline = False
        self.reboots = []
        self.cast = FakeCast(devices=[{"name": "Den", "ip": "10.0.0.2", "model": ""}])

    def fetch(self, lat, lon, method, school, day):
        self.fetches.append(day.isoformat())
        if self.offline:
            raise prayer_times.PrayerTimesError("no network")
        return {"times": dict(TIMES), "timezone": "America/New_York"}

    def scheduler(self):
        return Scheduler(self.store, self.player, fetch=self.fetch, cast=self.cast,
                         times_file=os.path.join(self.dir, "times.json"),
                         state_file=os.path.join(self.dir, "state.json"),
                         reboot=lambda: self.reboots.append(1))

    def test_plays_each_azan_once_at_its_time(self):
        s = self.scheduler()
        self.assertEqual(s.tick(at(4, 0)), [])
        self.assertEqual(s.tick(at(5, 11, 58)), [])
        self.assertEqual(s.tick(at(5, 12, 1)), [("play", "Fajr")])
        self.assertEqual(s.tick(at(5, 12, 6)), [])
        self.assertEqual(s.tick(at(11, 29, 3)), [("play", "Dhuhr")])
        self.assertEqual(self.player.played, [("Fajr azan", True), ("Dhuhr azan", False)])
        self.assertEqual(self.fetches, ["2026-11-13"])  # one fetch for the whole day

    def test_nothing_is_replayed_when_the_service_starts_late(self):
        s = self.scheduler()
        self.assertEqual(s.tick(at(11, 29, 30)), [])   # started 30 s after Dhuhr
        self.assertEqual(s.tick(at(14, 42, 2)), [("play", "Asr")])

    def test_restart_does_not_repeat_an_azan_already_started(self):
        s = self.scheduler()
        s.tick(at(11, 0))
        s.tick(at(11, 29, 1))
        again = self.scheduler()
        again.tick(at(11, 29, 20))
        self.assertEqual(again.tick(at(11, 29, 25)), [])
        self.assertEqual(len(self.player.played), 1)

    def test_disabled_prayer_and_offset(self):
        self.store.update({"prayers": {"Asr": {"enabled": False},
                                       "Maghrib": {"offset": 3}}})
        s = self.scheduler()
        s.tick(at(14, 0))
        self.assertEqual(s.tick(at(14, 42, 1)), [])
        self.assertEqual(s.tick(at(16, 24, 1)), [])
        self.assertEqual(s.tick(at(16, 27, 1)), [("play", "Maghrib")])

    def test_new_day_fetches_new_times(self):
        s = self.scheduler()
        s.tick(at(12, 0))
        s.tick(at(23, 59, 50))
        s.tick(at(0, 0, 5, day=14))
        self.assertEqual(self.fetches, ["2026-11-13", "2026-11-14"])
        self.assertEqual(s.tick(at(5, 12, 2, day=14)), [("play", "Fajr")])

    def test_failed_fetch_keeps_using_the_last_known_times(self):
        s = self.scheduler()
        s.tick(at(23, 0))
        self.offline = True
        s.tick(at(0, 1, day=14))
        snap = s.snapshot(at(0, 2, day=14))
        self.assertTrue(snap["times_stale"])
        self.assertEqual(snap["fetch_error"], "no network")
        self.assertEqual(s.tick(at(5, 12, 2, day=14)), [("play", "Fajr")])
        # Retries are spaced out, not every tick.
        before = len(self.fetches)
        s.tick(at(5, 12, 7, day=14))
        self.assertEqual(len(self.fetches), before)
        self.offline = False
        s.tick(at(5, 20, day=14))
        self.assertFalse(s.snapshot(at(5, 21, day=14))["times_stale"])

    def test_times_survive_a_restart_without_network(self):
        self.scheduler().tick(at(4, 0))
        self.offline = True
        s = self.scheduler()
        s.tick(at(4, 30))
        self.assertEqual(s.tick(at(5, 12, 1)), [("play", "Fajr")])

    def test_no_times_at_all_means_no_events(self):
        self.offline = True
        s = self.scheduler()
        self.assertEqual(s.tick(at(5, 12, 1)), [])
        snap = s.snapshot(at(5, 13))
        self.assertIsNone(snap["next"])
        self.assertEqual([p["time"] for p in snap["prayers"]], [None] * 5)

    def test_changing_location_discards_old_times(self):
        s = self.scheduler()
        s.tick(at(4, 0))
        self.offline = True
        self.store.update({"latitude": 10.0})
        self.assertEqual(s.times(), {})

    def test_speaker_check_runs_before_the_azan(self):
        self.store.update({"precheck_minutes": 5})
        s = self.scheduler()
        s.tick(at(5, 0))
        self.assertEqual(s.tick(at(5, 7, 1)), [("check", "Fajr")])

    def test_check_reboots_only_when_missing_and_enabled(self):
        s = self.scheduler()
        self.assertTrue(s.check_speaker("Fajr"))
        self.assertEqual(self.reboots, [])
        self.cast.devices = []
        import azan.scheduler as module
        module.time.sleep, real = (lambda seconds: None), module.time.sleep
        self.addCleanup(setattr, module.time, "sleep", real)
        self.assertFalse(s.check_speaker(allow_reboot=False))
        self.assertFalse(s.check_speaker())           # manual check: never reboots
        self.assertEqual(self.reboots, [])
        self.assertFalse(s.check_speaker("Fajr"))
        self.assertEqual(self.reboots, [1])
        self.store.update({"reboot_if_missing": False})
        s.check_speaker("Fajr")
        self.assertEqual(self.reboots, [1])
        self.assertFalse(s.device_status["online"])

    def test_snapshot_next_prayer(self):
        s = self.scheduler()
        s.tick(at(12, 0))
        snap = s.snapshot(at(12, 0))
        self.assertEqual(snap["next"]["name"], "Asr")
        self.assertEqual(snap["next"]["seconds"], 2 * 3600 + 42 * 60)
        self.assertTrue(snap["prayers"][0]["passed"])
        late = s.snapshot(at(20, 0))
        self.assertEqual(late["next"]["name"], "Fajr")
        self.assertTrue(late["next"]["tomorrow"])

    def test_first_fetch_uses_the_masjids_date_even_if_the_pi_clock_differs(self):
        s = self.scheduler()
        s.tick(at(23, 30).astimezone(ZoneInfo("Asia/Tokyo")))  # already the 14th in Tokyo
        self.assertEqual(self.fetches[-1], "2026-11-13")
        self.assertEqual(s.snapshot(at(23, 31))["times_date"], "2026-11-13")

    def test_azan_follows_the_masjid_timezone_not_the_pi_clock(self):
        s = self.scheduler()
        s.tick(at(4, 0))
        utc_fajr = at(5, 12, 1).astimezone(ZoneInfo("UTC"))
        self.assertEqual(s.tick(utc_fajr), [("play", "Fajr")])


if __name__ == "__main__":
    unittest.main()
