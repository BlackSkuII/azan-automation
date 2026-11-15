"""Small helpers for the machine we are running on."""

import logging
import socket
import subprocess

log = logging.getLogger("azan")

MIN_UPTIME_BEFORE_REBOOT = 15 * 60  # never reboot-loop


def is_pi():
    try:
        with open("/proc/device-tree/model") as f:
            return "raspberry" in f.read().lower()
    except OSError:
        return False


def uptime_seconds():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def reboot():
    """Reboot the Pi. Returns True if a reboot was actually requested."""
    if not is_pi():
        log.info("Reboot requested, but this is not a Raspberry Pi — skipping.")
        return False
    up = uptime_seconds()
    if up is not None and up < MIN_UPTIME_BEFORE_REBOOT:
        log.info("Reboot skipped: the Pi only booted %d min ago.", up // 60)
        return False
    log.warning("Rebooting the Pi now.")
    subprocess.Popen(["sudo", "-n", "reboot"])
    return True


def local_ip():
    """Best guess at this machine's LAN address (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
