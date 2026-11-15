"""Azan audio files in the audio/ folder."""

import os
import re

from azan import paths

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_duration_cache = {}


class AudioError(ValueError):
    pass


def safe_name(name):
    """Reduce an uploaded filename to something safe; must end in .mp3."""
    name = os.path.basename(str(name).replace("\\", "/")).strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
    if not name.lower().endswith(".mp3") or len(name) <= 4:
        raise AudioError("Only .mp3 files are supported")
    return name[:80]


def path_for(name):
    if not name or os.path.basename(name) != name:
        raise AudioError("Invalid file name")
    return os.path.join(paths.AUDIO_DIR, name)


def duration(path):
    """Length of an MP3 in seconds, or None if it cannot be read."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _duration_cache:
        try:
            from mutagen.mp3 import MP3
            _duration_cache[key] = round(float(MP3(path).info.length), 1)
        except Exception:
            _duration_cache[key] = None
    return _duration_cache[key]


def list_files():
    try:
        names = sorted(os.listdir(paths.AUDIO_DIR), key=str.lower)
    except OSError:
        return []
    files = []
    for name in names:
        full = os.path.join(paths.AUDIO_DIR, name)
        if name.lower().endswith(".mp3") and os.path.isfile(full):
            files.append({"name": name, "size": os.path.getsize(full),
                          "duration": duration(full)})
    return files


def save_upload(name, stream, length):
    name = safe_name(name)
    if length <= 0:
        raise AudioError("The file is empty")
    if length > MAX_UPLOAD_BYTES:
        raise AudioError("File is too large (25 MB maximum)")
    os.makedirs(paths.AUDIO_DIR, exist_ok=True)
    final = os.path.join(paths.AUDIO_DIR, name)
    tmp = final + ".part"
    remaining = length
    try:
        with open(tmp, "wb") as f:
            while remaining > 0:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise AudioError("Upload was interrupted")
                f.write(chunk)
                remaining -= len(chunk)
        if duration(tmp) is None:
            raise AudioError("That does not look like a playable MP3 file")
        os.replace(tmp, final)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return name


def delete(name, in_use=()):
    full = path_for(name)
    if name in in_use:
        raise AudioError("This file is selected in Settings — choose another first")
    if not os.path.isfile(full):
        raise AudioError("File not found")
    os.remove(full)
