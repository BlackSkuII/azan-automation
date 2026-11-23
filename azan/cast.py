"""Thin wrapper around the ``catt`` command-line tool (Chromecast control)."""

import json
import os
import re
import shutil
import subprocess
import sys

from azan import paths


class CastError(RuntimeError):
    pass


def catt_path():
    candidates = [
        os.environ.get("AZAN_CATT"),
        os.path.join(os.path.dirname(sys.executable), "catt"),
        os.path.join(paths.ROOT, "venv", "bin", "catt"),
        shutil.which("catt"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise CastError("catt is not installed — run ./install.sh")


def _run(args, timeout=30):
    try:
        return subprocess.run([catt_path()] + list(args), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CastError(f"catt {args[-1] if args else ''} timed out") from exc
    except OSError as exc:
        raise CastError(f"Could not run catt: {exc}") from exc


def _error_text(result):
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return lines[-1].replace("Error: ", "") if lines else f"exit code {result.returncode}"


def parse_scan_json(text):
    data = json.loads(text)
    devices = []
    for name, info in data.items():
        devices.append({
            "name": info.get("friendly_name") or name,
            "ip": str(info.get("host") or ""),
            "model": " ".join(x for x in (info.get("manufacturer"), info.get("model_name")) if x),
        })
    return devices


def parse_scan_text(text):
    """Parse ``ip - name - model`` lines printed by ``catt scan``."""
    devices = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(" - ")]
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F.:]+", parts[0]):
            devices.append({"name": parts[1], "ip": parts[0],
                            "model": " - ".join(parts[2:])})
    return devices


def scan():
    """Find speakers on the network. Returns [{name, ip, model}]."""
    result = _run(["scan", "-j"], timeout=45)
    if result.returncode == 0:
        try:
            return sorted(parse_scan_json(result.stdout), key=lambda d: d["name"].lower())
        except (ValueError, AttributeError):
            pass
    result = _run(["scan"], timeout=45)
    if result.returncode != 0 and "No devices found" not in (result.stderr + result.stdout):
        raise CastError(_error_text(result))
    return sorted(parse_scan_text(result.stdout), key=lambda d: d["name"].lower())


def matches(device, wanted):
    """True if a scanned device is the one named (or addressed) in settings."""
    wanted = (wanted or "").strip().lower()
    return bool(wanted) and wanted in (device["name"].strip().lower(), device["ip"].lower())


def get_volume(device):
    """Current speaker volume 0-100, or None if it cannot be read."""
    try:
        result = _run(["-d", device, "status"], timeout=25)
    except CastError:
        return None
    match = re.search(r"^Volume:\s*(\d+)", result.stdout, re.MULTILINE)
    return int(match.group(1)) if result.returncode == 0 and match else None


def set_volume(device, level):
    result = _run(["-d", device, "volume", str(int(level))], timeout=25)
    if result.returncode != 0:
        raise CastError(_error_text(result))


def stop(device):
    try:
        _run(["-d", device, "stop"], timeout=25)
    except CastError:
        pass


def start_cast(device, audio_path):
    """Start casting a local file. catt keeps running until playback ends."""
    try:
        return subprocess.Popen(
            [catt_path(), "-d", device, "cast", audio_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except OSError as exc:
        raise CastError(f"Could not run catt: {exc}") from exc
