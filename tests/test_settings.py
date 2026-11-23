import os
import tempfile
import unittest
from unittest import mock

from azan import paths, settings
from azan.settings import SettingsError, SettingsStore, validate

ANY_AUDIO = lambda name: True


class ValidateTests(unittest.TestCase):
    def test_accepts_and_normalises_good_values(self):
        clean = validate({"volume": "40", "latitude": "42.5", "ha_url": "http://ha:8123/",
                          "volume_after": "", "azan_file": "a.mp3",
                          "prayers": {"Fajr": {"enabled": False, "offset": "-3"}}},
                         audio_exists=ANY_AUDIO)
        self.assertEqual(clean["volume"], 40)
        self.assertEqual(clean["latitude"], 42.5)
        self.assertEqual(clean["ha_url"], "http://ha:8123")
        self.assertIsNone(clean["volume_after"])
        self.assertEqual(clean["prayers"], {"Fajr": {"enabled": False, "offset": -3}})

    def test_rejects_bad_values_with_field_names(self):
        bad = {"volume": 101, "latitude": 91, "school": 2, "ha_url": "ha.local",
               "reboot_if_missing": "yes", "volume_after": -1, "method": 1.5,
               "longitude": "nan", "azan_file": "../secret.mp3",
               "prayers": {"Asr": {"offset": 99}}}
        with self.assertRaises(SettingsError) as ctx:
            validate(bad, audio_exists=ANY_AUDIO)
        self.assertEqual(set(ctx.exception.errors), set(bad))

    def test_missing_audio_file_is_rejected(self):
        with self.assertRaises(SettingsError):
            validate({"azan_file": "nope.mp3"}, audio_exists=lambda name: False)

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(validate({"surprise": 1}), {})

    def test_setup_flag_must_be_a_bool(self):
        self.assertEqual(validate({"setup_complete": True}), {"setup_complete": True})
        with self.assertRaises(SettingsError) as ctx:
            validate({"setup_complete": "yes"})
        self.assertIn("setup_complete", ctx.exception.errors)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "settings.json")

    def test_changes_persist_and_file_is_private(self):
        store = SettingsStore(self.path)
        seen = []
        store.on_change(seen.append)
        store.update({"volume": 20, "prayers": {"Isha": {"enabled": False}}})
        self.assertEqual(seen, [["prayers", "volume"]])
        again = SettingsStore(self.path).get()
        self.assertEqual(again["volume"], 20)
        self.assertFalse(again["prayers"]["Isha"]["enabled"])
        self.assertEqual(again["prayers"]["Isha"]["offset"], 0)  # merged, not replaced
        self.assertTrue(again["prayers"]["Fajr"]["enabled"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_invalid_update_changes_nothing(self):
        store = SettingsStore(self.path)
        with self.assertRaises(SettingsError):
            store.update({"volume": 30, "fajr_volume": 500})
        self.assertEqual(store.get()["volume"], settings.DEFAULTS["volume"])

    def test_unchanged_update_does_not_notify(self):
        store = SettingsStore(self.path)
        seen = []
        store.on_change(seen.append)
        self.assertEqual(store.update({"volume": settings.DEFAULTS["volume"]}), [])
        self.assertEqual(seen, [])

    def test_corrupt_file_falls_back_to_defaults(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(SettingsStore(self.path).get(), settings.DEFAULTS)

    def test_one_bad_saved_value_does_not_discard_the_rest(self):
        paths.write_json_atomic(self.path, {"volume": 999, "device_name": "Kitchen"})
        got = SettingsStore(self.path).get()
        self.assertEqual(got["device_name"], "Kitchen")
        self.assertEqual(got["volume"], settings.DEFAULTS["volume"])

    def test_a_fresh_install_needs_the_browser_setup(self):
        self.assertFalse(SettingsStore(self.path).get()["setup_complete"])

    def test_settings_saved_before_the_wizard_are_already_set_up(self):
        paths.write_json_atomic(self.path, {"device_name": "Den", "volume": 30})
        store = SettingsStore(self.path)
        self.assertTrue(store.get()["setup_complete"])
        # The upgrade is written back, so it only happens once.
        self.assertTrue(paths.read_json(self.path)["setup_complete"])

    def test_an_unfinished_setup_stays_unfinished_across_restarts(self):
        paths.write_json_atomic(self.path, {"device_name": "Den", "setup_complete": False})
        self.assertFalse(SettingsStore(self.path).get()["setup_complete"])
        store = SettingsStore(self.path)
        store.update({"setup_complete": True})
        self.assertTrue(SettingsStore(self.path).get()["setup_complete"])


class LegacyImportTests(unittest.TestCase):
    V1 = ("masjid_name: Allston Brighton Islamic Center\nlatitude: 42.3601\n"
          "longitude: -71.0589\nmethod: 2   # ISNA\nschool: 1\n"
          "device_name: \"Living Room speaker\"\nazan_duration: 136\n"
          "fajr_volume: '35'\nvolume: '50'\nscan_before_minutes: 7\n"
          "azan_file: audio/azan1.mp3\nha_url: \"\"\n")

    def test_parse_flat_yaml(self):
        got = settings.parse_flat_yaml(self.V1)
        self.assertEqual(got["device_name"], "Living Room speaker")
        self.assertEqual(got["method"], "2")
        self.assertEqual(got["fajr_volume"], "35")
        self.assertNotIn("ha_url", got)

    def test_v1_config_is_imported_once(self):
        with tempfile.TemporaryDirectory() as d:
            old, local = os.path.join(d, "config.yaml"), os.path.join(d, "config.local.yaml")
            with open(old, "w") as f:
                f.write(self.V1)
            with open(local, "w") as f:
                f.write("ha_token: secret-token\n")
            target = os.path.join(d, "data", "settings.json")
            with mock.patch.object(paths, "SETTINGS_FILE", target), \
                 mock.patch.object(paths, "LEGACY_CONFIG_FILES", (old, local)), \
                 mock.patch.object(paths, "AUDIO_DIR", d):
                open(os.path.join(d, "azan1.mp3"), "w").close()
                got = SettingsStore(target).get()
            self.assertEqual(got["device_name"], "Living Room speaker")
            self.assertEqual((got["volume"], got["fajr_volume"]), (50, 35))
            self.assertEqual(got["precheck_minutes"], 7)
            self.assertEqual(got["azan_file"], "azan1.mp3")
            self.assertEqual(got["ha_token"], "secret-token")
            self.assertTrue(os.path.isfile(target))
            self.assertTrue(got["setup_complete"])  # v1 users are not sent through setup

    def test_city_based_config_keeps_masjid_defaults(self):
        patch = settings.from_legacy({"city": "Gurgaon", "method": "1", "volume": "80"})
        self.assertNotIn("method", patch)
        self.assertEqual(patch["fajr_volume"], "80")


if __name__ == "__main__":
    unittest.main()
