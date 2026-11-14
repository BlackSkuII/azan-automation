import unittest
from unittest.mock import patch

from azan import scheduler


class SchedulerVolumeTests(unittest.TestCase):
    def jobs(self, cfg):
        with patch.object(scheduler, "get_venv_python", return_value="python"), \
             patch.object(scheduler, "project_root", return_value="/azan"):
            return scheduler.generate_cron_jobs(cfg, {"Fajr": "05:12", "Dhuhr": "12:30"})

    def test_separate_fajr_volume(self):
        jobs = self.jobs({"volume": "40", "fajr_volume": "20"})
        self.assertIn("play_azan.py 20 fajr", jobs[1])
        self.assertIn("play_azan.py 40 >>", jobs[3])

    def test_missing_or_null_fajr_volume_falls_back(self):
        for cfg in ({"volume": "40"}, {"volume": "40", "fajr_volume": None}):
            with self.subTest(cfg=cfg):
                self.assertIn("play_azan.py 40 fajr", self.jobs(cfg)[1])

    def test_zero_fajr_volume_is_not_treated_as_missing(self):
        self.assertIn("play_azan.py 0 fajr", self.jobs({"volume": "40", "fajr_volume": 0})[1])


if __name__ == "__main__":
    unittest.main()
