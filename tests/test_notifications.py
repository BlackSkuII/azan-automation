import os
import tempfile
import unittest
from datetime import datetime

from azan.notifications import NotificationStore


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "notifications.json")

    def store(self):
        return NotificationStore(self.path)

    def failure(self, store, prayer="Fajr", when=None, message="speaker did not respond"):
        return store.record_failure("%s azan" % prayer, False, message,
                                    when or datetime(2026, 11, 23, 5, 12, 40))

    def test_a_failed_azan_is_delivered_once(self):
        store = self.store()
        item = self.failure(store)
        self.assertEqual((item["kind"], item["prayer"]), ("play", "Fajr"))
        self.assertEqual(item["date"], "2026-11-23")
        delivered = store.take_today("2026-11-23")
        self.assertEqual([n["message"] for n in delivered], ["speaker did not respond"])
        # The phone reconnecting, or the page reloading, gets nothing new.
        self.assertEqual(store.take_today("2026-11-23"), [])
        self.assertEqual(self.store().take_today("2026-11-23"), [])
        self.assertEqual(store.pending("2026-11-23"), [])

    def test_a_success_a_stop_or_a_test_does_not_queue_anything(self):
        store = self.store()
        when = datetime(2026, 11, 23, 5, 0)
        self.assertIsNone(store.record_failure("Fajr azan", True, "Played", when))
        self.assertIsNone(store.record_failure("Fajr azan", False, "Stopped", when))
        self.assertIsNone(store.record_failure("Test", False, "boom", when))
        self.assertEqual(store.take_today("2026-11-23"), [])

    def test_the_same_error_is_never_queued_twice(self):
        store = self.store()
        self.assertIsNotNone(self.failure(store))
        self.assertIsNone(self.failure(store))  # a retry logging the same failure
        self.assertEqual(len(store.take_today("2026-11-23")), 1)
        # A repeat after delivery does not resurrect it either.
        self.assertIsNone(self.failure(store))
        self.assertEqual(store.pending("2026-11-23"), [])

    def test_different_prayers_queue_separately(self):
        store = self.store()
        self.failure(store, "Fajr")
        self.failure(store, "Maghrib", when=datetime(2026, 11, 23, 16, 24))
        taken = store.take_today("2026-11-23")
        self.assertEqual(sorted(n["prayer"] for n in taken), ["Fajr", "Maghrib"])

    def test_an_undelivered_notification_expires_with_the_day(self):
        store = self.store()
        self.failure(store)
        # The phone only connects the next day: nothing is sent for it.
        self.assertEqual(store.take_today("2026-11-24"), [])
        with open(self.path) as f:
            self.assertNotIn("Fajr", f.read())
        # A failure on the new day is queued and delivered normally.
        self.failure(store, "Dhuhr", when=datetime(2026, 11, 24, 11, 29))
        self.assertEqual([n["prayer"] for n in store.take_today("2026-11-24")], ["Dhuhr"])

    def test_the_queue_survives_a_restart(self):
        self.failure(self.store())
        self.assertEqual([n["prayer"] for n in self.store().take_today("2026-11-23")],
                         ["Fajr"])

    def test_pending_does_not_mark_anything_delivered(self):
        store = self.store()
        self.failure(store)
        self.assertEqual(len(store.pending("2026-11-23")), 1)
        self.assertEqual(len(store.take_today("2026-11-23")), 1)

    def test_a_corrupt_file_is_treated_as_empty(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        store = self.store()
        self.assertEqual(store.pending("2026-11-23"), [])
        self.assertIsNotNone(self.failure(store))


if __name__ == "__main__":
    unittest.main()
