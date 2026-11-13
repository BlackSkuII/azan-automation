"""Tests for the masjid's Aladhan prayer-time query."""

import sys
import os
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from azan import config, prayer_times


def _response(payload, status=200):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.status_code = status
    resp.raise_for_status.return_value = None
    return resp


def _payload(**overrides):
    timings = {
        "Fajr": "05:12 (EST)",
        "Sunrise": "06:33 (EST)",
        "Dhuhr": "11:29 (EST)",
        "Asr": "14:42 (EST)",
        "Maghrib": "16:24 (EST)",
        "Isha": "17:45 (EST)",
    }
    timings.update(overrides)
    return {"code": 200, "status": "OK", "data": {"timings": timings}}


class MasjidQueryTests(unittest.TestCase):
    """The request must match what zamongajumath.com sends."""

    def test_build_request_uses_masjid_defaults(self):
        url, params = prayer_times.build_request(
            prayer_times.MASJID_LATITUDE,
            prayer_times.MASJID_LONGITUDE,
            prayer_times.MASJID_METHOD,
            prayer_times.MASJID_SCHOOL,
            when=date(2026, 11, 13),
        )
        self.assertEqual(url, "https://api.aladhan.com/v1/timings/13-11-2026")
        self.assertEqual(
            params,
            {"latitude": 42.3601, "longitude": -71.0589, "method": 2, "school": 1},
        )

    def test_date_formats(self):
        cases = [
            (date(2026, 1, 5), "05-01-2026"),
            (datetime(2026, 1, 5, 9, 30), "05-01-2026"),
            ("13-11-2026", "13-11-2026"),
        ]
        for value, expected in cases:
            url, _ = prayer_times.build_request(42.0, -71.0, 2, 1, when=value)
            self.assertTrue(url.endswith("/" + expected), url)

    def test_config_defaults_match_masjid_settings(self):
        defaults = config.DEFAULTS
        self.assertEqual(defaults["latitude"], prayer_times.MASJID_LATITUDE)
        self.assertEqual(defaults["longitude"], prayer_times.MASJID_LONGITUDE)
        self.assertEqual(defaults["method"], prayer_times.MASJID_METHOD)
        self.assertEqual(defaults["school"], prayer_times.MASJID_SCHOOL)


class LegacyConfigTests(unittest.TestCase):
    def test_old_city_config_is_upgraded_to_masjid_settings(self):
        cfg = config.upgrade_legacy_config(
            {"city": "Gurgaon", "country": "India", "method": 1, "school": 1,
             "volume": "100"}
        )
        self.assertEqual(cfg["latitude"], prayer_times.MASJID_LATITUDE)
        self.assertEqual(cfg["longitude"], prayer_times.MASJID_LONGITUDE)
        self.assertEqual(cfg["method"], 2)
        self.assertEqual(cfg["school"], 1)
        self.assertEqual(cfg["volume"], "100")  # user settings are preserved

    def test_new_config_is_left_alone(self):
        cfg = {"latitude": 40.0, "longitude": -73.0, "method": 3, "school": 0}
        self.assertEqual(
            config.upgrade_legacy_config(dict(cfg)), cfg,
        )


class FetchTests(unittest.TestCase):
    @mock.patch("azan.prayer_times.requests.get")
    def test_parses_times_without_timezone_suffix(self, get):
        get.return_value = _response(_payload())
        times = prayer_times.fetch_prayer_times(when=date(2026, 11, 13))

        self.assertEqual(
            times,
            {"Fajr": "05:12", "Dhuhr": "11:29", "Asr": "14:42",
             "Maghrib": "16:24", "Isha": "17:45"},
        )
        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://api.aladhan.com/v1/timings/13-11-2026")
        self.assertEqual(kwargs["params"]["method"], 2)
        self.assertEqual(kwargs["params"]["school"], 1)
        self.assertEqual(kwargs["timeout"], 10)

    @mock.patch("azan.prayer_times.requests.get")
    def test_parses_plain_times(self, get):
        payload = _payload(Fajr="05:12", Dhuhr="11:28", Isha="17:44")
        get.return_value = _response(payload)
        times = prayer_times.fetch_prayer_times()
        self.assertEqual(times["Fajr"], "05:12")
        self.assertEqual(times["Isha"], "17:44")

    @mock.patch("azan.prayer_times.requests.get")
    def test_raises_on_api_error_code(self, get):
        get.return_value = _response({"code": 400, "status": "BAD_REQUEST"})
        with self.assertRaises(prayer_times.PrayerTimesError):
            prayer_times.fetch_prayer_times()

    @mock.patch("azan.prayer_times.requests.get")
    def test_raises_on_missing_prayer(self, get):
        payload = _payload(Maghrib="N/A")
        get.return_value = _response(payload)
        with self.assertRaises(prayer_times.PrayerTimesError):
            prayer_times.fetch_prayer_times()

    @mock.patch("azan.prayer_times.requests.get")
    def test_raises_on_network_error(self, get):
        import requests
        get.side_effect = requests.ConnectionError("no route to host")
        with self.assertRaises(prayer_times.PrayerTimesError):
            prayer_times.fetch_prayer_times()


if __name__ == "__main__":
    unittest.main()
