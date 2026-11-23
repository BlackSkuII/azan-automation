"""Notifications about azans that failed to play.

An error is queued the moment a scheduled azan fails. It is handed over only
when the phone chosen in Settings (matched by its Wi-Fi MAC address) next asks
for it, and only once:

- the same error is never queued twice, and a delivered error is never sent
  again when the phone reconnects;
- anything still undelivered when the masjid's local day changes is dropped,
  because an azan from yesterday is no longer news.

Everything is kept in ``data/notifications.json`` so an error survives a
service restart (the phone may connect hours later).
"""

import logging
import threading
import uuid
from datetime import datetime

from azan import paths

log = logging.getLogger("azan")

MAX_ENTRIES = 50


class NotificationStore:
    """Thread-safe queue of notifications, saved on every change."""

    def __init__(self, path=None):
        self.path = path or paths.NOTIFICATION_FILE
        self._lock = threading.RLock()
        self._items = None  # loaded on first use

    # ── storage ─────────────────────────────────────────────────────────

    def _load(self):
        if self._items is not None:
            return
        saved = paths.read_json(self.path) or {}
        items = saved.get("notifications") if isinstance(saved, dict) else None
        self._items = [item for item in (items or [])
                       if isinstance(item, dict) and item.get("id") and item.get("date")]

    def _save(self):
        paths.write_json_atomic(
            self.path, {"notifications": self._items[-MAX_ENTRIES:]}, private=True)

    def _drop_other_days(self, today):
        kept = [item for item in self._items if item["date"] == today]
        changed = len(kept) != len(self._items)
        self._items = kept
        return changed

    # ── writing ─────────────────────────────────────────────────────────

    def record(self, kind, prayer, message, when, today=None):
        """Queue one notification; returns it, or None if nothing was added.

        A notification is identified by (day, kind, prayer), so the same
        failure — or a repeat of it after delivery — never queues twice.
        """
        with self._lock:
            self._load()
            date = today or when.date().isoformat()
            changed = self._drop_other_days(date)
            key = (date, kind, prayer)
            for item in self._items:
                if (item["date"], item["kind"], item["prayer"]) == key:
                    if changed:
                        self._save()
                    return None
            item = {
                "id": uuid.uuid4().hex[:12],
                "date": date,
                "at": when.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind,
                "prayer": prayer,
                "message": message,
                "delivered_at": None,
            }
            self._items.append(item)
            self._save()
            log.info("Notification queued for %s: %s", date, message)
            return item

    def record_failure(self, label, ok, message, when):
        """Queue a notification for a failed scheduled azan (not a test/stop)."""
        if ok or label == "Test" or message == "Stopped":
            return None
        prayer = label[:-5].strip() if label.endswith(" azan") else label
        return self.record("play", prayer, message, when)

    # ── reading ─────────────────────────────────────────────────────────

    def take_today(self, today):
        """Undelivered notifications for ``today``, marked as delivered.

        Called only for the chosen phone, so a second call (the phone
        reconnecting, or the page being reloaded) returns nothing.
        """
        with self._lock:
            self._load()
            changed = self._drop_other_days(today)
            taken = [dict(item) for item in self._items
                     if item["date"] == today and not item.get("delivered_at")]
            if taken:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ids = {item["id"] for item in taken}
                for item in self._items:
                    if item["id"] in ids:
                        item["delivered_at"] = stamp
                changed = True
                log.info("Notifications delivered: %d", len(taken))
            if changed:
                self._save()
            return taken

    def pending(self, today):
        """Undelivered notifications for ``today`` without marking them."""
        with self._lock:
            self._load()
            return [dict(item) for item in self._items
                    if item["date"] == today and not item.get("delivered_at")]
