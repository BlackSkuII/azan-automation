import os
import tempfile
import unittest
from unittest import mock

import yaml
from azan import config


class ConfigFileTests(unittest.TestCase):
    def test_local_overrides_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = os.path.join(tmp, "config.yaml")
            local = os.path.join(tmp, "config.local.yaml")
            with open(shared, "w") as f:
                yaml.safe_dump({"volume": "40", "device_name": "Nest"}, f)
            with open(local, "w") as f:
                yaml.safe_dump({"ha_token": "secret", "volume": "50"}, f)
            with mock.patch.object(config, "CONFIG_FILE", shared), mock.patch.object(config, "LOCAL_CONFIG_FILE", local):
                self.assertEqual(config.load_config(), {"volume": "50", "device_name": "Nest", "ha_token": "secret"})

    def test_save_keeps_token_out_of_shared_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = os.path.join(tmp, "config.yaml")
            local = os.path.join(tmp, "config.local.yaml")
            with mock.patch.object(config, "CONFIG_FILE", shared), mock.patch.object(config, "LOCAL_CONFIG_FILE", local):
                config.save_config({"volume": "40", "ha_token": "secret"})
                with open(shared) as f:
                    self.assertEqual(yaml.safe_load(f), {"volume": "40"})
                with open(local) as f:
                    self.assertEqual(yaml.safe_load(f), {"ha_token": "secret"})
                self.assertEqual(os.stat(local).st_mode & 0o777, 0o600)
                self.assertEqual(config.load_config()["ha_token"], "secret")


if __name__ == "__main__":
    unittest.main()
