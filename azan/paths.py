"""Where things live on disk.

Settings and other runtime state are kept in ``data/`` which is ignored by
Git, so they stay on the Raspberry Pi and survive ``git pull``.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("AZAN_DATA_DIR") or os.path.join(ROOT, "data")
AUDIO_DIR = os.environ.get("AZAN_AUDIO_DIR") or os.path.join(ROOT, "audio")
LOG_FILE = os.environ.get("AZAN_LOG_FILE") or os.path.join(ROOT, "azan.log")
STATIC_DIR = os.path.join(ROOT, "azan", "static")

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
TIMES_FILE = os.path.join(DATA_DIR, "times.json")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# Config files from version 1 (imported once, then left alone).
LEGACY_CONFIG_FILES = (
    os.path.join(ROOT, "config.yaml"),
    os.path.join(ROOT, "config.local.yaml"),
)


def write_json_atomic(path, data, private=False):
    """Write JSON so a power cut can never leave a half-written file."""
    import json

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default=None):
    import json

    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default
