import os
import sys

import yaml

from azan.platform_utils import project_root

CONFIG_FILE = os.path.join(project_root(), "config.yaml")
LOCAL_CONFIG_FILE = os.path.join(project_root(), "config.local.yaml")
CONFIG_EXAMPLE = os.path.join(project_root(), "config.yaml.example")

DEFAULTS = {
    # Masjid location and calculation settings — these match the masjid's
    # website/app so the azan fires at the same times shown there.
    "masjid_name": "Allston Brighton Islamic Center",
    "latitude": 42.3601,
    "longitude": -71.0589,
    "method": 2,  # ISNA (North America)
    "school": 1,  # Hanafi
    "volume": "100",
    "scan_before_minutes": 5,
    "device_name": "",
    "azan_file": "audio/azan.mp3",
    "fajr_azan_file": "audio/fajr_azan.mp3",
    "azan_duration": 136,
    "fajr_azan_duration": 150,
    "log_file": "azan.log",
    "ha_url": "",
    "ha_token": "",
    "tv_entity_id": "",
}


def upgrade_legacy_config(cfg):
    """Bring old city-based configs in line with the masjid's settings.

    Earlier versions configured a city/country and defaulted to method=1
    (Karachi). Those configs have no latitude/longitude, so their times would
    not match the masjid. When we see that shape, switch the location and
    calculation settings to the masjid defaults (ISNA + Hanafi).
    """
    if not cfg:
        return cfg

    is_legacy = "latitude" not in cfg and ("city" in cfg or "country" in cfg)
    if not is_legacy:
        return cfg

    for key in ("masjid_name", "latitude", "longitude", "method", "school"):
        cfg[key] = DEFAULTS[key]
    return cfg


def load_config():
    """Load shared config, with optional local overrides taking precedence."""
    cfg = {}
    for path in (CONFIG_FILE, LOCAL_CONFIG_FILE):
        try:
            with open(path) as f:
                cfg.update(yaml.safe_load(f) or {})
        except FileNotFoundError:
            pass
    return upgrade_legacy_config(cfg)


def load_config_or_exit():
    """Load config or exit with error. Used by cron-triggered scripts."""
    cfg = load_config()
    if not cfg:
        print("ERROR: config.yaml not found. Run install.py first.")
        sys.exit(1)
    return cfg


def save_config(data):
    """Save shared settings separately from the Home Assistant token."""
    shared = {key: value for key, value in data.items() if key != "ha_token"}
    local = {}
    try:
        with open(LOCAL_CONFIG_FILE) as f:
            local = yaml.safe_load(f) or {}
    except FileNotFoundError:
        pass
    if "ha_token" in data:
        local["ha_token"] = data["ha_token"]
    if local:
        # Create private files with restrictive permissions from the start.
        fd = os.open(LOCAL_CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(local, f, default_flow_style=False, sort_keys=False)
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(shared, f, default_flow_style=False, sort_keys=False)


def get(config, key, default=None):
    """Get a config value, falling back to DEFAULTS then provided default."""
    if config.get(key) is not None:
        return config[key]
    return DEFAULTS.get(key, default)


def get_or_prompt(config, key, prompt_text, default=None):
    """Return config value if set, otherwise prompt user interactively."""
    existing = config.get(key)
    if existing is not None and existing != "":
        return existing

    default_display = default if default is not None else DEFAULTS.get(key, "")
    prompt = f"  {prompt_text}"
    if default_display:
        prompt += f" [{default_display}]"
    prompt += ": "

    value = input(prompt).strip()
    if not value and default_display is not None:
        value = str(default_display)
    return value
