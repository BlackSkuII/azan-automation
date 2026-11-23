"""Settings stored on the device (data/settings.json), edited from the web UI."""

import copy
import logging
import os
import threading

from azan import PRAYERS, paths, system

log = logging.getLogger("azan")

DEFAULTS = {
    # Masjid location and calculation — the same query the masjid's own
    # website uses, so the azan fires at the published times.
    "masjid_name": "Allston Brighton Islamic Center",
    "latitude": 42.3601,
    "longitude": -71.0589,
    "method": 2,  # ISNA
    "school": 1,  # Hanafi
    # Speaker
    "device_name": "",
    "volume": 50,
    "fajr_volume": 35,
    "volume_after": None,  # None = put the speaker back to what it was
    # Audio
    "azan_file": "azan.mp3",
    "fajr_azan_file": "fajr_azan.mp3",
    "end_buffer_seconds": 5,
    # Speaker check before each prayer (0 = off)
    "precheck_minutes": 5,
    "reboot_if_missing": True,
    # Home Assistant TV pause/resume (optional)
    "ha_url": "",
    "ha_token": "",
    "tv_entity_id": "",
    # Set when the first-run setup in the web page is finished. A device that
    # already has a settings file is treated as set up (see SettingsStore.load).
    "setup_complete": False,
    # Tell this phone (its Wi-Fi MAC) when an azan fails to play
    "notify_mac": "",
    # Per-prayer switches; offset is minutes after (+) / before (-) the adhan time
    "prayers": {name: {"enabled": True, "offset": 0} for name in PRAYERS},
}

_INT_RANGES = {
    "method": (0, 99),
    "school": (0, 1),
    "volume": (0, 100),
    "fajr_volume": (0, 100),
    "end_buffer_seconds": (0, 60),
    "precheck_minutes": (0, 60),
}
_FLOAT_RANGES = {"latitude": (-90.0, 90.0), "longitude": (-180.0, 180.0)}
_STRINGS = {"masjid_name": 80, "device_name": 120, "ha_url": 200,
            "ha_token": 500, "tv_entity_id": 120}
_AUDIO_KEYS = ("azan_file", "fajr_azan_file")


class SettingsError(ValueError):
    """Raised with a {field: message} dict when a change is not valid."""

    def __init__(self, errors):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _to_int(value):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, float) and value != int(value):
        raise ValueError
    return int(str(value).strip()) if isinstance(value, str) else int(value)


def validate(patch, audio_exists=None):
    """Return a cleaned copy of ``patch``; raise SettingsError on bad values.

    Only keys present in ``patch`` are checked, so partial updates work.
    """
    if not isinstance(patch, dict):
        raise SettingsError({"_": "Expected an object"})
    if audio_exists is None:
        audio_exists = lambda name: os.path.isfile(os.path.join(paths.AUDIO_DIR, name))

    clean, errors = {}, {}
    for key, value in patch.items():
        try:
            if key in _INT_RANGES:
                lo, hi = _INT_RANGES[key]
                number = _to_int(value)
                if not lo <= number <= hi:
                    raise ValueError
                clean[key] = number
            elif key in _FLOAT_RANGES:
                lo, hi = _FLOAT_RANGES[key]
                number = float(value)
                if not lo <= number <= hi:  # also rejects NaN
                    raise ValueError
                clean[key] = number
            elif key == "volume_after":
                if value is None or value == "":
                    clean[key] = None
                else:
                    number = _to_int(value)
                    if not 0 <= number <= 100:
                        raise ValueError
                    clean[key] = number
            elif key == "notify_mac":
                text = str(value if value is not None else "").strip()
                if text:
                    mac = system.normalize_mac(text)
                    if mac is None:
                        errors[key] = "Must look like aa:bb:cc:dd:ee:ff"
                        continue
                    text = mac
                clean[key] = text
            elif key in ("reboot_if_missing", "setup_complete"):
                if not isinstance(value, bool):
                    raise ValueError
                clean[key] = value
            elif key in _STRINGS:
                text = str(value if value is not None else "").strip()
                if len(text) > _STRINGS[key]:
                    raise ValueError
                if key == "ha_url" and text:
                    if not text.startswith(("http://", "https://")):
                        errors[key] = "Must start with http:// or https://"
                        continue
                    text = text.rstrip("/")
                clean[key] = text
            elif key in _AUDIO_KEYS:
                name = os.path.basename(str(value))
                if not name or name != value or not audio_exists(name):
                    errors[key] = "Audio file not found"
                    continue
                clean[key] = name
            elif key == "prayers":
                clean[key] = _validate_prayers(value)
            # Unknown keys are ignored.
        except (ValueError, TypeError):
            errors[key] = _range_message(key)
    if errors:
        raise SettingsError(errors)
    return clean


def _validate_prayers(value):
    if not isinstance(value, dict):
        raise ValueError
    out = {}
    for name in PRAYERS:
        if name not in value:
            continue
        item = value[name]
        if not isinstance(item, dict):
            raise ValueError
        entry = {}
        if "enabled" in item:
            if not isinstance(item["enabled"], bool):
                raise ValueError
            entry["enabled"] = item["enabled"]
        if "offset" in item:
            offset = _to_int(item["offset"])
            if not -60 <= offset <= 60:
                raise ValueError
            entry["offset"] = offset
        out[name] = entry
    return out


def _range_message(key):
    if key in _INT_RANGES:
        return "Must be a whole number from %d to %d" % _INT_RANGES[key]
    if key in _FLOAT_RANGES:
        return "Must be a number from %g to %g" % _FLOAT_RANGES[key]
    if key == "volume_after":
        return "Must be empty or a whole number from 0 to 100"
    if key == "prayers":
        return "Offsets must be whole minutes from -60 to 60"
    return "Invalid value"


def _merge(base, patch):
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key == "prayers":
            for name, entry in value.items():
                merged["prayers"][name].update(entry)
        else:
            merged[key] = value
    return merged


# ── Import of version 1 config.yaml ─────────────────────────────────────

def parse_flat_yaml(text):
    """Parse the simple ``key: value`` files version 1 wrote (no nesting)."""
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value[:1] in ("'", '"'):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            value = value.split(" #")[0].strip()
        if value in ("", "null", "~"):
            continue
        result[key.strip()] = value
    return result


def from_legacy(old):
    """Translate version 1 keys into a patch for the new settings."""
    patch = {}
    for key in ("masjid_name", "latitude", "longitude", "method", "school",
                "device_name", "volume", "fajr_volume", "ha_url", "ha_token",
                "tv_entity_id"):
        if key in old:
            patch[key] = old[key]
    if "volume" in old and "fajr_volume" not in old:
        patch["fajr_volume"] = old["volume"]  # v1: Fajr followed the main volume
    if "scan_before_minutes" in old:
        patch["precheck_minutes"] = old["scan_before_minutes"]
    for key in _AUDIO_KEYS:
        if key in old:
            patch[key] = os.path.basename(old[key])
    if "latitude" not in old or "longitude" not in old:
        # Very old city-based configs: keep the masjid defaults instead.
        for key in ("latitude", "longitude", "method", "school"):
            patch.pop(key, None)
    return patch


def _import_legacy():
    old = {}
    for path in paths.LEGACY_CONFIG_FILES:
        try:
            with open(path) as f:
                old.update(parse_flat_yaml(f.read()))
        except OSError:
            pass
    if not old:
        return None
    patch = from_legacy(old)
    clean = {}
    for key, value in patch.items():  # keep whatever is valid, drop the rest
        try:
            clean.update(validate({key: value}))
        except SettingsError as exc:
            log.warning("Old config value ignored (%s)", exc)
    return clean


class SettingsStore:
    """Thread-safe settings, saved to data/settings.json on every change."""

    def __init__(self, path=None):
        self.path = path or paths.SETTINGS_FILE
        self._lock = threading.Lock()
        self._listeners = []
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        saved = paths.read_json(self.path)
        with self._lock:
            if isinstance(saved, dict):
                try:
                    saved = validate(saved, audio_exists=lambda name: True)
                except SettingsError as exc:
                    log.warning("Ignoring invalid saved settings: %s", exc)
                    saved = {k: v for k, v in saved.items() if k not in exc.errors}
                    try:
                        saved = validate(saved, audio_exists=lambda name: True)
                    except SettingsError:
                        saved = {}
                # Settings were saved before the setup wizard existed, so this
                # device is already configured — do not send it through setup.
                upgraded = "setup_complete" not in saved
                if upgraded:
                    saved["setup_complete"] = True
                self._data = _merge(DEFAULTS, saved)
                if upgraded:
                    self._save()
                return
            imported = _import_legacy() if self.path == paths.SETTINGS_FILE else None
            if imported:
                imported["setup_complete"] = True  # a v1 config is already set up
                self._data = _merge(DEFAULTS, imported)
                self._save()
                log.info("Imported settings from the old config.yaml.")

    def _save(self):
        paths.write_json_atomic(self.path, self._data, private=True)

    def get(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, patch):
        clean = validate(patch)
        with self._lock:
            before = self._data
            self._data = _merge(before, clean)
            changed = sorted(k for k in clean if before.get(k) != self._data.get(k))
            if changed:
                self._save()
        if changed:
            shown = [k for k in changed if k != "ha_token"]
            log.info("Settings changed: %s", ", ".join(shown) or "ha_token")
            for listener in list(self._listeners):
                listener(changed)
        return changed

    def on_change(self, listener):
        self._listeners.append(listener)
