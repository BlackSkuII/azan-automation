"""Small helpers for the machine we are running on."""

import logging
import re
import socket
import subprocess

log = logging.getLogger("azan")

MIN_UPTIME_BEFORE_REBOOT = 15 * 60  # never reboot-loop

_MAC_SEPARATED = re.compile(r"^[0-9a-f]{1,2}([:-][0-9a-f]{1,2}){5}$", re.IGNORECASE)
_MAC_PLAIN = re.compile(r"^[0-9a-f]{12}$", re.IGNORECASE)
_MAC_ANY = re.compile(r"([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})", re.IGNORECASE)


def normalize_mac(value):
    """``aa:bb:cc:dd:ee:ff`` for a MAC typed in any usual form, else None."""
    text = str(value or "").strip().replace("-", ":")
    if _MAC_PLAIN.match(text):
        text = ":".join(text[i:i + 2] for i in range(0, 12, 2))
    if not _MAC_SEPARATED.match(text):
        return None
    return ":".join(part.zfill(2) for part in text.split(":")).lower()


def mac_for_ip(ip):
    """The MAC address this machine has seen for ``ip``, or None.

    The neighbour table only holds addresses this machine has exchanged
    packets with — an HTTP request from the phone is exactly that, so the
    entry is there when the page asks.
    """
    if not ip:
        return None
    try:
        with open("/proc/net/arp") as f:
            next(f, None)  # header
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip and parts[2] != "0x0":
                    return normalize_mac(parts[3])
    except OSError:
        pass
    try:  # macOS / BSD, and Linux without /proc
        result = subprocess.run(["arp", "-n", ip], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _MAC_ANY.search(result.stdout or "")
    return normalize_mac(match.group(1)) if match else None


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
