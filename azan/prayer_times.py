"""Prayer times from the Aladhan API (the same query the masjid uses)."""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as date_cls

from azan import PRAYERS

ALADHAN_API = "https://api.aladhan.com/v1"


class PrayerTimesError(RuntimeError):
    """Raised when prayer times cannot be fetched or understood."""


def build_url(latitude, longitude, method, school, day):
    query = urllib.parse.urlencode({
        "latitude": latitude, "longitude": longitude,
        "method": method, "school": school,
    })
    return f"{ALADHAN_API}/timings/{day.strftime('%d-%m-%Y')}?{query}"


def parse_response(payload):
    """Turn Aladhan's JSON into {"times": {prayer: "HH:MM"}, "timezone": str|None}."""
    if not isinstance(payload, dict) or payload.get("code") != 200 \
            or not isinstance(payload.get("data"), dict):
        status = payload.get("status") if isinstance(payload, dict) else payload
        raise PrayerTimesError(f"Aladhan error: {status}")

    timings = payload["data"].get("timings") or {}
    times = {}
    for name in PRAYERS:
        # Aladhan may return "05:12 (EST)"; keep only the clock time.
        raw = str(timings.get(name) or "").split(" ")[0].strip()
        parts = raw.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts) \
                or not (int(parts[0]) < 24 and int(parts[1]) < 60):
            raise PrayerTimesError(f"Aladhan response has no usable time for {name}")
        times[name] = f"{int(parts[0]):02d}:{int(parts[1]):02d}"

    meta = payload["data"].get("meta") or {}
    return {"times": times, "timezone": meta.get("timezone") or None}


def fetch(latitude, longitude, method, school, day=None, timeout=15):
    day = day or date_cls.today()
    url = build_url(latitude, longitude, method, school, day)
    request = urllib.request.Request(url, headers={"User-Agent": "azan-automation"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise PrayerTimesError(f"Aladhan returned HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:  # URLError, timeouts, bad JSON
        raise PrayerTimesError(f"Could not reach Aladhan: {exc}") from exc
    return parse_response(payload)
