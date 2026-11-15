import unittest
from datetime import date

from azan import cast, prayer_times


def payload(**overrides):
    timings = {"Fajr": "05:12", "Sunrise": "06:33", "Dhuhr": "11:29", "Asr": "14:42",
               "Maghrib": "16:24 (EST)", "Isha": "17:45"}
    timings.update(overrides)
    return {"code": 200, "status": "OK",
            "data": {"timings": timings, "meta": {"timezone": "America/New_York"}}}


class PrayerTimesTests(unittest.TestCase):
    def test_url_is_the_masjids_query(self):
        url = prayer_times.build_url(42.3601, -71.0589, 2, 1, date(2026, 1, 5))
        self.assertEqual(url, "https://api.aladhan.com/v1/timings/05-01-2026"
                              "?latitude=42.3601&longitude=-71.0589&method=2&school=1")

    def test_parses_times_and_timezone(self):
        got = prayer_times.parse_response(payload())
        self.assertEqual(got["times"], {"Fajr": "05:12", "Dhuhr": "11:29", "Asr": "14:42",
                                        "Maghrib": "16:24", "Isha": "17:45"})
        self.assertEqual(got["timezone"], "America/New_York")

    def test_bad_responses_raise(self):
        for bad in ({"code": 400, "status": "BAD_REQUEST"}, payload(Maghrib="N/A"),
                    payload(Isha="25:00"), payload(Fajr=None), "nonsense", {"code": 200}):
            with self.subTest(bad=bad), self.assertRaises(prayer_times.PrayerTimesError):
                prayer_times.parse_response(bad)


class CastParsingTests(unittest.TestCase):
    def test_scan_text(self):
        text = ("Scanning Chromecasts...\n"
                "192.168.1.17 - Living Room speaker - Google Inc. Google Home\n"
                "192.168.1.30 - Den - TV - Vizio SmartCast\n")
        got = cast.parse_scan_text(text)
        self.assertEqual(got[0], {"name": "Living Room speaker", "ip": "192.168.1.17",
                                  "model": "Google Inc. Google Home"})
        self.assertEqual(got[1]["ip"], "192.168.1.30")

    def test_scan_json(self):
        got = cast.parse_scan_json('{"Kitchen": {"host": "10.0.0.5", "friendly_name": '
                                   '"Kitchen", "manufacturer": "Google", "model_name": "Nest Mini"}}')
        self.assertEqual(got, [{"name": "Kitchen", "ip": "10.0.0.5", "model": "Google Nest Mini"}])

    def test_matches_by_name_or_ip(self):
        device = {"name": "Living Room speaker", "ip": "192.168.1.17", "model": ""}
        self.assertTrue(cast.matches(device, "living room speaker "))
        self.assertTrue(cast.matches(device, "192.168.1.17"))
        self.assertFalse(cast.matches(device, "Kitchen"))
        self.assertFalse(cast.matches(device, ""))


if __name__ == "__main__":
    unittest.main()
