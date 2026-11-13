"""Fetch prayer times from the same Aladhan query the masjid uses.

The masjid's website/app (zamongajumath.com) calls Aladhan with a fixed
location, the ISNA calculation method, and the Hanafi asr school:

    https://api.aladhan.com/v1/timings/<DD-MM-YYYY>
        ?latitude=<lat>&longitude=<lng>&method=<method>&school=<school>

Using the same coordinates/method/school keeps the azan on the Google Home
in sync with the times shown by the masjid.
"""

from datetime import date as date_cls, datetime

import requests

ALADHAN_API = "https://api.aladhan.com/v1"

# Fixed masjid location — same coordinates the masjid website uses for every
# screen (no device-GPS drift). Change via config.yaml if the masjid moves.
MASJID_LATITUDE = 42.3601
MASJID_LONGITUDE = -71.0589
MASJID_METHOD = 2  # ISNA (North America)
MASJID_SCHOOL = 1  # Hanafi

PRAYER_NAMES = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

_DATE_FORMAT = "%d-%m-%Y"


class PrayerTimesError(RuntimeError):
    """Raised when prayer times cannot be fetched or parsed."""


def _format_date(value):
    """Return the DD-MM-YYYY string Aladhan expects (masjid uses this form)."""
    if value is None:
        value = datetime.now()
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date_cls):
        return value.strftime(_DATE_FORMAT)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise PrayerTimesError(f"Unsupported date value: {value!r}")


def build_request(latitude, longitude, method, school, when=None):
    """Build the (url, params) pair for Aladhan's /timings endpoint."""
    url = f"{ALADHAN_API}/timings/{_format_date(when)}"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "method": method,
        "school": school,
    }
    return url, params


def fetch_prayer_times(
    latitude=MASJID_LATITUDE,
    longitude=MASJID_LONGITUDE,
    method=MASJID_METHOD,
    school=MASJID_SCHOOL,
    when=None,
    timeout=10,
):
    """Return {prayer: "HH:MM"} (24h) for the given day.

    Defaults match the masjid's own settings, so a bare call returns the
    same times the masjid publishes.
    """
    url, params = build_request(latitude, longitude, method, school, when)

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise PrayerTimesError(f"Could not reach Aladhan: {exc}") from exc
    except ValueError as exc:
        raise PrayerTimesError(f"Aladhan returned invalid JSON: {exc}") from exc

    if payload.get("code") != 200 or "data" not in payload:
        raise PrayerTimesError(
            f"Aladhan error: {payload.get('status') or payload}"
        )

    timings = payload["data"].get("timings") or {}
    result = {}
    for name in PRAYER_NAMES:
        raw = timings.get(name)
        if not raw or raw == "N/A":
            raise PrayerTimesError(f"Aladhan response is missing {name}")
        # Aladhan may return "05:12 (EST)"; keep only the clock time.
        result[name] = raw.split(" ")[0].strip()

    return result
