"""Keeps today's prayer times fresh and fires the speaker check and the azan."""

import logging
import threading
import time
from datetime import datetime, timedelta

from azan import PRAYERS, cast as cast_module, paths, prayer_times, system

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

log = logging.getLogger("azan")

GRACE_SECONDS = 120      # how late an event may still run (e.g. after a busy tick)
RETRY_SECONDS = 120      # wait between failed fetches
TICK_SECONDS = 5
_LOCATION_KEYS = ("latitude", "longitude", "method", "school")


def _zone(name):
    if not name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        return None


class Scheduler:
    def __init__(self, store, player, fetch=prayer_times.fetch, cast=cast_module,
                 times_file=None, state_file=None, reboot=system.reboot):
        self.store = store
        self.player = player
        self.fetch = fetch
        self.cast = cast
        self.reboot = reboot
        self.times_file = times_file or paths.TIMES_FILE
        self.state_file = state_file or paths.STATE_FILE
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._cache = paths.read_json(self.times_file) or {}
        self._done = set((paths.read_json(self.state_file) or {}).get("done", []))
        self._started = False
        self._last_attempt = None
        self._force = False
        self.fetch_error = None
        self.device_status = None  # {"online": bool, "at": str, "detail": str}

    # ── times ───────────────────────────────────────────────────────────

    def _params(self, s):
        return [s[k] for k in _LOCATION_KEYS]

    def _tz(self):
        return _zone(self._cache.get("timezone"))

    def now(self):
        return datetime.now().astimezone()

    def local(self, moment):
        """A moment expressed in the masjid's timezone (or the Pi's)."""
        tz = self._tz()
        return moment.astimezone(tz) if tz else moment.astimezone()

    def _cache_valid_for(self, s):
        return bool(self._cache.get("times")) and self._cache.get("params") == self._params(s)

    def refresh(self, now=None, force=False):
        """Fetch today's times if needed. Returns True if times are current."""
        now = now or self.now()
        s = self.store.get()
        with self._lock:
            today = self.local(now).date().isoformat()
            current = self._cache_valid_for(s) and self._cache.get("date") == today
            if current and not force:
                return True
            if not force and self._last_attempt is not None \
                    and (now - self._last_attempt).total_seconds() < RETRY_SECONDS:
                return False
            self._last_attempt = now
        try:
            day = self.local(now).date()
            result = self.fetch(s["latitude"], s["longitude"], s["method"], s["school"], day)
            # The masjid's timezone is only known after the first answer. If the
            # Pi's clock is in another zone, "today" there may be a different date.
            zone = _zone(result.get("timezone"))
            if zone and now.astimezone(zone).date() != day:
                result = self.fetch(s["latitude"], s["longitude"], s["method"],
                                    s["school"], now.astimezone(zone).date())
        except prayer_times.PrayerTimesError as exc:
            if str(exc) != self.fetch_error:
                log.warning("Prayer times not updated: %s", exc)
            self.fetch_error = str(exc)
            return current
        with self._lock:
            self._cache = {
                "date": today, "times": result["times"],
                "timezone": result.get("timezone"), "params": self._params(s),
                "fetched_at": "",
            }
            self._cache["date"] = self.local(now).date().isoformat()
            self._cache["fetched_at"] = self.local(now).strftime("%Y-%m-%d %H:%M:%S")
            self.fetch_error = None
            paths.write_json_atomic(self.times_file, self._cache)
        log.info("Prayer times for %s: %s", self._cache["date"],
                 ", ".join(f"{k} {v}" for k, v in result["times"].items()))
        return True

    def times(self):
        """Clock times in use ({} if none are known for the current location)."""
        with self._lock:
            if self._cache_valid_for(self.store.get()):
                return dict(self._cache["times"])
            return {}

    def events(self, now):
        """Today's events: [(when, key, kind, prayer)] sorted by time."""
        s = self.store.get()
        times = self.times()
        day = self.local(now).date()
        tz = self._tz()
        out = []
        for name in PRAYERS:
            cfg = s["prayers"][name]
            if name not in times or not cfg["enabled"]:
                continue
            hour, minute = map(int, times[name].split(":"))
            naive = datetime(day.year, day.month, day.day, hour, minute)
            base = naive.replace(tzinfo=tz) if tz else naive.astimezone()
            play_at = base + timedelta(minutes=cfg["offset"])
            out.append((play_at, f"{day}:{name}:play", "play", name))
            if s["precheck_minutes"] > 0:
                check_at = play_at - timedelta(minutes=s["precheck_minutes"])
                out.append((check_at, f"{day}:{name}:check", "check", name))
        return sorted(out, key=lambda e: e[0])

    # ── the loop ────────────────────────────────────────────────────────

    def tick(self, now=None):
        """Run anything that is due. Returns the list of (kind, prayer) fired."""
        now = now or self.now()
        force, self._force = self._force, False
        self.refresh(now, force=force)
        fired = []
        changed = False
        with self._lock:
            for when, key, kind, prayer in self.events(now):
                if when > now or key in self._done:
                    continue
                self._done.add(key)
                changed = True
                late = (now - when).total_seconds()
                # Nothing is replayed on start-up: only events that come due
                # while the service is running are acted on.
                if self._started and late <= GRACE_SECONDS:
                    fired.append((kind, prayer))
            self._started = True
            if changed:
                today = str(self.local(now).date())
                self._done = {k for k in self._done if k.startswith(today)}
                paths.write_json_atomic(self.state_file, {"done": sorted(self._done)})
        for kind, prayer in fired:
            if kind == "play":
                self.player.play_async(f"{prayer} azan", fajr=(prayer == "Fajr"))
            else:
                threading.Thread(target=self.check_speaker, args=(prayer,),
                                 name="azan-check", daemon=True).start()
        return fired

    def run_forever(self):
        log.info("Scheduler started.")
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("Scheduler error (will keep going)")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def request_refresh(self):
        self._force = True
        self._last_attempt = None
        self._wake.set()

    def settings_changed(self, changed):
        if any(k in _LOCATION_KEYS for k in changed):
            self.request_refresh()

    # ── speaker check ───────────────────────────────────────────────────

    def check_speaker(self, prayer=None, allow_reboot=True):
        """Look for the speaker on the network; optionally reboot if it is gone."""
        s = self.store.get()
        wanted = s["device_name"]
        if not wanted:
            return None
        found, detail = False, ""
        for attempt in range(2):
            try:
                devices = self.cast.scan()
                found = any(self.cast.matches(d, wanted) for d in devices)
                detail = "" if found else f"{len(devices)} other device(s) seen"
            except cast_module.CastError as exc:
                detail = str(exc)
            if found:
                break
            time.sleep(3 if attempt == 0 else 0)
        self.device_status = {"online": found, "detail": detail,
                              "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        prefix = f"Before {prayer}: speaker" if prayer else "Speaker"
        if found:
            log.info("%s '%s' is online.", prefix, wanted)
        else:
            log.warning("%s '%s' NOT found (%s).", prefix, wanted, detail or "no reply")
            if allow_reboot and prayer and s["reboot_if_missing"]:
                self.reboot()
        return found

    # ── for the web page ────────────────────────────────────────────────

    def snapshot(self, now=None):
        now = now or self.now()
        s = self.store.get()
        local_now = self.local(now)
        times = self.times()
        with self._lock:
            cache = dict(self._cache)
        today = local_now.date().isoformat()
        stale = bool(times) and cache.get("date") != today

        prayers, next_item = [], None
        events = {p: w for w, _, kind, p in self.events(now) if kind == "play"}
        for name in PRAYERS:
            cfg = s["prayers"][name]
            when = events.get(name)
            item = {"name": name, "time": times.get(name), "enabled": cfg["enabled"],
                    "offset": cfg["offset"],
                    "plays_at": self.local(when).strftime("%H:%M") if when else None,
                    "passed": bool(when and when <= now)}
            prayers.append(item)
            if when and when > now and next_item is None:
                next_item = {"name": name, "at": when.isoformat(), "tomorrow": False,
                             "seconds": int((when - now).total_seconds())}
        if next_item is None and events:
            name, when = min(events.items(), key=lambda kv: kv[1])
            when += timedelta(days=1)  # tomorrow's time is within a minute or two
            next_item = {"name": name, "at": when.isoformat(), "tomorrow": True,
                         "seconds": int((when - now).total_seconds())}

        pi_offset = now.astimezone().utcoffset()
        return {
            "now": local_now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": today,
            "timezone": cache.get("timezone") if times else None,
            "timezone_mismatch": bool(times and self._tz()
                                      and local_now.utcoffset() != pi_offset),
            "prayers": prayers,
            "next": next_item,
            "times_date": cache.get("date") if times else None,
            "times_stale": stale,
            "fetched_at": cache.get("fetched_at") if times else None,
            "fetch_error": self.fetch_error,
            "device": self.device_status,
        }
